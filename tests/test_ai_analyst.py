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
