from __future__ import annotations

import copy
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_acceptance_matrix  # noqa: E402


def _write_fixture(tmp_path: Path, *, spec_status: str = "accepted") -> Path:
    spec_path = tmp_path / "docs" / "specs" / "runtime.md"
    spec_path.parent.mkdir(parents=True)
    spec_path.write_text(
        "\n".join(
            [
                "---",
                'spec_id: "runtime-spec"',
                'title: "Runtime"',
                "doc_type: spec",
                'domain: "test"',
                f"status: {spec_status}",
                'owner: "engineering"',
                'audience: ["engineering"]',
                "source_of_truth: true",
                "truth_scope: runtime-contours",
                "truth_priority: 100",
                'updated_at: "2026-08-01"',
                "---",
                "",
                "# Acceptance Criteria",
                "",
                "- RC-AC-01 is stable.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    script_path = tmp_path / "scripts" / "check_runtime.py"
    script_path.parent.mkdir(parents=True)
    script_path.write_text("def main():\n    return 0\n", encoding="utf-8")
    test_path = tmp_path / "tests" / "test_runtime.py"
    test_path.parent.mkdir(parents=True)
    test_path.write_text(
        "def test_runtime_is_healthy():\n    assert True\n", encoding="utf-8"
    )
    matrix_path = tmp_path / "config" / "acceptance" / "release.yml"
    matrix_path.parent.mkdir(parents=True)
    matrix_path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "release": "test",
                "updated_at": "2026-08-01",
                "criteria": [
                    {
                        "scope": "runtime-contours",
                        "spec_id": "runtime-spec",
                        "criterion_id": "RC-AC-01",
                        "required": True,
                        "owner": "engineering",
                        "status": "pending",
                        "evidence": [
                            {
                                "type": "production_command",
                                "check_id": "scripts/check_runtime.py:production",
                                "expected_result": "Health is ok.",
                                "observed_result": None,
                                "git_revision": None,
                                "environment": "production",
                                "evidence_date": None,
                                "reference": "docs/runbooks/runtime.md#health",
                            }
                        ],
                    }
                ],
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return matrix_path


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _save(path: Path, value: dict) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def test_repository_acceptance_matrix_is_valid() -> None:
    failures = []
    for path in validate_acceptance_matrix.matrix_paths(ROOT):
        failures.extend(validate_acceptance_matrix.validate_matrix(path, ROOT))
    assert failures == []


def test_validator_rejects_unknown_criterion_and_command(tmp_path: Path) -> None:
    matrix_path = _write_fixture(tmp_path)
    document = _load(matrix_path)
    document["criteria"][0]["criterion_id"] = "RC-AC-99"
    document["criteria"][0]["evidence"][0]["check_id"] = (
        "scripts/missing.py:production"
    )
    _save(matrix_path, document)

    failures = validate_acceptance_matrix.validate_matrix(matrix_path, tmp_path)

    assert any("criterion_id is absent from spec" in item for item in failures)
    assert any("references a missing file" in item for item in failures)


def test_validator_rejects_incomplete_passed_evidence(tmp_path: Path) -> None:
    matrix_path = _write_fixture(tmp_path)
    document = _load(matrix_path)
    document["criteria"][0]["status"] = "passed"
    _save(matrix_path, document)

    failures = validate_acceptance_matrix.validate_matrix(matrix_path, tmp_path)

    assert any("observed_result is required" in item for item in failures)
    assert any("git_revision must be" in item for item in failures)
    assert any("evidence_date must be" in item for item in failures)


def test_validator_blocks_implemented_spec_with_open_required_criterion(
    tmp_path: Path,
) -> None:
    matrix_path = _write_fixture(tmp_path, spec_status="implemented")

    failures = validate_acceptance_matrix.validate_matrix(matrix_path, tmp_path)

    assert any(
        "implemented spec runtime-spec has open required criteria: RC-AC-01"
        in item
        for item in failures
    )


def test_validator_checks_local_pytest_node_id(tmp_path: Path) -> None:
    matrix_path = _write_fixture(tmp_path)
    document = _load(matrix_path)
    evidence = document["criteria"][0]["evidence"][0]
    evidence.update(
        {
            "type": "local_test",
            "check_id": "tests/test_runtime.py::test_missing",
            "environment": "local",
        }
    )
    _save(matrix_path, document)

    failures = validate_acceptance_matrix.validate_matrix(matrix_path, tmp_path)

    assert any("test does not exist: test_missing" in item for item in failures)


def test_validator_rejects_duplicate_criterion_id(tmp_path: Path) -> None:
    matrix_path = _write_fixture(tmp_path)
    document = _load(matrix_path)
    document["criteria"].append(copy.deepcopy(document["criteria"][0]))
    _save(matrix_path, document)

    failures = validate_acceptance_matrix.validate_matrix(matrix_path, tmp_path)

    assert any("duplicate criterion_id RC-AC-01" in item for item in failures)


def test_validator_rejects_invalid_matrix_date_and_unregistered_spec_id(
    tmp_path: Path,
) -> None:
    matrix_path = _write_fixture(tmp_path)
    spec_path = tmp_path / "docs" / "specs" / "runtime.md"
    spec_path.write_text(
        spec_path.read_text(encoding="utf-8") + "- RC-AC-02 is also stable.\n",
        encoding="utf-8",
    )
    document = _load(matrix_path)
    document["updated_at"] = "not-a-date"
    _save(matrix_path, document)

    failures = validate_acceptance_matrix.validate_matrix(matrix_path, tmp_path)

    assert any("updated_at must be an ISO date string" in item for item in failures)
    assert any(
        "unregistered acceptance criteria: RC-AC-02" in item for item in failures
    )
