from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace

from wb_unit_economics.web import source_refresh as sr


class _FakeService:
    def __init__(self) -> None:
        self.calls: dict[str, tuple] = {}

    def _wb_tariffs_exporter(self, accounts, output_dir, *, period_start, period_end):
        self.calls["tariffs"] = (
            tuple(accounts), output_dir, period_start, period_end
        )
        return []

    def _wb_goods_return_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["goods_return"] = (
            tuple(accounts), output_dir, period_start, period_end
        )
        return []

    def _wb_supplier_sales_exporter(
        self, accounts, output_dir, *, period_start, period_end
    ):
        self.calls["supplier_sales"] = (
            tuple(accounts), output_dir, period_start, period_end
        )
        return []


def _context(tmp_path: Path, *, wb: bool) -> sr.CollectorContext:
    wb_settings = (
        SimpleNamespace(
            accounts=(
                SimpleNamespace(api_key="k", seller_account_id="WB_ACCOUNT_1"),
            )
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
    supplier_sales = sr._collect_wb_supplier_sales(service, context)

    assert tariffs.output_dir == tmp_path / "wb_tariffs"
    assert goods_return.output_dir == tmp_path / "wb_goods_return"
    assert supplier_sales.output_dir == tmp_path / "wb_supplier_sales"
    assert set(service.calls) == {"tariffs", "goods_return", "supplier_sales"}
    assert service.calls["tariffs"][0]  # accounts passed through


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
    for source_type in ("wb_tariffs", "wb_goods_return", "wb_supplier_sales"):
        assert source_type in plan
        assert plan[source_type].required is False
