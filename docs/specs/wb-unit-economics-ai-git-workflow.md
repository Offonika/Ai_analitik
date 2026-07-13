---
spec_id: "wb-unit-economics-ai-git-workflow"
title: "AI development Git workflow"
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
  - scripts/validate_no_secrets.py
  - .githooks/pre-commit
related_tests:
  - tests/test_ci_workflow.py
contracts: []
depends_on:
  - AGENTS.md
supersedes: []
rollout_required: false
updated_at: "2026-07-13"
---

# Implementation Status

Статус остается `accepted`. CLI, safety-check, pre-commit hook и GitHub Actions
CI реализованы, а структура CI покрыта контрактными тестами. Удаленная защита
ветки `main` должна быть включена только после первого успешного run с job
`quality` и `tests`; до проверки этой настройки spec не переводится в
`implemented`.

# Goal

Сделать разработку с ИИ быстрой и воспроизводимой: один локальный сценарий
проверяет безопасность Git, создает осмысленный snapshot-коммит и публикует его
в `origin/main` или текущую рабочую ветку.

# Scope

Входит:

- локальный Git hook перед коммитом;
- CLI для безопасного цикла `validate -> stage -> commit -> push`;
- GitHub Actions CI для pull request в `main`, push в `main` и ручного запуска;
- стабильные блокирующие job `quality` и `tests`;
- запрет публикации секретов, raw client data и generated artifacts;
- документация для ручного и автоматизированного сценария.

Не входит:

- запись во внешние WB, 1C, банк, CRM, Telegram, email или Bitrix;
- автоматический push без явного запуска пользователем или агентом;
- хранение GitHub tokens в репозитории;
- автоматическое создание pull requests;
- deployment, production migrations и включение feature flags;
- использование repository secrets или production credentials в CI;
- публикация `data/`, `reports/`, `.env` или generated Excel/CSV/ZIP.

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

# Rollout And Rollback

Rollout:

1. Закоммитить spec, runbook, scripts, hook и `.github/workflows/ci.yml`.
2. Включить hooks path локально:
   `git config core.hooksPath .githooks`.
3. Проверить `scripts/ai_git_publish.py --dry-run`.
4. Дождаться первого успешного `quality` и `tests` в pull request.
5. Включить для `main` branch protection с обязательными `quality` и `tests`.

Rollback:

- отключить hook: `git config --unset core.hooksPath`;
- снять обязательные CI checks в branch protection;
- использовать обычные `git add`, `git commit`, `git push`;
- удалить workflow-файлы отдельным коммитом, если сценарий не подходит.

# Changelog

- 2026-07-13: added read-only GitHub Actions CI contract for quality and tests.
- 2026-07-01: accepted spec for AI-assisted Git publication workflow.
