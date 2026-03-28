"""Tests for the AutopilotController."""

from __future__ import annotations

from pathlib import Path

import pytest

from bouquet.autopilot import AutopilotController
from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus
from bouquet.tasks.base import TaskStatus
from bouquet.tasks.local import LocalBackend


@pytest.fixture
def backend(tmp_path: Path) -> LocalBackend:
    return LocalBackend(db_path=str(tmp_path / "tasks.db"))


@pytest.fixture
def session_state() -> SessionState:
    return SessionState(
        project_name="test",
        tmux_session_name="bouquet-test",
        repo_path=Path("/tmp/test-repo"),
        worktrees=[],
    )


@pytest.fixture
def controller(backend: LocalBackend) -> AutopilotController:
    return AutopilotController(backend=backend, max_concurrency=2)


def test_tick_inactive_returns_empty(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    backend.create_task("Task 1")
    assert controller.active is False
    assert controller.tick(session_state) == []


def test_tick_returns_ready_tasks(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    backend.create_task("Task A")
    backend.create_task("Task B")
    controller.start()
    assert controller.active is True

    tasks = controller.tick(session_state)
    assert len(tasks) == 2
    assert {t.title for t in tasks} == {"Task A", "Task B"}


def test_tick_respects_max_concurrency(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    backend.create_task("Task A")
    backend.create_task("Task B")
    backend.create_task("Task C")
    controller.start()

    tasks = controller.tick(session_state)
    assert len(tasks) == 2  # max_concurrency is 2


def test_tick_accounts_for_active_worktrees(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    backend.create_task("Task A")
    backend.create_task("Task B")
    # One worktree already has a task
    session_state.worktrees.append(
        WorktreeInfo(branch="existing", path=Path("."), status=WorktreeStatus.ACTIVE, task_id="99")
    )
    controller.start()

    tasks = controller.tick(session_state)
    assert len(tasks) == 1  # Only 1 slot left (2 max - 1 active)


def test_tick_skips_blocked_tasks(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    parent = backend.create_task("Parent")
    backend.create_task("Child", parent_id=parent.id)
    controller.start()

    tasks = controller.tick(session_state)
    assert len(tasks) == 1
    assert tasks[0].title == "Parent"


def test_tick_picks_up_after_parent_done(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    parent = backend.create_task("Parent")
    backend.create_task("Child", parent_id=parent.id)
    backend.update_status(parent.id, TaskStatus.DONE)
    controller.start()

    tasks = controller.tick(session_state)
    assert len(tasks) == 1
    assert tasks[0].title == "Child"


def test_double_pickup_guard(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    backend.create_task("Task A")
    controller.start()

    tasks1 = controller.tick(session_state)
    assert len(tasks1) == 1

    # Second tick should not return the same task (it's in _picked_up_ids)
    tasks2 = controller.tick(session_state)
    assert tasks2 == []


def test_on_task_completed_clears_tracking(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    task = backend.create_task("Task A")
    controller.start()

    tasks1 = controller.tick(session_state)
    assert len(tasks1) == 1

    # Complete the task
    backend.update_status(task.id, TaskStatus.DONE)
    controller.on_task_completed(task.id)

    # Now tick should not return the completed task (it's DONE, not OPEN)
    tasks2 = controller.tick(session_state)
    assert tasks2 == []


def test_stop_clears_state(controller: AutopilotController, backend: LocalBackend, session_state: SessionState) -> None:
    backend.create_task("Task A")
    controller.start()
    controller.tick(session_state)
    controller.stop()

    assert controller.active is False
    # After stop + start, picked_up_ids should be cleared
    controller.start()
    tasks = controller.tick(session_state)
    assert len(tasks) == 1


def test_max_concurrency_setter(controller: AutopilotController) -> None:
    controller.max_concurrency = 5
    assert controller.max_concurrency == 5

    controller.max_concurrency = 0  # Floor to 1
    assert controller.max_concurrency == 1

    controller.max_concurrency = -1  # Floor to 1
    assert controller.max_concurrency == 1


def test_tick_fan_out_parallel(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    """When a parent is DONE, all its children are ready simultaneously."""
    parent = backend.create_task("Parent")
    backend.create_task("Child A", parent_id=parent.id)
    backend.create_task("Child B", parent_id=parent.id)
    backend.update_status(parent.id, TaskStatus.DONE)
    controller.start()

    tasks = controller.tick(session_state)
    assert len(tasks) == 2
    assert {t.title for t in tasks} == {"Child A", "Child B"}


def test_stop_clears_picked_up_ids_fully(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    """Verify stop/start cycle fully resets internal tracking state."""
    backend.create_task("Task A")
    backend.create_task("Task B")
    controller.start()

    # Pick up both tasks
    tasks1 = controller.tick(session_state)
    assert len(tasks1) == 2

    # Stop and restart — picked_up_ids must be cleared
    controller.stop()
    assert not controller.active
    controller.start()

    # Tasks are still OPEN, so they should be returned again
    tasks2 = controller.tick(session_state)
    assert len(tasks2) == 2


def test_tick_chain_unblocks_progressively(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    """A->B->C chain: only A is ready, then B after A is done, then C."""
    a = backend.create_task("A")
    b = backend.create_task("B", parent_id=a.id)
    c = backend.create_task("C", parent_id=b.id)
    controller.start()

    # Only A is ready
    tasks = controller.tick(session_state)
    assert [t.id for t in tasks] == [a.id]

    # Complete A, clear tracking — B should become ready
    backend.update_status(a.id, TaskStatus.DONE)
    controller.on_task_completed(a.id)
    tasks = controller.tick(session_state)
    assert [t.id for t in tasks] == [b.id]

    # Complete B — C should become ready
    backend.update_status(b.id, TaskStatus.DONE)
    controller.on_task_completed(b.id)
    tasks = controller.tick(session_state)
    assert [t.id for t in tasks] == [c.id]


def test_tick_does_not_return_in_progress_tasks(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    """Tasks already IN_PROGRESS should not be returned by tick."""
    task = backend.create_task("Running task")
    backend.update_status(task.id, TaskStatus.IN_PROGRESS, branch="task/1-running")
    controller.start()

    tasks = controller.tick(session_state)
    assert tasks == []


def test_tick_ignores_worktrees_without_task_id(
    controller: AutopilotController, backend: LocalBackend, session_state: SessionState
) -> None:
    """Manual worktrees (no task_id) should not count toward concurrency limit."""
    backend.create_task("Task A")
    backend.create_task("Task B")
    backend.create_task("Task C")
    # Add a manual worktree (no task_id)
    session_state.worktrees.append(WorktreeInfo(branch="manual-wt", path=Path("."), status=WorktreeStatus.ACTIVE))
    controller.start()

    # Should still have 2 slots (manual worktree doesn't count)
    tasks = controller.tick(session_state)
    assert len(tasks) == 2
