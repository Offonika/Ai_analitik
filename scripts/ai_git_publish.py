from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str], *, capture: bool = False) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=True,
        capture_output=capture,
        text=True,
    )
    return result.stdout.strip() if capture else ""


def git(args: list[str], *, capture: bool = False) -> str:
    return run(["git", *args], capture=capture)


def python_script(script: str, *args: str) -> None:
    python_bin = ROOT / ".venv" / "bin" / "python"
    executable = str(python_bin) if python_bin.exists() else sys.executable
    run([executable, str(ROOT / "scripts" / script), *args])


def changed_paths(*, staged: bool = False) -> list[str]:
    args = ["diff", "--name-only"]
    if staged:
        args.insert(1, "--cached")
    output = git(args, capture=True)
    return [line for line in output.splitlines() if line]


def has_staged_changes() -> bool:
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=ROOT,
        text=True,
    )
    return result.returncode == 1


def docs_changed(paths: list[str]) -> bool:
    doc_roots = ("docs/", "config/")
    doc_files = {"README.md", "AGENTS.md"}
    return any(path.startswith(doc_roots) or path in doc_files for path in paths)


def changed_specs(paths: list[str]) -> list[str]:
    return [
        path
        for path in paths
        if path.startswith("docs/specs/") and path.endswith(".md")
    ]


def default_message() -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"AI development snapshot {timestamp}"


def current_branch() -> str:
    branch = git(["branch", "--show-current"], capture=True)
    if not branch:
        raise RuntimeError("Cannot publish from detached HEAD.")
    return branch


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate, commit, and optionally push the current AI work."
    )
    parser.add_argument("-m", "--message", help="Commit message.")
    parser.add_argument(
        "--no-push",
        action="store_true",
        help="Create the commit locally but do not push it.",
    )
    parser.add_argument(
        "--skip-docs",
        action="store_true",
        help="Skip docs validators even when documentation changed.",
    )
    parser.add_argument(
        "--tests",
        action="store_true",
        help="Run the full test suite before committing.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show the current Git status without staging, committing, or pushing.",
    )
    args = parser.parse_args()

    if args.dry_run:
        print(git(["status", "--short", "--branch"], capture=True))
        print("Dry run only: no files were staged, committed, or pushed.")
        return 0

    branch = current_branch()
    python_script("validate_no_secrets.py")

    git(["add", "-A"])
    python_script("check_git_safety.py", "--staged", "--tracked")
    git(["diff", "--cached", "--check"])

    staged_paths = changed_paths(staged=True)
    if not has_staged_changes():
        print("No changes to commit.")
        if not args.no_push:
            git(["push", "-u", "origin", branch])
        return 0

    if docs_changed(staged_paths) and not args.skip_docs:
        python_script("validate_docs_manifest.py")
        python_script("validate_llm_docs.py")
        python_script("docs_route.py", "--check-generated")
        specs = changed_specs(staged_paths) or [
            "docs/specs/wb-unit-economics-mvp.md"
        ]
        python_script("validate_specs.py", *specs)

    if args.tests:
        run([str(ROOT / ".venv" / "bin" / "python"), "-m", "pytest"])

    message = args.message or default_message()
    git(["commit", "-m", message])
    if not args.no_push:
        git(["push", "-u", "origin", branch])
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"Command failed with exit code {exc.returncode}: {' '.join(exc.cmd)}")
        sys.exit(exc.returncode)
    except RuntimeError as exc:
        print(str(exc))
        sys.exit(1)
