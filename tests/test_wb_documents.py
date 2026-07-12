from __future__ import annotations

import base64
import json
from datetime import date
from io import BytesIO
from zipfile import ZipFile

import httpx
from openpyxl import Workbook

from wb_unit_economics.wb_documents import (
    export_wb_documents,
    load_wb_document_export_results,
)
from wb_unit_economics.wb_finance import WbFinanceSellerAccount, WbFinanceSettings


def test_wb_documents_export_writes_manifest_without_raw_document(tmp_path) -> None:
    document_bytes = _redeem_notification_zip()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/documents/list"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "documents": [
                            {
                                "serviceName": "redeem-notification-44841941",
                                "name": "redeem-notification",
                                "category": "Уведомление о выкупе",
                                "extensions": ["zip"],
                                "creationTime": "2026-06-17T00:00:00Z",
                                "viewed": False,
                            }
                        ]
                    }
                },
            )
        if request.url.path.endswith("/documents/download"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "fileName": "notice.zip",
                        "extension": "zip",
                        "document": base64.b64encode(document_bytes).decode(),
                    }
                },
            )
        return httpx.Response(404)

    output_dir = tmp_path / "data" / "wb_documents" / "run"
    results = export_wb_documents(
        settings=_settings(),
        output_dir=output_dir,
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 7),
        download=True,
        transport=httpx.MockTransport(handler),
    )

    assert results[0].ok is True
    assert results[0].row_count == 1
    assert results[0].downloaded_count == 1
    manifest = json.loads(
        (output_dir / "WB_ACCOUNT_1" / "documents_manifest.json").read_text(
            encoding="utf-8"
        )
    )
    assert manifest[0]["category"] == "Уведомление о выкупе"
    assert manifest[0]["download"]["sha256"]
    assert manifest[0]["download"]["size_bytes"] == len(document_bytes)
    assert manifest[0]["download"]["summary"] == {
        "reportId": "44841941",
        "status": "parsed",
        "quantity": "62",
        "purchaseAmount": "51532.81",
        "vatAmount": "9292.80",
        "workbookName": "Уведомление.xlsx",
    }
    assert base64.b64encode(document_bytes).decode() not in json.dumps(
        manifest,
        ensure_ascii=False,
    )
    assert (output_dir / "WB_ACCOUNT_1" / "documents" / "notice.zip").exists()


def test_wb_documents_401_is_not_reported_as_zero_documents(tmp_path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"title": "unauthorized"})

    results = export_wb_documents(
        settings=_settings(),
        output_dir=tmp_path / "data" / "wb_documents" / "run",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 7),
        transport=httpx.MockTransport(handler),
    )

    assert results[0].ok is False
    assert results[0].status == "http_error"
    assert results[0].status_code == 401
    assert results[0].row_count == 0


def test_wb_documents_results_can_be_restored_from_recorded_manifest(
    tmp_path,
) -> None:
    output_dir = tmp_path / "documents"
    output_dir.mkdir()
    (output_dir / "manifest.json").write_text(
        json.dumps(
            {
                "results": [{"sellerAccountId": "integrity-only"}],
                "provider_results": [
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "account_name": "WB test",
                        "ok": True,
                        "status": "ok",
                        "row_count": 4,
                        "downloaded_count": 4,
                        "output_file": "WB_ACCOUNT_1/documents_manifest.json",
                        "status_code": 200,
                        "error": "",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    results = load_wb_document_export_results(output_dir)

    assert len(results) == 1
    assert results[0].seller_account_id == "WB_ACCOUNT_1"
    assert results[0].downloaded_count == 4


def _settings() -> WbFinanceSettings:
    return WbFinanceSettings(
        accounts=(
            WbFinanceSellerAccount(
                seller_account_id="WB_ACCOUNT_1",
                account_name="WB test",
                api_key="token",
            ),
        )
    )


def _redeem_notification_zip() -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(
        [
            "№ п/п",
            "Количество",
            "Сумма выкупа, руб., (вкл. НДС)",
            "Ставка НДС",
            "Сумма НДС",
        ]
    )
    worksheet.append([1, 62, "51 532,81", "–", "9 292,80"])
    worksheet.append(["Итого:", 62, "51 532,81", "–", "9 292,80"])
    workbook_bytes = BytesIO()
    workbook.save(workbook_bytes)
    archive_bytes = BytesIO()
    with ZipFile(archive_bytes, "w") as archive:
        archive.writestr("Уведомление.xlsx", workbook_bytes.getvalue())
    return archive_bytes.getvalue()
