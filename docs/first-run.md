# First run

For an existing database project, use the [research run guide](run-research.md).
Reuse its database and model configuration.

## Install and configure

```bash
uv sync --frozen
uv run reddit-market-intel --help
uv run pytest -q
uv run ruff check app tests
cp .env.example .env
```

Edit the private `.env`. Set `DATABASE_URL` to your existing database when available.
Do not copy login secrets or commit `.env`.

## Database setup

The packaged PostgreSQL service can be started with:

```bash
docker compose up -d postgres
uv run reddit-market-intel db upgrade
uv run reddit-market-intel db status
```

`db preflight` checks connectivity, migrations, CLI imports, and Reddit credential
settings. Missing OAuth credentials can be expected when using the in-app browser.
The automated test suite does not establish PostgreSQL acceptance.

The migration chain has a known duplicate `discovered_urls` creation issue on
fresh SQLite databases. For a new local SQLite database only, configure its URL
and use the same native SQLAlchemy setup as the test fixtures:

```bash
uv run python - <<'PY'
from app.config import Settings
from app.db.base import Base
from app.db.engine import create_database_engine
import app.db.models
Base.metadata.create_all(create_database_engine(Settings()))
PY
```

This does not migrate an existing database or validate PostgreSQL migrations.

## Create a project once

Set `RESEARCH_TOPIC` and `RESEARCH_REGION` to your own research scope.
Choose the access mode appropriate to your permitted use.

```bash
uv run reddit-market-intel projects create \
  --topic "$RESEARCH_TOPIC" --region "$RESEARCH_REGION" \
  --language en --access-mode personal
uv run reddit-market-intel projects import-json
```

Use the registry that matches your database. Set `PROJECT_ID` to the returned ID.
Do not import a separate registry over an existing project.

## Model and source access

The pipeline uses the configured authenticated Codex CLI by default.
It can also use a configured Responses endpoint. Standalone stages keep explicit
deterministic modes. A model name alone does not prove a real call.

For official Reddit API collection, configure your own `REDDIT_CLIENT_ID`,
`REDDIT_CLIENT_SECRET`, and descriptive `REDDIT_USER_AGENT`, then run:

```bash
uv run reddit-market-intel reddit validate-credentials
```

The in-app browser workflow does not require these OAuth credentials.
Continue with [the run guide](run-research.md).

If console-script metadata is stale, refresh the local package:

```bash
uv run --reinstall-package reddit-market-intel reddit-market-intel --help
```
