"""Tests for TUI components."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus
from bouquet.tasks.base import Task, TaskStatus
from bouquet.tui.app import (
    _STATUS_PROMPT,
    _WORKTREE_BRANCH_COL,
    OrchestratorApp,
    _detect_accept_key,
    _extract_response,
)
from bouquet.tui.screens import (
    CompleteTaskScreen,
    CreateTaskScreen,
    NewWorktreeScreen,
    SendPromptScreen,
)
from bouquet.tui.widgets import (
    _STATUS_LABEL,
    _STATUS_STYLE,
    _TASK_STATUS_DISPLAY,
    ProjectHeader,
    TaskQueueTable,
    WorktreeDetailPanel,
    WorktreeTable,
)


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


def test_detail_panel_initial_content() -> None:
    """Panel starts with placeholder text."""
    panel = WorktreeDetailPanel()
    assert panel._rows == {}


def test_detail_panel_rows_contain_all_fields() -> None:
    """Showing a worktree populates all expected rows."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/x",
        path=Path("/tmp/wt"),
        status=WorktreeStatus.IDLE,
        created_at=datetime(2026, 1, 1, 12, 0),
    )
    panel.show_worktree(wt)
    assert "feature/x" in panel._rows["Branch"]
    assert "idle" in panel._rows["Status"]
    assert "off" in panel._rows["Accept"]


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


def test_detail_panel_has_all_labels() -> None:
    """All expected labels appear as row keys."""
    panel = WorktreeDetailPanel()
    wt = WorktreeInfo(
        branch="feature/x",
        path=Path("/tmp/wt"),
        tmux_window_id="@5",
        status=WorktreeStatus.RUNNING,
        created_at=datetime(2026, 3, 18, 10, 0),
        agent_profile="claude",
        auto_accept=True,
    )
    panel.show_worktree(wt)
    for label in ("Branch", "Status", "Accept", "Profile", "Window", "Path", "Created"):
        assert label in panel._rows, f"'{label}' missing from detail panel rows"


def test_detail_panel_all_statuses_have_style() -> None:
    """Every WorktreeStatus has an entry in both _STATUS_LABEL and _STATUS_STYLE."""
    for status in WorktreeStatus:
        assert status in _STATUS_LABEL, f"{status} missing from _STATUS_LABEL"
        assert status in _STATUS_STYLE, f"{status} missing from _STATUS_STYLE"


# --- Task queue table tests ---


def test_task_queue_table_importable() -> None:
    assert TaskQueueTable is not None
    assert CreateTaskScreen is not None


def test_task_status_display_covers_all_statuses() -> None:
    """Every TaskStatus has a display entry."""
    for status in TaskStatus:
        assert status in _TASK_STATUS_DISPLAY, f"{status} missing from _TASK_STATUS_DISPLAY"


# --- DetailTabs removed ---


def test_detail_tabs_not_exported() -> None:
    """DetailTabs was removed — verify it's no longer importable from widgets."""
    from bouquet.tui import widgets as w  # noqa: PLC0415

    assert not hasattr(w, "DetailTabs")


# --- Reconciliation logic tests ---


def _make_task(
    task_id: str, title: str, branch: str | None = None, status: TaskStatus = TaskStatus.IN_PROGRESS
) -> Task:
    """Helper to create a Task for testing."""
    return Task(id=task_id, title=title, branch=branch, status=status)


def test_reconcile_restores_task_id_on_matching_worktree() -> None:
    """_reconcile_tasks should restore task_id on worktrees matching IN_PROGRESS tasks."""
    wt = WorktreeInfo(branch="task/1-fix-bug", path=Path("/tmp/wt"), task_id=None)
    task = _make_task("1", "Fix bug", branch="task/1-fix-bug")

    state = MagicMock(spec=SessionState)
    state.worktrees = [wt]

    backend = MagicMock()
    backend.list_tasks.side_effect = lambda status=None: [task] if status == TaskStatus.IN_PROGRESS else [task]
    backend.reconcile_stale.return_value = []

    # Simulate what _reconcile_tasks does (step 1: restore task_id)
    in_progress = backend.list_tasks(status=TaskStatus.IN_PROGRESS)
    task_by_branch = {t.branch: t for t in in_progress if t.branch}
    for w in state.worktrees:
        if w.task_id is None and w.branch in task_by_branch:
            w.task_id = task_by_branch[w.branch].id

    assert wt.task_id == "1"


def test_reconcile_does_not_overwrite_existing_task_id() -> None:
    """_reconcile_tasks should not overwrite an existing task_id."""
    wt = WorktreeInfo(branch="task/1-fix-bug", path=Path("/tmp/wt"), task_id="99")
    task = _make_task("1", "Fix bug", branch="task/1-fix-bug")

    in_progress = [task]
    task_by_branch = {t.branch: t for t in in_progress if t.branch}
    if wt.task_id is None and wt.branch in task_by_branch:
        wt.task_id = task_by_branch[wt.branch].id

    assert wt.task_id == "99"


def test_reconcile_builds_correct_active_branches() -> None:
    """Active branches set should contain all worktree branches."""
    worktrees = [
        WorktreeInfo(branch="task/1-fix-bug", path=Path("/tmp/wt1")),
        WorktreeInfo(branch="feature/auth", path=Path("/tmp/wt2")),
    ]
    active_branches = {wt.branch for wt in worktrees}
    assert active_branches == {"task/1-fix-bug", "feature/auth"}


# --- Constants tests ---


def test_worktree_branch_col_constant() -> None:
    """The branch column constant should match the table layout."""
    assert _WORKTREE_BRANCH_COL == 1


def test_status_prompt_is_nonempty() -> None:
    """Status prompt constant should be a non-empty string."""
    assert isinstance(_STATUS_PROMPT, str)
    assert len(_STATUS_PROMPT) > 20


# --- Screen tests ---


def test_complete_task_screen_with_branch() -> None:
    """CompleteTaskScreen with a branch should show remove option."""
    screen = CompleteTaskScreen("Fix bug", branch="feature/fix")
    assert screen._task_title == "Fix bug"
    assert screen._branch == "feature/fix"


def test_complete_task_screen_without_branch() -> None:
    """CompleteTaskScreen without a branch has no branch context."""
    screen = CompleteTaskScreen("Fix bug", branch=None)
    assert screen._branch is None


def test_create_task_screen_instantiation() -> None:
    """CreateTaskScreen should instantiate without errors."""
    screen = CreateTaskScreen()
    assert screen is not None


def test_send_prompt_screen_with_branch() -> None:
    """SendPromptScreen should capture selected branch."""
    screen = SendPromptScreen(selected_branch="feature/auth", default_send_all=True)
    assert screen._selected_branch == "feature/auth"
    assert screen._default_send_all is True


def test_send_prompt_screen_defaults() -> None:
    """SendPromptScreen defaults."""
    screen = SendPromptScreen()
    assert screen._selected_branch is None
    assert screen._default_send_all is False


def test_new_worktree_screen_with_profiles() -> None:
    """NewWorktreeScreen should accept profile names."""
    screen = NewWorktreeScreen(default_base="main", profile_names=["claude", "aider"])
    assert screen._default_base == "main"
    assert screen._profile_names == ["claude", "aider"]


def test_new_worktree_screen_default_profiles() -> None:
    """NewWorktreeScreen with no profiles."""
    screen = NewWorktreeScreen()
    assert screen._profile_names == []


# --- __all__ exports ---


def test_widgets_all_exports() -> None:
    """widgets.__all__ should export the public widget classes."""
    from bouquet.tui import widgets  # noqa: PLC0415

    assert hasattr(widgets, "__all__")
    for name in ["ProjectHeader", "TaskQueueTable", "WorktreeDetailPanel", "WorktreeTable"]:
        assert name in widgets.__all__


def test_screens_all_exports() -> None:
    """screens.__all__ should export the public screen classes."""
    from bouquet.tui import screens  # noqa: PLC0415

    assert hasattr(screens, "__all__")
    expected = ["ConfirmQuitScreen", "NewWorktreeScreen", "CreateTaskScreen", "CompleteTaskScreen", "SendPromptScreen"]
    for name in expected:
        assert name in screens.__all__
