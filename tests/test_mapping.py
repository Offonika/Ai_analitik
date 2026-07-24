from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from scripts import rebuild_report_from_sources
from wb_unit_economics.contracts import AccountOrgMapping, MappingStatus, SkuMapping
from wb_unit_economics.mapping import (
    build_sku_mapping_from_articles,
    build_sku_mapping_from_onec_marketplace_files,
    merge_sku_mappings_with_current,
)

TZ = ZoneInfo("Europe/Moscow")


def test_current_mapping_overrides_product_and_keeps_legacy_barcode_aliases() -> None:
    fallback = [
        _sku_mapping(barcode="111", onec_item_id="OLD"),
        _sku_mapping(barcode="222", onec_item_id="OLD"),
    ]
    current = [
        _sku_mapping(
            barcode="111",
            onec_item_id="NEW",
            match_method="mapping_service_auto_barcode",
        )
    ]

    merged = merge_sku_mappings_with_current(fallback, current)

    assert len(merged) == 2
    assert {item.barcode for item in merged} == {"111", "222"}
    assert {item.onec_item_id for item in merged} == {"NEW"}
    assert {item.match_method for item in merged} == {
        "mapping_service_auto_barcode"
    }


def test_rebuild_keeps_card_aliases_when_legacy_mapping_file_exists(
    monkeypatch,
    tmp_path: Path,
) -> None:
    card_mappings = [
        _sku_mapping(barcode="111", onec_item_id="OLD"),
        _sku_mapping(barcode="222", onec_item_id="OLD"),
    ]
    file_mappings = [
        _sku_mapping(barcode="111", onec_item_id="NEW"),
    ]
    monkeypatch.setattr(
        rebuild_report_from_sources,
        "load_wb_card_flat_rows",
        lambda _path: [{"card": "fixture"}],
    )
    monkeypatch.setattr(
        rebuild_report_from_sources,
        "build_sku_mapping_from_articles",
        lambda **_kwargs: card_mappings,
    )
    monkeypatch.setattr(
        rebuild_report_from_sources,
        "has_onec_marketplace_mapping_files",
        lambda _path: True,
    )
    monkeypatch.setattr(
        rebuild_report_from_sources,
        "build_sku_mapping_from_onec_marketplace_files",
        lambda **_kwargs: file_mappings,
    )

    merged = rebuild_report_from_sources._fallback_sku_mappings(
        client_id="client",
        wb_cards_dir=tmp_path / "cards",
        onec_marketplace_mapping_dir=tmp_path / "mapping",
        onec_barcodes=[],
        onec_nomenclature=[],
        account_mapping=account_mapping(),
    )

    assert {item.barcode for item in merged} == {"111", "222"}
    assert {item.onec_item_id for item in merged} == {"NEW"}


def test_current_mapping_keeps_alias_characteristic_for_same_onec_item() -> None:
    fallback = [
        _sku_mapping(
            barcode="222",
            onec_item_id="ITEM-1",
            onec_characteristic="SIZE-L",
        )
    ]
    current = [
        _sku_mapping(
            barcode="111",
            onec_item_id="ITEM-1",
            onec_characteristic="",
            match_method="imported_mapping_file",
        )
    ]

    merged = merge_sku_mappings_with_current(fallback, current)

    alias = next(item for item in merged if item.barcode == "222")
    assert alias.onec_characteristic == "SIZE-L"


def test_imported_current_projection_does_not_replace_legacy_file_identity() -> None:
    fallback = [_sku_mapping(barcode="222", onec_item_id="LEGACY-PRECISE")]
    current = [
        _sku_mapping(
            barcode="111",
            onec_item_id="LOSSY-IMPORT",
            match_method="imported_mapping_file",
        )
    ]

    merged = merge_sku_mappings_with_current(fallback, current)

    alias = next(item for item in merged if item.barcode == "222")
    assert alias.onec_item_id == "LEGACY-PRECISE"


def test_conflicting_current_products_do_not_overwrite_legacy_alias() -> None:
    fallback = [_sku_mapping(barcode="222", onec_item_id="OLD")]
    current = [
        _sku_mapping(barcode="111", onec_item_id="NEW-1"),
        _sku_mapping(barcode="333", onec_item_id="NEW-2"),
    ]

    merged = merge_sku_mappings_with_current(fallback, current)

    alias = next(item for item in merged if item.barcode == "222")
    assert alias.onec_item_id == "OLD"


def _sku_mapping(
    *,
    barcode: str,
    onec_item_id: str,
    match_method: str = "onec_marketplace_mapping",
    onec_characteristic: str = "",
) -> SkuMapping:
    return SkuMapping(
        client_id="client",
        seller_account_id="WB_ACCOUNT_1",
        organization_id="ORG-1",
        nm_id=101,
        vendor_code="A-1",
        barcode=barcode,
        onec_item_id=onec_item_id,
        onec_article=onec_item_id,
        onec_characteristic=onec_characteristic,
        match_method=match_method,
        confidence="1",
        status=MappingStatus.MATCHED,
        comment="fixture",
        updated_by="test",
        updated_at=datetime(2026, 7, 11, 7, 0, tzinfo=TZ),
    )


def account_mapping() -> list[AccountOrgMapping]:
    return [
        AccountOrgMapping(
            client_id="client",
            seller_account_id="WB_ACCOUNT_1",
            organization_id="ORG-1",
            seller_account_name="First",
            organization_name="Org",
        )
    ]


def test_nm_id_article_mapping_exact_match() -> None:
    mappings = build_sku_mapping_from_articles(
        client_id="client",
        wb_card_rows=[
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "nm_id": 101,
                "vendor_code": "A-1",
                "barcode": "111",
            }
        ],
        onec_barcode_rows=[],
        nomenclature_rows=[
            {"Ref_Key": "ITEM-1", "Артикул": "A-1", "Description": "Product"}
        ],
        account_org_mapping=account_mapping(),
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(mappings) == 1
    assert mappings[0].status is MappingStatus.MATCHED
    assert mappings[0].onec_item_id == "ITEM-1"
    assert mappings[0].onec_article == "A-1"
    assert mappings[0].onec_characteristic == ""
    assert mappings[0].barcode == ""
    assert mappings[0].match_method == "article"
    assert mappings[0].comment == "сопоставлено по nmId + артикулу"
    assert mappings[0].confidence == 1


def test_nm_id_article_mapping_marks_missing_article() -> None:
    mappings = build_sku_mapping_from_articles(
        client_id="client",
        wb_card_rows=[
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "nm_id": 101,
                "vendor_code": "",
                "barcode": "111",
            }
        ],
        onec_barcode_rows=[],
        account_org_mapping=account_mapping(),
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert mappings[0].status is MappingStatus.MISSING
    assert mappings[0].comment == "не заполнен артикул WB"


def test_nm_id_article_mapping_marks_duplicate_onec_articles_as_ambiguous() -> None:
    mappings = build_sku_mapping_from_articles(
        client_id="client",
        wb_card_rows=[
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "nm_id": 101,
                "vendor_code": "A-1",
                "barcode": "111",
            }
        ],
        onec_barcode_rows=[],
        nomenclature_rows=[
            {"Ref_Key": "ITEM-1", "Артикул": "A-1"},
            {"Ref_Key": "ITEM-2", "Артикул": "A-1"},
        ],
        account_org_mapping=account_mapping(),
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert mappings[0].status is MappingStatus.AMBIGUOUS
    assert mappings[0].comment == "артикул 1С найден в нескольких номенклатурах"


def test_same_nm_id_with_multiple_skus_has_single_article_mapping() -> None:
    mappings = build_sku_mapping_from_articles(
        client_id="client",
        wb_card_rows=[
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "nm_id": 101,
                "vendor_code": "A-1",
                "barcode": "111",
            },
            {
                "seller_account_id": "WB_ACCOUNT_1",
                "nm_id": 101,
                "vendor_code": "A-1",
                "barcode": "222",
            },
        ],
        onec_barcode_rows=[],
        nomenclature_rows=[
            {"Ref_Key": "ITEM-1", "Артикул": "A-1", "Description": "Product"}
        ],
        account_org_mapping=account_mapping(),
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(mappings) == 1
    assert mappings[0].nm_id == 101
    assert mappings[0].vendor_code == "a-1"
    assert mappings[0].barcode == ""
    assert mappings[0].onec_item_id == "ITEM-1"


def test_onec_marketplace_mapping_export_collapses_size_skus(tmp_path) -> None:
    export_path = tmp_path / "ВБ ИП Мухамедов С.Б..txt"
    export_path.write_text(
        "\ufeffНоменклатура WB\tАртикул поставщика\tАртикул WB\tРазмер WB\t"
        "Номенклатура\tАртикул\tХарактеристика\tУпаковка\n"
        "Бейсболка\tVendor-1\t101\t204000000001\tТовар 1\tA-1\t56-60\tшт\n"
        "Бейсболка\tVendor-1\t101\t204000000002\tТовар 1\tA-1\t58-62\tшт\n",
        encoding="utf-8",
    )
    mappings = build_sku_mapping_from_onec_marketplace_files(
        client_id="client",
        mapping_dir=tmp_path,
        nomenclature_rows=[
            {"Ref_Key": "ITEM-1", "Артикул": "A-1", "Description": "Товар 1"}
        ],
        account_org_mapping=[
            AccountOrgMapping(
                client_id="client",
                seller_account_id="WB_ACCOUNT_2",
                organization_id="ORG-2",
                seller_account_name="Султан",
                organization_name="Мухамедов С. Б. ИП",
            )
        ],
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    product_mapping = next(
        mapping
        for mapping in mappings
        if mapping.match_method == "onec_marketplace_mapping"
    )
    fallback_mappings = [
        mapping
        for mapping in mappings
        if mapping.match_method == "onec_marketplace_mapping_sku_fallback"
    ]
    sku_mappings = [
        mapping
        for mapping in mappings
        if mapping.match_method == "onec_marketplace_mapping_sku"
    ]
    assert len(mappings) == 5
    assert product_mapping.seller_account_id == "WB_ACCOUNT_2"
    assert product_mapping.nm_id == 101
    assert product_mapping.vendor_code == "vendor-1"
    assert product_mapping.barcode == ""
    assert product_mapping.onec_item_id == "ITEM-1"
    assert product_mapping.status is MappingStatus.MATCHED
    assert {mapping.barcode for mapping in fallback_mappings} == {
        "204000000001",
        "204000000002",
    }
    assert {mapping.barcode for mapping in sku_mappings} == {
        "204000000001",
        "204000000002",
    }


def test_onec_marketplace_mapping_export_keeps_empty_rows_missing(tmp_path) -> None:
    export_path = tmp_path / "ВБ ИП Мухамедова М.Б..txt"
    export_path.write_text(
        "\ufeffНоменклатура WB\tАртикул поставщика\tАртикул WB\tРазмер WB\t"
        "Номенклатура\tАртикул\tХарактеристика\tУпаковка\n"
        "<>\tSweaterBlue\t142970288\t2037369088309\t\t\t\t\n",
        encoding="utf-8",
    )
    mappings = build_sku_mapping_from_onec_marketplace_files(
        client_id="client",
        mapping_dir=tmp_path,
        nomenclature_rows=[],
        account_org_mapping=[
            AccountOrgMapping(
                client_id="client",
                seller_account_id="WB_ACCOUNT_1",
                organization_id="ORG-1",
                seller_account_name="Минзифа",
                organization_name="Мухамедова Минзифа Батырхановна",
            )
        ],
        updated_at=datetime(2026, 6, 17, 12, 0, tzinfo=TZ),
    )

    assert len(mappings) == 2
    assert {mapping.status for mapping in mappings} == {MappingStatus.MISSING}
    assert {mapping.comment for mapping in mappings} == {
        "нет сопоставления в выгрузке 1С"
    }


def test_onec_marketplace_mapping_export_short_nm_size_format(tmp_path) -> None:
    export_path = tmp_path / "Галустов.txt"
    export_path.write_text(
        "\ufeffНоменклатура WB\tАртикул WB\tРазмер WB\t"
        "Номенклатура\tХарактеристика\tУпаковка\n"
        "Джинсы\t698880158\t2049879068542\tДжинсы женские\t\tшт\n",
        encoding="utf-8",
    )
    mappings = build_sku_mapping_from_onec_marketplace_files(
        client_id="client",
        mapping_dir=tmp_path,
        nomenclature_rows=[
            {
                "Ref_Key": "ITEM-1",
                "Артикул": "A-1",
                "Description": "Джинсы женские",
            }
        ],
        account_org_mapping=[
            AccountOrgMapping(
                client_id="client",
                seller_account_id="WB_ACCOUNT_1",
                organization_id="ORG-1",
                seller_account_name="ИП Галустов",
                organization_name="Галустов Рафаэль",
            )
        ],
        updated_at=datetime(2026, 7, 4, 12, 0, tzinfo=TZ),
    )

    product_mapping = next(
        mapping
        for mapping in mappings
        if mapping.match_method == "onec_marketplace_mapping"
    )
    sku_mapping = next(
        mapping
        for mapping in mappings
        if mapping.match_method == "onec_marketplace_mapping_sku"
    )
    assert product_mapping.nm_id == 698880158
    assert product_mapping.vendor_code == ""
    assert product_mapping.onec_item_id == "ITEM-1"
    assert product_mapping.status is MappingStatus.MATCHED
    assert sku_mapping.barcode == "2049879068542"
    assert sku_mapping.onec_item_id == "ITEM-1"
