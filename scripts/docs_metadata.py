from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import yaml


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
