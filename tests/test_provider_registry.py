from __future__ import annotations

import pytest

from wb_unit_economics.web import providers


def test_provider_registry_defaults_and_validation() -> None:
    wb = providers.provider_definition("wb_api:extra")
    assert wb.provider_base == "wb_api"
    assert wb.label == "Wildberries API"
    assert providers.normalize_role("wb_api", "") == "finance_reports"
    assert providers.normalize_role("wb_api", "content_cards") == "content_cards"
    assert providers.connection_key("wb_api:second") == "second"

    onec = providers.provider_definition("onec_readonly")
    assert onec.default_role == "cost_documents"
    assert providers.normalize_role("onec_readonly", "unknown") == "cost_documents"

    with pytest.raises(ValueError):
        providers.validate_provider("ozon_api")
