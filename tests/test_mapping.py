from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from wb_unit_economics.contracts import AccountOrgMapping, MappingStatus
from wb_unit_economics.mapping import (
    build_sku_mapping_from_articles,
    build_sku_mapping_from_onec_marketplace_files,
)

TZ = ZoneInfo("Europe/Moscow")


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
