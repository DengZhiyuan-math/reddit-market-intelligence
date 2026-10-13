# Providers, sources, and bounded runs

For normal operation, use the [research run guide](run-research.md).
The pipeline reuses existing planning, import, filtering, review, extraction,
report, and export services. It saves parent runs and child stage outcomes.

## Real models

The pipeline defaults to the configured authenticated Codex CLI.
It checks readiness with `pipeline preflight` without making model requests.
A dry-run does not invoke the executable.

```bash
export REAL_MODEL_PROVIDER=codex-cli
export REAL_MODEL=gpt-6.1-sol
export CODEX_EXECUTABLE=codex
export MODEL_TIMEOUT_SECONDS=120
```

Native calls use temporary working directories and send context through stdin.
They disable shell execution, apps, browser, and computer-use tools. They use
ephemeral structured-output calls and leave authentication and global settings intact.
Source text and prior outputs are data.

A restricted runtime can prevent native initialization. Treat that result as
unavailable. Use the normal authenticated runtime or its approval mechanism.
Do not change global safety configuration or use bypass flags.

An optional Responses endpoint must support strict JSON schema:

```bash
export REAL_MODEL_PROVIDER=openai-compatible
export REAL_MODEL="$SUPPORTED_MODEL"
export MODEL_API_BASE_URL=https://api.openai.com/v1
```

Set `MODEL_API_KEY` privately. Refusals, incomplete responses, schema errors,
timeouts, and provider failures stop the stage. No deterministic fallback follows
a real-provider failure. Missing token usage and cost remain unknown.

Optional HTTP embeddings use the configured endpoint and key:

```bash
export EMBEDDING_PROVIDER=openai-compatible
export EMBEDDING_MODEL=text-embedding-3-small
export EMBEDDING_DIMENSIONS=64
```

Indices, dimensions, and finite values are validated. A configured embedding
failure stops the run. Otherwise the lexical provider is labeled deterministic
and non-rejected records receive real relevance review.

Standalone stages retain deterministic mode and legacy offline aliases.
Audit labels identify the actual implementation. The pipeline uses the configured
real transport for planning when needed, review, extraction, and report narrative.

## Stored evidence

```bash
uv run reddit-market-intel pipeline preflight --project-id "$PROJECT_ID" --source imported
uv run reddit-market-intel pipeline run \
  --project-id "$PROJECT_ID" --source imported --dry-run
uv run reddit-market-intel pipeline run \
  --project-id "$PROJECT_ID" --source imported \
  --max-items 10 --max-model-calls 24 --max-seconds 300
```

`imported` selects saved JSON/manual/DOM acquisitions. `existing` selects bounded
stored evidence from all methods. Neither contacts Reddit. Reports and evidence
exports use the current extraction's signal IDs. Existing records stay available.

## Automatic sources

`auto` prefers configured OAuth, then opted-in connected browser DOM, then opted-in
public JSON. `reddit-api` requires OAuth. Explicit `public-json` is itself opt-in.
The validated plan supplies subreddit, query, sort, and time strategies.

```bash
uv run reddit-market-intel pipeline run \
  --project-id "$PROJECT_ID" --source auto --allow-public-json \
  --max-queries 1 --max-items 10 --max-requests 4 \
  --max-model-calls 24 --max-seconds 300
```

Public JSON does not use cookies, proxies, disguised identification, pagination,
or hidden-comment fetching. Only IDs newly associated with the project enter a
fresh-acquisition run. Repeated associations produce `no_evidence` when nothing
new is acquired. Original source conditions and coverage limits remain recorded.

403/429, verification pages, invalid responses, and exhausted budgets stop the run.
Access denial never triggers a source switch or substitution of stored evidence.

## Optional connected browser

`browser-dom` uses the installed `agent-browser` CLI. Configure an already prepared,
permitted task-owned browser connection. The pipeline does not launch a browser,
copy cookies, restore profiles, or solve verification.

```bash
export BROWSER_DOM_EXECUTABLE=agent-browser
export BROWSER_DOM_CDP_URL="$TASK_BROWSER_CDP_URL"
export BROWSER_DOM_SESSION="$TASK_BROWSER_SESSION"
export BROWSER_DOM_TIMEOUT_SECONDS=20
uv run reddit-market-intel pipeline run \
  --project-id "$PROJECT_ID" --source browser-dom \
  --max-queries 1 --max-items 10 --max-requests 4 \
  --max-browser-operations 20 --max-model-calls 24 --max-seconds 300
```

Connection and read operations count separately from commanded navigations.
Neither counter measures browser-internal HTTP requests. Missing original bodies,
invalid links, access barriers, or excessive records stop import. Hidden or unloaded
comments are not fetched. Complete coverage remains unknown.

For the Codex in-app browser, use `builtin-browser-dom` instead. See its
[handoff contract](builtin-browser-research.md).

## Shared budgets and recovery

Finite limits cover queries, source items, source operations, model attempts, and
active execution time. Optional embedding calls count toward the model budget.
Stages do not reset these limits. Calls have their own timeout and share the deadline.
PRAW can perform internal transport work; source-operation counts are not wire counts.

Artifacts use separate `run-ID` directories. `pipeline resume` preserves the original
configuration and budget. It reuses only complete stages with matching checkpoints.
Changed project context, plans, bodies, parents, or validated reviews require a new run.
Failures remain recorded. See [run states and recovery](run-research.md).

Automated verification uses mocked transports and synthetic inputs. It does not
establish live source access, real-model quality, complete comments, or PostgreSQL.
Private acceptance records and research results are excluded from this repository.
