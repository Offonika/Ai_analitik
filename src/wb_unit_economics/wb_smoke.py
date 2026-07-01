from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class WbSmokeResult:
    account_name: str
    endpoint: str
    status_code: int | None
    ok: bool
    error: str = ""


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return f"{value[:4]}...{value[-4:]}"


def smoke_check_get(
    *,
    account_name: str,
    api_key: str,
    endpoint: str,
    timeout_seconds: float = 20.0,
) -> WbSmokeResult:
    """Run a read-only WB GET smoke check without exposing the API key."""
    headers = {"Authorization": api_key}
    try:
        response = httpx.get(endpoint, headers=headers, timeout=timeout_seconds)
    except httpx.HTTPError as exc:
        return WbSmokeResult(
            account_name=account_name,
            endpoint=endpoint,
            status_code=None,
            ok=False,
            error=exc.__class__.__name__,
        )
    return WbSmokeResult(
        account_name=account_name,
        endpoint=endpoint,
        status_code=response.status_code,
        ok=200 <= response.status_code < 300,
    )
