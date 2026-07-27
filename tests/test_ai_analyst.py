from datetime import date
from types import SimpleNamespace

from wb_unit_economics.web import repository
from wb_unit_economics.web.ai import AiAnalyst
from wb_unit_economics.web.settings import WebSettings


def test_ai_limitations_use_current_period_status_not_static_june() -> None:
    analyst = AiAnalyst(WebSettings())
    summary = {
        "meta": {
            "periodStatus": "предварительный: июль неполный",
            "returnReasonLimitation": "Причины возвратов недоступны.",
        }
    }

    limitations = analyst._limitations(summary)

    assert any("июль неполный" in item for item in limitations)
    assert not any("июнь" in item.casefold() for item in limitations)


def test_ai_does_not_render_missing_financial_value_as_zero() -> None:
    analyst = AiAnalyst(WebSettings())

    assert analyst._money_or_na(None) == "не рассчитано"
    assert analyst._money_or_na(0) == "0 ₽"


def test_ai_logistics_digest_excludes_external_ids_and_raw_lineage() -> None:
    analyst = AiAnalyst(WebSettings())

    digest = analyst._logistics_digest(
        {
            "dataStatus": "ready",
            "sliceStatus": "partial",
            "financialMetricStatus": "not_available_partial_week",
            "methodologyVersion": "wb-logistics-v5",
            "coverage": {"keyPct": 100},
            "filterContext": {
                "wbCabinetId": "must-not-leak-cabinet",
                "clientCompanyId": "must-not-leak-company",
            },
            "kpis": {"logisticsTotal": 100},
            "components": {"reverse": 40},
            "rankings": {
                "byTotal": [
                    {
                        "product": "Панама",
                        "productKey": "nm:123",
                        "nmId": "123",
                        "sku": "external-sku",
                        "logisticsTotal": 100,
                        "logisticsReverse": 40,
                        "logisticsSharePct": 10,
                        "profitEffectAmount": -100,
                        "orderCount": 12,
                        "returnQuantity": 3,
                        "lowSample": False,
                        "sourceHash": "must-not-leak",
                    }
                ]
            },
            "recommendations": [
                {
                    "code": "check_returns",
                    "title": "Проверить возвраты",
                    "message": "Причину подтвердить отдельно.",
                    "valueType": "fact",
                    "evidence": {
                        "product": "Панама",
                        "productKey": "nm:123",
                        "reverseLogistics": 40,
                    },
                }
            ],
            "periodContext": {
                "analysisPeriod": {
                    "periodStart": "2026-07-13",
                    "periodEnd": "2026-07-19",
                }
            },
            "factorStates": [
                {
                    "code": "F-1",
                    "label": "Габариты",
                    "status": "partial",
                    "message": "доступна подтвержденная часть",
                }
            ],
            "insight": {
                "version": "wb-logistics-insight-v1",
                "headline": "Проверить обратную логистику.",
            },
        }
    )

    assert digest is not None
    serialized = str(digest)
    assert "Панама" in serialized
    assert "nm:123" not in serialized
    assert "external-sku" not in serialized
    assert "must-not-leak" not in serialized
    assert "must-not-leak-cabinet" not in serialized
    assert "must-not-leak-company" not in serialized
    assert digest["financial_metric_status"] == "not_available_partial_week"
    assert digest["factor_states"][0]["status"] == "partial"


def test_ai_logistics_uses_requested_period_from_current_screen(monkeypatch) -> None:
    analyst = AiAnalyst(WebSettings())
    captured: dict[str, object] = {}

    def fake_payload(_db, _report, **kwargs):
        captured.update(kwargs)
        return {"periodContext": {"analysisPeriod": None}}

    monkeypatch.setattr(
        repository,
        "report_logistics_analysis_payload",
        fake_payload,
    )
    report = SimpleNamespace(
        period_start=date(2026, 2, 23),
        period_end=date(2026, 7, 24),
    )
    thread = SimpleNamespace(
        scope={
            "analysisSurface": "logistics",
            "logisticsRequestedPeriodStart": "2026-07-01",
            "logisticsRequestedPeriodEnd": "2026-07-24",
            "logisticsWbCabinetId": "cabinet",
            "logisticsScheme": "fbo",
        }
    )

    analyst._thread_logistics_analysis(None, thread=thread, report=report)

    assert captured["period_start"] == date(2026, 7, 1)
    assert captured["period_end"] == date(2026, 7, 24)
    assert captured["period_mode"] == "closed_weeks"
    assert captured["scheme"] == "fbo"


def test_ai_financial_digest_uses_same_closed_logistics_period(monkeypatch) -> None:
    analyst = AiAnalyst(WebSettings())
    captured: dict[str, object] = {}
    base = {
        "meta": {"period": "весь отчёт", "periodStatus": "предварительный"},
        "kpis": {"revenue": 999, "profit": 555, "rowCount": 99, "lossRows": 9},
        "quality": {"rowCount": 99},
    }

    monkeypatch.setattr(
        repository,
        "report_summary_payload",
        lambda *_args, **_kwargs: base,
    )

    def fake_rows(_db, _report, **kwargs):
        captured.update(kwargs)
        return {
            "total": 1,
            "analytics": {
                "kpis": {
                    "revenue": 100,
                    "profit": 20,
                    "rowCount": 1,
                    "lossRows": 0,
                },
                "quality": {"rowCount": 1},
            },
        }

    monkeypatch.setattr(repository, "query_report_rows", fake_rows)
    logistics = {
        "periodContext": {
            "analysisPeriod": {
                "periodStart": "2026-07-13",
                "periodEnd": "2026-07-19",
            }
        }
    }
    summary = analyst._thread_report_summary(
        None,
        thread=SimpleNamespace(scope={"analysisSurface": "logistics"}),
        report=SimpleNamespace(),
        include_staff_readiness=True,
        logistics_analysis=logistics,
    )

    assert captured["period_start"] == date(2026, 7, 13)
    assert captured["period_end"] == date(2026, 7, 19)
    assert summary["meta"]["period"] == "13.07.2026 - 19.07.2026"
    assert summary["kpis"]["revenue"] == 100
    assert summary["kpis"]["profit"] == 20


def test_ai_without_closed_week_does_not_reuse_full_report_finance(
    monkeypatch,
) -> None:
    analyst = AiAnalyst(WebSettings())
    monkeypatch.setattr(
        repository,
        "report_summary_payload",
        lambda *_args, **_kwargs: {
            "meta": {"period": "весь отчёт"},
            "kpis": {"revenue": 999, "profit": 555, "rowCount": 99},
            "quality": {"rowCount": 99},
        },
    )

    summary = analyst._thread_report_summary(
        None,
        thread=SimpleNamespace(scope={"analysisSurface": "logistics"}),
        report=SimpleNamespace(),
        include_staff_readiness=True,
        logistics_analysis={
            "periodContext": {
                "requestedPeriod": {
                    "periodStart": "2026-07-20",
                    "periodEnd": "2026-07-24",
                },
                "analysisPeriod": None,
            }
        },
    )

    assert summary["meta"]["periodStatus"] == "нет полной закрытой недели"
    assert summary["kpis"]["revenue"] is None
    assert summary["kpis"]["profit"] is None
    assert summary["kpis"]["rowCount"] is None
