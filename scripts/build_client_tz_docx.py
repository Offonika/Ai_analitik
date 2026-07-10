#!/usr/bin/env python3
"""Build or verify the tracked client TZ DOCX from its Markdown source."""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wb_unit_economics.document_exports import (  # noqa: E402
    docx_source_sha256,
    markdown_sha256,
    normalized_docx_tokens,
    normalized_markdown_tokens,
    render_markdown_docx,
)

DEFAULT_SOURCE = ROOT / "docs" / "client-tz.md"
DEFAULT_OUTPUT = ROOT / "docs" / "shumeyko-partners-wb-unit-economics-client-tz.docx"


def main() -> int:
    args = parse_args()
    markdown = args.source.read_text(encoding="utf-8")
    source_hash = markdown_sha256(markdown)
    if args.check:
        return check_docx(markdown, source_hash=source_hash, output=args.output)
    render_client_tz(markdown, source_hash=source_hash, output=args.output)
    print(f"DOCX updated: {args.output}")
    return 0


def render_client_tz(markdown: str, *, source_hash: str, output: Path) -> Path:
    return render_markdown_docx(
        markdown,
        output,
        branded=False,
        landscape=False,
        footer_text="Шумейко и Партнеры · Техническое задание",
        source_sha256=source_hash,
    )


def check_docx(markdown: str, *, source_hash: str, output: Path) -> int:
    if not output.exists():
        print(f"DOCX is missing: {output}", file=sys.stderr)
        return 1
    if docx_source_sha256(output) != source_hash:
        print("DOCX source hash differs from docs/client-tz.md", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory() as tmp_dir:
        expected = Path(tmp_dir) / "client-tz.docx"
        render_client_tz(markdown, source_hash=source_hash, output=expected)
        if normalized_docx_tokens(output) != normalized_docx_tokens(expected):
            print("DOCX text differs from generated client TZ", file=sys.stderr)
            return 1
    if normalized_docx_tokens(output) != normalized_markdown_tokens(markdown):
        print("DOCX text differs from Markdown source", file=sys.stderr)
        return 1
    print("Client TZ DOCX is synchronized with Markdown.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())
