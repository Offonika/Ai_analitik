from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.prune_report_drafts import (
    ReportDraftRecord,
    _remove_artifacts,
    main,
    select_draft_candidates,
)


def test_select_draft_candidates_keeps_latest_recent_and_protected() -> None:
    now = datetime(2026, 7, 18, 8, tzinfo=UTC)
    records = [
        _record("latest", now - timedelta(days=3)),
        _record("recent", now - timedelta(hours=2)),
        _record("protected", now - timedelta(days=5)),
        _record("deletable", now - timedelta(days=6)),
        _record("other-kind", now - timedelta(days=10), kind="month_close_control"),
    ]

    candidates = select_draft_candidates(
        records,
        cutoff=now - timedelta(hours=24),
        keep_latest=1,
        protected_ids={"protected"},
    )

    assert [item.id for item in candidates] == ["deletable", "latest"]


def test_select_draft_candidates_keeps_latest_per_organization() -> None:
    now = datetime(2026, 7, 18, 8, tzinfo=UTC)
    records = [
        _record("org-a-new", now - timedelta(days=2), organization="org-a"),
        _record("org-a-old", now - timedelta(days=3), organization="org-a"),
        _record("org-b-new", now - timedelta(days=4), organization="org-b"),
        _record("org-b-old", now - timedelta(days=5), organization="org-b"),
    ]

    candidates = select_draft_candidates(
        records,
        cutoff=now - timedelta(hours=24),
        keep_latest=1,
        protected_ids=set(),
    )

    assert [item.id for item in candidates] == ["org-b-old", "org-a-old"]


def test_remove_artifacts_deletes_only_registered_file(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    report_dir = reports_root / "draft"
    report_dir.mkdir(parents=True)
    artifact = report_dir / "report.xlsx"
    artifact.write_bytes(b"draft")
    unrelated = reports_root / "keep.txt"
    unrelated.write_text("keep", encoding="utf-8")

    removed_files, removed_bytes = _remove_artifacts(
        [artifact],
        reports_root=reports_root,
    )

    assert removed_files == 1
    assert removed_bytes == 5
    assert not artifact.exists()
    assert unrelated.read_text(encoding="utf-8") == "keep"


def test_remove_artifacts_rejects_symlink_path(tmp_path: Path) -> None:
    reports_root = tmp_path / "reports"
    target_dir = reports_root / "target"
    target_dir.mkdir(parents=True)
    target = target_dir / "report.xlsx"
    target.write_bytes(b"draft")
    link = reports_root / "linked"
    link.symlink_to(target_dir, target_is_directory=True)

    with pytest.raises(OSError, match="changed"):
        _remove_artifacts([link / "report.xlsx"], reports_root=reports_root)

    assert target.exists()


def test_apply_requires_backup_before_database_access(monkeypatch) -> None:
    monkeypatch.setenv("SHUMEYKO_DATABASE_URL", "sqlite:///:memory:")
    monkeypatch.setattr(sys, "argv", ["prune_report_drafts.py", "--apply"])

    assert main() == 2


def _record(
    report_id: str,
    created_at: datetime,
    *,
    kind: str = "marketplace_unit_economics",
    organization: str = "",
) -> ReportDraftRecord:
    return ReportDraftRecord(
        id=report_id,
        tenant_id="tenant",
        client_id="client",
        report_kind=kind,
        organization_id=organization,
        created_at=created_at,
    )
