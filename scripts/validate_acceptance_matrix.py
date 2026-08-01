from __future__ import annotations

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from docs_metadata import date_text, load_frontmatter

ROOT = Path(__file__).resolve().parents[1]
MATRIX_GLOB = "config/acceptance/*.yml"

ALLOWED_STATUSES = {"pending", "passed", "failed", "blocked"}
ALLOWED_EVIDENCE_TYPES = {
    "ci",
    "git_record",
    "local_test",
    "production_command",
    "runbook_observation",
}
ALLOWED_ENVIRONMENTS = {"ci", "local", "repository", "test", "production"}
FULL_GIT_SHA = re.compile(r"[0-9a-f]{40}")
CI_CHECK_ID = re.compile(r"github-actions:[1-9][0-9]*:(quality|tests)")
GIT_RECORD_ID = re.compile(r"git:(commit:[0-9a-f]{40}|pr:[1-9][0-9]*)")
ACCEPTANCE_ID = re.compile(r"\b[A-Z]{2,}-AC-[0-9]{2}\b")


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _spec_index(root: Path) -> dict[str, tuple[Path, dict[str, Any], str]]:
    result: dict[str, tuple[Path, dict[str, Any], str]] = {}
    for path in sorted((root / "docs" / "specs").glob("*.md")):
        metadata, body = load_frontmatter(path)
        spec_id = metadata.get("spec_id")
        if isinstance(spec_id, str) and spec_id:
            result[spec_id] = (path, metadata, body)
    return result


def _validate_rfc3339(value: Any, label: str) -> list[str]:
    if not _non_empty_string(value):
        return [f"{label} must be a non-empty RFC3339 timestamp"]
    rendered = str(value)
    if rendered.endswith("Z"):
        rendered = rendered[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(rendered)
    except ValueError:
        return [f"{label} must be an RFC3339 timestamp"]
    if parsed.tzinfo is None:
        return [f"{label} must include a timezone offset"]
    return []


def _validate_repo_reference(root: Path, value: str, label: str) -> list[str]:
    path_text = value.split("#", 1)[0]
    if not path_text:
        return [f"{label} must start with a repository path"]
    target = root / path_text
    if not target.is_file():
        return [f"{label} references a missing file: {path_text}"]
    return []


def _validate_check_id(
    root: Path,
    evidence_type: str,
    check_id: Any,
    label: str,
) -> list[str]:
    if not _non_empty_string(check_id):
        return [f"{label}.check_id must be a non-empty string"]
    rendered = str(check_id)
    if evidence_type == "ci":
        if CI_CHECK_ID.fullmatch(rendered) is None:
            return [
                f"{label}.check_id must match "
                "github-actions:<run_id>:quality|tests"
            ]
        return []
    if evidence_type == "git_record":
        if GIT_RECORD_ID.fullmatch(rendered) is None:
            return [f"{label}.check_id must identify a full commit SHA or PR"]
        return []
    if evidence_type == "local_test":
        path_text, separator, test_id = rendered.partition("::")
        failures = _validate_repo_reference(root, path_text, f"{label}.check_id")
        if separator != "::" or not test_id:
            failures.append(f"{label}.check_id must include a pytest node id")
        elif not failures:
            text = (root / path_text).read_text(encoding="utf-8")
            test_name = test_id.split("[", 1)[0].split("::")[-1]
            if test_name not in text:
                failures.append(
                    f"{label}.check_id test does not exist: {test_name}"
                )
        return failures
    if evidence_type == "production_command":
        path_text = rendered.split(":", 1)[0]
        failures = _validate_repo_reference(root, path_text, f"{label}.check_id")
        if not path_text.startswith("scripts/") or not path_text.endswith(".py"):
            failures.append(
                f"{label}.check_id production command must reference scripts/*.py"
            )
        return failures
    if evidence_type == "runbook_observation":
        if "#" not in rendered:
            return [f"{label}.check_id must include a runbook section anchor"]
        return _validate_repo_reference(root, rendered, f"{label}.check_id")
    return []


def _validate_evidence(
    root: Path,
    value: Any,
    label: str,
    criterion_status: str,
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{label} must be a mapping"]
    failures: list[str] = []
    required_keys = {
        "type",
        "check_id",
        "expected_result",
        "observed_result",
        "git_revision",
        "environment",
        "evidence_date",
        "reference",
    }
    missing = sorted(required_keys - value.keys())
    if missing:
        failures.append(f"{label} missing keys: {', '.join(missing)}")

    evidence_type = value.get("type")
    if evidence_type not in ALLOWED_EVIDENCE_TYPES:
        failures.append(f"{label}.type is invalid: {evidence_type!r}")
    else:
        failures.extend(
            _validate_check_id(root, evidence_type, value.get("check_id"), label)
        )
    if not _non_empty_string(value.get("expected_result")):
        failures.append(f"{label}.expected_result must be a non-empty string")
    environment = value.get("environment")
    if environment not in ALLOWED_ENVIRONMENTS:
        failures.append(f"{label}.environment is invalid: {environment!r}")

    if criterion_status != "pending":
        if not _non_empty_string(value.get("observed_result")):
            failures.append(f"{label}.observed_result is required")
        revision = value.get("git_revision")
        if not isinstance(revision, str) or FULL_GIT_SHA.fullmatch(revision) is None:
            failures.append(f"{label}.git_revision must be a full lowercase Git SHA")
        failures.extend(
            _validate_rfc3339(value.get("evidence_date"), f"{label}.evidence_date")
        )
        reference = value.get("reference")
        if not _non_empty_string(reference):
            failures.append(f"{label}.reference is required")
        elif not str(reference).startswith(("https://", "docs/", "config/")):
            failures.append(
                f"{label}.reference must be HTTPS or a versioned evidence path"
            )
        elif str(reference).startswith(("docs/", "config/")):
            failures.extend(
                _validate_repo_reference(root, str(reference), f"{label}.reference")
            )
    return failures


def validate_matrix(path: Path, root: Path = ROOT) -> list[str]:
    label = str(path.relative_to(root)) if path.is_relative_to(root) else str(path)
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        return [f"{label}: cannot load YAML: {exc}"]
    if not isinstance(document, dict):
        return [f"{label}: root must be a mapping"]

    failures: list[str] = []
    if document.get("schema_version") != 1:
        failures.append(f"{label}: schema_version must be 1")
    if not _non_empty_string(document.get("release")):
        failures.append(f"{label}: release must be a non-empty string")
    if date_text(document.get("updated_at")) is None:
        failures.append(f"{label}: updated_at must be an ISO date string")

    criteria = document.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        return failures + [f"{label}: criteria must be a non-empty list"]

    specs = _spec_index(root)
    seen_ids: set[str] = set()
    criteria_by_spec: dict[str, list[dict[str, Any]]] = {}
    for index, criterion in enumerate(criteria):
        criterion_label = f"{label}: criteria[{index}]"
        if not isinstance(criterion, dict):
            failures.append(f"{criterion_label} must be a mapping")
            continue
        required_keys = {
            "scope",
            "spec_id",
            "criterion_id",
            "required",
            "owner",
            "status",
            "evidence",
        }
        missing = sorted(required_keys - criterion.keys())
        if missing:
            failures.append(
                f"{criterion_label} missing keys: {', '.join(missing)}"
            )

        criterion_id = criterion.get("criterion_id")
        if not _non_empty_string(criterion_id):
            failures.append(f"{criterion_label}.criterion_id must be non-empty")
        elif criterion_id in seen_ids:
            failures.append(f"{criterion_label}: duplicate criterion_id {criterion_id}")
        else:
            seen_ids.add(str(criterion_id))

        if not isinstance(criterion.get("required"), bool):
            failures.append(f"{criterion_label}.required must be boolean")
        if not _non_empty_string(criterion.get("owner")):
            failures.append(f"{criterion_label}.owner must be non-empty")
        status = criterion.get("status")
        if status not in ALLOWED_STATUSES:
            failures.append(f"{criterion_label}.status is invalid: {status!r}")

        spec_id = criterion.get("spec_id")
        spec = specs.get(spec_id) if isinstance(spec_id, str) else None
        if spec is None:
            failures.append(f"{criterion_label}: unknown spec_id {spec_id!r}")
        else:
            _, metadata, body = spec
            if criterion.get("scope") != metadata.get("truth_scope"):
                failures.append(
                    f"{criterion_label}: scope does not match spec truth_scope"
                )
            if _non_empty_string(criterion_id) and str(criterion_id) not in body:
                failures.append(
                    f"{criterion_label}: criterion_id is absent from spec: "
                    f"{criterion_id}"
                )
            criteria_by_spec.setdefault(str(spec_id), []).append(criterion)

        evidence = criterion.get("evidence")
        if not isinstance(evidence, list) or not evidence:
            failures.append(f"{criterion_label}.evidence must be a non-empty list")
        elif status in ALLOWED_STATUSES:
            for evidence_index, item in enumerate(evidence):
                failures.extend(
                    _validate_evidence(
                        root,
                        item,
                        f"{criterion_label}.evidence[{evidence_index}]",
                        str(status),
                    )
                )

    for spec_id, spec_criteria in criteria_by_spec.items():
        _, metadata, body = specs[spec_id]
        registered_ids = {
            str(item.get("criterion_id")) for item in spec_criteria
        }
        missing_ids = sorted(set(ACCEPTANCE_ID.findall(body)) - registered_ids)
        if missing_ids:
            failures.append(
                f"{label}: spec {spec_id} has unregistered acceptance criteria: "
                f"{', '.join(missing_ids)}"
            )
        if metadata.get("status") != "implemented":
            continue
        open_ids = [
            str(item.get("criterion_id"))
            for item in spec_criteria
            if item.get("required") is True and item.get("status") != "passed"
        ]
        if open_ids:
            failures.append(
                f"{label}: implemented spec {spec_id} has open required "
                f"criteria: {', '.join(open_ids)}"
            )
    return failures


def matrix_paths(root: Path = ROOT) -> list[Path]:
    return sorted(root.glob(MATRIX_GLOB))


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    paths = [ROOT / value for value in args] if args else matrix_paths()
    if not paths:
        print(f"no acceptance matrices found: {MATRIX_GLOB}", file=sys.stderr)
        return 1
    failures: list[str] = []
    for path in paths:
        failures.extend(validate_matrix(path))
    if failures:
        for failure in failures:
            print(failure, file=sys.stderr)
        return 1
    print(f"validated {len(paths)} acceptance matrix file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
