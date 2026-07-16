from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn

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

    table = Document(output).tables[0]
    assert table.rows[0]._tr.trPr.find(qn("w:tblHeader")) is not None
    assert all(
        row._tr.trPr.find(qn("w:cantSplit")) is not None for row in table.rows
    )

    branded_output = tmp_path / "branded.docx"
    render_markdown_docx(
        markdown,
        branded_output,
        branded=True,
        landscape=False,
        cover_title="Заголовок",
        cover_subtitle="2026-07",
        source_sha256=source_hash,
    )
    assert normalized_docx_tokens(branded_output) == normalized_markdown_tokens(
        markdown
    )
