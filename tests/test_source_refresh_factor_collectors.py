from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from wb_unit_economics.web import source_refresh as sr


class _FakeService:
    def __init__(self) -> None:
        self.calls: dict[str, tuple] = {}
        self.tariffs_recorded = False
        self.goods_return_recorded = False
        self.return_claims_recorded = False
        self.supplier_sales_recorded = False
        self.measurements_recorded: set[str] = set()

    def _wb_tariffs_exporter(self, accounts, output_dir, *, period_start, period_end):
        self.calls["tariffs"] = (tuple(accounts), output_dir, period_start, period_end)
        return []

    def _record_wb_tariffs(
        self,
        db,
        refresh_run,
        output_dir,
        results,
        *,
        wb_cabinet_ids,
        period_start,
        period_end,
    ):
        self.tariffs_recorded = True
        return SimpleNamespace(id=1)

    def _wb_goods_return_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["goods_return"] = (
            tuple(accounts),
            output_dir,
            period_start,
            period_end,
        )
        return []

    def _record_wb_goods_return(
        self,
        db,
        refresh_run,
        output_dir,
        results,
        *,
        wb_cabinet_ids,
        period_start,
        period_end,
    ):
        self.goods_return_recorded = True
        return SimpleNamespace(id=4)

    def _wb_return_claims_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["return_claims"] = (
            tuple(accounts),
            output_dir,
            period_start,
            period_end,
        )
        return []

    def _record_wb_return_claims(
        self,
        db,
        refresh_run,
        output_dir,
        results,
        *,
        wb_cabinet_ids,
    ):
        self.return_claims_recorded = True
        return SimpleNamespace(id=5)

    def _wb_supplier_sales_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["supplier_sales"] = (
            tuple(accounts),
            output_dir,
            period_start,
            period_end,
        )
        return []

    def _record_wb_supplier_sales(
        self,
        db,
        refresh_run,
        output_dir,
        results,
        *,
        wb_cabinet_ids,
        period_start,
        period_end,
    ):
        self.supplier_sales_recorded = True
        return SimpleNamespace(id=2)

    def _wb_measurement_penalties_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["measurement_penalties"] = (
            tuple(accounts),
            output_dir,
            period_start,
            period_end,
        )
        return []

    def _wb_warehouse_measurements_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["warehouse_measurements"] = (
            tuple(accounts),
            output_dir,
            period_start,
            period_end,
        )
        return []

    def _record_wb_measurements(
        self,
        db,
        refresh_run,
        output_dir,
        results,
        *,
        source_type,
        wb_cabinet_ids,
        period_start,
        period_end,
    ):
        self.measurements_recorded.add(source_type)
        return SimpleNamespace(id=3)


def _context(tmp_path: Path, *, wb: bool) -> sr.CollectorContext:
    wb_settings = (
        SimpleNamespace(
            accounts=(SimpleNamespace(api_key="k", seller_account_id="WB_ACCOUNT_1"),)
        )
        if wb
        else None
    )
    credentials = sr.SourceCredentials(
        wb_settings=wb_settings,
        onec_settings=None,
        ozon_settings=None,
        wb_cabinet_ids={},
        ozon_cabinet_ids={},
        issues=(),
    )
    return sr.CollectorContext(
        db=None,
        refresh_run=None,
        credentials=credentials,
        root_dir=tmp_path,
        period_start=date(2026, 7, 1),
        period_end=date(2026, 7, 19),
        mode="full",
    )


def test_factor_collectors_call_exporter_and_return_output_dir(
    tmp_path: Path,
) -> None:
    service = _FakeService()
    context = _context(tmp_path, wb=True)

    tariffs = sr._collect_wb_tariffs(service, context)
    goods_return = sr._collect_wb_goods_return(service, context)
    return_claims = sr._collect_wb_return_claims(service, context)
    supplier_sales = sr._collect_wb_supplier_sales(service, context)
    measurement_penalties = sr._collect_wb_measurement_penalties(service, context)
    warehouse_measurements = sr._collect_wb_warehouse_measurements(service, context)

    assert tariffs.output_dir == tmp_path / "wb_tariffs"
    assert goods_return.output_dir == tmp_path / "wb_goods_return"
    assert return_claims.output_dir == tmp_path / "wb_return_claims"
    assert supplier_sales.output_dir == tmp_path / "wb_supplier_sales"
    assert measurement_penalties.output_dir == tmp_path / "wb_measurement_penalties"
    assert warehouse_measurements.output_dir == tmp_path / "wb_warehouse_measurements"
    assert set(service.calls) == {
        "tariffs",
        "goods_return",
        "return_claims",
        "supplier_sales",
        "measurement_penalties",
        "warehouse_measurements",
    }
    assert service.calls["tariffs"][0]  # accounts passed through
    assert service.tariffs_recorded is True
    assert service.goods_return_recorded is True
    assert service.return_claims_recorded is True
    assert service.supplier_sales_recorded is True
    assert service.measurements_recorded == {
        "wb_measurement_penalties",
        "wb_warehouse_measurements",
    }


def test_factor_collectors_skip_without_wb_settings(tmp_path: Path) -> None:
    service = _FakeService()
    context = _context(tmp_path, wb=False)

    result = sr._collect_wb_tariffs(service, context)

    assert result.output_dir is None
    assert service.calls == {}


def test_factor_collectors_registered_as_optional() -> None:
    service = sr.SourceRefreshService.__new__(sr.SourceRefreshService)
    plan = {
        collector.source_type: collector
        for collector in service._collector_plan("full")  # type: ignore[attr-defined]
    }
    for source_type in (
        "wb_tariffs",
        "wb_goods_return",
        "wb_return_claims",
        "wb_supplier_sales",
        "wb_measurement_penalties",
        "wb_warehouse_measurements",
    ):
        assert source_type in plan
        assert plan[source_type].required is False
