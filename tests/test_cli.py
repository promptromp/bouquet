"""Tests for CLI argument resolution (no tmux required)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from bouquet.cli import _build_tui_command, _resolve_project_name, cli
from bouquet.config import BouquetSettings
from bouquet.models import SessionState


@patch("bouquet.cli.TmuxManager")
def test_start_no_args_with_config(mock_tmux_cls: MagicMock, tmp_git_repo: Path) -> None:
    """Running 'bouquet start' in a repo with .bouquet.toml should work."""
    (tmp_git_repo / ".bouquet.toml").write_text('[project]\nname = "my-proj"\n')

    mock_tmux = mock_tmux_cls.return_value
    mock_tmux.session_exists.return_value = False
    mock_tmux.is_inside_tmux.return_value = False

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_git_repo.parent):
        # Simulate running from the repo root
        result = runner.invoke(cli, ["start", "--repo", str(tmp_git_repo)])

    # Should not error — it found the project name from config
    assert result.exit_code == 0 or "Attaching" in (result.output or "")
    mock_tmux.create_session.assert_called_once()


@patch("bouquet.cli.TmuxManager")
def test_start_no_args_no_config_errors(mock_tmux_cls: MagicMock, tmp_git_repo: Path) -> None:
    """Running 'bouquet start' without .bouquet.toml should error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--repo", str(tmp_git_repo)])

    assert result.exit_code != 0
    assert "no project name" in result.output.lower() or "no .bouquet.toml" in result.output.lower()


def test_start_not_git_repo_errors(tmp_path: Path) -> None:
    """Running 'bouquet start' in a non-git directory should error."""
    not_a_repo = tmp_path / "not-repo"
    not_a_repo.mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--repo", str(not_a_repo)])

    assert result.exit_code != 0
    assert "not a git repository" in result.output.lower()


@patch("bouquet.cli.TmuxManager")
def test_start_explicit_project_name(mock_tmux_cls: MagicMock, tmp_git_repo: Path) -> None:
    """Passing an explicit project name should work even without .bouquet.toml."""
    mock_tmux = mock_tmux_cls.return_value
    mock_tmux.session_exists.return_value = False
    mock_tmux.is_inside_tmux.return_value = False

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "my-project", "--repo", str(tmp_git_repo)])

    assert result.exit_code == 0 or "Attaching" in (result.output or "")
    mock_tmux.create_session.assert_called_once()


@patch("bouquet.cli.TmuxManager")
@patch("bouquet.cli.SessionState.load", return_value=None)
def test_stop_no_args_with_config(mock_load: MagicMock, mock_tmux_cls: MagicMock, tmp_git_repo: Path) -> None:
    """Running 'bouquet stop' with .bouquet.toml should infer project name."""
    (tmp_git_repo / ".bouquet.toml").write_text('[project]\nname = "my-proj"\n')

    runner = CliRunner()
    result = runner.invoke(cli, ["stop", "--repo", str(tmp_git_repo)])

    # It should resolve the project name from config and try to load state
    mock_load.assert_called_once_with("my-proj")
    assert result.exit_code != 0
    assert "no session state found" in result.output.lower()


def test_stop_no_args_no_config_errors(tmp_git_repo: Path) -> None:
    """Running 'bouquet stop' without .bouquet.toml should error."""
    runner = CliRunner()
    result = runner.invoke(cli, ["stop", "--repo", str(tmp_git_repo)])

    assert result.exit_code != 0
    assert "no project name" in result.output.lower() or "no .bouquet.toml" in result.output.lower()


@patch("bouquet.cli.create_backend")
@patch("bouquet.cli.TmuxManager")
def test_stop_reconciles_stale_tasks(
    mock_tmux_cls: MagicMock, mock_create_backend: MagicMock, tmp_git_repo: Path, tmp_path: Path
) -> None:
    """bouquet stop should reset all IN_PROGRESS tasks via reconcile_stale(set())."""
    (tmp_git_repo / ".bouquet.toml").write_text('[project]\nname = "my-proj"\n')

    # Create a real session state file
    state = SessionState(
        project_name="my-proj",
        tmux_session_name="bouquet-my-proj",
        repo_path=tmp_git_repo,
        created_at=datetime(2026, 3, 20, 10, 0),
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mock_backend = mock_create_backend.return_value

    with patch.object(SessionState, "state_dir", return_value=state_dir):
        state.save()
        runner = CliRunner()
        result = runner.invoke(cli, ["stop", "--repo", str(tmp_git_repo)])

    assert result.exit_code == 0
    mock_backend.reconcile_stale.assert_called_once_with(set())


@patch("bouquet.cli.create_backend")
@patch("bouquet.cli.TmuxManager")
def test_stop_with_explicit_name_reconciles(
    mock_tmux_cls: MagicMock, mock_create_backend: MagicMock, tmp_git_repo: Path, tmp_path: Path
) -> None:
    """bouquet stop <name> should also reconcile tasks."""
    state = SessionState(
        project_name="my-proj",
        tmux_session_name="bouquet-my-proj",
        repo_path=tmp_git_repo,
        created_at=datetime(2026, 3, 20, 10, 0),
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    mock_backend = mock_create_backend.return_value

    with patch.object(SessionState, "state_dir", return_value=state_dir):
        state.save()
        runner = CliRunner()
        result = runner.invoke(cli, ["stop", "my-proj"])

    assert result.exit_code == 0
    mock_backend.reconcile_stale.assert_called_once_with(set())


# --- CLI helper function tests ---


def test_build_tui_command_basic(tmp_path: Path) -> None:
    """_build_tui_command produces a valid command without config."""
    repo = tmp_path / "repo"
    cmd = _build_tui_command(None, repo)
    assert "-m" in cmd
    assert "bouquet.tui.app" in cmd
    assert str(repo) in cmd
    assert "--config" not in cmd


def test_build_tui_command_with_config(tmp_path: Path) -> None:
    """_build_tui_command includes --config when config_path is given."""
    repo = tmp_path / "repo"
    config = tmp_path / "config.toml"
    cmd = _build_tui_command(config, repo)
    assert "--config" in cmd
    assert str(config) in cmd


def test_resolve_project_name_explicit() -> None:
    """Explicit name takes priority."""
    settings = BouquetSettings()
    name = _resolve_project_name("explicit", settings, Path("/tmp"))
    assert name == "explicit"


def test_resolve_project_name_from_config() -> None:
    """Config-provided name is used when no explicit name."""
    settings = BouquetSettings()
    settings.project.name = "from-config"
    name = _resolve_project_name(None, settings, Path("/tmp"))
    assert name == "from-config"
