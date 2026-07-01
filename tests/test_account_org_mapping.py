import json

from scripts.build_excel_mvp_from_snapshots import (
    _best_organization_for_account,
    _latest_sales_register_dir,
    _wb_finance_manifest_notes,
)


def test_best_organization_prefers_name_match_over_order() -> None:
    organizations = [
        {"Description": "Beta Trading"},
        {"Description": "Alpha Seller"},
    ]

    index, organization = _best_organization_for_account(
        {"account_name": "Alpha"},
        organizations,
        set(),
        fallback_index=0,
    )

    assert index == 1
    assert organization["Description"] == "Alpha Seller"


def test_best_organization_skips_already_used_matches() -> None:
    organizations = [
        {"Description": "Alpha Seller"},
        {"Description": "Alpha Backup"},
    ]

    index, organization = _best_organization_for_account(
        {"account_name": "Alpha"},
        organizations,
        {0},
        fallback_index=0,
    )

    assert index == 1
    assert organization["Description"] == "Alpha Backup"


def test_latest_sales_register_dir_picks_newest_valid_snapshot(tmp_path) -> None:
    old_dir = tmp_path / "20260617-120000"
    new_dir = tmp_path / "20260618-120000"
    invalid_dir = tmp_path / "20260619-120000"
    old_dir.mkdir()
    new_dir.mkdir()
    invalid_dir.mkdir()
    (old_dir / "sales_register.raw.json").write_text("{}", encoding="utf-8")
    (new_dir / "sales_register.raw.json").write_text("{}", encoding="utf-8")

    assert _latest_sales_register_dir(tmp_path) == new_dir


def test_latest_sales_register_dir_allows_missing_base(tmp_path) -> None:
    assert _latest_sales_register_dir(tmp_path / "missing") is None


def test_wb_finance_manifest_notes_ignore_no_data_pagination(tmp_path) -> None:
    manifest_dir = tmp_path / "wb_finance"
    manifest_dir.mkdir()
    (manifest_dir / "manifest.json").write_text(
        json.dumps(
            {
                "results": [
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "account_name": "Кабинет 1",
                        "page_index": 1,
                        "status": "ok",
                    },
                    {
                        "seller_account_id": "WB_ACCOUNT_1",
                        "account_name": "Кабинет 1",
                        "page_index": 2,
                        "status": "no_data",
                    },
                    {
                        "seller_account_id": "WB_ACCOUNT_2",
                        "account_name": "Кабинет 2",
                        "page_index": 1,
                        "status": "rate_limited",
                        "error": "HTTP 429",
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    notes = _wb_finance_manifest_notes(
        manifest_dir,
        {"WB_ACCOUNT_2": "Организация 2"},
    )

    assert len(notes) == 1
    assert "Организация 2" in notes[0]
    assert "HTTP 429" in notes[0]
