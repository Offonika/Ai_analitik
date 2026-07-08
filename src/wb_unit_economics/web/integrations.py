from __future__ import annotations

import base64
import binascii
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from wb_unit_economics.onec_odata import OnecODataSettings
from wb_unit_economics.ozon import OzonConfigError, ozon_settings_from_secret
from wb_unit_economics.web import providers, security
from wb_unit_economics.web.settings import WebSettings

WB_FINANCE_PING_URL = "https://finance-api.wildberries.ru/ping"
OZON_SELLER_INFO_URL = "https://api-seller.ozon.ru/v1/seller/info"
OZON_CASH_FLOW_CHECK_URL = (
    "https://api-seller.ozon.ru/v1/finance/cash-flow-statement/list"
)
OZON_STOCK_CHECK_URL = (
    "https://api-seller.ozon.ru/v2/analytics/stock_on_warehouses"
)


@dataclass(frozen=True)
class SecretStorageResult:
    storage: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class IntegrationCheckResult:
    status: str
    message: str
    payload: dict[str, Any]


class IntegrationSecretError(ValueError):
    pass


def secret_storage_payload(settings: WebSettings, secret: str) -> SecretStorageResult:
    normalized = secret.strip()
    if not normalized:
        raise ValueError("integration secret is required")
    fernet = _fernet_or_none(settings)
    if fernet is None:
        return SecretStorageResult(
            storage="hash_only",
            payload={
                "storage": "hash_only",
                "readOnly": True,
                "storageReady": False,
                "storageReason": "integration_secret_key_missing_or_invalid",
            },
        )
    token = fernet.encrypt(normalized.encode("utf-8")).decode("ascii")
    return SecretStorageResult(
        storage="encrypted",
        payload={
            "storage": "encrypted",
            "secretCiphertext": token,
            "readOnly": True,
            "storageReady": True,
        },
    )


def decrypt_secret(settings: WebSettings, config_payload: dict[str, Any]) -> str:
    if config_payload.get("storage") != "encrypted":
        raise IntegrationSecretError("secret_storage_is_not_encrypted")
    ciphertext = str(config_payload.get("secretCiphertext") or "")
    if not ciphertext:
        raise IntegrationSecretError("secret_ciphertext_missing")
    fernet = _fernet_or_none(settings)
    if fernet is None:
        raise IntegrationSecretError("integration_secret_key_missing_or_invalid")
    try:
        return fernet.decrypt(ciphertext.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError) as exc:
        raise IntegrationSecretError("secret_decryption_failed") from exc


def onec_odata_settings_from_secret(secret: str) -> OnecODataSettings:
    config = _parse_onec_secret(secret)
    return OnecODataSettings(
        base_url=config["base_url"],
        username=config["username"],
        password=config["password"],
        verify_ssl=config["verify_ssl"],
    )


def run_provider_check(
    settings: WebSettings,
    *,
    provider: str,
    secret: str,
) -> IntegrationCheckResult:
    definition = providers.provider_definition(provider)
    handlers = {
        "wb_api": _check_wb_api,
        "onec_readonly": _check_onec_readonly,
        "ozon_api": _check_ozon_api,
    }
    handler = handlers.get(definition.check_handler)
    if handler is not None:
        return handler(settings, secret)
    raise ValueError(f"unsupported integration provider: {provider}")


def _check_wb_api(settings: WebSettings, secret: str) -> IntegrationCheckResult:
    checked_at = security.utcnow().isoformat()
    try:
        with httpx.Client(
            headers={"Authorization": secret},
            timeout=settings.integration_check_timeout_seconds,
            follow_redirects=True,
        ) as client:
            response = client.get(WB_FINANCE_PING_URL)
    except httpx.HTTPError as exc:
        return IntegrationCheckResult(
            status="check_failed",
            message="WB API не ответил на read-only ping.",
            payload={
                "provider": "wb_api",
                "checkedAt": checked_at,
                "checkMode": "live_read_only",
                "endpointCategory": "finance_ping",
                "errorType": exc.__class__.__name__,
            },
        )
    payload: dict[str, Any] = {
        "provider": "wb_api",
        "checkedAt": checked_at,
        "checkMode": "live_read_only",
        "endpointCategory": "finance_ping",
        "httpStatus": response.status_code,
    }
    if response.status_code == 200:
        return IntegrationCheckResult(
            status="check_ok",
            message="WB Finance ping прошел, токен принят read-only проверкой.",
            payload=payload,
        )
    if response.status_code == 429:
        return IntegrationCheckResult(
            status="check_failed",
            message="WB ограничил частоту ping. Повторите проверку позже.",
            payload=payload,
        )
    return IntegrationCheckResult(
        status="check_failed",
        message=(
            "WB не принял токен для Finance ping. Проверьте срок действия, "
            "категорию Finance и режим read-only."
        ),
        payload=payload,
    )


def _check_onec_readonly(
    settings: WebSettings, secret: str
) -> IntegrationCheckResult:
    checked_at = security.utcnow().isoformat()
    config = _parse_onec_secret(secret)
    metadata_url = config["base_url"].rstrip("/") + "/$metadata"
    try:
        with httpx.Client(
            auth=(config["username"], config["password"]),
            headers={"Accept": "application/xml, application/json"},
            timeout=settings.integration_check_timeout_seconds,
            verify=config["verify_ssl"],
            follow_redirects=True,
        ) as client:
            response = client.get(metadata_url)
    except httpx.HTTPError as exc:
        return IntegrationCheckResult(
            status="check_failed",
            message="1С OData не ответила на read-only metadata check.",
            payload={
                "provider": "onec_readonly",
                "checkedAt": checked_at,
                "checkMode": "live_read_only",
                "endpointCategory": "odata_metadata",
                "errorType": exc.__class__.__name__,
            },
        )
    payload = {
        "provider": "onec_readonly",
        "checkedAt": checked_at,
        "checkMode": "live_read_only",
        "endpointCategory": "odata_metadata",
        "httpStatus": response.status_code,
        "verifySsl": config["verify_ssl"],
    }
    if response.status_code == 200:
        return IntegrationCheckResult(
            status="check_ok",
            message="1С OData metadata доступна в read-only режиме.",
            payload=payload,
        )
    return IntegrationCheckResult(
        status="check_failed",
        message=(
            "1С OData metadata недоступна. Проверьте URL, пользователя, пароль "
            "и read-only права."
        ),
        payload=payload,
    )


def _check_ozon_api(settings: WebSettings, secret: str) -> IntegrationCheckResult:
    checked_at = security.utcnow().isoformat()
    try:
        ozon_settings = ozon_settings_from_secret(secret)
    except OzonConfigError as exc:
        return IntegrationCheckResult(
            status="check_failed",
            message=(
                "Ozon secret должен содержать Client-Id и Api-Key в JSON "
                "или key=value формате."
            ),
            payload={
                "provider": "ozon_api",
                "checkedAt": checked_at,
                "checkMode": "parse_only",
                "endpointCategory": "seller_info",
                "errorType": str(exc),
            },
        )
    account = ozon_settings.accounts[0]
    try:
        with httpx.Client(
            headers={
                "Client-Id": account.client_id,
                "Api-Key": account.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            timeout=settings.integration_check_timeout_seconds,
            follow_redirects=True,
        ) as client:
            results = []
            for endpoint_category, url, body in _ozon_readonly_check_requests():
                response = client.post(url, json=body)
                results.append(
                    {
                        "endpointCategory": endpoint_category,
                        "httpStatus": response.status_code,
                    }
                )
                if response.status_code == 200:
                    return IntegrationCheckResult(
                        status="check_ok",
                        message=(
                            "Ozon read-only проверка прошла по рабочему "
                            f"источнику {endpoint_category}."
                        ),
                        payload={
                            "provider": "ozon_api",
                            "checkedAt": checked_at,
                            "checkMode": "live_read_only",
                            "endpointCategory": endpoint_category,
                            "httpStatus": response.status_code,
                            "checkedEndpoints": results,
                        },
                    )
    except httpx.HTTPError as exc:
        return IntegrationCheckResult(
            status="check_failed",
            message="Ozon Seller API не ответил на read-only проверку.",
            payload={
                "provider": "ozon_api",
                "checkedAt": checked_at,
                "checkMode": "live_read_only",
                "endpointCategory": "ozon_readonly_sources",
                "errorType": exc.__class__.__name__,
            },
        )
    payload: dict[str, Any] = {
        "provider": "ozon_api",
        "checkedAt": checked_at,
        "checkMode": "live_read_only",
        "endpointCategory": "ozon_readonly_sources",
        "httpStatus": results[-1]["httpStatus"] if results else None,
        "checkedEndpoints": results,
    }
    if any(item["httpStatus"] == 429 for item in results):
        return IntegrationCheckResult(
            status="check_failed",
            message="Ozon ограничил частоту проверки. Повторите позже.",
            payload=payload,
        )
    return IntegrationCheckResult(
        status="check_failed",
        message="Ozon не принял Client-Id/Api-Key для read-only проверки.",
        payload=payload,
    )


def _ozon_readonly_check_requests() -> list[tuple[str, str, dict[str, Any]]]:
    checked_on = security.utcnow().date().isoformat()
    return [
        (
            "finance_cash_flow",
            OZON_CASH_FLOW_CHECK_URL,
            {
                "page": 1,
                "page_size": 1,
                "date": {
                    "from": f"{checked_on}T00:00:00Z",
                    "to": f"{checked_on}T23:59:59Z",
                },
                "with_details": False,
            },
        ),
        (
            "stock_on_warehouses",
            OZON_STOCK_CHECK_URL,
            {"limit": 1, "offset": 0},
        ),
    ]


def _parse_onec_secret(secret: str) -> dict[str, Any]:
    raw = secret.strip()
    if raw.startswith("{"):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise IntegrationSecretError("onec_secret_json_invalid") from exc
        if not isinstance(parsed, dict):
            raise IntegrationSecretError("onec_secret_json_must_be_object")
        values = {str(key): value for key, value in parsed.items()}
    else:
        values: dict[str, Any] = {}
        for item in raw.replace("\n", ";").split(";"):
            if not item.strip():
                continue
            key, sep, value = item.partition("=")
            if not sep:
                raise IntegrationSecretError("onec_secret_key_value_expected")
            values[key.strip()] = value.strip()

    base_url = _first_value(
        values,
        "baseUrl",
        "base_url",
        "ONEC_ODATA_BASE_URL",
        "ONEC_ODATA_URL",
        "ONEC_ODATA_ENDPOINT",
    )
    username = _first_value(
        values,
        "username",
        "user",
        "login",
        "ONEC_ODATA_USERNAME",
        "ONEC_ODATA_USER",
        "ONEC_ODATA_LOGIN",
    )
    password = _first_value(
        values,
        "password",
        "pass",
        "ONEC_ODATA_PASSWORD",
        "ONEC_ODATA_PASS",
    )
    if not base_url or not username or not password:
        raise IntegrationSecretError("onec_secret_missing_required_fields")
    base_url = _normalize_onec_base_url(base_url)
    parsed_url = urlparse(base_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise IntegrationSecretError("onec_base_url_invalid")
    verify_ssl = _parse_bool(
        _first_value(values, "verifySsl", "verify_ssl", "ONEC_ODATA_VERIFY_SSL"),
        default=True,
    )
    return {
        "base_url": base_url,
        "username": username,
        "password": password,
        "verify_ssl": verify_ssl,
    }


def _first_value(values: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = values.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _normalize_onec_base_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    metadata_suffix = "/$metadata"
    if normalized.lower().endswith(metadata_suffix):
        normalized = normalized[: -len(metadata_suffix)].rstrip("/")
    return normalized


def _parse_bool(value: str, *, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on", "да"}


def _fernet_or_none(settings: WebSettings) -> Fernet | None:
    key = settings.integration_secret_key.strip()
    if not key:
        return None
    try:
        decoded = base64.urlsafe_b64decode(key.encode("ascii"))
    except (binascii.Error, UnicodeEncodeError):
        return None
    if len(decoded) != 32:
        return None
    return Fernet(key.encode("ascii"))
