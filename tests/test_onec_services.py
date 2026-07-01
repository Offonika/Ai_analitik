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

    rows = load_onec_marketplace_service_rows(
        service_dir,
        client_id=CLIENT_ID,
        reference_dir=reference_dir,
    )

    assert len(rows) == 1
    assert rows[0].service_name == "Услуга доставки"
    assert rows[0].service_category == "Логистика"
    assert rows[0].total == Decimal("125.50")
