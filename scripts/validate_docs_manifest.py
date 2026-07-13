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
RECONCILED_RE = re.compile(r"^(?P<path>.+?)\s+@\s+(?P<date>\d{4}-\d{2}-\d{2})$")
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
        if (
            path.suffix == ".md"
            and rel_path.startswith(("docs/", "config/"))
        ):
            validate_markdown_metadata(rel_path, record, failures)

    failures.extend(validate_truth_precedence(records))

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
