#!/usr/bin/env python3
"""Dry-run or configure the tagged three-year raw snapshot S3 lifecycle."""

# ruff: noqa: E402

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.maintenance_safety import (
    load_s3_backup_config,
    make_s3_client,
)

RULE_ID = "expire-source-refresh-raw-after-three-years"
RETENTION_DAYS = 365 * 3


def desired_rule() -> dict:
    return {
        "ID": RULE_ID,
        "Status": "Enabled",
        "Filter": {"Tag": {"Key": "archive-class", "Value": "raw-source"}},
        "Expiration": {"Days": RETENTION_DAYS},
        "NoncurrentVersionExpiration": {"NoncurrentDays": RETENTION_DAYS},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-config", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    config = load_s3_backup_config(args.s3_config)
    rule = desired_rule()
    print(json.dumps(rule, ensure_ascii=False, sort_keys=True))
    if not args.apply:
        print("Dry run only. S3 lifecycle was not changed.")
        return 0
    client = make_s3_client(config)
    existing = []
    try:
        existing = client.get_bucket_lifecycle_configuration(
            Bucket=config.bucket
        ).get("Rules", [])
    except Exception as exc:
        error_code = str(
            getattr(exc, "response", {}).get("Error", {}).get("Code", "")
        )
        if error_code not in {"NoSuchLifecycleConfiguration", "NoSuchConfiguration"}:
            raise
    rules = [item for item in existing if item.get("ID") != RULE_ID]
    rules.append(rule)
    client.put_bucket_lifecycle_configuration(
        Bucket=config.bucket,
        LifecycleConfiguration={"Rules": rules},
    )
    verified = client.get_bucket_lifecycle_configuration(
        Bucket=config.bucket
    ).get("Rules", [])
    if not any(item.get("ID") == RULE_ID for item in verified):
        raise SystemExit("S3 lifecycle verification failed")
    print("S3 raw snapshot lifecycle verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
