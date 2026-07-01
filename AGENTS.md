# AGENTS.md

## Project Mission

This repository is a local working area for the "Shumeyko and partners:
Wildberries unit economics" pilot.

The product goal is a read-only analytics workflow that combines Wildberries API
facts with 1C:UNF cost data, calculates reproducible unit economics, and produces
an Excel MVP first. A lightweight consultant/client web cabinet can be specified
after the Excel methodology is accepted.

Work in this repository must preserve three invariants:

- read-only integrations are the default;
- real keys, tokens, raw client data, and generated reports never enter Git or
  Markdown documentation;
- calculations must be reproducible from snapshots, data contracts, and a
  versioned methodology.

## Current Source Of Truth

- Current accepted implementation target:
  `docs/specs/wb-unit-economics-excel-mvp-implementation.md`.
- Product and technical scope: `docs/specs/wb-unit-economics-mvp.md`.
- Project overview and secret handling: `README.md`.
- Non-secret configuration notes: `config/README.md`.
- Documentation navigation and registry: `docs/index.md`, `docs/manifest.yml`.
- Client-facing scope and access instructions: `docs/client-scope.md`,
  `docs/client-tz.md`, `docs/onec-access-instruction.md`.

If these documents conflict, follow this order:

1. accepted implementation spec, when one exists;
2. `docs/specs/wb-unit-economics-mvp.md`;
3. client-facing documents in `docs/`;
4. `README.md` and local notes.

Do not treat chat messages, generated reports, or ad hoc spreadsheets as the
source of truth unless the user explicitly asks to update the spec from them.

## Security And Secrets

- Never print, copy, commit, summarize, or transform the contents of `.env`.
- `.env`, `.env.*`, `data/`, `reports/`, generated Excel/CSV archives, and raw
  client exports are local-only artifacts.
- `.env.example` may contain only empty variables and safe placeholders.
- If a secret appears in a document, report it and recommend rotation.
- Do not add write-capable WB, 1C, bank, CRM, Telegram, email, or Bitrix
  behavior without a separate accepted spec.
- When connecting to external APIs, use least-privilege access and read-only
  scopes wherever the provider supports them.

## Spec-First Workflow

For any non-trivial feature, start from the relevant spec before editing code.
If the behavior is not specified, update or create a spec first.

Recommended spec states:

- `draft`: exploratory, not ready for implementation guarantees;
- `accepted`: approved implementation target;
- `implemented`: code and tests match the accepted spec;
- `superseded`: replaced by a newer spec.

Each implementation spec should include:

- goal, scope, and out of scope;
- user roles and business decisions;
- data sources and exact read/write boundaries;
- data contracts and schemas;
- calculation formulas and rounding rules;
- security, tenant isolation, audit, and retention rules;
- errors and edge cases;
- acceptance criteria;
- test plan;
- rollout and rollback notes;
- changelog with dates.

Keep specs answerable by tests. Avoid vague requirements such as "improve
analytics" unless they are broken down into measurable outputs.

## Data Contracts

Preserve and evolve these contract names unless a new accepted spec renames them:

- `wb_api_snapshot`;
- `onec_unf_cost_snapshot`;
- `sku_mapping`;
- `unit_economics_report`;
- `ai_analysis_summary`.

For contract changes:

- prefer additive fields over breaking renames;
- keep `client_id`, period, source endpoint/document, load timestamp, and raw
  payload hash or snapshot identifier;
- make missing cost, ambiguous mapping, and partial loads explicit statuses;
- never silently coerce unavailable data to zero;
- keep tenant boundaries visible in schemas, storage, tests, and reports.

## Implementation Principles

- Build the Excel MVP before a broad dashboard unless a newer accepted spec says
  otherwise.
- Keep connectors, normalization, calculation, report building, and AI summary
  as separate layers.
- Persist raw snapshots before normalization so parser or formula changes can be
  reproduced.
- Version calculation methodology and include the version in every report.
- Prefer deterministic calculations in code over formulas hidden inside Excel.
- Use AI only to summarize already computed facts; AI must not mutate source data
  or invent missing values.
- Any external documentation for Wildberries, 1C, or platform APIs must be
  rechecked against the official current documentation before implementation.

## Expected Future Structure

Use this structure unless the accepted spec chooses something else:

```text
config/          non-secret project and client configuration
data/            local raw snapshots and fixtures, not committed
docs/            client docs, runbooks, decisions, and specs
docs/specs/      source-of-truth specs
reports/         generated Excel and report artifacts, not committed
src/             application code when implementation starts
tests/           unit, contract, integration, and report smoke tests
scripts/         validation, import, export, and maintenance scripts
```

## Documentation Rules

- Update docs in the same change when behavior, contracts, setup, or acceptance
  criteria change.
- Keep client-facing docs free of implementation secrets and internal debug
  details.
- Keep technical specs precise enough for another engineer or agent to implement
  from them.
- Add ADR-style notes in `docs/decisions/` for irreversible architecture choices
  once implementation starts.
- Add runbooks in `docs/runbooks/` for API access, report generation, key
  rotation, incident handling, and manual reconciliation once those workflows
  exist.

## Testing And Verification

When validation scripts exist, run the relevant checks before finishing:

- `.venv/bin/python scripts/validate_specs.py docs/specs/wb-unit-economics-mvp.md`;
- `.venv/bin/python scripts/validate_docs_manifest.py`;
- `.venv/bin/python scripts/validate_llm_docs.py`.

If the scripts do not exist yet, say so instead of claiming they passed.

For future implementation, prefer these test layers:

- schema validation for every data contract;
- connector contract tests using anonymized fixtures;
- formula tests for revenue, returns, WB fees, logistics, storage, penalties,
  advertising when enabled, COGS, gross profit, margin, and unit profit;
- edge-case tests for missing costs, ambiguous mappings, partial WB loads, API
  limits, returns from previous periods, and expenses without SKU attribution;
- repeatability tests for the same snapshots and methodology version;
- Excel smoke tests for required sheets, readable file format, and aggregate
  reconciliation;
- permission and tenant-boundary tests before any web cabinet work.

## Development Hygiene

- Keep changes small and tied to the current spec.
- Do not introduce broad frameworks, queues, databases, or dashboards before the
  MVP needs them.
- Prefer clear names over clever abstractions.
- Keep generated artifacts out of commits.
- If Git is unavailable in this workspace, do not rely on Git-only checks; use
  direct file inspection and explicit verification notes.
- Before adding dependencies, explain why the standard library or existing stack
  is not enough.

## Agent Operating Rules

- Communicate with the user in Russian unless they ask for another language.
- Before modifying files, inspect the relevant docs and nearby files.
- When reading project files, prefer fast search tools such as `rg` and scoped
  file reads.
- Do not read or display `.env`; only confirm whether required variables appear
  to be documented in `.env.example` or README.
- After edits, summarize changed files and verification performed.
- If requested behavior conflicts with read-only or secret-handling rules, stop
  and ask for an accepted spec or explicit confirmation.
