"""Tests for TUI components."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from bouquet.models import WorktreeInfo, WorktreeStatus
from bouquet.tui.app import OrchestratorApp, _extract_response
from bouquet.tui.screens import NewWorktreeScreen, SendPromptScreen
from bouquet.tui.widgets import ProjectHeader, WorktreeTable


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
