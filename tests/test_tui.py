"""Tests for TUI components."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from bouquet.models import WorktreeInfo, WorktreeStatus
from bouquet.tui.widgets import ProjectHeader


def test_project_header_content() -> None:
    header = ProjectHeader("my-project")
    assert "my-project" in str(header.content)


def test_worktree_info_display_format() -> None:
    """Verify WorktreeInfo can produce display-friendly data."""
    info = WorktreeInfo(
        branch="feature/auth",
        path=Path("/tmp/wt"),
        tmux_window_id="@1",
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
    )
    assert info.status.value == "active"
    assert info.created_at.strftime("%m-%d %H:%M") == "03-18 10:00"
