<!-- GSD:project-start source:PROJECT.md -->
## Project

**Reddit Market Intelligence System**

Reddit Market Intelligence System is an LLM-assisted Reddit market research pipeline. A user provides a market topic, then the system plans the research direction, collects relevant Reddit posts and comments through Python, filters and classifies the data, extracts market signals, and generates an actionable report for positioning, content strategy, and advertising research.

The initial concrete use case is Swiss tutoring demand analysis for Zurich, including math, science, Gymnasium, Matura, ETH preparation, expat families, parents, and students. The system is a market research and content strategy assistant, not a Reddit automation, spam, or account manipulation tool.

**Core Value:** Given a market topic, the system must reliably turn real Reddit discussions into structured, evidence-grounded market insights without violating Reddit community or API rules.

### Constraints

- **Compliance**: The MVP must not implement automatic posting, commenting, private messaging, vote manipulation, account farming, or disguised promotion - Reddit participation should remain transparent, manual, and subreddit-rule-aware.
- **Reddit API**: Prefer official Reddit Data API or compliant authorized access. The system must monitor and respect rate-limit headers such as `X-Ratelimit-Used`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset`.
- **Access Mode**: Configuration must leave room for `personal`, `research`, and `commercial-approved` API access modes because commercial or higher-volume usage may require separate Reddit authorization.
- **Data Retention**: The design must account for removed/deleted content handling, request logging, and future retention policy decisions.
- **MVP Scope**: Start with posts and top-level comments only. Avoid full comment tree ingestion until the core analysis loop works.
- **Structured LLM Output**: LLM planner, ambiguity filter, signal extractor, and report writer must use strict contracts where downstream code expects JSON or a fixed report template.
- **Evidence Discipline**: Reports must not invent data and must clearly separate observed Reddit evidence from analyst interpretation.
- **Database Reuse**: Do not recreate the database for each run. Store multiple research runs in one database using `project_id`.
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Recommendation
## Recommended Stack
### Runtime and Packaging
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| Python | 3.13 initially; allow 3.14 after dependency CI passes | Main runtime | Python is the natural fit for PRAW, SQLAlchemy, LLM SDKs, embeddings, statistics, and report generation. Python 3.13 is the conservative 2026 choice; 3.14 is current but newer ecosystem wheels may lag. | HIGH |
| uv | Current stable | Environment, dependency locking, script execution | Fast project setup, reproducible lockfiles, Python version management, and simple `uv run` workflows for CLI-first MVP. | HIGH |
| `pyproject.toml` | PEP 621 project metadata | Dependency and tool configuration | Keeps packaging, tool config, and scripts in one standard file. Avoid ad hoc `requirements.txt` as the source of truth; export only for deployment if needed. | HIGH |
| Ruff | Current stable | Linting and formatting | One fast tool for lint/format/import hygiene. Use instead of a pile of Flake8, isort, Black, pyupgrade unless a future team requires those separately. | MEDIUM |
| mypy or pyright | Current stable | Static type checking | The pipeline depends on schema contracts and database models; type checking catches interface drift early. Prefer gradual strictness on `app/`, looser on scripts. | MEDIUM |
### Reddit Collection
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| Reddit Data API | Current official API terms as of 2026-05-11 | Authorized data source | **Compliance-sensitive.** Reddit says clients must authenticate with registered OAuth, use a unique descriptive User-Agent, monitor rate limits, and remove Reddit-deleted content from stored data. This is mandatory, not optional. | HIGH |
| PRAW | 7.7.1 docs are current stable docs | Python Reddit API wrapper | Use PRAW for MVP because the collector is mostly sequential, rate-limited, and CLI-operated. PRAW supports read-only instances and OAuth app types, and its docs assume script apps unless otherwise noted. | HIGH |
| Async PRAW | Consider later, not MVP default | Async collection at higher volume | Only adopt if collection throughput becomes a real bottleneck and API access mode permits it. Async adds complexity and increases the risk of accidental parallel request pressure. | MEDIUM |
| prawcore exceptions | Bundled under PRAW stack | Retry/error classification | Catch API exceptions explicitly, log status, endpoint, query, and retry state. Do not hide collector failures behind generic `except Exception`. | HIGH |
- Store `access_mode`: `personal`, `research`, or `commercial-approved` on each project/run.
- Use read-only access unless a future explicitly approved workflow requires more.
- Log request metadata: endpoint kind, query/subreddit, timestamp, response status, rate-limit headers when available, and collector version.
- Respect `X-Ratelimit-Used`, `X-Ratelimit-Remaining`, and `X-Ratelimit-Reset`.
- Design a deletion/retention job from day one. Reddit's current Data API wiki says deleted Reddit content and user-identifying information must be removed from your possession, and recommends routinely deleting stored user data/content within 48 hours.
- Do not collect via browser scraping, Pushshift-like archives, or unofficial mirrors for MVP. They weaken compliance and provenance.
### Database and Persistence
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| PostgreSQL | 16 or 17 for MVP; 18 acceptable if ops environment supports it | Primary relational store | Best fit for project-scoped relational records, JSONB raw payloads, uniqueness constraints, full-text features, and pgvector. | HIGH |
| SQLAlchemy | 2.0.x; official docs show 2.0.49 current release on 2026-04-03 | ORM and SQL layer | SQLAlchemy 2.0 typed declarative models match this system's need for explicit schema, relationships, JSONB columns, and maintainable queries. | HIGH |
| Alembic | Current stable | Schema migrations | Required because the schema will evolve across raw data, cleaned items, LLM judgements, embeddings, and report outputs. Use autogenerate, but review migrations manually. | HIGH |
| psycopg | 3.3.x | PostgreSQL driver | Psycopg 3 is the current generation and supports modern PostgreSQL/Python, asyncio if needed later, COPY, typing, and better pooling options. Use package name `psycopg`, not `psycopg3`. | HIGH |
| pgvector extension | 0.8.2 server extension guidance; Python `pgvector` 0.4.2 | Vector search inside Postgres | Keeps embeddings beside source records and metadata. Supports HNSW indexes and SQLAlchemy integration, enough for MVP and early scaling. | HIGH |
- `projects`: topic, region, languages, business context, access mode.
- `research_runs`: immutable run metadata and status.
- `reddit_queries`: keyword/subreddit strategy and execution metadata.
- `raw_posts`, `raw_comments`: Reddit IDs, project/run IDs, JSONB payload, normalized text fields, author fields separated for retention deletion.
- `cleaned_items`: content-level records after rule cleaning.
- `embeddings`: item ID, provider/model, dimensions, vector, text hash.
- `llm_judgements`: schema version, model, prompt version, JSON result, confidence.
- `market_signals`: extracted structured facts and evidence links.
- `reports`: rendered Markdown/HTML/DOCX path plus report metadata.
- `api_request_logs`: rate-limit headers, endpoint, status, retry count.
### Embeddings and Filtering
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| OpenAI embeddings or equivalent provider | Pin model name in config and store per vector | Semantic relevance filter | Use embeddings to cheaply accept/reject obvious relevance before LLM judgement. Keep provider behind a small interface because embedding model names and dimensions change. | MEDIUM |
| pgvector | Server extension + SQLAlchemy adapter | Similarity search | Store vectors in Postgres for MVP instead of adding a separate vector DB. This preserves joins, auditability, and deployment simplicity. | HIGH |
| scikit-learn | 1.8.0 docs current; requires Python >=3.10 for recent versions | TF-IDF baselines, clustering, metrics | Use for non-LLM baselines, keyword analysis, clustering, and validation metrics. Do not use it as the primary semantic matching layer when embeddings are available. | HIGH |
| pandas | 3.0.1 current as of 2026-02-17 | Analysis tables and exports | Useful for report stats, CSV exports, and quick aggregation. Keep core persistence in SQL, not DataFrames. | HIGH |
### LLM Structured Judgement
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| OpenAI Python SDK | 2.36.0 on PyPI as of 2026-05-07 | LLM calls | Official SDK, current, supports modern Responses API patterns. Pin a compatible range and record SDK/model versions in run metadata. | HIGH |
| OpenAI Structured Outputs | Current official API docs | Strict JSON planner, relevance, judgement, extraction | Use `json_schema`/strict structured outputs instead of plain JSON mode. OpenAI docs distinguish Structured Outputs from JSON mode: JSON mode gives valid JSON, not schema adherence. | HIGH |
| Pydantic | 2.x | Runtime validation and schema definitions | Define every LLM contract as a Pydantic model, then validate before database writes. This gives typed schemas, enum constraints, schema versioning, and safer refactors. | HIGH |
| tiktoken | 0.12.0 current PyPI release | Token estimation/cost controls | Use for rough budget planning and chunk sizing. Treat counts as estimates when model tokenization changes. | MEDIUM |
- `TopicPlan`: hypotheses, keywords, negative keywords, candidate subreddits, labels.
- `RelevanceJudgement`: relevant, reason, confidence, topic fit, market fit, quality.
- `MarketSignal`: persona, pain point, urgency, buying signal, evidence quote, interpretation.
- `ReportSection`: section type, claims, evidence item IDs, caveats.
### Configuration and Secrets
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| pydantic-settings | Latest 2.x matching Pydantic | Typed config loading | Official Pydantic settings package reads environment variables/secrets into typed settings models. Good fit for Reddit credentials, database URLs, LLM provider config, and feature flags. | HIGH |
| python-dotenv | 1.2.2 current as of 2026-03-01 | Local `.env` loading | Developer convenience only. Do not rely on `.env` in production; use environment variables or a secret manager. | HIGH |
| Secret manager | Platform dependent | Production secrets | **Compliance-sensitive.** Reddit and LLM credentials should not live in repo, report output, logs, or database. Use environment/secrets injection locally; later use 1Password, Doppler, AWS Secrets Manager, GCP Secret Manager, or similar. | HIGH |
- `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`, `REDDIT_USER_AGENT`
- `REDDIT_ACCESS_MODE`
- `DATABASE_URL`
- `OPENAI_API_KEY`, `LLM_MODEL`, `EMBEDDING_MODEL`
- `RETENTION_POLICY_DAYS`, `DELETE_REDDIT_DELETED_WITHIN_HOURS`
- `LOG_LEVEL`, `RUN_ENV`
### CLI and Orchestration
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| Typer | Current stable | CLI app | Type-hint-driven commands, clear help text, and easy migration from scripts to grouped commands. Better than raw `argparse` for this multi-command workflow. | HIGH |
| Rich | Current stable | CLI output | Progress bars, tables, tracebacks, and readable run summaries. Keep machine-readable logs separate. | MEDIUM |
| Database-backed run state | Internal tables | Pipeline orchestration | For MVP, explicit commands plus persistent statuses are enough. Add a task queue only when runs need scheduling, retries across processes, or concurrency. | HIGH |
### Testing and Quality
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| pytest | 9.0 stable docs; 9.1 draft exists | Unit/integration tests | Standard Python testing tool. Use for models, cleaning rules, SQLAlchemy repositories, LLM schema validation, and CLI commands. | HIGH |
| pytest-cov | Current stable | Coverage reports | Track coverage on deterministic pipeline logic. Do not chase coverage on provider SDK calls. | MEDIUM |
| respx or pytest-httpx | Match HTTP client use | Mock HTTP APIs | Useful for OpenAI/provider wrappers. PRAW is higher-level, so prefer small collector integration tests with recorded fixtures rather than mocking internals heavily. | MEDIUM |
| VCR.py | Current stable | Recorded API fixtures | Useful for stable, sanitized Reddit/OpenAI HTTP fixtures if legal and safe. Scrub secrets, user identifiers, and content that should not be retained. | MEDIUM |
| testcontainers-python | Current stable | PostgreSQL/pgvector integration tests | Use for migration and repository tests against real Postgres rather than SQLite. SQLite will hide JSONB/vector/index behavior. | MEDIUM |
- Compliance gates: user-agent required, OAuth config required, access mode recorded, rate-limit headers logged.
- Deduplication: repeated collection does not duplicate posts/comments.
- Retention/deletion: deleted/removed markers clear content fields according to policy.
- LLM contracts: invalid/missing fields fail closed before persistence.
- Report evidence: every report claim that cites Reddit evidence links back to item IDs.
### Logging, Observability, and Audit
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| structlog | 25.5.0 docs current | Structured logs | Good fit for run IDs, project IDs, request IDs, provider/model names, cost estimates, rate-limit fields, and JSON logs. | HIGH |
| stdlib logging bridge | Built in | Library integration | Route PRAW/SQLAlchemy/application logs consistently. Avoid print-debugging pipeline stages. | HIGH |
| OpenTelemetry | Defer unless deployed service | Traces/metrics | Not necessary for local MVP. Add later if running scheduled/background jobs or a service. | MEDIUM |
- `event`, `project_id`, `run_id`, `stage`, `query_id`
- `reddit_endpoint`, `subreddit`, `keyword`
- `x_ratelimit_used`, `x_ratelimit_remaining`, `x_ratelimit_reset`
- `llm_provider`, `llm_model`, `schema_version`, `prompt_version`, `input_tokens`, `output_tokens`, `cost_estimate`
- `item_count_in`, `item_count_out`, `reject_reason`
### Report Generation
| Technology | Version Guidance | Purpose | Why | Confidence |
|------------|------------------|---------|-----|------------|
| Jinja2 | 3.x | Report templating | Use templates for repeatable Markdown/HTML report sections with explicit evidence loops and caveats. | HIGH |
| Markdown | Plain Markdown as primary output | Human-readable MVP report | Markdown is diffable, easy to inspect, and can be converted later. Make it the canonical report artifact. | HIGH |
| python-docx | 1.2.0 | Optional Word export | Use for business-facing `.docx` exports after Markdown stabilizes. Good for simple structured Word output. | HIGH |
| ReportLab | 4.4.x | Optional PDF export | Use only when direct PDF generation is required. For MVP, Markdown/HTML is faster to iterate. | MEDIUM |
| pandas | 3.0.1 | Tables and CSV appendices | Use for dataset summaries, counts by subreddit/persona/pain point, and evidence tables. | HIGH |
## Alternatives Considered
| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Reddit access | PRAW + Reddit Data API | Browser scraping / unofficial archives | Compliance risk, weak provenance, deletion-retention conflicts, and likely fragility. |
| Reddit client | PRAW | Async PRAW | Worthwhile later for high-volume async collection, but extra complexity for MVP. |
| Storage | PostgreSQL + JSONB + pgvector | SQLite | SQLite is convenient but hides production issues around JSONB, constraints, concurrency, and vectors. |
| Vector DB | pgvector | Pinecone/Weaviate/Qdrant | Separate vector DB is overkill until vector volume/search latency justifies operating another service. |
| ORM | SQLAlchemy 2.0 | Django ORM | No web app yet; SQLAlchemy is lighter and better suited to CLI/data pipeline boundaries. |
| Migrations | Alembic | Manual SQL files only | Manual migrations drift quickly as schema expands. Alembic integrates with SQLAlchemy models. |
| LLM contracts | OpenAI Structured Outputs + Pydantic | Plain prompting / JSON mode | JSON mode does not guarantee schema adherence. Plain prompts are too brittle for persistence. |
| LLM framework | Thin provider module | LangChain/LlamaIndex/agents | Adds abstraction and dependency churn without solving the core pipeline problem. |
| Orchestration | Typer commands + DB run state | Airflow/Dagster/Prefect/Celery | Premature until scheduled multi-run production operation exists. |
| Reports | Markdown + Jinja2 | LLM freeform documents | Templates preserve structure, evidence links, and repeatability. |
## Installation Sketch
## Compliance-Sensitive Defaults
- Fail startup if Reddit User-Agent is missing or generic.
- Fail startup if access mode is missing.
- Never implement posting, commenting, messaging, voting, follow/unfollow, account creation, or subreddit manipulation.
- Store enough request metadata to prove rate-limit behavior.
- Add retention/deletion handling before broad collection.
- Keep raw author-identifying fields separate so they can be deleted without destroying aggregate analysis.
- Mark report claims as `observed`, `inferred`, or `recommendation`.
- Keep prompt/model/schema versions for every LLM judgement.
## Source Notes
| Area | Source | Confidence |
|------|--------|------------|
| Reddit API rules, OAuth, User-Agent, deletion, rate limits | Reddit Data API Wiki, updated 2026-05-11: https://support.reddithelp.com/hc/en-us/articles/16160319875092-Reddit-Data-API-Wiki | HIGH |
| PRAW docs and current docs version | PRAW 7.7.1 docs: https://praw.readthedocs.io/en/stable/index.html | HIGH |
| PRAW read-only/script app patterns | Context7 `/websites/praw_readthedocs_io_en_stable`; PRAW docs: https://praw.readthedocs.io/en/stable/getting_started/quick_start.html | HIGH |
| SQLAlchemy 2.0 current docs/release | SQLAlchemy 2.0 docs: https://docs.sqlalchemy.org/en/20/ | HIGH |
| SQLAlchemy typed declarative/session patterns | Context7 `/websites/sqlalchemy_en_20`; SQLAlchemy ORM docs: https://docs.sqlalchemy.org/en/20/orm/ | HIGH |
| Alembic autogenerate | Context7 `/websites/alembic_sqlalchemy`; Alembic docs: https://alembic.sqlalchemy.org/en/latest/autogenerate.html | HIGH |
| Psycopg 3 current generation | Psycopg official site/docs: https://www.psycopg.org/ and https://www.psycopg.org/psycopg3/docs/ | HIGH |
| pgvector extension and HNSW | pgvector GitHub: https://github.com/pgvector/pgvector | HIGH |
| pgvector Python SQLAlchemy adapter | pgvector PyPI: https://pypi.org/project/pgvector/ | HIGH |
| OpenAI Structured Outputs vs JSON mode | OpenAI API docs: https://platform.openai.com/docs/guides/structured-outputs | HIGH |
| OpenAI Python SDK current PyPI version | OpenAI PyPI: https://pypi.org/project/openai/ | HIGH |
| Pydantic settings | Pydantic docs: https://pydantic.dev/docs/latest/concepts/pydantic_settings/ | HIGH |
| python-dotenv current release | PyPI: https://pypi.org/project/python-dotenv/ | HIGH |
| uv project manager | uv docs: https://docs.astral.sh/uv/ | HIGH |
| Typer CLI | Typer docs: https://typer.tiangolo.com/ | HIGH |
| structlog current docs | structlog docs: https://www.structlog.org/en/stable/ | HIGH |
| pandas current version | pandas site: https://pandas.pydata.org/ | HIGH |
| scikit-learn current docs | scikit-learn docs: https://sklearn.org/stable/install.html | HIGH |
| python-docx current docs | python-docx docs: https://python-docx.readthedocs.io/en/latest/index.html | HIGH |
| ReportLab release/docs | ReportLab docs/PyPI: https://docs.reportlab.com/ and https://pypi.org/project/reportlab/ | MEDIUM |
## Open Questions for Later Phases
- Exact Reddit access tier for any commercial use: validate with Reddit terms/contact before using this for production commercial data collection.
- Retention policy details: legal/compliance review should decide whether to store raw content longer than the 48-hour recommendation and under what authorization.
- Embedding provider/model: choose during implementation based on cost, multilingual quality for English/German, dimensions, and structured privacy requirements.
- PDF export: decide whether business users need PDF in MVP or whether Markdown/DOCX is sufficient.
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:skills-start source:skills/ -->
## Project Skills

No project skills found. Add skills to any of: `.claude/skills/`, `.agents/skills/`, `.cursor/skills/`, `.github/skills/`, or `.codex/skills/` with a `SKILL.md` index file.
<!-- GSD:skills-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd-quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd-debug` for investigation and bug fixing
- `/gsd-execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->



<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd-profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->
