"""Custom widgets for the Bouquet TUI."""

from __future__ import annotations

from textual.widgets import DataTable, Static

from bouquet.models import WorktreeInfo, WorktreeStatus


_LOGO = r"""
 _                       _
| |_ ___ _ _ ___ _ _ ___| |_
| . | . | | | . | | | -_|  _|
|___|___|___|_  |___|___|_|
              |_|"""


class ProjectHeader(Static):
    """Displays the ASCII logo and project name in the header area."""

    def __init__(self, project_name: str) -> None:
        super().__init__(f"{_LOGO}\n{project_name}")
        self.add_class("project-header")


class WorktreeTable(DataTable):
    """A table displaying active worktrees."""

    def __init__(self) -> None:
        super().__init__(cursor_type="row")
        self.add_class("worktree-table")

    def on_mount(self) -> None:
        self.add_columns("#", "Branch", "Status", "Window", "Created")

    _STATUS_DISPLAY = {
        WorktreeStatus.CREATING: "creating...",
        WorktreeStatus.REMOVING: "removing...",
        WorktreeStatus.ERROR: "ERROR",
    }

    def refresh_worktrees(self, worktrees: list[WorktreeInfo]) -> None:
        """Clear and repopulate the table with current worktree data."""
        self.clear()
        for i, wt in enumerate(worktrees, 1):
            created = wt.created_at.strftime("%m-%d %H:%M")
            window_id = wt.tmux_window_id or "-"
            status = self._STATUS_DISPLAY.get(wt.status, wt.status.value)
            self.add_row(
                str(i),
                wt.branch,
                status,
                window_id,
                created,
                key=wt.branch,
            )
