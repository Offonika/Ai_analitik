from __future__ import annotations

import sys
from pathlib import Path

from docs_metadata import (
    date_text,
    has_superseded_banner,
    load_frontmatter,
    string_list,
    validate_truth_metadata,
)

ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"draft", "accepted", "implemented", "superseded"}
REQUIRED_KEYS = {
    "spec_id",
    "title",
    "doc_type",
    "domain",
    "status",
    "owner",
    "audience",
    "source_of_truth",
    "updated_at",
}


def _reference_exists(reference: str, spec_ids: set[str]) -> bool:
    return reference in spec_ids or (ROOT / reference).exists()


def validate_spec(path: Path, spec_ids: set[str] | None = None) -> list[str]:
    failures: list[str] = []
    rel_path = path.relative_to(ROOT)
    metadata, body = load_frontmatter(path)
    if not metadata:
        return [f"{rel_path}: missing YAML frontmatter"]

    missing = sorted(REQUIRED_KEYS - metadata.keys())
    if missing:
        failures.append(f"{rel_path}: missing keys {', '.join(missing)}")
    if metadata.get("doc_type") != "spec":
        failures.append(f"{rel_path}: doc_type must be spec")
    if metadata.get("status") not in VALID_STATUSES:
        failures.append(f"{rel_path}: invalid status {metadata.get('status')!r}")
    if not isinstance(metadata.get("audience"), list) or not metadata.get("audience"):
        failures.append(f"{rel_path}: audience must be a non-empty list")
    if not isinstance(metadata.get("source_of_truth"), bool):
        failures.append(f"{rel_path}: source_of_truth must be boolean")
    if date_text(metadata.get("updated_at")) is None:
        failures.append(f"{rel_path}: updated_at must be an ISO date")
    if metadata.get("status") == "draft" and metadata.get("source_of_truth") is True:
        failures.append(f"{rel_path}: draft spec cannot be source_of_truth")
    failures.extend(validate_truth_metadata(metadata, str(rel_path)))

    for key in ("related_code", "related_tests"):
        value = metadata.get(key, [])
        listed = string_list(value)
        if value is not None and not isinstance(value, (str, list)):
            failures.append(f"{rel_path}: {key} must be a string or list")
        elif isinstance(value, list) and len(listed) != len(value):
            failures.append(f"{rel_path}: {key} entries must be strings")
        for target_path in listed:
            if not (ROOT / target_path).exists():
                failures.append(
                    f"{rel_path}: {key} path does not exist: {target_path}"
                )

    known_ids = spec_ids or set()
    for key in ("depends_on", "related_specs", "superseded_by"):
        for reference in string_list(metadata.get(key)):
            if not _reference_exists(reference, known_ids):
                failures.append(f"{rel_path}: unknown {key} reference: {reference}")

    for reference in string_list(metadata.get("supersedes")):
        if reference.startswith("legacy_"):
            continue
        if not _reference_exists(reference, known_ids):
            failures.append(f"{rel_path}: unknown supersedes reference: {reference}")

    if metadata.get("status") == "superseded":
        replacements = string_list(metadata.get("superseded_by"))
        if not replacements:
            failures.append(f"{rel_path}: superseded spec needs superseded_by")
        if metadata.get("source_of_truth") is not False:
            failures.append(f"{rel_path}: superseded spec cannot be source_of_truth")
        if not has_superseded_banner(body):
            failures.append(f"{rel_path}: superseded spec needs a visible banner")

    if metadata.get("status") == "implemented":
        if not string_list(metadata.get("related_code")):
            failures.append(f"{rel_path}: implemented spec needs related_code")
        if not string_list(metadata.get("related_tests")):
            failures.append(f"{rel_path}: implemented spec needs related_tests")

    return failures


def validate_dependency_graph(
    metadata_by_path: dict[Path, dict], spec_ids: dict[str, Path]
) -> list[str]:
    """Return failures when spec implementation dependencies contain a cycle."""
    graph: dict[Path, list[Path]] = {path: [] for path in metadata_by_path}
    for path, metadata in metadata_by_path.items():
        for reference in string_list(metadata.get("depends_on")):
            target = spec_ids.get(reference)
            if target is None:
                candidate = ROOT / reference
                if candidate in metadata_by_path:
                    target = candidate
            if target is not None:
                graph[path].append(target)

    failures: list[str] = []
    visiting: list[Path] = []
    visited: set[Path] = set()

    def visit(path: Path) -> None:
        if path in visited:
            return
        if path in visiting:
            start = visiting.index(path)
            cycle = visiting[start:] + [path]
            rendered = " -> ".join(str(item.relative_to(ROOT)) for item in cycle)
            failure = f"spec dependency cycle: {rendered}"
            if failure not in failures:
                failures.append(failure)
            return
        visiting.append(path)
        for target in graph[path]:
            visit(target)
        visiting.pop()
        visited.add(path)

    for path in sorted(graph):
        visit(path)
    return failures


def main() -> int:
    if len(sys.argv) > 1:
        spec_paths = [ROOT / arg for arg in sys.argv[1:]]
    else:
        spec_paths = sorted((ROOT / "docs" / "specs").glob("*.md"))

    failures: list[str] = []
    all_specs = sorted((ROOT / "docs" / "specs").glob("*.md"))
    spec_ids: dict[str, Path] = {}
    metadata_by_path: dict[Path, dict] = {}
    for path in all_specs:
        metadata, _ = load_frontmatter(path)
        metadata_by_path[path] = metadata
        spec_id = metadata.get("spec_id")
        if not isinstance(spec_id, str) or not spec_id:
            continue
        if spec_id in spec_ids:
            failures.append(
                f"{path.relative_to(ROOT)}: duplicate spec_id also used by "
                f"{spec_ids[spec_id].relative_to(ROOT)}"
            )
        spec_ids[spec_id] = path

    for path, metadata in metadata_by_path.items():
        rel_path = str(path.relative_to(ROOT))
        spec_id = str(metadata.get("spec_id") or "")
        for reference in string_list(metadata.get("supersedes")):
            if reference.startswith("legacy_"):
                continue
            target = spec_ids.get(reference) or (ROOT / reference)
            target_metadata = metadata_by_path.get(target)
            if target_metadata is None:
                continue
            if target_metadata.get("status") != "superseded":
                failures.append(
                    f"{rel_path}: supersedes target is not superseded: {reference}"
                )
            reverse = string_list(target_metadata.get("superseded_by"))
            if rel_path not in reverse and spec_id not in reverse:
                failures.append(
                    f"{rel_path}: supersedes target lacks reciprocal "
                    f"superseded_by: {reference}"
                )

    failures.extend(validate_dependency_graph(metadata_by_path, spec_ids))

    for path in spec_paths:
        if not path.exists():
            failures.append(f"{path.relative_to(ROOT)}: file does not exist")
            continue
        failures.extend(validate_spec(path, set(spec_ids)))

    if failures:
        print("Spec validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Spec validation passed ({len(spec_paths)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
