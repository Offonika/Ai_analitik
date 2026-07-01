from __future__ import annotations

import json
from datetime import date, datetime
from decimal import Decimal
from io import StringIO
from pathlib import Path
from zoneinfo import ZoneInfo

from wb_unit_economics.contracts import (
    AccountOrgMapping,
    MappingStatus,
    OnecUnfCostSnapshot,
    SkuMapping,
)
from wb_unit_economics.postgres_finance import (
    DETAIL_COLUMNS,
    cost_snapshot_db_row_to_contract,
    iter_cost_snapshot_records,
    iter_sku_mapping_records,
    iter_wb_finance_detail_records,
    iter_wb_finance_page_records,
    sku_mapping_db_row_to_contract,
    wb_finance_db_row_to_snapshot,
    write_copy_payload,
)


def test_postgres_finance_records_keep_raw_payload_and_week(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        rows=[
            {
                "rrdId": 10,
                "reportId": "777",
                "rrDate": "2026-04-08",
                "nmId": 101,
                "vendorCode": "Vendor-1",
                "sku": "204",
                "docTypeName": "Продажа",
                "sellerOperName": "Продажа",
                "quantity": 2,
                "retailAmount": "1000",
                "ppvzSalesCommission": "100",
                "deliveryService": "50",
                "paidStorage": "5",
                "paidAcceptance": "0",
                "penalty": "1",
                "additionalPayment": "3",
                "deduction": "4",
                "acquiringFee": "11",
                "deliveryMethod": "FBS",
                "currency": "RUB",
                "unexpectedColumn": "must stay in jsonb",
            }
        ],
    )

    records = list(
        iter_wb_finance_detail_records(
            export_dir,
            client_id="client",
            account_org_mapping=[
                AccountOrgMapping(
                    client_id="client",
                    seller_account_id="WB_ACCOUNT_2",
                    organization_id="ORG-2",
                    seller_account_name="Султан",
                    organization_name="Организация 2",
                )
            ],
            snapshot_id="snapshot-1",
        )
    )

    assert len(records) == 1
    record = records[0]
    assert record["organization_id"] == "ORG-2"
    assert record["report_id"] == "777"
    assert record["row_date"] == date(2026, 4, 8)
    assert record["week_start"] == date(2026, 4, 6)
    assert record["week_end"] == date(2026, 4, 12)
    assert record["sales_model"] == "fbs"
    assert record["net_revenue"] == 1000
    assert record["deduction"] == 4
    assert record["penalties_and_holdbacks"] == -2
    assert record["is_partial_source"] is True
    assert json.loads(record["row_payload"])["unexpectedColumn"] == "must stay in jsonb"


def test_postgres_page_records_include_rate_limit_status(tmp_path: Path) -> None:
    export_dir = _write_export(tmp_path, rows=[])

    pages = list(
        iter_wb_finance_page_records(
            export_dir,
            client_id="client",
            snapshot_id="snapshot-1",
        )
    )

    assert [page["status"] for page in pages] == ["rate_limited", "ok"]
    assert pages[0]["seller_account_id"] == "WB_ACCOUNT_1"
    assert pages[0]["row_count"] == 0
    assert pages[0]["error"] == "HTTP 429"
    assert json.loads(pages[0]["manifest_payload"])["status_code"] == 429


def test_db_row_to_snapshot_restores_contract_values() -> None:
    snapshot = wb_finance_db_row_to_snapshot(
        {
            "client_id": "client",
            "seller_account_id": "WB_ACCOUNT_2",
            "organization_id": "ORG-2",
            "row_date": "2026-04-08",
            "source_endpoint": "https://example.test/wb",
            "loaded_at": "2026-06-17T14:52:08.288988+03:00",
            "wb_document_id": "10",
            "wb_report_id": "777",
            "nm_id": "101",
            "vendor_code": "vendor-1",
            "barcode": "204",
            "sales_model": "fbs",
            "operation_type": "Возврат",
            "quantity": "-1",
            "net_revenue": "-500.50",
            "wb_commission": "-50",
            "logistics": "30",
            "storage": "0",
            "acceptance": "0",
            "penalties_and_holdbacks": "2",
            "acquiring": "-7",
            "currency": "RUB",
            "raw_payload_hash": "hash",
            "sale_dt": "2026-04-01T01:04:02+00:00",
            "is_partial_source": "t",
        }
    )

    assert snapshot.period_start == date(2026, 4, 8)
    assert snapshot.period_end == date(2026, 4, 8)
    assert snapshot.wb_report_id == "777"
    assert snapshot.nm_id == 101
    assert snapshot.barcode == "204"
    assert snapshot.quantity == -1
    assert snapshot.net_revenue == Decimal("-500.50")
    assert snapshot.is_partial_source is True
    assert snapshot.original_sale_date == date(2026, 4, 1)


def test_sku_mapping_records_round_trip_contract_values() -> None:
    updated_at = datetime(2026, 6, 17, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    mapping = SkuMapping(
        client_id="client",
        seller_account_id="WB_ACCOUNT_2",
        organization_id="ORG-2",
        nm_id=142970288,
        vendor_code="свитер2бсиний",
        barcode="",
        onec_item_id="ITEM-1",
        onec_article="свитер2бсиний",
        onec_characteristic="",
        match_method="onec_marketplace_mapping",
        confidence=Decimal("1"),
        status=MappingStatus.MATCHED,
        comment="сопоставлено из модуля маркетплейса 1С",
        updated_by="1c_marketplace_export",
        updated_at=updated_at,
    )

    record = next(iter_sku_mapping_records([mapping], snapshot_id="snapshot-1"))
    changed_record = next(
        iter_sku_mapping_records(
            [
                mapping.model_copy(
                    update={
                        "status": MappingStatus.AMBIGUOUS,
                        "onec_item_id": "ITEM-2",
                    }
                )
            ],
            snapshot_id="snapshot-1",
        )
    )
    restored = sku_mapping_db_row_to_contract(record)

    assert record["snapshot_id"] == "snapshot-1"
    assert isinstance(record["mapping_key"], str)
    assert changed_record["mapping_key"] == record["mapping_key"]
    assert restored.seller_account_id == "WB_ACCOUNT_2"
    assert restored.nm_id == 142970288
    assert restored.vendor_code == "свитер2бсиний"
    assert restored.onec_item_id == "ITEM-1"
    assert restored.status is MappingStatus.MATCHED
    assert restored.updated_at == updated_at


def test_cost_snapshot_records_round_trip_contract_values() -> None:
    loaded_at = datetime(2026, 6, 17, 12, 0, tzinfo=ZoneInfo("Europe/Moscow"))
    cost = OnecUnfCostSnapshot(
        client_id="client",
        organization_id="ORG-2",
        loaded_at=loaded_at,
        onec_item_id="ITEM-1",
        article="свитер2бсиний",
        barcode="",
        name="Свитер 2B синий",
        characteristic="",
        cost_value=Decimal("320.45"),
        extra_costs_value=Decimal("0"),
        cost_currency="RUB",
        cost_method="sales_register_weighted_average_allocated_extra_costs",
        effective_from=date(2026, 4, 1),
        source_document="AccumulationRegister_Продажи",
        raw_payload_hash="hash-1",
    )

    record = next(iter_cost_snapshot_records([cost], snapshot_id="snapshot-1"))
    changed_record = next(
        iter_cost_snapshot_records(
            [
                cost.model_copy(
                    update={
                        "cost_value": Decimal("321.00"),
                        "raw_payload_hash": "hash-2",
                    }
                )
            ],
            snapshot_id="snapshot-1",
        )
    )
    restored = cost_snapshot_db_row_to_contract(record)

    assert record["snapshot_id"] == "snapshot-1"
    assert isinstance(record["cost_key"], str)
    assert changed_record["cost_key"] == record["cost_key"]
    assert restored.onec_item_id == "ITEM-1"
    assert restored.article == "свитер2бсиний"
    assert restored.cost_value == Decimal("320.45")
    assert restored.extra_costs_value == Decimal("0")
    assert restored.cost_with_extra_costs == Decimal("320.45")
    assert (
        restored.cost_method
        == "sales_register_weighted_average_allocated_extra_costs"
    )
    assert restored.effective_from == date(2026, 4, 1)


def test_copy_payload_uses_csv_copy_and_jsonb_text(tmp_path: Path) -> None:
    export_dir = _write_export(
        tmp_path,
        rows=[{"rrdId": 10, "rrDate": "2026-04-08", "nmId": 101}],
    )
    record = next(
        iter_wb_finance_detail_records(
            export_dir,
            client_id="client",
            account_org_mapping=[
                AccountOrgMapping(
                    client_id="client",
                    seller_account_id="WB_ACCOUNT_2",
                    organization_id="ORG-2",
                    seller_account_name="Султан",
                    organization_name="Организация 2",
                )
            ],
            snapshot_id="snapshot-1",
        )
    )
    stream = StringIO()

    count = write_copy_payload(
        stream,
        table="wb_unit_economics.wb_finance_detail_raw",
        columns=DETAIL_COLUMNS,
        rows=[record],
    )

    payload = stream.getvalue()
    assert count == 1
    assert payload.startswith("COPY wb_unit_economics.wb_finance_detail_raw")
    assert "rrDate" in payload
    assert "2026-04-08" in payload
    assert payload.endswith("\\.\n")


def _write_export(tmp_path: Path, *, rows: list[dict[str, object]]) -> Path:
    export_dir = tmp_path / "20260617-144810"
    export_dir.mkdir()
    raw_file = export_dir / "wb_account_2_finance_page_1.raw.json"
    raw_file.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    manifest = {
        "endpoint": "https://finance-api.wildberries.ru/api/finance/v1/sales-reports/detailed",
        "generated_at": datetime(
            2026,
            6,
            17,
            14,
            52,
            tzinfo=ZoneInfo("Europe/Moscow"),
        ).isoformat(),
        "period": "daily",
        "period_start": "2026-04-01",
        "period_end": "2026-06-17",
        "source": "wb_finance_sales_reports_detailed",
        "request_delay_seconds": 61.0,
        "results": [
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "account_name": "Минзифа",
                "page_index": 1,
                "ok": False,
                "status": "rate_limited",
                "row_count": 0,
                "status_code": 429,
                "rrd_id_start": 0,
                "rrd_id_next": None,
                "raw_payload_hash": "",
                "output_file": None,
                "error": "HTTP 429",
            },
            {
                "seller_account_id": "WB_ACCOUNT_2",
                "account_name": "Султан",
                "page_index": 1,
                "ok": True,
                "status": "ok",
                "row_count": len(rows),
                "status_code": 200,
                "rrd_id_start": 0,
                "rrd_id_next": 10,
                "raw_payload_hash": "page-hash",
                "output_file": raw_file.name,
                "error": "",
            },
        ],
    }
    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    return export_dir
