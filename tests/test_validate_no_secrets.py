from __future__ import annotations

from pathlib import Path

from scripts.validate_no_secrets import iter_candidate_files


def test_candidate_files_prune_local_artifact_trees(tmp_path: Path) -> None:
    included = tmp_path / "src/app.py"
    ignored_data = tmp_path / "data/raw.json"
    ignored_reports = tmp_path / "reports/report.xlsx"
    ignored_env = tmp_path / ".env"
    for path in (included, ignored_data, ignored_reports, ignored_env):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("placeholder", encoding="utf-8")

    candidates = set(iter_candidate_files(tmp_path))

    assert candidates == {included}
