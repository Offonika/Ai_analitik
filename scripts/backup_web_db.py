#!/usr/bin/env python3
"""Create a gzip PostgreSQL backup for the Shumeyko web cabinet."""

from __future__ import annotations

import argparse
import gzip
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlparse


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
    parser.add_argument("--retention-days", type=int, default=3)
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
    write_pg_dump_backup(pg_dump_url(args.database_url), target)
    target.chmod(0o600)
    removed = prune_old_backups(args.output_dir, args.retention_days)
    print(f"backup={target} removed_old={removed}")
    return 0


def pg_dump_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def write_pg_dump_backup(database_url: str, target: Path) -> None:
    tmp_target = target.with_name(f"{target.name}.tmp")
    tmp_target.unlink(missing_ok=True)
    command, env = pg_dump_command(database_url)
    try:
        with tempfile.TemporaryFile() as stderr_file:
            process = subprocess.Popen(
                command,
                env=env,
                stderr=stderr_file,
                stdout=subprocess.PIPE,
            )
            if process.stdout is None:
                raise SystemExit("pg_dump stdout pipe was not created")
            with process.stdout, gzip.open(tmp_target, "wb") as handle:
                shutil.copyfileobj(process.stdout, handle, length=1024 * 1024)
            return_code = process.wait()
            if return_code != 0:
                stderr_file.seek(0)
                detail = stderr_file.read().decode("utf-8", errors="replace").strip()
                raise SystemExit(f"pg_dump failed: {detail or 'unknown error'}")
        tmp_target.replace(target)
    except BaseException:
        tmp_target.unlink(missing_ok=True)
        raise


def pg_dump_command(database_url: str) -> tuple[list[str], dict[str, str]]:
    parsed = urlparse(database_url)
    if parsed.scheme not in {"postgresql", "postgres"}:
        return (
            ["pg_dump", "--no-owner", "--no-privileges", database_url],
            os.environ.copy(),
        )

    env = os.environ.copy()
    if parsed.hostname:
        env["PGHOST"] = parsed.hostname
    if parsed.port:
        env["PGPORT"] = str(parsed.port)
    if parsed.username:
        env["PGUSER"] = unquote(parsed.username)
    if parsed.password:
        env["PGPASSWORD"] = unquote(parsed.password)
    database = unquote(parsed.path.lstrip("/"))
    if database:
        env["PGDATABASE"] = database
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if key.lower() == "sslmode" and value:
            env["PGSSLMODE"] = value
    return ["pg_dump", "--no-owner", "--no-privileges"], env


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
