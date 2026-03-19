"""CLI entry point for Bouquet — Click commands."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click

from bouquet import __version__
from bouquet.config import TEMPLATE_CONFIG, BouquetSettings, load_config
from bouquet.git import is_git_repo
from bouquet.models import SessionState
from bouquet.tmux import TmuxManager
from bouquet.worktree import WorktreeManager


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """Bouquet — orchestration layer for agentic coding."""


@cli.command()
@click.argument("project_name")
@click.option("--repo", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None)
def start(project_name: str, repo: Path | None, config_path: Path | None) -> None:
    """Start a Bouquet session for a project.

    Creates a tmux session with an orchestrator TUI for managing
    worktree-backed coding windows.
    """
    # Load config
    settings = load_config(config_path=config_path, repo_path=repo)

    # Override project name from CLI
    settings.project.name = project_name

    # Resolve repo path
    repo_path = Path(settings.project.repo_path).resolve()
    if not repo_path.exists():
        click.echo(f"Error: repo path '{repo_path}' does not exist.", err=True)
        sys.exit(1)
    if not is_git_repo(repo_path):
        click.echo(f"Error: '{repo_path}' is not a git repository.", err=True)
        sys.exit(1)

    settings.project.repo_path = str(repo_path)

    # Build session name
    session_name = f"{settings.tmux.session_prefix}-{project_name}"

    # Check for existing session
    tmux = TmuxManager()
    if tmux.session_exists(session_name):
        click.echo(f"Session '{session_name}' already exists. Attaching...")
        tmux.attach_session(session_name)
        return  # exec replaces process; this line is never reached

    # Check if inside tmux (MVP: error out)
    if tmux.is_inside_tmux():
        click.echo(
            "Error: already inside a tmux session. Run `bouquet start` from outside tmux.",
            err=True,
        )
        sys.exit(1)

    # Create session state
    state = SessionState(
        project_name=project_name,
        tmux_session_name=session_name,
        repo_path=repo_path,
        created_at=datetime.now(),
    )
    state.save()

    # Create tmux session
    tmux.create_session(session_name, start_directory=repo_path)

    # Adopt any existing git worktrees into the session
    manager = WorktreeManager(settings, state, tmux)
    adopted = manager.adopt_existing()
    if adopted:
        branches = [w.branch for w in adopted]
        click.echo(f"Adopted {len(adopted)} existing worktree(s): {', '.join(branches)}")

    # Build the command to launch the TUI in window 0
    tui_cmd = _build_tui_command(config_path, repo_path)
    tmux.send_keys(session_name, "orchestrator", tui_cmd)

    click.echo(f"Created session '{session_name}'. Attaching...")
    tmux.attach_session(session_name)


def _build_tui_command(config_path: Path | None, repo_path: Path) -> str:
    """Build the shell command to launch the TUI."""
    parts = [sys.executable, "-m", "bouquet.tui.app", "--repo", str(repo_path)]
    if config_path:
        parts.extend(["--config", str(config_path)])
    return " ".join(parts)


@cli.command()
@click.argument("project_name")
def stop(project_name: str) -> None:
    """Stop a Bouquet session — remove worktrees and kill tmux session."""
    state = SessionState.load(project_name)
    if state is None:
        click.echo(f"No session state found for '{project_name}'.", err=True)
        sys.exit(1)

    click.echo(f"Stopping session '{state.tmux_session_name}'...")

    # Load config for settings
    settings = BouquetSettings()
    settings.project.repo_path = str(state.repo_path)

    # Create manager and remove all worktrees
    tmux = TmuxManager()
    manager = WorktreeManager(settings, state, tmux)
    manager.remove_all()

    # Kill tmux session
    tmux.kill_session(state.tmux_session_name)

    # Delete state file
    state.delete_state()

    click.echo("Session stopped and cleaned up.")


@cli.command()
@click.option("--repo", type=click.Path(exists=True, path_type=Path), default=None)
def init(repo: Path | None) -> None:
    """Generate a .bouquet.toml template in the repo root."""
    repo_path = (repo or Path.cwd()).resolve()

    config_file = repo_path / ".bouquet.toml"
    if config_file.exists():
        click.echo(f"Config file already exists: {config_file}")
        sys.exit(1)

    project_name = repo_path.name
    config_file.write_text(TEMPLATE_CONFIG.format(name=project_name))

    click.echo(f"Created {config_file}")
    click.echo()
    click.echo("Edit the file to customize your project settings, then run:")
    click.echo(f"  bouquet start {project_name}")
