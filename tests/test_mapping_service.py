from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from wb_unit_economics.web import mapping_service, repository, security
from wb_unit_economics.web.app import create_app
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    Marketplace1cCurrentMapping,
    Marketplace1cMappingDecision,
    MarketplaceMappingItem,
    OnecMappingItem,
    ReportRun,
    ReportUnitRow,
    SourceLoad,
    SourceRefreshCollection,
    SourceRefreshRun,
    SourceSnapshotRow,
)
from wb_unit_economics.web.settings import WebSettings


def test_mapping_service_builds_candidates_accepts_and_exports(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        stale_item = MarketplaceMappingItem(
            id="mp-stale",
            tenant_id="shumeyko",
            client_id="shumeyko",
            marketplace="ozon",
            source_item_key="ozon:old-empty-key",
            title="",
            status="ambiguous",
            created_at=security.utcnow(),
            updated_at=security.utcnow(),
        )
        db.add(stale_item)
        result = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        db.commit()

        assert result["items"] == 2
        assert result["onecItems"] >= 2
        assert result["candidates"] >= 2
        assert result["archivedItems"] == 1
        assert result["autoAccepted"] == 1
        assert result["remainingReview"] == 1
        assert result["currentMappingConflictCount"] == 0
        assert db.get(MarketplaceMappingItem, "mp-stale").status == "archived"

        items = mapping_service.list_mapping_items(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
        )["items"]
        ozon_item = next(item for item in items if item["marketplace"] == "ozon")
        assert all(item["id"] != "mp-stale" for item in items)
        assert ozon_item["status"] == "needs_review"
        assert ozon_item["candidateCount"] == 1
        ozon_candidates = mapping_service.mapping_candidates_payload(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=ozon_item["id"],
        )["candidates"]
        assert len(ozon_candidates) == 1
        assert ozon_candidates[0]["onecItem"]["onecItemId"] == "ONEC-1"

        wb_item = next(item for item in items if item["marketplace"] == "wb")
        assert wb_item["status"] == "matched"
        assert wb_item["currentMapping"]["matchMethod"] == (
            "mapping_service_auto_barcode"
        )
        candidates = mapping_service.mapping_candidates_payload(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
        )["candidates"]
        barcode_candidate = next(
            item for item in candidates if item["method"] == "barcode"
        )

        history = mapping_service.mapping_history_payload(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
        )
        assert history["items"][0]["action"] == "auto_accept"
        review_items = mapping_service.list_mapping_items(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            status="review",
        )["items"]
        assert [item["id"] for item in review_items] == [ozon_item["id"]]
        assert {item["status"] for item in review_items} <= {
            "needs_review",
            "ambiguous",
            "missing",
        }
        exported = mapping_service.export_sku_mapping(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
        )
        assert exported["summary"]["wbRows"] == 1
        assert exported["skuMappingRows"][0]["status"] == "matched"
        assert exported["skuMappingRows"][0]["onec_item_id"] == "ONEC-1"

        with pytest.raises(mapping_service.MappingConflictError):
            mapping_service.accept_mapping(
                db,
                tenant_id="shumeyko",
                client_id="shumeyko",
                item_id=wb_item["id"],
                user=user,
                candidate_id=barcode_candidate["id"],
            )


def test_mapping_file_import_accepts_current_mapping(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        mapping_file = tmp_path / "ozon_mapping.csv"
        mapping_file.write_text(
            "offer_id\tonec_article\nART-1\tART-1\n",
            encoding="utf-8",
        )

        result = mapping_service.import_mapping_file(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            path=mapping_file,
            user=user,
        )
        db.commit()

        assert result["imported"] == 1
        assert result["accepted"] == 1
        items = mapping_service.list_mapping_items(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
        )["items"]
        ozon_item = next(item for item in items if item["marketplace"] == "ozon")
        assert ozon_item["status"] == "matched"
        assert ozon_item["candidateCount"] == 1
        assert ozon_item["currentMapping"]["matchMethod"] == "imported_mapping_file"
        ozon_candidates = mapping_service.mapping_candidates_payload(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=ozon_item["id"],
        )["candidates"]
        assert len(ozon_candidates) == 1
        assert ozon_candidates[0]["method"] == "imported_mapping_file"
        exported = mapping_service.export_sku_mapping(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
        )
        assert exported["ozonMappingRows"][0]["status"] == "matched"
        assert exported["ozonMappingRows"][0]["onec_item_id"] == "ONEC-1"


def test_exact_barcode_auto_accept_is_idempotent_and_audited(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)

        first = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        second = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        db.commit()

        assert first["autoAccepted"] == 1
        assert second["autoAccepted"] == 0
        assert db.query(Marketplace1cCurrentMapping).count() == 1
        decisions = db.query(Marketplace1cMappingDecision).filter_by(
            action="auto_accept"
        )
        assert decisions.count() == 1
        decision = decisions.one()
        assert decision.user_id is None
        assert decision.payload["refreshRunId"] == "refresh-1"
        assert decision.payload["matchMethod"] == "mapping_service_auto_barcode"


def test_rejected_exact_barcode_is_not_auto_accepted_again(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        wb_item = next(
            item
            for item in mapping_service.list_mapping_items(
                db, tenant_id="shumeyko", client_id="shumeyko"
            )["items"]
            if item["marketplace"] == "wb"
        )
        barcode_candidate = next(
            item
            for item in mapping_service.mapping_candidates_payload(
                db,
                tenant_id="shumeyko",
                client_id="shumeyko",
                item_id=wb_item["id"],
            )["candidates"]
            if item["method"] == "barcode"
        )
        mapping_service.revoke_mapping(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
            user=user,
            reason="test rejection",
        )
        mapping_service.reject_candidate(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
            user=user,
            candidate_id=barcode_candidate["id"],
            reason="wrong barcode in marketplace card",
        )

        rebuilt = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        db.commit()

        assert rebuilt["autoAccepted"] == 0
        assert db.query(Marketplace1cCurrentMapping).filter_by(
            item_id=wb_item["id"]
        ).one_or_none() is None
        candidates = mapping_service.mapping_candidates_payload(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
        )["candidates"]
        assert next(item for item in candidates if item["method"] == "barcode")[
            "status"
        ] == "rejected"


def test_excluded_item_is_not_auto_accepted(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        wb_item = next(
            item
            for item in mapping_service.list_mapping_items(
                db, tenant_id="shumeyko", client_id="shumeyko"
            )["items"]
            if item["marketplace"] == "wb"
        )
        mapping_service.revoke_mapping(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
            user=user,
            reason="exclude fixture",
        )
        mapping_service.exclude_item(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
            user=user,
            reason="not sold",
        )

        rebuilt = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )

        assert rebuilt["autoAccepted"] == 0
        current = db.query(Marketplace1cCurrentMapping).filter_by(
            item_id=wb_item["id"]
        ).one()
        assert current.status == "excluded"
        assert current.match_method == "manual_exclude"


def test_exact_barcode_does_not_replace_existing_mapping_and_reports_conflict(
    tmp_path: Path,
) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        wb_item = next(
            item
            for item in mapping_service.list_mapping_items(
                db, tenant_id="shumeyko", client_id="shumeyko"
            )["items"]
            if item["marketplace"] == "wb"
        )
        mapping_service.revoke_mapping(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
            user=user,
            reason="replace in fixture",
        )
        now = security.utcnow()
        alternative = OnecMappingItem(
            id="onec-alternative",
            tenant_id="shumeyko",
            client_id="shumeyko",
            source_item_key="onec:alternative:",
            onec_item_id="ONEC-ALTERNATIVE",
            onec_article="ALT",
            name="Другой товар 1С",
            barcode="222",
            source_type="onec_barcodes",
            created_at=now,
            updated_at=now,
        )
        db.add(alternative)
        db.flush()
        mapping_service.accept_mapping(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            item_id=wb_item["id"],
            user=user,
            onec_mapping_item_id=alternative.id,
            reason="confirmed earlier",
        )

        rebuilt = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        db.commit()

        assert rebuilt["autoAccepted"] == 0
        assert rebuilt["currentMappingConflictCount"] == 1
        current = db.query(Marketplace1cCurrentMapping).filter_by(
            item_id=wb_item["id"]
        ).one()
        assert current.onec_mapping_item_id == alternative.id
        assert current.match_method == "manual_search"


def test_ambiguous_exact_barcode_stays_in_manual_queue(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        _seed_second_onec_for_barcode(db, barcode="111")

        rebuilt = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        db.commit()

        wb_item = next(
            item
            for item in mapping_service.list_mapping_items(
                db, tenant_id="shumeyko", client_id="shumeyko"
            )["items"]
            if item["marketplace"] == "wb"
        )
        assert rebuilt["autoAccepted"] == 0
        assert wb_item["status"] == "ambiguous"
        assert wb_item["currentMapping"] is None


def test_marketplace_item_without_candidate_stays_missing(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        run = db.get(SourceRefreshRun, "refresh-1")
        collection = next(
            item
            for item in run.collections
            if item.source_type == "wb_product_cards"
        )
        db.add(
            SourceSnapshotRow(
                refresh_run_id=run.id,
                collection_id=collection.id,
                tenant_id="shumeyko",
                client_id="shumeyko",
                source_type="wb_product_cards",
                source_label="wb_product_cards",
                source_row_id="wb-no-candidate",
                row_number=99,
                raw_payload_hash="hash-no-candidate",
                row_payload={
                    "seller_account_id": "WB_ACCOUNT_1",
                    "nm_id": 9999,
                    "vendor_code": "NO-MATCH",
                    "barcode": "777777",
                    "title": "Без кандидата",
                },
                loaded_at=security.utcnow(),
            )
        )
        db.flush()

        rebuilt = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )

        missing_item = next(
            item
            for item in mapping_service.list_mapping_items(
                db, tenant_id="shumeyko", client_id="shumeyko"
            )["items"]
            if item["nmId"] == "9999"
        )
        assert rebuilt["autoAccepted"] == 1
        assert missing_item["status"] == "missing"
        assert missing_item["candidateCount"] == 0


def test_auto_accept_reports_items_affected_in_source_report(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        now = security.utcnow()
        report = ReportRun(
            id="report-mapping-impact",
            tenant_id="shumeyko",
            client_id="shumeyko",
            client_name="Шумейко",
            title="Mapping impact",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 30),
            period_text="01.03.2026 - 30.06.2026",
            period_status="full_months",
            generated_at=now,
            status="ready",
            publication_status="published",
            methodology_version="test",
            source_workbook="",
            created_at=now,
        )
        db.add(report)
        db.add(
            ReportUnitRow(
                report_run_id=report.id,
                row_uid="impact-row",
                nm_id="1001",
                article_wb="ART-1",
                barcode="111",
                status="missing_mapping",
            )
        )
        db.get(SourceRefreshRun, "refresh-1").source_report_run_id = report.id
        db.flush()

        rebuilt = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )

        assert rebuilt["autoAccepted"] == 1
        assert rebuilt["affectedReportItems"] == 1
        assert rebuilt["reportRebuildRequired"] is True


def test_report_mapping_source_load_is_scoped_and_staff_payload_is_filtered(
    tmp_path: Path,
) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        _seed_source_rows(db)
        run = db.get(SourceRefreshRun, "refresh-1")
        mapping_collection = SourceRefreshCollection(
            refresh_run=run,
            tenant_id="shumeyko",
            client_id="shumeyko",
            source_type="sku_mapping",
            source_label="Marketplace mapping",
            required=True,
            status="needs_review",
            row_count=10,
            payload={
                "rebuild": {
                    "autoAccepted": 3,
                    "remainingReview": 2,
                    "currentMappingConflictCount": 1,
                }
            },
            loaded_at=security.utcnow(),
        )
        db.add(mapping_collection)
        now = security.utcnow()
        report = ReportRun(
            id="report-scoped-mapping",
            tenant_id="shumeyko",
            client_id="shumeyko",
            client_name="Шумейко",
            title="Scoped mapping",
            period_start=date(2026, 3, 1),
            period_end=date(2026, 6, 30),
            period_text="01.03.2026 - 30.06.2026",
            period_status="full_months",
            generated_at=now,
            status="ready",
            publication_status="draft",
            methodology_version="test",
            source_workbook="",
            created_at=now,
        )
        db.add(report)
        db.add(
            ReportUnitRow(
                report_run_id=report.id,
                row_uid="scoped-ok",
                nm_id="1001",
                status="ОК",
            )
        )
        db.flush()
        repository.replace_source_loads_from_refresh(db, report, run)

        scoped = repository.reconcile_report_mapping_source_load(db, report)
        mapping_load = db.query(SourceLoad).filter_by(
            report_run_id=report.id,
            source_type="sku_mapping",
        ).one()
        staff_payload = repository.source_refresh_run_payload(
            run, include_sensitive=True
        )
        client_payload = repository.source_refresh_run_payload(
            run, include_sensitive=False
        )

        assert scoped["mappingIssueRows"] == 0
        assert scoped["sourceLoadUpdated"] is True
        assert mapping_load.status == "loaded"
        assert staff_payload["mappingAutoSync"]["autoAccepted"] == 3
        assert client_payload["mappingAutoSync"] is None


def test_empty_ozon_refresh_does_not_archive_valid_existing_items(
    tmp_path: Path,
) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        db.commit()

        ozon_item = (
            db.query(MarketplaceMappingItem)
            .filter_by(client_id="shumeyko", marketplace="ozon")
            .one()
        )
        assert ozon_item.status != "archived"

        _seed_empty_ozon_refresh(db)
        result = mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-empty-ozon",
        )
        db.commit()

        assert result["items"] == 0
        assert result["candidateItems"] == 2
        assert result["archivedItems"] == 0
        restored_item = db.get(MarketplaceMappingItem, ozon_item.id)
        assert restored_item.status == "needs_review"
        assert restored_item.candidate_count == 1


def test_mapping_upload_reader_uses_header_delimiter(tmp_path: Path) -> None:
    mapping_file = tmp_path / "ozon_mapping.txt"
    mapping_file.write_text(
        "Номенклатура Ozon\tНоменклатура\n"
        "Ozon товар, с запятыми, в названии\t1C товар\n",
        encoding="utf-8",
    )

    rows = mapping_service._read_mapping_upload_rows(mapping_file)

    assert rows == [
        {
            "Номенклатура Ozon": "Ozon товар, с запятыми, в названии",
            "Номенклатура": "1C товар",
        }
    ]


def test_mapping_service_requires_reason_for_exclude_and_revoke(tmp_path: Path) -> None:
    session_factory = _mapping_session_factory(tmp_path)
    with session_factory() as db:
        user = db.query(repository.User).filter_by(email="admin@example.com").one()
        _seed_source_rows(db)
        mapping_service.rebuild_candidates(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
            user=user,
            refresh_run_id="refresh-1",
        )
        item = mapping_service.list_mapping_items(
            db,
            tenant_id="shumeyko",
            client_id="shumeyko",
        )["items"][0]

        with pytest.raises(mapping_service.MappingValidationError):
            mapping_service.exclude_item(
                db,
                tenant_id="shumeyko",
                client_id="shumeyko",
                item_id=item["id"],
                user=user,
                reason="",
            )


def test_mapping_api_is_staff_only_and_reports_conflict(tmp_path: Path) -> None:
    database_url = f"sqlite:///{tmp_path / 'web.sqlite3'}"
    session_factory = _mapping_session_factory(tmp_path, database_url=database_url)
    with session_factory() as db:
        _seed_source_rows(db)
        repository.upsert_user(
            db,
            email="client@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="client",
        )
        db.commit()
    app = create_app(
        settings=WebSettings(
            database_url=database_url,
            cookie_secure=False,
            openai_api_key="",
        ),
        session_factory=session_factory,
    )
    client = TestClient(app)
    _login(client, "admin@example.com")

    rebuild = client.post(
        "/api/clients/shumeyko/mapping/rebuild-candidates",
        json={"refresh_run_id": "refresh-1"},
    )
    assert rebuild.status_code == 200
    items = client.get("/api/clients/shumeyko/mapping/items").json()["items"]
    item = next(row for row in items if row["marketplace"] == "wb")
    candidates = client.get(
        f"/api/clients/shumeyko/mapping/items/{item['id']}/candidates"
    ).json()["candidates"]

    protected = client.post(
        f"/api/clients/shumeyko/mapping/items/{item['id']}/accept",
        json={"candidate_id": candidates[0]["id"], "reason": "ok"},
    )
    assert protected.status_code == 409
    history = client.get(f"/api/clients/shumeyko/mapping/items/{item['id']}/history")
    assert history.status_code == 200
    assert history.json()["items"][0]["action"] == "auto_accept"

    ozon_item = next(row for row in items if row["marketplace"] == "ozon")
    ozon_candidates = client.get(
        f"/api/clients/shumeyko/mapping/items/{ozon_item['id']}/candidates"
    ).json()["candidates"]
    accept = client.post(
        f"/api/clients/shumeyko/mapping/items/{ozon_item['id']}/accept",
        json={"candidate_id": ozon_candidates[0]["id"], "reason": "checked"},
    )
    assert accept.status_code == 200
    accept_history = client.get(
        f"/api/clients/shumeyko/mapping/items/{ozon_item['id']}/history"
    )
    assert accept_history.status_code == 200
    assert accept_history.json()["items"][0]["action"] == "accept"

    client.post("/api/auth/logout")
    _login(client, "client@example.com")
    forbidden = client.get("/api/clients/shumeyko/mapping/items")
    assert forbidden.status_code == 403


def test_mapping_ui_static_assets_expose_staff_workflow() -> None:
    html = Path("src/wb_unit_economics/web/static/index.html").read_text()
    app_js = Path("src/wb_unit_economics/web/static/app.js").read_text()
    css = Path("src/wb_unit_economics/web/static/styles.css").read_text()

    assert 'id="mapping-service-panel"' in html
    assert 'id="mapping-marketplace-filter"' in html
    assert 'id="mapping-status-filter"' in html
    assert 'id="mapping-search"' in html

    assert "loadMappingItems" in app_js
    assert "selectMappingItem" in app_js
    assert "handleMappingCandidateAction" in app_js
    assert 'mappingActionButton("accept"' in app_js
    assert 'mappingActionButton("reject"' in app_js
    assert 'mappingActionButton("revoke"' in app_js
    assert 'mappingActionButton("exclude"' in app_js
    assert "postMappingAction" in app_js
    assert "/mapping/onec-search" in app_js
    assert "/mapping/export/sku-mapping" in app_js
    assert "Автоматически сопоставлено по штрихкоду 1С" in app_js
    assert "Конфликт с ранее принятой связью" in app_js
    assert "mapping_service_auto_barcode" in app_js

    assert ".mapping-service-panel" in css
    assert ".mapping-candidate" in css


def _mapping_session_factory(tmp_path: Path, *, database_url: str | None = None):
    database_url = database_url or f"sqlite:///{tmp_path / 'web.sqlite3'}"
    engine = make_engine(database_url)
    init_db(engine)
    session_factory = make_session_factory(engine)
    with session_factory() as db:
        repository.ensure_tenant(db, "shumeyko", "Шумейко и Партнеры")
        repository.upsert_user(
            db,
            email="admin@example.com",
            password="secret",
            tenant_id="shumeyko",
            role="admin",
        )
        db.commit()
    return session_factory


def _login(client: TestClient, email: str) -> None:
    response = client.post(
        "/api/auth/login",
        json={"email": email, "password": "secret"},
    )
    assert response.status_code == 200


def _seed_source_rows(db) -> None:
    now = security.utcnow()
    run = SourceRefreshRun(
        id="refresh-1",
        tenant_id="shumeyko",
        client_id="shumeyko",
        requested_by_user_id=None,
        source_report_run_id=None,
        new_report_run_id=None,
        mode="full",
        credential_source="tenant",
        dry_run=False,
        status="source_loaded",
        reason="fixture",
        snapshot_set_id="fixture",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 6, 30),
        root_dir="",
        workbook_path="",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    collections = {
        source_type: SourceRefreshCollection(
            refresh_run=run,
            tenant_id="shumeyko",
            client_id="shumeyko",
            source_type=source_type,
            source_label=source_type,
            required=True,
            status="loaded",
            row_count=1,
            loaded_at=now,
        )
        for source_type in (
            "wb_product_cards",
            "ozon_products_report",
            "onec_nomenclature",
            "onec_barcodes",
        )
    }
    db.add_all(collections.values())
    db.flush()
    rows = [
        (
            "onec_nomenclature",
            "onec-1",
            {
                "Ref_Key": "ONEC-1",
                "Description": "Товар WB",
                "Артикул": "ART-1",
            },
        ),
        (
            "onec_barcodes",
            "barcode-1",
            {"Номенклатура_Key": "ONEC-1", "Штрихкод": "111"},
        ),
        (
            "wb_product_cards",
            "wb-1",
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "nm_id": 1001,
                "vendor_code": "ART-1",
                "barcode": "111",
                "title": "Товар WB",
            },
        ),
        (
            "ozon_products_report",
            "ozon-1",
            {
                "seller_account_id": "OZON_ACCOUNT_1",
                "product_id": "5001",
                "offer_id": "ART-1",
                "sku": "OZON-SKU-1",
                "barcode": "999",
                "name": "Товар Ozon",
            },
        ),
    ]
    for index, (source_type, row_id, payload) in enumerate(rows, 1):
        db.add(
            SourceSnapshotRow(
                refresh_run_id=run.id,
                collection_id=collections[source_type].id,
                tenant_id="shumeyko",
                client_id="shumeyko",
                source_type=source_type,
                source_label=source_type,
                source_row_id=row_id,
                row_number=index,
                raw_payload_hash=f"hash-{index}",
                row_payload=payload,
                loaded_at=now,
            )
        )
    db.flush()


def _seed_empty_ozon_refresh(db) -> None:
    now = security.utcnow()
    run = SourceRefreshRun(
        id="refresh-empty-ozon",
        tenant_id="shumeyko",
        client_id="shumeyko",
        requested_by_user_id=None,
        source_report_run_id=None,
        new_report_run_id=None,
        mode="ozon-only",
        credential_source="tenant",
        dry_run=False,
        status="source_loaded",
        reason="fixture",
        snapshot_set_id="fixture-empty",
        period_start=date(2026, 3, 1),
        period_end=date(2026, 6, 30),
        root_dir="",
        workbook_path="",
        error_message="",
        created_at=now,
        updated_at=now,
    )
    db.add(run)
    collections = {
        source_type: SourceRefreshCollection(
            refresh_run=run,
            tenant_id="shumeyko",
            client_id="shumeyko",
            source_type=source_type,
            source_label=source_type,
            required=True,
            status="loaded",
            row_count=0,
            loaded_at=now,
        )
        for source_type in (
            "ozon_products_report",
            "onec_nomenclature",
            "onec_barcodes",
        )
    }
    db.add_all(collections.values())
    db.flush()
    rows = [
        (
            "ozon_products_report",
            "ozon-empty-control",
            {
                "marketplace": "ozon",
                "seller_account_id": "OZON_ACCOUNT_1",
                "source_endpoint": "/v1/report/info",
            },
        ),
        (
            "onec_nomenclature",
            "onec-1-empty",
            {
                "Ref_Key": "ONEC-1",
                "Description": "Товар WB",
                "Артикул": "ART-1",
            },
        ),
        (
            "onec_barcodes",
            "barcode-1-empty",
            {"Номенклатура_Key": "ONEC-1", "Штрихкод": "111"},
        ),
    ]
    for index, (source_type, row_id, payload) in enumerate(rows, 1):
        db.add(
            SourceSnapshotRow(
                refresh_run_id=run.id,
                collection_id=collections[source_type].id,
                tenant_id="shumeyko",
                client_id="shumeyko",
                source_type=source_type,
                source_label=source_type,
                source_row_id=row_id,
                row_number=index,
                raw_payload_hash=f"empty-hash-{index}",
                row_payload=payload,
                loaded_at=now,
            )
        )
    db.flush()


def _seed_second_onec_for_barcode(db, *, barcode: str) -> None:
    run = db.get(SourceRefreshRun, "refresh-1")
    collections = {
        item.source_type: item
        for item in run.collections
        if item.source_type in {"onec_nomenclature", "onec_barcodes"}
    }
    now = security.utcnow()
    rows = [
        (
            "onec_nomenclature",
            "onec-2",
            {
                "Ref_Key": "ONEC-2",
                "Description": "Другой товар",
                "Артикул": "ART-2",
            },
        ),
        (
            "onec_barcodes",
            "barcode-2",
            {"Номенклатура_Key": "ONEC-2", "Штрихкод": barcode},
        ),
    ]
    for index, (source_type, row_id, payload) in enumerate(rows, 100):
        db.add(
            SourceSnapshotRow(
                refresh_run_id=run.id,
                collection_id=collections[source_type].id,
                tenant_id="shumeyko",
                client_id="shumeyko",
                source_type=source_type,
                source_label=source_type,
                source_row_id=row_id,
                row_number=index,
                raw_payload_hash=f"second-hash-{index}",
                row_payload=payload,
                loaded_at=now,
            )
        )
    db.flush()
