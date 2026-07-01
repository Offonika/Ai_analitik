#!/usr/bin/env python3
"""Create a gzip PostgreSQL backup for the Shumeyko web cabinet."""

from __future__ import annotations

import argparse
import gzip
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url", default=os.getenv("SHUMEYKO_DATABASE_URL", "")
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("/var/backups/shumeiko-web"),
    )
    parser.add_argument("--retention-days", type=int, default=14)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("SHUMEYKO_DATABASE_URL is required")
    if args.database_url.startswith("sqlite"):
        raise SystemExit("PostgreSQL database URL is required for production backup")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    target = args.output_dir / f"shumeiko-web-{stamp}.sql.gz"
    process = run_pg_dump(pg_dump_url(args.database_url))
    with gzip.open(target, "wb") as handle:
        handle.write(process.stdout)
    target.chmod(0o600)
    removed = prune_old_backups(args.output_dir, args.retention_days)
    print(f"backup={target} removed_old={removed}")
    return 0


def pg_dump_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def run_pg_dump(database_url: str) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["pg_dump", "--no-owner", "--no-privileges", database_url],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"pg_dump failed: {detail or 'unknown error'}") from exc


def prune_old_backups(output_dir: Path, retention_days: int) -> int:
    if retention_days <= 0:
        return 0
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    removed = 0
    for path in output_dir.glob("shumeiko-web-*.sql.gz"):
        modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
        if modified < cutoff:
            path.unlink()
            removed += 1
    return removed


if __name__ == "__main__":
    raise SystemExit(main())
