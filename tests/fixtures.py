from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from wb_unit_economics.config import default_account_org_mapping
from wb_unit_economics.contracts import (
    MappingStatus,
    OnecUnfCostSnapshot,
    SalesModel,
    SkuMapping,
    WbApiSnapshot,
)

CLIENT_ID = "client-shumeyko-test"
TZ = ZoneInfo("Europe/Moscow")


def account_org_mapping():
    return default_account_org_mapping(CLIENT_ID)


def cost_snapshots():
    loaded_at = datetime(2026, 6, 16, 10, 0, tzinfo=TZ)
    return [
        OnecUnfCostSnapshot(
            client_id=CLIENT_ID,
            organization_id="1C_ORG_1",
            loaded_at=loaded_at,
            onec_item_id="ONEC-1",
            article="A-1",
            barcode="111",
            name="Product 1",
            cost_value="100",
            extra_costs_value="15",
            cost_method="with_extra_costs",
            effective_from=date(2026, 1, 1),
            source_document="fixture",
            raw_payload_hash="cost-hash-1",
        ),
        OnecUnfCostSnapshot(
            client_id=CLIENT_ID,
            organization_id="1C_ORG_2",
            loaded_at=loaded_at,
            onec_item_id="ONEC-2",
            article="B-2",
            barcode="222",
            name="Product 2",
            cost_value="200",
            extra_costs_value="25",
            cost_method="with_extra_costs",
            effective_from=date(2026, 1, 1),
            source_document="fixture",
            raw_payload_hash="cost-hash-2",
        ),
    ]


def sku_mappings():
    updated_at = datetime(2026, 6, 16, 10, 0, tzinfo=TZ)
    return [
        SkuMapping(
            client_id=CLIENT_ID,
            seller_account_id="WB_ACCOUNT_1",
            organization_id="1C_ORG_1",
            nm_id=101,
            vendor_code="A-1",
            barcode="",
            onec_item_id="ONEC-1",
            onec_article="A-1",
            match_method="article",
            confidence="1",
            status=MappingStatus.MATCHED,
            updated_by="fixture",
            updated_at=updated_at,
        ),
        SkuMapping(
            client_id=CLIENT_ID,
            seller_account_id="WB_ACCOUNT_2",
            organization_id="1C_ORG_2",
            nm_id=202,
            vendor_code="B-2",
            barcode="",
            onec_item_id="ONEC-2",
            onec_article="B-2",
            match_method="article",
            confidence="1",
            status=MappingStatus.MATCHED,
            updated_by="fixture",
            updated_at=updated_at,
        ),
        SkuMapping(
            client_id=CLIENT_ID,
            seller_account_id="WB_ACCOUNT_1",
            organization_id="1C_ORG_1",
            nm_id=303,
            vendor_code="AMB-3",
            barcode="",
            onec_item_id="ONEC-3",
            onec_article="AMB-3",
            match_method="article",
            confidence="0.5",
            status=MappingStatus.AMBIGUOUS,
            updated_by="fixture",
            updated_at=updated_at,
        ),
    ]


def wb_snapshots():
    loaded_at = datetime(2026, 6, 16, 10, 0, tzinfo=TZ)
    common = {
        "client_id": CLIENT_ID,
        "source_endpoint": "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed",
        "loaded_at": loaded_at,
        "currency": "RUB",
    }
    return [
        WbApiSnapshot(
            **common,
            seller_account_id="WB_ACCOUNT_1",
            organization_id="1C_ORG_1",
            period_start=date(2026, 4, 6),
            period_end=date(2026, 4, 12),
            wb_document_id="doc-1",
            wb_report_id="WB-REPORT-1",
            nm_id=101,
            vendor_code="A-1",
            barcode="111",
            sales_model=SalesModel.FBO,
            operation_type="sale",
            quantity="2",
            net_revenue="1000",
            wb_commission="100",
            logistics="50",
            storage="20",
            acceptance="10",
            penalties_and_holdbacks="5",
            acquiring="15",
            advertising="99",
            raw_payload_hash="wb-hash-1",
        ),
        WbApiSnapshot(
            **common,
            seller_account_id="WB_ACCOUNT_2",
            organization_id="1C_ORG_2",
            period_start=date(2026, 4, 13),
            period_end=date(2026, 4, 19),
            wb_document_id="doc-2",
            wb_report_id="WB-REPORT-1",
            nm_id=202,
            vendor_code="B-2",
            barcode="222",
            sales_model=SalesModel.FBS,
            operation_type="return",
            quantity="-1",
            net_revenue="-500",
            wb_commission="-50",
            logistics="30",
            storage="0",
            acceptance="0",
            penalties_and_holdbacks="0",
            acquiring="-7",
            raw_payload_hash="wb-hash-2",
            original_sale_date=date(2026, 4, 1),
        ),
        WbApiSnapshot(
            **common,
            seller_account_id="WB_ACCOUNT_1",
            organization_id="1C_ORG_1",
            period_start=date(2026, 4, 20),
            period_end=date(2026, 4, 26),
            wb_document_id="doc-3",
            wb_report_id="WB-REPORT-2",
            nm_id=303,
            vendor_code="AMB-3",
            barcode="333",
            sales_model=SalesModel.FBO,
            operation_type="sale",
            quantity="1",
            net_revenue="300",
            wb_commission="30",
            logistics="10",
            storage="5",
            acceptance="0",
            penalties_and_holdbacks="0",
            acquiring="4",
            raw_payload_hash="wb-hash-3",
        ),
        WbApiSnapshot(
            **common,
            seller_account_id="WB_ACCOUNT_1",
            organization_id="1C_ORG_2",
            period_start=date(2026, 4, 27),
            period_end=date(2026, 5, 3),
            wb_document_id="doc-4",
            wb_report_id="WB-REPORT-2",
            nm_id=404,
            vendor_code="ORG-MISMATCH",
            barcode="444",
            sales_model=SalesModel.FBO,
            operation_type="sale",
            quantity="1",
            net_revenue="200",
            wb_commission="20",
            logistics="10",
            storage="0",
            acceptance="0",
            penalties_and_holdbacks="0",
            acquiring="3",
            raw_payload_hash="wb-hash-4",
        ),
    ]
