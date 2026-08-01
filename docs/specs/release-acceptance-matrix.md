---
spec_id: "release-acceptance-matrix"
title: "Release acceptance matrix"
doc_type: spec
domain: "project-governance"
status: implemented
owner: "engineering"
audience: ["engineering", "operations", "analytics"]
source_of_truth: false
related_specs:
  - docs/specs/web-cabinet-runtime-contours.md
  - docs/specs/wb-unit-economics-source-refresh-hardening-provider-registry.md
  - docs/specs/wb-unit-economics-db-first-report-marts.md
related_code:
  - config/acceptance/v2.63.yml
  - scripts/validate_acceptance_matrix.py
  - .github/workflows/ci.yml
related_tests:
  - tests/test_acceptance_matrix.py
  - tests/test_ci_workflow.py
updated_at: "2026-08-01"
---

# Goal

Сделать release acceptance воспроизводимым: связать критерии канонических
спецификаций с конкретными CI, командами и датированными operational evidence,
не помещая в Git секреты, raw client data или сгенерированные отчёты.

# Boundaries

Матрица является внутренним governance-контрактом. Она не меняет HTTP API,
схему БД, формулы, источники WB/1С или read-only границы интеграций. Live-статус
нельзя выводить из кода или недатированного сообщения: production evidence
должно быть собрано в указанном окружении и привязано к полному Git SHA.

# Contract

Версионированный YAML имеет `schema_version`, `release`, `updated_at` и список
`criteria`. Критерий содержит `scope`, `spec_id`, стабильный `criterion_id`,
`required`, роль `owner`, `status` и непустой список `evidence`.

Evidence содержит тип, `check_id`, ожидаемый и наблюдаемый результат, полный Git
SHA, окружение, RFC3339 timestamp и ссылку. Для `pending` фактические поля могут
быть `null`; `passed`, `failed` и `blocked` всегда требуют датированного
фактического результата. Обязательный критерий считается закрытым только в
статусе `passed`.

# Validation

Валидатор проверяет YAML-схему, enum, дубли ID, полные SHA, timezone timestamp,
наличие спецификации и criterion ID, а также существование локального test или
command target. GitHub CI и PR используют строгие идентификаторы, а runbook
observation обязан ссылаться на версионированный документ.

Если связанная каноническая спецификация имеет статус `implemented`, все её
обязательные критерии в матрице должны быть `passed`. Статусы `draft` и
`accepted` могут иметь открытые критерии, которые остаются явными blockers.

# Rollout And Rollback

Матрица и валидатор входят в blocking job `quality`. Изменение не требует
runtime deployment. Rollback выполняется обычным revert governance-коммита;
historical evidence не переписывается, а исправляется аддитивной записью.

# Acceptance Criteria

- Matrix v2.63 проходит новый валидатор локально и в CI.
- Неизвестные spec/criterion/check IDs и неполное evidence отклоняются.
- `implemented` с открытым обязательным критерием отклоняется.
- Pending production checks не выдаются за фактически выполненные.
- Матрица и runbooks не содержат secrets, raw payloads и generated reports.

# Test Plan

- Положительная проверка repository matrix.
- Негативные проверки дублей, неизвестных ID, отсутствующих команд/тестов,
  неверных SHA/timestamp и неполного evidence.
- Contract test подтверждает наличие валидатора в GitHub `quality`.

# Changelog

- 2026-08-01: implemented schema v1, v2.63 matrix, cross-spec criterion checks
  and blocking GitHub quality validation.
