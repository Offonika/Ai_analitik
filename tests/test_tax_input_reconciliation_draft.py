from __future__ import annotations

from scripts.build_tax_input_reconciliation_draft import (
    build_tax_input_summary,
    render_tax_input_markdown,
)


def test_tax_input_reconciliation_draft_summary_aggregates_without_raw_rows() -> None:
    summary = build_tax_input_summary(
        {
            "meta": {
                "client": "Тестовый клиент",
                "period": "01.03.2026 - 31.03.2026",
                "methodologyVersion": "test",
            },
            "unitRows": [{"product": "Товар"}],
            "taxInputReconciliation": [
                {
                    "week": "2026-03-02",
                    "cabinet": "Кабинет",
                    "organization": "Организация",
                    "vatInputFromWb": 0,
                    "vatInputFrom1c": 100.125,
                    "vatInputDifference": 100.125,
                    "vatInputCompleteness": "partial",
                },
                {
                    "week": "2026-03-09",
                    "vatInputFromWb": 0,
                    "vatInputFrom1c": 50,
                    "vatInputDifference": 50,
                    "vatInputCompleteness": "partial",
                },
            ],
        },
        wb_rows=10,
    )

    assert summary["wbRows"] == 10
    assert summary["unitRows"] == 1
    assert summary["taxReconciliationRows"] == 2
    assert summary["statusCounts"] == {"partial": 2}
    assert summary["totals"]["vatInputFromWb"] == "0.00"
    assert summary["totals"]["vatInputFrom1c"] == "150.12"
    assert "raw" not in summary

    markdown = render_tax_input_markdown(summary)

    assert "# Draft-сверка входящего НДС" in markdown
    assert "Raw WB/1C строки" in markdown
    assert "22/122" in markdown
    assert "## Причины расхождений" in markdown
    assert "## Крупные хвосты по неделям" in markdown
    assert "| partial | 2 |" in markdown
    assert "| НДС входящий 1С | 150.12 |" in markdown
