from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.docs_metadata import has_superseded_banner, load_frontmatter, string_list
from scripts.validate_documentation_contracts import validate_excel_sheet_contract

ROOT = Path(__file__).resolve().parents[1]


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


def test_manifest_metadata_parity_validator() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/validate_docs_manifest.py"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
