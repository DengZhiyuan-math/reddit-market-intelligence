# Quality Coverage Matrix

Phase 10 hardening keeps verification deterministic, no-network, and no-live-LLM by default. The goal is not raw coverage percentage; it is proving the MVP seams that can most easily break compliance, provenance, structured LLM contracts, and evidence-grounded reporting.

Full validation commands:

```bash
uv run pytest -q
uv run ruff check app tests
```

Live Reddit credentials and live LLM provider calls are not required for automated verification. Tests use local fixtures, fake clients/providers, isolated database sessions, and deterministic offline embeddings.

## MVP Seam Coverage

| Seam | Existing coverage | Phase 10 coverage | Known gap / boundary | Verification command |
|------|-------------------|-------------------|----------------------|----------------------|
| settings/config loading | `tests/projects/test_settings.py`, `tests/db/test_database_settings.py`, `tests/reddit/test_client.py` | `tests/quality/test_quality_contracts.py` confirms this matrix keeps settings/config visible | Production secret-manager wiring remains future work | `uv run pytest tests/projects tests/db tests/reddit -q` |
| DB model/migration smoke | `tests/db/test_models.py`, `tests/db/test_migration_smoke.py`, `tests/db/test_provenance_contracts.py` | `tests/quality/test_quality_contracts.py` requires persistence coverage to stay mapped | Postgres/pgvector integration can be expanded later; SQLite-style tests remain MVP-safe | `uv run pytest tests/db -q` |
| Reddit dedup/rate-limit behavior | `tests/reddit/test_collector_posts.py`, `tests/reddit/test_collector_comments.py`, `tests/reddit/test_rate_limiter.py`, `tests/reddit/test_repository.py` | `tests/quality/test_quality_contracts.py` checks Reddit and rate-limit coverage references | Live Reddit API smoke is intentionally excluded from automated verification | `uv run pytest tests/reddit -q` |
| cleaning/relevance routing | `tests/processing/test_cleaner.py`, `tests/processing/test_rules.py`, `tests/processing/test_relevance.py`, `tests/processing/test_service.py`, `tests/processing/test_embeddings.py` | `tests/quality/test_quality_contracts.py` keeps this routing seam in the matrix | Threshold calibration uses fixture exports; statistical validation remains later work | `uv run pytest tests/processing -q` |
| LLM structured validation | `tests/llm/test_models.py`, `tests/llm/test_gateway.py`, `tests/llm/test_service.py`, `tests/llm/test_repository.py` | `tests/quality/test_quality_contracts.py` enforces no-live-LLM wording and LLM seam visibility | Live provider evaluation is excluded; schema validation is deterministic | `uv run pytest tests/llm -q` |
| market signal extraction | `tests/analysis/test_models.py`, `tests/analysis/test_gateway.py`, `tests/analysis/test_service.py`, `tests/analysis/test_repository.py` | `tests/quality/test_quality_contracts.py` requires signal extraction coverage in this matrix | Human-labeled precision/recall benchmarking starts with Phase 10 fixture samples | `uv run pytest tests/analysis -q` |
| report rendering/export | `tests/reports/test_models.py`, `tests/reports/test_generator.py`, `tests/reports/test_service.py`, `tests/reports/test_exporter.py`, `tests/reports/test_cli.py` | `tests/quality/test_quality_contracts.py` checks report/export coverage remains documented | Polished DOCX/PDF/slides are outside v1 hardening | `uv run pytest tests/reports -q` |
| CLI failure readability | `tests/projects/test_cli.py`, `tests/reddit/test_cli.py`, `tests/processing/test_cli.py`, `tests/llm/test_cli.py`, `tests/analysis/test_cli.py`, `tests/reports/test_cli.py` | `tests/quality/test_quality_contracts.py` ensures CLI coverage remains called out | End-user UX polish beyond CLI text is deferred | `uv run pytest tests -q` |
| fixture demo | Planned in `tests/demo/test_eval_sample.py`, `tests/demo/test_fixture_service.py`, `tests/demo/test_fixture_cli.py` | `tests/quality/test_quality_contracts.py` requires fixture/no-credential demo coverage to be named | Demo data is synthetic and not real market evidence | `uv run pytest tests/demo -q` |
| Offline no-key export import | `tests/reddit/test_export_import.py` | CLI/service imports, raw Listing and author CSV contracts, BOM/multiline handling, nested replies/more, full-file validation, dry-run, transaction rollback, canonical dedup, batch history, and comment-only rows | Synthetic files and SQLite; no real plugin/browser/Reddit acceptance | `uv run pytest tests/reddit/test_export_import.py -q` |
| Import through existing analysis and reports | `tests/reddit/test_export_import_pipeline.py`, `tests/reports/test_generator.py` | Real filtering, signal extraction, report and evidence exports; all import methods, API/import project order, source URLs, unique capture counts, missing text and unknown/incomplete coverage | Deterministic providers; no live model or PostgreSQL acceptance | `uv run pytest tests/reddit/test_export_import_pipeline.py tests/processing tests/analysis tests/reports -q` |
| observability | Planned in `tests/observability/test_logging.py`, `tests/observability/test_service_events.py` | `tests/quality/test_quality_contracts.py` requires structured log coverage to be named | Hosted monitoring, alerting, OpenTelemetry, and dashboards are deferred | `uv run pytest tests/observability -q` |

## Verification Boundary

| New seam | Local coverage | Boundary |
|---|---|---|
| Real native/HTTP models and indexed embeddings | `tests/llm/test_real_providers.py` | Mocked subprocess/HTTP only; strict schemas, failures/refusals, truthful usage, vector validation, narrative citations |
| Bounded automatic Reddit acquisition | `tests/reddit/test_public_json.py` | Mocked public JSON and existing fake OAuth client; selected queries, item/request limits, new project associations, repeats and durable stops |
| One real research pipeline | `tests/test_pipeline.py` | Production provider factories with mocked native responses; prior signals excluded by new extraction IDs, stale acquisition refusal, shared budgets, dry-run and prior artifact preservation |
| Connected browser DOM acquisition | `tests/reddit/test_browser_dom.py`, `tests/fixtures/reddit_dom/`, `tests/test_pipeline.py` | Mocked connected boundary and synthetic literal content using supplied observed selectors; connect/tab ordering, canonical original bodies, unknown coverage, barriers, bounds, importer/new-association scope, genuine report scope and zero-side-effect dry-run |

Run these focused checks with `uv run pytest tests/llm/test_real_providers.py tests/reddit/test_public_json.py tests/test_pipeline.py -q`.

For DOM checks, run `uv run pytest tests/reddit/test_browser_dom.py tests/test_pipeline.py tests/reddit/test_export_import.py tests/reddit/test_export_import_pipeline.py -q`. Passing mocked tests establishes no live browser acquisition or actual-source report. A regression uses the observed v0.33.1 reused-CDP lifecycle response while retaining relaunch/restore rejection.

- Default automated tests must be no-network and no-live-LLM.
- Tests must not require `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`, or `OPENAI_API_KEY`.
- Reddit collection tests should use fakes or sanitized fixtures rather than live Reddit API calls.
- LLM tests should validate schemas, deterministic providers, persistence, and failure handling rather than live provider behavior.
- Fixture/demo tests use synthetic test records and must label outputs as synthetic demonstration data.
