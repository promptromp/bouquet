"""Tests for TUI components."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.table import Table
from rich.text import Text
from textual.geometry import Size

from bouquet.models import WorktreeInfo, WorktreeStatus
from bouquet.tui.app import OrchestratorApp, _detect_accept_key, _extract_response
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


def test_auto_accept_defaults_false() -> None:
    """auto_accept defaults to False on WorktreeInfo."""
    wt = WorktreeInfo(branch="feature/x", path=Path("/tmp/wt"))
    assert wt.auto_accept is False


def test_auto_accept_json_roundtrip() -> None:
    """auto_accept=True survives JSON serialization round-trip."""
    wt = WorktreeInfo(branch="feature/x", path=Path("/tmp/wt"), auto_accept=True)
    data = wt.model_dump_json()
    restored = WorktreeInfo.model_validate_json(data)
    assert restored.auto_accept is True


def test_auto_accept_backward_compat() -> None:
    """Old JSON without auto_accept deserializes with auto_accept=False."""
    data = '{"branch": "feature/x", "path": "/tmp/wt", "status": "active", "created_at": "2026-03-18T10:00:00"}'
    wt = WorktreeInfo.model_validate_json(data)
    assert wt.auto_accept is False


def test_agent_pane_id_defaults_none() -> None:
    """agent_pane_id defaults to None on WorktreeInfo."""
    wt = WorktreeInfo(branch="feature/x", path=Path("/tmp/wt"))
    assert wt.agent_pane_id is None


def test_agent_pane_id_json_roundtrip() -> None:
    """agent_pane_id survives JSON serialization round-trip."""
    wt = WorktreeInfo(branch="feature/x", path=Path("/tmp/wt"), agent_pane_id="%42")
    data = wt.model_dump_json()
    restored = WorktreeInfo.model_validate_json(data)
    assert restored.agent_pane_id == "%42"


def test_agent_pane_id_backward_compat() -> None:
    """Old JSON without agent_pane_id deserializes with agent_pane_id=None."""
    data = '{"branch": "feature/x", "path": "/tmp/wt", "status": "active", "created_at": "2026-03-18T10:00:00"}'
    wt = WorktreeInfo.model_validate_json(data)
    assert wt.agent_pane_id is None


def test_detail_panel_auto_accept_on() -> None:
    """Detail panel shows 'on' for auto_accept=True."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/x",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
        auto_accept=True,
    )
    panel.show_worktree(wt)
    assert "on" in panel._rows["Accept"]


def test_detail_panel_auto_accept_off() -> None:
    """Detail panel shows 'off' for auto_accept=False."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/x",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
        auto_accept=False,
    )
    panel.show_worktree(wt)
    assert "off" in panel._rows["Accept"]


# --- _detect_accept_key tests ---


def test_detect_accept_key_prefers_dont_ask_again() -> None:
    """Should return the option number for 'Yes, and don't ask again'."""
    content = """\
 Do you want to proceed?
 ❯ 1. Yes
   2. Yes, and don't ask again for: git rebase:*
   3. No
"""
    assert _detect_accept_key(content) == "2"


def test_detect_accept_key_falls_back_to_yes() -> None:
    """When no 'don't ask again' option, returns the plain Yes option."""
    content = """\
 Do you want to proceed?
 ❯ 1. Yes
   2. No
"""
    assert _detect_accept_key(content) == "1"


def test_detect_accept_key_returns_none_for_traditional_prompt() -> None:
    """Returns None for [Y/n] style prompts (no numbered options)."""
    content = "Continue? [Y/n] "
    assert _detect_accept_key(content) is None


def test_detect_accept_key_handles_cursor_on_option_2() -> None:
    """Works when cursor is already on option 2."""
    content = """\
 Do you want to proceed?
   1. Yes
 ❯ 2. Yes, and don't ask again for: ruff check
   3. No
"""
    assert _detect_accept_key(content) == "2"


def test_detail_panel_content_height_empty() -> None:
    """get_content_height returns 1 when no worktree is shown."""
    panel = WorktreeDetailPanel()
    assert panel.get_content_height(Size(80, 24), Size(80, 24), 80) == 1


def test_detail_panel_content_height_with_rows() -> None:
    """get_content_height returns the number of rows when a worktree is shown."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/x",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.ACTIVE,
        created_at=datetime(2026, 3, 18, 10, 0),
    )
    panel.show_worktree(wt)
    height = panel.get_content_height(Size(80, 24), Size(80, 24), 80)
    assert height == len(panel._rows)
    assert height >= 7  # Branch, Status, Accept, Profile, Window, Path, Created


def test_detail_panel_all_statuses_have_style() -> None:
    """Every WorktreeStatus has an entry in both _STATUS_LABEL and _STATUS_STYLE."""
    for status in WorktreeStatus:
        assert status in _STATUS_LABEL, f"{status} missing from _STATUS_LABEL"
        assert status in _STATUS_STYLE, f"{status} missing from _STATUS_STYLE"
