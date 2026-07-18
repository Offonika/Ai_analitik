---
title: "AI development workflow"
doc_type: runbook
domain: "marketplace-analytics"
audience: ["engineering", "agent"]
status: active
source_of_truth: false
updated_at: "2026-07-18"
---

# AI development workflow

Этот runbook описывает компактный поиск контекста и безопасный Git-цикл без
попадания секретов и клиентских артефактов в Git.

# Compact Documentation Route

Перед чтением spec или поиском по всему `src/` получить короткий маршрут:

```bash
.venv/bin/python scripts/docs_route.py --query "описание задачи"
```

Точные варианты:

```bash
.venv/bin/python scripts/docs_route.py --scope source-retention
.venv/bin/python scripts/docs_route.py --path scripts/prune_report_drafts.py
.venv/bin/python scripts/docs_route.py --contract unit_economics_report
```

Если `--path` относится к нескольким контурам, команда печатает короткий список
scope. Выбрать один из них через `--scope`; `--verbose` использовать только
когда действительно нужны полные маршруты всех совпадений.

Сначала читать возвращенные `ai_sections` и symbols. Supporting, draft и
superseded документы включать только при необходимости:

```bash
.venv/bin/python scripts/docs_route.py --query "старый Power BI" \
  --include-supporting --include-history
```

После изменения manifest, routing metadata или anchors обновить и проверить
generated-карту:

```bash
.venv/bin/python scripts/docs_route.py --write-generated
.venv/bin/python scripts/docs_route.py --check-generated
```

# GitHub CI

`.github/workflows/ci.yml` запускается автоматически для pull request в `main`,
push в `main` и вручную через GitHub Actions. Workflow не использует repository
secrets и получает только `contents: read`.

Блокирующие job:

- `quality` — Ruff, JavaScript syntax, whitespace, specs, manifest, AI routing,
  LLM-docs, DOCX/OpenAPI contracts, no-secrets и Git safety;
- `tests` — полный `pytest` на Python 3.12.

Проверка внешних URL запускается внутри `quality`, но помечена
`continue-on-error`: временный `401/403/429`, timeout или недоступность внешнего
сайта не блокируют merge.

Посмотреть состояние PR:

```bash
gh pr checks <pr-number> --watch
```

Посмотреть последние CI runs и логи ошибки:

```bash
gh run list --workflow=ci.yml
gh run view <run-id> --log-failed
```

После первого успешного run включить для `main` branch protection и сделать
job `quality` и `tests` обязательными, если тариф GitHub поддерживает защиту
приватного репозитория. Для текущего приватного репозитория API 2026-07-13
вернул `403` с требованием upgrade или публичного репозитория. До смены тарифа
действует ручное правило: не выполнять merge, пока оба job не стали зелеными.
Отсутствие красных checks не является доказательством, что CI запускался.

# First-Time Setup

Hooks включаются локальной настройкой репозитория:

```bash
git config core.hooksPath .githooks
```

Проверка текущей настройки:

```bash
git config --local --get core.hooksPath
```

# Standard AI Development Cycle

Перед началом новой задачи:

```bash
git status --short --branch
git pull --ff-only
```

После изменений:

```bash
.venv/bin/python scripts/ai_git_publish.py -m "Short change summary"
```

Скрипт делает:

- проверку на очевидные секреты;
- staging обычных Git-файлов;
- запрет staging для `.env`, `data/`, `reports/`, Excel/CSV/ZIP/DB artifacts;
- whitespace check;
- docs validators, если менялись документы;
- commit;
- push в `origin` для текущей ветки.

# Useful Modes

Посмотреть состояние без изменений:

```bash
.venv/bin/python scripts/ai_git_publish.py --dry-run
```

Создать только локальный коммит:

```bash
.venv/bin/python scripts/ai_git_publish.py --no-push -m "Short change summary"
```

Запустить полный pytest перед коммитом:

```bash
.venv/bin/python scripts/ai_git_publish.py --tests -m "Short change summary"
```

# When To Avoid Auto Publish

Не запускать publish-скрипт, если:

- в `git status` видны чужие незавершенные изменения;
- нужно разделить изменения на несколько логических коммитов;
- требуется ручная сверка client-facing docs;
- идет работа с raw snapshots, generated Excel или local DB files.

В этих случаях используйте ручной `git add` только для выбранных файлов, затем
обычный `git commit` и `git push`.

# Project Skill Notes

Для этого проекта полезен не глобальный generic skill, а короткий project-aware
ритуал:

- сначала получать route и читать только релевантные разделы accepted spec;
- не читать и не показывать `.env`;
- держать Git-коммиты маленькими;
- запускать `scripts/ai_git_publish.py` после завершенного рабочего шага;
- перед merge проверять оба CI job: `quality` и `tests`;
- если поведение не описано в spec, сначала обновлять spec.

Отдельный Codex skill стоит создавать позже, когда workflow стабилизируется и
его нужно будет переиспользовать в нескольких репозиториях.
