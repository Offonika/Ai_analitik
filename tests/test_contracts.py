from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from tests.fixtures import CLIENT_ID, sku_mappings, wb_snapshots
from wb_unit_economics.config import default_account_org_mapping, default_tax_profiles
from wb_unit_economics.contracts import (
    MappingStatus,
    Marketplace,
    OzonApiSnapshot,
    SalesModel,
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
