"""Custom widgets for the Bouquet TUI."""

from __future__ import annotations


__all__ = ["AutopilotIndicator", "ProjectHeader", "TaskQueueTable", "WorktreeDetailPanel", "WorktreeTable"]

from rich.text import Text
from textual.widgets import DataTable, Static

from bouquet.models import WorktreeInfo, WorktreeStatus
from bouquet.tasks.base import Task, TaskStatus


_STATUS_STYLE: dict[WorktreeStatus, str] = {
    WorktreeStatus.CREATING: "yellow",
    WorktreeStatus.RUNNING: "green",
    WorktreeStatus.WAITING: "yellow",
    WorktreeStatus.ACTIVE: "cyan",
    WorktreeStatus.IDLE: "dim",
    WorktreeStatus.ERROR: "bold red",
    WorktreeStatus.REMOVING: "yellow",
}

_STATUS_LABEL: dict[WorktreeStatus, str] = {
    WorktreeStatus.CREATING: "creating…",
    WorktreeStatus.RUNNING: "running",
    WorktreeStatus.WAITING: "waiting",
    WorktreeStatus.ACTIVE: "active",
    WorktreeStatus.IDLE: "idle",
    WorktreeStatus.ERROR: "ERROR",
    WorktreeStatus.REMOVING: "removing…",
}


class ProjectHeader(Static):
    """Displays the app name and project name in the header area."""

    def __init__(self, project_name: str) -> None:
        super().__init__(f"[bold italic]bouquet[/bold italic] [dim]//[/dim] {project_name}")
        self.add_class("project-header")


class AutopilotIndicator(Static):
    """Shows autopilot status near the header."""

    def __init__(self) -> None:
        super().__init__("")
        self.add_class("autopilot-indicator")

    def update_status(self, active: bool, current: int, max_concurrent: int) -> None:
        if active:
            self.update(f"[bold green]AUTOPILOT[/bold green] [{current}/{max_concurrent}]")
        else:
            self.update("")


class WorktreeTable(DataTable):
    """A table displaying active worktrees."""

    def __init__(self) -> None:
        super().__init__(cursor_type="row")
        self.add_class("worktree-table")

    def on_mount(self) -> None:
        self.add_columns("#", "Branch", "Status", "Profile", "Window", "Created")

    _STATUS_DISPLAY: dict[WorktreeStatus, Text] = {
        WorktreeStatus.CREATING: Text("⟳ creating…", style="yellow"),
        WorktreeStatus.RUNNING: Text("● running", style="green"),
        WorktreeStatus.WAITING: Text("◆ waiting", style="yellow"),
        WorktreeStatus.ACTIVE: Text("○ active", style="cyan"),
        WorktreeStatus.IDLE: Text("○ idle", style="dim"),
        WorktreeStatus.ERROR: Text("✗ ERROR", style="bold red"),
        WorktreeStatus.REMOVING: Text("⟳ removing…", style="yellow"),
    }

    def refresh_worktrees(self, worktrees: list[WorktreeInfo]) -> None:
        """Clear and repopulate the table with current worktree data."""
        self.clear()
        for i, wt in enumerate(worktrees, 1):
            created = wt.created_at.strftime("%m-%d %H:%M")
            window_id = wt.tmux_window_id or "-"
            status = self._STATUS_DISPLAY.get(wt.status, Text(wt.status.value))
            if wt.auto_accept:
                status = status.copy()
                status.append(" [A]", style="bold cyan")
            profile = wt.agent_profile or "-"
            self.add_row(
                str(i),
                wt.branch,
                status,
                profile,
                window_id,
                created,
                key=wt.branch,
            )


class WorktreeDetailPanel(Static):
    """Displays details about the currently highlighted worktree.

    Uses Static.update() so that content changes trigger proper re-layout
    (Widget.render() + refresh() doesn't re-layout in Textual 8.x).
    """

    _PLACEHOLDER = "[dim]Select a worktree to view details.[/dim]"

    def __init__(self) -> None:
        super().__init__(self._PLACEHOLDER)
        self._current_branch: str | None = None
        self._current_wt: WorktreeInfo | None = None
        self._pr_cache: dict[str, str | None] = {}
        self._pr_pending: set[str] = set()
        self._rows: dict[str, str] = {}

    @property
    def current_branch(self) -> str | None:
        return self._current_branch

    def needs_pr_lookup(self, branch: str) -> bool:
        return branch not in self._pr_cache and branch not in self._pr_pending

    def show_worktree(self, wt: WorktreeInfo | None) -> None:
        """Update the panel to show details for the given worktree."""
        self._current_wt = wt
        if wt is None:
            self._current_branch = None
            self._rows = {}
            self.update(self._PLACEHOLDER)
            return
        self._current_branch = wt.branch
        self._rebuild_rows()

    def _rebuild_rows(self) -> None:
        """Rebuild the key-value rows from the current worktree."""
        wt = self._current_wt
        if wt is None:
            return
        status_label = _STATUS_LABEL.get(wt.status, wt.status.value)
        status_style = _STATUS_STYLE.get(wt.status, "")
        rows: dict[str, str] = {
            "Branch": wt.branch,
            "Status": f"[{status_style}]{status_label}[/{status_style}]" if status_style else status_label,
            "Accept": "[green]on[/green]" if wt.auto_accept else "[dim]off[/dim]",
            "Profile": wt.agent_profile or "default",
            "Window": wt.tmux_window_id or "-",
            "Path": str(wt.path),
            "Created": wt.created_at.strftime("%Y-%m-%d %H:%M"),
        }
        # PR row
        if wt.branch in self._pr_cache:
            pr_url = self._pr_cache[wt.branch]
            rows["PR"] = pr_url if pr_url else "[dim]No PR[/dim]"
        elif wt.branch in self._pr_pending:
            rows["PR"] = "[dim]Looking up…[/dim]"
        self._rows = rows
        lines = [f"[dim]{label:8s}[/dim] {value}" for label, value in rows.items()]
        self.update("\n".join(lines))

    def mark_pr_pending(self, branch: str) -> None:
        """Mark a PR lookup as in-flight."""
        self._pr_pending.add(branch)
        if branch == self._current_branch:
            self._rebuild_rows()

    def set_pr_url(self, branch: str, url: str | None) -> None:
        """Cache a PR URL and re-render if this branch is currently shown."""
        self._pr_cache[branch] = url
        self._pr_pending.discard(branch)
        if branch == self._current_branch:
            self._rebuild_rows()


_TASK_STATUS_DISPLAY: dict[TaskStatus, Text] = {
    TaskStatus.OPEN: Text("○ open", style="cyan"),
    TaskStatus.IN_PROGRESS: Text("● in progress", style="green"),
    TaskStatus.DONE: Text("✓ done", style="dim green"),
}


_TASK_BLOCKED = Text("◌ blocked", style="dim yellow")


class TaskQueueTable(DataTable):
    """Table for displaying queued tasks."""

    def __init__(self) -> None:
        super().__init__(cursor_type="row")
        self.add_class("task-queue-table")

    def on_mount(self) -> None:
        self.add_columns("#", "Title", "Status", "Dep", "Branch", "Created")

    def refresh_tasks(self, tasks: list[Task]) -> None:
        """Clear and repopulate the table with current task data."""
        self.clear()
        status_by_id = {t.id: t.status for t in tasks}
        for task in tasks:
            created = task.created_at.strftime("%m-%d %H:%M")
            # Show blocked status for OPEN tasks whose parent is not DONE
            if (
                task.status == TaskStatus.OPEN
                and task.parent_id is not None
                and status_by_id.get(task.parent_id) != TaskStatus.DONE
            ):
                status = _TASK_BLOCKED
            else:
                status = _TASK_STATUS_DISPLAY.get(task.status, Text(task.status.value))
            dep = f"#{task.parent_id}" if task.parent_id else "-"
            branch = task.branch or "-"
            self.add_row(
                task.id,
                task.title,
                status,
                dep,
                branch,
                created,
                key=task.id,
            )
