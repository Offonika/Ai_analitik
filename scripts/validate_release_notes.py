from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NOTES_PATH = ROOT / "src/wb_unit_economics/web/static/release-notes.json"
INDEX_PATH = ROOT / "src/wb_unit_economics/web/static/index.html"
STATIC_ROOT = ROOT / "src/wb_unit_economics/web/static"
VERSION_RE = re.compile(r"^v(\d+)\.(\d+)(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?$")
GUIDE_ID_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_CATEGORIES = {"new", "improved", "fixed"}
FORBIDDEN_TEXT_PATTERNS = (
    (re.compile(r"https?://", re.IGNORECASE), "external URL"),
    (re.compile(r"(?:^|\s)/(?:opt|data|tmp|run|etc)/", re.IGNORECASE), "raw path"),
    (
        re.compile(
            r"\b(?:gh[opusr]_|sk-|Bearer\s+)[A-Za-z0-9_-]+", re.IGNORECASE
        ),
        "credential-like value",
    ),
    (re.compile(r"\b[a-f0-9]{40,64}\b", re.IGNORECASE), "commit or content hash"),
    (re.compile(r"\breport[_ -]?id\b", re.IGNORECASE), "report identifier"),
    (re.compile(r"[<>]"), "HTML markup"),
)


@dataclass(frozen=True)
class GuideEntry:
    guide_id: str
    roles: tuple[str, ...]
    updated_version: str


class GuideEntryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.entries: list[GuideEntry] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        guide_id = values.get("data-guide-id", "").strip()
        if not guide_id:
            return
        roles = tuple(
            role.strip()
            for role in values.get("data-guide-roles", "").split(",")
            if role.strip()
        )
        self.entries.append(
            GuideEntry(
                guide_id=guide_id,
                roles=roles,
                updated_version=values.get("data-guide-updated-version", "").strip(),
            )
        )


def _version_key(value: str) -> tuple[int, int, int, int, tuple[str, ...]] | None:
    match = VERSION_RE.fullmatch(value)
    if not match:
        return None
    prerelease = match.group(4)
    return (
        int(match.group(1)),
        int(match.group(2)),
        int(match.group(3) or 0),
        1 if prerelease is None else 0,
        tuple((prerelease or "").split(".")),
    )


def _validate_safe_text(value: Any, path: str, failures: list[str]) -> None:
    if not isinstance(value, str) or not value.strip():
        failures.append(f"{path}: expected non-empty text")
        return
    for pattern, label in FORBIDDEN_TEXT_PATTERNS:
        if pattern.search(value):
            failures.append(f"{path}: forbidden {label}")


def _load_guide_entries(index_path: Path) -> tuple[dict[str, GuideEntry], list[str]]:
    parser = GuideEntryParser()
    parser.feed(index_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    entries: dict[str, GuideEntry] = {}
    for entry in parser.entries:
        if not GUIDE_ID_RE.fullmatch(entry.guide_id):
            failures.append(f"guide:{entry.guide_id}: invalid data-guide-id")
        if entry.guide_id in entries:
            failures.append(f"guide:{entry.guide_id}: duplicate data-guide-id")
        entries[entry.guide_id] = entry
    return entries, failures


def _validate_media(
    media: Any,
    path: str,
    static_root: Path,
    failures: list[str],
) -> None:
    if not isinstance(media, dict):
        failures.append(f"{path}: expected object")
        return
    src = media.get("src")
    _validate_safe_text(src, f"{path}.src", failures)
    _validate_safe_text(media.get("alt"), f"{path}.alt", failures)
    _validate_safe_text(media.get("caption"), f"{path}.caption", failures)
    if not isinstance(src, str) or not src.startswith("/static/release-media/"):
        failures.append(f"{path}.src: expected local /static/release-media/ path")
        return
    relative = Path(src.removeprefix("/static/"))
    if relative.suffix.lower() != ".webp" or ".." in relative.parts:
        failures.append(f"{path}.src: expected safe WebP path")
        return
    asset = static_root / relative
    if not asset.is_file():
        failures.append(f"{path}.src: missing asset {src}")
        return
    payload = asset.read_bytes()
    if len(payload) > 500 * 1024:
        failures.append(f"{path}.src: asset exceeds 500 KiB")
    if len(payload) < 12 or payload[:4] != b"RIFF" or payload[8:12] != b"WEBP":
        failures.append(f"{path}.src: invalid WebP header")
    if b"EXIF" in payload or b"XMP " in payload:
        failures.append(f"{path}.src: metadata chunk is forbidden")


def validate_release_notes(
    notes_path: Path = NOTES_PATH,
    index_path: Path = INDEX_PATH,
    static_root: Path = STATIC_ROOT,
) -> list[str]:
    failures: list[str] = []
    try:
        payload = json.loads(notes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"{notes_path}: cannot read release notes: {error}"]

    guide_entries, guide_failures = _load_guide_entries(index_path)
    failures.extend(guide_failures)
    if payload.get("schemaVersion") != 1:
        failures.append("schemaVersion: expected 1")
    releases = payload.get("releases")
    if not isinstance(releases, list) or not releases:
        return failures + ["releases: expected non-empty list"]

    versions: list[str] = []
    keys: list[tuple[int, int, int, int, tuple[str, ...]]] = []
    for release_index, release in enumerate(releases):
        release_path = f"releases[{release_index}]"
        if not isinstance(release, dict):
            failures.append(f"{release_path}: expected object")
            continue
        version = release.get("version")
        key = _version_key(version) if isinstance(version, str) else None
        if key is None:
            failures.append(f"{release_path}.version: expected SemVer with v prefix")
        else:
            versions.append(version)
            keys.append(key)
        released_at = release.get("releasedAt")
        try:
            date.fromisoformat(released_at)
        except (TypeError, ValueError):
            failures.append(f"{release_path}.releasedAt: expected ISO date")
        _validate_safe_text(release.get("title"), f"{release_path}.title", failures)
        _validate_safe_text(release.get("summary"), f"{release_path}.summary", failures)
        items = release.get("items")
        if not isinstance(items, list) or not items:
            failures.append(f"{release_path}.items: expected non-empty list")
            continue
        for item_index, item in enumerate(items):
            item_path = f"{release_path}.items[{item_index}]"
            if not isinstance(item, dict):
                failures.append(f"{item_path}: expected object")
                continue
            if item.get("category") not in ALLOWED_CATEGORIES:
                failures.append(f"{item_path}.category: unsupported category")
            _validate_safe_text(item.get("title"), f"{item_path}.title", failures)
            _validate_safe_text(
                item.get("description"), f"{item_path}.description", failures
            )
            guide_id = item.get("guideId")
            if not isinstance(guide_id, str) or guide_id not in guide_entries:
                failures.append(f"{item_path}.guideId: unknown guide target")
            elif guide_entries[guide_id].roles:
                failures.append(
                    f"{item_path}.guideId: target is not visible to every role"
                )
            if "media" in item:
                _validate_media(
                    item["media"], f"{item_path}.media", static_root, failures
                )

    if len(versions) != len(set(versions)):
        failures.append("releases: duplicate version")
    if keys != sorted(keys, reverse=True):
        failures.append("releases: expected newest SemVer first")
    current_version = payload.get("currentVersion")
    if not versions or current_version != versions[0]:
        failures.append("currentVersion: expected latest release version")
    known_versions = set(versions)
    for guide_id, entry in guide_entries.items():
        if entry.updated_version and entry.updated_version not in known_versions:
            failures.append(
                f"guide:{guide_id}: unknown updated release {entry.updated_version}"
            )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate client-safe release notes.")
    parser.parse_args()
    failures = validate_release_notes()
    if failures:
        for failure in failures:
            print(failure)
        return 1
    print("Release notes validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
