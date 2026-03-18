"""Tests for data models."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import bouquet.models as models_mod
from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus


def test_worktree_info_defaults() -> None:
    info = WorktreeInfo(branch="feature/test", path=Path("/tmp/wt"))
    assert info.status == WorktreeStatus.CREATING
    assert info.tmux_window_id is None
    assert isinstance(info.created_at, datetime)


def test_session_state_save_load(tmp_path: Path, monkeypatch: object) -> None:
    # Redirect state dir to tmp_path
    monkeypatch.setattr(  # type: ignore[attr-defined]
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: tmp_path),
    )

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


def test_session_state_delete(tmp_path: Path, monkeypatch: object) -> None:
    monkeypatch.setattr(  # type: ignore[attr-defined]
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: tmp_path),
    )

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
    assert WorktreeStatus.IDLE == "idle"
    assert WorktreeStatus.ERROR == "error"
    assert WorktreeStatus.REMOVING == "removing"
