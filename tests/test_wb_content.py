from __future__ import annotations

from pathlib import Path

import httpx

from wb_unit_economics.wb_content import (
    WbContentClient,
    WbContentSettings,
    WbSellerAccount,
    build_cards_list_request,
    export_product_cards_page,
    extract_card_dimensions,
    flatten_product_cards,
)


def test_wb_content_settings_loads_accounts_without_printing_keys(
    tmp_path: Path,
) -> None:
    env_file = tmp_path / ".env"
    key_name = "WB_ACCOUNT_1_API_KEY"
    env_file.write_text(
        "\n".join(
            [
                "WB_ACCOUNT_1_NAME=First cabinet",
                f"{key_name}=test-key",
            ]
        ),
        encoding="utf-8",
    )

    settings = WbContentSettings.from_env_file(env_file)

    assert len(settings.accounts) == 1
    assert settings.accounts[0].seller_account_id == "WB_ACCOUNT_1"
    assert settings.accounts[0].account_name == "First cabinet"


def test_cards_list_request_uses_cursor_pagination() -> None:
    payload = build_cards_list_request(
        limit=100,
        cursor={"updatedAt": "2026-06-17T10:00:00Z", "nmID": 123},
    )

    cursor = payload["settings"]["cursor"]
    assert cursor == {
        "limit": 100,
        "updatedAt": "2026-06-17T10:00:00Z",
        "nmID": 123,
    }
    assert payload["settings"]["filter"] == {"withPhoto": -1}


def test_product_cards_export_page_writes_raw_payload(tmp_path: Path) -> None:
    requested: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested.append(request)
        return httpx.Response(
            200,
            json={
                "cards": [
                    {
                        "nmID": 101,
                        "vendorCode": "A-1",
                        "sizes": [{"techSize": "0", "skus": ["111"]}],
                    }
                ],
                "cursor": {"updatedAt": "2026-06-17T10:00:00Z", "nmID": 101},
            },
        )

    account = WbSellerAccount(
        seller_account_id="WB_ACCOUNT_1",
        account_name="First cabinet",
        api_key="test-key",
    )
    client = WbContentClient(account, transport=httpx.MockTransport(handler))
    try:
        result = export_product_cards_page(
            client,
            account,
            tmp_path,
            limit=50,
            locale="ru",
            cursor=None,
            page_index=1,
            cards_source="active",
            endpoint_url="https://content-api.wildberries.ru/content/v2/get/cards/list",
        )
    finally:
        client.close()

    assert result.ok is True
    assert result.card_count == 1
    assert result.flat_row_count == 1
    assert result.output_path == tmp_path / "wb_account_1_active_cards_page_1.raw.json"
    assert result.flat_output_path == (
        tmp_path / "wb_account_1_active_cards_page_1.flat.json"
    )
    assert result.output_path.exists()
    assert result.flat_output_path.exists()
    assert requested[0].method == "POST"
    assert requested[0].url.params["locale"] == "ru"


def test_flatten_product_cards_matches_finmodel_katalog_shape() -> None:
    account = WbSellerAccount(
        seller_account_id="WB_ACCOUNT_1",
        account_name="First cabinet",
        api_key="test-key",
    )
    rows = flatten_product_cards(
        account,
        [
            {
                "nmID": 101,
                "imtID": 201,
                "nmUUID": "uuid-1",
                "subjectID": 301,
                "subjectName": "Предмет",
                "brand": "Brand",
                "vendorCode": "A-1",
                "title": "Product",
                "dimensions": {
                    "length": 30,
                    "width": 20,
                    "height": 10,
                    "weightBrutto": 1.5,
                    "isValid": False,
                },
                "sizes": [
                    {"techSize": "42", "chrtID": 401, "skus": ["111", "222"]}
                ],
                "createdAt": "2026-06-01T00:00:00Z",
                "updatedAt": "2026-06-02T00:00:00Z",
            }
        ],
        cards_source="active",
    )

    assert len(rows) == 2
    assert rows[0]["nm_id"] == 101
    assert rows[0]["vendor_code"] == "a-1"
    assert rows[0]["barcode"] == "111"
    assert rows[1]["barcode"] == "222"
    assert rows[0]["length_cm"] == 30
    assert rows[0]["width_cm"] == 20
    assert rows[0]["height_cm"] == 10
    assert rows[0]["weight_brutto_kg"] == 1.5
    assert rows[0]["dimensions_valid"] is False
    assert rows[1]["length_cm"] == 30


def test_extract_card_dimensions_keeps_none_when_absent_or_invalid() -> None:
    assert extract_card_dimensions({}) == {
        "length_cm": None,
        "width_cm": None,
        "height_cm": None,
        "weight_brutto_kg": None,
        "dimensions_valid": None,
    }
    # Присутствующий, но не булев isValid не превращается в ложное значение.
    partial = extract_card_dimensions(
        {"dimensions": {"length": 5, "isValid": "yes"}}
    )
    assert partial["length_cm"] == 5
    assert partial["width_cm"] is None
    assert partial["weight_brutto_kg"] is None
    assert partial["dimensions_valid"] is None
