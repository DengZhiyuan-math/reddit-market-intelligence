from pathlib import Path

from app.config import Settings


def test_settings_project_runtime_defaults() -> None:
    settings = Settings(_env_file=None)

    assert settings.project_registry_path == Path("outputs/projects/projects.json")
    assert settings.default_run_limit == 100


def test_settings_project_runtime_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("PROJECT_REGISTRY_PATH", "tmp/custom-projects.json")
    monkeypatch.setenv("DEFAULT_RUN_LIMIT", "25")

    settings = Settings(_env_file=None)

    assert settings.project_registry_path == Path("tmp/custom-projects.json")
    assert settings.default_run_limit == 25
