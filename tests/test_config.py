"""Tests for config loading and models."""

from __future__ import annotations

from pathlib import Path

from bouquet.config import BouquetSettings, load_config


def test_default_settings() -> None:
    settings = BouquetSettings()
    assert settings.project.name == "default"
    assert settings.project.base_branch == "main"
    assert settings.agent.command == "claude"
    assert settings.tmux.session_prefix == "bouquet"
    assert settings.bootstrap.use_cow_clone is True


def test_load_config_from_file(bouquet_toml: Path, tmp_git_repo: Path) -> None:
    settings = load_config(config_path=bouquet_toml, repo_path=tmp_git_repo)
    assert settings.project.name == "my-test-project"
    assert settings.agent.command == "echo"
    assert settings.agent.args == ["hello"]
    assert settings.bootstrap.copy_env_files == []


def test_load_config_from_repo_root(bouquet_toml: Path, tmp_git_repo: Path) -> None:
    # load_config should find .bouquet.toml in repo root
    settings = load_config(repo_path=tmp_git_repo)
    assert settings.project.name == "my-test-project"


def test_load_config_defaults_when_no_file(tmp_path: Path) -> None:
    settings = load_config(repo_path=tmp_path)
    assert settings.project.name == "default"


def test_repo_path_override(bouquet_toml: Path, tmp_git_repo: Path) -> None:
    settings = load_config(config_path=bouquet_toml, repo_path=tmp_git_repo)
    assert settings.project.repo_path == str(tmp_git_repo)


def test_default_services_empty() -> None:
    settings = BouquetSettings()
    assert settings.services == []


def test_default_layout_none() -> None:
    settings = BouquetSettings()
    assert settings.tmux.layout is None


def test_services_from_toml(tmp_git_repo: Path) -> None:
    config = tmp_git_repo / ".bouquet.toml"
    config.write_text("""\
[project]
name = "svc-test"

[[services]]
name = "api"
command = "uvicorn app:main --port {{ 8000 + BOUQUET_WORKTREE_INDEX }}"

[[services]]
name = "worker"
command = "celery -A app worker"

[tmux]
session_prefix = "bouquet"
layout = "main-vertical"
""")
    settings = load_config(repo_path=tmp_git_repo)
    assert len(settings.services) == 2
    assert settings.services[0].name == "api"
    assert "8000" in settings.services[0].command
    assert settings.services[1].name == "worker"
    assert settings.tmux.layout == "main-vertical"
