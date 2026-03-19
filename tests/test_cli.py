"""Tests for CLI argument resolution (no tmux required)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from bouquet.cli import cli


@patch("bouquet.cli.TmuxManager")
def test_start_no_args_with_config(mock_tmux_cls: MagicMock, tmp_path: Path) -> None:
    """Running 'bouquet start' in a repo with .bouquet.toml should work."""
    repo = _make_git_repo(tmp_path / "repo")
    (repo / ".bouquet.toml").write_text('[project]\nname = "my-proj"\n')

    mock_tmux = mock_tmux_cls.return_value
    mock_tmux.session_exists.return_value = False
    mock_tmux.is_inside_tmux.return_value = False

    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path):
        # Simulate running from the repo root
        result = runner.invoke(cli, ["start", "--repo", str(repo)])

    # Should not error — it found the project name from config
    assert result.exit_code == 0 or "Attaching" in (result.output or "")
    mock_tmux.create_session.assert_called_once()


@patch("bouquet.cli.TmuxManager")
def test_start_no_args_no_config_errors(mock_tmux_cls: MagicMock, tmp_path: Path) -> None:
    """Running 'bouquet start' without .bouquet.toml should error."""
    repo = _make_git_repo(tmp_path / "repo")

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "--repo", str(repo)])

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
def test_start_explicit_project_name(mock_tmux_cls: MagicMock, tmp_path: Path) -> None:
    """Passing an explicit project name should work even without .bouquet.toml."""
    repo = _make_git_repo(tmp_path / "repo")

    mock_tmux = mock_tmux_cls.return_value
    mock_tmux.session_exists.return_value = False
    mock_tmux.is_inside_tmux.return_value = False

    runner = CliRunner()
    result = runner.invoke(cli, ["start", "my-project", "--repo", str(repo)])

    assert result.exit_code == 0 or "Attaching" in (result.output or "")
    mock_tmux.create_session.assert_called_once()


@patch("bouquet.cli.TmuxManager")
@patch("bouquet.cli.SessionState.load", return_value=None)
def test_stop_no_args_with_config(mock_load: MagicMock, mock_tmux_cls: MagicMock, tmp_path: Path) -> None:
    """Running 'bouquet stop' with .bouquet.toml should infer project name."""
    repo = _make_git_repo(tmp_path / "repo")
    (repo / ".bouquet.toml").write_text('[project]\nname = "my-proj"\n')

    runner = CliRunner()
    result = runner.invoke(cli, ["stop", "--repo", str(repo)])

    # It should resolve the project name from config and try to load state
    mock_load.assert_called_once_with("my-proj")
    assert result.exit_code != 0
    assert "no session state found" in result.output.lower()


def test_stop_no_args_no_config_errors(tmp_path: Path) -> None:
    """Running 'bouquet stop' without .bouquet.toml should error."""
    repo = _make_git_repo(tmp_path / "repo")

    runner = CliRunner()
    result = runner.invoke(cli, ["stop", "--repo", str(repo)])

    assert result.exit_code != 0
    assert "no project name" in result.output.lower() or "no .bouquet.toml" in result.output.lower()


def _make_git_repo(path: Path) -> Path:
    """Create a minimal git repo with an initial commit."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=path, capture_output=True, check=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run(["git", "add", "."], cwd=path, capture_output=True, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, capture_output=True, check=True)
    return path
