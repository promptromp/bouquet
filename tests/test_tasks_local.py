"""Tests for the LocalBackend task queue."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from bouquet.tasks.base import TaskBackendError, TaskStatus
from bouquet.tasks.local import LocalBackend


def test_create_task(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Fix login page")
    assert task.id == "1"
    assert task.title == "Fix login page"
    assert task.status == TaskStatus.OPEN
    assert task.source == "local"


def test_create_task_with_description(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Fix login", description="The page crashes on submit")
    assert task.description == "The page crashes on submit"


def test_create_task_with_labels(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Fix login", labels=["bug", "urgent"])
    assert task.labels == ["bug", "urgent"]


def test_list_tasks_empty(local_backend: LocalBackend) -> None:
    assert local_backend.list_tasks() == []


def test_list_tasks(local_backend: LocalBackend) -> None:
    local_backend.create_task("Task A")
    local_backend.create_task("Task B")
    tasks = local_backend.list_tasks()
    assert len(tasks) == 2
    assert tasks[0].title == "Task A"
    assert tasks[1].title == "Task B"


def test_list_tasks_filter_by_status(local_backend: LocalBackend) -> None:
    local_backend.create_task("Open task")
    t2 = local_backend.create_task("Done task")
    local_backend.update_status(t2.id, TaskStatus.DONE)

    open_tasks = local_backend.list_tasks(status=TaskStatus.OPEN)
    assert len(open_tasks) == 1
    assert open_tasks[0].title == "Open task"

    done_tasks = local_backend.list_tasks(status=TaskStatus.DONE)
    assert len(done_tasks) == 1
    assert done_tasks[0].title == "Done task"


def test_get_task(local_backend: LocalBackend) -> None:
    created = local_backend.create_task("Get me")
    task = local_backend.get_task(created.id)
    assert task is not None
    assert task.title == "Get me"


def test_get_task_not_found(local_backend: LocalBackend) -> None:
    assert local_backend.get_task("999") is None


def test_update_status(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Update me")
    updated = local_backend.update_status(task.id, TaskStatus.IN_PROGRESS, branch="task/1-update-me")
    assert updated.status == TaskStatus.IN_PROGRESS
    assert updated.branch == "task/1-update-me"


def test_update_status_without_branch(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Just status")
    updated = local_backend.update_status(task.id, TaskStatus.DONE)
    assert updated.status == TaskStatus.DONE
    assert updated.branch is None


def test_delete_task(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Delete me")
    local_backend.delete_task(task.id)
    assert local_backend.get_task(task.id) is None
    assert local_backend.list_tasks() == []


def test_auto_increment_ids(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("First")
    t2 = local_backend.create_task("Second")
    assert t1.id == "1"
    assert t2.id == "2"


def test_reconcile_stale_resets_orphaned_tasks(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Task A")
    local_backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-task-a")
    t2 = local_backend.create_task("Task B")
    local_backend.update_status(t2.id, TaskStatus.IN_PROGRESS, branch="task/2-task-b")

    reset = local_backend.reconcile_stale(set())
    assert len(reset) == 2
    assert local_backend.get_task(t1.id).status == TaskStatus.OPEN  # type: ignore[union-attr]
    assert local_backend.get_task(t2.id).status == TaskStatus.OPEN  # type: ignore[union-attr]


def test_reconcile_stale_preserves_active_tasks(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Active task")
    local_backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-active")

    reset = local_backend.reconcile_stale({"task/1-active"})
    assert reset == []
    assert local_backend.get_task(t1.id).status == TaskStatus.IN_PROGRESS  # type: ignore[union-attr]


def test_reconcile_stale_mixed(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Active")
    local_backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-active")
    t2 = local_backend.create_task("Stale")
    local_backend.update_status(t2.id, TaskStatus.IN_PROGRESS, branch="task/2-stale")

    reset = local_backend.reconcile_stale({"task/1-active"})
    assert len(reset) == 1
    assert reset[0].id == t2.id
    assert local_backend.get_task(t1.id).status == TaskStatus.IN_PROGRESS  # type: ignore[union-attr]
    assert local_backend.get_task(t2.id).status == TaskStatus.OPEN  # type: ignore[union-attr]


def test_reconcile_stale_returns_reset_list(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Will reset")
    local_backend.update_status(t1.id, TaskStatus.IN_PROGRESS, branch="task/1-reset")

    reset = local_backend.reconcile_stale(set())
    assert len(reset) == 1
    assert reset[0].id == t1.id
    assert reset[0].title == "Will reset"


def test_reconcile_stale_no_in_progress(local_backend: LocalBackend) -> None:
    local_backend.create_task("Open task")
    t2 = local_backend.create_task("Done task")
    local_backend.update_status(t2.id, TaskStatus.DONE)

    reset = local_backend.reconcile_stale(set())
    assert reset == []


def test_reconcile_stale_task_with_no_branch(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("No branch task")
    # Manually set to IN_PROGRESS without a branch
    local_backend.update_status(t1.id, TaskStatus.IN_PROGRESS)

    reset = local_backend.reconcile_stale({"some-branch"})
    assert len(reset) == 1
    assert reset[0].id == t1.id
    assert local_backend.get_task(t1.id).status == TaskStatus.OPEN  # type: ignore[union-attr]


def test_update_status_not_found_raises_backend_error(local_backend: LocalBackend) -> None:
    with pytest.raises(TaskBackendError, match="not found"):
        local_backend.update_status("999", TaskStatus.DONE)


def test_task_timestamps(local_backend: LocalBackend) -> None:
    task = local_backend.create_task("Timed task")
    assert task.created_at is not None
    assert task.updated_at is not None
    # updated_at should change after status update
    old_updated = task.updated_at
    updated = local_backend.update_status(task.id, TaskStatus.IN_PROGRESS)
    assert updated.updated_at >= old_updated


# --- Parent / dependency tests ---


def test_create_task_with_parent(local_backend: LocalBackend) -> None:
    parent = local_backend.create_task("Parent task")
    child = local_backend.create_task("Child task", parent_id=parent.id)
    assert child.parent_id == parent.id


def test_create_task_with_nonexistent_parent(local_backend: LocalBackend) -> None:
    with pytest.raises(TaskBackendError, match="does not exist"):
        local_backend.create_task("Child", parent_id="999")


def test_set_parent(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Task A")
    t2 = local_backend.create_task("Task B")
    updated = local_backend.set_parent(t2.id, t1.id)
    assert updated.parent_id == t1.id


def test_set_parent_clear(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Parent")
    t2 = local_backend.create_task("Child", parent_id=t1.id)
    assert t2.parent_id == t1.id
    updated = local_backend.set_parent(t2.id, None)
    assert updated.parent_id is None


def test_set_parent_cycle_rejected(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("A")
    t2 = local_backend.create_task("B", parent_id=t1.id)
    with pytest.raises(TaskBackendError, match="cycle"):
        local_backend.set_parent(t1.id, t2.id)


def test_set_parent_self_cycle_rejected(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Self")
    with pytest.raises(TaskBackendError, match="cycle"):
        local_backend.set_parent(t1.id, t1.id)


def test_set_parent_nonexistent_parent(local_backend: LocalBackend) -> None:
    t1 = local_backend.create_task("Task")
    with pytest.raises(TaskBackendError, match="does not exist"):
        local_backend.set_parent(t1.id, "999")


def test_set_parent_nonexistent_task(local_backend: LocalBackend) -> None:
    with pytest.raises(TaskBackendError, match="not found"):
        local_backend.set_parent("999", "1")


def test_delete_task_orphans_children(local_backend: LocalBackend) -> None:
    parent = local_backend.create_task("Parent")
    child1 = local_backend.create_task("Child 1", parent_id=parent.id)
    child2 = local_backend.create_task("Child 2", parent_id=parent.id)
    local_backend.delete_task(parent.id)
    # Children should have parent_id cleared
    assert local_backend.get_task(child1.id).parent_id is None  # type: ignore[union-attr]
    assert local_backend.get_task(child2.id).parent_id is None  # type: ignore[union-attr]


def test_get_children(local_backend: LocalBackend) -> None:
    parent = local_backend.create_task("Parent")
    child1 = local_backend.create_task("Child 1", parent_id=parent.id)
    child2 = local_backend.create_task("Child 2", parent_id=parent.id)
    local_backend.create_task("Unrelated")
    children = local_backend.get_children(parent.id)
    assert len(children) == 2
    assert {c.id for c in children} == {child1.id, child2.id}


def test_schema_migration_adds_parent_id(tmp_path: Path) -> None:
    """Opening a LocalBackend against a pre-existing DB without parent_id should migrate it."""
    db_path = str(tmp_path / "legacy.db")
    # Create a legacy DB without parent_id column
    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE tasks (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            title       TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            status      TEXT NOT NULL DEFAULT 'open',
            branch      TEXT,
            labels      TEXT NOT NULL DEFAULT '[]',
            created_at  TEXT NOT NULL,
            updated_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
    """)
    conn.execute(
        "INSERT INTO tasks (title, created_at, updated_at) VALUES ('Old task', '2026-01-01', '2026-01-01')"
    )
    conn.commit()
    conn.close()

    # Opening LocalBackend should migrate without error
    backend = LocalBackend(db_path=db_path)
    tasks = backend.list_tasks()
    assert len(tasks) == 1
    assert tasks[0].title == "Old task"
    assert tasks[0].parent_id is None

    # parent_id should now work
    parent = backend.create_task("Parent")
    child = backend.create_task("Child", parent_id=parent.id)
    assert child.parent_id == parent.id
