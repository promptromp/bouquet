"""OrchestratorApp — the main Textual TUI for Bouquet."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static
from textual.work import work

from bouquet.config import BouquetSettings, load_config
from bouquet.models import SessionState
from bouquet.tmux import TmuxManager
from bouquet.tui.screens import NewWorktreeScreen
from bouquet.tui.widgets import ProjectHeader, WorktreeTable
from bouquet.worktree import WorktreeManager


class OrchestratorApp(App):
    """Bouquet orchestrator TUI — runs in tmux window 0."""

    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("n", "new_worktree", "New worktree"),
        Binding("enter", "switch_worktree", "Switch to window"),
        Binding("d", "delete_worktree", "Delete worktree"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        settings: BouquetSettings,
        state: SessionState,
        manager: WorktreeManager,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.session_state = state
        self.manager = manager

    def compose(self) -> ComposeResult:
        yield ProjectHeader(self.settings.project.name)
        with Vertical(id="body"):
            yield Static("Active Worktrees", id="section-title")
            yield WorktreeTable()
        yield Static(
            "[N] New worktree  [Enter] Switch  [D] Delete  [R] Refresh  [Q] Quit",
            id="footer-bar",
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()

    def _refresh_table(self) -> None:
        table = self.query_one(WorktreeTable)
        table.refresh_worktrees(self.manager.list_active())

    def action_new_worktree(self) -> None:
        """Open the new worktree dialog."""
        base = self.settings.project.base_branch

        def on_result(result: tuple[str, str] | None) -> None:
            if result is not None:
                branch, base_branch = result
                self._create_worktree(branch, base_branch)

        self.push_screen(NewWorktreeScreen(default_base=base), callback=on_result)

    @work(thread=True)
    def _create_worktree(self, branch: str, base_branch: str) -> None:
        """Create a worktree in a background thread."""
        try:
            self.manager.create(branch, base_branch)
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Worktree '{branch}' created")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error creating worktree: {e}", severity="error")

    def action_switch_worktree(self) -> None:
        """Switch to the tmux window for the selected worktree."""
        table = self.query_one(WorktreeTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_data = table.get_row_at(table.cursor_row)
            branch = str(row_data[1])  # Column 1 is Branch
            try:
                self.manager.switch_to(branch)
            except Exception as e:
                self.notify(f"Error switching: {e}", severity="error")

    def action_delete_worktree(self) -> None:
        """Delete the selected worktree."""
        table = self.query_one(WorktreeTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_data = table.get_row_at(table.cursor_row)
            branch = str(row_data[1])  # Column 1 is Branch
            self._remove_worktree(branch)

    @work(thread=True)
    def _remove_worktree(self, branch: str) -> None:
        """Remove a worktree in a background thread."""
        try:
            self.manager.remove(branch)
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Worktree '{branch}' removed")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error removing worktree: {e}", severity="error")

    def action_refresh(self) -> None:
        """Refresh the worktree table."""
        self._refresh_table()


def _run_tui(repo_path: Path, config_path: Path | None = None) -> None:
    """Launch the TUI — called from within a tmux window."""
    settings = load_config(config_path=config_path, repo_path=repo_path)
    settings.project.repo_path = str(repo_path)

    # Determine project/session from the current tmux environment
    project_name = settings.project.name
    state = SessionState.load(project_name)
    if state is None:
        # Fallback: discover from tmux session name
        tmux_session = os.environ.get("TMUX_SESSION", "")
        prefix = settings.tmux.session_prefix + "-"
        if tmux_session.startswith(prefix):
            project_name = tmux_session[len(prefix) :]
            state = SessionState.load(project_name)

    if state is None:
        click.echo("Error: could not find session state.", err=True)
        sys.exit(1)

    tmux = TmuxManager()
    manager = WorktreeManager(settings, state, tmux)

    app = OrchestratorApp(settings, state, manager)
    app.run()


@click.command()
@click.option("--repo", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--config", "config_path", type=click.Path(exists=True, path_type=Path), default=None)
def main(repo: Path, config_path: Path | None) -> None:
    """Launch the Bouquet TUI (internal — called from within tmux)."""
    _run_tui(repo.resolve(), config_path)


if __name__ == "__main__":
    main()
