from __future__ import annotations

import json
from decimal import Decimal

from wb_unit_economics.onec_services import load_onec_marketplace_service_rows

CLIENT_ID = "shumeyko-partners"


def test_marketplace_services_use_nomenclature_names_for_classification(tmp_path):
    service_dir = tmp_path / "services"
    reference_dir = tmp_path / "refs"
    service_dir.mkdir()
    reference_dir.mkdir()
    (service_dir / "supplier_receipts.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "RECEIPT-1",
                        "Posted": True,
                        "DeletionMark": False,
                        "Date": "2026-04-14T00:00:00",
                        "Организация_Key": "ORG-1",
                        "Контрагент_Key": "RWB",
                        "Number": "1",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (service_dir / "supplier_receipt_expenses.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "RECEIPT-1",
                        "LineNumber": 1,
                        "Номенклатура_Key": "SERVICE-DELIVERY",
                        "Сумма": "125.50",
                        "СуммаНДС": "0",
                        "Всего": "125.50",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (reference_dir / "nomenclature.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "SERVICE-DELIVERY",
                        "Description": "Услуга доставки",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (service_dir / "incoming_invoices.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "FALLBACK-MUST-NOT-BE-ADDED",
                        "Posted": True,
                        "Date": "2026-04-14T00:00:00",
                        "Организация_Key": "ORG-1",
                        "Контрагент_Key": "RWB",
                        "Расходы": [
                            {
                                "Содержание": "Услуга доставки",
                                "Сумма": "999",
                                "Всего": "999",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = load_onec_marketplace_service_rows(
        service_dir,
        client_id=CLIENT_ID,
        reference_dir=reference_dir,
    )

    assert len(rows) == 1
    assert rows[0].service_name == "Услуга доставки"
    assert rows[0].service_category == "Логистика"
    assert rows[0].total == Decimal("125.50")
    assert rows[0].source_kind == "supplier_receipt_expenses"


def test_marketplace_services_fall_back_to_incoming_invoice_expenses(tmp_path):
    service_dir = tmp_path / "services"
    sales_dir = tmp_path / "sales"
    service_dir.mkdir()
    sales_dir.mkdir()
    (service_dir / "incoming_invoices.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Ref_Key": "IN-1",
                        "Posted": True,
                        "DeletionMark": False,
                        "Date": "2026-04-13T00:00:00",
                        "Организация_Key": "ORG-1",
                        "Контрагент_Key": "WB",
                        "Number": "15",
                        "Расходы": [
                            {
                                "LineNumber": 1,
                                "Содержание": "Услуга доставки",
                                "Сумма": "100.00",
                                "СуммаНДС": "22.00",
                                "Всего": "122.00",
                            },
                            {
                                "LineNumber": 2,
                                "Содержание": "Комиссия WB",
                                "Сумма": "50.00",
                                "СуммаНДС": "10.00",
                                "Всего": "50.00",
                            }
                        ],
                    },
                    {
                        "Ref_Key": "IN-OTHER",
                        "Posted": True,
                        "DeletionMark": False,
                        "Date": "2026-04-13T00:00:00",
                        "Организация_Key": "ORG-1",
                        "Контрагент_Key": "SUPPLIER",
                        "Расходы": [
                            {
                                "LineNumber": 1,
                                "Содержание": "Обычная доставка",
                                "Сумма": "999.00",
                                "СуммаНДС": "0",
                                "Всего": "999.00",
                            }
                        ],
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (sales_dir / "sales_register.raw.json").write_text(
        json.dumps(
            {
                "value": [
                    {
                        "Recorder_Type": "StandardODATA.Document_ОтчетКомиссионера",
                        "RecordSet": [
                            {
                                "Организация_Key": "ORG-1",
                                "Покупатель_Key": "WB",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    rows = load_onec_marketplace_service_rows(
        service_dir,
        client_id=CLIENT_ID,
        sales_register_dir=sales_dir,
    )

    assert len(rows) == 2
    delivery = next(row for row in rows if row.service_category == "Логистика")
    commission = next(row for row in rows if row.service_category == "Комиссия WB")
    assert delivery.document_id == "IN-1"
    assert delivery.amount == Decimal("100.00")
    assert delivery.vat == Decimal("22.00")
    assert delivery.total == Decimal("122.00")
    assert delivery.source_kind == "incoming_invoice_expenses"
    assert commission.amount == Decimal("40.00")
    assert commission.vat == Decimal("10.00")
    assert commission.total == Decimal("50.00")
    assert commission.amount_includes_vat is True
