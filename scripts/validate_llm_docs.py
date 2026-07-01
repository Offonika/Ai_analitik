from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DOC_ROOTS = [ROOT / "README.md", ROOT / "AGENTS.md", ROOT / "config", ROOT / "docs"]
LINK_RE = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
CODE_PATH_RE = re.compile(
    r"`((?:AGENTS\.md|README\.md|pyproject\.toml|config/|docs/|scripts/|src/|"
    r"tests/|sql/)[^`\\s]*)`"
)
SKIP_MARKERS = {"<", ">", "*", "..."}


def iter_markdown_files() -> list[Path]:
    files: list[Path] = []
    for root in DOC_ROOTS:
        if root.is_file():
            files.append(root)
        elif root.exists():
            files.extend(sorted(root.rglob("*.md")))
    return sorted(set(files))


def is_external(target: str) -> bool:
    parsed = urlparse(target)
    return bool(parsed.scheme) or target.startswith(("#", "mailto:"))


def normalize_target(raw_target: str) -> str:
    target = raw_target.split("#", 1)[0].strip()
    target = target.strip("<>")
    return target


def should_skip_path(target: str) -> bool:
    if not target:
        return True
    if any(marker in target for marker in SKIP_MARKERS):
        return True
    return target.startswith((".env", "data/", "reports/"))


def resolve(base_file: Path, target: str) -> Path:
    path = Path(target)
    if path.is_absolute():
        return path
    return (base_file.parent / path).resolve()


def check_markdown_links(path: Path, text: str) -> list[str]:
    failures: list[str] = []
    for match in LINK_RE.finditer(text):
        raw_target = match.group(1)
        if is_external(raw_target):
            continue
        target = normalize_target(raw_target)
        if should_skip_path(target):
            continue
        resolved = resolve(path, target)
        if not resolved.exists():
            rel = path.relative_to(ROOT)
            failures.append(f"{rel}: broken markdown link {raw_target}")
    return failures


def check_inline_paths(path: Path, text: str) -> list[str]:
    failures: list[str] = []
    for match in CODE_PATH_RE.finditer(text):
        target = normalize_target(match.group(1))
        if should_skip_path(target):
            continue
        resolved = ROOT / target
        if not resolved.exists():
            rel = path.relative_to(ROOT)
            failures.append(f"{rel}: broken inline path `{target}`")
    return failures


def main() -> int:
    failures: list[str] = []
    for path in iter_markdown_files():
        text = path.read_text(encoding="utf-8")
        failures.extend(check_markdown_links(path, text))
        failures.extend(check_inline_paths(path, text))

    if failures:
        print("LLM docs validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("LLM docs links are valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
