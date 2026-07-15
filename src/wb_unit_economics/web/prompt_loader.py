from __future__ import annotations

import re
from functools import lru_cache
from importlib.resources import files

PROMPT_PACKAGE = "wb_unit_economics.web.prompts"
PROMPT_FILES = {
    "ai_analyst": "ai_analyst.md",
    "client_draft": "client_draft.md",
}
PLACEHOLDER_PATTERN = re.compile(r"\{\{[A-Z][A-Z0-9_]*\}\}")


@lru_cache(maxsize=len(PROMPT_FILES))
def load_prompt(name: str) -> str:
    filename = PROMPT_FILES.get(name)
    if not filename:
        raise ValueError(f"Unknown prompt: {name}")
    prompt = (
        files(PROMPT_PACKAGE)
        .joinpath(filename)
        .read_text(encoding="utf-8")
        .strip()
    )
    if not prompt:
        raise RuntimeError(f"Prompt is empty: {filename}")
    return prompt


def render_prompt(name: str, **values: str) -> str:
    prompt = load_prompt(name)
    for key, value in values.items():
        prompt = prompt.replace(f"{{{{{key}}}}}", value)
    unresolved = PLACEHOLDER_PATTERN.findall(prompt)
    if unresolved:
        raise RuntimeError(
            f"Unresolved placeholders in {PROMPT_FILES[name]}: "
            + ", ".join(sorted(set(unresolved)))
        )
    return prompt
