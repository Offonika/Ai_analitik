from __future__ import annotations

import json
from pathlib import Path

from scripts.validate_release_notes import (
    INDEX_PATH,
    NOTES_PATH,
    STATIC_ROOT,
    validate_release_notes,
)


def _notes_copy(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    payload = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    destination = tmp_path / "release-notes.json"
    return destination, payload


def test_release_notes_contract_is_valid() -> None:
    assert validate_release_notes() == []


def test_release_notes_reject_unknown_guide_target(tmp_path: Path) -> None:
    path, payload = _notes_copy(tmp_path)
    payload["releases"][0]["items"][0]["guideId"] = "missing-topic"
    path.write_text(json.dumps(payload), encoding="utf-8")

    failures = validate_release_notes(path, INDEX_PATH, STATIC_ROOT)

    assert any("unknown guide target" in failure for failure in failures)


def test_release_notes_reject_external_or_unsafe_content(tmp_path: Path) -> None:
    path, payload = _notes_copy(tmp_path)
    payload["releases"][0]["summary"] = "Подробнее: https://example.invalid"
    path.write_text(json.dumps(payload), encoding="utf-8")

    failures = validate_release_notes(path, INDEX_PATH, STATIC_ROOT)

    assert any("external URL" in failure for failure in failures)


def test_release_notes_reject_duplicate_versions(tmp_path: Path) -> None:
    path, payload = _notes_copy(tmp_path)
    payload["releases"][1]["version"] = payload["releases"][0]["version"]
    path.write_text(json.dumps(payload), encoding="utf-8")

    failures = validate_release_notes(path, INDEX_PATH, STATIC_ROOT)

    assert "releases: duplicate version" in failures


def test_release_notes_reject_guide_link_to_unknown_release(tmp_path: Path) -> None:
    index_path = tmp_path / "index.html"
    index_path.write_text(
        INDEX_PATH.read_text(encoding="utf-8").replace(
            'data-guide-updated-version="v2.64"',
            'data-guide-updated-version="v9.99"',
            1,
        ),
        encoding="utf-8",
    )

    failures = validate_release_notes(NOTES_PATH, index_path, STATIC_ROOT)

    assert any("unknown updated release v9.99" in failure for failure in failures)


def test_web_build_id_matches_current_release_version() -> None:
    """Метка сборки обязана нести текущую версию из release notes.

    Без этой связи `WEB_BUILD_ID` молча отстаёт от выпущенной версии, и
    `/api/health` перестаёт различать контуры после promote.
    """

    from wb_unit_economics.web.app import WEB_BUILD_ID

    payload = json.loads(NOTES_PATH.read_text(encoding="utf-8"))
    current_version = payload["currentVersion"]

    assert current_version in WEB_BUILD_ID, (
        f"WEB_BUILD_ID={WEB_BUILD_ID!r} не содержит currentVersion="
        f"{current_version!r}: обновите метку вместе с release notes"
    )
