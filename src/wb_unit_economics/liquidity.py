from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

ZERO_BAND = Decimal("5")

QUALITY_SEVERITY = {
    "ОК": 0,
    "Документ WB загружен": 5,
    "Себестоимость 1С требует сверки": 20,
    "Тип отчета WB определен эвристикой": 22,
    "Нужен источник выплаты 1С": 25,
    "ОПиУ: пилотные GUID-настройки": 25,
    "Исключено": 30,
    "Документ WB не найден": 35,
    "Нет себестоимости 1С": 40,
    "Неоднозначное сопоставление": 50,
    "Нет сопоставления WB-1С": 60,
    "Расход без SKU": 70,
    "Неполный источник": 80,
    "Кабинет WB не совпадает с организацией 1С": 90,
}

GROUP_FIELDS = (
    "month",
    "organization",
    "cabinet",
    "product",
    "articleWb",
    "article1c",
    "barcode",
    "scheme",
)

SUM_FIELDS = (
    "sales",
    "returns",
    "netQty",
    "revenue",
    "cost",
    "commission",
    "storage",
    "logistics",
    "acceptance",
    "promotion",
    "penalties",
    "acquiring",
    "vat",
    "usn",
)


def aggregate_liquidity_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, ...], dict[str, Any]] = {}
    for row in rows:
        key = tuple(_text(row.get(field)) for field in GROUP_FIELDS)
        bucket = buckets.setdefault(
            key,
            {
                **{field: key[index] for index, field in enumerate(GROUP_FIELDS)},
                **{field: Decimal("0") for field in SUM_FIELDS},
                "profitBeforeTax": Decimal("0"),
                "profit": Decimal("0"),
                "profitBeforeTaxCount": 0,
                "profitCount": 0,
                "rowCount": 0,
                "nmIds": set(),
                "statuses": Counter(),
                "statusReasons": defaultdict(Counter),
                "sppStatuses": Counter(),
            },
        )
        bucket["rowCount"] += 1
        for field in SUM_FIELDS:
            bucket[field] += _decimal(row.get(field))
        profit_before_tax = _optional_decimal(row.get("profitBeforeTax"))
        if profit_before_tax is not None:
            bucket["profitBeforeTax"] += profit_before_tax
            bucket["profitBeforeTaxCount"] += 1
        profit_after_tax = _optional_decimal(row.get("profit"))
        if profit_after_tax is not None:
            bucket["profit"] += profit_after_tax
            bucket["profitCount"] += 1
        nm_id = _text(row.get("nmId"))
        if nm_id:
            bucket["nmIds"].add(nm_id)
        status = _text(row.get("status")) or "Не указан"
        bucket["statuses"][status] += 1
        reason = _text(row.get("statusReason"))
        if reason:
            bucket["statusReasons"][status][reason] += 1
        spp_status = _text(row.get("sppStatus"))
        if spp_status:
            bucket["sppStatuses"][spp_status] += 1

    result = []
    for index, bucket in enumerate(buckets.values(), start=1):
        md1 = bucket["revenue"] - bucket["cost"]
        md2 = md1 - bucket["commission"]
        md3 = md2 - bucket["storage"]
        md4 = md3 - bucket["logistics"] - bucket["acceptance"]
        md5 = md4 - bucket["promotion"]
        diagnostic_md6 = md5 - bucket["penalties"] - bucket["acquiring"]
        md6 = (
            bucket["profitBeforeTax"]
            if bucket["profitBeforeTaxCount"] == bucket["rowCount"]
            else diagnostic_md6
        )
        profit = (
            bucket["profit"]
            if bucket["profitCount"] == bucket["rowCount"]
            else md6 - bucket["vat"] - bucket["usn"]
        )
        data_status = _worst_status(bucket["statuses"])
        status_reason = _status_reason(data_status, bucket["statusReasons"])
        liquidity_status, liquidity_driver = _liquidity_status(
            bucket,
            md1=md1,
            md2=md2,
            md3=md3,
            md4=md4,
            md5=md5,
            md6=md6,
            profit=profit,
            data_status=data_status,
        )
        result.append(
            {
                "id": f"liquidity-{index}",
                "month": bucket["month"],
                "organization": bucket["organization"],
                "cabinet": bucket["cabinet"],
                "product": bucket["product"],
                "nmId": ", ".join(sorted(bucket["nmIds"])),
                "articleWb": bucket["articleWb"],
                "article1c": bucket["article1c"],
                "barcode": bucket["barcode"],
                "scheme": bucket["scheme"],
                "sales": bucket["sales"],
                "returns": bucket["returns"],
                "netQty": bucket["netQty"],
                "returnRate": _ratio(bucket["returns"], bucket["sales"]),
                "revenue": bucket["revenue"],
                "cost": bucket["cost"],
                "md1Markup": md1,
                "commission": bucket["commission"],
                "md2AfterCommission": md2,
                "storage": bucket["storage"],
                "md3AfterStorage": md3,
                "logistics": bucket["logistics"],
                "acceptance": bucket["acceptance"],
                "md4AfterLogisticsAcceptance": md4,
                "promotion": bucket["promotion"],
                "md5AfterPromotion": md5,
                "penalties": bucket["penalties"],
                "acquiring": bucket["acquiring"],
                "md6BeforeTax": md6,
                "vat": bucket["vat"],
                "usn": bucket["usn"],
                "profit": profit,
                "margin": _ratio(profit, bucket["revenue"]),
                "unitProfit": _ratio(profit, bucket["netQty"]),
                "liquidityStatus": liquidity_status,
                "liquidityDriver": liquidity_driver,
                "status": data_status,
                "statusReason": status_reason,
                "sppStatus": _combined_status(bucket["sppStatuses"]),
            }
        )
    return sorted(
        result,
        key=lambda item: (
            _decimal(item.get("profit")),
            _text(item.get("month")),
            _text(item.get("product")),
        ),
    )


def liquidity_statuses(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    return sorted(
        {
            _text(row.get("liquidityStatus"))
            for row in rows
            if _text(row.get("liquidityStatus"))
        }
    )


def liquidity_rows_payload(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    payload = []
    for row in rows:
        payload.append(
            {
                key: float(value) if isinstance(value, Decimal) else value
                for key, value in row.items()
            }
        )
    return payload


def _liquidity_status(
    bucket: Mapping[str, Any],
    *,
    md1: Decimal,
    md2: Decimal,
    md3: Decimal,
    md4: Decimal,
    md5: Decimal,
    md6: Decimal,
    profit: Decimal,
    data_status: str,
) -> tuple[str, str]:
    if data_status != "ОК":
        return "Нужна проверка данных", data_status
    if bucket["sales"] == 0 and bucket["revenue"] == 0 and _has_expenses(bucket):
        return "Только затраты - нет продаж", "Нет продаж при наличии затрат"
    if abs(profit) <= ZERO_BAND:
        return "Нулевая маржинальность", "Итог после налогов около нуля"
    if profit > 0:
        if profit <= Decimal("500"):
            return "Прибыльный до 500 руб. в месяц", "МД после налогов > 0"
        if profit <= Decimal("1000"):
            return "Прибыльный 500-1000 руб. в месяц", "МД после налогов > 500"
        if profit <= Decimal("30000"):
            return "Прибыльный 1000-30000 руб. в месяц", "МД после налогов > 1000"
        return "Прибыльный более 30000 руб. в месяц", "МД после налогов > 30000"
    checks = [
        (md1, "Убыточный: отрицательная наценка", "Выручка ниже себестоимости"),
        (md2, "Убыточный: комиссия WB", "Комиссия WB выводит МД ниже нуля"),
        (md3, "Убыточный: хранение WB", "Хранение WB выводит МД ниже нуля"),
        (
            md4,
            "Убыточный: логистика и приемка WB",
            "Логистика и приемка выводят МД ниже нуля",
        ),
        (md5, "Убыточный: продвижение WB", "Продвижение WB выводит МД ниже нуля"),
        (
            md6,
            "Убыточный: штрафы/доплаты и эквайринг",
            "Штрафы/доплаты или эквайринг выводят МД ниже нуля",
        ),
    ]
    for value, status, driver in checks:
        if value < 0:
            return status, driver
    return "Убыточный: налоги", "НДС 5% и УСН 1% выводят МД ниже нуля"


def _worst_status(statuses: Counter[str]) -> str:
    if not statuses:
        return "Не указан"
    return max(
        statuses,
        key=lambda status: (QUALITY_SEVERITY.get(status, 20), statuses[status]),
    )


def _status_reason(status: str, reasons: Mapping[str, Counter[str]]) -> str:
    status_reasons = reasons.get(status)
    if status_reasons:
        return status_reasons.most_common(1)[0][0]
    return "" if status == "ОК" else status


def _combined_status(statuses: Counter[str]) -> str:
    if not statuses:
        return ""
    if any("cashbackDiscountSum" in status for status in statuses):
        return "СПП из WB sales-reports/list cashbackDiscountSum"
    return statuses.most_common(1)[0][0]


def _has_expenses(bucket: Mapping[str, Any]) -> bool:
    return any(
        abs(bucket[field]) > 0
        for field in (
            "cost",
            "commission",
            "storage",
            "logistics",
            "acceptance",
            "promotion",
            "penalties",
            "acquiring",
            "vat",
            "usn",
        )
    )


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _decimal(value: Any) -> Decimal:
    if value is None or value == "":
        return Decimal("0")
    return Decimal(str(value))


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()
