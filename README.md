# Reddit Market Intelligence System

Reddit Market Intelligence System is a compliance-first, CLI-oriented market research pipeline. It turns a market topic into Reddit research plans, collected evidence, structured market signals, and evidence-grounded reports.

The first target use case is Swiss tutoring demand analysis for Zurich families, students, and expat communities.

## Compliance Boundary

This MVP is for market research and content strategy only. It does not automate Reddit posting, commenting, private messaging, voting, multi-account operation, account farming, hidden promotion, or ban evasion.

See [docs/compliance.md](docs/compliance.md) for access-mode, retention, deletion, and prohibited-automation guardrails.

## V1 Quickstart: No-Credential Demo First

Start with the synthetic fixture demo before configuring Reddit credentials. This
proves the local pipeline shape with safe demo data and writes outputs under
`outputs/demo/`:

```bash
uv sync
uv run reddit-market-intel demo run-fixture
```

Expected outputs:

- `outputs/demo/market-report.md`
- `outputs/demo/evidence/report-evidence.md`
- `outputs/demo/evidence/report-evidence.csv`
- `outputs/demo/market-signals.md`
- `outputs/demo/demo-summary.json`

The fixture demo uses synthetic Zurich tutoring examples only. It does not call
Reddit, does not require Reddit credentials, does not call a live LLM provider,
and does not produce real market evidence.

## Public Repository Boundary

This public repository contains source code, tests, documentation, and synthetic
evaluation fixtures only. It deliberately excludes local databases, generated
research reports, project registries, credentials, and internal planning records.
Run the demo locally to generate artifacts under `outputs/`; that directory is
ignored by Git and must not be committed.

For the full operator path, see [docs/first-run.md](docs/first-run.md).

## Local Setup

Install dependencies and run the test suite with `uv`:

```bash
uv sync
uv run pytest -q
uv run ruff check app tests
```

Create a local `.env` if you want runtime overrides. Reddit collection requires
your own Reddit OAuth app credentials:

```bash
REDDIT_CLIENT_ID=your-client-id
REDDIT_CLIENT_SECRET=your-client-secret
REDDIT_USER_AGENT=reddit-market-intel/0.1 by you@example.com
```

Use a descriptive `REDDIT_USER_AGENT` that identifies the app and gives a contact
hint. Do not commit `.env` or other secret files.

## Database Setup

Start the local database with Docker Compose:

```bash
docker compose up -d postgres
```

Apply migrations and inspect migration status:

```bash
uv run reddit-market-intel db upgrade
uv run reddit-market-intel db status
```

Before live collection, run local preflight diagnostics:

```bash
PYTHONPATH=. uv run reddit-market-intel db preflight
```

The preflight checks database connectivity, migration state, Reddit credential
settings, Docker Compose availability, and local CLI import health. If the
console script cannot import the local `app` package, run from the repository
root with `PYTHONPATH=.` or refresh the package entrypoint:

```bash
uv run --reinstall-package reddit-market-intel reddit-market-intel --help
```

If you created projects with the Phase 2 JSON registry, explicitly import them
after the database is migrated:

```bash
uv run reddit-market-intel projects import-json \
  --registry-path outputs/projects/projects.json
```

The import is intentional and one-way for normal MVP usage: the database becomes
the source of truth after import, and the app does not auto-import or dual-write
JSON plus database state.

## CLI Usage

Preview project creation without writing a registry file:

```bash
uv run reddit-market-intel projects create --dry-run \
  --topic "Swiss tutoring market in Zurich" \
  --region "Switzerland, Zurich" \
  --language en \
  --language de \
  --target-user parents \
  --business-context "AI + human tutor platform"
```

Create a stored project:

```bash
uv run reddit-market-intel projects create \
  --topic "Swiss tutoring market in Zurich" \
  --region "Switzerland, Zurich" \
  --language en \
  --language de \
  --target-user parents \
  --access-mode commercial-approved
```

Show an existing project by ID:

```bash
uv run reddit-market-intel projects show --project-id 1
```

## Topic Planning

After database setup and optional JSON registry import, generate a structured
Reddit research plan for a database-backed project:

```bash
uv run reddit-market-intel plans generate --project-id 1
```

Inspect persisted plans:

```bash
uv run reddit-market-intel plans list --project-id 1
uv run reddit-market-intel plans show --plan-id 1
```

Select the plan that later collection stages should execute:

```bash
uv run reddit-market-intel plans select --project-id 1 --plan-id 1
```

Export the validated JSON plan:

```bash
uv run reddit-market-intel plans export \
  --plan-id 1 \
  --output outputs/plans/plan-1.json
```

Phase 4 uses an offline deterministic planner by default. It does not collect
Reddit data and does not call LLM providers.

## Reddit Collection

Phase 5 adds read-only Reddit API collection through PRAW. Before collecting,
complete the database setup, import/create a database-backed project, generate a
topic plan, and ensure the desired plan is selected:

```bash
uv run reddit-market-intel db upgrade
uv run reddit-market-intel projects import-json \
  --registry-path outputs/projects/projects.json
uv run reddit-market-intel plans generate --project-id 1
```

Validate credentials and the descriptive User-Agent before collection starts:

```bash
uv run reddit-market-intel reddit validate-credentials
```

Collect posts and top-level comments for materialized search queries:

```bash
uv run reddit-market-intel reddit collect \
  --project-id 1 \
  --limit-per-query 25 \
  --max-comments-per-post 10
```

Use `--skip-comments` to collect posts only. The v1 collector stores top-level
comments only; it calls `replace_more(limit=0)` and does not recursively ingest
full comment trees.

The collector records request logs with endpoint/action context, timing, errors,
available `X-Ratelimit-*` metadata, retry/permanent-failure counts, duplicate
skips, and elapsed time. It backs off or stops instead of attempting to bypass
rate-limit behavior.

This package remains read-only: it does not automate Reddit posting, commenting,
private messaging, voting, multi-account behavior, hidden promotion, or other
engagement automation.

## Filtering and Relevance Routing

Phase 6 turns collected posts and top-level comments into unified content items,
then applies rule-based cleaning, duplicate detection, language labels, embedding
similarity, and low-false-negative routing:

```bash
uv run reddit-market-intel filtering run --project-id 1
```

Use `--limit` for a small calibration pass before processing the full project:

```bash
uv run reddit-market-intel filtering run --project-id 1 --limit 50
```

Routing states are intentionally simple:

- `accepted`: similarity is high enough to keep as candidate market evidence.
- `rejected`: content is deleted/removed, inaccessible, empty, duplicate, obvious spam, off-language, negatively matched, or clearly below the relevance floor.
- `ambiguous`: content sits between the accept and reject thresholds and should be reviewed by the Phase 7 LLM ambiguity workflow.

The default thresholds favor low false negatives: uncertain evidence is routed to
`ambiguous` rather than discarded. Deleted, removed, inaccessible, and empty
content is excluded as market evidence before embedding. Every rule decision
persists compact reason codes plus readable explanations so later audits can see
why content moved.

Export calibration samples for manual threshold/rule review:

```bash
uv run reddit-market-intel filtering export-samples --project-id 1
```

The default export path is
`outputs/exports/project-1/calibration-samples.md`. The Markdown groups accepted,
ambiguous, and rejected examples with scores, language, review flags, reason
codes, explanations, and cleaned-text excerpts. Use `--output-path` and
`--limit-per-band` to customize the review set.

Embedding behavior is configured through `.env` settings such as
`EMBEDDING_PROVIDER`, `EMBEDDING_MODEL`, `EMBEDDING_DIMENSIONS`,
`RELEVANCE_ACCEPT_THRESHOLD`, and `RELEVANCE_REJECT_THRESHOLD`. The MVP ships
with deterministic offline embeddings so tests and local calibration work without
network calls; provider/model/dimension metadata is still recorded with each
embedding decision for future OpenAI or local embedding integrations.

## LLM Ambiguity Review

Phase 7 reviews only content routed to `ambiguous` with
`llm_review_required=true`; accepted and rejected items are not sent through this
gateway. Start by exporting the pending queue:

```bash
uv run reddit-market-intel llm export-review-queue --project-id 1
```

The default export path is
`outputs/exports/project-1/llm-review-queue.md`. The Markdown contains pending
content item IDs, source IDs, scores, language labels, and cleaned-text excerpts
so operators can inspect what Codex/local review will see.

Run the review pass:

```bash
uv run reddit-market-intel llm review --project-id 1
```

Use `--dry-run` to count the current queue without writing LLM calls,
judgements, or relevance decisions:

```bash
uv run reddit-market-intel llm review --project-id 1 --dry-run
```

The MVP path does not require an external API key. The local/Codex provider
contract still enforces strict JSON validation, records every LLM call attempt,
persists validated `llm_judgements`, and keeps failed validation attempts as
audit records without creating a judgement.

Phase 7 stops at ambiguity review. Market signal extraction remains Phase 8, and
final report generation remains Phase 9.

## Market Signal Extraction

Phase 8 consumes Phase 6 `accepted` content and Phase 7 validated relevant
ambiguity judgements. It uses strict JSON validation to extract source-linked
market signals, supports `abstained` and `uncertain` outcomes for weak evidence,
and records audit calls without turning abstentions into trusted signals.

Preview eligible evidence without writing pipeline runs, LLM calls, or market
signals:

```bash
uv run reddit-market-intel analysis extract-signals --project-id 1 --dry-run
```

Run extraction:

```bash
uv run reddit-market-intel analysis extract-signals --project-id 1
```

Use `--limit` for a smaller pass:

```bash
uv run reddit-market-intel analysis extract-signals --project-id 1 --limit 25
```

Export a reviewer-friendly Markdown QA file:

```bash
uv run reddit-market-intel analysis export-signals --project-id 1
```

The default export path is `outputs/exports/project-1/market-signals.md`. It
lists extracted signal IDs, source content IDs, optional judgement links,
personas, pain points, urgency, buying-signal flags, quotes, confidence, and
compact signal JSON for inspection.

Phase 8 does not generate the final market report, executive summary, content
strategy, or recommendations. Final report generation remains Phase 9.

## Evidence-Grounded Reporting

Phase 9 generates a Markdown market intelligence report from stored Phase 8
market signals and source-linked evidence IDs. Reports are intentionally
evidence-grounded: Reddit evidence is qualitative and not representative market
truth, and unsupported claims are caveated instead of invented.

Generate the default Markdown report:

```bash
uv run reddit-market-intel reports generate --project-id 1
```

The default report path is `outputs/reports/project-1/market-report.md`. The
report includes the executive summary, dataset overview, demand categories,
persona and pain-point analysis, posting style, market gaps, content strategy,
community participation strategy, actionable recommendations, evidence appendix,
methodology, and limitations.

Export reviewer evidence as Markdown and CSV:

```bash
uv run reddit-market-intel reports export-evidence --project-id 1
```

The default evidence export paths are
`outputs/exports/project-1/report-evidence.md` and
`outputs/exports/project-1/report-evidence.csv`. These exports include trusted
signal IDs, content item IDs, optional judgement IDs, source type/source ID,
quotes, persona, pain point, urgency, buying-signal flags, confidence, and other
fields needed to audit report claims.

Phase 9 remains Markdown/CSV-first. DOCX, PDF, slides, dashboard exports,
automated Reddit posting, and content-calendar generation are out of scope.

## Fixture Demo And Observability

Run the no-credential fixture demo at any time:

```bash
uv run reddit-market-intel demo run-fixture \
  --output-dir outputs/demo/phase10-smoke
```

The command creates a local SQLite database by default at
`outputs/demo/fixture-demo.sqlite3`, seeds synthetic Zurich tutoring samples,
generates cleaned content items and market signals, writes a Markdown report,
and exports evidence files. Every artifact is marked as synthetic fixture output,
not observed Reddit evidence.

Core services emit lightweight structured log events through `app.observability`
with stable fields such as `project_id`, `run_id`, `stage`, `event`, counts,
rate-limit metadata, LLM provider/model metadata, and artifact paths. Logs redact
sensitive key names such as API keys, client secrets, tokens, passwords, and
authorization headers.

If `uv run reddit-market-intel ...` loads stale console-script metadata, refresh
the package cache and retry:

```bash
uv cache clean reddit-market-intel
uv run reddit-market-intel demo run-fixture --help
```

For live database setup failures, run:

```bash
PYTHONPATH=. uv run reddit-market-intel db preflight
```

## Project Registry

Phase 2 stores projects in a local JSON registry before Phase 3 introduces
database persistence. The default path is controlled by `PROJECT_REGISTRY_PATH`
and defaults to `outputs/projects/projects.json`.

Use `DEFAULT_RUN_LIMIT` to change the CLI default for `--limit`; the built-in
default is `100`.
