"""Custom widgets for the Bouquet TUI."""

from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.widgets import DataTable, Static, TabbedContent, TabPane

from bouquet.models import WorktreeInfo, WorktreeStatus


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
