# offonika

Safe source package for the 1C extension
`offonika`.

The extension adds only one read-only HTTP service for exporting marketplace to
1C mapping from an existing `ИС_Маркетплейс` installation. It does not store
secrets, does not create data tables, and does not write to 1C objects.

## Package

- extension name: `offonika`;
- human name: `offonika: экспорт сопоставления маркетплейсов и 1С`;
- version: `0.2.0`;
- source root: `src/`;
- delivery artifact after 1C build:
  `offonika_0.2.0.cfe`.

Do not commit a customer-built `.cfe` file if it contains customer parameters or
was built in a customer base.

## Metadata

The source package contains only:

- `Configuration.xml`;
- `HTTPServices/WBUnitEconomics.xml`;
- `HTTPServices/WBUnitEconomics/Ext/Module.bsl`;
- `Roles/offonika_ТолькоЧтение.xml`;
- `Roles/offonika_ТолькоЧтение/Ext/Rights.xml`.

The extension must not add catalogs, registers, documents, constants, scheduled
jobs, UI forms, exchange plans, or background tasks.

## Build Notes

Build and syntax check this package in 1C Designer or 1C:EDT against a test
`1С:УНФ` base that already has the vendor extension `ИС_Маркетплейс` installed.

The local Linux workspace has no 1C Designer/EDT runtime, so the `.cfe` binary is
not generated here.

Before delivery, check:

- extension version is `0.2.0`;
- HTTP service root is `/hs/wb-unit-economics/v1`;
- methods are only `GET /health` and `GET /mapping`;
- `GET /mapping` without parameters returns WB mapping;
- `GET /mapping?marketplace=ozon&limit=10` returns Ozon mapping from
  `ИС_Ozon_СоответствиеХарактеристик`;
- service user has no insert, update, delete, post, or administrative rights;
- `GET /mapping?limit=10` returns only the fields from
  `docs/specs/onec-marketplace-mapping-http-service.md`;
- response contains no tokens, passwords, profile settings, raw WB payloads, or
  raw Ozon API payloads.
