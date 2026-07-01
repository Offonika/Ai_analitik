from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALID_STATUSES = {"draft", "accepted", "implemented", "superseded"}
REQUIRED_KEYS = {
    "spec_id",
    "title",
    "doc_type",
    "domain",
    "status",
    "owner",
    "source_of_truth",
    "updated_at",
}


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


def inline_list(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return []
    inner = value[1:-1].strip()
    if not inner:
        return []
    return [item.strip().strip('"').strip("'") for item in inner.split(",")]


def validate_spec(path: Path) -> list[str]:
    failures: list[str] = []
    rel_path = path.relative_to(ROOT)
    fm = frontmatter(path)
    if not fm:
        return [f"{rel_path}: missing YAML frontmatter"]

    missing = sorted(REQUIRED_KEYS - set(fm))
    if missing:
        failures.append(f"{rel_path}: missing keys {', '.join(missing)}")

    if fm.get("doc_type") != "spec":
        failures.append(f"{rel_path}: doc_type must be spec")
    if fm.get("status") not in VALID_STATUSES:
        failures.append(f"{rel_path}: invalid status {fm.get('status')!r}")
    if fm.get("source_of_truth") not in {"true", "false"}:
        failures.append(f"{rel_path}: source_of_truth must be true or false")

    for key in ("related_code", "related_tests"):
        for listed in inline_list(fm.get(key, "")):
            target = ROOT / listed
            if not target.exists():
                failures.append(f"{rel_path}: {key} path does not exist: {listed}")

    return failures


def main() -> int:
    if len(sys.argv) > 1:
        spec_paths = [ROOT / arg for arg in sys.argv[1:]]
    else:
        spec_paths = sorted((ROOT / "docs" / "specs").glob("*.md"))

    failures: list[str] = []
    for path in spec_paths:
        if not path.exists():
            failures.append(f"{path.relative_to(ROOT)}: file does not exist")
            continue
        failures.extend(validate_spec(path))

    if failures:
        print("Spec validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print(f"Spec validation passed ({len(spec_paths)} file(s)).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
