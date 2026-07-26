from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from scripts.build_client_analytical_report import _report_summary
from wb_unit_economics.client_report import (
    CLIENT_REPORT_CONTRACT_VERSION,
    build_client_analytical_markdown,
    build_client_analytical_report,
    render_client_report_html,
)
from wb_unit_economics.document_exports import (
    docx_source_sha256,
    normalized_docx_tokens,
    normalized_markdown_tokens,
)


def report_payload(*, tax_calculated: bool = True) -> dict:
    return {
        "meta": {
            "reportId": "report-july-2026",
            "title": "Кабинет юнит-экономики WB",
            "client": "Тестовый клиент",
            "period": "01.07.2026 - 12.07.2026",
            "reportPeriod": "01.07.2026 - 12.07.2026",
            "periodStatus": "предварительный: июль неполный",
            "sourceCoverage": "01.07.2026 - 12.07.2026",
            "generatedAt": "16.07.2026 12:00",
            "methodologyVersion": "test-v1",
            "returnReasonLimitation": (
                "Причина возврата не передаётся текущими источниками"
            ),
        },
        "readiness": {
            "status": "ready",
            "label": "Готов к передаче клиенту",
            "blockingReasons": [],
            "reviewReasons": [],
        },
        "kpis": {
            "revenue": 150000,
            "cogs": 70000,
            "profitManagement": 23000,
            "profitBeforeTax": 23000,
            "profit": 18000 if tax_calculated else None,
            "sales": 150,
            "returns": 15,
            "lossRows": 1,
            "rowCount": 2,
            "vatPayable": 3000 if tax_calculated else None,
            "revenueTax": 2000 if tax_calculated else None,
            "lostSalesUnits": 5,
            "lostSalesRevenue": 10000,
            "lostContributionMargin": 2000,
        },
        "quality": {
            "rowCount": 2,
            "okRows": 2,
            "okShare": 1,
            "missingCostRows": 0,
            "mappingRows": 0,
            "documentReconciliationIssues": 0,
        },
        "taxContext": {
            "calculated": tax_calculated,
            "status": "ready" if tax_calculated else "missing",
            "taxSystem": "УСН Доходы" if tax_calculated else None,
            "vatRate": 5.0 if tax_calculated else None,
            "revenueTaxRate": 0.01 if tax_calculated else None,
            "source": "Catalog_Организации" if tax_calculated else "missing",
        },
        "monthly": [
            {
                "month": "Июль 2026",
                "status": "неполный месяц",
                "revenue": 150000,
                "profit": 18000 if tax_calculated else 23000,
                "margin": 0.12 if tax_calculated else 0.153333,
                "returns": 15,
            }
        ],
        "expenses": [
            {"expense": "Себестоимость 1С", "amount": 70000, "share": 0.4667},
            {"expense": "Комиссия WB", "amount": 20000, "share": 0.1333},
            {"expense": "Логистика WB", "amount": 12000, "share": 0.08},
        ],
        "unitRows": [
            {
                "product": "Прибыльный товар",
                "article1c": "A-1",
                "cabinet": "Основной кабинет",
                "month": "Июль 2026",
                "sales": 100,
                "returns": 5,
                "revenue": 100000,
                "profitBeforeTax": 30000,
                "profit": 25000,
                "commission": 12000,
                "logistics": 10000,
                "storage": 2000,
                "lossDriver": "",
                "status": "ОК",
            },
            {
                "product": "Товар | к проверке",
                "article1c": "A-2",
                "cabinet": "Кабинет Султана",
                "month": "Июль 2026",
                "sales": 50,
                "returns": 10,
                "revenue": 50000,
                "profitBeforeTax": -7000,
                "profit": -7000,
                "commission": 7000,
                "logistics": 20000,
                "storage": 3000,
                "lossDriver": "Возвраты + логистика",
                "status": "ОК",
            },
        ],
        "returns": [
            {
                "product": "Товар | к проверке",
                "cabinet": "Кабинет Султана",
                "sales": 50,
                "returns": 10,
                "returnAmount": 10000,
            }
        ],
        "lostSalesCoverage": {
            "calculated": True,
            "calculationPeriodStart": "2026-07-01",
            "calculationPeriodEnd": "2026-07-12",
        },
        "lostSales": [
            {
                "product": "Прибыльный товар",
                "cabinet": "Основной кабинет",
                "zeroStockDays": 2,
                "onecStock": 4,
                "lostUnits": 5,
                "lostRevenue": 10000,
            }
        ],
        "reconciliationMonthly": [
            {
                "month": "Июль 2026",
                "quantity_delta": 0,
                "cogs_delta": 0,
                "mp_expenses_delta": 0,
                "status": "OK",
            }
        ],
    }


def logistics_analysis_payload() -> dict:
    return {
        "financialMetricStatus": "ready",
        "kpis": {
            "logisticsTotal": 12500,
            "logisticsSharePct": 8.33,
            "profitEffectAmount": -12500,
            "logisticsPerOrder": 125,
            "logisticsPerSale": 83.33,
            "orderCount": 100,
            "salesQuantity": 150,
            "returnQuantity": 15,
            "revenue": 150000,
        },
        "components": {
            "forward": 8500,
            "reverse": 3000,
            "adjustment": 500,
            "unclassified": 500,
        },
        "dynamics": [
            {
                "periodStart": "2026-07-06",
                "logisticsTotal": 6000,
                "revenue": 70000,
                "logisticsSharePct": 8.57,
            },
            {
                "periodStart": "2026-07-13",
                "logisticsTotal": 6500,
                "revenue": 80000,
                "logisticsSharePct": 8.13,
            },
        ],
        "rankings": {
            "byTotal": [
                {
                    "productRef": "product-a",
                    "product": "Товар с высокой логистикой",
                    "logisticsTotal": 7000,
                    "logisticsReverse": 2400,
                    "logisticsSharePct": 10,
                    "profitEffectAmount": -7000,
                    "dataQualityStatus": "ready",
                }
            ],
            "byRevenueShare": [
                {
                    "productRef": "product-b",
                    "product": "Товар с высокой долей",
                    "logisticsTotal": 3500,
                    "logisticsReverse": 300,
                    "logisticsSharePct": 18,
                    "profitEffectAmount": -3500,
                    "dataQualityStatus": "partial",
                }
            ],
            "byProfitEffect": [
                {
                    "productRef": "product-a",
                    "product": "Товар с высокой логистикой",
                    "logisticsTotal": 7000,
                    "logisticsReverse": 2400,
                    "logisticsSharePct": 10,
                    "profitEffectAmount": -7000,
                    "dataQualityStatus": "ready",
                }
            ],
        },
        "periodContext": {
            "requestedPeriod": {
                "periodStart": "2026-07-01",
                "periodEnd": "2026-07-24",
            },
            "analysisPeriod": {
                "periodStart": "2026-07-06",
                "periodEnd": "2026-07-19",
            },
        },
        "partialPeriods": [
            {
                "periodStart": "2026-07-20",
                "periodEnd": "2026-07-24",
                "financialMetricStatus": "not_available_partial_week",
                "kpis": {
                    "logisticsTotal": 1200,
                    "orderCount": 14,
                    "revenue": None,
                    "profitEffectAmount": None,
                },
            }
        ],
        "factorStates": [
            {
                "code": "F-1",
                "label": "Габариты",
                "status": "partial",
                "message": "доступна только подтвержденная часть данных",
            }
        ],
        "insight": {
            "version": "wb-logistics-insight-v1",
            "headline": "Финансовое влияние рассчитано по закрытым неделям.",
            "findings": [
                {
                    "title": "Логистика закрытого периода",
                    "message": "Фактический расход.",
                    "amount": 12500,
                }
            ],
            "actions": [
                {
                    "priority": 1,
                    "title": "Проверить обратную логистику",
                    "message": "Сверить подтвержденные цепочки.",
                }
            ],
            "limitations": ["Неполная неделя не входит в долю и влияние на прибыль."],
        },
    }


def test_client_report_is_answer_first_and_uses_onec_tax_settings() -> None:
    markdown = build_client_analytical_markdown(report_payload())

    assert markdown.startswith("# Аналитический отчёт")
    assert "## Executive Summary — краткий вывод" in markdown
    assert markdown.index("## Executive Summary") < markdown.index(
        "## Параметры отчёта"
    )
    assert "## Налоги рассчитаны по настройкам 1С" in markdown
    assert "Прибыль до налогов" in markdown
    assert "| Ставка НДС | 5,00% |" in markdown
    assert "| Ставка налога с выручки | 1,00% |" in markdown
    assert "500,00%" not in markdown
    assert "Отдельное ручное подтверждение не требуется" in markdown
    assert "Подтвердить налоговый профиль" not in markdown
    assert "report-july-2026" in markdown
    assert "Товар / к проверке" in markdown
    assert "## Аналитические выводы и действия по кабинетам" in markdown
    assert "### Кабинет Султана" in markdown
    assert "**Сценарный ориентир, не прогноз.**" in markdown
    assert "**На этой неделе — разобрать логистику.**" in markdown
    assert "прибыль вырастет" not in markdown
    assert CLIENT_REPORT_CONTRACT_VERSION in markdown


def test_client_report_uses_same_logistics_insight_without_zero_substitution() -> None:
    payload = report_payload()
    payload["logisticsAnalysis"] = logistics_analysis_payload()

    markdown = build_client_analytical_markdown(payload)

    assert "## Логистика WB: затраты, влияние и проблемные зоны" in markdown
    assert "**Логистика.** За закрытый период" in markdown
    assert "### Финансовый итог закрытого периода" in markdown
    assert "| Доля логистики в выручке | 8,33% |" in markdown
    assert "### Из чего сложились логистические затраты" in markdown
    assert "| Возвратная логистика | 3 000,00 ₽ | 24,00% |" in markdown
    assert "### Недельная динамика затрат" in markdown
    assert "### Какие товары проверить в первую очередь" in markdown
    assert "Максимальная сумма, Наибольшее влияние" in markdown
    assert "Товар с высокой долей" in markdown
    assert "### Приоритет действий финансового директора" in markdown
    assert "2026-07-06 — 2026-07-19" in markdown
    assert "Финансовое влияние рассчитано по закрытым неделям." in markdown
    assert "Текущая незакрытая неделя — только оперативный факт" in markdown
    assert "Недоступны до закрытия полной недели" in markdown
    assert "F‑1…F‑5" in markdown
    assert "F-1 · Габариты | partial" in markdown
    assert markdown.index("## Логистика WB") < markdown.index(
        "## Динамика: результат по месяцам"
    )
    assert CLIENT_REPORT_CONTRACT_VERSION == "client-analytical-report.v5"


def test_client_report_keeps_missing_logistics_financial_kpis_explicit() -> None:
    payload = report_payload()
    logistics = logistics_analysis_payload()
    logistics["financialMetricStatus"] = "not_available_missing_profit_link"
    logistics["kpis"]["logisticsSharePct"] = None
    logistics["kpis"]["profitEffectAmount"] = None
    logistics["rankings"]["byRevenueShare"] = []
    logistics["rankings"]["byProfitEffect"] = []
    payload["logisticsAnalysis"] = logistics

    markdown = build_client_analytical_markdown(payload)

    assert "| Доля логистики в выручке | Не рассчитано |" in markdown
    assert "| Влияние на прибыль | Не рассчитано |" in markdown
    assert "доля в выручке и влияние на прибыль требуют подтверждения связи" in markdown
    assert "| Доля логистики в выручке | 0,00% |" not in markdown


def test_client_report_without_closed_week_shows_only_known_operational_fact() -> None:
    payload = report_payload()
    logistics = logistics_analysis_payload()
    logistics["periodContext"]["analysisPeriod"] = None
    logistics["kpis"] = {key: None for key in logistics["kpis"]}
    logistics["components"] = {
        key: None for key in logistics["components"]
    }
    logistics["dynamics"] = []
    logistics["rankings"] = {
        "byTotal": [],
        "byRevenueShare": [],
        "byProfitEffect": [],
    }
    logistics["partialPeriods"][0]["kpis"]["logisticsTotal"] = None
    logistics["insight"]["headline"] = (
        "В выбранном периоде пока нет полной закрытой недели."
    )
    payload["logisticsAnalysis"] = logistics

    markdown = build_client_analytical_markdown(payload)

    assert "Нет полной недели для финансового анализа" in markdown
    assert "Оперативный расход не рассчитан" in markdown
    assert "### Финансовый итог закрытого периода" not in markdown
    assert "### Из чего сложились логистические затраты" not in markdown
    assert "Доступен только оперативный расход 0,00 ₽" not in markdown


def test_client_report_does_not_replace_missing_tax_with_zero() -> None:
    markdown = build_client_analytical_markdown(report_payload(tax_calculated=False))

    assert "## Налоговые настройки 1С не применены к отчёту" in markdown
    assert "Управленческая прибыль WB" in markdown
    assert "налоговые показатели не подменяются нулями" in markdown
    assert "Подтвердить налоговый профиль" not in markdown


def test_client_report_rejects_contradictory_negative_result_driver() -> None:
    payload = report_payload()
    payload["unitRows"][1]["lossDriver"] = "Маржинальный доход не отрицательный"

    markdown = build_client_analytical_markdown(payload)

    assert "Маржинальный доход не отрицательный" not in markdown
    assert "Причина требует отдельного расчёта" in markdown


def test_cost_reason_does_not_inflate_mapping_issue_count() -> None:
    payload = report_payload()
    payload["unitRows"][1].update(
        {
            "status": "Нет себестоимости 1С",
            "statusReason": (
                "Для сопоставленного товара нет действующей себестоимости 1С"
            ),
            "lossDriver": "Нет себестоимости 1С",
        }
    )

    markdown = build_client_analytical_markdown(payload)

    assert "строки сопоставления: 0" in markdown


def test_client_report_docx_preserves_source_and_content(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "wb_unit_economics.client_report.convert_client_docx_to_pdf",
        lambda _path: (None, "unavailable", "test"),
    )
    payload = report_payload()
    payload["logisticsAnalysis"] = logistics_analysis_payload()
    artifacts = build_client_analytical_report(
        summary=payload,
        output_dir=tmp_path,
        basename="client-report",
        branded=False,
    )
    markdown = artifacts.markdown_path.read_text(encoding="utf-8")

    assert artifacts.docx_path.exists()
    assert artifacts.pdf_path is None
    assert docx_source_sha256(artifacts.docx_path) == artifacts.source_sha256
    assert normalized_docx_tokens(artifacts.docx_path) == normalized_markdown_tokens(
        markdown
    )
    assert "Логистика WB: затраты, влияние и проблемные зоны" in markdown


def test_client_report_inaccessible_optional_logo_does_not_block_docx(
    tmp_path: Path,
    monkeypatch,
) -> None:
    logo_path = tmp_path / "restricted" / "logo.png"
    original_is_file = Path.is_file

    def fake_is_file(path: Path) -> bool:
        if path == logo_path:
            raise PermissionError("logo directory is not readable")
        return original_is_file(path)

    monkeypatch.setattr(Path, "is_file", fake_is_file)
    monkeypatch.setattr(
        "wb_unit_economics.client_report.convert_client_docx_to_pdf",
        lambda _path: (None, "unavailable", "test"),
    )

    artifacts = build_client_analytical_report(
        summary=report_payload(),
        output_dir=tmp_path / "output",
        basename="report-without-logo",
        logo_path=logo_path,
        branded=True,
    )

    assert artifacts.markdown_path.is_file()
    assert artifacts.docx_path.is_file()


def test_client_report_html_comes_from_same_markdown_and_escapes_values() -> None:
    markdown = build_client_analytical_markdown(report_payload())
    rendered = render_client_report_html(markdown)

    assert "<h2>Executive Summary — краткий вывод</h2>" in rendered
    assert "<strong>Результат периода.</strong>" in rendered
    assert "Товар / к проверке" in rendered
    assert "source-sha256" in rendered


def test_scoped_report_summary_keeps_source_lineage_and_relabels_only_scope(
    monkeypatch,
) -> None:
    report = SimpleNamespace(
        period_start=date(2026, 3, 1),
        period_end=date(2026, 7, 12),
        return_reason_limitation="Причина возврата не передаётся",
    )
    base = report_payload()
    base["meta"]["reportPeriod"] = "01.03.2026 - 12.07.2026"
    base["meta"]["sourceCoverage"] = "23.02.2026 - 12.07.2026"
    scoped_row = {
        **base["unitRows"][0],
        "id": "row-1",
        "week": "2026-07-06",
    }
    analytics = {
        "kpis": {**base["kpis"], "rowCount": 1},
        "quality": {**base["quality"], "rowCount": 1},
        "monthly": base["monthly"],
        "expenses": base["expenses"],
        "lostSales": [],
        "lostSalesCoverage": {"calculated": False},
        "taxContext": base["taxContext"],
    }
    monkeypatch.setattr(
        "wb_unit_economics.web.report_scope.repository.report_summary_payload",
        lambda _db, _report: base,
    )
    monkeypatch.setattr(
        "wb_unit_economics.web.report_scope.repository.query_report_rows",
        lambda *_args, **_kwargs: {
            "items": [scoped_row],
            "total": 1,
            "analytics": analytics,
        },
    )
    monkeypatch.setattr(
        "wb_unit_economics.web.report_scope.repository.returns_payload",
        lambda rows, _limitation: [{"id": rows[0]["id"]}],
    )

    summary = _report_summary(
        object(),
        report,
        period_start=date(2026, 7, 6),
        period_end=date(2026, 7, 12),
    )

    assert summary["meta"]["reportPeriod"] == "06.07.2026 - 12.07.2026"
    assert summary["meta"]["periodStatus"] == "закрытая неделя"
    assert summary["meta"]["sourceReportPeriod"] == "01.03.2026 - 12.07.2026"
    assert summary["meta"]["sourceReportCoverage"] == "23.02.2026 - 12.07.2026"
    assert summary["unitRows"] == [scoped_row]
    assert summary["returns"] == [{"id": "row-1"}]
    assert summary["reconciliationMonthly"] == []
