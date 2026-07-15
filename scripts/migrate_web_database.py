#!/usr/bin/env python3
"""Apply idempotent web schema migrations using runtime configuration."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.web.database import (  # noqa: E402
    init_db,
    make_engine,
    schema_version,
)
from wb_unit_economics.web.settings import WebSettings  # noqa: E402


def main() -> int:
    settings = WebSettings()
    engine = make_engine(
        settings.database_url,
        statement_timeout_ms=settings.postgres_statement_timeout_ms,
    )
    init_db(engine, run_backfill=True)
    print(f"schema_version={schema_version(engine)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
