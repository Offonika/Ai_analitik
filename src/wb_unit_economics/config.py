from __future__ import annotations

from decimal import Decimal

from wb_unit_economics.contracts import AccountOrgMapping, TaxProfile, VatMode


def default_account_org_mapping(client_id: str) -> list[AccountOrgMapping]:
    return [
        AccountOrgMapping(
            client_id=client_id,
            seller_account_id="WB_ACCOUNT_1",
            organization_id="1C_ORG_1",
            seller_account_name="WB cabinet 1",
            organization_name="1C organization 1",
        ),
        AccountOrgMapping(
            client_id=client_id,
            seller_account_id="WB_ACCOUNT_2",
            organization_id="1C_ORG_2",
            seller_account_name="WB cabinet 2",
            organization_name="1C organization 2",
        ),
    ]


def default_tax_profiles(client_id: str) -> list[TaxProfile]:
    return [
        TaxProfile(
            client_id=client_id,
            organization_id="1C_ORG_1",
            tax_system="legacy_mvp",
            vat_rate=Decimal("5"),
            vat_mode=VatMode.INCLUDED,
            revenue_tax_rate=Decimal("0.01"),
            source="legacy-default",
        ),
        TaxProfile(
            client_id=client_id,
            organization_id="1C_ORG_2",
            tax_system="legacy_mvp",
            vat_rate=Decimal("5"),
            vat_mode=VatMode.INCLUDED,
            revenue_tax_rate=Decimal("0.01"),
            source="legacy-default",
        ),
    ]
