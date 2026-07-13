from __future__ import annotations

import ctypes
import gc
import multiprocessing
import shutil
import tempfile
from collections.abc import Iterable
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from multiprocessing.connection import Connection
from pathlib import Path

from wb_unit_economics.calculation import (
    METHODOLOGY_VERSION,
    build_unit_economics_report,
    overlaps_period,
    week_bounds,
)
from wb_unit_economics.contracts import (
    AccountOrgMapping,
    InputVatPolicy,
    MarketplaceFinanceDailyFact,
    OnecMarketplaceServiceRow,
    OnecUnfCostSnapshot,
    ReportStatus,
    SkuMapping,
    TaxProfile,
    UnitEconomicsReport,
    WbApiSnapshot,
    WbExpenseAllocationBase,
    WbSalesReportSummaryRow,
)
from wb_unit_economics.wb_finance import iter_wb_finance_snapshots


@dataclass(frozen=True)
class StreamedUnitEconomicsBuild:
    report: UnitEconomicsReport
    wb_rows: int
    bucket_count: int
    spool_dir: Path
    daily_facts: list[MarketplaceFinanceDailyFact]


def build_streamed_unit_economics_report(
    *,
    client_id: str,
    wb_finance_dir: Path,
    cost_snapshots: list[OnecUnfCostSnapshot],
    sku_mappings: list[SkuMapping],
    account_org_mapping: list[AccountOrgMapping],
    wb_sales_report_summary_rows: list[WbSalesReportSummaryRow] | None = None,
    expense_allocation_bases: list[WbExpenseAllocationBase] | None = None,
    onec_marketplace_service_rows: list[OnecMarketplaceServiceRow] | None = None,
    tax_profiles: list[TaxProfile] | None = None,
    input_vat_policies: list[InputVatPolicy] | None = None,
    confirmed_input_vat_org_ids: set[str] | None = None,
    generated_at: datetime,
    report_period_start: date,
    report_period_end: date,
    as_of_date: date | None = None,
    methodology_version: str = METHODOLOGY_VERSION,
    stream_cache_dir: Path | None = None,
    keep_stream_cache: bool = False,
    collect_daily_facts: bool = True,
) -> StreamedUnitEconomicsBuild:
    prepared = prepare_streamed_wb_spool(
        wb_finance_dir=wb_finance_dir,
        client_id=client_id,
        account_org_mapping=account_org_mapping,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        stream_cache_dir=stream_cache_dir,
        keep_stream_cache=keep_stream_cache,
    )
    return build_streamed_unit_economics_from_spool(
        prepared=prepared,
        client_id=client_id,
        cost_snapshots=cost_snapshots,
        sku_mappings=sku_mappings,
        account_org_mapping=account_org_mapping,
        wb_sales_report_summary_rows=wb_sales_report_summary_rows,
        expense_allocation_bases=expense_allocation_bases,
        onec_marketplace_service_rows=onec_marketplace_service_rows,
        tax_profiles=tax_profiles,
        input_vat_policies=input_vat_policies,
        confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
        generated_at=generated_at,
        as_of_date=as_of_date,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        methodology_version=methodology_version,
        collect_daily_facts=collect_daily_facts,
    )


@dataclass
class PreparedStreamedWbSpool:
    spool: _Spool
    spool_dir: Path
    keep_stream_cache: bool
    cleaned: bool = False

    def cleanup(self) -> None:
        if self.cleaned:
            return
        self.cleaned = True
        if not self.keep_stream_cache:
            shutil.rmtree(self.spool_dir, ignore_errors=True)

    def __del__(self) -> None:
        with suppress(Exception):  # pragma: no cover - interpreter shutdown safety
            self.cleanup()


def prepare_streamed_wb_spool(
    *,
    wb_finance_dir: Path,
    client_id: str,
    account_org_mapping: Iterable[AccountOrgMapping],
    report_period_start: date,
    report_period_end: date,
    stream_cache_dir: Path | None = None,
    keep_stream_cache: bool = False,
    isolate_process: bool = False,
) -> PreparedStreamedWbSpool:
    cache_root = stream_cache_dir or Path("data/.cache/wb_stream_rebuild")
    cache_root.mkdir(parents=True, exist_ok=True)
    spool_dir = Path(tempfile.mkdtemp(prefix="stream-", dir=cache_root))
    try:
        mapping_items = list(account_org_mapping)
        spool = (
            _spool_wb_snapshots_isolated(
                wb_finance_dir=wb_finance_dir,
                client_id=client_id,
                account_org_mapping=mapping_items,
                report_period_start=report_period_start,
                report_period_end=report_period_end,
                spool_dir=spool_dir,
            )
            if isolate_process
            else _spool_wb_snapshots(
                wb_finance_dir=wb_finance_dir,
                client_id=client_id,
                account_org_mapping=mapping_items,
                report_period_start=report_period_start,
                report_period_end=report_period_end,
                spool_dir=spool_dir,
            )
        )
        return PreparedStreamedWbSpool(
            spool=spool,
            spool_dir=spool_dir,
            keep_stream_cache=keep_stream_cache,
        )
    except BaseException:
        if not keep_stream_cache:
            shutil.rmtree(spool_dir, ignore_errors=True)
        raise


def _spool_wb_snapshots_isolated(
    *,
    wb_finance_dir: Path,
    client_id: str,
    account_org_mapping: list[AccountOrgMapping],
    report_period_start: date,
    report_period_end: date,
    spool_dir: Path,
) -> _Spool:
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(
        target=_isolated_spool_worker,
        args=(
            send,
            wb_finance_dir,
            client_id,
            account_org_mapping,
            report_period_start,
            report_period_end,
            spool_dir,
        ),
        name="wb-finance-spool",
    )
    process.start()
    send.close()
    try:
        while process.is_alive() and not receive.poll(1):
            process.join(timeout=1)
        if not receive.poll():
            process.join()
            raise RuntimeError(
                f"isolated WB spool exited without a result: {process.exitcode}"
            )
        status, payload = receive.recv()
        process.join()
        if status != "ok" or not isinstance(payload, _Spool):
            raise RuntimeError(f"isolated WB spool failed: {payload}")
        return payload
    finally:
        receive.close()
        if process.is_alive():
            process.terminate()
            process.join()


def _isolated_spool_worker(
    send: Connection,
    wb_finance_dir: Path,
    client_id: str,
    account_org_mapping: list[AccountOrgMapping],
    report_period_start: date,
    report_period_end: date,
    spool_dir: Path,
) -> None:
    try:
        spool = _spool_wb_snapshots(
            wb_finance_dir=wb_finance_dir,
            client_id=client_id,
            account_org_mapping=account_org_mapping,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            spool_dir=spool_dir,
        )
        send.send(("ok", spool))
    except Exception as exc:
        send.send(("error", exc.__class__.__name__))
    finally:
        send.close()


def build_streamed_unit_economics_from_spool(
    *,
    prepared: PreparedStreamedWbSpool,
    client_id: str,
    cost_snapshots: list[OnecUnfCostSnapshot],
    sku_mappings: list[SkuMapping],
    account_org_mapping: list[AccountOrgMapping],
    wb_sales_report_summary_rows: list[WbSalesReportSummaryRow] | None = None,
    expense_allocation_bases: list[WbExpenseAllocationBase] | None = None,
    onec_marketplace_service_rows: list[OnecMarketplaceServiceRow] | None = None,
    tax_profiles: list[TaxProfile] | None = None,
    input_vat_policies: list[InputVatPolicy] | None = None,
    confirmed_input_vat_org_ids: set[str] | None = None,
    generated_at: datetime,
    report_period_start: date,
    report_period_end: date,
    as_of_date: date | None = None,
    methodology_version: str = METHODOLOGY_VERSION,
    collect_daily_facts: bool = True,
) -> StreamedUnitEconomicsBuild:
    try:
        report, daily_facts = _build_report_from_spool(
            client_id=client_id,
            spool=prepared.spool,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_org_mapping=account_org_mapping,
            wb_sales_report_summary_rows=wb_sales_report_summary_rows or [],
            expense_allocation_bases=expense_allocation_bases or [],
            onec_marketplace_service_rows=onec_marketplace_service_rows or [],
            tax_profiles=tax_profiles,
            input_vat_policies=input_vat_policies,
            confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
            generated_at=generated_at,
            as_of_date=as_of_date,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            methodology_version=methodology_version,
            collect_daily_facts=collect_daily_facts,
        )
        return StreamedUnitEconomicsBuild(
            report=report,
            wb_rows=prepared.spool.rows_in_report_period,
            bucket_count=len(prepared.spool.buckets),
            spool_dir=prepared.spool_dir,
            daily_facts=daily_facts,
        )
    finally:
        prepared.cleanup()


@dataclass(frozen=True)
class _Bucket:
    seller_account_id: str
    week_start: date
    week_end: date
    path: Path
    row_count: int


@dataclass(frozen=True)
class _Spool:
    buckets: list[_Bucket]
    source_coverage_start: date | None
    source_coverage_end: date | None
    rows_seen: int
    rows_in_report_period: int


def _spool_wb_snapshots(
    *,
    wb_finance_dir: Path,
    client_id: str,
    account_org_mapping: Iterable[AccountOrgMapping],
    report_period_start: date,
    report_period_end: date,
    spool_dir: Path,
) -> _Spool:
    handles: dict[tuple[str, date], object] = {}
    bucket_paths: dict[tuple[str, date], Path] = {}
    bucket_counts: dict[tuple[str, date], int] = {}
    source_coverage_start: date | None = None
    source_coverage_end: date | None = None
    rows_seen = 0
    rows_in_report_period = 0
    try:
        for snapshot in iter_wb_finance_snapshots(
            wb_finance_dir,
            client_id=client_id,
            account_org_mapping=account_org_mapping,
        ):
            rows_seen += 1
            source_coverage_start = (
                snapshot.period_start
                if source_coverage_start is None
                else min(source_coverage_start, snapshot.period_start)
            )
            source_coverage_end = (
                snapshot.period_end
                if source_coverage_end is None
                else max(source_coverage_end, snapshot.period_end)
            )
            if rows_seen % 100_000 == 0:
                _release_stream_memory()
            week_start, week_end = week_bounds(snapshot.period_start)
            if not report_period_start <= week_end <= report_period_end:
                continue
            rows_in_report_period += 1
            key = (snapshot.seller_account_id, week_start)
            handle = handles.get(key)
            if handle is None:
                path = spool_dir / _bucket_filename(
                    snapshot.seller_account_id,
                    week_start,
                )
                handle = path.open("a", encoding="utf-8")
                handles[key] = handle
                bucket_paths[key] = path
                bucket_counts[key] = 0
            handle.write(snapshot.model_dump_json())
            handle.write("\n")
            bucket_counts[key] += 1
    finally:
        for handle in handles.values():
            handle.close()
        _release_stream_memory()

    buckets = [
        _Bucket(
            seller_account_id=seller_account_id,
            week_start=week_start,
            week_end=week_bounds(week_start)[1],
            path=bucket_paths[(seller_account_id, week_start)],
            row_count=bucket_counts[(seller_account_id, week_start)],
        )
        for seller_account_id, week_start in sorted(bucket_paths)
    ]
    return _Spool(
        buckets=buckets,
        source_coverage_start=source_coverage_start,
        source_coverage_end=source_coverage_end,
        rows_seen=rows_seen,
        rows_in_report_period=rows_in_report_period,
    )


def _build_report_from_spool(
    *,
    client_id: str,
    spool: _Spool,
    cost_snapshots: list[OnecUnfCostSnapshot],
    sku_mappings: list[SkuMapping],
    account_org_mapping: list[AccountOrgMapping],
    wb_sales_report_summary_rows: list[WbSalesReportSummaryRow],
    expense_allocation_bases: list[WbExpenseAllocationBase],
    onec_marketplace_service_rows: list[OnecMarketplaceServiceRow],
    tax_profiles: list[TaxProfile] | None,
    input_vat_policies: list[InputVatPolicy] | None,
    confirmed_input_vat_org_ids: set[str] | None,
    generated_at: datetime,
    as_of_date: date | None,
    report_period_start: date,
    report_period_end: date,
    methodology_version: str,
    collect_daily_facts: bool,
) -> tuple[UnitEconomicsReport, list[MarketplaceFinanceDailyFact]]:
    rows = []
    report_reconciliation_rows = []
    onec_report_reconciliation_rows = []
    onec_report_product_rows = []
    expense_allocation_rows = []
    tax_input_reconciliation_rows = []
    daily_facts: list[MarketplaceFinanceDailyFact] = []
    for bucket in spool.buckets:
        snapshots = _read_bucket(bucket.path)
        partial = build_unit_economics_report(
            client_id=client_id,
            wb_snapshots=snapshots,
            cost_snapshots=cost_snapshots,
            sku_mappings=sku_mappings,
            account_org_mapping=account_org_mapping,
            wb_sales_report_summary_rows=_summary_rows_for_bucket(
                wb_sales_report_summary_rows,
                bucket,
            ),
            expense_allocation_bases=_expense_bases_for_bucket(
                expense_allocation_bases,
                bucket,
            ),
            onec_marketplace_service_rows=_service_rows_for_bucket(
                onec_marketplace_service_rows,
                bucket,
            ),
            tax_profiles=tax_profiles,
            input_vat_policies=input_vat_policies,
            confirmed_input_vat_org_ids=confirmed_input_vat_org_ids,
            generated_at=generated_at,
            as_of_date=as_of_date,
            report_period_start=report_period_start,
            report_period_end=report_period_end,
            methodology_version=methodology_version,
            daily_facts_sink=daily_facts if collect_daily_facts else None,
        )
        rows.extend(partial.rows)
        report_reconciliation_rows.extend(partial.report_reconciliation_rows)
        onec_report_reconciliation_rows.extend(partial.onec_report_reconciliation_rows)
        onec_report_product_rows.extend(partial.onec_report_product_rows)
        expense_allocation_rows.extend(partial.expense_allocation_rows)
        tax_input_reconciliation_rows.extend(partial.tax_input_reconciliation_rows)
        del snapshots, partial
        _release_stream_memory()

    effective_as_of = as_of_date or generated_at.date()
    report = UnitEconomicsReport(
        client_id=client_id,
        report_period_start=report_period_start,
        report_period_end=report_period_end,
        source_coverage_start=spool.source_coverage_start,
        source_coverage_end=spool.source_coverage_end,
        generated_at=generated_at,
        status=(
            ReportStatus.PARTIAL_PERIOD
            if effective_as_of <= report_period_end
            else ReportStatus.FINAL
        ),
        methodology_version=methodology_version,
        rows=sorted(
            rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.organization_id,
                row.nm_id or 0,
                row.vendor_code,
            ),
        ),
        report_reconciliation_rows=sorted(
            report_reconciliation_rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.organization_id,
                row.wb_report_id,
            ),
        ),
        onec_report_reconciliation_rows=sorted(
            onec_report_reconciliation_rows,
            key=lambda row: (
                row.week_start,
                row.document_kind.value,
                row.seller_account_id,
                row.organization_id,
            ),
        ),
        onec_report_product_rows=sorted(
            onec_report_product_rows,
            key=lambda row: (
                row.week_start,
                row.document_kind.value,
                row.seller_account_id,
                row.organization_id,
                row.nm_id or 0,
                row.vendor_code,
            ),
        ),
        expense_allocation_rows=sorted(
            expense_allocation_rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.document_label,
                row.expense_category,
                row.nm_id or 0,
                row.vendor_code,
            ),
        ),
        tax_input_reconciliation_rows=sorted(
            tax_input_reconciliation_rows,
            key=lambda row: (
                row.week_start,
                row.seller_account_id,
                row.organization_id,
            ),
        ),
        wb_sales_report_summary_rows=sorted(
            _summary_rows_in_report_period(
                wb_sales_report_summary_rows,
                report_period_start=report_period_start,
                report_period_end=report_period_end,
            ),
            key=lambda row: (
                row.date_from,
                row.seller_account_id,
                row.report_type or 0,
                row.report_id,
            ),
        ),
    )
    return report, daily_facts


def _read_bucket(path: Path) -> list[WbApiSnapshot]:
    snapshots: list[WbApiSnapshot] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                snapshots.append(WbApiSnapshot.model_validate_json(line))
    return snapshots


def _release_stream_memory() -> None:
    """Release parser arenas between bounded streaming batches when supported."""

    gc.collect()
    try:
        malloc_trim = ctypes.CDLL(None).malloc_trim
    except (AttributeError, OSError):
        return
    malloc_trim(0)


def _summary_rows_for_bucket(
    rows: list[WbSalesReportSummaryRow],
    bucket: _Bucket,
) -> list[WbSalesReportSummaryRow]:
    return [
        row
        for row in rows
        if row.seller_account_id == bucket.seller_account_id
        and (
            row.date_from == date.min
            or overlaps_period(
                row.date_from,
                row.date_to,
                bucket.week_start,
                bucket.week_end,
            )
        )
    ]


def _summary_rows_in_report_period(
    rows: list[WbSalesReportSummaryRow],
    *,
    report_period_start: date,
    report_period_end: date,
) -> list[WbSalesReportSummaryRow]:
    return [
        row
        for row in rows
        if row.date_from == date.min
        or report_period_start <= row.date_to <= report_period_end
    ]


def _expense_bases_for_bucket(
    bases: list[WbExpenseAllocationBase],
    bucket: _Bucket,
) -> list[WbExpenseAllocationBase]:
    return [
        base
        for base in bases
        if base.seller_account_id == bucket.seller_account_id
        and overlaps_period(
            base.week_start,
            base.week_end,
            bucket.week_start,
            bucket.week_end,
        )
    ]


def _service_rows_for_bucket(
    rows: list[OnecMarketplaceServiceRow],
    bucket: _Bucket,
) -> list[OnecMarketplaceServiceRow]:
    return [
        row
        for row in rows
        if overlaps_period(
            row.week_start,
            row.week_end,
            bucket.week_start,
            bucket.week_end,
        )
    ]


def _bucket_filename(seller_account_id: str, week_start: date) -> str:
    safe_account = "".join(
        char if char.isalnum() or char in {"-", "_"} else "_"
        for char in seller_account_id
    )
    return f"{safe_account}_{week_start.isoformat()}.jsonl"
