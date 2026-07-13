from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from scripts.rebuild_report_from_sources import _wb_snapshots_from_daily_facts
from wb_unit_economics.contracts import MarketplaceFinanceDailyFact
from wb_unit_economics.web import repository
from wb_unit_economics.web.database import init_db, make_engine, make_session_factory
from wb_unit_economics.web.models import (
    MarketplaceFactStaging,
    MarketplaceOperationFact,
    SourceRefreshCollection,
    SourceRefreshRun,
    Tenant,
)
from wb_unit_economics.web.models import (
    MarketplaceFinanceDailyFact as MarketplaceFinanceDailyFactModel,
)
from wb_unit_economics.web.source_refresh import (
    _full_wb_calculation_parity,
    _persisted_daily_facts_parity,
)


def test_daily_facts_replace_coverage_window_atomically() -> None:
    session_factory, refresh_run = _context()
    first = _daily_fact(net_revenue="100")
    later = _daily_fact(net_revenue="200", fact_date=date(2026, 7, 10))
    replacement = _daily_fact(net_revenue="125")

    with session_factory() as db:
        run = db.get(SourceRefreshRun, refresh_run.id)
        assert run is not None
        assert (
            repository.replace_marketplace_finance_daily_facts(
                db,
                run,
                [first, later],
                marketplace="wb",
                cabinet_ids={"seller": "cabinet"},
            )
            == 2
        )
        db.commit()

        assert (
            repository.replace_marketplace_finance_daily_facts(
                db,
                run,
                [replacement],
                marketplace="wb",
                cabinet_ids={"seller": "cabinet"},
            )
            == 1
        )
        db.commit()

        rows = list(db.scalars(select(MarketplaceFinanceDailyFactModel)))
        parity = _persisted_daily_facts_parity(db, run, [replacement])

    assert len(rows) == 1
    assert rows[0].net_revenue == Decimal("125.00")
    assert all(row.wb_cabinet_id == "cabinet" for row in rows)
    assert all(row.source_snapshot_set_id == "snapshot-1" for row in rows)
    assert parity["status"] == "matched"


def test_daily_fact_staging_cleanup_is_batched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory, refresh_run = _context()
    monkeypatch.setattr(repository, "MARKETPLACE_STAGING_DELETE_BATCH_SIZE", 1)

    with session_factory() as db:
        run = db.get(SourceRefreshRun, refresh_run.id)
        assert run is not None
        repository.replace_marketplace_finance_daily_facts(
            db,
            run,
            [
                _daily_fact(net_revenue="100", fact_date=date(2026, 7, 5)),
                _daily_fact(net_revenue="200", fact_date=date(2026, 7, 6)),
            ],
            marketplace="wb",
        )
        assert db.scalar(select(func.count()).select_from(MarketplaceFactStaging)) == 0


def test_staging_digest_streams_the_existing_canonical_list_format() -> None:
    values = [{"b": 2, "a": "один"}, {"a": "два", "b": 3}]
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    assert (
        repository._staging_digest(iter(values))
        == hashlib.sha256(canonical).hexdigest()
    )


def test_daily_facts_replace_full_window_across_different_runs() -> None:
    session_factory, first_run = _context()
    now = datetime(2026, 7, 11, tzinfo=UTC)
    second_run = SourceRefreshRun(
        id="refresh-2",
        tenant_id=first_run.tenant_id,
        client_id=first_run.client_id,
        mode="daily",
        credential_source="tenant",
        dry_run=False,
        status="source_loaded",
        snapshot_set_id="snapshot-2",
        period_start=first_run.period_start,
        period_end=first_run.period_end,
        created_at=now,
        updated_at=now,
    )
    with session_factory() as db:
        db.add(second_run)
        db.commit()
        first = db.get(SourceRefreshRun, first_run.id)
        second = db.get(SourceRefreshRun, second_run.id)
        assert first is not None and second is not None
        repository.replace_marketplace_finance_daily_facts(
            db,
            first,
            [
                _daily_fact(net_revenue="100", fact_date=date(2026, 7, 5)),
                _daily_fact(net_revenue="200", fact_date=date(2026, 7, 10)),
            ],
            marketplace="wb",
        )
        db.commit()
        repository.replace_marketplace_finance_daily_facts(
            db,
            second,
            [_daily_fact(net_revenue="125", fact_date=date(2026, 7, 5))],
            marketplace="wb",
        )
        db.commit()
        rows = list(db.scalars(select(MarketplaceFinanceDailyFactModel)))

    assert [(row.fact_date, row.source_refresh_run_id) for row in rows] == [
        (date(2026, 7, 5), "refresh-2")
    ]


def test_daily_facts_replace_only_explicit_incremental_window() -> None:
    session_factory, first_run = _context()
    now = datetime(2026, 7, 11, tzinfo=UTC)
    second_run = SourceRefreshRun(
        id="refresh-incremental",
        tenant_id=first_run.tenant_id,
        client_id=first_run.client_id,
        mode="incremental",
        credential_source="tenant",
        dry_run=False,
        status="source_loaded",
        snapshot_set_id="snapshot-incremental",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 14),
        source_window_start=date(2026, 7, 8),
        source_window_end=date(2026, 7, 14),
        created_at=now,
        updated_at=now,
    )
    with session_factory() as db:
        db.add(second_run)
        db.commit()
        first = db.get(SourceRefreshRun, first_run.id)
        second = db.get(SourceRefreshRun, second_run.id)
        assert first is not None and second is not None
        repository.replace_marketplace_finance_daily_facts(
            db,
            first,
            [
                _daily_fact(net_revenue="100", fact_date=date(2026, 7, 5)),
                _daily_fact(net_revenue="200", fact_date=date(2026, 7, 10)),
            ],
            marketplace="wb",
        )
        db.commit()
        repository.replace_marketplace_finance_daily_facts(
            db,
            second,
            [_daily_fact(net_revenue="225", fact_date=date(2026, 7, 10))],
            marketplace="wb",
            coverage_start=second.source_window_start,
            coverage_end=second.source_window_end,
        )
        db.commit()
        rows = list(
            db.scalars(
                select(MarketplaceFinanceDailyFactModel).order_by(
                    MarketplaceFinanceDailyFactModel.fact_date
                )
            )
        )

    assert [
        (row.fact_date, row.source_refresh_run_id, row.net_revenue)
        for row in rows
    ] == [
        (date(2026, 7, 5), "refresh-1", Decimal("100.00")),
        (date(2026, 7, 10), "refresh-incremental", Decimal("225.00")),
    ]


def test_daily_facts_recreate_wb_snapshot_grain_and_source_count() -> None:
    fact = _daily_fact(net_revenue="125")
    fact = fact.model_copy(
        update={
            "source_row_count": 7,
            "storage": Decimal("4.50"),
            "marketplace_promotion": Decimal("3.25"),
        }
    )

    snapshots = _wb_snapshots_from_daily_facts([fact])

    assert len(snapshots) == 1
    assert snapshots[0].period_start == fact.fact_date
    assert snapshots[0].source_row_count == 7
    assert snapshots[0].storage == Decimal("4.50")
    assert snapshots[0].wb_promotion == Decimal("3.25")
    assert snapshots[0].raw_payload_hash == fact.source_hash_digest


def test_operation_facts_replace_source_snapshot_without_duplicates() -> None:
    session_factory, refresh_run = _context()
    with session_factory() as db:
        run = db.get(SourceRefreshRun, refresh_run.id)
        assert run is not None
        collection = SourceRefreshCollection(
            refresh_run_id=run.id,
            tenant_id=run.tenant_id,
            client_id=run.client_id,
            source_type="ozon_realization",
            source_label="Ozon realization",
            required=False,
            publication_required=False,
            status="loaded",
            snapshot_hash="collection-hash",
            row_count=1,
            raw_path="/tmp/fixture",
            payload={},
            loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
        )
        db.add(collection)
        db.flush()
        repository.replace_marketplace_operation_facts(
            db,
            collection,
            [_operation("source-1", "100")],
        )
        repository.replace_marketplace_operation_facts(
            db,
            collection,
            [_operation("source-1", "125")],
        )
        db.commit()
        count = db.scalar(select(func.count()).select_from(MarketplaceOperationFact))
        row = db.scalar(select(MarketplaceOperationFact))
        adapted = repository._ozon_realization_source_rows(
            db,
            tenant_id=run.tenant_id,
            refresh_run=run,
            limit=50,
        )

    assert count == 1
    assert row is not None
    assert row.amount == Decimal("125.00")
    assert len(adapted) == 1
    assert adapted[0].row_payload["sale_amount"] == Decimal("125.00")


def test_operation_staging_failure_keeps_current_facts() -> None:
    session_factory, refresh_run = _context()
    with session_factory() as db:
        run = db.get(SourceRefreshRun, refresh_run.id)
        assert run is not None
        collection = SourceRefreshCollection(
            refresh_run_id=run.id,
            tenant_id=run.tenant_id,
            client_id=run.client_id,
            source_type="ozon_realization",
            source_label="Ozon realization",
            required=False,
            publication_required=False,
            status="loaded",
            snapshot_hash="collection-hash",
            row_count=1,
            raw_path="/tmp/fixture",
            payload={},
            loaded_at=datetime(2026, 7, 11, tzinfo=UTC),
        )
        db.add(collection)
        db.flush()
        repository.replace_marketplace_operation_facts(
            db,
            collection,
            [_operation("source-1", "100")],
        )
        db.commit()

        with pytest.raises(IntegrityError):
            repository.replace_marketplace_operation_facts(
                db,
                collection,
                [
                    _operation("duplicate", "200"),
                    _operation("duplicate", "300"),
                ],
            )
        db.rollback()
        rows = list(db.scalars(select(MarketplaceOperationFact)))

    assert len(rows) == 1
    assert rows[0].amount == Decimal("100.00")


def test_full_calculation_parity_compares_rows_kpis_reconciliation_and_taxes() -> None:
    report = {
        "rows": [
            {
                "grain": "sku-1",
                "netRevenue": Decimal("100.00"),
                "vatOutput": Decimal("20.00"),
                "incomeTax": Decimal("10.00"),
                "quality": "reliable",
            }
        ]
    }
    payload = {
        "kpis": {"revenue": Decimal("100.00")},
        "documentReconciliation": [{"document": "report-1", "delta": 0}],
    }
    legacy = {
        "report": report,
        "payload": payload,
        "daily_facts": [],
        "wb_rows": 2,
        "wb_source_rows": 2,
        "wb_report_period_rows": 1,
    }
    streamed = {
        "report": report,
        "payload": payload,
        "daily_facts": [],
        "wb_rows": 1,
        "wb_source_rows": 2,
        "wb_report_period_rows": 1,
    }

    matched = _full_wb_calculation_parity(legacy, streamed, legacy_row_count=1)
    streamed["payload"] = {
        **payload,
        "kpis": {"revenue": Decimal("99.99")},
    }
    mismatched = _full_wb_calculation_parity(legacy, streamed, legacy_row_count=1)

    assert matched["status"] == "matched"
    assert mismatched["status"] == "mismatch"
    assert "kpiAndReconciliation" in mismatched["mismatches"]


def _context():
    engine = make_engine("sqlite:///:memory:")
    init_db(engine)
    session_factory = make_session_factory(engine)
    now = datetime(2026, 7, 11, tzinfo=UTC)
    refresh_run = SourceRefreshRun(
        id="refresh-1",
        tenant_id="tenant",
        client_id="client",
        mode="daily",
        credential_source="tenant",
        dry_run=False,
        status="source_loaded",
        snapshot_set_id="snapshot-1",
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 14),
        created_at=now,
        updated_at=now,
    )
    with session_factory() as db:
        db.add(Tenant(id="tenant", name="Tenant", created_at=now))
        db.commit()
        db.add(refresh_run)
        db.commit()
    return session_factory, refresh_run


def _daily_fact(
    *,
    net_revenue: str,
    fact_date: date = date(2026, 7, 5),
) -> MarketplaceFinanceDailyFact:
    return MarketplaceFinanceDailyFact(
        client_id="client",
        seller_account_id="seller",
        organization_id="org",
        fact_date=fact_date,
        marketplace_report_id="report",
        document_kind="commissioner_report",
        nm_id=10,
        vendor_code="article",
        barcode="barcode",
        onec_item_id="item",
        sales_model="fbo",
        operation_group="sale",
        quantity=1,
        sales_quantity=1,
        net_revenue=net_revenue,
        source_row_count=1,
        source_hash_digest="a" * 64,
        methodology_version="test-v1",
    )


def _operation(source_key: str, amount: str) -> dict[str, object]:
    return {
        "source_key": source_key,
        "source_row_id": "row-1",
        "operation_id": "operation-1",
        "posting_number": "posting-1",
        "product_id": "product-1",
        "offer_id": "offer-1",
        "sku": "sku-1",
        "operation_type": "sale",
        "operation_date": date(2026, 7, 5),
        "quantity": Decimal("1"),
        "amount": Decimal(amount),
        "commission": Decimal("10"),
        "service_amount": Decimal("5"),
        "currency": "RUB",
        "raw_payload_hash": "b" * 64,
    }
