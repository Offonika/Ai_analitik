from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from wb_unit_economics.web import repository
from wb_unit_economics.web.models import ReportRun


class NoReportRowsError(ValueError):
    pass


def last_closed_week_period(report: ReportRun) -> tuple[date, date]:
    period_end = report.period_end
    days_since_sunday = (period_end.weekday() - 6) % 7
    closed_week_end = period_end - timedelta(days=days_since_sunday)
    closed_week_start = closed_week_end - timedelta(days=6)
    if closed_week_start < report.period_start:
        raise ValueError(
            "В выбранном report_id нет полной закрытой недели "
            "в пределах периода отчёта."
        )
    return closed_week_start, closed_week_end


def report_summary_for_period(
    db: Any,
    report: ReportRun,
    *,
    period_start: date | None,
    period_end: date | None,
) -> dict[str, Any]:
    if period_start is None and period_end is None:
        return repository.report_full_payload(db, report)
    if period_start is None or period_end is None:
        raise ValueError("Дата начала и дата конца должны быть указаны вместе.")
    if period_start > period_end:
        raise ValueError("Дата начала не может быть позже даты конца.")
    if period_start < report.period_start or period_end > report.period_end:
        raise ValueError(
            "Выбранный период должен находиться внутри периода report_id "
            f"{report.period_start}..{report.period_end}."
        )

    base = repository.report_summary_payload(db, report)
    items: list[dict[str, Any]] = []
    offset = 0
    analytics: dict[str, Any] | None = None
    total = 0
    while True:
        page = repository.query_report_rows(
            db,
            report,
            period_start=period_start,
            period_end=period_end,
            limit=repository.REPORT_ROWS_MAX_LIMIT,
            offset=offset,
        )
        if analytics is None:
            analytics = dict(page["analytics"])
            total = int(page["total"])
        page_items = list(page["items"])
        items.extend(page_items)
        offset += len(page_items)
        if not page_items or offset >= total:
            break
    if not items:
        raise NoReportRowsError(
            f"В выбранном периоде {period_start}..{period_end} нет строк отчёта."
        )

    closed_week = (
        period_start.weekday() == 0
        and period_end.weekday() == 6
        and (period_end - period_start).days == 6
    )
    period_label = f"{period_start:%d.%m.%Y} - {period_end:%d.%m.%Y}"
    source_meta = dict(base["meta"])
    source_period = str(
        source_meta.get("reportPeriod") or source_meta.get("period") or ""
    )
    source_coverage = str(source_meta.get("sourceCoverage") or "")
    meta = {
        **source_meta,
        "period": period_label,
        "reportPeriod": period_label,
        "periodStart": period_start.isoformat(),
        "periodEnd": period_end.isoformat(),
        "periodStatus": (
            "закрытая неделя" if closed_week else "выбранный период отчёта"
        ),
        "sourceCoverage": period_label,
        "sourceCoverageStart": period_start.isoformat(),
        "sourceCoverageEnd": period_end.isoformat(),
        "analysisScope": "closed_week" if closed_week else "selected_period",
        "sourceReportPeriod": source_period,
        "sourceReportCoverage": source_coverage,
    }
    return {
        **base,
        **(analytics or {}),
        "meta": meta,
        "unitRows": items,
        "returns": repository.returns_payload(
            items,
            report.return_reason_limitation,
        ),
        # Месячная сверка остаётся атрибутом исходного report_id и не должна
        # переименовываться в недельную или произвольную сверку.
        "reconciliationMonthly": [],
    }


def report_summary_for_last_closed_week(
    db: Any,
    report: ReportRun,
) -> tuple[date, date, dict[str, Any]]:
    period_start, period_end = last_closed_week_period(report)
    requested_period_start = period_start
    requested_period_end = period_end
    while period_start >= report.period_start:
        try:
            summary = report_summary_for_period(
                db,
                report,
                period_start=period_start,
                period_end=period_end,
            )
        except NoReportRowsError:
            period_end = period_start - timedelta(days=1)
            period_start = period_end - timedelta(days=6)
            continue
        summary = {
            **summary,
            "meta": {
                **summary["meta"],
                "requestedPeriodStart": requested_period_start.isoformat(),
                "requestedPeriodEnd": requested_period_end.isoformat(),
                "actualPeriodStart": period_start.isoformat(),
                "actualPeriodEnd": period_end.isoformat(),
                "periodFallback": (
                    period_start != requested_period_start
                    or period_end != requested_period_end
                ),
            },
        }
        return period_start, period_end, summary
    raise NoReportRowsError(
        "В выбранном report_id нет строк за полную закрытую неделю."
    )
