"""Tests for TUI components."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text

from bouquet.models import WorktreeInfo, WorktreeStatus
from bouquet.tui.app import OrchestratorApp, _extract_response
from bouquet.tui.screens import NewWorktreeScreen, SendPromptScreen
from bouquet.tui.widgets import _STATUS_LABEL, _STATUS_STYLE, ProjectHeader, WorktreeDetailPanel, WorktreeTable


def test_tui_modules_importable() -> None:
    """Smoke test: all TUI modules import without error."""
    assert OrchestratorApp is not None
    assert NewWorktreeScreen is not None
    assert SendPromptScreen is not None
    assert WorktreeTable is not None


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


def test_extract_response_finds_prompt() -> None:
    """_extract_response should return content after the sent prompt."""
    prompt = "Briefly summarize your current progress and state in 2-3 sentences."
    content = f"old output\n{prompt}\nI am working on auth.\nDone."
    result = _extract_response(content, prompt)
    assert "I am working on auth." in result
    assert "old output" not in result


def test_extract_response_fallback() -> None:
    """_extract_response falls back to last lines when prompt not found."""
    content = "line1\nline2\nline3"
    result = _extract_response(content, "not in content")
    assert "line1" in result


# --- WorktreeDetailPanel tests ---


def test_detail_panel_initial_state() -> None:
    """Detail panel starts empty (placeholder shown via render)."""
    panel = WorktreeDetailPanel()
    assert panel._rows == {}
    assert panel._current_wt is None


def test_detail_panel_show_worktree() -> None:
    """Detail panel populates rows from worktree info."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/auth",
        path=Path("/tmp/wt"),
        tmux_window_id="@1",
        status=WorktreeStatus.RUNNING,
        created_at=datetime(2026, 3, 18, 10, 0),
        agent_profile="claude",
    )
    panel.show_worktree(wt)
    assert panel._rows["Branch"] == "feature/auth"
    assert "running" in panel._rows["Status"]
    assert panel._rows["Profile"] == "claude"
    assert panel._rows["Window"] == "@1"


def test_detail_panel_show_none() -> None:
    """Showing None clears the rows."""
    panel = WorktreeDetailPanel()
    panel.show_worktree(None)
    assert panel._rows == {}


def test_detail_panel_pr_cache_with_url() -> None:
    """PR URL is cached and shown when set."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/auth",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
    )
    panel.show_worktree(wt)
    panel.set_pr_url("feature/auth", "https://github.com/org/repo/pull/42")
    assert panel._rows["PR"] == "https://github.com/org/repo/pull/42"


def test_detail_panel_pr_cache_none() -> None:
    """When PR cache is None (no PR), shows 'No PR'."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/no-pr",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
    )
    panel.show_worktree(wt)
    panel.set_pr_url("feature/no-pr", None)
    assert "No PR" in panel._rows["PR"]


def test_detail_panel_pr_pending() -> None:
    """Pending PR lookup shows 'Looking up…'."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/pending",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
    )
    panel.show_worktree(wt)
    panel.mark_pr_pending("feature/pending")
    assert "Looking up" in panel._rows["PR"]


def test_detail_panel_render_placeholder() -> None:
    """render() returns dim Text placeholder when no worktree selected."""
    panel = WorktreeDetailPanel()
    result = panel.render()
    assert isinstance(result, Text)
    assert "Select a worktree" in result.plain


def test_detail_panel_render_table() -> None:
    """render() returns a Rich Table when a worktree is shown."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/x",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.IDLE,
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    panel.show_worktree(wt)
    result = panel.render()
    assert isinstance(result, Table)


def test_detail_panel_set_pr_url_other_branch() -> None:
    """Setting PR URL for a non-current branch caches but doesn't change rows."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/current",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    panel.show_worktree(wt)
    panel.set_pr_url("feature/other", "https://github.com/org/repo/pull/99")
    assert panel._pr_cache["feature/other"] == "https://github.com/org/repo/pull/99"
    assert "PR" not in panel._rows


def test_detail_panel_all_statuses_have_style() -> None:
    """Every WorktreeStatus has an entry in both _STATUS_LABEL and _STATUS_STYLE."""
    for status in WorktreeStatus:
        assert status in _STATUS_LABEL, f"{status} missing from _STATUS_LABEL"
        assert status in _STATUS_STYLE, f"{status} missing from _STATUS_STYLE"
