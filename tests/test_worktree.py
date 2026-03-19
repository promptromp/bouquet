"""Tests for the WorktreeManager (integration-level, no tmux)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

import bouquet.models as models_mod
from bouquet.config import BouquetSettings, ServiceConfig
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

    # Verify tmux interactions — uses window-ID-based send_keys
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)
    mock_tmux.create_window.assert_called_once()
    mock_tmux.send_keys_to_window_id.assert_called_once()


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
    """adopt_existing should fully initialise adopted worktrees (window + agent)."""
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

    # Verify agent was launched in the adopted worktree
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)
    mock_tmux.send_keys_to_window_id.assert_called_once()


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


# --- Index allocation ---


def test_index_allocation(manager: WorktreeManager) -> None:
    info1 = manager.create("feature/idx1")
    info2 = manager.create("feature/idx2")
    assert info1.index == 1
    assert info2.index == 2


def test_index_reuse_after_removal(manager: WorktreeManager) -> None:
    manager.create("feature/r1")  # index 1
    manager.create("feature/r2")  # index 2
    manager.remove("feature/r1")

    info3 = manager.create("feature/r3")
    assert info3.index == 1  # reused


def test_adopt_existing_allocates_indices(manager: WorktreeManager, tmp_git_repo: Path) -> None:
    wt_path = tmp_git_repo.parent / "manual-idx-wt"
    git_create_worktree(tmp_git_repo, wt_path, "feature/manual-idx", "main")

    adopted = manager.adopt_existing()
    assert len(adopted) == 1
    assert adopted[0].index == 1


# --- Services integration ---


def test_create_with_services(
    sample_settings: BouquetSettings,
    tmp_git_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """When services are configured, create should call setup_service_panes."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: state_dir),
    )

    sample_settings.bootstrap.python_deps_command = ""
    sample_settings.bootstrap.node_deps_command = ""
    sample_settings.bootstrap.copy_env_files = []
    sample_settings.bootstrap.use_cow_clone = False
    sample_settings.services = [
        ServiceConfig(name="api", command="serve --port {{ 8000 + BOUQUET_WORKTREE_INDEX }}"),
        ServiceConfig(name="worker", command="work"),
    ]
    sample_settings.tmux.layout = "main-vertical"

    tmux = MagicMock()
    mock_window = MagicMock()
    mock_window.window_id = "@1"
    tmux.create_window.return_value = mock_window

    state = SessionState(
        project_name="test-project",
        tmux_session_name="bouquet-test-project",
        repo_path=tmp_git_repo,
    )
    state.save()

    mgr = WorktreeManager(sample_settings, state, tmux)
    info = mgr.create("feature/svc-test")

    # Verify setup_service_panes was called with rendered commands
    tmux.setup_service_panes.assert_called_once()
    call_kwargs = tmux.setup_service_panes.call_args
    rendered_cmds = call_kwargs.kwargs.get("service_commands") or call_kwargs[1].get("service_commands")
    if rendered_cmds is None:
        rendered_cmds = call_kwargs[0][1]
    assert "serve --port 8001" in rendered_cmds
    assert "work" in rendered_cmds
    assert call_kwargs.kwargs.get("layout") or call_kwargs[1].get("layout") == "main-vertical"

    assert info.index == 1


def test_create_without_services_no_panes(manager: WorktreeManager) -> None:
    """When no services configured, setup_service_panes should not be called."""
    manager.create("feature/no-svc")
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)
    mock_tmux.setup_service_panes.assert_not_called()


# --- services-top layout ---


def test_create_with_services_uses_default_layout(
    sample_settings: BouquetSettings,
    tmp_git_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Default layout should be services-top."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: state_dir),
    )

    sample_settings.bootstrap.python_deps_command = ""
    sample_settings.bootstrap.node_deps_command = ""
    sample_settings.bootstrap.copy_env_files = []
    sample_settings.bootstrap.use_cow_clone = False
    sample_settings.services = [
        ServiceConfig(name="api", command="serve"),
    ]
    # Don't set layout — should default to "services-top"

    tmux = MagicMock()
    mock_window = MagicMock()
    mock_window.window_id = "@1"
    tmux.create_window.return_value = mock_window

    state = SessionState(
        project_name="test-project",
        tmux_session_name="bouquet-test-project",
        repo_path=tmp_git_repo,
    )
    state.save()

    mgr = WorktreeManager(sample_settings, state, tmux)
    mgr.create("feature/default-layout")

    call_kwargs = tmux.setup_service_panes.call_args
    assert call_kwargs.kwargs.get("layout") == "services-top"


# --- Setup commands env propagation to tmux ---


def test_create_with_setup_commands_sets_tmux_env(
    sample_settings: BouquetSettings,
    tmp_git_repo: Path,
    tmp_path: Path,
    monkeypatch: object,
) -> None:
    """Setup command env vars should be set on the tmux session."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(  # type: ignore[attr-defined]
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: state_dir),
    )

    sample_settings.bootstrap.setup_commands = ["export BOUQUET_TMUX_TEST=hello"]
    sample_settings.bootstrap.python_deps_command = ""
    sample_settings.bootstrap.node_deps_command = ""
    sample_settings.bootstrap.copy_env_files = []
    sample_settings.bootstrap.use_cow_clone = False

    tmux = MagicMock()
    mock_window = MagicMock()
    mock_window.window_id = "@1"
    tmux.create_window.return_value = mock_window

    state = SessionState(
        project_name="test-project",
        tmux_session_name="bouquet-test-project",
        repo_path=tmp_git_repo,
    )
    state.save()

    mgr = WorktreeManager(sample_settings, state, tmux)
    mgr.create("feature/setup-env-test")

    # Verify set_session_environment was called with the exported var
    tmux.set_session_environment.assert_any_call(
        "bouquet-test-project",
        "BOUQUET_TMUX_TEST",
        "hello",
    )


def test_create_without_setup_commands_no_tmux_env(manager: WorktreeManager) -> None:
    """Without setup_commands, set_session_environment should not be called."""
    manager.create("feature/no-setup")
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)
    mock_tmux.set_session_environment.assert_not_called()


# --- Window name bug fix ---


def test_window_name_replaces_slashes(manager: WorktreeManager) -> None:
    """_window_name should use the full branch with / replaced by -."""
    assert manager._window_name("feature/auth") == "feature-auth"
    assert manager._window_name("bugfix/auth") == "bugfix-auth"
    assert manager._window_name("simple") == "simple"


def test_window_name_uniqueness(manager: WorktreeManager) -> None:
    """Different prefixes with the same suffix should produce different names."""
    assert manager._window_name("feature/auth") != manager._window_name("bugfix/auth")


# --- Agent profile ---


def test_create_with_agent_profile(manager: WorktreeManager) -> None:
    """create() should store agent_profile on WorktreeInfo."""
    info = manager.create("feature/profile-test", agent_profile="aider")
    assert info.agent_profile == "aider"


def test_create_without_agent_profile(manager: WorktreeManager) -> None:
    """create() without profile should default to None."""
    info = manager.create("feature/no-profile")
    assert info.agent_profile is None


# --- Window-ID-based operations ---


def test_remove_uses_window_id(manager: WorktreeManager) -> None:
    """remove() should use kill_window_by_id when window_id is available."""
    manager.create("feature/rm-by-id")
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)
    mock_tmux.kill_window_by_id.reset_mock()

    manager.remove("feature/rm-by-id")
    mock_tmux.kill_window_by_id.assert_called_once()


def test_switch_to_uses_window_id(manager: WorktreeManager) -> None:
    """switch_to() should use switch_to_window_by_id when window_id is available."""
    manager.create("feature/switch-by-id")
    mock_tmux = manager.tmux
    assert isinstance(mock_tmux, MagicMock)

    manager.switch_to("feature/switch-by-id")
    mock_tmux.switch_to_window_by_id.assert_called()
