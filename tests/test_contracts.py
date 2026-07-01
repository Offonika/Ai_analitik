from __future__ import annotations

from tests.fixtures import CLIENT_ID, sku_mappings, wb_snapshots
from wb_unit_economics.config import default_account_org_mapping
from wb_unit_economics.contracts import MappingStatus, SalesModel


def test_default_account_org_mapping_has_two_pairs() -> None:
    mapping = default_account_org_mapping(CLIENT_ID)
    assert [(item.seller_account_id, item.organization_id) for item in mapping] == [
        ("WB_ACCOUNT_1", "1C_ORG_1"),
        ("WB_ACCOUNT_2", "1C_ORG_2"),
    ]


def test_wb_snapshot_contract_parses_decimal_and_sales_model() -> None:
    snapshot = wb_snapshots()[0]
    assert snapshot.sales_model is SalesModel.FBO
    assert snapshot.net_revenue == 1000
    assert snapshot.advertising == 99


def test_sku_mapping_contract_has_statuses() -> None:
    mappings = sku_mappings()
    assert mappings[0].status is MappingStatus.MATCHED
    assert mappings[2].status is MappingStatus.AMBIGUOUS
