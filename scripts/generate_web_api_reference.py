#!/usr/bin/env python3
"""Generate or verify the route inventory from the FastAPI OpenAPI schema."""

# ruff: noqa: E402, I001

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

# Importing the web module builds its module-level app. Keep documentation
# generation isolated from the live database and external integrations.
os.environ["SHUMEYKO_DATABASE_URL"] = "sqlite:///:memory:"
os.environ["SHUMEYKO_SESSION_SECRET"] = "docs-generation-only"
os.environ["SHUMEYKO_SOURCE_REFRESH_ENABLED"] = "false"
os.environ["SHUMEYKO_AUTO_REFRESH_ENABLED"] = "false"
os.environ["SHUMEYKO_LIVE_CHECKS_ENABLED"] = "false"
os.environ["SHUMEYKO_OPENAI_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""

from wb_unit_economics.web.app import app  # noqa: E402

from scripts.docs_metadata import date_text, load_frontmatter  # noqa: E402

DEFAULT_OUTPUT = ROOT / "docs" / "generated" / "web-api.md"
SOURCE_SPEC = ROOT / "docs" / "specs" / (
    "wb-unit-economics-ai-web-cabinet-implementation.md"
)
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head"}


def render_inventory(schema: dict[str, Any] | None = None) -> str:
    schema = schema or app.openapi()
    source_metadata, _ = load_frontmatter(SOURCE_SPEC)
    updated_at = date_text(source_metadata.get("updated_at"))
    if updated_at is None:
        raise ValueError(f"Invalid updated_at in {SOURCE_SPEC}")

    rows: list[tuple[str, str, str, str]] = []
    for route, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.casefold() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            rows.append(
                (
                    route,
                    method.upper(),
                    str(operation.get("operationId", "")),
                    str(operation.get("summary", "")),
                )
            )
    rows.sort(key=lambda item: (item[0], item[1]))

    lines = [
        "---",
        'title: "FastAPI route inventory"',
        "doc_type: generated_reference",
        "status: active",
        'audience: ["engineering", "operations"]',
        "source_of_truth: false",
        "source_spec: "
        '"docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md"',
        "last_reconciled_with: "
        '"docs/specs/wb-unit-economics-ai-web-cabinet-implementation.md @ '
        f'{updated_at}"',
        f'updated_at: "{updated_at}"',
        "---",
        "",
        "# FastAPI route inventory",
        "",
        "> Этот файл сгенерирован из текущего OpenAPI приложения. Не редактируйте",
        "> список маршрутов вручную; используйте",
        "> `python scripts/generate_web_api_reference.py`.",
        "",
        "Бизнес-права, роли и ограничения описаны в accepted web-spec. Этот файл",
        "фиксирует только фактически объявленные HTTP-маршруты.",
        "",
        "| Метод | Маршрут | Operation ID | OpenAPI summary |",
        "|---|---|---|---|",
    ]
    for route, method, operation_id, summary in rows:
        safe_summary = summary.replace("|", "\\|")
        lines.append(
            f"| `{method}` | `{route}` | `{operation_id}` | {safe_summary} |"
        )
    lines.extend(["", f"Всего маршрутов: **{len(rows)}**.", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    expected = render_inventory()
    if args.check:
        if not args.output.exists():
            print(f"OpenAPI inventory is missing: {args.output}", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != expected:
            print("OpenAPI inventory is stale", file=sys.stderr)
            return 1
        print("OpenAPI inventory matches the current FastAPI schema.")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8")
    print(f"OpenAPI inventory updated: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
