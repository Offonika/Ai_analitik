# AGENTS.md

## Mission And Non-Negotiables

This repository is the local working area for the "Shumeyko and partners:
Wildberries unit economics" pilot. It combines read-only Wildberries facts
with 1C:UNF cost data, calculates reproducible unit economics and publishes an
Excel MVP before broader product surfaces.

Preserve these invariants:

- integrations are read-only by default;
- real keys, tokens, raw client data and generated reports never enter Git or
  Markdown;
- calculations remain reproducible from snapshots, versioned contracts and a
  versioned methodology;
- missing, partial or ambiguous data remains explicit and is never silently
  coerced to zero.

## Source Of Truth And Retrieval

`docs/manifest.yml` is the machine registry. Within one `truth_scope`, the
document with the highest `truth_priority` is canonical. `docs/index.md` is the
generated human map. An accepted implementation spec overrides product briefs,
client documents and README only inside its own scope. Supporting ADRs and
runbooks cannot override a higher-priority canonical document.

For each task, use this token-efficient retrieval protocol:

1. Run `.venv/bin/python scripts/docs_route.py --query "<task>"`, or use
   `--scope`, `--path` or `--contract` when the key is known.
2. Read only the returned document frontmatter and its heading list.
3. Read the relevant `ai_sections`, then search code/tests by returned symbols.
4. When the route lists `operational_docs` and the task concerns rollout or an
   environment claim, verify the current state in the referenced runbook.
5. Expand to the full spec or supporting/history documents only for a
   cross-scope conflict or a task spanning the whole scope.

Do not read all of `docs/manifest.yml`, `docs/index.md`, a large spec or a large
source file when the compact route and a scoped `rg` answer the question. Use
`--include-supporting --include-history` only when current canonical sources are
insufficient.

If two scopes genuinely conflict, do not choose silently: update the affected
specs or record an explicit cross-scope decision first. Chat messages, generated
reports and ad hoc spreadsheets are not sources of truth unless the user asks
to update a spec from them.

Environment and rollout claims require dated operational evidence; code
defaults are not evidence of deployed state. Report an exact count only with
the command and revision that reproduce it. Treat subagent summaries as leads
until their primary files, commands or external evidence have been checked.

## Security And External Boundaries

- Never print, copy, summarize, transform or otherwise read the contents of
  `.env`.
- `.env`, `.env.*`, `data/`, `reports/`, generated Excel/CSV archives and raw
  client exports are local-only. `.env.example` may contain only empty values
  and safe placeholders.
- If a secret appears in a tracked document, report it and recommend rotation.
- Do not add write-capable WB, 1C, bank, CRM, Telegram, email or Bitrix behavior
  without a separate accepted spec and explicit user authority.
- Recheck current official Wildberries, 1C or platform API documentation before
  implementing an external API change. Use least-privilege read-only access.

## Spec-First And Contracts

For a non-trivial feature, read the relevant accepted spec before code. If the
behavior is not specified, update or create a spec first. States are `draft`,
`accepted`, `implemented` and `superseded`; only `implemented` means code and
tests demonstrably match the spec.

Implementation specs must make goal, scope/out-of-scope, roles, read/write
boundaries, schemas, formulas/rounding, security/tenant isolation, edge cases,
acceptance criteria, tests, rollout and rollback testable. Keep full history in
a registered changelog when the validator requires it.

Preserve these contract names unless an accepted spec renames them:

- `wb_api_snapshot`;
- `onec_unf_cost_snapshot`;
- `sku_mapping`;
- `unit_economics_report`;
- `ai_analysis_summary`.

Prefer additive changes. Keep `client_id`, period, source document/endpoint,
load timestamp and snapshot/hash identity visible. Preserve tenant boundaries
and explicit statuses for missing cost, ambiguous mapping and partial loads.

Each spec maps its scope through `related_code`, `related_tests`, optional
`ai_sections`, `code_anchors` and `test_anchors`. Update these in the same
change. `scripts/validate_specs.py` verifies paths, headings and symbols.

## Implementation And Documentation

- Keep connectors, normalization, calculation, report building and AI summary
  separate. Persist raw snapshots before normalization.
- Prefer deterministic code over hidden Excel formulas. Include methodology
  version in each report. AI summarizes computed facts; it does not mutate
  sources or invent missing values.
- Build only what the accepted scope requires; do not introduce broad
  frameworks, queues or dashboards prematurely.
- Follow the existing `config/`, `data/`, `deploy/`, `docs/`, `reports/`,
  `scripts/`, `sql/`, `src/` and `tests/` layout unless a spec changes it.
- Update canonical docs in the same change as behavior, contract, setup or
  acceptance changes. Keep client docs free of internal secrets/debug details.
- Put irreversible architecture decisions in `docs/decisions/` and operational
  procedures in `docs/runbooks/`.
- Preserve unrelated user changes in a dirty worktree. Explain any new
  dependency before adding it.

## Verification And Handoff

After documentation changes run:

```bash
.venv/bin/python scripts/validate_specs.py
.venv/bin/python scripts/validate_docs_manifest.py
.venv/bin/python scripts/validate_llm_docs.py
.venv/bin/python scripts/docs_route.py --check-generated
.venv/bin/python scripts/validate_documentation_contracts.py
```

After code changes also run Ruff and the relevant tests returned by the route.
Run broader tests in proportion to risk. GitHub Actions must create and complete
both blocking jobs, `quality` and `tests`; an absent check is not a passing
check. If a referenced script does not exist, say so rather than claiming it
passed.

Communicate with the user in Russian unless asked otherwise. Before editing,
inspect the routed spec and nearby files with `rg` and scoped reads. Never read
`.env`; only confirm safe variable documentation in `.env.example` or README.
After edits, summarize changed files and verification. If requested behavior
conflicts with read-only or secret-handling rules, stop and request an accepted
spec or explicit confirmation.
