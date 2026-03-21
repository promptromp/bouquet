"""Tests for the LocalBackend task queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from bouquet.tasks.base import TaskBackendError, TaskStatus
from bouquet.tasks.local import LocalBackend


def test_create_task(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Fix login page")
    assert task.id == "1"
    assert task.title == "Fix login page"
    assert task.status == TaskStatus.OPEN
    assert task.source == "local"


def test_create_task_with_description(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Fix login", description="The page crashes on submit")
    assert task.description == "The page crashes on submit"


def test_create_task_with_labels(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Fix login", labels=["bug", "urgent"])
    assert task.labels == ["bug", "urgent"]


def test_list_tasks_empty(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    assert backend.list_tasks() == []


def test_list_tasks(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    backend.create_task("Task A")
    backend.create_task("Task B")
    tasks = backend.list_tasks()
    assert len(tasks) == 2
    assert tasks[0].title == "Task A"
    assert tasks[1].title == "Task B"


def test_list_tasks_filter_by_status(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    backend.create_task("Open task")
    t2 = backend.create_task("Done task")
    backend.update_status(t2.id, TaskStatus.DONE)

    open_tasks = backend.list_tasks(status=TaskStatus.OPEN)
    assert len(open_tasks) == 1
    assert open_tasks[0].title == "Open task"

    done_tasks = backend.list_tasks(status=TaskStatus.DONE)
    assert len(done_tasks) == 1
    assert done_tasks[0].title == "Done task"


def test_get_task(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    created = backend.create_task("Get me")
    task = backend.get_task(created.id)
    assert task is not None
    assert task.title == "Get me"


def test_get_task_not_found(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    assert backend.get_task("999") is None


def test_update_status(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Update me")
    updated = backend.update_status(task.id, TaskStatus.IN_PROGRESS, branch="task/1-update-me")
    assert updated.status == TaskStatus.IN_PROGRESS
    assert updated.branch == "task/1-update-me"


def test_update_status_without_branch(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Just status")
    updated = backend.update_status(task.id, TaskStatus.DONE)
    assert updated.status == TaskStatus.DONE
    assert updated.branch is None


def test_delete_task(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Delete me")
    backend.delete_task(task.id)
    assert backend.get_task(task.id) is None
    assert backend.list_tasks() == []


def test_auto_increment_ids(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    t1 = backend.create_task("First")
    t2 = backend.create_task("Second")
    assert t1.id == "1"
    assert t2.id == "2"


def test_reconcile_stale_resets_orphaned_tasks(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    t1 = backend.create_task("Task A")
    backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-task-a")
    t2 = backend.create_task("Task B")
    backend.update_status(t2.id, TaskStatus.IN_PROGRESS, branch="task/2-task-b")

    reset = backend.reconcile_stale(set())
    assert len(reset) == 2
    assert backend.get_task(t1.id).status == TaskStatus.OPEN  # type: ignore[union-attr]
    assert backend.get_task(t2.id).status == TaskStatus.OPEN  # type: ignore[union-attr]


def test_reconcile_stale_preserves_active_tasks(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    t1 = backend.create_task("Active task")
    backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-active")

    reset = backend.reconcile_stale({"task/1-active"})
    assert reset == []
    assert backend.get_task(t1.id).status == TaskStatus.IN_PROGRESS  # type: ignore[union-attr]


def test_reconcile_stale_mixed(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    t1 = backend.create_task("Active")
    backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-active")
    t2 = backend.create_task("Stale")
    backend.update_status(t2.id, TaskStatus.IN_PROGRESS, branch="task/2-stale")

    reset = backend.reconcile_stale({"task/1-active"})
    assert len(reset) == 1
    assert reset[0].id == t2.id
    assert backend.get_task(t1.id).status == TaskStatus.IN_PROGRESS  # type: ignore[union-attr]
    assert backend.get_task(t2.id).status == TaskStatus.OPEN  # type: ignore[union-attr]


def test_reconcile_stale_returns_reset_list(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    t1 = backend.create_task("Will reset")
    backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-reset")

    reset = backend.reconcile_stale(set())
    assert len(reset) == 1
    assert reset[0].id == t1.id
    assert reset[0].title == "Will reset"


def test_reconcile_stale_no_in_progress(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    backend.create_task("Open task")
    t2 = backend.create_task("Done task")
    backend.update_status(t2.id, TaskStatus.DONE)

    reset = backend.reconcile_stale(set())
    assert reset == []


def test_reconcile_stale_task_with_no_branch(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    t1 = backend.create_task("No branch task")
    # Manually set to IN_PROGRESS without a branch
    backend.update_status(t1.id, TaskStatus.IN_PROGRESS)

    reset = backend.reconcile_stale({"some-branch"})
    assert len(reset) == 1
    assert reset[0].id == t1.id
    assert backend.get_task(t1.id).status == TaskStatus.OPEN  # type: ignore[union-attr]


def test_update_status_not_found_raises_backend_error(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    with pytest.raises(TaskBackendError, match="not found"):
        backend.update_status("999", TaskStatus.DONE)


def test_task_timestamps(tmp_path: Path) -> None:
    backend = LocalBackend(db_path=str(tmp_path / "tasks.db"))
    task = backend.create_task("Timed task")
    assert task.created_at is not None
    assert task.updated_at is not None
    # updated_at should change after status update
    old_updated = task.updated_at
    updated = backend.update_status(task.id, TaskStatus.IN_PROGRESS)
    assert updated.updated_at >= old_updated
