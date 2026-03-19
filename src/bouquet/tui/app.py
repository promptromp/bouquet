"""OrchestratorApp — the main Textual TUI for Bouquet."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import click
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Static

from bouquet.activity import POLLABLE_STATUSES, ActivityMonitor
from bouquet.agents import AgentAdapter, ClaudeCodeAdapter
from bouquet.config import BouquetSettings, load_config
from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus
from bouquet.tmux import TmuxManager
from bouquet.tui.screens import (
    BroadcastInputScreen,
    BroadcastResultsScreen,
    ConfirmQuitScreen,
    NewWorktreeScreen,
    SendPromptScreen,
)
from bouquet.tui.widgets import ProjectHeader, WorktreeTable
from bouquet.worktree import WorktreeManager


class OrchestratorApp(App):
    """Bouquet orchestrator TUI — runs in tmux window 0."""

    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("n", "new_worktree", "New worktree"),
        Binding("s", "switch_worktree", "Switch to window"),
        Binding("d", "delete_worktree", "Delete worktree"),
        Binding("b", "broadcast", "Broadcast"),
        Binding("t", "status", "Status"),
        Binding("p", "send_prompt", "Send prompt"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        settings: BouquetSettings,
        state: SessionState,
        manager: WorktreeManager,
        agent: AgentAdapter | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.session_state = state
        self.manager = manager
        self.agent = agent or ClaudeCodeAdapter(max_turns=3)
        self._activity_monitor = ActivityMonitor(manager.tmux)
        self._polling = False

    def compose(self) -> ComposeResult:
        yield ProjectHeader(self.settings.project.name)
        with Vertical(id="body"):
            yield Static("Active Worktrees", id="section-title")
            yield WorktreeTable()
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_table()
        self.set_interval(2.0, self._poll_activity)

    def _refresh_table(self) -> None:
        table = self.query_one(WorktreeTable)
        table.refresh_worktrees(self.manager.list_active())

    # --- Activity polling ---

    def _poll_activity(self) -> None:
        """Kick off a background poll (guards against overlapping polls)."""
        if not self._polling:
            self._poll_activity_worker()

    @work(thread=True)
    def _poll_activity_worker(self) -> None:
        """Poll tmux panes and update worktree statuses."""
        self._polling = True
        try:
            changed = False
            for wt in self.session_state.worktrees:
                if wt.tmux_window_id and wt.status in POLLABLE_STATUSES:
                    new_status = self._activity_monitor.check(self.session_state.tmux_session_name, wt.tmux_window_id)
                    if new_status != wt.status:
                        wt.status = new_status
                        changed = True
            if changed:
                self.call_from_thread(self._refresh_table)
        finally:
            self._polling = False

    # --- Worktree CRUD ---

    def action_new_worktree(self) -> None:
        """Open the new worktree dialog."""
        base = self.settings.project.base_branch
        profile_names = [p.name for p in self.settings.agent.profiles]

        def on_result(result: tuple[str, str, str | None] | None) -> None:
            if result is not None:
                branch, base_branch, profile = result
                # Add a CREATING placeholder immediately so the user sees feedback
                placeholder = WorktreeInfo(
                    branch=branch,
                    path=Path("."),
                    status=WorktreeStatus.CREATING,
                )
                self.session_state.worktrees.append(placeholder)
                self._refresh_table()
                self._create_worktree(branch, base_branch, profile)

        self.push_screen(
            NewWorktreeScreen(default_base=base, profile_names=profile_names),
            callback=on_result,
        )

    @work(thread=True)
    def _create_worktree(self, branch: str, base_branch: str, agent_profile: str | None = None) -> None:
        """Create a worktree in a background thread."""
        try:
            self.manager.create(branch, base_branch, agent_profile=agent_profile)
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Worktree '{branch}' created")
        except Exception as e:
            # Remove the placeholder on error
            self.session_state.worktrees = [w for w in self.session_state.worktrees if w.branch != branch]
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Error creating worktree: {e}", severity="error")

    def on_data_table_row_selected(self, event: WorktreeTable.RowSelected) -> None:
        """Handle Enter on a table row — switch to that worktree's tmux window."""
        row_data = event.data_table.get_row(event.row_key)
        branch = str(row_data[1])  # Column 1 is Branch
        self._switch_to_branch(branch)

    def action_switch_worktree(self) -> None:
        """Switch to the tmux window for the currently highlighted worktree."""
        table = self.query_one(WorktreeTable)
        if table.cursor_row is not None and table.row_count > 0:
            row_data = table.get_row_at(table.cursor_row)
            branch = str(row_data[1])  # Column 1 is Branch
            self._switch_to_branch(branch)

    def _switch_to_branch(self, branch: str) -> None:
        """Switch to the tmux window for the given branch."""
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
            # Show REMOVING status immediately
            info = next((w for w in self.session_state.worktrees if w.branch == branch), None)
            if info:
                info.status = WorktreeStatus.REMOVING
                self._refresh_table()
            self._remove_worktree(branch)

    @work(thread=True)
    def _remove_worktree(self, branch: str) -> None:
        """Remove a worktree in a background thread."""
        # Clean up activity monitor state
        info = next((w for w in self.session_state.worktrees if w.branch == branch), None)
        if info and info.tmux_window_id:
            self._activity_monitor.remove(info.tmux_window_id)
        try:
            self.manager.remove(branch)
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Worktree '{branch}' removed")
        except Exception as e:
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Error removing worktree: {e}", severity="error")

    # --- Broadcast (claude -p) ---

    def _active_worktree_targets(self) -> list[tuple[str, Path]]:
        """Return (branch, path) pairs for all active worktrees."""
        return [(wt.branch, wt.path) for wt in self.session_state.worktrees if wt.status in POLLABLE_STATUSES]

    def action_broadcast(self) -> None:
        """Open a dialog to broadcast a prompt to all agents."""

        def on_prompt(prompt: str | None) -> None:
            if prompt:
                self._run_broadcast(prompt)

        self.push_screen(BroadcastInputScreen(), callback=on_prompt)

    def action_status(self) -> None:
        """Ask all agents to summarize their current progress."""
        targets = self._active_worktree_targets()
        if not targets:
            self.notify("No active worktrees", severity="warning")
            return
        self.notify(f"Requesting status from {len(targets)} agent(s)...")
        self._run_broadcast(
            "Briefly summarize your current progress and state in 2-3 sentences. "
            "What are you working on, what have you done, and what remains?"
        )

    @work(thread=True)
    def _run_broadcast(self, prompt: str) -> None:
        """Send *prompt* to all active worktrees and show results."""
        targets = self._active_worktree_targets()
        if not targets:
            self.call_from_thread(self.notify, "No active worktrees", severity="warning")
            return

        self.call_from_thread(self.notify, f"Broadcasting to {len(targets)} agent(s)...")

        responses = asyncio.run(self.agent.broadcast(prompt, targets, timeout=120))

        def show_results() -> None:
            self.push_screen(BroadcastResultsScreen(responses))

        self.call_from_thread(show_results)

    # --- Send prompt (tmux send-keys) ---

    def action_send_prompt(self) -> None:
        """Open a dialog to send a prompt directly into agent terminal(s)."""
        table = self.query_one(WorktreeTable)
        selected_branch: str | None = None
        if table.cursor_row is not None and table.row_count > 0:
            row_data = table.get_row_at(table.cursor_row)
            selected_branch = str(row_data[1])  # Column 1 is Branch

        def on_result(result: tuple[str, bool] | None) -> None:
            if result is not None:
                prompt, send_to_all = result
                self._send_prompt_to_agents(prompt, send_to_all, selected_branch)

        self.push_screen(SendPromptScreen(selected_branch=selected_branch), callback=on_result)

    def _send_prompt_to_agents(self, prompt: str, send_to_all: bool, selected_branch: str | None) -> None:
        """Send a prompt via tmux send-keys to one or all agent terminals."""
        targets: list[WorktreeInfo] = []
        if send_to_all:
            targets = [
                wt for wt in self.session_state.worktrees if wt.tmux_window_id and wt.status in POLLABLE_STATUSES
            ]
        elif selected_branch:
            wt = next(
                (w for w in self.session_state.worktrees if w.branch == selected_branch and w.tmux_window_id),
                None,
            )
            if wt:
                targets = [wt]

        if not targets:
            self.notify("No valid targets", severity="warning")
            return

        errors = 0
        for wt in targets:
            try:
                self.manager.tmux.send_keys_to_window_id(
                    self.session_state.tmux_session_name,
                    wt.tmux_window_id,  # type: ignore[arg-type]
                    prompt,
                )
            except Exception as e:
                self.notify(f"Error sending to {wt.branch}: {e}", severity="error")
                errors += 1

        sent = len(targets) - errors
        if sent > 0:
            self.notify(f"Sent prompt to {sent} agent(s)")

    # --- Quit ---

    async def action_quit(self) -> None:
        """Show confirmation dialog before quitting."""

        def on_result(confirmed: bool | None) -> None:
            if confirmed:
                # Kill the tmux session (leaves git worktrees in place)
                self.manager.tmux.kill_session(self.session_state.tmux_session_name)
                self.exit()

        self.push_screen(ConfirmQuitScreen(), callback=on_result)

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
