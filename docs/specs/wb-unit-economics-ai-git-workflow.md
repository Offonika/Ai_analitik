---
spec_id: "wb-unit-economics-ai-git-workflow"
title: "AI development and documentation routing workflow"
doc_type: spec
domain: "marketplace-analytics"
status: accepted
owner: "engineering"
audience: ["engineering", "agent"]
source_of_truth: true
truth_scope: development-workflow
truth_priority: 100
related_code:
  - .github/workflows/ci.yml
  - scripts/ai_git_publish.py
  - scripts/check_git_safety.py
  - scripts/docs_route.py
  - scripts/docs_metadata.py
  - scripts/validate_docs_manifest.py
  - scripts/validate_specs.py
  - scripts/validate_no_secrets.py
  - .githooks/pre-commit
related_tests:
  - tests/test_ci_workflow.py
  - tests/test_docs_routing.py
  - tests/test_documentation_validators.py
contracts: [ai_document_route]
ai_sections:
  status: "Implementation Status"
  goal: "Goal"
  scope: "Scope"
  routing_contract: "Documentation Routing Contract"
  acceptance: "Acceptance Criteria"
  rollout: "Rollout And Rollback"
code_anchors:
  - path: scripts/docs_route.py
    symbols: ["class RouteRecord", "def find_routes", "def check_generated"]
  - path: scripts/validate_docs_manifest.py
    symbols: ["def validate_routing_metadata"]
  - path: scripts/validate_specs.py
    symbols: ["def validate_ai_sections", "def validate_anchors"]
test_anchors:
  - path: tests/test_docs_routing.py
    symbols: ["test_query_routes_report_draft_retention", "test_shared_path_lists_scopes_without_expanding_routes", "test_generated_artifacts_are_current"]
depends_on:
  - AGENTS.md
supersedes: []
rollout_required: false
updated_at: "2026-07-18"
---

# Implementation Status

Статус остается `accepted`. Git CLI, safety-check, pre-commit hook и GitHub
Actions CI реализованы. В scope также принят read-only маршрутизатор
документации, который строит компактную AI-карту из manifest и spec
frontmatter. Пока branch protection недоступен и новый routing-контракт не
прошел rollout через CI, spec не переводится в `implemented`.

# Goal

Сделать разработку с ИИ быстрой и воспроизводимой: до изменения кода агент
получает короткий маршрут `scope -> раздел spec -> символы кода -> тесты`, а
после изменения один локальный сценарий проверяет безопасность Git, создает
осмысленный snapshot-коммит и публикует его в `origin/main` или текущую рабочую
ветку.

# Scope

Входит:

- локальный Git hook перед коммитом;
- CLI для безопасного цикла `validate -> stage -> commit -> push`;
- GitHub Actions CI для pull request в `main`, push в `main` и ручного запуска;
- стабильные блокирующие job `quality` и `tests`;
- запрет публикации секретов, raw client data и generated artifacts;
- read-only поиск канонического scope по запросу, пути кода или data contract;
- компактный generated JSONL index для поиска без чтения полного manifest;
- секционные и символьные anchors в spec frontmatter;
- generated-блок `scope -> документ -> read_when` в `docs/index.md`;
- документация для ручного и автоматизированного сценария.

Не входит:

- запись во внешние WB, 1C, банк, CRM, Telegram, email или Bitrix;
- автоматический push без явного запуска пользователем или агентом;
- хранение GitHub tokens в репозитории;
- автоматическое создание pull requests;
- deployment, production migrations и включение feature flags;
- использование repository secrets или production credentials в CI;
- публикация `data/`, `reports/`, `.env` или generated Excel/CSV/ZIP.

# Documentation Routing Contract

`scripts/docs_route.py` объединяет только безопасные metadata из
`docs/manifest.yml` и frontmatter Markdown-документов. Он не читает `.env`,
`data/`, `reports/`, raw snapshots или generated client reports.

Поддерживаемые входы:

- `--query TEXT` — полнотекстовый поиск по title, summary, `read_when`,
  `search_terms`, scope, contracts, sections и зарегистрированным путям;
- `--scope SCOPE` — точный канонический документ scope;
- `--path PATH` — спеки, где путь зарегистрирован в `related_code`,
  `related_tests`, `code_anchors` или `test_anchors`;
- `--contract NAME` — спеки, которые объявляют data contract;
- `--include-supporting` и `--include-history` — явное расширение результата
  за пределы канонических текущих документов.

По умолчанию query возвращает один лучший маршрут, только среди однозначных
лидеров scope, и не включает `draft`/`superseded`. Уникальный `--path` сразу
возвращает полный маршрут. Если один путь зарегистрирован в нескольких scope,
обычный вывод содержит только компактный список всех совпавших scope и
предлагает выбрать один через `--scope`; полные маршруты раскрываются только по
явному `--verbose` или `--limit`. Компактный вывод ограничивает списки путей.
Результат всегда помечает status, canonical scope и не превращает
supporting-документ в источник правды.

Generated-файл `docs/generated/ai-routing.jsonl` содержит одну JSON-запись на
строку и полностью воспроизводится командой `--write-generated`. Команда
`--check-generated` ничего не меняет и блокирует stale JSONL или generated-блок
в `docs/index.md`.

Для канонических лидеров manifest обязательны непустые `read_when` и
`search_terms`. `ai_sections` ссылается на существующие Markdown headings.
Каждый `code_anchors`/`test_anchors` элемент содержит зарегистрированный путь и
непустые текстовые symbols, которые реально присутствуют в целевом файле.

Retrieval protocol агента:

1. Получить маршрут через `docs_route.py`, не читать весь manifest/index.
2. Прочитать frontmatter выбранного документа и список headings.
3. Прочитать только названные `ai_sections`.
4. Искать код и тесты сначала по symbols из anchors.
5. Расширять чтение до полного spec или supporting-документов только при
   межконтурном конфликте или задаче, затрагивающей весь scope.

# User Roles And Decisions

Роли:

- engineer или агент ИИ готовит изменения;
- owner проекта решает, когда запускать публикацию;
- reviewer читает историю Git, видит результат CI и может восстановить изменения
  по коммитам.

Бизнес-решение: AI-assisted development должна оставлять частые, небольшие и
проверяемые коммиты без риска утечки клиентских данных.

# Data Boundaries

Git workflow читает только рабочее дерево и Git metadata. Он не читает `.env`.
Сканер секретов пропускает локальные `data/` и `reports/`, потому что эти папки
не должны участвовать в Git-публикации.

GitHub-hosted runner получает только содержимое репозитория и стандартный
`GITHUB_TOKEN` с разрешением `contents: read`. Checkout не сохраняет credentials
в Git config. В workflow не передаются repository secrets, WB/1C/Ozon tokens или
production database URL.

Запрещено коммитить:

- `.env` и `.env.*`, кроме `.env.example`;
- `data/` и `reports/`;
- `.venv/`, caches и `__pycache__`;
- Excel/CSV/ZIP/7z и локальные SQLite/DB файлы.

# Commands

Основной сценарий:

```bash
.venv/bin/python scripts/ai_git_publish.py -m "Describe the change"
```

Только локальный коммит без push:

```bash
.venv/bin/python scripts/ai_git_publish.py --no-push -m "Describe the change"
```

С полным тестовым прогоном:

```bash
.venv/bin/python scripts/ai_git_publish.py --tests -m "Describe the change"
```

# Acceptance Criteria

- `scripts/check_git_safety.py --staged --tracked` блокирует запрещенные пути.
- Pre-commit hook запускает path safety и no-secrets checks.
- `scripts/ai_git_publish.py --dry-run` не меняет Git state.
- `scripts/ai_git_publish.py --no-push` может создать локальный коммит после
  успешных проверок.
- CI запускается для pull request в `main`, push в `main` и вручную.
- Job `quality` использует Python 3.12 и Node.js 20, запускает Ruff, JavaScript
  syntax check, документальные контракты, DOCX/OpenAPI parity, no-secrets и Git
  safety checks.
- Job `tests` запускает полный `pytest` на Python 3.12.
- `permissions` ограничены `contents: read`, а checkout использует
  `persist-credentials: false`.
- Проверка внешних ссылок видима в CI, но остается неблокирующей.
- Новый push отменяет устаревший CI run той же ветки или pull request.
- Documentation validators проходят после добавления runbook/spec.
- Existing local raw data, reports and `.env` remain ignored.
- `docs_route.py --scope development-workflow` возвращает один канонический
  документ и компактный список sections/code/tests.
- Общий `--path` перечисляет все совпавшие scope без полного раскрытия каждого
  маршрута; выбор через `--scope` возвращает один полный маршрут.
- Запрос про удаление старых черновиков отчетов маршрутизируется в
  `source-retention`, а поиск по `scripts/prune_report_drafts.py` возвращает тот
  же scope.
- Default query не возвращает `draft` и `superseded`; явные флаги позволяют их
  диагностически включить.
- Spec validation отклоняет отсутствующий heading, незарегистрированный anchor
  path и отсутствующий symbol.
- Manifest validation требует `read_when` и `search_terms` для каждого
  однозначного лидера truth scope.
- `docs_route.py --check-generated` подтверждает parity JSONL и generated-блока
  в `docs/index.md`; этот check входит в CI и AI publish workflow.
- Компактный результат не печатает содержимое документов, кода, `.env`, raw
  data или reports.

# Rollout And Rollback

Rollout:

1. Закоммитить spec, runbook, scripts, hook и `.github/workflows/ci.yml`.
2. Включить hooks path локально:
   `git config core.hooksPath .githooks`.
3. Проверить `scripts/ai_git_publish.py --dry-run`.
4. Дождаться первого успешного `quality` и `tests` в pull request.
5. Если тариф GitHub поддерживает branch protection для приватного репозитория,
   включить для `main` обязательные `quality` и `tests`.
6. До включения защиты применять ручное правило: не сливать PR, пока оба job не
   завершились успешно.

Rollback:

- отключить hook: `git config --unset core.hooksPath`;
- снять обязательные CI checks в branch protection;
- использовать обычные `git add`, `git commit`, `git push`;
- удалить workflow-файлы отдельным коммитом, если сценарий не подходит.

# Changelog

- 2026-07-18: accepted compact AI documentation routing contract with
  query/scope/path/contract lookup, generated JSONL, section/code anchors and
  stale-index checks.
- 2026-07-13: first CI run passed; private-repository branch protection was
  unavailable on the current GitHub plan.
- 2026-07-13: added read-only GitHub Actions CI contract for quality and tests.
- 2026-07-01: accepted spec for AI-assisted Git publication workflow.
