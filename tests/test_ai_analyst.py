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
            "methodologyVersion": "wb-logistics-v4",
            "coverage": {"keyPct": 100},
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
        }
    )

    assert digest is not None
    serialized = str(digest)
    assert "Панама" in serialized
    assert "nm:123" not in serialized
    assert "external-sku" not in serialized
    assert "must-not-leak" not in serialized
    assert digest["financial_metric_status"] == "not_available_partial_week"
