"""Tests for data models."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus


def test_worktree_info_defaults() -> None:
    info = WorktreeInfo(branch="feature/test", path=Path("/tmp/wt"))
    assert info.status == WorktreeStatus.CREATING
    assert info.tmux_window_id is None
    assert isinstance(info.created_at, datetime)


def test_session_state_save_load(mock_state_dir: Path) -> None:
    state = SessionState(
        project_name="test",
        tmux_session_name="bouquet-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/x", path=Path("/tmp/wt/x")),
        ],
    )
    state.save()

    loaded = SessionState.load("test")
    assert loaded is not None
    assert loaded.project_name == "test"
    assert loaded.tmux_session_name == "bouquet-test"
    assert len(loaded.worktrees) == 1
    assert loaded.worktrees[0].branch == "feat/x"


def test_session_state_delete(mock_state_dir: Path) -> None:
    state = SessionState(
        project_name="del-test",
        tmux_session_name="bouquet-del-test",
        repo_path=Path("/tmp/repo"),
    )
    state.save()
    assert SessionState.load("del-test") is not None

    state.delete_state()
    assert SessionState.load("del-test") is None


def test_worktree_status_values() -> None:
    assert WorktreeStatus.CREATING == "creating"
    assert WorktreeStatus.ACTIVE == "active"
    assert WorktreeStatus.RUNNING == "running"
    assert WorktreeStatus.WAITING == "waiting"
    assert WorktreeStatus.IDLE == "idle"
    assert WorktreeStatus.ERROR == "error"
    assert WorktreeStatus.REMOVING == "removing"


def test_worktree_info_index_default() -> None:
    info = WorktreeInfo(branch="feat/a", path=Path("/tmp/wt"))
    assert info.index == 0


def test_worktree_info_agent_profile_default() -> None:
    info = WorktreeInfo(branch="feat/a", path=Path("/tmp/wt"))
    assert info.agent_profile is None


def test_worktree_info_agent_profile_serialization(mock_state_dir: Path) -> None:
    state = SessionState(
        project_name="profile-test",
        tmux_session_name="bouquet-profile-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/x", path=Path("/tmp/wt/x"), agent_profile="aider"),
        ],
    )
    state.save()

    loaded = SessionState.load("profile-test")
    assert loaded is not None
    assert loaded.worktrees[0].agent_profile == "aider"


def test_worktree_info_index_serialization(mock_state_dir: Path) -> None:
    state = SessionState(
        project_name="idx-test",
        tmux_session_name="bouquet-idx-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/x", path=Path("/tmp/wt/x"), index=5),
        ],
    )
    state.save()

    loaded = SessionState.load("idx-test")
    assert loaded is not None
    assert loaded.worktrees[0].index == 5


def test_worktree_info_task_id_default() -> None:
    info = WorktreeInfo(branch="feat/a", path=Path("/tmp/wt"))
    assert info.task_id is None


def test_worktree_info_task_id_serialization(mock_state_dir: Path) -> None:
    state = SessionState(
        project_name="task-test",
        tmux_session_name="bouquet-task-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/x", path=Path("/tmp/wt/x"), task_id="42"),
        ],
    )
    state.save()

    loaded = SessionState.load("task-test")
    assert loaded is not None
    assert loaded.worktrees[0].task_id == "42"


def test_worktree_info_task_id_backward_compat() -> None:
    """Old JSON without task_id deserializes with task_id=None."""
    data = '{"branch": "feature/x", "path": "/tmp/wt", "status": "active", "created_at": "2026-03-18T10:00:00"}'
    wt = WorktreeInfo.model_validate_json(data)
    assert wt.task_id is None


# --- find_worktree / remove_worktree ---


def test_find_worktree_found() -> None:
    state = SessionState(
        project_name="test",
        tmux_session_name="bouquet-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/a", path=Path("/tmp/wt/a")),
            WorktreeInfo(branch="feat/b", path=Path("/tmp/wt/b")),
        ],
    )
    wt = state.find_worktree("feat/b")
    assert wt is not None
    assert wt.branch == "feat/b"


def test_find_worktree_not_found() -> None:
    state = SessionState(
        project_name="test",
        tmux_session_name="bouquet-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/a", path=Path("/tmp/wt/a")),
        ],
    )
    assert state.find_worktree("feat/missing") is None


def test_remove_worktree() -> None:
    state = SessionState(
        project_name="test",
        tmux_session_name="bouquet-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/a", path=Path("/tmp/wt/a")),
            WorktreeInfo(branch="feat/b", path=Path("/tmp/wt/b")),
        ],
    )
    state.remove_worktree("feat/a")
    assert len(state.worktrees) == 1
    assert state.worktrees[0].branch == "feat/b"


def test_remove_worktree_not_found() -> None:
    state = SessionState(
        project_name="test",
        tmux_session_name="bouquet-test",
        repo_path=Path("/tmp/repo"),
        worktrees=[
            WorktreeInfo(branch="feat/a", path=Path("/tmp/wt/a")),
        ],
    )
    state.remove_worktree("feat/missing")
    assert len(state.worktrees) == 1
