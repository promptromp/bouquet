"""OrchestratorApp — the main Textual TUI for Bouquet."""

from __future__ import annotations

import hashlib
import os
import re
import sys
import time
from pathlib import Path

import click
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.coordinate import Coordinate
from textual.widgets import Footer, Static

from bouquet.activity import POLLABLE_STATUSES, ActivityMonitor
from bouquet.agents.base import AgentResponse
from bouquet.config import BouquetSettings, load_config
from bouquet.github import GitHubError, lookup_pr_url
from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus
from bouquet.tasks import TaskQueueBackend, create_backend
from bouquet.tasks.base import TaskStatus
from bouquet.tmux import TmuxManager
from bouquet.tui.screens import (
    BroadcastResultsScreen,
    ConfirmQuitScreen,
    CreateTaskScreen,
    NewWorktreeScreen,
    SendPromptScreen,
)
from bouquet.tui.widgets import ProjectHeader, TaskQueueTable, WorktreeDetailPanel, WorktreeTable
from bouquet.worktree import WorktreeManager


_RE_AUTO_ACCEPT = re.compile(r"^\s*[❯ ]\s*(\d+)\.\s*Yes,?\s+and\s+don't\s+ask\s+again", re.MULTILINE)
_RE_YES = re.compile(r"^\s*[❯ ]\s*(\d+)\.\s*Yes\s*$", re.MULTILINE)


def _detect_accept_key(content: str) -> str | None:
    """Detect the right key to send for a permission prompt.

    Returns the option number for "Yes, and don't ask again" if available,
    then falls back to plain "Yes", then None for non-numbered prompts.
    """
    last_lines = "\n".join(content.splitlines()[-15:])
    m = _RE_AUTO_ACCEPT.search(last_lines)
    if m:
        return m.group(1)
    m = _RE_YES.search(last_lines)
    if m:
        return m.group(1)
    return None


def _extract_response(content: str, prompt: str) -> str:
    """Extract the agent's response from captured pane content.

    Looks for the sent prompt in the pane output and returns everything
    after it.  Falls back to the last 30 non-empty lines.
    """
    lines = content.splitlines()
    prompt_prefix = prompt[:50]
    for i, line in enumerate(lines):
        if prompt_prefix in line:
            return "\n".join(lines[i + 1 :]).strip()
    # Fallback: last 30 non-empty lines
    recent = [line for line in lines if line.strip()][-30:]
    return "\n".join(recent).strip()


class OrchestratorApp(App):
    """Bouquet orchestrator TUI — runs in tmux window 0."""

    CSS_PATH = "styles/app.tcss"

    BINDINGS = [
        Binding("n", "new_worktree", "New worktree"),
        Binding("s", "switch_worktree", "Switch to window"),
        Binding("d", "delete_worktree", "Delete worktree"),
        Binding("a", "toggle_auto_accept", "Auto-accept"),
        Binding("p", "send_prompt", "Send prompt"),
        Binding("t", "status", "Status"),
        Binding("c", "create_task", "Create task"),
        Binding("x", "pick_up_task", "Pick up task"),
        Binding("m", "complete_task", "Complete task"),
        Binding("backspace", "delete_task", "Delete task"),
        Binding("r", "refresh", "Refresh"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self,
        settings: BouquetSettings,
        state: SessionState,
        manager: WorktreeManager,
        task_backend: TaskQueueBackend | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings
        self.session_state = state
        self.manager = manager
        self.task_backend = task_backend or create_backend(settings.task_queue, settings.project.name)
        self._activity_monitor = ActivityMonitor(manager.tmux)
        self._polling = False
        self._send_to_all = False
        self._recently_accepted: set[str] = set()

    def compose(self) -> ComposeResult:
        yield ProjectHeader(self.settings.project.name)
        with Horizontal(id="body"):
            with Vertical(id="left-panel"):
                yield Static("Worktrees", id="section-title")
                yield WorktreeTable()
                yield Static(
                    "No worktrees yet. Press [bold]n[/bold] to create one.",
                    id="empty-state",
                )
                with Vertical(id="tasks-container"):
                    yield TaskQueueTable()
            with Vertical(id="right-panel"), Vertical(id="detail-container"):
                yield WorktreeDetailPanel()
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#detail-container").border_title = "Details"
        self.query_one("#tasks-container").border_title = "Task Queue"
        self._refresh_table()
        self._reconcile_tasks()
        self.set_interval(2.0, self._poll_activity)

    def _refresh_table(self) -> None:
        table = self.query_one(WorktreeTable)
        worktrees = self.manager.list_active()
        table.refresh_worktrees(worktrees)
        empty = self.query_one("#empty-state", Static)
        empty.display = not worktrees
        table.display = bool(worktrees)
        # Re-render detail panel for the currently selected branch
        detail = self.query_one(WorktreeDetailPanel)
        if detail._current_branch:
            wt = next((w for w in worktrees if w.branch == detail._current_branch), None)
            detail.show_worktree(wt)

    def _sendable_worktrees(self) -> list[WorktreeInfo]:
        """Return worktrees that have a tmux window and are in a pollable state."""
        return [wt for wt in self.session_state.worktrees if wt.tmux_window_id and wt.status in POLLABLE_STATUSES]

    def _send_auto_accept(self, wt: WorktreeInfo) -> None:
        """Send the right key sequence to accept a permission prompt.

        For Claude Code numbered menus, prefers "Yes, and don't ask again"
        over plain "Yes". Falls back to "y" for traditional [Y/n] prompts.
        """
        if wt.agent_pane_id:
            content = self.manager.tmux.capture_pane_by_id(wt.agent_pane_id)
        else:
            content = self.manager.tmux.capture_pane(
                self.session_state.tmux_session_name,
                wt.tmux_window_id,  # type: ignore[arg-type]
            )

        key = _detect_accept_key(content)
        if key:
            # Claude Code numbered menu: type the option number (no Enter — the menu accepts on keypress)
            if wt.agent_pane_id:
                self.manager.tmux.send_keys_to_pane(wt.agent_pane_id, key, enter=False)
            else:
                self.manager.tmux.send_keys_to_window_id(
                    self.session_state.tmux_session_name,
                    wt.tmux_window_id,  # type: ignore[arg-type]
                    key,
                    enter=False,
                )
        else:
            # Traditional [Y/n] prompt: send "y" + Enter
            if wt.agent_pane_id:
                self.manager.tmux.send_keys_to_pane(wt.agent_pane_id, "y")
            else:
                self.manager.tmux.send_keys_to_window_id(
                    self.session_state.tmux_session_name,
                    wt.tmux_window_id,  # type: ignore[arg-type]
                    "y",
                )

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
                    new_status = self._activity_monitor.check(
                        self.session_state.tmux_session_name, wt.tmux_window_id, wt.agent_pane_id
                    )
                    if new_status != wt.status and wt.status in POLLABLE_STATUSES:
                        wt.status = new_status
                        changed = True
                    # Auto-accept: accept prompt when WAITING and auto_accept is on
                    guard_key = wt.agent_pane_id or wt.tmux_window_id
                    if (
                        new_status == WorktreeStatus.WAITING
                        and wt.auto_accept
                        and guard_key not in self._recently_accepted
                    ):
                        try:
                            self._send_auto_accept(wt)
                            self._recently_accepted.add(guard_key)
                        except Exception:
                            pass
                    elif new_status != WorktreeStatus.WAITING and guard_key in self._recently_accepted:
                        self._recently_accepted.discard(guard_key)
            if changed:
                self.call_from_thread(self._refresh_table)
        finally:
            self._polling = False

    # --- Worktree CRUD ---

    def action_new_worktree(self) -> None:
        """Open the new worktree dialog."""
        base = self.settings.project.base_branch
        profile_names = [p.name for p in self.settings.agent.profiles]

        def on_result(result: tuple[str, str, str | None, bool] | None) -> None:
            if result is not None:
                branch, base_branch, profile, auto_accept = result
                # Add a CREATING placeholder immediately so the user sees feedback
                placeholder = WorktreeInfo(
                    branch=branch,
                    path=Path("."),
                    status=WorktreeStatus.CREATING,
                    auto_accept=auto_accept,
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

    def on_data_table_row_highlighted(self, event: WorktreeTable.RowHighlighted) -> None:
        """Update the detail panel when the cursor moves to a new row."""
        if not isinstance(event.data_table, WorktreeTable):
            return
        if event.row_key is None:
            return
        row_data = event.data_table.get_row(event.row_key)
        branch = str(row_data[1])  # Column 1 is Branch
        wt = next((w for w in self.session_state.worktrees if w.branch == branch), None)
        detail = self.query_one(WorktreeDetailPanel)
        detail.show_worktree(wt)
        if wt and branch not in detail._pr_cache and branch not in detail._pr_pending:
            detail.mark_pr_pending(branch)
            self._lookup_pr(branch)

    @work(thread=True, group="pr-lookup")
    def _lookup_pr(self, branch: str) -> None:
        """Look up the PR URL for a branch in the background."""
        try:
            url = lookup_pr_url(branch, cwd=Path(self.settings.project.repo_path))
        except GitHubError:
            url = None
        detail = self.query_one(WorktreeDetailPanel)
        self.call_from_thread(detail.set_pr_url, branch, url)

    def on_data_table_row_selected(self, event: WorktreeTable.RowSelected) -> None:
        """Handle Enter on a table row — switch to that worktree's tmux window."""
        if not isinstance(event.data_table, WorktreeTable):
            return
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

    def action_toggle_auto_accept(self) -> None:
        """Toggle auto-accept for the currently highlighted worktree."""
        table = self.query_one(WorktreeTable)
        if table.cursor_row is None or table.row_count == 0:
            return
        row_data = table.get_row_at(table.cursor_row)
        branch = str(row_data[1])  # Column 1 is Branch
        wt = next((w for w in self.session_state.worktrees if w.branch == branch), None)
        if wt is None:
            return
        wt.auto_accept = not wt.auto_accept
        guard_key = wt.agent_pane_id or wt.tmux_window_id
        if not wt.auto_accept and guard_key:
            self._recently_accepted.discard(guard_key)
        self.session_state.save()
        self._refresh_table()
        state = "on" if wt.auto_accept else "off"
        self.notify(f"Auto-accept {state} for {branch}")

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
            guard_key = info.agent_pane_id or info.tmux_window_id
            self._recently_accepted.discard(guard_key)
        try:
            self.manager.remove(branch)
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Worktree '{branch}' removed")
        except Exception as e:
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self.notify, f"Error removing worktree: {e}", severity="error")

    # --- Status (send-keys + capture pane responses) ---

    def action_status(self) -> None:
        """Ask all agents to summarize their current progress."""
        targets = self._sendable_worktrees()
        if not targets:
            self.notify("No active worktrees", severity="warning")
            return
        self.notify(f"Requesting status from {len(targets)} agent(s)...")
        self._run_status()

    @work(thread=True)
    def _run_status(self) -> None:
        """Send status prompt via send-keys, poll for completion, capture responses."""
        targets = self._sendable_worktrees()
        if not targets:
            self.call_from_thread(self.notify, "No active worktrees", severity="warning")
            return

        prompt = (
            "Briefly summarize your current progress and state in 2-3 sentences. "
            "What are you working on, what have you done, and what remains?"
        )
        session = self.session_state.tmux_session_name
        start = time.monotonic()

        # 1. Send prompt to all agents
        sent: list[WorktreeInfo] = []
        for wt in targets:
            try:
                if wt.agent_pane_id:
                    self.manager.tmux.send_keys_to_pane(wt.agent_pane_id, prompt)
                else:
                    self.manager.tmux.send_keys_to_window_id(session, wt.tmux_window_id, prompt)  # type: ignore[arg-type]
                sent.append(wt)
            except Exception:
                pass

        if not sent:
            self.call_from_thread(self.notify, "Failed to send status request", severity="error")
            return

        # 2. Poll until all agents stabilize (or timeout)
        hashes: dict[str, str] = {}
        stable_counts: dict[str, int] = {}
        max_wait = 120
        elapsed = 0
        stability_threshold = 3

        time.sleep(3)  # initial wait for agents to start responding

        while elapsed < max_wait:
            all_stable = True
            for wt in sent:
                try:
                    if wt.agent_pane_id:
                        content = self.manager.tmux.capture_pane_by_id(wt.agent_pane_id)
                    else:
                        content = self.manager.tmux.capture_pane(session, wt.tmux_window_id)  # type: ignore[arg-type]
                except Exception:
                    continue
                h = hashlib.sha256(content.encode()).hexdigest()
                prev = hashes.get(wt.branch)
                hashes[wt.branch] = h
                if prev is None or h != prev:
                    stable_counts[wt.branch] = 0
                    all_stable = False
                else:
                    stable_counts[wt.branch] = stable_counts.get(wt.branch, 0) + 1
                    if stable_counts[wt.branch] < stability_threshold:
                        all_stable = False
            if all_stable:
                break
            time.sleep(2)
            elapsed += 2

        duration_ms = int((time.monotonic() - start) * 1000)

        # 3. Capture final pane content and build responses
        responses: list[AgentResponse] = []
        for wt in sent:
            try:
                if wt.agent_pane_id:
                    content = self.manager.tmux.capture_pane_by_id(wt.agent_pane_id)
                else:
                    content = self.manager.tmux.capture_pane(session, wt.tmux_window_id)  # type: ignore[arg-type]
            except Exception:
                content = ""
            response_text = _extract_response(content, prompt)
            responses.append(
                AgentResponse(
                    worktree_branch=wt.branch,
                    result=response_text or "(no response captured)",
                    duration_ms=duration_ms,
                )
            )

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
                self._send_to_all = send_to_all  # remember for next invocation
                self._send_prompt_to_agents(prompt, send_to_all, selected_branch)

        self.push_screen(
            SendPromptScreen(selected_branch=selected_branch, default_send_all=self._send_to_all),
            callback=on_result,
        )

    def _send_prompt_to_agents(self, prompt: str, send_to_all: bool, selected_branch: str | None) -> None:
        """Send a prompt via tmux send-keys to one or all agent terminals."""
        targets: list[WorktreeInfo] = []
        if send_to_all:
            targets = self._sendable_worktrees()
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
                if wt.agent_pane_id:
                    self.manager.tmux.send_keys_to_pane(wt.agent_pane_id, prompt)
                else:
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

    # --- Task queue ---

    @work(thread=True, group="task-refresh")
    def _reconcile_tasks(self) -> None:
        """Reconcile task state on startup: restore task_id links and reset stale tasks."""
        # 1. Restore task_id on adopted worktrees matching IN_PROGRESS tasks
        in_progress = self.task_backend.list_tasks(status=TaskStatus.IN_PROGRESS)
        task_by_branch = {t.branch: t for t in in_progress if t.branch}
        restored = False
        for wt in self.session_state.worktrees:
            if wt.task_id is None and wt.branch in task_by_branch:
                wt.task_id = task_by_branch[wt.branch].id
                restored = True
        if restored:
            self.session_state.save()

        # 2. Reset stale IN_PROGRESS tasks (no matching worktree)
        active_branches = {wt.branch for wt in self.session_state.worktrees}
        reset = self.task_backend.reconcile_stale(active_branches)
        if reset:
            self.call_from_thread(self.notify, f"Reset {len(reset)} stale task(s) to open")

        # 3. Refresh task table
        tasks = self.task_backend.list_tasks()
        task_table = self.query_one(TaskQueueTable)
        self.call_from_thread(task_table.refresh_tasks, tasks)

    def _refresh_tasks(self) -> None:
        """Refresh the task queue table from the backend."""
        self._refresh_tasks_worker()

    @work(thread=True, group="task-refresh")
    def _refresh_tasks_worker(self) -> None:
        tasks = self.task_backend.list_tasks()
        task_table = self.query_one(TaskQueueTable)
        self.call_from_thread(task_table.refresh_tasks, tasks)

    def action_create_task(self) -> None:
        """Open the create task dialog."""

        def on_result(result: tuple[str, str] | None) -> None:
            if result is not None:
                title, description = result
                self._create_task_worker(title, description)

        self.push_screen(CreateTaskScreen(), callback=on_result)

    @work(thread=True)
    def _create_task_worker(self, title: str, description: str) -> None:
        try:
            self.task_backend.create_task(title, description)
            self.call_from_thread(self._refresh_tasks)
            self.call_from_thread(self.notify, f"Task '{title}' created")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error creating task: {e}", severity="error")

    def action_pick_up_task(self) -> None:
        """Pick up the highlighted task in the task queue table."""
        task_table = self.query_one(TaskQueueTable)
        if task_table.cursor_row is None or task_table.row_count == 0:
            self.notify("No task selected", severity="warning")
            return
        row_key = task_table.coordinate_to_cell_key(Coordinate(task_table.cursor_row, 0)).row_key
        task_id = str(row_key.value)
        task = self.task_backend.get_task(task_id)
        if task is None:
            self.notify(f"Task {task_id} not found", severity="error")
            return
        if task.status != TaskStatus.OPEN:
            self.notify(f"Task is already {task.status.value}", severity="warning")
            return
        # Compute branch name to add a CREATING placeholder immediately
        sanitized = re.sub(r"[^a-z0-9]+", "-", task.title.lower())[:40].strip("-")
        branch = f"{self.settings.task_queue.auto_branch_prefix}{task.id}-{sanitized}"
        placeholder = WorktreeInfo(
            branch=branch,
            path=Path("."),
            status=WorktreeStatus.CREATING,
            task_id=task_id,
        )
        self.session_state.worktrees.append(placeholder)
        self._refresh_table()
        self._refresh_tasks()
        self.notify(f"Picking up task: {task.title}")
        self._pick_up_task_worker(task_id, branch)

    @work(thread=True)
    def _pick_up_task_worker(self, task_id: str, branch: str) -> None:
        try:
            task = self.task_backend.get_task(task_id)
            if task is None:
                self.session_state.worktrees = [w for w in self.session_state.worktrees if w.branch != branch]
                self.call_from_thread(self._refresh_table)
                self.call_from_thread(self.notify, f"Task {task_id} not found", severity="error")
                return
            profile_names = [p.name for p in self.settings.agent.profiles]
            agent_profile = profile_names[0] if profile_names else None
            self.manager.pick_up_task(
                task=task,
                backend=self.task_backend,
                auto_branch_prefix=self.settings.task_queue.auto_branch_prefix,
                agent_profile=agent_profile,
            )
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self._refresh_tasks)
            self.call_from_thread(self.notify, f"Picked up task: {task.title}")
        except Exception as e:
            # Remove the placeholder on error
            self.session_state.worktrees = [w for w in self.session_state.worktrees if w.branch != branch]
            self.call_from_thread(self._refresh_table)
            self.call_from_thread(self._refresh_tasks)
            self.call_from_thread(self.notify, f"Error picking up task: {e}", severity="error")

    def action_complete_task(self) -> None:
        """Mark the highlighted task as done."""
        task_table = self.query_one(TaskQueueTable)
        if task_table.cursor_row is None or task_table.row_count == 0:
            self.notify("No task selected", severity="warning")
            return
        row_key = task_table.coordinate_to_cell_key(Coordinate(task_table.cursor_row, 0)).row_key
        task_id = str(row_key.value)
        self._complete_task_worker(task_id)

    @work(thread=True)
    def _complete_task_worker(self, task_id: str) -> None:
        try:
            task = self.task_backend.get_task(task_id)
            if task is None:
                self.call_from_thread(self.notify, f"Task {task_id} not found", severity="error")
                return
            if task.status == TaskStatus.DONE:
                self.call_from_thread(self.notify, "Task is already done", severity="warning")
                return
            self.task_backend.update_status(task_id, TaskStatus.DONE)
            self.call_from_thread(self._refresh_tasks)
            self.call_from_thread(self.notify, f"Task '{task.title}' completed")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error completing task: {e}", severity="error")

    def action_delete_task(self) -> None:
        """Delete the highlighted task from the task queue."""
        task_table = self.query_one(TaskQueueTable)
        if task_table.cursor_row is None or task_table.row_count == 0:
            self.notify("No task selected", severity="warning")
            return
        row_key = task_table.coordinate_to_cell_key(Coordinate(task_table.cursor_row, 0)).row_key
        task_id = str(row_key.value)
        self._delete_task_worker(task_id)

    @work(thread=True)
    def _delete_task_worker(self, task_id: str) -> None:
        try:
            task = self.task_backend.get_task(task_id)
            if task is None:
                self.call_from_thread(self.notify, f"Task {task_id} not found", severity="error")
                return
            self.task_backend.delete_task(task_id)
            self.call_from_thread(self._refresh_tasks)
            self.call_from_thread(self.notify, f"Task '{task.title}' deleted")
        except Exception as e:
            self.call_from_thread(self.notify, f"Error deleting task: {e}", severity="error")

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
        """Refresh the worktree table and task queue."""
        self._refresh_table()
        self._refresh_tasks()


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
