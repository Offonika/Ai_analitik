from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from tests.fixtures import CLIENT_ID, sku_mappings, wb_snapshots
from wb_unit_economics.config import (
    default_account_org_mapping,
    default_tax_profiles,
    tax_profile_source_diagnostic,
    tax_profiles_from_account_org_mapping,
)
from wb_unit_economics.contracts import (
    AccountOrgMapping,
    MappingStatus,
    Marketplace,
    OzonApiSnapshot,
    SalesModel,
    VatDeductionMode,
    VatMode,
)
from wb_unit_economics.marketplace import (
    ozon_snapshot_to_marketplace,
    wb_snapshot_to_marketplace,
)


def test_default_account_org_mapping_has_two_pairs() -> None:
    mapping = default_account_org_mapping(CLIENT_ID)
    assert [(item.seller_account_id, item.organization_id) for item in mapping] == [
        ("WB_ACCOUNT_1", "1C_ORG_1"),
        ("WB_ACCOUNT_2", "1C_ORG_2"),
    ]


def test_default_tax_profiles_keep_legacy_tax_method() -> None:
    profiles = default_tax_profiles(CLIENT_ID)
    profile_values = [
        (item.organization_id, item.vat_rate, item.vat_mode) for item in profiles
    ]
    assert profile_values == [
        ("1C_ORG_1", Decimal("5"), VatMode.INCLUDED),
        ("1C_ORG_2", Decimal("5"), VatMode.INCLUDED),
    ]
    assert all(item.revenue_tax_rate == Decimal("0.01") for item in profiles)
    assert all(item.vat_deduction_mode is VatDeductionMode.UNKNOWN for item in profiles)


def test_tax_profiles_do_not_infer_galustov_osno_from_name() -> None:
    profiles = tax_profiles_from_account_org_mapping(
        CLIENT_ID,
        [
            AccountOrgMapping(
                client_id=CLIENT_ID,
                seller_account_id="WB_ACCOUNT_1",
                organization_id="galustov-org",
                seller_account_name="ИП Галустов",
                organization_name="Галустов Рафаэль Рудольфович",
            )
        ],
    )

    assert profiles == []


def test_shumeyko_partner_mapping_does_not_force_osno_without_onec_settings() -> None:
    profiles = tax_profiles_from_account_org_mapping(
        "shumeyko-partners",
        [
            AccountOrgMapping(
                client_id="shumeyko-partners",
                seller_account_id="WB_ACCOUNT_1",
                organization_id="1C_ORG_1",
                seller_account_name="WB cabinet 1",
                organization_name="1C organization 1",
            ),
            AccountOrgMapping(
                client_id="shumeyko-partners",
                seller_account_id="WB_ACCOUNT_2",
                organization_id="1C_ORG_2",
                seller_account_name="WB cabinet 2",
                organization_name="1C organization 2",
            ),
        ],
    )

    assert profiles == []


def test_tax_profiles_do_not_infer_usn_from_insurance_contribution_field() -> None:
    profiles = tax_profiles_from_account_org_mapping(
        "shumeyko-partners",
        [
            AccountOrgMapping(
                client_id="shumeyko-partners",
                seller_account_id="WB_ACCOUNT_1",
                organization_id="ORG-USN",
                seller_account_name="ИП Галустов",
                organization_name="Галустов Рафаэль Рудольфович",
            )
        ],
        onec_organization_rows=[
            {
                "Ref_Key": "ORG-USN",
                "ВидУчетаСтраховыхВзносов": "УчитыватьВУСН",
            }
        ],
    )

    assert profiles == []


@pytest.mark.parametrize("default_vat_kind", ["Общая", "БезНДС"])
def test_default_vat_kind_from_onec_is_a_hint_not_a_tax_profile(
    default_vat_kind: str,
) -> None:
    organization = {
        "Ref_Key": "ORG-USN",
        "ВидСтавкиНДСПоУмолчанию": default_vat_kind,
        "НДСВключатьВСтоимость": True,
    }
    mapping = [
        AccountOrgMapping(
            client_id="shumeyko-partners",
            seller_account_id="WB_ACCOUNT_1",
            organization_id="ORG-USN",
            seller_account_name="WB cabinet 1",
            organization_name="ИП на УСН",
        )
    ]

    profiles = tax_profiles_from_account_org_mapping(
        "shumeyko-partners",
        mapping,
        onec_organization_rows=[organization],
    )
    diagnostic = tax_profile_source_diagnostic(
        "ORG-USN",
        organization=organization,
    )

    assert profiles == []
    assert diagnostic["status"] == "missing_authoritative_fields"
    assert diagnostic["oneCHints"] == {
        "defaultVatRateKind": default_vat_kind,
        "vatIncludedInCost": True,
        "authoritativeForTaxSystem": False,
    }
    assert "taxSystem" in diagnostic["missingFields"]
    assert "vatDeductionMode" in diagnostic["missingFields"]


def test_tax_profiles_require_explicit_rates_in_special_tax_notification() -> None:
    profiles = tax_profiles_from_account_org_mapping(
        "shumeyko-partners",
        [
            AccountOrgMapping(
                client_id="shumeyko-partners",
                seller_account_id="WB_ACCOUNT_1",
                organization_id="ORG-USN",
                seller_account_name="WB cabinet 1",
                organization_name="1C organization 1",
            )
        ],
        special_tax_mode_rows=[
            {
                "Ref_Key": "NOTICE-1",
                "Posted": True,
                "DeletionMark": False,
                "Организация_Key": "ORG-USN",
                "ВидУведомления": "УведомлениеОПереходеНаУСН",
                "ДатаПодписи": "2026-01-01T00:00:00",
            }
        ],
    )

    assert profiles == []


def test_tax_profiles_use_explicit_onec_organization_profile() -> None:
    profiles = tax_profiles_from_account_org_mapping(
        "shumeyko-partners",
        [
            AccountOrgMapping(
                client_id="shumeyko-partners",
                seller_account_id="OZON-1",
                organization_id="ORG-USN",
                seller_account_name="Ozon cabinet",
                organization_name="ООО Пример",
            )
        ],
        onec_organization_rows=[
            {
                "Ref_Key": "ORG-USN",
                "СистемаНалогообложения": "УСН Доходы",
                "СтавкаНДС": "0",
                "РежимНДС": "none",
                "РежимВычетаНДС": "not_applicable",
                "СтавкаНалогаСВыручки": "0.06",
                "ДатаНачала": "2026-01-01",
            }
        ],
    )

    assert len(profiles) == 1
    assert profiles[0].organization_id == "ORG-USN"
    assert profiles[0].tax_system == "УСН Доходы"
    assert profiles[0].vat_mode is VatMode.NONE
    assert profiles[0].vat_deduction_mode is VatDeductionMode.NOT_APPLICABLE
    assert profiles[0].revenue_tax_rate == Decimal("0.06")
    assert profiles[0].valid_from == date(2026, 1, 1)
    assert profiles[0].source == "Catalog_Организации"


def test_wb_snapshot_contract_parses_decimal_and_sales_model() -> None:
    snapshot = wb_snapshots()[0]
    assert snapshot.sales_model is SalesModel.FBO
    assert snapshot.net_revenue == 1000
    assert snapshot.advertising == 99


def test_sku_mapping_contract_has_statuses() -> None:
    mappings = sku_mappings()
    assert mappings[0].status is MappingStatus.MATCHED
    assert mappings[2].status is MappingStatus.AMBIGUOUS


def test_ozon_snapshot_contract_parses_decimal_and_period() -> None:
    snapshot = OzonApiSnapshot(
        client_id=CLIENT_ID,
        seller_account_id="OZON_ACCOUNT_1",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        source_endpoint="/v1/finance/cash-flow-statement/list",
        loaded_at=datetime(2026, 7, 3, 12, 0),
        offer_id="SKU-1",
        sales_quantity="3",
        return_quantity="1",
        gross_revenue="1500.50",
        commission="123.45",
        raw_payload_hash="ozon-hash",
    )
    assert snapshot.sales_quantity == Decimal("3")
    assert snapshot.return_quantity == Decimal("1")
    assert snapshot.gross_revenue == Decimal("1500.50")
    assert snapshot.commission == Decimal("123.45")

    with pytest.raises(ValueError):
        OzonApiSnapshot(
            client_id=CLIENT_ID,
            seller_account_id="OZON_ACCOUNT_1",
            period_start=date(2026, 7, 1),
            period_end=date(2026, 6, 30),
            source_endpoint="/v1/finance/cash-flow-statement/list",
            loaded_at=datetime(2026, 7, 3, 12, 0),
            raw_payload_hash="ozon-hash",
        )


def test_marketplace_contract_normalizes_wb_and_ozon() -> None:
    wb_row = wb_snapshot_to_marketplace(wb_snapshots()[0])
    assert wb_row.marketplace is Marketplace.WB
    assert wb_row.nm_id == 101
    assert wb_row.commission == 100
    assert wb_row.promotion == 0

    ozon_row = ozon_snapshot_to_marketplace(
        OzonApiSnapshot(
            client_id=CLIENT_ID,
            seller_account_id="OZON_ACCOUNT_1",
            organization_id="1C_ORG_1",
            period_start=date(2026, 6, 1),
            period_end=date(2026, 6, 30),
            source_endpoint="/v1/finance/cash-flow-statement/list",
            loaded_at=datetime(2026, 7, 3, 12, 0),
            source_report_code="report-code",
            product_id="123",
            ozon_sku="456",
            offer_id="A-1",
            net_revenue="1000",
            logistics="50",
            payout="900",
            raw_payload_hash="ozon-hash",
        )
    )
    assert ozon_row.marketplace is Marketplace.OZON
    assert ozon_row.offer_id == "A-1"
    assert ozon_row.ozon_sku == "456"
    assert ozon_row.payout == 900
