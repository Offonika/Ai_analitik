from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from wb_unit_economics.contracts import AccountOrgMapping, MappingStatus, SkuMapping
from wb_unit_economics.onec_odata import extract_odata_rows

MOSCOW_TZ = ZoneInfo("Europe/Moscow")


@dataclass(frozen=True)
class OnecArticleCandidate:
    onec_item_id: str
    onec_article: str
    onec_name: str


@dataclass(frozen=True)
class OnecMarketplaceMappingRow:
    seller_account_id: str
    organization_id: str
    nm_id: int | None
    vendor_code: str
    barcode: str
    onec_item_id: str
    onec_article: str
    onec_characteristic: str
    status: MappingStatus
    confidence: str
    comment: str


def build_sku_mapping_from_articles(
    *,
    client_id: str,
    wb_card_rows: Iterable[Mapping[str, Any]],
    onec_barcode_rows: Iterable[Mapping[str, Any]],
    account_org_mapping: Iterable[AccountOrgMapping],
    nomenclature_rows: Iterable[Mapping[str, Any]] = (),
    updated_at: datetime | None = None,
) -> list[SkuMapping]:
    updated_at = updated_at or datetime.now(tz=MOSCOW_TZ)
    account_to_org = {
        item.seller_account_id: item.organization_id for item in account_org_mapping
    }
    article_index = _index_onec_articles(nomenclature_rows)
    mappings: list[SkuMapping] = []
    seen: set[tuple[str, int | None, str]] = set()

    for row in wb_card_rows:
        seller_account_id = _text(row.get("seller_account_id"))
        nm_id = _int_or_none(row.get("nm_id"))
        vendor_code = normalize_article(row.get("vendor_code"))
        key = (seller_account_id, nm_id, vendor_code)
        if key in seen:
            continue
        seen.add(key)
        candidates = article_index.get(vendor_code, []) if vendor_code else []
        status, confidence, candidate, comment = _match_status(
            nm_id,
            vendor_code,
            candidates,
        )
        mappings.append(
            SkuMapping(
                client_id=client_id,
                seller_account_id=seller_account_id,
                organization_id=account_to_org.get(seller_account_id, ""),
                nm_id=nm_id,
                vendor_code=vendor_code,
                barcode="",
                onec_item_id=candidate.onec_item_id if candidate else "",
                onec_article=candidate.onec_article if candidate else "",
                onec_characteristic="",
                match_method="article",
                confidence=confidence,
                status=status,
                comment=comment,
                updated_by="snapshot_builder",
                updated_at=updated_at,
            )
        )
    return mappings


def build_sku_mapping_from_onec_marketplace_files(
    *,
    client_id: str,
    mapping_dir: Path,
    account_org_mapping: Iterable[AccountOrgMapping],
    nomenclature_rows: Iterable[Mapping[str, Any]],
    updated_at: datetime | None = None,
) -> list[SkuMapping]:
    updated_at = updated_at or datetime.now(tz=MOSCOW_TZ)
    accounts = list(account_org_mapping)
    nomenclature_index = _nomenclature_lookup(nomenclature_rows)
    grouped_rows: dict[tuple[str, int | None, str], list[OnecMarketplaceMappingRow]] = (
        defaultdict(list)
    )
    for path in sorted(mapping_dir.glob("*.txt")):
        account = _match_account_for_file(path.name, accounts)
        if account is None:
            continue
        for row in _read_onec_marketplace_tsv(path):
            nm_id = _int_or_none(row["nm_id"])
            vendor_code = normalize_article(row["vendor_code"])
            candidates = _resolve_onec_mapping_candidates(row, nomenclature_index)
            grouped_rows[(account.seller_account_id, nm_id, vendor_code)].append(
                _marketplace_mapping_row(account, nm_id, vendor_code, candidates, row)
            )

    mappings = []
    for (
        seller_account_id,
        nm_id,
        vendor_code,
    ), rows in sorted(grouped_rows.items()):
        resolved = [
            row
            for row in rows
            if row.status in {MappingStatus.MATCHED, MappingStatus.AMBIGUOUS}
        ]
        if not resolved:
            selected = rows[0]
        else:
            item_ids = {row.onec_item_id for row in resolved if row.onec_item_id}
            if len(item_ids) == 1:
                selected = next(row for row in resolved if row.onec_item_id)
                selected = OnecMarketplaceMappingRow(
                    seller_account_id=selected.seller_account_id,
                    organization_id=selected.organization_id,
                    nm_id=selected.nm_id,
                    vendor_code=selected.vendor_code,
                    barcode="",
                    onec_item_id=selected.onec_item_id,
                    onec_article=selected.onec_article,
                    onec_characteristic="",
                    status=MappingStatus.MATCHED,
                    confidence="1",
                    comment="сопоставлено из модуля маркетплейса 1С",
                )
            else:
                selected = resolved[0]
                selected = OnecMarketplaceMappingRow(
                    seller_account_id=selected.seller_account_id,
                    organization_id=selected.organization_id,
                    nm_id=selected.nm_id,
                    vendor_code=selected.vendor_code,
                    barcode="",
                    onec_item_id=selected.onec_item_id,
                    onec_article=selected.onec_article,
                    onec_characteristic="",
                    status=MappingStatus.AMBIGUOUS,
                    confidence="0.5",
                    comment="разные номенклатуры 1С внутри одного товара WB",
                )
        mappings.append(
            SkuMapping(
                client_id=client_id,
                seller_account_id=seller_account_id,
                organization_id=selected.organization_id,
                nm_id=nm_id,
                vendor_code=vendor_code,
                barcode="",
                onec_item_id=selected.onec_item_id,
                onec_article=selected.onec_article,
                onec_characteristic=selected.onec_characteristic,
                match_method="onec_marketplace_mapping",
                confidence=selected.confidence,
                status=selected.status,
                comment=selected.comment,
                updated_by="1c_marketplace_export",
                updated_at=updated_at,
            )
        )
    mappings.extend(_sku_level_mappings(client_id, grouped_rows, updated_at))
    mappings.extend(_barcode_fallback_mappings(client_id, grouped_rows, updated_at))
    return mappings


def build_sku_mapping_from_barcodes(
    *,
    client_id: str,
    wb_card_rows: Iterable[Mapping[str, Any]],
    onec_barcode_rows: Iterable[Mapping[str, Any]],
    account_org_mapping: Iterable[AccountOrgMapping],
    nomenclature_rows: Iterable[Mapping[str, Any]] = (),
    updated_at: datetime | None = None,
) -> list[SkuMapping]:
    return build_sku_mapping_from_articles(
        client_id=client_id,
        wb_card_rows=wb_card_rows,
        onec_barcode_rows=onec_barcode_rows,
        nomenclature_rows=nomenclature_rows,
        account_org_mapping=account_org_mapping,
        updated_at=updated_at,
    )


def load_wb_card_flat_rows(cards_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(cards_dir.glob("*.flat.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            rows.extend(item for item in data if isinstance(item, dict))
    return rows


def load_onec_rows(sample_dir: Path, sample_id: str) -> list[dict[str, Any]]:
    path = sample_dir / f"{sample_id}.raw.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return [item for item in extract_odata_rows(payload) if isinstance(item, dict)]


def normalize_barcode(value: object) -> str:
    return _text(value)


def normalize_article(value: object) -> str:
    return _text(value).lower()


def normalize_name(value: object) -> str:
    return " ".join(_text(value).lower().split())


def has_onec_marketplace_mapping_files(path: Path) -> bool:
    return path.is_dir() and any(path.glob("*.txt"))


def _index_onec_articles(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[OnecArticleCandidate]]:
    index: dict[str, dict[str, OnecArticleCandidate]] = defaultdict(dict)
    for row in rows:
        item_id = _text(row.get("Ref_Key") or row.get("onec_item_id"))
        article = _text(row.get("Артикул") or row.get("article"))
        normalized_article = normalize_article(article)
        if not item_id or not normalized_article:
            continue
        candidate = OnecArticleCandidate(
            onec_item_id=item_id,
            onec_article=article or item_id,
            onec_name=_text(row.get("Description") or row.get("НаименованиеПолное")),
        )
        index[normalized_article][item_id] = candidate
    return {article: list(candidates.values()) for article, candidates in index.items()}


def _nomenclature_lookup(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, list[Mapping[str, Any]]]]:
    lookup: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        "article": defaultdict(list),
        "code": defaultdict(list),
        "name": defaultdict(list),
    }
    for row in rows:
        article = normalize_article(row.get("Артикул") or row.get("article"))
        code = _text(row.get("Code") or row.get("Код"))
        name = normalize_name(row.get("Description") or row.get("НаименованиеПолное"))
        if article:
            lookup["article"][article].append(row)
        if code:
            lookup["code"][code].append(row)
        if name:
            lookup["name"][name].append(row)
    return lookup


def _read_onec_marketplace_tsv(path: Path) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file, delimiter="\t")
        try:
            header = next(reader)
        except StopIteration:
            return rows
        normalized_header = [_normalized_header_name(item) for item in header]
        for values in reader:
            if "артикулпоставщика" in normalized_header:
                row = _read_onec_marketplace_vendor_article_row(
                    values,
                    normalized_header,
                )
            else:
                row = _read_onec_marketplace_nm_only_row(values, normalized_header)
            rows.append(row)
    return rows


def _value(values: list[str], index: int) -> str:
    return values[index].strip() if index < len(values) else ""


def _read_onec_marketplace_vendor_article_row(
    values: list[str],
    header: list[str],
) -> dict[str, str]:
    return {
        "wb_name": _header_value(values, header, "номенклатураwb", fallback=0),
        "vendor_code": _header_value(values, header, "артикулпоставщика", fallback=1),
        "nm_id": _header_value(values, header, "артикулwb", fallback=2),
        "wb_size": _header_value(values, header, "размерwb", fallback=3),
        "onec_name": _header_value(values, header, "номенклатура", fallback=4),
        "onec_code": _header_value(values, header, "код", fallback=5),
        "onec_article": _header_value(values, header, "артикул", fallback=7),
        "onec_barcode": _header_value(values, header, "штрихкод", fallback=8),
        "onec_characteristic": _header_value(
            values,
            header,
            "характеристика",
            fallback=10,
        ),
    }


def _read_onec_marketplace_nm_only_row(
    values: list[str],
    header: list[str],
) -> dict[str, str]:
    return {
        "wb_name": _header_value(values, header, "номенклатураwb", fallback=0),
        "vendor_code": "",
        "nm_id": _header_value(values, header, "артикулwb", fallback=1),
        "wb_size": _header_value(values, header, "размерwb", fallback=2),
        "onec_name": _header_value(values, header, "номенклатура", fallback=3),
        "onec_code": _header_value(values, header, "код", fallback=-1),
        "onec_article": _header_value(values, header, "артикул", fallback=-1),
        "onec_barcode": _header_value(values, header, "штрихкод", fallback=-1),
        "onec_characteristic": _header_value(
            values,
            header,
            "характеристика",
            fallback=4,
        ),
    }


def _header_value(
    values: list[str],
    header: list[str],
    name: str,
    *,
    fallback: int,
) -> str:
    try:
        index = header.index(name)
    except ValueError:
        index = fallback
    return _value(values, index) if index >= 0 else ""


def _normalized_header_name(value: str) -> str:
    return "".join(char for char in value.lower() if char.isalnum())


def _match_account_for_file(
    file_name: str,
    accounts: list[AccountOrgMapping],
) -> AccountOrgMapping | None:
    file_tokens = _significant_tokens(file_name)
    scored: list[tuple[int, AccountOrgMapping]] = []
    for account in accounts:
        org_tokens = _significant_tokens(account.organization_name)
        account_tokens = _significant_tokens(account.seller_account_name)
        score = len(file_tokens & org_tokens) * 2 + len(file_tokens & account_tokens)
        if score:
            scored.append((score, account))
    if not scored:
        return None
    scored.sort(key=lambda item: item[0], reverse=True)
    if len(scored) > 1 and scored[0][0] == scored[1][0]:
        return None
    return scored[0][1]


def _normalized_tokens(value: str) -> list[str]:
    cleaned = (
        value.lower()
        .replace(".", " ")
        .replace(",", " ")
        .replace("_", " ")
        .replace("-", " ")
    )
    return [token for token in cleaned.split() if token and token != "ип"]


def _significant_tokens(value: str) -> set[str]:
    return {token for token in _normalized_tokens(value) if len(token) >= 3}


def _resolve_onec_mapping_candidates(
    row: Mapping[str, str],
    nomenclature_lookup: Mapping[str, Mapping[str, list[Mapping[str, Any]]]],
) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    onec_code = _text(row.get("onec_code"))
    onec_article = normalize_article(row.get("onec_article"))
    if onec_code:
        candidates = list(nomenclature_lookup["code"].get(onec_code, []))
    if not candidates and onec_article:
        candidates = list(nomenclature_lookup["article"].get(onec_article, []))
    onec_name = normalize_name(row.get("onec_name"))
    if not candidates and onec_name:
        candidates = list(nomenclature_lookup["name"].get(onec_name, []))
    if onec_name and candidates:
        named_candidates = [
            candidate
            for candidate in candidates
            if normalize_name(
                candidate.get("Description") or candidate.get("НаименованиеПолное")
            )
            == onec_name
        ]
        if named_candidates:
            candidates = named_candidates
    return candidates


def _marketplace_mapping_row(
    account: AccountOrgMapping,
    nm_id: int | None,
    vendor_code: str,
    candidates: list[Mapping[str, Any]],
    row: Mapping[str, str],
) -> OnecMarketplaceMappingRow:
    mapping_value = row.get("onec_name") or row.get("onec_article") or row.get(
        "onec_code"
    )
    if not _text(mapping_value):
        return OnecMarketplaceMappingRow(
            account.seller_account_id,
            account.organization_id,
            nm_id,
            vendor_code,
            _text(row.get("wb_size")),
            "",
            "",
            "",
            MappingStatus.MISSING,
            "0",
            "нет сопоставления в выгрузке 1С",
        )
    if len(candidates) == 1:
        candidate = candidates[0]
        return OnecMarketplaceMappingRow(
            account.seller_account_id,
            account.organization_id,
            nm_id,
            vendor_code,
            _text(row.get("wb_size")),
            _text(candidate.get("Ref_Key")),
            _text(candidate.get("Артикул") or row.get("onec_article")),
            "",
            MappingStatus.MATCHED,
            "1",
            "сопоставлено из модуля маркетплейса 1С",
        )
    if len(candidates) > 1:
        candidate = sorted(candidates, key=lambda item: _text(item.get("Ref_Key")))[0]
        return OnecMarketplaceMappingRow(
            account.seller_account_id,
            account.organization_id,
            nm_id,
            vendor_code,
            _text(row.get("wb_size")),
            _text(candidate.get("Ref_Key")),
            _text(candidate.get("Артикул") or row.get("onec_article")),
            "",
            MappingStatus.AMBIGUOUS,
            "0.5",
            "несколько номенклатур 1С по выгрузке маркетплейса",
        )
    return OnecMarketplaceMappingRow(
        account.seller_account_id,
        account.organization_id,
        nm_id,
        vendor_code,
        _text(row.get("wb_size")),
        "",
        _text(row.get("onec_article")),
        "",
        MappingStatus.MISSING,
        "0",
        "номенклатура из выгрузки не найдена в справочнике 1С",
    )


def _barcode_fallback_mappings(
    client_id: str,
    grouped_rows: Mapping[tuple[str, int | None, str], list[OnecMarketplaceMappingRow]],
    updated_at: datetime,
) -> list[SkuMapping]:
    barcode_groups: dict[tuple[str, str], list[OnecMarketplaceMappingRow]] = (
        defaultdict(list)
    )
    for rows in grouped_rows.values():
        for row in rows:
            if row.barcode:
                barcode_groups[(row.seller_account_id, row.barcode)].append(row)

    mappings = []
    for (seller_account_id, barcode), rows in sorted(barcode_groups.items()):
        resolved = [
            row
            for row in rows
            if row.onec_item_id and row.status is MappingStatus.MATCHED
        ]
        if not resolved:
            continue
        item_ids = {row.onec_item_id for row in resolved}
        selected = resolved[0]
        if len(item_ids) == 1:
            status = MappingStatus.MATCHED
            confidence = "1"
            comment = (
                "fallback по Размер WB/SKU из выгрузки 1С для строк WB без nmId"
            )
        else:
            status = MappingStatus.AMBIGUOUS
            confidence = "0.5"
            comment = "один Размер WB/SKU ведет к разным номенклатурам 1С"
        mappings.append(
            SkuMapping(
                client_id=client_id,
                seller_account_id=seller_account_id,
                organization_id=selected.organization_id,
                nm_id=0,
                vendor_code="",
                barcode=barcode,
                onec_item_id=selected.onec_item_id,
                onec_article=selected.onec_article,
                onec_characteristic="",
                match_method="onec_marketplace_mapping_sku_fallback",
                confidence=confidence,
                status=status,
                comment=comment,
                updated_by="1c_marketplace_export",
                updated_at=updated_at,
            )
        )
    return mappings


def _sku_level_mappings(
    client_id: str,
    grouped_rows: Mapping[tuple[str, int | None, str], list[OnecMarketplaceMappingRow]],
    updated_at: datetime,
) -> list[SkuMapping]:
    sku_groups: dict[
        tuple[str, int | None, str, str], list[OnecMarketplaceMappingRow]
    ] = defaultdict(list)
    for (seller_account_id, nm_id, vendor_code), rows in grouped_rows.items():
        for row in rows:
            if row.barcode:
                sku_groups[(seller_account_id, nm_id, vendor_code, row.barcode)].append(
                    row
                )

    mappings = []
    for (
        seller_account_id,
        nm_id,
        vendor_code,
        barcode,
    ), rows in sorted(sku_groups.items()):
        selected = _select_sku_row(rows)
        if selected is None:
            continue
        mappings.append(
            SkuMapping(
                client_id=client_id,
                seller_account_id=seller_account_id,
                organization_id=selected.organization_id,
                nm_id=nm_id,
                vendor_code=vendor_code,
                barcode=barcode,
                onec_item_id=selected.onec_item_id,
                onec_article=selected.onec_article,
                onec_characteristic="",
                match_method="onec_marketplace_mapping_sku",
                confidence=selected.confidence,
                status=selected.status,
                comment=selected.comment,
                updated_by="1c_marketplace_export",
                updated_at=updated_at,
            )
        )
    return mappings


def _select_sku_row(
    rows: list[OnecMarketplaceMappingRow],
) -> OnecMarketplaceMappingRow | None:
    resolved = [row for row in rows if row.onec_item_id]
    if not resolved:
        return rows[0] if rows else None
    item_ids = {row.onec_item_id for row in resolved}
    selected = resolved[0]
    if len(item_ids) == 1:
        return OnecMarketplaceMappingRow(
            seller_account_id=selected.seller_account_id,
            organization_id=selected.organization_id,
            nm_id=selected.nm_id,
            vendor_code=selected.vendor_code,
            barcode=selected.barcode,
            onec_item_id=selected.onec_item_id,
            onec_article=selected.onec_article,
            onec_characteristic="",
            status=MappingStatus.MATCHED,
            confidence="1",
            comment="сопоставлено из модуля маркетплейса 1С по Размер WB/SKU",
        )
    return OnecMarketplaceMappingRow(
        seller_account_id=selected.seller_account_id,
        organization_id=selected.organization_id,
        nm_id=selected.nm_id,
        vendor_code=selected.vendor_code,
        barcode=selected.barcode,
        onec_item_id=selected.onec_item_id,
        onec_article=selected.onec_article,
        onec_characteristic="",
        status=MappingStatus.AMBIGUOUS,
        confidence="0.5",
        comment="один Размер WB/SKU ведет к разным номенклатурам 1С",
    )


def _match_status(
    nm_id: int | None,
    vendor_code: str,
    candidates: list[OnecArticleCandidate],
) -> tuple[MappingStatus, str, OnecArticleCandidate | None, str]:
    if nm_id is None:
        return MappingStatus.MISSING, "0", None, "не заполнен nmId WB"
    if not vendor_code:
        return MappingStatus.MISSING, "0", None, "не заполнен артикул WB"
    if not candidates:
        return (
            MappingStatus.MISSING,
            "0",
            None,
            "артикул WB не найден в артикулах 1С",
        )
    if len(candidates) > 1:
        return (
            MappingStatus.AMBIGUOUS,
            "0.5",
            sorted(candidates, key=lambda item: item.onec_item_id)[0],
            "артикул 1С найден в нескольких номенклатурах",
        )
    return MappingStatus.MATCHED, "1", candidates[0], "сопоставлено по nmId + артикулу"


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _int_or_none(value: object) -> int | None:
    text = _text(value)
    return int(text) if text else None
