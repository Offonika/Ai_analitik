from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml

TRUTH_SCOPES = {
    "configuration",
    "development-workflow",
    "excel-methodology",
    "mapping",
    "ozon",
    "product-scope",
    "project-governance",
    "project-overview",
    "report-publication",
    "source-refresh",
    "source-retention",
    "tax-methodology",
    "web-cabinet",
}
TRUTH_PRIORITY_MIN = 1
TRUTH_PRIORITY_MAX = 100


def load_yaml(path: Path) -> Any:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def load_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return {}, text
    marker = text.find("\n---\n", 4)
    if marker < 0:
        return {}, text
    parsed = yaml.safe_load(text[4:marker]) or {}
    if not isinstance(parsed, dict):
        return {}, text
    return parsed, text[marker + 5 :]


def date_text(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            return None
    return None


def string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list) and all(isinstance(item, str) for item in value):
        return value
    return []


def has_superseded_banner(body: str) -> bool:
    visible = "\n".join(body.splitlines()[:30]).casefold()
    markers = (
        "superseded",
        "заменен",
        "заменён",
        "устарел",
        "устаревш",
        "исторический документ",
    )
    return any(marker in visible for marker in markers)


def validate_truth_metadata(metadata: dict[str, Any], label: str) -> list[str]:
    """Validate scoped source-of-truth metadata for one document record."""
    failures: list[str] = []
    is_truth = metadata.get("source_of_truth") is True
    scope = metadata.get("truth_scope")
    priority = metadata.get("truth_priority")
    if is_truth:
        if scope not in TRUTH_SCOPES:
            failures.append(f"{label}: source_of_truth requires valid truth_scope")
        if (
            not isinstance(priority, int)
            or isinstance(priority, bool)
            or not TRUTH_PRIORITY_MIN <= priority <= TRUTH_PRIORITY_MAX
        ):
            failures.append(
                f"{label}: source_of_truth requires truth_priority "
                f"{TRUTH_PRIORITY_MIN}..{TRUTH_PRIORITY_MAX}"
            )
    elif scope is not None or priority is not None:
        failures.append(
            f"{label}: truth_scope/truth_priority require source_of_truth: true"
        )
    return failures
