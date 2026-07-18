from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import docs_route  # noqa: E402
from docs_route import (  # noqa: E402
    find_routes,
    load_route_records,
    render_generated_jsonl,
    render_route,
)
from validate_docs_manifest import validate_routing_metadata  # noqa: E402
from validate_specs import validate_ai_sections, validate_anchors  # noqa: E402


def test_scope_returns_one_canonical_development_route() -> None:
    matches = find_routes(
        load_route_records(),
        scope="development-workflow",
        limit=5,
    )

    assert len(matches) == 1
    _score, record = matches[0]
    assert record.canonical is True
    assert record.path.endswith("wb-unit-economics-ai-git-workflow.md")
    assert dict(record.ai_sections)["routing_contract"] == (
        "Documentation Routing Contract"
    )


def test_logistics_route_exposes_operational_runbook_without_body() -> None:
    score, record = find_routes(
        load_route_records(),
        scope="logistics-cost-analysis",
        limit=1,
    )[0]

    rendered = render_route(score, record)

    assert "operational_docs (verify current state):" in rendered
    assert "docs/runbooks/wb-logistics-v4-continuation.md ::" in rendered
    assert "# Текущее состояние" not in rendered
    assert len(record.operational_docs) == 1


def test_query_routes_report_draft_retention() -> None:
    matches = find_routes(
        load_route_records(),
        query="удалить старые черновики отчетов",
        limit=3,
    )

    assert matches
    assert matches[0][1].truth_scope == "source-retention"


def test_path_routes_report_draft_retention() -> None:
    matches = find_routes(
        load_route_records(),
        path="scripts/prune_report_drafts.py",
        limit=3,
    )

    assert [record.truth_scope for _score, record in matches] == [
        "source-retention"
    ]


def test_shared_path_lists_scopes_without_expanding_routes(capsys) -> None:
    path = "src/wb_unit_economics/web/source_refresh.py"
    records = load_route_records()
    expected = find_routes(
        records,
        path=path,
        limit=len(records),
    )
    assert len(expected) > 1

    exit_code = docs_route.main(["--path", path])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert f"matches: {len(expected)}" in output
    for _score, record in expected:
        assert f"  - {record.truth_scope} -> {record.path} " in output
    assert output.count(" -> ") == len(expected)
    assert "next: rerun with --scope <scope>" in output
    assert "summary:" not in output
    assert len(output.splitlines()) == len(expected) + 4


def test_default_query_expands_only_one_route(capsys) -> None:
    exit_code = docs_route.main(["--query", "unit economics report"])

    output = capsys.readouterr().out
    assert exit_code == 0
    assert output.count("scope:") == 1
    assert "matches:" not in output


def test_default_route_excludes_history() -> None:
    default_matches = find_routes(
        load_route_records(),
        query="Power BI WB model reference",
        include_supporting=True,
        limit=10,
    )
    history_matches = find_routes(
        load_route_records(),
        query="Power BI WB model reference",
        include_supporting=True,
        include_history=True,
        limit=10,
    )

    assert all(record.status != "superseded" for _score, record in default_matches)
    assert any(record.status == "superseded" for _score, record in history_matches)


def test_compact_route_does_not_embed_document_body() -> None:
    score, record = find_routes(
        load_route_records(),
        scope="excel-methodology",
        limit=1,
    )[0]

    rendered = render_route(score, record)

    assert len(rendered.splitlines()) < 30
    assert "# Calculation" not in rendered
    assert "related_code:" in rendered


def test_generated_jsonl_has_one_safe_record_per_manifest_entry() -> None:
    records = load_route_records()
    lines = render_generated_jsonl(records).splitlines()

    assert len(lines) == len(records)
    payload = [json.loads(line) for line in lines]
    assert all("path" in item and "summary" in item for item in payload)
    assert all("body" not in item for item in payload)
    logistics = next(
        item for item in payload if item["truthScope"] == "logistics-cost-analysis"
    )
    assert logistics["operationalDocs"] == [
        {
            "path": "docs/runbooks/wb-logistics-v4-continuation.md",
            "summary": (
                "Последнее записанное состояние WB-логистики по средам, evidence "
                "и безопасный путь к test-rollout v5."
            ),
        }
    ]


def test_generated_artifacts_are_current() -> None:
    assert docs_route.check_generated(load_route_records()) == []


def test_routing_metadata_is_required_only_for_canonical_leader() -> None:
    records = [
        {
            "path": "supporting.md",
            "source_of_truth": True,
            "truth_scope": "source-refresh",
            "truth_priority": 80,
        },
        {
            "path": "canonical.md",
            "source_of_truth": True,
            "truth_scope": "source-refresh",
            "truth_priority": 100,
            "read_when": "When source refresh changes.",
            "search_terms": ["source refresh", "provider registry"],
        },
    ]

    assert validate_routing_metadata(records) == []
    del records[1]["read_when"]
    assert validate_routing_metadata(records) == [
        "canonical.md: canonical route needs non-empty read_when"
    ]


def test_ai_sections_validator_rejects_missing_heading() -> None:
    failures = validate_ai_sections(
        Path("docs/specs/example.md"),
        {"ai_sections": {"missing": "Not Present"}},
        "# Existing\n",
    )

    assert failures == [
        "docs/specs/example.md: ai_sections['missing'] heading does not exist: "
        "'Not Present'"
    ]


def test_anchor_validator_rejects_unregistered_path_and_missing_symbol(
    tmp_path: Path,
    monkeypatch,
) -> None:
    target = tmp_path / "module.py"
    target.write_text("def present():\n    return True\n", encoding="utf-8")
    monkeypatch.setattr("validate_specs.ROOT", tmp_path)
    metadata = {
        "related_code": [],
        "code_anchors": [
            {"path": "module.py", "symbols": ["def absent"]},
        ],
    }

    failures = validate_anchors(
        Path("docs/specs/example.md"),
        metadata,
        "code_anchors",
        "related_code",
    )

    assert failures == [
        "docs/specs/example.md: code_anchors[0].path must also be listed in "
        "related_code: module.py",
        "docs/specs/example.md: code_anchors[0] symbol does not exist: "
        "'def absent'",
    ]
