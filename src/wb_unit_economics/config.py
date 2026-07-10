from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import date
from decimal import Decimal
from typing import Any

from wb_unit_economics.contracts import (
    AccountOrgMapping,
    TaxProfile,
    VatDeductionMode,
    VatMode,
)

_TAX_SYSTEM_KEYS = ("СистемаНалогообложения", "tax_system", "taxSystem")
_VAT_RATE_KEYS = ("СтавкаНДС", "vat_rate", "vatRate")
_VAT_MODE_KEYS = ("РежимНДС", "vat_mode", "vatMode")
_VAT_DEDUCTION_MODE_KEYS = (
    "РежимВычетаНДС",
    "vat_deduction_mode",
    "vatDeductionMode",
)
_REVENUE_TAX_RATE_KEYS = (
    "СтавкаНалогаСВыручки",
    "revenue_tax_rate",
    "revenueTaxRate",
)


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


def tax_profiles_from_account_org_mapping(
    client_id: str,
    account_org_mapping: list[AccountOrgMapping],
    *,
    onec_organization_rows: Iterable[Mapping[str, Any]] | None = None,
    special_tax_mode_rows: Iterable[Mapping[str, Any]] | None = None,
) -> list[TaxProfile]:
    onec_organizations = _index_onec_organizations(onec_organization_rows or ())
    special_tax_modes = _index_special_tax_modes(special_tax_mode_rows or ())
    profiles: list[TaxProfile] = []
    for item in account_org_mapping:
        onec_profile = _tax_profile_from_onec_settings(
            client_id,
            item,
            onec_organizations.get(item.organization_id),
            special_tax_modes.get(item.organization_id, []),
        )
        if onec_profile is not None:
            profiles.append(onec_profile)
    return profiles


def tax_profile_source_diagnostic(
    organization_id: str,
    *,
    organization: Mapping[str, Any] | None,
    special_tax_mode_rows: Iterable[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Describe which authoritative tax fields 1C actually published.

    ``ВидСтавкиНДСПоУмолчанию`` and ``НДСВключатьВСтоимость`` are retained as
    source hints for staff diagnostics only. They must never be interpreted as
    evidence of ОСНО/УСН or of the right to deduct input VAT.
    """

    relevant_notices = _index_special_tax_modes(special_tax_mode_rows).get(
        organization_id, []
    )
    candidates = [
        row
        for row in sorted(
            relevant_notices, key=_special_tax_mode_sort_key, reverse=True
        )
        if "усн" in _text(row.get("ВидУведомления")).casefold()
    ]
    if organization is not None:
        candidates.append(organization)
    candidate = next(
        (row for row in candidates if _first_text(row, *_TAX_SYSTEM_KEYS)),
        organization,
    )
    candidate = candidate or {}
    published = {
        "taxSystem": bool(_first_text(candidate, *_TAX_SYSTEM_KEYS)),
        "vatRate": _decimal_from_row(candidate, *_VAT_RATE_KEYS) is not None,
        "vatMode": bool(_first_text(candidate, *_VAT_MODE_KEYS)),
        "vatDeductionMode": bool(_first_text(candidate, *_VAT_DEDUCTION_MODE_KEYS)),
        "revenueTaxRate": (
            _decimal_from_row(candidate, *_REVENUE_TAX_RATE_KEYS) is not None
        ),
    }
    missing = [name for name, is_published in published.items() if not is_published]
    deduction_mode = _vat_deduction_mode_from_row(candidate)
    if organization is None:
        status = "missing_organization"
        message = "Карточка связанной организации не найдена в выгрузке 1С."
    elif missing:
        status = "missing_authoritative_fields"
        message = (
            "Карточка организации получена из 1С, но OData не публикует полный "
            "набор налоговых реквизитов."
        )
    elif deduction_mode is VatDeductionMode.UNKNOWN:
        status = "unconfirmed"
        message = "Налоговые реквизиты получены, но право на вычет не подтверждено."
    else:
        status = "ready"
        message = "Налоговые реквизиты организации получены из 1С."

    organization_payload = organization or {}
    return {
        "status": status,
        "message": message,
        "publishedFields": published,
        "missingFields": missing,
        "specialRegimeNoticeCount": len(relevant_notices),
        "oneCHints": {
            "defaultVatRateKind": _first_text(
                organization_payload, "ВидСтавкиНДСПоУмолчанию"
            )
            or None,
            "vatIncludedInCost": _optional_bool(
                organization_payload.get("НДСВключатьВСтоимость")
            ),
            "authoritativeForTaxSystem": False,
        },
    }


def _tax_profile_from_onec_settings(
    client_id: str,
    item: AccountOrgMapping,
    organization: Mapping[str, Any] | None,
    special_tax_modes: list[Mapping[str, Any]],
) -> TaxProfile | None:
    special_tax_profile = _tax_profile_from_special_tax_modes(
        client_id, item.organization_id, special_tax_modes
    )
    if special_tax_profile is not None:
        return special_tax_profile
    if organization is None:
        return None
    return _explicit_tax_profile(
        client_id,
        item.organization_id,
        organization,
        source="Catalog_Организации",
    )


def _tax_profile_from_special_tax_modes(
    client_id: str,
    organization_id: str,
    rows: list[Mapping[str, Any]],
) -> TaxProfile | None:
    for row in sorted(rows, key=_special_tax_mode_sort_key, reverse=True):
        notice_kind = _text(row.get("ВидУведомления")).casefold()
        if not notice_kind or "усн" not in notice_kind:
            continue
        if any(marker in notice_kind for marker in ("отказ", "утрат", "прекращ")):
            return None
        return _explicit_tax_profile(
            client_id,
            organization_id,
            row,
            valid_from=_date_from_value(row.get("ДатаПодписи") or row.get("Date")),
            source="Document_УведомлениеОСпецрежимахНалогообложения",
        )
    return None


def _explicit_tax_profile(
    client_id: str,
    organization_id: str,
    row: Mapping[str, Any],
    *,
    valid_from: date | None = None,
    source: str,
) -> TaxProfile | None:
    tax_system = _first_text(row, *_TAX_SYSTEM_KEYS)
    if not tax_system:
        return None
    vat_rate = _decimal_from_row(row, *_VAT_RATE_KEYS)
    revenue_tax_rate = _decimal_from_row(row, *_REVENUE_TAX_RATE_KEYS)
    if vat_rate is None or revenue_tax_rate is None:
        return None
    vat_mode = _vat_mode_from_row(row, vat_rate=vat_rate)
    vat_deduction_mode = _vat_deduction_mode_from_row(row)
    return TaxProfile(
        client_id=client_id,
        organization_id=organization_id,
        tax_system=tax_system,
        vat_rate=vat_rate,
        vat_mode=vat_mode,
        vat_deduction_mode=vat_deduction_mode,
        revenue_tax_rate=revenue_tax_rate,
        income_tax_kind=_first_text(row, "ВидНалогаНаДоход", "income_tax_kind"),
        valid_from=valid_from
        or _date_from_value(row.get("ДатаНачала") or row.get("valid_from")),
        valid_to=_date_from_value(row.get("ДатаОкончания") or row.get("valid_to")),
        source=source,
    )


def _vat_mode_from_row(row: Mapping[str, Any], *, vat_rate: Decimal) -> VatMode:
    value = _first_text(row, *_VAT_MODE_KEYS).casefold()
    if value in {"included", "включен", "включено", "внутри"}:
        return VatMode.INCLUDED
    if value in {"excluded", "сверху", "не включен", "не включено"}:
        return VatMode.EXCLUDED
    if value in {"none", "без ндс", "не облагается"} or vat_rate == 0:
        return VatMode.NONE
    return VatMode.INCLUDED


def _vat_deduction_mode_from_row(row: Mapping[str, Any]) -> VatDeductionMode:
    value = _first_text(row, *_VAT_DEDUCTION_MODE_KEYS).casefold()
    aliases = {
        "allowed": VatDeductionMode.ALLOWED,
        "разрешен": VatDeductionMode.ALLOWED,
        "разрешено": VatDeductionMode.ALLOWED,
        "not_allowed": VatDeductionMode.NOT_ALLOWED,
        "не разрешен": VatDeductionMode.NOT_ALLOWED,
        "не разрешено": VatDeductionMode.NOT_ALLOWED,
        "not_applicable": VatDeductionMode.NOT_APPLICABLE,
        "не применимо": VatDeductionMode.NOT_APPLICABLE,
        "unknown": VatDeductionMode.UNKNOWN,
        "неизвестно": VatDeductionMode.UNKNOWN,
    }
    return aliases.get(value, VatDeductionMode.UNKNOWN)


def _decimal_from_row(row: Mapping[str, Any], *keys: str) -> Decimal | None:
    for key in keys:
        value = row.get(key)
        if value in (None, ""):
            continue
        try:
            return Decimal(str(value).replace(",", "."))
        except (ValueError, ArithmeticError):
            return None
    return None


def _first_text(row: Mapping[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(row.get(key))
        if value:
            return value
    return ""


def _optional_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    if text in {"true", "1", "да"}:
        return True
    if text in {"false", "0", "нет"}:
        return False
    return None


def _index_onec_organizations(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        ref_key = _text(row.get("Ref_Key"))
        if ref_key:
            result[ref_key] = row
    return result


def _index_special_tax_modes(
    rows: Iterable[Mapping[str, Any]],
) -> dict[str, list[Mapping[str, Any]]]:
    result: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        if bool(row.get("DeletionMark")) or row.get("Posted") is False:
            continue
        organization_id = _text(row.get("Организация_Key"))
        if organization_id:
            result.setdefault(organization_id, []).append(row)
    return result


def _special_tax_mode_sort_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return (_text(row.get("ДатаПодписи") or row.get("Date")), _text(row.get("Ref_Key")))


def _date_from_value(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
