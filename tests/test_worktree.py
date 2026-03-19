"""Tests for the WorktreeManager (integration-level, no tmux)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import bouquet.models as models_mod
from bouquet.config import BouquetSettings
from bouquet.git import create_worktree as git_create_worktree
from bouquet.models import SessionState, WorktreeStatus
from bouquet.worktree import WorktreeManager


@pytest.fixture
def mock_tmux() -> MagicMock:
    """Return a mock TmuxManager."""
    tmux = MagicMock()
    mock_window = MagicMock()
    mock_window.window_id = "@1"
    tmux.create_window.return_value = mock_window
    return tmux


@pytest.fixture
def manager(
    sample_settings: BouquetSettings,
    tmp_git_repo: Path,
    tmp_path: Path,
    mock_tmux: MagicMock,
    monkeypatch: object,
) -> WorktreeManager:
    """Return a WorktreeManager with mocked tmux and redirected state dir."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: state_dir),
    )

    state = SessionState(
        project_name="test-project",
        tmux_session_name="bouquet-test-project",
        repo_path=tmp_git_repo,
    )
    state.save()

    # Disable bootstrap commands for tests
    sample_settings.bootstrap.python_deps_command = ""
    sample_settings.bootstrap.node_deps_command = ""
    sample_settings.bootstrap.copy_env_files = []
    sample_settings.bootstrap.use_cow_clone = False

    return WorktreeManager(sample_settings, state, mock_tmux)


def test_create_worktree(manager: WorktreeManager) -> None:
    info = manager.create("feature/test-create")
    assert info.branch == "feature/test-create"
    assert info.status == WorktreeStatus.ACTIVE
    assert info.path.exists()
    assert info.tmux_window_id == "@1"

    # Verify tmux interactions
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)
    mock_tmux.create_window.assert_called_once()
    mock_tmux.send_keys.assert_called_once()


def test_remove_worktree(manager: WorktreeManager) -> None:
    manager.create("feature/test-remove")
    assert len(manager.list_active()) == 1

    manager.remove("feature/test-remove")
    assert len(manager.list_active()) == 0


def test_list_active(manager: WorktreeManager) -> None:
    assert manager.list_active() == []

    manager.create("feature/a")
    manager.create("feature/b")
    active = manager.list_active()
    assert len(active) == 2
    branches = {w.branch for w in active}
    assert branches == {"feature/a", "feature/b"}


def test_adopt_existing(manager: WorktreeManager, tmp_git_repo: Path) -> None:
    """adopt_existing should discover pre-existing git worktrees."""
    # Create a worktree outside of bouquet (simulating manual creation)
    wt_path = tmp_git_repo.parent / "manual-worktree"
    git_create_worktree(tmp_git_repo, wt_path, "feature/manual", "main")

    assert manager.list_active() == []

    adopted = manager.adopt_existing()
    assert len(adopted) == 1
    assert adopted[0].branch == "feature/manual"
    assert adopted[0].status == WorktreeStatus.ACTIVE
    assert adopted[0].tmux_window_id == "@1"

    # Should now appear in list_active
    assert len(manager.list_active()) == 1


def test_adopt_existing_skips_main_worktree(manager: WorktreeManager) -> None:
    """adopt_existing should not adopt the main repo worktree."""
    adopted = manager.adopt_existing()
    assert len(adopted) == 0


def test_adopt_existing_skips_already_tracked(manager: WorktreeManager, tmp_git_repo: Path) -> None:
    """adopt_existing should skip worktrees already in session state."""
    # Create a worktree through bouquet (tracked)
    manager.create("feature/tracked")
    assert len(manager.list_active()) == 1

    # adopt_existing should not duplicate it
    adopted = manager.adopt_existing()
    assert len(adopted) == 0
    assert len(manager.list_active()) == 1


def test_remove_all(manager: WorktreeManager) -> None:
    manager.create("feature/x")
    manager.create("feature/y")
    assert len(manager.list_active()) == 2

    manager.remove_all()
    assert len(manager.list_active()) == 0
