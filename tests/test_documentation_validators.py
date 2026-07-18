from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_docs_manifest  # noqa: E402
from validate_docs_manifest import (  # noqa: E402
    validate_changelog_registration,
    validate_index_consistency,
    validate_operational_docs,
    validate_truth_precedence,
)
from validate_specs import validate_dependency_graph  # noqa: E402

from scripts.build_client_tz_docx import check_docx, render_client_tz  # noqa: E402
from scripts.docs_metadata import (  # noqa: E402
    has_superseded_banner,
    load_frontmatter,
    string_list,
)
from scripts.validate_documentation_contracts import (  # noqa: E402
    UserGuideContractParser,
    validate_client_profit_terminology,
    validate_excel_sheet_contract,
    validate_user_guide_contract,
)
from wb_unit_economics.document_exports import markdown_sha256  # noqa: E402


def test_block_yaml_lists_are_loaded_and_code_paths_exist() -> None:
    path = ROOT / "docs/specs/wb-unit-economics-excel-mvp-implementation.md"
    metadata, _body = load_frontmatter(path)

    assert isinstance(metadata["related_code"], list)
    assert len(metadata["related_code"]) > 5
    assert all((ROOT / item).exists() for item in metadata["related_code"])


def test_superseded_documents_have_replacement_and_banner() -> None:
    for path in sorted((ROOT / "docs").rglob("*.md")):
        metadata, body = load_frontmatter(path)
        if metadata.get("status") != "superseded":
            continue
        replacements = string_list(metadata.get("superseded_by"))
        assert replacements, path
        assert all((ROOT / replacement).exists() for replacement in replacements)
        assert has_superseded_banner(body), path


def test_excel_sheet_contract_matches_code() -> None:
    assert validate_excel_sheet_contract() == []


def test_user_guide_contract_matches_primary_interface() -> None:
    assert validate_user_guide_contract() == []


def test_user_guide_contract_rejects_undocumented_workspace() -> None:
    parser = UserGuideContractParser()
    parser.feed('<button data-workspace-nav="new-section">Новый раздел</button>')

    assert "button: expected data-guide-entry='sections'" in parser.failures
    assert "button: guide description is missing" in parser.failures


def test_user_guide_contract_rejects_undocumented_source_refresh_action() -> None:
    parser = UserGuideContractParser()
    parser.feed(
        '<div class="source-refresh-actions">'
        '<button id="new-refresh-action">Новая загрузка</button>'
        "</div>"
    )

    assert "new-refresh-action: expected data-guide-entry='checks'" in parser.failures
    assert "new-refresh-action: guide description is missing" in parser.failures


def test_manifest_metadata_parity_validator() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_docs_manifest.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_truth_metadata_requires_scope_and_priority() -> None:
    from scripts.docs_metadata import validate_truth_metadata

    failures = validate_truth_metadata({"source_of_truth": True}, "example.md")

    assert "example.md: source_of_truth requires valid truth_scope" in failures
    assert any("truth_priority" in failure for failure in failures)


def test_truth_precedence_rejects_equal_leaders() -> None:
    records = [
        {
            "path": "a.md",
            "source_of_truth": True,
            "truth_scope": "source-refresh",
            "truth_priority": 100,
        },
        {
            "path": "b.md",
            "source_of_truth": True,
            "truth_scope": "source-refresh",
            "truth_priority": 100,
        },
    ]

    assert validate_truth_precedence(records) == [
        "truth_scope 'source-refresh' must have one highest-priority document; "
        "found a.md, b.md"
    ]


def test_operational_docs_require_active_supporting_runbook() -> None:
    canonical = {
        "path": "spec.md",
        "source_of_truth": True,
        "truth_scope": "scope",
        "truth_priority": 100,
        "operational_docs": ["runbook.md"],
    }
    runbook = {
        "path": "runbook.md",
        "source_of_truth": False,
        "status": "active",
        "doc_type": "runbook",
    }

    assert validate_operational_docs([canonical, runbook]) == []

    runbook["status"] = "draft"
    runbook["source_of_truth"] = True
    runbook["doc_type"] = "reference"
    assert validate_operational_docs([canonical, runbook]) == [
        "runbook.md: operational doc must have status active",
        "runbook.md: operational doc must not be source_of_truth",
        "runbook.md: operational doc must have doc_type runbook",
    ]


def test_changelog_registration_requires_registered_back_reference(
    tmp_path: Path, monkeypatch
) -> None:
    spec = tmp_path / "current.md"
    spec.write_text(
        "---\nchangelog_path: history.md\n---\nCurrent requirements\n\n"
        "# Changelog\n\nFull history: `history.md`.\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.md"
    history.write_text(
        "---\nsource_spec: wrong.md\n---\nHistory\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_docs_manifest, "ROOT", tmp_path)
    records = [
        {"path": "current.md", "doc_type": "spec"},
        {"path": "history.md", "doc_type": "reference"},
    ]

    failures = validate_changelog_registration(records, {"current.md"})

    assert failures == [
        "current.md: changelog_path must reference doc_type changelog: history.md",
        "history.md: source_spec must point back to current.md",
    ]


def test_changelog_registration_rejects_inline_history(
    tmp_path: Path, monkeypatch
) -> None:
    spec = tmp_path / "current.md"
    spec.write_text(
        "---\nchangelog_path: history.md\n---\nCurrent requirements\n\n"
        "# Changelog\n\nFull history: `history.md`.\n"
        "- 2026-07-15: duplicated inline change.\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.md"
    history.write_text(
        "---\nsource_spec: current.md\n---\nHistory\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_docs_manifest, "ROOT", tmp_path)
    records = [
        {"path": "current.md", "doc_type": "spec"},
        {"path": "history.md", "doc_type": "changelog"},
    ]

    failures = validate_changelog_registration(records, {"current.md"})

    assert failures == [
        "current.md: inline changelog must contain only the external history pointer"
    ]


def test_changelog_registration_rejects_stale_history(
    tmp_path: Path, monkeypatch
) -> None:
    spec = tmp_path / "current.md"
    spec.write_text(
        "---\nchangelog_path: history.md\nupdated_at: '2026-07-15'\n---\n"
        "Current requirements\n\n# Changelog\n\nFull history: `history.md`.\n",
        encoding="utf-8",
    )
    history = tmp_path / "history.md"
    history.write_text(
        "---\nsource_spec: current.md\nupdated_at: '2026-07-14'\n---\nHistory\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_docs_manifest, "ROOT", tmp_path)
    records = [
        {"path": "current.md", "doc_type": "spec"},
        {"path": "history.md", "doc_type": "changelog"},
    ]

    failures = validate_changelog_registration(records, {"current.md"})

    assert failures == [
        "history.md: updated_at 2026-07-14 is older than source spec 2026-07-15"
    ]


def test_index_consistency_rejects_missing_scope_and_stale_status() -> None:
    records = [
        {
            "path": "docs/specs/current.md",
            "status": "accepted",
            "source_of_truth": True,
            "truth_scope": "source-refresh",
            "truth_priority": 100,
        },
        {
            "path": "docs/specs/old.md",
            "status": "superseded",
            "source_of_truth": False,
        },
    ]
    index_text = (
        "| Scope | Canonical | Priority |\n"
        "| --- | --- | ---: |\n"
        "| `old` | `docs/specs/old.md` | 100 | draft | Description |\n"
    )

    failures = validate_index_consistency(records, index_text)

    assert "docs/index.md: missing truth_scope row 'source-refresh'" in failures
    assert any("docs/specs/old.md" in failure for failure in failures)


def test_client_profit_terminology_rejects_deprecated_label(tmp_path: Path) -> None:
    document = tmp_path / "current.md"
    document.write_text("Прибыль после налогов", encoding="utf-8")

    failures = validate_client_profit_terminology((document,))

    assert failures == [
        "current.md: deprecated client profit term remains: 'прибыль после налогов'"
    ]


def test_dependency_graph_rejects_cycle_but_ignores_related_specs() -> None:
    a = ROOT / "docs/specs/a.md"
    b = ROOT / "docs/specs/b.md"
    metadata = {
        a: {"depends_on": ["b"], "related_specs": ["docs/specs/b.md"]},
        b: {"depends_on": ["a"]},
    }

    failures = validate_dependency_graph(metadata, {"a": a, "b": b})

    assert len(failures) == 1
    assert "docs/specs/a.md -> docs/specs/b.md -> docs/specs/a.md" in failures[0]

    metadata[a]["depends_on"] = []
    assert validate_dependency_graph(metadata, {"a": a, "b": b}) == []


def test_reconciled_document_cannot_have_older_updated_at(
    tmp_path: Path, monkeypatch
) -> None:
    source = tmp_path / "source.md"
    source.write_text(
        "---\ntitle: Source\ndoc_type: reference\nstatus: accepted\n"
        "audience: [engineering]\nsource_of_truth: false\n"
        "updated_at: '2026-07-13'\n---\nSource\n",
        encoding="utf-8",
    )
    target = tmp_path / "target.md"
    target.write_text(
        "---\ntitle: Target\ndoc_type: reference\nstatus: draft\n"
        "audience: [engineering]\nsource_of_truth: false\n"
        "last_reconciled_with: 'source.md @ 2026-07-13'\n"
        "updated_at: '2026-07-12'\n---\nTarget\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(validate_docs_manifest, "ROOT", tmp_path)
    failures: list[str] = []

    validate_docs_manifest.validate_markdown_metadata(
        "target.md",
        {
            "title": "Target",
            "doc_type": "reference",
            "status": "draft",
            "audience": ["engineering"],
            "source_of_truth": False,
        },
        failures,
    )

    assert any("updated_at 2026-07-12 is older" in failure for failure in failures)


def test_client_docx_check_rejects_stale_source(tmp_path: Path) -> None:
    output = tmp_path / "client-tz.docx"
    old_markdown = "# Старое ТЗ\n"
    render_client_tz(
        old_markdown,
        source_hash=markdown_sha256(old_markdown),
        output=output,
    )
    new_markdown = "# Новое ТЗ\n"

    assert (
        check_docx(
            new_markdown,
            source_hash=markdown_sha256(new_markdown),
            output=output,
        )
        == 1
    )
