---
title: "Single heavy slot and realistic memory envelope"
doc_type: decision
domain: "marketplace-analytics"
audience: ["engineering", "operations"]
status: accepted
source_of_truth: true
truth_scope: source-refresh
truth_priority: 90
updated_at: "2026-08-08"
---

# Context

Scalable pipeline закрепил heavy slot с `MemoryHigh=1.5G`, `MemoryMax=2G` и
`MemorySwapMax=0`, а второй heavy slot был отложен до performance-canary.
Frozen-source canary 08.08.2026 выполнен в test на снимке
`full-20260805-093650` без внешних вызовов и этот бюджет не подтвердил.

На production объеме одного клиента (`740 706` строк WB Finance) стадии дают
`peakMemoryBytes` `1 769 758 720` для `materialize_facts` и `1 902 358 528` для
`build_report`. Под спековыми лимитами `build_report` не завершается: прогон
уперся в `RuntimeMaxSec` через `2h 52m`, израсходовав `1m 13s` CPU. Отношение
CPU к wall-clock примерно `1:141` показывает reclaim-трэшинг, а не медленный
расчет: при запрете swap ядро циклически вытесняет и перечитывает рабочий
набор. Тот же расчет при `MemoryHigh=3G` занял `1m 43s` и не использовал swap.

Пара «лимит ниже рабочего набора» плюс «swap запрещен» не деградирует
производительность плавно, а останавливает прогресс. Поднимать `MemorySwapMax`
вместо лимита неприемлемо: swap на этом сервере уже используется, а спек
требует, чтобы PostgreSQL и web не свопились.

Полный прогон одного клиента занимает около `7` минут (`5m 17s` плюс
`1m 43s`). Последовательная обработка `20` клиентов одним heavy slot
укладывается примерно в `2.5` часа, что помещается в weekly-окно и не требует
второго слота.

# Decision

- Heavy slot остается один. Требование включить `dispatcher@1/@2` после
  performance-canary снимается: канарейка показала, что пропускной способности
  одного слота достаточно для `20` клиентов в weekly-окне.
- Бюджет heavy slot приводится к измеренному: `MemoryHigh=2560M`,
  `MemoryMax=3G`, `MemorySwapMax=0`. Запас над наибольшим измеренным пиком
  (`1.81G`) составляет около `40%` и покрывает рост объема одного клиента.
- Collector slots и общий `shumeiko-source-refresh.slice` не меняются:
  `768M/1G` на collector и `5G` на slice. Один heavy `3G` плюс два collector
  `1G` остаются внутри envelope.
- `MemorySwapMax=0` сохраняется. Канарейка при `MemoryHigh=3G` не
  использовала swap, поэтому запрет остается корректной защитой PostgreSQL и
  web, как только лимит перестает быть заведомо недостаточным.
- Лимит heavy обязан оставаться выше измеренного пика. Понижение лимита без
  нового frozen-source canary запрещено.
- Evidence для лимита берется из `peakMemoryBytes` в
  `source_refresh_stage_events` и `anon` из `memory.stat`. cgroup `MemoryPeak`
  из `systemd-run` включает page cache, на этой задаче завышает результат почти
  вдвое и доказательством не является.

# Consequences

- Rollout перестает зависеть от оптимизации heavy стадий: путь к production
  promotion открыт, а оптимизация памяти становится отдельной необязательной
  работой.
- Пиковое потребление pipeline растет с `2G` до `3G` на один heavy slot. При
  `11` ГБ RAM сервера и неизменном slice `5G` это не создает нового риска для
  PostgreSQL и web.
- Параллельная обработка двух клиентов остается недоступной. Если weekly-окно
  перестанет вмещать `20` клиентов, решение пересматривается отдельным ADR
  вместе с оценкой памяти двух одновременных heavy стадий.
- Если оптимизация впоследствии снизит рабочий набор ниже `1.5G`, лимиты можно
  вернуть, но только с новым frozen-source canary в качестве доказательства.
