from __future__ import annotations

from pathlib import Path

from wb_unit_economics.document_exports import (
    docx_source_sha256,
    markdown_sha256,
    normalized_docx_tokens,
    normalized_markdown_tokens,
    render_markdown_docx,
)


def test_markdown_docx_preserves_normalized_text_and_source_hash(
    tmp_path: Path,
) -> None:
    markdown = """---
title: Test
---

# Заголовок

- Первый пункт
- Второй пункт

| Поле | Значение |
| --- | --- |
| Период | 2026-07 |

```text
profit = revenue - cost
```
"""
    output = tmp_path / "test.docx"
    source_hash = markdown_sha256(markdown)

    render_markdown_docx(
        markdown,
        output,
        branded=False,
        landscape=False,
        source_sha256=source_hash,
    )

    assert docx_source_sha256(output) == source_hash
    assert normalized_docx_tokens(output) == normalized_markdown_tokens(markdown)
