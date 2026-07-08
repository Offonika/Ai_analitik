# Changelog

## 0.2.0 - 2026-07-07

- Added read-only Ozon mapping mode:
  `GET /mapping?marketplace=ozon`.
- Reads only `ИС_Ozon_СоответствиеХарактеристик`,
  `ИС_Ozon_Номенклатура`, standard 1C nomenclature and characteristics.
- Kept WB `/mapping` behavior backward compatible.
- Kept the package free of Ozon/WB tokens, profile settings, raw marketplace
  payloads, and writes to 1C.

## 0.1.0 - 2026-07-06

- Added first safe source package for `offonika`.
- Added read-only HTTP service `WBUnitEconomics` with `GET /health` and
  `GET /mapping`.
- Added minimal read-only role source
  `offonika_ТолькоЧтение`.
- Kept the package free of customer data, runtime URLs, passwords, tokens, and
  generated `.cfe` binaries.
