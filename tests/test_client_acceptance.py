from __future__ import annotations

import json
from pathlib import Path

import pytest

from wb_unit_economics.client_acceptance import (
    AcceptancePackageError,
    build_client_acceptance_package,
)
from wb_unit_economics.report_exports import file_sha256
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory


def _payload() -> dict:
    return {
        "meta": {
            "title": "Кабинет юнит-экономики WB",
            "client": "Шумейко и Партнеры",
            "period": "01.07.2026 - 09.07.2026",
            "reportPeriod": "01.07.2026 - 09.07.2026",
            "periodText": "июль 2026",
            "periodStatus": "",
            "sourceCoverage": "01.07.2026 - 09.07.2026",
            "sourceCoverageStart": "2026-07-01",
            "sourceCoverageEnd": "2026-07-09",
            "methodologyVersion": "test-profiled-taxes",
            "generatedAt": "10.07.2026 12:00",
            "sourceWorkbook": "",
            "returnReasonLimitation": "",
        },
        "readiness": {},
        "options": {},
        "monthly": [],
        "expenses": [],
        "unitRows": [
            {
                "id": "unit-1",
                "week": "2026-07-06",
                "month": "Июль 2026",
                "organization": "Организация A",
                "cabinet": "Кабинет A",
                "product": "Товар",
                "sales": 1,
                "returns": 0,
                "netQty": 1,
                "revenue": 100,
                "cost": 40,
                "profitBeforeTax": 60,
                "profit": 60,
                "status": "ОК",
            }
        ],
        "returns": [],
        "lostSales": [],
        "reconciliation": [],
        "reconciliationMonthly": [],
        "documentReconciliation": [],
    }


def _ready_summary() -> dict:
    return {
        "meta": {
            "reportPeriod": "01.07.2026 - 09.07.2026",
            "sourceCoverage": "01.07.2026 - 09.07.2026",
            "sourceCoverageStart": "2026-07-01",
            "sourceCoverageEnd": "2026-07-09",
            "generatedAtIso": "2026-07-10T12:00:00+03:00",
        },
        "readiness": {
            "status": "ready",
            "label": "Готов",
            "score": 100,
            "blockingReasons": [],
            "reviewReasons": [],
        },
    }


def test_build_client_acceptance_package_is_safe_and_report_specific(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = repository.save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-ready",
        )
        artifact = tmp_path / "secret-client-path" / "report.xlsx"
        artifact.parent.mkdir()
        artifact.write_bytes(b"safe aggregate artifact")
        repository.record_report_artifact(
            db,
            report,
            artifact_type="excel",
            path=artifact,
            sha256=file_sha256(artifact),
            byte_size=artifact.stat().st_size,
        )
        db.commit()
        monkeypatch.setattr(
            "wb_unit_economics.client_acceptance.repository.report_summary_payload",
            lambda *_args, **_kwargs: _ready_summary(),
        )

        result = build_client_acceptance_package(
            db,
            report,
            output_dir=tmp_path / "client-package",
        )

    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)
    markdown = result.markdown_path.read_text(encoding="utf-8")
    assert result.docx_path.exists()
    assert manifest["report"]["id"] == "report-ready"
    assert manifest["report"]["methodologyVersion"] == "test-profiled-taxes"
    assert manifest["readiness"]["status"] == "ready"
    assert manifest["counts"]["unitRows"] == 1
    assert manifest["artifacts"][0]["sha256"] == file_sha256(artifact)
    assert {item["name"] for item in manifest["packageFiles"]} == {
        "acceptance-package.md",
        "acceptance-package.docx",
    }
    forbidden = (
        "secret-client-path",
        "source_workbook",
        "password",
        "api_key",
        "connection",
        "unit-1",
    )
    assert not any(value in manifest_text.casefold() for value in forbidden)
    assert "исходных строк" in markdown


def test_client_acceptance_rejects_unpublished_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = repository.save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-draft",
        )
        report.publication_status = "draft"
        db.commit()
        monkeypatch.setattr(
            "wb_unit_economics.client_acceptance.repository.report_summary_payload",
            lambda *_args, **_kwargs: _ready_summary(),
        )

        with pytest.raises(AcceptancePackageError, match="not published"):
            build_client_acceptance_package(
                db,
                report,
                output_dir=tmp_path / "client-package",
            )


def test_client_acceptance_rejects_report_without_ready_status(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = make_engine(f"sqlite:///{tmp_path / 'web.sqlite3'}")
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        report = repository.save_report_marts(
            db,
            _payload(),
            tenant_id="shumeyko",
            tenant_name="Шумейко и Партнеры",
            report_id="report-needs-review",
        )
        summary = _ready_summary()
        summary["readiness"]["status"] = "needs_review"
        monkeypatch.setattr(
            "wb_unit_economics.client_acceptance.repository.report_summary_payload",
            lambda *_args, **_kwargs: summary,
        )

        with pytest.raises(AcceptancePackageError, match="not ready"):
            build_client_acceptance_package(
                db,
                report,
                output_dir=tmp_path / "client-package",
            )
