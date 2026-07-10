#!/usr/bin/env python3
"""Validate code-backed Excel, DOCX, and OpenAPI documentation contracts."""

# ruff: noqa: E402, I001

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from wb_unit_economics.excel import (  # noqa: E402
    CLIENT_VISIBLE_SHEETS,
    REQUIRED_SHEETS,
)
from wb_unit_economics.document_exports import markdown_sha256  # noqa: E402

from scripts.build_client_tz_docx import (  # noqa: E402
    DEFAULT_OUTPUT as CLIENT_TZ_DOCX,
)
from scripts.build_client_tz_docx import (  # noqa: E402
    DEFAULT_SOURCE as CLIENT_TZ_MARKDOWN,
)
from scripts.build_client_tz_docx import check_docx  # noqa: E402
from scripts.generate_web_api_reference import (  # noqa: E402
    DEFAULT_OUTPUT as OPENAPI_INVENTORY,
)
from scripts.generate_web_api_reference import render_inventory  # noqa: E402

EXCEL_SPEC = ROOT / "docs" / "specs" / (
    "wb-unit-economics-excel-mvp-implementation.md"
)


def markdown_list_between(text: str, start: str, end: str) -> list[str]:
    try:
        fragment = text.split(start, 1)[1].split(end, 1)[0]
    except IndexError:
        return []
    return re.findall(r"^- `([^`]+)`[.;]?$", fragment, flags=re.MULTILINE)


def validate_excel_sheet_contract() -> list[str]:
    text = EXCEL_SPEC.read_text(encoding="utf-8")
    documented_required = markdown_list_between(
        text, "Обязательные листы:", "Опциональный лист:"
    )
    documented_visible = markdown_list_between(
        text,
        "По умолчанию пользователь видит только клиентские вкладки:",
        "Остальные листы остаются",
    )
    failures: list[str] = []
    if documented_required != REQUIRED_SHEETS:
        failures.append(
            "Excel required sheets differ: "
            f"docs={documented_required!r}, code={REQUIRED_SHEETS!r}"
        )
    if set(documented_visible) != CLIENT_VISIBLE_SHEETS:
        failures.append(
            "Excel client-visible sheets differ: "
            f"docs={sorted(documented_visible)!r}, "
            f"code={sorted(CLIENT_VISIBLE_SHEETS)!r}"
        )
    return failures


def validate_openapi_inventory() -> list[str]:
    if not OPENAPI_INVENTORY.exists():
        return [f"OpenAPI inventory is missing: {OPENAPI_INVENTORY}"]
    if OPENAPI_INVENTORY.read_text(encoding="utf-8") != render_inventory():
        return ["OpenAPI inventory differs from the current FastAPI OpenAPI"]
    return []


def main() -> int:
    failures = validate_excel_sheet_contract()
    markdown = CLIENT_TZ_MARKDOWN.read_text(encoding="utf-8")
    if check_docx(
        markdown,
        source_hash=markdown_sha256(markdown),
        output=CLIENT_TZ_DOCX,
    ):
        failures.append("Tracked client TZ DOCX differs from its Markdown source")
    failures.extend(validate_openapi_inventory())

    if failures:
        print("Documentation contract validation failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print("Documentation contracts are synchronized with code and OpenAPI.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
