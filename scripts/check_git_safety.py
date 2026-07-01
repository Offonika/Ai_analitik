from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_PREFIXES = (
    "data/",
    "reports/",
    ".venv/",
    "venv/",
    ".pytest_cache/",
    ".ruff_cache/",
)
FORBIDDEN_PARTS = {"__pycache__"}
FORBIDDEN_SUFFIXES = (
    ".7z",
    ".csv",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".xls",
    ".xlsx",
    ".zip",
)
ALLOWED_EXACT = {".env.example"}


def run_git(args: list[str]) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def normalize(path: str) -> str:
    return path.replace("\\", "/").lstrip("./")


def is_forbidden(path: str) -> bool:
    normalized = normalize(path)
    if normalized in ALLOWED_EXACT:
        return False
    if normalized == ".env" or normalized.startswith(".env."):
        return True
    if normalized.startswith(FORBIDDEN_PREFIXES):
        return True
    if any(part in FORBIDDEN_PARTS for part in normalized.split("/")):
        return True
    return normalized.lower().endswith(FORBIDDEN_SUFFIXES)


def collect_paths(*, staged: bool, tracked: bool) -> dict[str, list[str]]:
    paths: dict[str, list[str]] = {}
    if staged:
        paths["staged"] = run_git(["diff", "--cached", "--name-only"])
    if tracked:
        paths["tracked"] = run_git(["ls-files"])
    return paths


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Block Git publication of local secrets and generated artifacts."
    )
    parser.add_argument(
        "--staged",
        action="store_true",
        help="Check paths staged for the next commit.",
    )
    parser.add_argument(
        "--tracked",
        action="store_true",
        help="Check all paths already tracked by Git.",
    )
    args = parser.parse_args()

    staged = args.staged or not args.tracked
    tracked = args.tracked
    failures: list[str] = []
    for group, paths in collect_paths(staged=staged, tracked=tracked).items():
        for path in paths:
            if is_forbidden(path):
                failures.append(f"{group}: {path}")

    if failures:
        print("Git safety check blocked forbidden paths:")
        for failure in failures:
            print(f"- {failure}")
        print("Move these files outside Git or update .gitignore before committing.")
        return 1

    print("Git safety check passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
