#!/usr/bin/env python3
"""Create separate root-only production and test environment files safely."""

from __future__ import annotations

import argparse
import os
import secrets
import tempfile
from pathlib import Path

from sqlalchemy.engine import make_url


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("/etc/shumeiko-web.env")
    )
    parser.add_argument(
        "--production-output",
        type=Path,
        default=Path("/etc/shumeiko-web-prod.env"),
    )
    parser.add_argument(
        "--test-output",
        type=Path,
        default=Path("/etc/shumeiko-web-test.env"),
    )
    parser.add_argument("--test-database", default="shumeyko_web_cabinet_test")
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def _parse_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _write_env(path: Path, values: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            for key in sorted(values):
                value = values[key]
                if "\n" in value or "\r" in value:
                    raise ValueError(f"multiline environment value is forbidden: {key}")
                escaped = value.replace("\\", "\\\\").replace('"', '\\"')
                stream.write(f'{key}="{escaped}"\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    args = parse_args()
    values = _parse_env(args.source)
    database_url = values.get("SHUMEYKO_DATABASE_URL", "")
    if not database_url:
        raise SystemExit("Source environment has no SHUMEYKO_DATABASE_URL")
    test_database_url = make_url(database_url).set(
        database=args.test_database
    ).render_as_string(hide_password=False)

    production = dict(values)
    production.update(
        {
            "SHUMEYKO_RUNTIME_ENVIRONMENT": "production",
            "SHUMEYKO_SESSION_COOKIE_NAME": "shumeyko_prod_session",
            "SHUMEYKO_CLIENT_LOGIN_ENABLED": "true",
            "SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED": "true",
            "SHUMEYKO_MAINTENANCE_MESSAGE": "",
            "SHUMEYKO_ALLOWED_EXPORT_ROOT": (
                "/opt/shumeyko-partners-wb-unit-economics/reports"
            ),
            "SHUMEYKO_DEFAULT_REPORT_WORKBOOK": (
                "/opt/shumeyko-partners-wb-unit-economics/reports/"
                "shumeyko_wb_excel_mvp.xlsx"
            ),
            "SHUMEYKO_SOURCE_REFRESH_ROOT": "/data/shumeyko/source_refresh",
        }
    )

    test = dict(values)
    test.update(
        {
            "SHUMEYKO_DATABASE_URL": test_database_url,
            "SHUMEYKO_RUNTIME_ENVIRONMENT": "test",
            "SHUMEYKO_SESSION_SECRET": secrets.token_urlsafe(48),
            "SHUMEYKO_SESSION_COOKIE_NAME": "shumeyko_test_session",
            "SHUMEYKO_CLIENT_LOGIN_ENABLED": "false",
            "SHUMEYKO_EXTERNAL_INTEGRATIONS_ENABLED": "false",
            "SHUMEYKO_MAINTENANCE_MESSAGE": "",
            "SHUMEYKO_ALLOWED_EXPORT_ROOT": "/data/shumeyko/test/reports",
            "SHUMEYKO_DEFAULT_REPORT_WORKBOOK": (
                "/data/shumeyko/test/reports/none.xlsx"
            ),
            "SHUMEYKO_INTEGRATION_SECRET_KEY": "",
            "SHUMEYKO_BOOTSTRAP_PASSWORD": "",
            "SHUMEYKO_OPENAI_API_KEY": "",
            "OPENAI_API_KEY": "",
            "SHUMEYKO_LIVE_CHECKS_ENABLED": "false",
            "SHUMEYKO_AUTO_REFRESH_ENABLED": "false",
            "SHUMEYKO_SOURCE_REFRESH_ENABLED": "false",
            "SHUMEYKO_SOURCE_REFRESH_ROOT": "/data/shumeyko/test/source_refresh",
            "SHUMEYKO_SOURCE_REFRESH_RETENTION_DAILY_RUNS": "1",
            "SHUMEYKO_SOURCE_REFRESH_RETENTION_FULL_RUNS": "1",
            "SHUMEYKO_SOURCE_REFRESH_FAILED_SNAPSHOT_KEEP": "1",
            "SHUMEYKO_SOURCE_REFRESH_MIN_FREE_GB": "15",
            "WB_ACCOUNT_1_API_KEY": "",
            "WB_ACCOUNT_2_API_KEY": "",
            "OZON_ACCOUNT_1_API_KEY": "",
            "ONEC_ODATA_USERNAME": "",
            "ONEC_ODATA_PASSWORD": "",
        }
    )

    print(
        f"source={args.source} production={args.production_output} "
        f"test={args.test_output} apply={bool(args.apply)}"
    )
    if not args.apply:
        print("Dry-run: environment files were not changed.")
        return 0
    _write_env(args.production_output, production)
    _write_env(args.test_output, test)
    print("status=created permissions=0600 secretsPrinted=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
