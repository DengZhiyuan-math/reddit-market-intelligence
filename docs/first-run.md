# First Run Guide

This guide gets the v1 CLI from a clean checkout to a working local smoke run, then shows the live Reddit workflow. Start with the fixture path; it is faster, safer, and does not require credentials.

## 1. Install And Verify

```bash
uv sync
uv run pytest -q
uv run ruff check app tests
```

If the console script appears stale after recent code changes, refresh the package cache:

```bash
uv cache clean reddit-market-intel
uv run reddit-market-intel --help
```

## 2. No-Credential Fixture Demo

Run the synthetic Zurich tutoring fixture demo:

```bash
uv run reddit-market-intel demo run-fixture
```

Expected default outputs:

- `outputs/demo/fixture-demo.sqlite3`
- `outputs/demo/market-report.md`
- `outputs/demo/evidence/report-evidence.md`
- `outputs/demo/evidence/report-evidence.csv`
- `outputs/demo/market-signals.md`
- `outputs/demo/demo-summary.json`

The fixture demo uses synthetic records from `data/eval/zurich_tutoring_sample.jsonl`. It does not call Reddit, does not require Reddit credentials, does not call a live LLM provider, and does not prove real market demand.

Run a scoped smoke output directory:

```bash
uv run reddit-market-intel demo run-fixture \
  --database-url sqlite:///outputs/demo/phase10-smoke.sqlite3 \
  --output-dir outputs/demo/phase10-smoke
```

The command prints counts and artifact paths. Report and evidence Markdown include a synthetic-data notice.

## 3. Live Database Setup

Use PostgreSQL for real project runs:

```bash
docker compose up -d postgres
PYTHONPATH=. uv run reddit-market-intel db preflight
uv run reddit-market-intel db upgrade
uv run reddit-market-intel db status
```

`db preflight` checks common local blockers before live collection: database URL
parsing and connectivity, Alembic migration state, Reddit credential settings,
Docker Compose availability, and CLI import/package-path health.

If `uv run reddit-market-intel ...` cannot import `app`, run commands from the
repository root with `PYTHONPATH=.` or refresh the package entrypoint:

```bash
uv run --reinstall-package reddit-market-intel reddit-market-intel --help
```

If you already have Phase 2 JSON project data:

```bash
uv run reddit-market-intel projects import-json \
  --registry-path outputs/projects/projects.json
```

## 4. Live Reddit Credential Setup

Create a local `.env` from `.env.example` and set your own credentials:

```bash
REDDIT_CLIENT_ID=your-client-id
REDDIT_CLIENT_SECRET=your-client-secret
REDDIT_USER_AGENT=reddit-market-intel/0.1 by you@example.com
REDDIT_ACCESS_MODE=personal
```

Use a descriptive `REDDIT_USER_AGENT`. Do not commit `.env`.

Validate before collection:

```bash
uv run reddit-market-intel reddit validate-credentials
```

## 5. Live Pipeline Commands

Create or import a project, then generate and select a plan:

```bash
uv run reddit-market-intel projects create \
  --topic "Swiss tutoring market in Zurich" \
  --region "Switzerland, Zurich" \
  --language en \
  --language de \
  --target-user parents \
  --access-mode commercial-approved

uv run reddit-market-intel plans generate --project-id 1
uv run reddit-market-intel plans list --project-id 1
uv run reddit-market-intel plans select --project-id 1 --plan-id 1
```

Collect read-only Reddit posts and top-level comments:

```bash
uv run reddit-market-intel reddit collect \
  --project-id 1 \
  --limit-per-query 25 \
  --max-comments-per-post 10
```

Clean and route relevance:

```bash
uv run reddit-market-intel filtering run --project-id 1
uv run reddit-market-intel filtering export-samples --project-id 1
```

Review ambiguous items and export the queue:

```bash
uv run reddit-market-intel llm export-review-queue --project-id 1
uv run reddit-market-intel llm review --project-id 1
```

Extract market signals and export QA material:

```bash
uv run reddit-market-intel analysis extract-signals --project-id 1
uv run reddit-market-intel analysis export-signals --project-id 1
```

Generate report and evidence exports:

```bash
uv run reddit-market-intel reports generate --project-id 1
uv run reddit-market-intel reports export-evidence --project-id 1
```

## 6. Structured Logs

Core stages emit lightweight structured events with fields such as `project_id`, `run_id`, `stage`, `event`, `item_count_in`, `item_count_out`, Reddit rate-limit metadata, LLM provider/model metadata, and artifact paths.

The logging helper redacts sensitive key names containing `api_key`, `client_secret`, `token`, `password`, or `authorization`. Logs should not include raw Reddit bodies, raw comments, raw LLM prompts, or credential values.

## 7. Compliance Boundary

This project is a market research and content strategy assistant. It must not automate Reddit posting, commenting, private messaging, voting, multi-account operation, account farming, hidden promotion, or disruptive community manipulation.

Fixture outputs are synthetic demonstration data. Live Reddit outputs are qualitative evidence, not statistically representative market truth unless separately validated.

## 8. Troubleshooting

If `uv run reddit-market-intel ...` shows an old command list or cannot find a new command:

```bash
uv cache clean reddit-market-intel
uv run reddit-market-intel --help
```

If a SQLite demo command cannot open the database file, ensure the parent output directory is writable or pass an absolute output path:

```bash
uv run reddit-market-intel demo run-fixture \
  --database-url sqlite:////tmp/reddit-market-intel-demo.sqlite3 \
  --output-dir /tmp/reddit-market-intel-demo
```

If PostgreSQL commands fail, check Docker and migration state:

```bash
docker compose ps
PYTHONPATH=. uv run reddit-market-intel db preflight
uv run reddit-market-intel db status
```

If Reddit collection fails, rerun credential validation and inspect access mode:

```bash
uv run reddit-market-intel reddit validate-credentials
```
