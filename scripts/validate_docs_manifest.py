from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any

from docs_metadata import (
    date_text,
    has_superseded_banner,
    load_frontmatter,
    load_yaml,
    string_list,
    validate_truth_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs" / "manifest.yml"
DOCS_INDEX = ROOT / "docs" / "index.md"
REQUIRED_KEYS = {
    "path",
    "title",
    "doc_type",
    "status",
    "audience",
    "source_of_truth",
    "summary",
}
FRONTMATTER_PARITY_KEYS = {
    "title",
    "doc_type",
    "status",
    "audience",
    "source_of_truth",
}
VALID_STATUSES = {"active", "draft", "accepted", "implemented", "superseded"}
CHANGELOG_REQUIRED_SPECS = {
    "docs/specs/marketplace-unit-economics-ozon-integration.md",
    "docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md",
    "docs/specs/wb-unit-economics-excel-mvp-implementation.md",
}
RECONCILED_RE = re.compile(r"^(?P<path>.+?)\s+@\s+(?P<date>\d{4}-\d{2}-\d{2})$")
TRUTH_TABLE_ROW_RE = re.compile(
    r"^\| `(?P<scope>[^`]+)` \| `(?P<path>[^`]+)` \| "
    r"(?P<priority>\d+) \|(?:.*\|)?$",
    re.MULTILINE,
)
CONTOUR_STATUS_ROW_RE = re.compile(
    r"^\| `[^`]+` \| `(?P<path>[^`]+)` \| \d+ \| "
    r"(?P<status>[a-z-]+) \|",
    re.MULTILINE,
)
CHANGELOG_HEADING_RE = re.compile(r"^# Changelog\s*$", re.MULTILINE)
CLIENT_TZ_DATE_RE = re.compile(
    r"^Дата актуализации: (?P<day>\d{1,2}) (?P<month>[а-яё]+) (?P<year>\d{4})\.$",
    re.MULTILINE,
)
RU_MONTHS = {
    "января": 1,
    "февраля": 2,
    "марта": 3,
    "апреля": 4,
    "мая": 5,
    "июня": 6,
    "июля": 7,
    "августа": 8,
    "сентября": 9,
    "октября": 10,
    "ноября": 11,
    "декабря": 12,
}


def parse_manifest() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    payload = load_yaml(MANIFEST)
    if not isinstance(payload, dict):
        raise ValueError("manifest root must be a mapping")
    documents = payload.get("documents")
    if not isinstance(documents, list) or not all(
        isinstance(record, dict) for record in documents
    ):
        raise ValueError("documents must be a list of mappings")
    return payload, documents


def discover_expected_docs() -> set[str]:
    docs = {str(path.relative_to(ROOT)) for path in (ROOT / "docs").rglob("*.md")}
    docs.update({"README.md", "AGENTS.md", "config/README.md"})
    docx = ROOT / "docs" / "shumeyko-partners-wb-unit-economics-client-tz.docx"
    if docx.exists():
        docs.add(str(docx.relative_to(ROOT)))
    return docs


def _validate_reference(
    failures: list[str], rel_path: str, key: str, reference: str
) -> None:
    if not (ROOT / reference).exists():
        failures.append(f"{rel_path}: {key} path does not exist: {reference}")


def validate_markdown_metadata(
    rel_path: str, record: dict[str, Any], failures: list[str]
) -> None:
    path = ROOT / rel_path
    metadata, body = load_frontmatter(path)
    if not metadata:
        failures.append(f"{rel_path}: missing YAML frontmatter")
        return

    required = FRONTMATTER_PARITY_KEYS | {"updated_at"}
    for key in sorted(required - metadata.keys()):
        failures.append(f"{rel_path}: frontmatter missing {key}")

    for key in sorted(FRONTMATTER_PARITY_KEYS):
        if key in metadata and metadata[key] != record[key]:
            failures.append(f"{rel_path}: {key} differs from manifest")

    if record.get("source_of_truth") is True:
        for key in ("truth_scope", "truth_priority"):
            if metadata.get(key) != record.get(key):
                failures.append(f"{rel_path}: {key} differs from manifest")

    failures.extend(validate_truth_metadata(metadata, rel_path))

    if date_text(metadata.get("updated_at")) is None:
        failures.append(f"{rel_path}: updated_at must be an ISO date")

    source_spec = metadata.get("source_spec")
    if source_spec is not None:
        if not isinstance(source_spec, str):
            failures.append(f"{rel_path}: source_spec must be a path string")
        else:
            _validate_reference(failures, rel_path, "source_spec", source_spec)

    reconciled = metadata.get("last_reconciled_with")
    if reconciled is not None:
        match = RECONCILED_RE.fullmatch(str(reconciled))
        if not match:
            failures.append(
                f"{rel_path}: last_reconciled_with must be '<path> @ YYYY-MM-DD'"
            )
        else:
            source_path = ROOT / match.group("path")
            if not source_path.exists():
                failures.append(
                    f"{rel_path}: reconciled source does not exist: "
                    f"{match.group('path')}"
                )
            else:
                source_metadata, _ = load_frontmatter(source_path)
                source_date = date_text(source_metadata.get("updated_at"))
                if source_date != match.group("date"):
                    failures.append(
                        f"{rel_path}: last_reconciled_with date "
                        f"{match.group('date')} != source updated_at {source_date}"
                    )
                own_date = date_text(metadata.get("updated_at"))
                if own_date is not None and own_date < match.group("date"):
                    failures.append(
                        f"{rel_path}: updated_at {own_date} is older than "
                        f"last_reconciled_with {match.group('date')}"
                    )

    if rel_path == "docs/client-tz.md":
        visible_match = CLIENT_TZ_DATE_RE.search(body)
        if visible_match is None:
            failures.append(f"{rel_path}: visible update date is missing")
        else:
            month = RU_MONTHS.get(visible_match.group("month"))
            visible_date = None
            if month is not None:
                visible_date = (
                    f"{int(visible_match.group('year')):04d}-{month:02d}-"
                    f"{int(visible_match.group('day')):02d}"
                )
            if visible_date != date_text(metadata.get("updated_at")):
                failures.append(
                    f"{rel_path}: visible update date {visible_date!r} differs "
                    f"from updated_at {date_text(metadata.get('updated_at'))!r}"
                )

    if metadata.get("status") == "draft" and metadata.get("source_of_truth") is True:
        failures.append(f"{rel_path}: draft document cannot be source_of_truth")

    if metadata.get("status") == "superseded":
        replacements = string_list(metadata.get("superseded_by"))
        if not replacements:
            failures.append(f"{rel_path}: superseded document needs superseded_by")
        for replacement in replacements:
            _validate_reference(failures, rel_path, "superseded_by", replacement)
        if metadata.get("source_of_truth") is not False:
            failures.append(
                f"{rel_path}: superseded document cannot be source_of_truth"
            )
        if not has_superseded_banner(body):
            failures.append(f"{rel_path}: superseded document needs a visible banner")


def validate_truth_precedence(records: list[dict[str, Any]]) -> list[str]:
    """Require one unambiguous highest-priority truth document per scope."""
    failures: list[str] = []
    truth_by_scope: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record.get("source_of_truth") is True and isinstance(
            record.get("truth_scope"), str
        ):
            truth_by_scope.setdefault(record["truth_scope"], []).append(record)
    for scope, scoped_records in sorted(truth_by_scope.items()):
        priorities = [
            record.get("truth_priority")
            for record in scoped_records
            if isinstance(record.get("truth_priority"), int)
            and not isinstance(record.get("truth_priority"), bool)
        ]
        if not priorities:
            continue
        highest = max(priorities)
        leaders = [
            record["path"]
            for record in scoped_records
            if record.get("truth_priority") == highest
        ]
        if len(leaders) != 1:
            failures.append(
                f"truth_scope {scope!r} must have one highest-priority document; "
                f"found {', '.join(leaders)}"
            )
    return failures


def validate_routing_metadata(records: list[dict[str, Any]]) -> list[str]:
    """Require compact search metadata on each canonical scope leader."""
    failures: list[str] = []
    truth_by_scope: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        scope = record.get("truth_scope")
        priority = record.get("truth_priority")
        if (
            record.get("source_of_truth") is True
            and isinstance(scope, str)
            and isinstance(priority, int)
            and not isinstance(priority, bool)
        ):
            truth_by_scope.setdefault(scope, []).append(record)

    for scope, scoped_records in sorted(truth_by_scope.items()):
        highest = max(int(record["truth_priority"]) for record in scoped_records)
        leaders = [
            record for record in scoped_records if record["truth_priority"] == highest
        ]
        if len(leaders) != 1:
            continue
        leader = leaders[0]
        path = str(leader.get("path", scope))
        read_when = leader.get("read_when")
        if not isinstance(read_when, str) or not read_when.strip():
            failures.append(f"{path}: canonical route needs non-empty read_when")
        raw_terms = leader.get("search_terms")
        terms = string_list(raw_terms)
        if (
            not isinstance(raw_terms, list)
            or len(terms) < 2
            or len(terms) != len(raw_terms)
            or any(not term.strip() for term in terms)
        ):
            failures.append(
                f"{path}: canonical route needs at least two search_terms"
            )
    return failures


def validate_operational_docs(records: list[dict[str, Any]]) -> list[str]:
    """Keep body-free operational navigation explicit and unambiguous."""

    failures: list[str] = []
    records_by_path = {str(record.get("path", "")): record for record in records}
    canonical_paths: set[str] = set()
    truth_by_scope: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        scope = record.get("truth_scope")
        priority = record.get("truth_priority")
        if (
            record.get("source_of_truth") is True
            and isinstance(scope, str)
            and isinstance(priority, int)
            and not isinstance(priority, bool)
        ):
            truth_by_scope.setdefault(scope, []).append(record)
    for scoped_records in truth_by_scope.values():
        highest = max(int(record["truth_priority"]) for record in scoped_records)
        leaders = [
            record for record in scoped_records if record["truth_priority"] == highest
        ]
        if len(leaders) == 1:
            canonical_paths.add(str(leaders[0]["path"]))

    referenced_by: dict[str, str] = {}
    for record in records:
        raw_links = record.get("operational_docs")
        if raw_links is None:
            continue
        source_path = str(record.get("path", "<missing>"))
        if source_path not in canonical_paths:
            failures.append(
                f"{source_path}: operational_docs is allowed only on a canonical route"
            )
        links = string_list(raw_links)
        if (
            not isinstance(raw_links, list)
            or len(links) != len(raw_links)
            or any(not link.strip() for link in links)
        ):
            failures.append(
                f"{source_path}: operational_docs must be a list of non-empty paths"
            )
            continue
        if len(links) != len(set(links)):
            failures.append(f"{source_path}: operational_docs contains duplicates")
        for link in dict.fromkeys(links):
            previous = referenced_by.setdefault(link, source_path)
            if previous != source_path:
                failures.append(
                    f"{link}: operational doc is linked by both {previous} and "
                    f"{source_path}"
                )
            target = records_by_path.get(link)
            if target is None:
                failures.append(
                    f"{source_path}: operational_docs path is not registered: {link}"
                )
                continue
            if target.get("status") != "active":
                failures.append(f"{link}: operational doc must have status active")
            if target.get("source_of_truth") is not False:
                failures.append(f"{link}: operational doc must not be source_of_truth")
            if target.get("doc_type") != "runbook":
                failures.append(f"{link}: operational doc must have doc_type runbook")
    return failures


def validate_changelog_registration(
    records: list[dict[str, Any]],
    required_specs: set[str] | None = None,
) -> list[str]:
    """Keep long source specs linked to registered, back-referenced changelogs."""
    failures: list[str] = []
    required = CHANGELOG_REQUIRED_SPECS if required_specs is None else required_specs
    records_by_path = {str(record.get("path")): record for record in records}

    for rel_path in sorted(records_by_path):
        path = ROOT / rel_path
        if path.suffix != ".md" or not path.exists():
            continue
        metadata, body = load_frontmatter(path)
        changelog_path = metadata.get("changelog_path")
        if rel_path in required and changelog_path is None:
            failures.append(f"{rel_path}: required changelog_path is missing")
            continue
        if changelog_path is None:
            continue
        if not isinstance(changelog_path, str):
            failures.append(f"{rel_path}: changelog_path must be a path string")
            continue

        changelog_record = records_by_path.get(changelog_path)
        if changelog_record is None:
            failures.append(
                f"{rel_path}: changelog_path is not registered: {changelog_path}"
            )
            continue
        if changelog_record.get("doc_type") != "changelog":
            failures.append(
                f"{rel_path}: changelog_path must reference doc_type changelog: "
                f"{changelog_path}"
            )
        changelog_file = ROOT / changelog_path
        if not changelog_file.exists():
            failures.append(
                f"{rel_path}: changelog_path does not exist: {changelog_path}"
            )
            continue
        changelog_metadata, _ = load_frontmatter(changelog_file)
        if changelog_metadata.get("source_spec") != rel_path:
            failures.append(
                f"{changelog_path}: source_spec must point back to {rel_path}"
            )
        source_updated_at = date_text(metadata.get("updated_at"))
        changelog_updated_at = date_text(changelog_metadata.get("updated_at"))
        if (
            source_updated_at is not None
            and changelog_updated_at is not None
            and changelog_updated_at < source_updated_at
        ):
            failures.append(
                f"{changelog_path}: updated_at {changelog_updated_at} is older "
                f"than source spec {source_updated_at}"
            )

        changelog_heading = CHANGELOG_HEADING_RE.search(body)
        if changelog_heading is None:
            failures.append(f"{rel_path}: externalized changelog heading is missing")
            continue
        inline_tail = body[changelog_heading.end() :].strip()
        inline_lines = [line for line in inline_tail.splitlines() if line.strip()]
        if f"`{changelog_path}`" not in inline_tail:
            failures.append(
                f"{rel_path}: inline changelog must point to {changelog_path}"
            )
        if len(inline_lines) > 3 or any(
            line.lstrip().startswith(("- ", "* ", "#")) for line in inline_lines
        ):
            failures.append(
                f"{rel_path}: inline changelog must contain only the external "
                "history pointer"
            )
    return failures


def validate_index_consistency(
    records: list[dict[str, Any]], index_text: str
) -> list[str]:
    """Keep human-readable truth and status tables aligned with the manifest."""
    failures: list[str] = []
    truth_by_scope: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        scope = record.get("truth_scope")
        priority = record.get("truth_priority")
        if (
            record.get("source_of_truth") is True
            and isinstance(scope, str)
            and isinstance(priority, int)
            and not isinstance(priority, bool)
        ):
            truth_by_scope.setdefault(scope, []).append(record)

    expected_truth: dict[str, tuple[str, int]] = {}
    for scope, scoped_records in truth_by_scope.items():
        highest = max(int(record["truth_priority"]) for record in scoped_records)
        leaders = [
            record for record in scoped_records if record["truth_priority"] == highest
        ]
        if len(leaders) == 1:
            expected_truth[scope] = (str(leaders[0]["path"]), highest)

    indexed_truth: dict[str, tuple[str, int]] = {}
    for match in TRUTH_TABLE_ROW_RE.finditer(index_text):
        scope = match.group("scope")
        if scope in indexed_truth:
            failures.append(f"docs/index.md: duplicate truth_scope row {scope!r}")
            continue
        indexed_truth[scope] = (
            match.group("path"),
            int(match.group("priority")),
        )

    for scope, expected in sorted(expected_truth.items()):
        actual = indexed_truth.get(scope)
        if actual is None:
            failures.append(f"docs/index.md: missing truth_scope row {scope!r}")
        elif actual != expected:
            failures.append(
                f"docs/index.md: truth_scope {scope!r} differs from manifest; "
                f"index={actual!r}, manifest={expected!r}"
            )
    for scope in sorted(indexed_truth.keys() - expected_truth.keys()):
        failures.append(f"docs/index.md: unknown truth_scope row {scope!r}")

    records_by_path = {str(record.get("path")): record for record in records}
    for match in CONTOUR_STATUS_ROW_RE.finditer(index_text):
        path = match.group("path")
        record = records_by_path.get(path)
        if record is None:
            failures.append(
                f"docs/index.md: contour path is absent from manifest: {path}"
            )
            continue
        status = match.group("status")
        if status != record.get("status"):
            failures.append(
                f"docs/index.md: status for {path} is {status!r}, "
                f"manifest has {record.get('status')!r}"
            )
    return failures


def main() -> int:
    failures: list[str] = []
    if not MANIFEST.exists():
        print("Missing docs/manifest.yml")
        return 1

    try:
        manifest, records = parse_manifest()
    except (ValueError, OSError) as exc:
        print(f"Docs manifest validation failed: {exc}")
        return 1

    manifest_date = date_text(manifest.get("updated_at"))
    if manifest_date is None:
        failures.append("docs/manifest.yml: updated_at must be an ISO date")

    paths = [record.get("path", "") for record in records]
    if len(paths) != len(set(paths)):
        failures.append("manifest contains duplicate path entries")

    for record in records:
        rel_path = str(record.get("path", "<missing>"))
        missing = sorted(REQUIRED_KEYS - record.keys())
        if missing:
            failures.append(f"{rel_path}: missing keys {', '.join(missing)}")
            continue
        path = ROOT / rel_path
        if not path.exists():
            failures.append(f"{rel_path}: listed file does not exist")
            continue
        if record["status"] not in VALID_STATUSES:
            failures.append(f"{rel_path}: invalid status {record['status']!r}")
        if not isinstance(record["audience"], list) or not record["audience"]:
            failures.append(f"{rel_path}: audience must be a non-empty list")
        if not isinstance(record["source_of_truth"], bool):
            failures.append(f"{rel_path}: source_of_truth must be boolean")
        failures.extend(validate_truth_metadata(record, rel_path))
        if path.suffix == ".md" and rel_path.startswith(("docs/", "config/")):
            validate_markdown_metadata(rel_path, record, failures)

    failures.extend(validate_truth_precedence(records))
    failures.extend(validate_routing_metadata(records))
    failures.extend(validate_operational_docs(records))
    failures.extend(validate_changelog_registration(records))
    if DOCS_INDEX.exists():
        failures.extend(
            validate_index_consistency(
                records,
                DOCS_INDEX.read_text(encoding="utf-8"),
            )
        )
    else:
        failures.append("docs/index.md: file is missing")

    registered_dates: list[str] = []
    for record in records:
        rel_path = str(record.get("path", ""))
        path = ROOT / rel_path
        if path.suffix != ".md" or not path.exists():
            continue
        metadata, _ = load_frontmatter(path)
        updated = date_text(metadata.get("updated_at"))
        if updated is not None:
            registered_dates.append(updated)
    if manifest_date is not None and registered_dates:
        newest_document_date = max(registered_dates)
        if manifest_date < newest_document_date:
            failures.append(
                "docs/manifest.yml: updated_at "
                f"{manifest_date} is older than document date {newest_document_date}"
            )

    listed = set(paths)
    for rel_path in sorted(discover_expected_docs() - listed):
        failures.append(f"{rel_path}: document is not listed in docs/manifest.yml")

    if failures:
        print("Docs manifest validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Docs manifest is valid ({len(records)} entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
