from __future__ import annotations

import sys
from pathlib import Path

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
VALID_STATUSES = {"active", "draft", "accepted", "implemented", "superseded"}


def parse_manifest() -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for raw_line in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw_line.rstrip()
        if line.startswith("  - path:"):
            if current is not None:
                records.append(current)
            current = {"path": clean_value(line.split(":", 1)[1])}
            continue
        if current is None or not line.startswith("    "):
            continue
        key, sep, value = line.strip().partition(":")
        if sep:
            current[key] = clean_value(value)
    if current is not None:
        records.append(current)
    return records


def clean_value(value: str) -> str:
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    return value


def frontmatter(path: Path) -> dict[str, str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---":
        return {}
    result: dict[str, str] = {}
    for line in lines[1:]:
        if line == "---":
            return result
        key, sep, value = line.partition(":")
        if sep:
            result[key.strip()] = clean_value(value)
    return result


def discover_expected_docs() -> set[str]:
    docs = {str(path.relative_to(ROOT)) for path in (ROOT / "docs").rglob("*.md")}
    docs.add("README.md")
    docs.add("AGENTS.md")
    docs.add("config/README.md")
    docx = ROOT / "docs" / "shumeyko-partners-wb-unit-economics-client-tz.docx"
    if docx.exists():
        docs.add(str(docx.relative_to(ROOT)))
    return docs


def main() -> int:
    failures: list[str] = []
    if not MANIFEST.exists():
        print("Missing docs/manifest.yml")
        return 1

    records = parse_manifest()
    paths = [record.get("path", "") for record in records]
    if len(paths) != len(set(paths)):
        failures.append("manifest contains duplicate path entries")

    for record in records:
        missing = sorted(REQUIRED_KEYS - set(record))
        path_value = record.get("path", "<missing>")
        if missing:
            failures.append(f"{path_value}: missing keys {', '.join(missing)}")
            continue

        rel_path = record["path"]
        path = ROOT / rel_path
        if not path.exists():
            failures.append(f"{rel_path}: listed file does not exist")
            continue

        if record["status"] not in VALID_STATUSES:
            failures.append(f"{rel_path}: invalid status {record['status']!r}")

        if record["source_of_truth"] not in {"true", "false"}:
            failures.append(f"{rel_path}: source_of_truth must be true or false")

        if path.suffix == ".md" and rel_path.startswith(("docs/", "config/")):
            fm = frontmatter(path)
            if not fm:
                failures.append(f"{rel_path}: missing frontmatter")
                continue
            for key in ("title", "doc_type", "status", "updated_at"):
                if key not in fm:
                    failures.append(f"{rel_path}: frontmatter missing {key}")
            if fm.get("doc_type") != record["doc_type"]:
                failures.append(f"{rel_path}: doc_type differs from manifest")
            if fm.get("status") != record["status"]:
                failures.append(f"{rel_path}: status differs from manifest")

    listed = set(paths)
    missing_from_manifest = sorted(discover_expected_docs() - listed)
    for rel_path in missing_from_manifest:
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
