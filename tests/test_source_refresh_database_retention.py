from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from scripts.prune_source_refresh_database import (
    RunRetentionRecord,
    _verify_collection_files,
    main,
    select_protected_run_ids,
)
from wb_unit_economics.source_integrity import canonical_payload_hash


def test_retention_protects_report_recent_and_dependency_runs() -> None:
    now = datetime(2026, 7, 11, 8, tzinfo=UTC)
    old = now - timedelta(days=5)
    recent = now - timedelta(hours=1)
    records = [
        _run("report", old, snapshot="published-set", report="report-1"),
        _run("base", old),
        _run("composite", old, mode="onec-only", base="base"),
        _run("recent", recent),
        _run("active", old, finished=False),
        _run("deletable", old, status="failed"),
    ]

    protected = select_protected_run_ids(
        records,
        report_ids={"report-1"},
        report_snapshot_set_ids={"published-set"},
        source_load_run_ids={"composite"},
        cutoff=now - timedelta(hours=24),
        daily_keep=0,
        full_keep=0,
        explicit_protected=set(),
    )

    assert {"report", "base", "composite", "recent", "active"} <= protected
    assert "deletable" not in protected


def test_retention_keeps_latest_materialized_daily_and_full_per_client() -> None:
    now = datetime(2026, 7, 11, 8, tzinfo=UTC)
    records = [
        _run(f"daily-{index}", now - timedelta(days=index + 2), mode="daily")
        for index in range(4)
    ] + [
        _run(f"full-{index}", now - timedelta(days=index + 2), mode="full")
        for index in range(3)
    ]

    protected = select_protected_run_ids(
        records,
        report_ids=set(),
        report_snapshot_set_ids=set(),
        source_load_run_ids=set(),
        cutoff=now - timedelta(hours=24),
        daily_keep=3,
        full_keep=2,
        explicit_protected=set(),
    )

    assert {"daily-0", "daily-1", "daily-2"} <= protected
    assert "daily-3" not in protected
    assert {"full-0", "full-1"} <= protected
    assert "full-2" not in protected


def test_retention_keeps_explicit_run_and_resumed_source() -> None:
    now = datetime(2026, 7, 11, 8, tzinfo=UTC)
    old = now - timedelta(days=5)
    records = [
        _run("resumed-source", old),
        _run("current", old, resumed="resumed-source"),
    ]

    protected = select_protected_run_ids(
        records,
        report_ids=set(),
        report_snapshot_set_ids=set(),
        source_load_run_ids=set(),
        cutoff=now - timedelta(hours=24),
        daily_keep=0,
        full_keep=0,
        explicit_protected={"current"},
    )

    assert protected == {"current", "resumed-source"}


def test_file_authoritative_verification_requires_matching_manifest_hash(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_refresh"
    raw_path = source_root / "daily-1" / "wb_finance"
    raw_path.mkdir(parents=True)
    payload = [{"rrdId": 1, "retailAmount": "100"}]
    output_path = raw_path / "page.raw.json"
    output_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    expected_hash = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    results = [
        {
            "output_file": output_path.name,
            "raw_payload_hash": expected_hash,
            "row_count": 1,
        }
    ]
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": results}),
        encoding="utf-8",
    )
    collection = SimpleNamespace(
        raw_path=str(raw_path),
        snapshot_hash=canonical_payload_hash(results),
        source_type="wb_finance_detail",
        row_count=1,
        payload={"results": results},
    )

    assert _verify_collection_files(collection, source_root=source_root) is True

    output_path.write_text("[]", encoding="utf-8")
    assert _verify_collection_files(collection, source_root=source_root) is False


def test_file_authoritative_verification_rejects_truncated_manifest(
    tmp_path: Path,
) -> None:
    source_root = tmp_path / "source_refresh"
    raw_path = source_root / "daily-1" / "wb_finance"
    raw_path.mkdir(parents=True)
    output_path = raw_path / "page.raw.json"
    output_path.write_text("[]", encoding="utf-8")
    empty_hash = hashlib.sha256(b"[]").hexdigest()
    manifest_results = [
        {
            "output_file": output_path.name,
            "raw_payload_hash": empty_hash,
            "row_count": 0,
        }
    ]
    collection_results = [
        *manifest_results,
        {
            "output_file": "missing.raw.json",
            "raw_payload_hash": "a" * 64,
            "row_count": 100,
        },
    ]
    (raw_path / "manifest.json").write_text(
        json.dumps({"results": manifest_results}),
        encoding="utf-8",
    )
    collection = SimpleNamespace(
        raw_path=str(raw_path),
        snapshot_hash=canonical_payload_hash(collection_results),
        source_type="wb_finance_detail",
        row_count=100,
        payload={"results": collection_results},
    )

    assert _verify_collection_files(collection, source_root=source_root) is False


def test_retention_apply_requires_backup_before_database_access(
    monkeypatch,
) -> None:
    monkeypatch.setenv("SHUMEYKO_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(sys, "argv", ["prune_source_refresh_database.py", "--apply"])

    assert main() == 2


def _run(
    run_id: str,
    created_at: datetime,
    *,
    mode: str = "daily",
    status: str = "source_loaded",
    snapshot: str = "",
    report: str | None = None,
    base: str | None = None,
    resumed: str | None = None,
    finished: bool = True,
) -> RunRetentionRecord:
    return RunRetentionRecord(
        id=run_id,
        tenant_id="tenant",
        client_id="client",
        mode=mode,
        status=status,
        snapshot_set_id=snapshot,
        created_at=created_at,
        finished_at=created_at + timedelta(minutes=5) if finished else None,
        new_report_run_id=report,
        base_source_refresh_run_id=base,
        resumed_from_run_id=resumed,
    )
