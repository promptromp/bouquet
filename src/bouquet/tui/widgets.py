"""Custom widgets for the Bouquet TUI."""

from __future__ import annotations

from rich.console import RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import DataTable, Static, TabbedContent, TabPane

from bouquet.models import WorktreeInfo, WorktreeStatus


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


class WorktreeDetailPanel(Widget):
    """Displays details about the currently highlighted worktree as a Rich table."""

    _PLACEHOLDER = "Select a worktree to view details."

    def __init__(self) -> None:
        super().__init__()
        self._current_branch: str | None = None
        self._current_wt: WorktreeInfo | None = None
        self._pr_cache: dict[str, str | None] = {}
        self._pr_pending: set[str] = set()
        self._rows: dict[str, str] = {}

    def render(self) -> RenderableType:
        if not self._rows:
            return Text(self._PLACEHOLDER, style="dim")
        table = Table(show_header=False, box=None, padding=(0, 1, 0, 0), expand=True)
        table.add_column("label", style="dim", no_wrap=True, width=8)
        table.add_column("value")
        for label, value in self._rows.items():
            table.add_row(label, value)
        return table

    def show_worktree(self, wt: WorktreeInfo | None) -> None:
        """Update the panel to show details for the given worktree."""
        self._current_wt = wt
        if wt is None:
            self._current_branch = None
            self._rows = {}
            self.refresh()
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
        self.refresh()

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


class DetailTabs(TabbedContent):
    """Tabbed panel on the right side of the orchestrator."""

    def compose(self) -> ComposeResult:
        with TabPane("Task Queue", id="tab-task-queue"):
            yield Static(
                "No tasks in queue.",
                id="task-queue-empty",
            )


class TaskQueueTable(DataTable):
    """Table for displaying queued tasks (placeholder for future implementation)."""

    def __init__(self) -> None:
        super().__init__(cursor_type="row")
        self.add_class("task-queue-table")

    def on_mount(self) -> None:
        self.add_columns("Task", "Branch", "Status")
