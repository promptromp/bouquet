"""CLI entry point for Bouquet — Click commands."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import click

from bouquet import __version__
from bouquet.config import TEMPLATE_CONFIG, BouquetSettings, load_config
from bouquet.git import get_repo_root, is_git_repo
from bouquet.models import SessionState
from bouquet.tasks import create_backend
from bouquet.tmux import TmuxManager
from bouquet.worktree import WorktreeManager


@click.group()
@click.version_option(version=__version__)
def cli() -> None:
    """Bouquet — orchestration layer for agentic coding."""


@cli.command()
@click.argument("project_name", required=False, default=None)
@click.option("--repo", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None)
def start(project_name: str | None, repo: Path | None, config_path: Path | None) -> None:
    """Start a Bouquet session for a project.

    Creates a tmux session with an orchestrator TUI for managing
    worktree-backed coding windows.

    When run without arguments, uses the current directory as the repo
    and reads project name from .bouquet.toml.
    """
    # Resolve repo path: explicit --repo, or cwd
    repo_path = _resolve_repo_path(repo)

    # Load config
    settings = load_config(config_path=config_path, repo_path=repo_path)

    # Resolve project name: explicit arg > config file > error
    project_name = _resolve_project_name(project_name, settings, repo_path)
    settings.project.name = project_name
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


def _resolve_repo_path(repo: Path | None) -> Path:
    """Resolve the repository path from --repo or cwd, validating it's a git repo root."""
    if repo is not None:
        repo_path = repo.resolve()
    else:
        cwd = Path.cwd().resolve()
        if not is_git_repo(cwd):
            click.echo(
                "Error: current directory is not a git repository. Run from a repo root or pass --repo.",
                err=True,
            )
            sys.exit(1)
        repo_path = get_repo_root(cwd)

    if not repo_path.exists():
        click.echo(f"Error: repo path '{repo_path}' does not exist.", err=True)
        sys.exit(1)
    if not is_git_repo(repo_path):
        click.echo(f"Error: '{repo_path}' is not a git repository.", err=True)
        sys.exit(1)
    return repo_path


def _resolve_project_name(name: str | None, settings: BouquetSettings, repo_path: Path) -> str:
    """Resolve the project name from CLI arg, config, or error out."""
    if name is not None:
        return name

    # Config file provided a non-default name
    if settings.project.name != "default":
        return settings.project.name

    # No config found — error
    click.echo(
        "Error: no project name given and no .bouquet.toml found. Run 'bouquet init' first or pass a project name.",
        err=True,
    )
    sys.exit(1)


def _build_tui_command(config_path: Path | None, repo_path: Path) -> str:
    """Build the shell command to launch the TUI."""
    parts = [sys.executable, "-m", "bouquet.tui.app", "--repo", str(repo_path)]
    if config_path:
        parts.extend(["--config", str(config_path)])
    return " ".join(parts)


@cli.command()
@click.argument("project_name", required=False, default=None)
@click.option("--repo", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None)
def stop(project_name: str | None, repo: Path | None, config_path: Path | None) -> None:
    """Stop a Bouquet session — remove worktrees and kill tmux session.

    When run without arguments, infers the project name from .bouquet.toml
    in the current directory.
    """
    if project_name is None:
        repo_path = _resolve_repo_path(repo)
        settings = load_config(config_path=config_path, repo_path=repo_path)
        project_name = _resolve_project_name(None, settings, repo_path)

    state = SessionState.load(project_name)
    if state is None:
        click.echo(f"No session state found for '{project_name}'.", err=True)
        sys.exit(1)

    click.echo(f"Stopping session '{state.tmux_session_name}'...")

    # Load real config from repo path
    settings = load_config(config_path=config_path, repo_path=state.repo_path)
    settings.project.repo_path = str(state.repo_path)

    # Create manager and remove all worktrees
    tmux = TmuxManager()
    manager = WorktreeManager(settings, state, tmux)
    manager.remove_all()

    # Reset all IN_PROGRESS tasks (no active worktrees after remove_all)
    backend = create_backend(settings.task_queue, project_name)
    backend.reconcile_stale(set())

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
    click.echo("  bouquet start")
