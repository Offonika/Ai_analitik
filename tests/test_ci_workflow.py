from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def load_workflow() -> dict:
    return yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)


def commands(job: dict) -> str:
    return "\n".join(
        str(step.get("run", "")) for step in job.get("steps", [])
    )


def test_ci_workflow_has_read_only_pr_and_main_checks() -> None:
    workflow = load_workflow()

    assert set(workflow["on"]) == {"pull_request", "push", "workflow_dispatch"}
    assert workflow["on"]["pull_request"]["branches"] == ["main"]
    assert workflow["on"]["push"]["branches"] == ["main"]
    assert workflow["permissions"] == {"contents": "read"}
    assert workflow["concurrency"]["cancel-in-progress"] == "true"
    assert set(workflow["jobs"]) == {"quality", "tests"}


def test_ci_workflow_uses_pinned_runtimes_without_persisted_credentials() -> None:
    workflow = load_workflow()

    for job in workflow["jobs"].values():
        checkout = next(
            step for step in job["steps"] if step.get("uses") == "actions/checkout@v7"
        )
        setup_python = next(
            step
            for step in job["steps"]
            if step.get("uses") == "actions/setup-python@v6"
        )
        assert checkout["with"]["persist-credentials"] == "false"
        assert setup_python["with"]["python-version"] == "3.12"

    setup_node = next(
        step
        for step in workflow["jobs"]["quality"]["steps"]
        if step.get("uses") == "actions/setup-node@v6"
    )
    assert setup_node["with"]["node-version"] == "20"
    assert setup_node["with"]["package-manager-cache"] == "false"


def test_ci_workflow_runs_all_blocking_project_checks() -> None:
    workflow = load_workflow()
    quality_commands = commands(workflow["jobs"]["quality"])
    tests_commands = commands(workflow["jobs"]["tests"])

    required_commands = {
        "python -m ruff check scripts src tests",
        "node --check src/wb_unit_economics/web/static/app.js",
        "python scripts/validate_specs.py",
        "python scripts/validate_docs_manifest.py",
        "python scripts/validate_llm_docs.py",
        "python scripts/docs_route.py --check-generated",
        "python scripts/validate_documentation_contracts.py",
        "python scripts/build_client_tz_docx.py --check",
        "python scripts/generate_web_api_reference.py --check",
        "python scripts/validate_no_secrets.py",
        "python scripts/check_git_safety.py --tracked",
    }
    for command in required_commands:
        assert command in quality_commands
    assert "python -m pytest -q" in tests_commands
    assert workflow["jobs"]["tests"]["timeout-minutes"] == "45"

    external_links = next(
        step
        for step in workflow["jobs"]["quality"]["steps"]
        if step.get("name") == "Check external documentation links"
    )
    assert external_links["continue-on-error"] == "true"


def test_ci_workflow_does_not_reference_repository_secrets() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "${{ secrets." not in text
    assert "contents: write" not in text
    assert ".env" not in text
