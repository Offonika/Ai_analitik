# CLAUDE.md

Автозагружаемая точка входа Claude Code. Правила проекта — в `AGENTS.md`,
он импортируется целиком:

@AGENTS.md

## Быстрая навигация

- Начинай с `.venv/bin/python scripts/docs_route.py --query "<задача>"`.
  Известный ключ можно передать через `--scope`, `--path` или `--contract`.
- Читай только возвращенные `ai_sections` и ищи код/тесты сначала по symbols
  из anchors. Полный manifest, index, крупный spec или source-файл без
  необходимости не загружай.
- Перед чтением неизвестного файла проверь `wc -l <path>`; крупные файлы читать
  через `rg` и диапазоны. Статический список размеров намеренно не хранится.
- Статус rollout/флагов среды проверяй по возвращенному operational runbook, а
  не по defaults в `settings.py` или статусной шапке спека. Точные числа
  сопровождай воспроизводимой командой и ревизией; вывод субагента сверяй с
  первоисточником.

## Быстрые команды

Виртуальное окружение уже создано: `.venv/bin/python`.

- Lint: `.venv/bin/python -m ruff check scripts src tests`
- Точечные тесты: `.venv/bin/python -m pytest tests/test_<area>.py -q` —
  какой файл относится к задаче, смотри в `related_tests` спека.
- Полный прогон: `.venv/bin/python -m pytest -q` (~10 минут, ~730 тестов).
- Проверки документации после изменения docs — блок «Проверки документации»
  в `docs/index.md`.
- Parity AI-карты: `.venv/bin/python scripts/docs_route.py --check-generated`.
- Публикация: `.venv/bin/python scripts/ai_git_publish.py -m "..."` — сама
  прогоняет no-secrets, git safety и docs-валидаторы; `--tests` добавляет
  полный pytest, `--no-push` — только локальный коммит, `--dry-run` — ничего
  не меняет. Check-only режима без `git add` у скрипта нет: для проверки без
  коммита запускай ruff, pytest и валидаторы по отдельности.

## Перед завершением задачи

- Изменил код — прогони ruff и релевантные тесты из `related_tests`.
- Изменил поведение, контракты или методику — обнови спек соответствующего
  `truth_scope` в том же изменении (spec-first, см. `AGENTS.md`).
- Изменил docs — прогони валидаторы документации из `docs/index.md`.
