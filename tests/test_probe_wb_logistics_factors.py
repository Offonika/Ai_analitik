from __future__ import annotations

import importlib.util
from datetime import date
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "probe_wb_logistics_factors",
    Path(__file__).resolve().parents[1] / "scripts" / "probe_wb_logistics_factors.py",
)
probe = importlib.util.module_from_spec(_SPEC)
assert _SPEC and _SPEC.loader
_SPEC.loader.exec_module(probe)


def test_collect_key_names_is_recursive_and_names_only() -> None:
    keys: set[str] = set()
    probe.collect_key_names(
        {"response": {"data": [{"reason": "цвет", "srid": "abc"}]}}, keys
    )
    assert "reason" in keys
    assert "srid" in keys
    # значения не попадают в множество имён
    assert "цвет" not in keys
    assert "abc" not in keys


def test_max_list_len_finds_deepest_list() -> None:
    assert probe.max_list_len({"a": {"b": [1, 2, 3]}}) == 3
    assert probe.max_list_len({"a": 1}) is None


def test_summarize_reports_field_presence_without_values() -> None:
    payload = {
        "data": [
            {"reason": "RAWVALUE", "status": "RAWSTATUS", "srid": "z", "nmId": 1}
        ]
    }
    summary = probe.summarize("goods_return", payload)
    present = summary["fields_present_anywhere"]
    assert present["reason"] is True
    assert present["srid"] is True
    assert present["returnType"] is False
    assert summary["max_list_len"] == 1
    # в сводке нет сырых значений
    assert "RAWVALUE" not in str(summary)
    assert "RAWSTATUS" not in str(summary)


def test_endpoints_are_read_only_wb_hosts() -> None:
    for _name, url, _params, _scope in probe.endpoints(date(2026, 7, 19)):
        assert url.startswith("https://")
        assert "wildberries.ru" in url
