from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from scripts.prune_runtime_releases import (
    ReleaseInfo,
    inspect_releases,
    select_release_candidates,
)
from wb_unit_economics.runtime_release_lock import exclusive_runtime_release_lock


def _release(path: Path, age_hours: int, *, complete: bool = True) -> ReleaseInfo:
    return ReleaseInfo(
        path=path,
        modified_at=datetime.now(UTC) - timedelta(hours=age_hours),
        complete=complete,
    )


def test_select_release_candidates_preserves_active_recent_and_rollback(
    tmp_path: Path,
) -> None:
    active = _release(tmp_path / "runtime-active", 10)
    rollback = _release(tmp_path / "runtime-rollback", 20)
    old = _release(tmp_path / "runtime-old", 30)
    recent_partial = _release(tmp_path / ".runtime-recent-partial", 1, complete=False)
    old_partial = _release(tmp_path / ".runtime-old-partial", 40, complete=False)

    candidates, rollback_paths = select_release_candidates(
        [active, rollback, old, recent_partial, old_partial],
        active_paths={active.path},
        keep_latest=1,
        cutoff=datetime.now(UTC) - timedelta(hours=24),
    )

    assert rollback_paths == {rollback.path}
    assert {item.path for item in candidates} == {old.path, old_partial.path}


def test_runtime_release_lock_fails_closed_on_contention(tmp_path: Path) -> None:
    lock_path = tmp_path / "runtime-release.lock"
    with (
        exclusive_runtime_release_lock(lock_path),
        pytest.raises(RuntimeError, match="already active"),
        exclusive_runtime_release_lock(lock_path),
    ):
        pass


def test_inspect_releases_rejects_symlink_entry(tmp_path: Path) -> None:
    release_root = tmp_path / "releases"
    runtime_root = tmp_path / "runtime"
    active = release_root / "runtime-active"
    active.mkdir(parents=True)
    (active / "release-manifest.json").write_text(
        '{"sourceDirty": false, "sourceCommit": "abc", "contentSha256": "def"}',
        encoding="utf-8",
    )
    for environment in ("prod", "test"):
        contour = runtime_root / environment
        contour.mkdir(parents=True)
        (contour / "current").symlink_to(active, target_is_directory=True)
    (release_root / "runtime-unsafe-link").symlink_to(active, target_is_directory=True)

    with pytest.raises(RuntimeError, match="unexpected release-root entry"):
        inspect_releases(release_root, runtime_root)
