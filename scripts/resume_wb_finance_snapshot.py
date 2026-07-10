#!/usr/bin/env python3
"""Resume a local WB finance snapshot from the last manifest rrd_id."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from wb_unit_economics.wb_finance import resume_wb_finance_export
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import make_engine, make_session_factory
from wb_unit_economics.web.settings import WebSettings
from wb_unit_economics.web.source_refresh import (
    CREDENTIAL_SOURCES,
    SourceRefreshService,
)


def main() -> int:
    args = _parse_args()
    settings = _settings_from_args(args)
    export_dir = args.export_dir.resolve()
    if not (export_dir / "manifest.json").exists():
        print(f"WB finance manifest not found: {export_dir / 'manifest.json'}")
        return 2

    engine = make_engine(settings.database_url)
    session_factory = make_session_factory(engine)
    service = SourceRefreshService(settings)
    with session_factory() as db:
        conflict = repository.active_conflicting_source_refresh_run(
            db,
            tenant_id=args.tenant,
            mode="full",
        )
        if conflict is not None:
            print(
                "Source refresh already active: "
                f"{conflict.id} ({conflict.mode}, {conflict.status})"
            )
            return 2
        credentials = service._credentials(
            db,
            tenant_id=args.tenant,
            credential_source=args.credential_source,
            mode="full",
        )

    wb_issues = [
        item
        for item in credentials.issues
        if str(item.get("source_type", "")).startswith("wb_api")
    ]
    if wb_issues or credentials.wb_settings is None:
        _print(
            {
                "status": "needs_configuration",
                "source": "wb_api",
                "issues": [
                    {
                        "sourceType": item.get("source_type", ""),
                        "status": item.get("status", ""),
                        "errorMessage": item.get("error_message", ""),
                    }
                    for item in wb_issues
                ],
            },
            as_json=args.json,
        )
        return 2

    max_pages = args.max_pages or settings.source_refresh_wb_max_pages
    request_delay_seconds = (
        args.request_delay_seconds
        if args.request_delay_seconds is not None
        else settings.source_refresh_wb_request_delay_seconds
    )
    before = _manifest_summary(export_dir)
    results = resume_wb_finance_export(
        credentials.wb_settings,
        export_dir,
        max_pages=max_pages,
        request_delay_seconds=request_delay_seconds,
    )
    after = _manifest_summary(export_dir)
    payload = {
        "status": "completed" if after["complete"] else "partial_source",
        "exportDir": str(export_dir),
        "maxPages": max_pages,
        "requestDelaySeconds": request_delay_seconds,
        "previousPages": before["pages"],
        "previousRows": before["rows"],
        "newPages": len(results),
        "newRows": sum(item.row_count for item in results),
        "totalPages": after["pages"],
        "totalRows": after["rows"],
        "complete": after["complete"],
        "accounts": after["accounts"],
    }
    _print(payload, as_json=args.json)
    return 0 if after["complete"] else 1


def _settings_from_args(args: argparse.Namespace) -> WebSettings:
    database_url = args.database_url or os.getenv("SHUMEYKO_DATABASE_URL")
    if database_url:
        return WebSettings(_env_file=None, database_url=database_url)
    return WebSettings(_env_file=None)


def _manifest_summary(export_dir: Path) -> dict[str, Any]:
    manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
    results = [item for item in manifest.get("results", []) if isinstance(item, dict)]
    accounts: dict[str, dict[str, Any]] = {}
    for item in results:
        account_id = str(item.get("seller_account_id") or "")
        if not account_id:
            continue
        accounts[account_id] = {
            "sellerAccountId": account_id,
            "lastPageIndex": item.get("page_index"),
            "lastStatus": item.get("status"),
            "lastRowCount": item.get("row_count", 0),
            "hasNextRrdId": item.get("rrd_id_next") is not None,
        }
    return {
        "pages": len(results),
        "rows": sum(int(item.get("row_count") or 0) for item in results),
        "complete": bool(accounts)
        and all(item["lastStatus"] == "no_data" for item in accounts.values()),
        "accounts": list(accounts.values()),
    }


def _print(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(f"Status: {payload['status']}")
    print(f"Export dir: {payload.get('exportDir', '')}")
    print(f"New pages: {payload.get('newPages', 0)}")
    print(f"New rows: {payload.get('newRows', 0)}")
    print(f"Total pages: {payload.get('totalPages', 0)}")
    print(f"Total rows: {payload.get('totalRows', 0)}")
    print(f"Complete: {payload.get('complete', False)}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resume a local read-only WB finance snapshot by rrd_id."
    )
    parser.add_argument("--tenant", required=True, help="Tenant id.")
    parser.add_argument(
        "--export-dir",
        required=True,
        type=Path,
        help="Directory with WB finance manifest.json and raw page files.",
    )
    parser.add_argument(
        "--credential-source",
        choices=sorted(CREDENTIAL_SOURCES),
        default="tenant",
        help="Use encrypted tenant integrations by default.",
    )
    parser.add_argument(
        "--database-url",
        default="",
        help="Database URL. Defaults to SHUMEYKO_DATABASE_URL or WebSettings.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=0,
        help="Maximum additional WB pages to fetch in this batch.",
    )
    parser.add_argument(
        "--request-delay-seconds",
        type=float,
        default=None,
        help="Delay between WB requests. Defaults to web settings.",
    )
    parser.add_argument("--json", action="store_true", help="Print safe JSON summary.")
    return parser.parse_args()


if __name__ == "__main__":
    sys.exit(main())
