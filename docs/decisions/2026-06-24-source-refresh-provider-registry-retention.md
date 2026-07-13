---
title: "Provider registry and source refresh retention"
doc_type: decision
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: accepted
source_of_truth: true
truth_scope: source-refresh
truth_priority: 80
updated_at: "2026-07-13"
---

# Context

Кабинет уже хранит tenant-level read-only integrations и lineage для
`source_refresh`, но провайдеры WB/1C были зашиты в repository, live-check и UI.
Перед добавлением новых сервисов это создавало риск копирования условий и
разных правил ролей.

Также scheduled refresh начал упираться в эксплуатационные ограничения: мало
места под raw snapshots, конфликтующие запуски и неочевидные причины failed
status.

# Decision

- Read-only провайдеры описываются в одном внутреннем provider registry.
- `GET /api/integrations` возвращает metadata провайдеров вместе с прежним
  `items`.
- `source_refresh` получает явные blocked statuses:
  `blocked_low_disk`, `blocked_active_refresh`.
- Raw snapshot cleanup делается отдельным CLI и только через явный `--apply`.
- Новые провайдеры можно сохранять и проверять read-only, но расчет требует
  отдельного accepted spec для collector, lineage и формул.

# Consequences

Плюсы:

- добавление нового read-only провайдера начинается с registry, а не с правок в
  нескольких слоях;
- scheduled refresh лучше объясняет, почему не стартовал;
- cleanup raw snapshots становится воспроизводимой операцией.

Ограничения:

- registry не означает автоматическое включение провайдера в расчет;
- retention policy защищает только известные snapshot directories и БД-ссылки;
- live timers все равно требуют отдельной операционной проверки после rollout.
