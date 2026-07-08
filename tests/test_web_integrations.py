from __future__ import annotations

import json

from wb_unit_economics.web import integrations


def test_onec_secret_normalizes_metadata_url_suffix() -> None:
    settings = integrations.onec_odata_settings_from_secret(
        "baseUrl=https://onec.example/base/odata/standard.odata/$metadata;"
        "username=reader;password=secret"
    )

    assert settings.base_url == "https://onec.example/base/odata/standard.odata"


def test_onec_secret_normalizes_metadata_url_suffix_in_json() -> None:
    settings = integrations.onec_odata_settings_from_secret(
        json.dumps(
            {
                "baseUrl": "https://onec.example/base/odata/standard.odata/$metadata/",
                "username": "reader",
                "password": "secret",
            }
        )
    )

    assert settings.base_url == "https://onec.example/base/odata/standard.odata"
