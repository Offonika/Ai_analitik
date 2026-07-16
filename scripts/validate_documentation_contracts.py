#!/usr/bin/env python3
"""Validate code-backed Excel, DOCX, and OpenAPI documentation contracts."""

# ruff: noqa: E402, I001

from __future__ import annotations

import re
import sys
from html.parser import HTMLParser
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

EXCEL_SPEC = ROOT / "docs" / "specs" / ("wb-unit-economics-excel-mvp-implementation.md")
WEB_INDEX = ROOT / "src" / "wb_unit_economics" / "web" / "static" / "index.html"
WEB_APP_JS = ROOT / "src" / "wb_unit_economics" / "web" / "static" / "app.js"
CURRENT_CLIENT_SEMANTICS_DOCS = (
    ROOT / "docs" / "specs" / "wb-unit-economics-excel-mvp-implementation.md",
    ROOT / "docs" / "specs" / "wb-unit-economics-ai-web-cabinet-implementation.md",
    ROOT / "docs" / "specs" / "marketplace-unit-economics-ozon-integration.md",
    ROOT / "docs" / "runbooks" / "report-generation.md",
    ROOT / "docs" / "runbooks" / "power-bi-power-query.md",
    ROOT / "docs" / "client-scope.md",
    ROOT / "docs" / "client-methodology.md",
    ROOT / "docs" / "client-tz.md",
    ROOT / "docs" / "calculation-formulas.md",
)
FORBIDDEN_CLIENT_PROFIT_TERMS = (
    "маржинальный доход wb после налогов",
    "прибыль по юнит-экономике wb после налогов",
    "прибыль после налогов",
    "рентабельность после налогов",
)


class UserGuideContractParser(HTMLParser):
    """Check that primary UI controls can populate the generated user guide."""

    VOID_TAGS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
    }
    TOPBAR_FILTER_CLASSES = {
        "client-switcher",
        "cabinet-switcher",
        "period-start-switcher",
        "period-end-switcher",
    }
    CHECKS_GUIDE_IDS = {
        "source-refresh-status",
        "source-refresh-steps",
        "source-refresh-collections",
        "source-refresh-mapping-form",
        "preflight-panel",
    }

    def __init__(self) -> None:
        super().__init__()
        self.stack: list[tuple[str, set[str]]] = []
        self.failures: list[str] = []
        self.workspaces: set[str] = set()
        self.checks_guide_ids: set[str] = set()
        self.guide_panel_found = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        self._inspect(tag, attributes, classes)
        if tag not in self.VOID_TAGS:
            self.stack.append((tag, classes))

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        self._inspect(tag, attributes, set(attributes.get("class", "").split()))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def _inside(self, class_name: str) -> bool:
        return any(class_name in classes for _tag, classes in self.stack)

    def _inspect(
        self,
        tag: str,
        attributes: dict[str, str],
        classes: set[str],
    ) -> None:
        identifier = attributes.get("id", tag)
        guide_entry = attributes.get("data-guide-entry", "")
        has_description = bool(
            attributes.get("data-guide-description") or attributes.get("data-tooltip")
        )
        ignored = attributes.get("data-guide-ignore") == "true"

        workspace = attributes.get("data-workspace-nav", "")
        if workspace:
            self.workspaces.add(workspace)
            if workspace != "guide":
                self._require_guide_entry(
                    identifier,
                    guide_entry,
                    "sections",
                    has_description,
                )
        if attributes.get("data-workspace-panel") == "guide":
            self.guide_panel_found = True

        if identifier in self.CHECKS_GUIDE_IDS:
            self.checks_guide_ids.add(identifier)
            self._require_guide_entry(
                identifier,
                guide_entry,
                "checks",
                has_description,
            )

        if tag == "label" and classes & self.TOPBAR_FILTER_CLASSES:
            self._require_guide_entry(
                identifier,
                guide_entry,
                "start",
                has_description,
            )

        is_primary_action = tag in {"button", "a"} and (
            self._inside("topbar-actions") or self._inside("workspace-header")
        )
        if is_primary_action and not ignored:
            self._require_guide_entry(
                identifier,
                guide_entry,
                "actions",
                has_description,
            )

        is_source_refresh_action = tag == "button" and self._inside(
            "source-refresh-actions"
        )
        if is_source_refresh_action:
            self._require_guide_entry(
                identifier,
                guide_entry,
                "checks",
                has_description,
            )

    def _require_guide_entry(
        self,
        identifier: str,
        actual_group: str,
        expected_group: str,
        has_description: bool,
    ) -> None:
        if actual_group != expected_group:
            self.failures.append(
                f"{identifier}: expected data-guide-entry={expected_group!r}"
            )
        if not has_description:
            self.failures.append(f"{identifier}: guide description is missing")


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


def validate_client_profit_terminology(
    paths: tuple[Path, ...] = CURRENT_CLIENT_SEMANTICS_DOCS,
) -> list[str]:
    """Reject superseded client-facing profit labels in current documentation."""
    failures: list[str] = []
    for path in paths:
        text = path.read_text(encoding="utf-8").casefold()
        try:
            label = str(path.relative_to(ROOT))
        except ValueError:
            label = path.name
        for term in FORBIDDEN_CLIENT_PROFIT_TERMS:
            if term in text:
                failures.append(
                    f"{label}: deprecated client profit term remains: {term!r}"
                )
    return failures


def validate_user_guide_contract() -> list[str]:
    parser = UserGuideContractParser()
    parser.feed(WEB_INDEX.read_text(encoding="utf-8"))
    failures = list(parser.failures)
    if "guide" not in parser.workspaces:
        failures.append("user guide workspace navigation is missing")
    if not parser.guide_panel_found:
        failures.append("user guide workspace panel is missing")
    missing_checks_ids = parser.CHECKS_GUIDE_IDS - parser.checks_guide_ids
    for identifier in sorted(missing_checks_ids):
        failures.append(f"checks guide source is missing: {identifier}")

    app_js = WEB_APP_JS.read_text(encoding="utf-8")
    required_js = [
        'if (value === "guide")',
        "function renderUserGuide()",
        'document.createElement("li")',
        "list.replaceChildren(...cards)",
    ]
    for token in required_js:
        if token not in app_js:
            failures.append(f"user guide renderer token is missing: {token}")
    return failures


def main() -> int:
    failures = validate_excel_sheet_contract()
    failures.extend(validate_user_guide_contract())
    failures.extend(validate_client_profit_terminology())
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
