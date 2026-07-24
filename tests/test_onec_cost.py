from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from tests.fixtures import CLIENT_ID, account_org_mapping, wb_snapshots
from wb_unit_economics.calculation import build_unit_economics_report
from wb_unit_economics.contracts import (
    DataQualityStatus,
    InputVatPolicy,
    MappingStatus,
    OnecUnfCostSnapshot,
    SkuMapping,
)
from wb_unit_economics.onec_cost import (
    PROVISIONAL_COST_METHOD,
    STOCK_REGISTER_FALLBACK_COST_METHOD,
    attach_document_metadata_to_documents,
    attach_settlement_totals_to_documents,
    extract_gross_profit_document_rows,
    extract_marketplace_document_metadata,
    extract_marketplace_settlement_totals,
    extract_provisional_cost_snapshots,
    extract_sales_register_cost_snapshots,
    flatten_stock_record_sets,
    merge_sales_and_stock_cost_snapshots,
)

TZ = ZoneInfo("Europe/Moscow")


def _cost_snapshot(
    *,
    item_id: str,
    cost: str,
    source: str,
    organization_id: str = "1C_ORG_1",
    characteristic: str = "",
) -> OnecUnfCostSnapshot:
    is_sales = source == "sales"
    return OnecUnfCostSnapshot(
        client_id=CLIENT_ID,
        organization_id=organization_id,
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
        onec_item_id=item_id,
        article=f"ARTICLE-{item_id}",
        barcode="",
        name=f"Product {item_id}",
        characteristic=characteristic,
        cost_value=Decimal(cost),
        extra_costs_value=Decimal("0"),
        cost_method=(
            "sales_register_weighted_average_allocated_extra_costs"
            if is_sales
            else PROVISIONAL_COST_METHOD
        ),
        effective_from=date(2026, 4, 6),
        effective_to=date(2026, 4, 12) if is_sales else None,
        source_document_kind="commissioner_report" if is_sales else "",
        source_document=(
            "AccumulationRegister_Продажи"
            if is_sales
            else "AccumulationRegister_Запасы"
        ),
        raw_payload_hash=f"{source}-{organization_id}-{item_id}-{characteristic}",
    )


def stock_rows():
    return [
        {
            "Recorder": "DOC-1",
            "Recorder_Type": "Document",
            "RecordSet": [
                {
                    "Active": True,
                    "LineNumber": "1",
                    "Period": "2026-04-05T00:00:00",
                    "RecordType": "Receipt",
                    "Номенклатура_Key": "ITEM-1",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "CHAR-1",
                    "Количество": "2",
                    "Сумма": "300",
                    "СуммаБезНДС": "250",
                    "ФиксированнаяСтоимость": True,
                },
                {
                    "Active": True,
                    "LineNumber": "2",
                    "Period": "2026-04-06T00:00:00",
                    "RecordType": "Expense",
                    "Номенклатура_Key": "ITEM-1",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "CHAR-1",
                    "Количество": "0",
                    "Сумма": "100",
                    "ФиксированнаяСтоимость": False,
                },
            ],
        }
    ]


def sales_rows():
    return [
        {
            "Recorder": "SALE-DOC-1",
            "Recorder_Type": "Document",
            "RecordSet": [
                {
                    "Active": True,
                    "Period": "2026-04-10T00:00:00",
                    "Номенклатура_Key": "ITEM-1",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "CHAR-1",
                    "Количество": "2",
                    "Себестоимость": "0",
                    "СебестоимостьБезНДС": "0",
                },
                {
                    "Active": True,
                    "Period": "2026-04-12T00:00:00",
                    "Номенклатура_Key": "ITEM-1",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "CHAR-1",
                    "Количество": "3",
                    "Себестоимость": "0",
                    "СебестоимостьБезНДС": "0",
                },
                {
                    "Active": True,
                    "Period": "2026-04-12T00:00:00",
                    "Номенклатура_Key": "ITEM-1",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "CHAR-1",
                    "Количество": "0",
                    "Себестоимость": "220",
                    "СебестоимостьБезНДС": "200",
                },
                {
                    "Active": True,
                    "Period": "2026-04-12T00:00:00",
                    "Номенклатура_Key": "ITEM-1",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "CHAR-1",
                    "Количество": "0",
                    "Себестоимость": "390",
                    "СебестоимостьБезНДС": "360",
                },
                {
                    "Active": True,
                    "Period": "2026-04-12T00:00:00",
                    "Номенклатура_Key": "ITEM-2",
                    "Организация_Key": "1C_ORG_1",
                    "Характеристика_Key": "",
                    "Количество": "0",
                    "Себестоимость": "10",
                    "СебестоимостьБезНДС": "9",
                },
            ],
        }
    ]


def test_flatten_stock_record_sets_preserves_recorder_context() -> None:
    rows = flatten_stock_record_sets(stock_rows())

    assert len(rows) == 2
    assert rows[0]["Recorder"] == "DOC-1"
    assert rows[0]["LineNumber"] == "1"


def test_extract_provisional_fixed_receipt_cost_candidates() -> None:
    costs = extract_provisional_cost_snapshots(
        client_id=CLIENT_ID,
        stock_rows=stock_rows(),
        barcode_rows=[
            {
                "Штрихкод": "111",
                "Номенклатура_Key": "ITEM-1",
                "Характеристика_Key": "CHAR-1",
            }
        ],
        nomenclature_rows=[
            {"Ref_Key": "ITEM-1", "Артикул": "A-1", "Description": "Product"}
        ],
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(costs) == 1
    assert costs[0].onec_item_id == "ITEM-1"
    assert costs[0].barcode == "111"
    assert costs[0].cost_value == Decimal("150")
    assert costs[0].cost_method == PROVISIONAL_COST_METHOD
    assert costs[0].effective_from == date(2026, 4, 5)


def test_stock_cost_fills_item_missing_from_sales_register() -> None:
    sales = [_cost_snapshot(item_id="ITEM-1", cost="120", source="sales")]
    stock = [
        _cost_snapshot(item_id="ITEM-1", cost="90", source="stock"),
        _cost_snapshot(item_id="ITEM-2", cost="80", source="stock"),
    ]

    merged = merge_sales_and_stock_cost_snapshots(sales, stock)

    assert [(item.onec_item_id, item.cost_value) for item in merged] == [
        ("ITEM-1", Decimal("120")),
        ("ITEM-2", Decimal("80")),
    ]
    assert merged[0].cost_method == (
        "sales_register_weighted_average_allocated_extra_costs"
    )
    assert merged[1].cost_method == STOCK_REGISTER_FALLBACK_COST_METHOD
    assert "AccumulationRegister_Запасы fallback" in merged[1].source_document


def test_stock_cost_replaces_zero_only_sales_item() -> None:
    sales = [_cost_snapshot(item_id="ITEM-1", cost="0", source="sales")]
    stock = [_cost_snapshot(item_id="ITEM-1", cost="90", source="stock")]

    merged = merge_sales_and_stock_cost_snapshots(sales, stock)

    assert len(merged) == 1
    assert merged[0].cost_value == Decimal("90")
    assert merged[0].cost_method == STOCK_REGISTER_FALLBACK_COST_METHOD


def test_nonzero_sales_cost_blocks_stock_fallback_for_same_item_and_org() -> None:
    sales = [
        _cost_snapshot(
            item_id="ITEM-1",
            cost="120",
            source="sales",
            characteristic="CHAR-1",
        )
    ]
    stock = [
        _cost_snapshot(
            item_id="ITEM-1",
            cost="90",
            source="stock",
            characteristic="CHAR-2",
        )
    ]

    merged = merge_sales_and_stock_cost_snapshots(sales, stock)

    assert merged == sales


def test_sales_cost_priority_is_scoped_by_organization() -> None:
    sales = [
        _cost_snapshot(
            item_id="ITEM-1",
            organization_id="ORG-1",
            cost="120",
            source="sales",
        )
    ]
    stock = [
        _cost_snapshot(
            item_id="ITEM-1",
            organization_id="ORG-2",
            cost="90",
            source="stock",
        )
    ]

    merged = merge_sales_and_stock_cost_snapshots(sales, stock)

    assert [item.organization_id for item in merged] == ["ORG-1", "ORG-2"]
    assert merged[1].cost_method == STOCK_REGISTER_FALLBACK_COST_METHOD


def test_merged_stock_fallback_is_used_and_marked_for_review() -> None:
    mapping = SkuMapping(
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
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    costs = merge_sales_and_stock_cost_snapshots(
        [_cost_snapshot(item_id="OTHER-ITEM", cost="120", source="sales")],
        [_cost_snapshot(item_id="ONEC-1", cost="100", source="stock")],
    )

    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=costs,
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert report.rows[0].data_quality_status is DataQualityStatus.NEEDS_REVIEW
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("200.00")
    assert report.rows[0].cost_method == STOCK_REGISTER_FALLBACK_COST_METHOD


def test_extract_sales_register_cost_candidates_weighted_average() -> None:
    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        barcode_rows=[
            {
                "Штрихкод": "111",
                "Номенклатура_Key": "ITEM-1",
                "Характеристика_Key": "CHAR-1",
            }
        ],
        nomenclature_rows=[
            {"Ref_Key": "ITEM-1", "Артикул": "A-1", "Description": "Product"}
        ],
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(costs) == 1
    assert costs[0].onec_item_id == "ITEM-1"
    assert costs[0].barcode == "111"
    assert costs[0].characteristic == ""
    assert costs[0].cost_value == Decimal("122")
    assert costs[0].extra_costs_value == Decimal("0")
    assert (
        costs[0].cost_method
        == "sales_register_weighted_average_allocated_extra_costs"
    )
    assert costs[0].effective_from == date(2026, 4, 6)
    assert costs[0].effective_to == date(2026, 4, 12)
    assert costs[0].source_document == (
        "AccumulationRegister_Продажи 2026-04-06..2026-04-12"
    )


def test_extract_sales_register_cost_candidates_without_vat_field() -> None:
    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        amount_field="СебестоимостьБезНДС",
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(costs) == 1
    assert costs[0].cost_value == Decimal("112")
    assert costs[0].cost_method == (
        "sales_register_weighted_average_without_vat_reconciliation_needs_review"
    )


def test_sales_cost_difference_becomes_audited_management_input_vat() -> None:
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )

    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        amount_field="СебестоимостьБезНДС",
        input_vat_policies=[policy],
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(costs) == 1
    assert costs[0].cost_value == Decimal("112")
    assert costs[0].input_vat_value == Decimal("10")
    assert costs[0].input_vat_source == (
        "management_assumption:sales_cost_difference"
    )


def test_input_vat_policy_period_and_organization_are_isolated() -> None:
    future_policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 5, 1),
        reason="Future scenario",
    )
    other_org_policy = future_policy.model_copy(
        update={
            "organization_id": "1C_ORG_2",
            "valid_from": date(2026, 3, 1),
        }
    )

    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        amount_field="СебестоимостьБезНДС",
        input_vat_policies=[future_policy, other_org_policy],
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert costs[0].input_vat_value is None
    assert costs[0].input_vat_source == ""

    closing_day_policy = future_policy.model_copy(
        update={"valid_from": date(2026, 4, 12)}
    )
    closing_week_costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        amount_field="СебестоимостьБезНДС",
        input_vat_policies=[closing_day_policy],
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    assert closing_week_costs[0].input_vat_value == Decimal("10")


def test_purchase_book_confirmation_overrides_management_scenario() -> None:
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )

    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        amount_field="СебестоимостьБезНДС",
        input_vat_policies=[policy],
        confirmed_input_vat_org_ids={"1C_ORG_1"},
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert costs[0].input_vat_value == Decimal("10")
    assert costs[0].input_vat_source == (
        "onec_purchase_book_confirmed_cost_difference"
    )


def test_invalid_or_incomplete_cost_difference_is_not_silently_used() -> None:
    policy = InputVatPolicy(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        mode="management_assumption",
        valid_from=date(2026, 3, 1),
        reason="Unit economics scenario",
    )
    negative_rows = sales_rows()
    for row in negative_rows[0]["RecordSet"]:
        if Decimal(str(row["СебестоимостьБезНДС"])) > 0:
            row["Себестоимость"] = "1"
    incomplete_rows = sales_rows()
    incomplete_rows[0]["RecordSet"][2].pop("СебестоимостьБезНДС")

    negative = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=negative_rows,
        amount_field="СебестоимостьБезНДС",
        input_vat_policies=[policy],
    )
    incomplete = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=incomplete_rows,
        amount_field="СебестоимостьБезНДС",
        input_vat_policies=[policy],
    )

    assert negative[0].input_vat_value is None
    assert incomplete[0].input_vat_value is None


def test_sales_register_cost_excludes_non_marketplace_sales_documents() -> None:
    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=[
            {
                "Recorder": "DOC-RWB-REPORT",
                "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-RWB-REPORT",
                        "Документ_Type": (
                            "StandardODATA.Document_ОтчетКомиссионера"
                        ),
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "2",
                        "Себестоимость": "200",
                    }
                ],
            },
            {
                "Recorder": "DOC-USUAL-SALE",
                "Recorder_Type": "StandardODATA.Document_РеализацияТоваровУслуг",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-USUAL-SALE",
                        "Документ_Type": (
                            "StandardODATA.Document_РеализацияТоваровУслуг"
                        ),
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "1",
                        "Себестоимость": "900",
                    }
                ],
            },
        ],
        marketplace_counterparties_only=True,
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(costs) == 1
    assert costs[0].cost_value == Decimal("100")
    assert costs[0].raw_payload_hash != ""


def test_sales_register_cost_keeps_commissioner_and_buyout_layers_separate() -> None:
    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=[
            {
                "Recorder": "DOC-COMMISSIONER",
                "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-COMMISSIONER",
                        "Документ_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "2",
                        "Себестоимость": "200",
                    }
                ],
            },
            {
                "Recorder": "DOC-BUYOUT",
                "Recorder_Type": "StandardODATA.Document_РасходнаяНакладная",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-BUYOUT",
                        "Документ_Type": "StandardODATA.Document_РасходнаяНакладная",
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "1",
                        "Себестоимость": "80",
                    }
                ],
            },
        ],
        marketplace_counterparties_only=True,
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    by_kind = {item.source_document_kind: item for item in costs}
    assert set(by_kind) == {"commissioner_report", "buyout_notice"}
    assert by_kind["commissioner_report"].cost_value == Decimal("100")
    assert by_kind["buyout_notice"].cost_value == Decimal("80")

    mapping = SkuMapping(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        organization_id="1C_ORG_1",
        nm_id=101,
        vendor_code="A-1",
        barcode="",
        onec_item_id="ITEM-1",
        onec_article="ITEM-1",
        match_method="fixture",
        confidence="1",
        status=MappingStatus.MATCHED,
        updated_by="fixture",
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    commissioner = wb_snapshots()[0].model_copy(
        update={"report_type": 1, "quantity": Decimal("2")}
    )
    buyout = wb_snapshots()[0].model_copy(
        update={
            "wb_document_id": "buyout-row",
            "wb_report_id": "buyout-report",
            "report_type": 2,
            "quantity": Decimal("1"),
            "raw_payload_hash": "buyout-row-hash",
        }
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[commissioner, buyout],
        cost_snapshots=costs,
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    rows = {row.document_report.split(" · ", maxsplit=1)[0]: row for row in report.rows}
    assert rows["Отчет комиссионера"].cogs_from_1c_with_extra_costs == Decimal(
        "200.00"
    )
    assert rows["Уведомление о выкупе"].cogs_from_1c_with_extra_costs == Decimal(
        "80.00"
    )


def test_sales_register_cost_does_not_mix_amount_only_other_documents() -> None:
    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=[
            {
                "Recorder": "CLOSING-ROWSET",
                "Recorder_Type": "StandardODATA.Document_ЗакрытиеМесяца",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-05T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-RWB-REPORT-37",
                        "Документ_Type": (
                            "StandardODATA.Document_ОтчетКомиссионера"
                        ),
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "1",
                        "Себестоимость": "0",
                    },
                    {
                        "Active": True,
                        "Period": "2026-04-05T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-RWB-REPORT-37",
                        "Документ_Type": (
                            "StandardODATA.Document_ОтчетКомиссионера"
                        ),
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "0",
                        "Себестоимость": "890",
                    },
                    {
                        "Active": True,
                        "Period": "2026-04-05T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-RWB-REPORT-OTHER",
                        "Документ_Type": (
                            "StandardODATA.Document_ОтчетКомиссионера"
                        ),
                        "Номенклатура_Key": "ITEM-1",
                        "Количество": "0",
                        "Себестоимость": "47505.85",
                    },
                ],
            }
        ],
        marketplace_counterparties_only=True,
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(costs) == 1
    assert costs[0].cost_value == Decimal("890")


def test_marketplace_settlement_totals_attach_to_document_rows() -> None:
    gross_rows = extract_gross_profit_document_rows(
        client_id=CLIENT_ID,
        sales_rows=[
            {
                "Recorder": "DOC-REPORT-1",
                "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-REPORT-1",
                        "Документ_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "Количество": "2",
                        "Сумма": "1000",
                        "СуммаНДС": "47.62",
                        "Себестоимость": "430",
                    }
                ],
            }
        ],
    )
    settlement_totals = extract_marketplace_settlement_totals(
        [
            {
                "Recorder": "DOC-REPORT-1",
                "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "RecordType": "Receipt",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-REPORT-1",
                        "Документ_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "Сумма": "850",
                    },
                    {
                        "Active": True,
                        "Period": "2026-04-15T00:00:00",
                        "RecordType": "Expense",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-REPORT-1",
                        "Документ_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "Сумма": "850",
                    }
                ],
            }
        ]
    )

    attached = attach_settlement_totals_to_documents(gross_rows, settlement_totals)

    assert attached[0].settlement_total == Decimal("850")


def test_gross_profit_document_rows_split_sales_returns_and_net_quantity() -> None:
    rows = extract_gross_profit_document_rows(
        client_id=CLIENT_ID,
        sales_rows=[
            {
                "Recorder": "DOC-REPORT-1",
                "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-REPORT-1",
                        "Документ_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "Количество": "10",
                        "Сумма": "1000",
                        "СуммаНДС": "47.62",
                        "Себестоимость": "430",
                    },
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-REPORT-1",
                        "Документ_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "Количество": "-3",
                        "Сумма": "-300",
                        "СуммаНДС": "-14.29",
                        "Себестоимость": "-129",
                    },
                ],
            }
        ],
    )

    assert len(rows) == 1
    assert rows[0].sales_quantity == Decimal("10")
    assert rows[0].return_quantity == Decimal("3")
    assert rows[0].quantity == Decimal("7")


def test_marketplace_document_metadata_attaches_external_report_ids() -> None:
    gross_rows = extract_gross_profit_document_rows(
        client_id=CLIENT_ID,
        sales_rows=[
            {
                "Recorder": "DOC-COMMISSIONER-1",
                "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-12T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-COMMISSIONER-1",
                        "Документ_Type": (
                            "StandardODATA.Document_ОтчетКомиссионера"
                        ),
                        "Количество": "2",
                        "Сумма": "1000",
                        "СуммаНДС": "47.62",
                        "Себестоимость": "430",
                    }
                ],
            },
            {
                "Recorder": "DOC-BUYOUT-1",
                "Recorder_Type": "StandardODATA.Document_РасходнаяНакладная",
                "RecordSet": [
                    {
                        "Active": True,
                        "Period": "2026-04-13T00:00:00",
                        "Организация_Key": "1C_ORG_1",
                        "Контрагент_Key": "RWB",
                        "Документ": "DOC-BUYOUT-1",
                        "Документ_Type": (
                            "StandardODATA.Document_РасходнаяНакладная"
                        ),
                        "Количество": "1",
                        "Сумма": "200",
                        "СуммаНДС": "9.52",
                        "Себестоимость": "80",
                    }
                ],
            },
        ],
    )
    metadata = extract_marketplace_document_metadata(
        [
            (
                "ОтчетКомиссионера",
                {
                    "Ref_Key": "DOC-COMMISSIONER-1",
                    "Number": "ОК-000001",
                    "НомерВходящегоДокумента": "686 063 420",
                    "СуммаДокумента": "1000",
                },
            ),
            (
                "РасходнаяНакладная",
                {
                    "Ref_Key": "DOC-BUYOUT-1",
                    "Number": "РН-000002",
                    "Комментарий": "УВЕДОМЛЕНИЕ О ВЫКУПЕ №686 063 423",
                    "СуммаДокумента": "200",
                },
            ),
        ]
    )

    attached = attach_document_metadata_to_documents(gross_rows, metadata)

    by_document_id = {row.document_id: row for row in attached}
    assert by_document_id["DOC-COMMISSIONER-1"].external_report_id == "686063420"
    assert by_document_id["DOC-COMMISSIONER-1"].document_number == "ОК-000001"
    assert by_document_id["DOC-COMMISSIONER-1"].input_number == "686 063 420"
    assert by_document_id["DOC-COMMISSIONER-1"].settlement_total is None
    assert by_document_id["DOC-BUYOUT-1"].external_report_id == "686063423"
    assert by_document_id["DOC-BUYOUT-1"].document_number == "РН-000002"
    assert by_document_id["DOC-BUYOUT-1"].settlement_total is None


def test_sales_register_cost_marks_complete_report_row_reliable() -> None:
    mapping = SkuMapping(
        client_id=CLIENT_ID,
        seller_account_id="WB_ACCOUNT_1",
        organization_id="1C_ORG_1",
        nm_id=101,
        vendor_code="A-1",
        barcode="",
        onec_item_id="ITEM-1",
        onec_article="A-1",
        onec_characteristic="",
        match_method="article",
        confidence="1",
        status=MappingStatus.MATCHED,
        updated_by="fixture",
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    costs = extract_sales_register_cost_snapshots(
        client_id=CLIENT_ID,
        sales_rows=sales_rows(),
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=costs,
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert report.rows[0].data_quality_status is DataQualityStatus.RELIABLE
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("244.00")
    assert report.rows[0].gross_profit == Decimal("556.00")


def test_provisional_cost_marks_report_row_needs_review() -> None:
    mapping = SkuMapping(
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
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    cost = OnecUnfCostSnapshot(
        client_id=CLIENT_ID,
        organization_id="1C_ORG_1",
        loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
        onec_item_id="ONEC-1",
        article="A-1",
        barcode="111",
        name="Product",
        cost_value="100",
        cost_method=PROVISIONAL_COST_METHOD,
        effective_from=date(2026, 1, 1),
        source_document="fixture",
        raw_payload_hash="cost-hash",
    )
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=[cost],
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert report.rows[0].data_quality_status is DataQualityStatus.NEEDS_REVIEW
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("200.00")


def test_ambiguous_characteristic_cost_is_not_used() -> None:
    mapping = SkuMapping(
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
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )
    costs = [
        OnecUnfCostSnapshot(
            client_id=CLIENT_ID,
            organization_id="1C_ORG_1",
            loaded_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
            onec_item_id="ONEC-1",
            article="A-1",
            barcode="111",
            name="Product",
            characteristic=characteristic,
            cost_value="100",
            cost_method="with_extra_costs",
            effective_from=date(2026, 1, 1),
            source_document="fixture",
            raw_payload_hash=f"cost-hash-{characteristic}",
        )
        for characteristic in ("CHAR-1", "CHAR-2")
    ]
    report = build_unit_economics_report(
        client_id=CLIENT_ID,
        wb_snapshots=[wb_snapshots()[0]],
        cost_snapshots=costs,
        sku_mappings=[mapping],
        account_org_mapping=account_org_mapping(),
        generated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert report.rows[0].data_quality_status is DataQualityStatus.MISSING_COST
    assert report.rows[0].cogs_from_1c_with_extra_costs == Decimal("0.00")
