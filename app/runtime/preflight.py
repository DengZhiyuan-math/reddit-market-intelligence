"""Local preflight checks for live collection setup."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import importlib.util
from pathlib import Path
import shutil
import sys
import subprocess

from sqlalchemy.engine import make_url

from app.config import Settings
from app.reddit.client import RedditClientFactory


PreflightStatus = str
DatabaseStatusChecker = Callable[[str], tuple[str | None, str | None]]


@dataclass(frozen=True)
class PreflightCheck:
    """One operator-facing runtime readiness check."""

    name: str
    status: PreflightStatus
    detail: str
    remediation: str = ""


def run_preflight(
    *,
    settings: Settings,
    database_status_checker: DatabaseStatusChecker,
    project_root: Path | None = None,
) -> list[PreflightCheck]:
    """Run local setup checks without calling live Reddit APIs."""

    root = project_root or Path.cwd()
    checks = [
        _check_cli_import(root),
        _check_database_url(settings.database_url),
        _check_database_status(settings.database_url, database_status_checker),
        _check_docker_compose(),
        _check_reddit_settings(settings),
    ]
    return checks


def preflight_exit_code(checks: list[PreflightCheck]) -> int:
    """Return a shell exit code for preflight results."""

    return 1 if any(check.status == "fail" for check in checks) else 0


def _check_cli_import(project_root: Path) -> PreflightCheck:
    app_spec = importlib.util.find_spec("app")
    root_on_path = str(project_root.resolve()) in {str(Path(entry or ".").resolve()) for entry in sys.path}
    if app_spec is None:
        return PreflightCheck(
            name="cli_import",
            status="fail",
            detail="The local app package cannot be imported from the current Python path.",
            remediation=(
                "Run with `PYTHONPATH=. uv run reddit-market-intel ...` from the project root, "
                "or refresh the entrypoint with `uv run --reinstall-package reddit-market-intel "
                "reddit-market-intel ...`."
            ),
        )
    if not root_on_path:
        return PreflightCheck(
            name="cli_import",
            status="warn",
            detail="The app package imports, but the project root is not on sys.path.",
            remediation=(
                "If the console script loads stale package metadata, run with `PYTHONPATH=.` "
                "or reinstall the local package with uv."
            ),
        )
    return PreflightCheck(
        name="cli_import",
        status="pass",
        detail="The local app package imports from the current runtime.",
    )


def _check_database_url(database_url: str) -> PreflightCheck:
    try:
        parsed = make_url(database_url)
    except Exception as exc:
        return PreflightCheck(
            name="database_url",
            status="fail",
            detail=f"DATABASE_URL is not parseable: {exc}",
            remediation="Set DATABASE_URL to a valid SQLAlchemy URL, for example the Postgres URL in .env.example.",
        )
    return PreflightCheck(
        name="database_url",
        status="pass",
        detail=f"DATABASE_URL uses driver `{parsed.drivername}`.",
    )


def _check_database_status(
    database_url: str,
    database_status_checker: DatabaseStatusChecker,
) -> PreflightCheck:
    try:
        current, head = database_status_checker(database_url)
    except Exception as exc:
        return PreflightCheck(
            name="database_connection",
            status="fail",
            detail=f"Database status check failed: {exc}",
            remediation=(
                "Start Postgres, verify DATABASE_URL, or run `reddit-market-intel db upgrade` "
                "after the database is reachable."
            ),
        )

    if current != head:
        return PreflightCheck(
            name="database_connection",
            status="warn",
            detail=f"Database reachable but migration state is {current or 'none'}; head is {head or 'none'}.",
            remediation="Run `reddit-market-intel db upgrade` before live collection.",
        )
    return PreflightCheck(
        name="database_connection",
        status="pass",
        detail=f"Database reachable at migration {current or 'none'}.",
    )


def _check_docker_compose() -> PreflightCheck:
    docker = shutil.which("docker")
    docker_compose = shutil.which("docker-compose")
    if docker:
        try:
            compose_v2 = subprocess.run(
                [docker, "compose", "version"],
                capture_output=True,
                check=False,
                text=True,
                timeout=5,
            )
            compose_available = compose_v2.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            compose_available = False
        if not compose_available:
            return PreflightCheck(
                name="docker_compose",
                status="warn",
                detail="Docker CLI is installed, but `docker compose` is not available.",
                remediation=(
                    "Install Docker Compose v2, use legacy `docker-compose` if available, "
                    "or point DATABASE_URL at an already running PostgreSQL instance."
                ),
            )
        return PreflightCheck(
            name="docker_compose",
            status="pass",
            detail="Docker Compose v2 is available; use `docker compose up -d postgres`.",
        )
    if docker_compose:
        return PreflightCheck(
            name="docker_compose",
            status="pass",
            detail="Legacy docker-compose CLI is installed; use `docker-compose up -d postgres`.",
        )
    return PreflightCheck(
        name="docker_compose",
        status="warn",
        detail="No Docker Compose command was found on PATH.",
        remediation=(
            "Install Docker Desktop/Compose, start Postgres another way, or set DATABASE_URL "
            "to an existing PostgreSQL instance."
        ),
    )


def _check_reddit_settings(settings: Settings) -> PreflightCheck:
    status = RedditClientFactory.validate_settings(settings)
    if status.valid:
        return PreflightCheck(
            name="reddit_settings",
            status="pass",
            detail="Reddit credentials and User-Agent are configured for read-only collection.",
        )
    return PreflightCheck(
        name="reddit_settings",
        status="warn",
        detail="Reddit credentials are incomplete: " + ", ".join(status.reason_codes),
        remediation="Set REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, and a descriptive REDDIT_USER_AGENT in .env.",
    )
