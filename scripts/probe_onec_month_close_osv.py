from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, time
from pathlib import Path
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.month_close_cabinet_settings import (  # noqa: E402
    CabinetOnecLookup,
    CabinetOnecSettingsError,
    load_onec_settings_from_cabinet,
)
from wb_unit_economics.onec_odata import (  # noqa: E402
    BASE_URL_KEYS,
    PASSWORD_KEYS,
    TIMEOUT_KEYS,
    USERNAME_KEYS,
    VERIFY_SSL_KEYS,
    OnecODataConfigError,
    OnecODataSettings,
    extract_odata_rows,
)

MOSCOW_TZ = ZoneInfo("Europe/Moscow")
DEFAULT_PERIOD_START = date(2026, 5, 1)
DEFAULT_PERIOD_END = date(2026, 6, 1)
DEFAULT_REGISTER = "AccountingRegister_Управленческий"


@dataclass(frozen=True)
class VirtualTableProbe:
    name: str
    ok: bool
    status_code: int | None = None
    row_count: int = 0
    fields: list[str] = field(default_factory=list)
    error: str = ""


def main() -> int:
    args = _parse_args()
    try:
        settings = _load_settings_from_args(args)
    except (CabinetOnecSettingsError, OnecODataConfigError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_dir = args.output_dir or _default_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    period_start = datetime.combine(args.period_start, time.min)
    period_end = datetime.combine(args.period_end, time.min)

    probes = probe_virtual_accounting_tables(
        settings=settings,
        register_name=args.register,
        period_start=period_start,
        period_end=period_end,
        top=args.top,
    )
    manifest = {
        "generated_at": datetime.now(tz=MOSCOW_TZ).isoformat(),
        "source": "1c_odata",
        "read_boundary": "GET only",
        "register_name": args.register,
        "period_start": args.period_start.isoformat(),
        "period_end_exclusive": args.period_end.isoformat(),
        "contains_raw_rows": False,
        "probes": [asdict(probe) for probe in probes],
    }
    manifest_path = output_dir / "manifest.json"
    _write_json(manifest_path, manifest)

    print(f"1C OSV virtual table probe: {output_dir}")
    for probe in probes:
        status = "ok" if probe.ok else "error"
        details = f"status={probe.status_code}, rows={probe.row_count}"
        if probe.error:
            details = f"{details}, {probe.error}"
        print(f"- {probe.name}: {status}, {details}")
    print("Manifest: manifest.json")
    return 0 if any(probe.ok for probe in probes) else 1


def probe_virtual_accounting_tables(
    *,
    settings: OnecODataSettings,
    register_name: str,
    period_start: datetime,
    period_end: datetime,
    top: int = 5,
    transport: httpx.BaseTransport | None = None,
) -> list[VirtualTableProbe]:
    probes: list[VirtualTableProbe] = []
    base_url = settings.base_url.rstrip("/")
    register_path = quote(register_name, safe="")
    with httpx.Client(
        auth=(settings.username, settings.password),
        headers={"Accept": "application/json"},
        timeout=settings.timeout_seconds,
        verify=settings.verify_ssl,
        follow_redirects=True,
        transport=transport,
    ) as client:
        for name, function_call in _virtual_table_calls(period_start, period_end):
            try:
                response = client.get(
                    f"{base_url}/{register_path}/{function_call}",
                    params={"$format": "json", "$top": str(top)},
                )
                probes.append(_probe_from_response(name, response))
            except (httpx.HTTPError, ValueError) as exc:
                probes.append(
                    VirtualTableProbe(name=name, ok=False, error=exc.__class__.__name__)
                )
    return probes


def _probe_from_response(
    name: str,
    response: httpx.Response,
) -> VirtualTableProbe:
    if response.status_code != 200:
        return VirtualTableProbe(
            name=name,
            ok=False,
            status_code=response.status_code,
            error=_odata_error_message(response.text),
        )
    rows = extract_odata_rows(response.json())
    dict_rows = [row for row in rows if isinstance(row, dict)]
    fields = sorted({field for row in dict_rows for field in row})
    return VirtualTableProbe(
        name=name,
        ok=True,
        status_code=response.status_code,
        row_count=len(rows),
        fields=fields[:60],
    )


def _virtual_table_calls(
    period_start: datetime,
    period_end: datetime,
) -> list[tuple[str, str]]:
    start = f"datetime'{period_start:%Y-%m-%dT%H:%M:%S}'"
    end = f"datetime'{period_end:%Y-%m-%dT%H:%M:%S}'"
    return [
        (
            "BalanceAndTurnovers",
            "BalanceAndTurnovers("
            f"StartPeriod={start},EndPeriod={end},"
            "AccountCondition='',Condition='',Dimensions='Организация')",
        ),
        (
            "Turnovers",
            "Turnovers("
            f"StartPeriod={start},EndPeriod={end},"
            "AccountCondition='',BalancedAccountCondition='',"
            "Condition='',Dimensions='Организация')",
        ),
        (
            "DrCrTurnovers",
            "DrCrTurnovers("
            f"StartPeriod={start},EndPeriod={end},"
            "AccountCondition='',BalancedAccountCondition='',"
            "Condition='',Dimensions='Организация')",
        ),
    ]


def _load_settings(env_file: Path | None) -> OnecODataSettings:
    if env_file is not None:
        return OnecODataSettings.from_env_file(env_file)
    values = os.environ
    base_url = _first_present(values, BASE_URL_KEYS)
    username = _first_present(values, USERNAME_KEYS)
    password = _first_present(values, PASSWORD_KEYS)
    missing: list[str] = []
    if not base_url:
        missing.append(BASE_URL_KEYS[0])
    if not username:
        missing.append(USERNAME_KEYS[0])
    if not password:
        missing.append(PASSWORD_KEYS[0])
    if missing:
        names = ", ".join(missing)
        raise OnecODataConfigError(
            f"Missing required 1C OData environment variables: {names}"
        )
    timeout_value = _first_present(values, TIMEOUT_KEYS)
    verify_value = _first_present(values, VERIFY_SSL_KEYS)
    return OnecODataSettings(
        base_url=base_url.rstrip("/"),
        username=username,
        password=password,
        timeout_seconds=float(timeout_value) if timeout_value else 30.0,
        verify_ssl=_parse_bool(verify_value, default=True),
    )


def _load_settings_from_args(args: argparse.Namespace) -> OnecODataSettings:
    if args.cabinet_client_name or args.tenant_id:
        return load_onec_settings_from_cabinet(
            CabinetOnecLookup(
                client_name=args.cabinet_client_name,
                tenant_id=args.tenant_id,
                provider=args.integration_provider,
                database_url=args.web_database_url,
            )
        )
    return _load_settings(args.env_file)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Probe read-only 1C OData accounting virtual tables for month-close OSV."
        )
    )
    parser.add_argument(
        "--period-start",
        type=_parse_date,
        default=DEFAULT_PERIOD_START,
    )
    parser.add_argument("--period-end", type=_parse_date, default=DEFAULT_PERIOD_END)
    parser.add_argument("--register", default=DEFAULT_REGISTER)
    parser.add_argument("--top", type=int, default=5)
    parser.add_argument("--output-dir", type=Path, default=None)
    parser.add_argument(
        "--cabinet-client-name",
        default="",
        help="Load encrypted 1C OData settings from web cabinet by client name.",
    )
    parser.add_argument(
        "--tenant-id",
        default="",
        help="Load encrypted 1C OData settings from web cabinet by tenant id.",
    )
    parser.add_argument(
        "--integration-provider",
        default="onec_readonly",
        help="Tenant integration provider id for 1C settings.",
    )
    parser.add_argument(
        "--web-database-url",
        default="",
        help=(
            "Optional web cabinet database URL. Defaults to SHUMEYKO_DATABASE_URL "
            "or local web settings."
        ),
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help=(
            "Optional env file. By default the probe uses already exported "
            "environment variables and does not read .env."
        ),
    )
    return parser.parse_args()


def _first_present(values: Mapping[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = values.get(key, "").strip()
        if value:
            return value
    return ""


def _parse_bool(value: str, *, default: bool) -> bool:
    if not value:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


def _odata_error_message(text: str) -> str:
    try:
        payload = json.loads(text)
        message = payload.get("odata.error", {}).get("message", {}).get("value")
        if message:
            return str(message).replace("\n", " ")[:500]
    except ValueError:
        pass
    return text.replace("\n", " ")[:500]


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def _default_output_dir() -> Path:
    timestamp = datetime.now(tz=MOSCOW_TZ).strftime("%Y%m%d-%H%M%S")
    return Path("data") / "onec_month_close_osv_probe" / timestamp


if __name__ == "__main__":
    sys.exit(main())
