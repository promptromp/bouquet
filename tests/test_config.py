"""Tests for config loading and models."""

from __future__ import annotations

from pathlib import Path

from bouquet.config import AgentProfile, BouquetSettings, load_config


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


def test_default_layout_services_top() -> None:
    settings = BouquetSettings()
    assert settings.tmux.layout == "services-top"


def test_default_agent_profiles_empty() -> None:
    settings = BouquetSettings()
    assert settings.agent.profiles == []
    assert settings.agent.default_profile == "claude"


def test_resolve_profile_with_defined_profiles() -> None:
    settings = BouquetSettings()
    settings.agent.profiles = [
        AgentProfile(name="claude", command="claude"),
        AgentProfile(name="aider", command="aider", args=["--model", "sonnet"]),
    ]
    profile = settings.agent.resolve_profile("aider")
    assert profile.name == "aider"
    assert profile.command == "aider"
    assert profile.args == ["--model", "sonnet"]


def test_resolve_profile_fallback_to_command_args() -> None:
    settings = BouquetSettings()
    settings.agent.command = "claude"
    settings.agent.args = ["--verbose"]
    # No profiles defined — should synthesize from command/args
    profile = settings.agent.resolve_profile()
    assert profile.command == "claude"
    assert profile.args == ["--verbose"]


def test_resolve_profile_default() -> None:
    settings = BouquetSettings()
    settings.agent.profiles = [
        AgentProfile(name="claude", command="claude"),
        AgentProfile(name="aider", command="aider"),
    ]
    settings.agent.default_profile = "claude"
    profile = settings.agent.resolve_profile()
    assert profile.name == "claude"


def test_resolve_profile_unknown_name_falls_back() -> None:
    settings = BouquetSettings()
    settings.agent.command = "claude"
    profile = settings.agent.resolve_profile("nonexistent")
    assert profile.name == "default"
    assert profile.command == "claude"


def test_profiles_from_toml(tmp_git_repo: Path) -> None:
    config = tmp_git_repo / ".bouquet.toml"
    config.write_text("""\
[project]
name = "profile-test"

[agent]
command = "claude"
default_profile = "aider"

[[agent.profiles]]
name = "claude"
command = "claude"

[[agent.profiles]]
name = "aider"
command = "aider"
args = ["--model", "sonnet"]
""")
    settings = load_config(repo_path=tmp_git_repo)
    assert len(settings.agent.profiles) == 2
    assert settings.agent.default_profile == "aider"
    assert settings.agent.profiles[1].name == "aider"
    assert settings.agent.profiles[1].args == ["--model", "sonnet"]


def test_default_python_version_none() -> None:
    settings = BouquetSettings()
    assert settings.bootstrap.python_version is None


def test_default_setup_commands_empty() -> None:
    settings = BouquetSettings()
    assert settings.bootstrap.setup_commands == []


def test_setup_commands_from_toml(tmp_git_repo: Path) -> None:
    config = tmp_git_repo / ".bouquet.toml"
    config.write_text("""\
[project]
name = "setup-test"

[bootstrap]
setup_commands = [
    "export TOKEN=abc",
    'export URL="https://example.com"',
]
""")
    settings = load_config(repo_path=tmp_git_repo)
    assert len(settings.bootstrap.setup_commands) == 2
    assert settings.bootstrap.setup_commands[0] == "export TOKEN=abc"
    assert "https://example.com" in settings.bootstrap.setup_commands[1]


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
