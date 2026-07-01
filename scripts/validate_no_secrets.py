from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET_PATTERNS = [
    re.compile(r"WB_ACCOUNT_\d+_API_KEY[ \t]*=[ \t]*[^\s#]+"),
    re.compile(r"ONEC_ODATA_(?:PASSWORD|PASS)[ \t]*=[ \t]*[^\s#]+"),
    re.compile(
        r"Authorization[\"']?[ \t]*:[ \t]*[\"']?"
        r"(?:Bearer|eyJ|[A-Za-z0-9_-]{20,})"
    ),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY"),
]
SKIP_PARTS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    "data",
    "reports",
}
SKIP_NAMES = {".env"}


def should_skip(path: Path) -> bool:
    return path.name in SKIP_NAMES or any(part in SKIP_PARTS for part in path.parts)


def main() -> int:
    failures: list[str] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(content):
                failures.append(str(path.relative_to(ROOT)))
                break
    if failures:
        print("Potential secret markers found:")
        for item in failures:
            print(f"- {item}")
        return 1
    print("No obvious secret markers found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
