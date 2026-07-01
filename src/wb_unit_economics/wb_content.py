from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
PRODUCT_CARDS_LIST_URL = (
    "https://content-api.wildberries.ru/content/v2/get/cards/list"
)
PRODUCT_CARDS_TRASH_URL = (
    "https://content-api.wildberries.ru/content/v2/get/cards/trash"
)
PRODUCT_CARDS_ENDPOINTS = {
    "active": PRODUCT_CARDS_LIST_URL,
    "trash": PRODUCT_CARDS_TRASH_URL,
}


@dataclass(frozen=True)
class WbSellerAccount:
    seller_account_id: str
    account_name: str
    api_key: str = field(repr=False)


@dataclass(frozen=True)
class WbContentSettings:
    accounts: tuple[WbSellerAccount, ...]
    timeout_seconds: float = 30.0

    @classmethod
    def from_env_file(
        cls,
        env_file: Path = Path(".env"),
        *,
        max_accounts: int = 10,
    ) -> WbContentSettings:
        values = _load_env_values(env_file)
        values.update(os.environ)
        accounts: list[WbSellerAccount] = []
        for index in range(1, max_accounts + 1):
            api_key = values.get(f"WB_ACCOUNT_{index}_API_KEY", "").strip()
            if not api_key:
                continue
            account_name = values.get(f"WB_ACCOUNT_{index}_NAME", "").strip()
            seller_account_id = f"WB_ACCOUNT_{index}"
            accounts.append(
                WbSellerAccount(
                    seller_account_id=seller_account_id,
                    account_name=account_name or seller_account_id,
                    api_key=api_key,
                )
            )
        if not accounts:
            raise WbContentConfigError("No WB_ACCOUNT_*_API_KEY variables configured")

        timeout_value = values.get("WB_TIMEOUT_SECONDS", "").strip()
        return cls(
            accounts=tuple(accounts),
            timeout_seconds=float(timeout_value) if timeout_value else 30.0,
        )


@dataclass(frozen=True)
class WbProductCardsPageResult:
    seller_account_id: str
    account_name: str
    cards_source: str
    page_index: int
    ok: bool
    card_count: int
    flat_row_count: int = 0
    raw_payload_hash: str = ""
    output_path: Path | None = None
    flat_output_path: Path | None = None
    status_code: int | None = None
    cursor: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class WbContentConfigError(ValueError):
    pass


class WbContentClient:
    """Small read-only client for WB Content product card list."""

    def __init__(
        self,
        account: WbSellerAccount,
        *,
        timeout_seconds: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._account = account
        self._client = httpx.Client(
            headers={
                "Authorization": account.api_key,
                "Content-Type": "application/json",
            },
            timeout=timeout_seconds,
            follow_redirects=True,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> WbContentClient:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_product_cards_page(
        self,
        *,
        endpoint_url: str,
        limit: int,
        locale: str = "ru",
        cursor: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], int]:
        payload = build_cards_list_request(limit=limit, cursor=cursor)
        response = self._client.post(
            endpoint_url,
            params={"locale": locale},
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("Unexpected WB product cards payload")
        return data, response.status_code


def build_cards_list_request(
    *,
    limit: int,
    cursor: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cursor_payload: dict[str, Any] = {"limit": limit}
    if cursor:
        if cursor.get("updatedAt"):
            cursor_payload["updatedAt"] = cursor["updatedAt"]
        if cursor.get("nmID"):
            cursor_payload["nmID"] = cursor["nmID"]
    return {
        "settings": {
            "sort": {"ascending": True},
            "filter": {"withPhoto": -1},
            "cursor": cursor_payload,
        }
    }


def export_wb_product_cards(
    settings: WbContentSettings,
    output_dir: Path,
    *,
    limit: int = 100,
    max_pages: int = 1,
    locale: str = "ru",
    include_trash: bool = False,
    request_delay_seconds: float = 0.65,
) -> list[WbProductCardsPageResult]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results: list[WbProductCardsPageResult] = []
    source_names = ["active"]
    if include_trash:
        source_names.append("trash")
    for account in settings.accounts:
        with WbContentClient(
            account,
            timeout_seconds=settings.timeout_seconds,
        ) as client:
            for source_name in source_names:
                cursor: dict[str, Any] | None = None
                page_index = 1
                endpoint_url = PRODUCT_CARDS_ENDPOINTS[source_name]
                while page_index <= max_pages:
                    result = export_product_cards_page(
                        client,
                        account,
                        output_dir,
                        cards_source=source_name,
                        endpoint_url=endpoint_url,
                        limit=limit,
                        locale=locale,
                        cursor=cursor,
                        page_index=page_index,
                    )
                    results.append(result)
                    if not result.ok or result.card_count < limit:
                        break
                    cursor = result.cursor
                    page_index += 1
                    time.sleep(request_delay_seconds)
    _write_manifest(
        output_dir / "manifest.json",
        results,
        limit=limit,
        max_pages=max_pages,
        locale=locale,
        include_trash=include_trash,
        request_delay_seconds=request_delay_seconds,
    )
    return results


def export_product_cards_page(
    client: WbContentClient,
    account: WbSellerAccount,
    output_dir: Path,
    *,
    cards_source: str,
    endpoint_url: str,
    limit: int,
    locale: str,
    cursor: dict[str, Any] | None,
    page_index: int,
) -> WbProductCardsPageResult:
    try:
        payload, status_code = client.fetch_product_cards_page(
            endpoint_url=endpoint_url,
            limit=limit,
            locale=locale,
            cursor=cursor,
        )
    except httpx.HTTPStatusError as exc:
        return WbProductCardsPageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            cards_source=cards_source,
            page_index=page_index,
            ok=False,
            card_count=0,
            status_code=exc.response.status_code,
            error=f"HTTP {exc.response.status_code}",
        )
    except (httpx.HTTPError, ValueError) as exc:
        return WbProductCardsPageResult(
            seller_account_id=account.seller_account_id,
            account_name=account.account_name,
            cards_source=cards_source,
            page_index=page_index,
            ok=False,
            card_count=0,
            error=exc.__class__.__name__,
        )

    cards = extract_product_cards(payload)
    flat_rows = flatten_product_cards(account, cards, cards_source=cards_source)
    payload_hash = raw_payload_hash(payload)
    output_prefix = (
        f"{account.seller_account_id.lower()}_{cards_source}_cards_page_{page_index}"
    )
    output_path = (
        output_dir
        / f"{output_prefix}.raw.json"
    )
    flat_output_path = (
        output_dir
        / f"{output_prefix}.flat.json"
    )
    _write_json(output_path, payload)
    _write_json_list(flat_output_path, flat_rows)
    return WbProductCardsPageResult(
        seller_account_id=account.seller_account_id,
        account_name=account.account_name,
        cards_source=cards_source,
        page_index=page_index,
        ok=True,
        card_count=len(cards),
        flat_row_count=len(flat_rows),
        raw_payload_hash=payload_hash,
        output_path=output_path,
        flat_output_path=flat_output_path,
        status_code=status_code,
        cursor=extract_cursor(payload),
    )


def extract_product_cards(payload: dict[str, Any]) -> list[dict[str, Any]]:
    cards = payload.get("cards")
    if isinstance(cards, list):
        return [item for item in cards if isinstance(item, dict)]
    return []


def extract_cursor(payload: dict[str, Any]) -> dict[str, Any]:
    cursor = payload.get("cursor")
    return cursor if isinstance(cursor, dict) else {}


def flatten_product_cards(
    account: WbSellerAccount,
    cards: list[dict[str, Any]],
    *,
    cards_source: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for card in cards:
        vendor_code = str(card.get("vendorCode", "")).lower()
        sizes = card.get("sizes")
        if not isinstance(sizes, list):
            sizes = []
        for size in sizes:
            if not isinstance(size, dict):
                continue
            skus = size.get("skus")
            if not isinstance(skus, list):
                skus = []
            for sku in skus:
                rows.append(
                    {
                        "seller_account_id": account.seller_account_id,
                        "account_name": account.account_name,
                        "cards_source": cards_source,
                        "nm_id": card.get("nmID"),
                        "imt_id": card.get("imtID"),
                        "nm_uuid": card.get("nmUUID"),
                        "subject_id": card.get("subjectID"),
                        "subject_name": card.get("subjectName"),
                        "brand": card.get("brand"),
                        "vendor_code": vendor_code,
                        "title": card.get("title"),
                        "tech_size": size.get("techSize"),
                        "barcode": str(sku),
                        "chrt_id": size.get("chrtID"),
                        "created_at": card.get("createdAt"),
                        "updated_at": card.get("updatedAt"),
                    }
                )
    return rows


def raw_payload_hash(payload: dict[str, Any]) -> str:
    content = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _write_manifest(
    path: Path,
    results: list[WbProductCardsPageResult],
    *,
    limit: int,
    max_pages: int,
    locale: str,
    include_trash: bool,
    request_delay_seconds: float,
) -> None:
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "wb_content_product_cards",
        "endpoints": PRODUCT_CARDS_ENDPOINTS,
        "read_boundary": "read-only POST product card list",
        "limit": limit,
        "max_pages": max_pages,
        "locale": locale,
        "include_trash": include_trash,
        "request_delay_seconds": request_delay_seconds,
        "results": [
            {
                "seller_account_id": item.seller_account_id,
                "account_name": item.account_name,
                "cards_source": item.cards_source,
                "page_index": item.page_index,
                "ok": item.ok,
                "card_count": item.card_count,
                "flat_row_count": item.flat_row_count,
                "status_code": item.status_code,
                "raw_payload_hash": item.raw_payload_hash,
                "output_file": item.output_path.name if item.output_path else None,
                "flat_output_file": (
                    item.flat_output_path.name if item.flat_output_path else None
                ),
                "cursor": item.cursor,
                "error": item.error,
            }
            for item in results
        ],
    }
    _write_json(path, manifest)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _write_json_list(path: Path, payload: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )


def _load_env_values(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key.strip()] = value
    return values
