from __future__ import annotations

import pytest

from wb_unit_economics.web import providers


def test_provider_registry_defaults_and_validation() -> None:
    wb = providers.provider_definition("wb_api:extra")
    assert wb.provider_base == "wb_api"
    assert wb.label == "API Wildberries"
    assert providers.normalize_role("wb_api", "") == "finance_reports"
    assert providers.normalize_role("wb_api", "content_cards") == "content_cards"
    assert providers.connection_key("wb_api:second") == "second"

    onec = providers.provider_definition("onec_readonly")
    assert onec.default_role == "cost_documents"
    assert providers.normalize_role("onec_readonly", "unknown") == "cost_documents"

    ozon = providers.provider_definition("ozon_api:finance")
    assert ozon.provider_base == "ozon_api"
    assert ozon.label == "API кабинета продавца Ozon"
    assert providers.normalize_role("ozon_api", "") == "finance_reports"
    assert providers.normalize_role("ozon_api", "returns_reports") == "returns_reports"
    assert providers.connection_key("ozon_api:finance") == "finance"
    providers.validate_provider("ozon_api")

    with pytest.raises(ValueError):
        providers.validate_provider("unknown_api")
