from __future__ import annotations

import re
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
_ZERO_GUID = "00000000-0000-0000-0000-000000000000"
_OSNO_2026_START = date(2026, 1, 1)


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
    tax_kind_rows: Iterable[Mapping[str, Any]] | None = None,
    tax_accrual_rows: Iterable[Mapping[str, Any]] | None = None,
    tax_accrual_line_rows: Iterable[Mapping[str, Any]] | None = None,
    vat_sales_rows: Iterable[Mapping[str, Any]] | None = None,
    rate_anchors: Iterable[TaxProfile] | None = None,
    calculation_date: date | None = None,
    special_tax_source_complete: bool = False,
) -> list[TaxProfile]:
    onec_organizations = _index_onec_organizations(onec_organization_rows or ())
    special_tax_modes = _index_special_tax_modes(special_tax_mode_rows or ())
    tax_kinds = list(tax_kind_rows or ())
    tax_accruals = list(tax_accrual_rows or ())
    tax_accrual_lines = list(tax_accrual_line_rows or ())
    vat_sales = list(vat_sales_rows or ())
    anchors = {item.organization_id: item for item in rate_anchors or ()}
    profiles: list[TaxProfile] = []
    for item in account_org_mapping:
        onec_profile = _tax_profile_from_onec_settings(
            client_id,
            item,
            onec_organizations.get(item.organization_id),
            special_tax_modes.get(item.organization_id, []),
            tax_kind_rows=tax_kinds,
            tax_accrual_rows=tax_accruals,
            tax_accrual_line_rows=tax_accrual_lines,
            vat_sales_rows=vat_sales,
            rate_anchor=anchors.get(item.organization_id),
            calculation_date=calculation_date,
            special_tax_source_complete=special_tax_source_complete,
        )
        if onec_profile is not None:
            profiles.append(onec_profile)
    return profiles


def tax_profile_source_diagnostic(
    organization_id: str,
    *,
    organization: Mapping[str, Any] | None,
    special_tax_mode_rows: Iterable[Mapping[str, Any]] = (),
    tax_kind_rows: Iterable[Mapping[str, Any]] = (),
    tax_accrual_rows: Iterable[Mapping[str, Any]] = (),
    tax_accrual_line_rows: Iterable[Mapping[str, Any]] = (),
    vat_sales_rows: Iterable[Mapping[str, Any]] = (),
    rate_anchor: TaxProfile | None = None,
    calculation_date: date | None = None,
    special_tax_source_complete: bool = False,
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
    accounting_profile, accounting_evidence = _tax_profile_from_accounting_evidence(
        "diagnostic",
        organization_id,
        organization,
        tax_kind_rows=tax_kind_rows,
        tax_accrual_rows=tax_accrual_rows,
        tax_accrual_line_rows=tax_accrual_line_rows,
        vat_sales_rows=vat_sales_rows,
        rate_anchor=rate_anchor,
        calculation_date=calculation_date,
    )
    osno_profile = (
        _derived_osno_profile_from_organization(
            "diagnostic",
            organization_id,
            organization,
            relevant_notices,
            calculation_date=calculation_date,
            special_tax_source_complete=special_tax_source_complete,
        )
        if organization is not None
        else None
    )
    derived_profile = accounting_profile or osno_profile
    published = {
        "taxSystem": bool(_first_text(candidate, *_TAX_SYSTEM_KEYS))
        or bool(accounting_evidence.get("taxSystem")),
        "vatRate": _decimal_from_row(candidate, *_VAT_RATE_KEYS) is not None
        or accounting_evidence.get("vatRate") is not None,
        "vatMode": bool(_first_text(candidate, *_VAT_MODE_KEYS))
        or bool(accounting_evidence.get("vatMode")),
        "vatDeductionMode": bool(_first_text(candidate, *_VAT_DEDUCTION_MODE_KEYS))
        or bool(accounting_evidence.get("vatDeductionMode")),
        "revenueTaxRate": (
            _decimal_from_row(candidate, *_REVENUE_TAX_RATE_KEYS) is not None
        )
        or accounting_evidence.get("revenueTaxRate") is not None,
    }
    missing = (
        []
        if derived_profile is not None
        else [name for name, is_published in published.items() if not is_published]
    )
    deduction_mode = _vat_deduction_mode_from_row(candidate)
    if organization is None:
        status = "missing_organization"
        message = "Карточка связанной организации не найдена в выгрузке 1С."
    elif accounting_profile is not None:
        status = "ready"
        message = (
            "Профиль УСН получен из проведенных начислений налогов, книги "
            "продаж 1С и аудируемого якоря ставки."
        )
    elif osno_profile is not None:
        status = "ready"
        message = (
            "Профиль ОСНО получен из учетных признаков карточки организации 1С "
            "и полного источника уведомлений о спецрежимах."
        )
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
            "authoritativeForTaxSystem": bool(
                accounting_profile is not None or osno_profile is not None
            ),
        },
        "derivedProfile": (
            {
                "taxSystem": derived_profile.tax_system,
                "vatRate": str(derived_profile.vat_rate),
                "vatMode": derived_profile.vat_mode.value,
                "vatDeductionMode": derived_profile.vat_deduction_mode.value,
                "source": derived_profile.source,
            }
            if derived_profile is not None
            else None
        ),
        "accountingEvidence": accounting_evidence,
    }


def _tax_profile_from_onec_settings(
    client_id: str,
    item: AccountOrgMapping,
    organization: Mapping[str, Any] | None,
    special_tax_modes: list[Mapping[str, Any]],
    tax_kind_rows: Iterable[Mapping[str, Any]],
    tax_accrual_rows: Iterable[Mapping[str, Any]],
    tax_accrual_line_rows: Iterable[Mapping[str, Any]],
    vat_sales_rows: Iterable[Mapping[str, Any]],
    rate_anchor: TaxProfile | None,
    *,
    calculation_date: date | None,
    special_tax_source_complete: bool,
) -> TaxProfile | None:
    special_tax_profile = _tax_profile_from_special_tax_modes(
        client_id, item.organization_id, special_tax_modes
    )
    if special_tax_profile is not None:
        return special_tax_profile
    if organization is None:
        return None
    explicit_profile = _explicit_tax_profile(
        client_id,
        item.organization_id,
        organization,
        source="Catalog_Организации",
    )
    if explicit_profile is not None:
        return explicit_profile
    accounting_profile, _evidence = _tax_profile_from_accounting_evidence(
        client_id,
        item.organization_id,
        organization,
        tax_kind_rows=tax_kind_rows,
        tax_accrual_rows=tax_accrual_rows,
        tax_accrual_line_rows=tax_accrual_line_rows,
        vat_sales_rows=vat_sales_rows,
        rate_anchor=rate_anchor,
        calculation_date=calculation_date,
    )
    if accounting_profile is not None:
        return accounting_profile
    return _derived_osno_profile_from_organization(
        client_id,
        item.organization_id,
        organization,
        special_tax_modes,
        calculation_date=calculation_date,
        special_tax_source_complete=special_tax_source_complete,
    )


def _tax_profile_from_accounting_evidence(
    client_id: str,
    organization_id: str,
    organization: Mapping[str, Any] | None,
    *,
    tax_kind_rows: Iterable[Mapping[str, Any]],
    tax_accrual_rows: Iterable[Mapping[str, Any]],
    tax_accrual_line_rows: Iterable[Mapping[str, Any]],
    vat_sales_rows: Iterable[Mapping[str, Any]],
    rate_anchor: TaxProfile | None,
    calculation_date: date | None,
) -> tuple[TaxProfile | None, dict[str, Any]]:
    tax_kind_by_id = {
        _text(row.get("Ref_Key")): _text(row.get("Description"))
        for row in tax_kind_rows
        if _text(row.get("Ref_Key")) and not bool(row.get("DeletionMark"))
    }
    accrual_refs = {
        _text(row.get("Ref_Key"))
        for row in tax_accrual_rows
        if _text(row.get("Организация_Key")) == organization_id
        and bool(row.get("Posted"))
        and not bool(row.get("DeletionMark"))
        and _row_date_matches_calculation(
            row,
            calculation_date=calculation_date,
            keys=("Date",),
        )
    }
    tax_names = {
        tax_kind_by_id.get(_text(row.get("ВидНалога_Key")), "")
        for row in tax_accrual_line_rows
        if _text(row.get("Ref_Key")) in accrual_refs
    }
    tax_system = _tax_system_from_accounting_tax_names(tax_names)

    vat_rows: list[tuple[date | None, Decimal]] = []
    for row in vat_sales_rows:
        if (
            _text(row.get("Организация_Key")) != organization_id
            or row.get("Active") is False
            or not _row_date_matches_calculation(
                row,
                calculation_date=calculation_date,
                keys=("Period",),
            )
        ):
            continue
        vat_amount = _decimal_from_row(row, "НДС")
        if vat_amount is not None and vat_amount == 0:
            continue
        vat_rate = _vat_rate_from_accounting_label(row.get("СтавкаНДС"))
        if vat_rate is not None and vat_rate > 0:
            vat_rows.append((_date_from_value(row.get("Period")), vat_rate))
    vat_rates = {item[1] for item in vat_rows}
    vat_rate = next(iter(vat_rates)) if len(vat_rates) == 1 else None

    vat_mode: VatMode | None = None
    vat_deduction_mode: VatDeductionMode | None = None
    if tax_system == "УСН Доходы" and vat_rate in {Decimal("5"), Decimal("7")}:
        vat_mode = VatMode.INCLUDED
        vat_deduction_mode = VatDeductionMode.NOT_ALLOWED

    anchor_matches = _rate_anchor_matches(
        rate_anchor,
        tax_system=tax_system,
        vat_rate=vat_rate,
        calculation_date=calculation_date,
    )
    revenue_tax_rate = (
        rate_anchor.revenue_tax_rate
        if rate_anchor is not None and anchor_matches
        else None
    )
    evidence = {
        "taxSystem": tax_system,
        "vatRate": str(vat_rate) if vat_rate is not None else None,
        "vatMode": vat_mode.value if vat_mode is not None else None,
        "vatDeductionMode": (
            vat_deduction_mode.value if vat_deduction_mode is not None else None
        ),
        "revenueTaxRate": (
            str(revenue_tax_rate) if revenue_tax_rate is not None else None
        ),
        "taxAccrualCount": len(accrual_refs),
        "vatSalesEntryCount": len(vat_rows),
        "rateAnchorMatched": anchor_matches,
        "rateAnchorConflict": bool(rate_anchor is not None and not anchor_matches),
    }
    if (
        tax_system is None
        or vat_rate is None
        or vat_mode is None
        or vat_deduction_mode is None
        or revenue_tax_rate is None
    ):
        return None, evidence
    valid_from = (
        rate_anchor.valid_from
        if rate_anchor is not None and rate_anchor.valid_from is not None
        else date(calculation_date.year, 1, 1)
        if calculation_date is not None
        else None
    )
    return (
        TaxProfile(
            client_id=client_id,
            organization_id=organization_id,
            tax_system=tax_system,
            vat_rate=vat_rate,
            vat_mode=vat_mode,
            vat_deduction_mode=vat_deduction_mode,
            revenue_tax_rate=revenue_tax_rate,
            income_tax_kind=rate_anchor.income_tax_kind if rate_anchor else "",
            valid_from=valid_from,
            valid_to=rate_anchor.valid_to if rate_anchor else None,
            source="1C:tax_accruals+vat_sales+audited_rate",
            rate_basis_kind=rate_anchor.rate_basis_kind if rate_anchor else "",
            basis_document=rate_anchor.basis_document if rate_anchor else "",
            confirmed_by=rate_anchor.confirmed_by if rate_anchor else "",
            source_object_ids=sorted(
                {
                    *(rate_anchor.source_object_ids if rate_anchor else []),
                    *accrual_refs,
                }
            ),
        ),
        evidence,
    )


def _tax_system_from_accounting_tax_names(tax_names: Iterable[str]) -> str | None:
    normalized = [
        re.sub(r"[^a-zа-я0-9]+", " ", item.casefold()).strip()
        for item in tax_names
    ]
    usn_income = any(
        "усн" in item and "доход" in item and "расход" not in item
        for item in normalized
    )
    usn_income_expense = any(
        "усн" in item and "доход" in item and "расход" in item
        for item in normalized
    )
    if usn_income and not usn_income_expense:
        return "УСН Доходы"
    return None


def _vat_rate_from_accounting_label(value: Any) -> Decimal | None:
    label = _text(value).casefold().replace(" ", "")
    if not label or "безндс" in label or "необлаг" in label:
        return None
    match = re.search(r"ндс(\d+(?:[.,]\d+)?)", label)
    if match is None:
        return None
    try:
        return Decimal(match.group(1).replace(",", "."))
    except (ValueError, ArithmeticError):
        return None


def _row_date_matches_calculation(
    row: Mapping[str, Any],
    *,
    calculation_date: date | None,
    keys: tuple[str, ...],
) -> bool:
    if calculation_date is None:
        return True
    row_date = next(
        (_date_from_value(row.get(key)) for key in keys if row.get(key)),
        None,
    )
    return bool(
        row_date is not None
        and row_date.year == calculation_date.year
        and row_date <= calculation_date
    )


def _rate_anchor_matches(
    anchor: TaxProfile | None,
    *,
    tax_system: str | None,
    vat_rate: Decimal | None,
    calculation_date: date | None,
) -> bool:
    if (
        anchor is None
        or tax_system != "УСН Доходы"
        or _tax_system_from_accounting_tax_names([anchor.tax_system]) != tax_system
        or anchor.revenue_tax_rate <= 0
    ):
        return False
    if anchor.vat_rate > 0 and vat_rate is not None and anchor.vat_rate != vat_rate:
        return False
    if calculation_date is not None:
        if anchor.valid_from is not None and calculation_date < anchor.valid_from:
            return False
        if anchor.valid_to is not None and calculation_date > anchor.valid_to:
            return False
    return True


def _derived_osno_profile_from_organization(
    client_id: str,
    organization_id: str,
    organization: Mapping[str, Any],
    special_tax_modes: list[Mapping[str, Any]],
    *,
    calculation_date: date | None,
    special_tax_source_complete: bool,
) -> TaxProfile | None:
    """Derive the accepted 2026 OSNO profile from a complete 1C evidence set."""

    if (
        calculation_date is None
        or calculation_date.year != 2026
        or not special_tax_source_complete
        or special_tax_modes
    ):
        return None
    default_vat_kind = _first_text(
        organization, "ВидСтавкиНДСПоУмолчанию"
    ).casefold()
    vat_included_in_cost = _optional_bool(
        organization.get("НДСВключатьВСтоимость")
    )
    entity_kind = _first_text(
        organization, "ЮридическоеФизическоеЛицо"
    ).casefold()
    personal_funds_account = _first_text(
        organization, "СчетУчетаЛичныхСредствПредпринимателя_Key"
    )
    is_entrepreneur = (
        "физическ" in entity_kind
        and bool(personal_funds_account)
        and personal_funds_account != _ZERO_GUID
    )
    if (
        default_vat_kind not in {"общая", "общий", "основная"}
        or vat_included_in_cost is not False
        or not is_entrepreneur
    ):
        return None
    return TaxProfile(
        client_id=client_id,
        organization_id=organization_id,
        tax_system="ОСНО",
        vat_rate=Decimal("22"),
        vat_mode=VatMode.INCLUDED,
        vat_deduction_mode=VatDeductionMode.ALLOWED,
        revenue_tax_rate=Decimal("0"),
        income_tax_kind="",
        valid_from=_OSNO_2026_START,
        source="Catalog_Организации:derived_osno_2026",
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
