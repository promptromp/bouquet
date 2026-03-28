"""Tests for task DAG utilities."""

from __future__ import annotations

from datetime import datetime

import pytest

from bouquet.tasks.base import Task, TaskStatus
from bouquet.tasks.dag import detect_cycle, get_ready_tasks, topo_sort


def _task(id: str, parent_id: str | None = None, status: TaskStatus = TaskStatus.OPEN) -> Task:
    """Helper to create a minimal Task for testing."""
    now = datetime.now()
    return Task(id=id, title=f"Task {id}", parent_id=parent_id, status=status, created_at=now, updated_at=now)


class TestDetectCycle:
    def test_self_cycle(self):
        tasks = [_task("1")]
        assert detect_cycle(tasks, "1", "1") is True

    def test_direct_cycle(self):
        """A->B, proposing B->A creates a cycle."""
        tasks = [_task("1"), _task("2", parent_id="1")]
        assert detect_cycle(tasks, "1", "2") is True

    def test_transitive_cycle(self):
        """A->B->C, proposing C->A creates a cycle."""
        tasks = [_task("1"), _task("2", parent_id="1"), _task("3", parent_id="2")]
        assert detect_cycle(tasks, "1", "3") is True

    def test_no_cycle(self):
        """A->B->C, proposing D->A is fine."""
        tasks = [_task("1"), _task("2", parent_id="1"), _task("3", parent_id="2"), _task("4")]
        assert detect_cycle(tasks, "4", "1") is False

    def test_no_cycle_sibling(self):
        """A->B, A->C, proposing D->C is fine."""
        tasks = [_task("1"), _task("2", parent_id="1"), _task("3", parent_id="1"), _task("4")]
        assert detect_cycle(tasks, "4", "3") is False

    def test_no_cycle_independent(self):
        """Two independent tasks, proposing parent is fine."""
        tasks = [_task("1"), _task("2")]
        assert detect_cycle(tasks, "2", "1") is False

    def test_cycle_with_unknown_parent(self):
        """Proposed parent not in task list — no cycle (parent doesn't exist yet in graph)."""
        tasks = [_task("1")]
        assert detect_cycle(tasks, "1", "99") is False


class TestTopoSort:
    def test_empty(self):
        assert topo_sort([]) == []

    def test_single_task(self):
        tasks = [_task("1")]
        result = topo_sort(tasks)
        assert [t.id for t in result] == ["1"]

    def test_linear_chain(self):
        """C depends on B depends on A → sorted A, B, C."""
        tasks = [_task("3", parent_id="2"), _task("1"), _task("2", parent_id="1")]
        result = topo_sort(tasks)
        ids = [t.id for t in result]
        assert ids.index("1") < ids.index("2") < ids.index("3")

    def test_fan_out(self):
        """A is parent of B and C — A must come first."""
        tasks = [_task("2", parent_id="1"), _task("3", parent_id="1"), _task("1")]
        result = topo_sort(tasks)
        ids = [t.id for t in result]
        assert ids.index("1") < ids.index("2")
        assert ids.index("1") < ids.index("3")

    def test_forest(self):
        """Two independent chains: A->B and C->D."""
        tasks = [_task("2", parent_id="1"), _task("1"), _task("4", parent_id="3"), _task("3")]
        result = topo_sort(tasks)
        ids = [t.id for t in result]
        assert ids.index("1") < ids.index("2")
        assert ids.index("3") < ids.index("4")

    def test_cycle_raises(self):
        """Defensive: tasks with a cycle raise ValueError."""
        # Manually create a cycle (shouldn't happen in practice)
        tasks = [_task("1", parent_id="2"), _task("2", parent_id="1")]
        with pytest.raises(ValueError, match="Cycle detected"):
            topo_sort(tasks)

    def test_parent_outside_list_ignored(self):
        """Task with parent_id pointing to a task not in the list — treated as root."""
        tasks = [_task("2", parent_id="99"), _task("1")]
        result = topo_sort(tasks)
        assert len(result) == 2


class TestGetReadyTasks:
    def test_no_deps_all_ready(self):
        tasks = [_task("1"), _task("2")]
        ready = get_ready_tasks(tasks)
        assert len(ready) == 2

    def test_blocked_by_open_parent(self):
        tasks = [_task("1"), _task("2", parent_id="1")]
        ready = get_ready_tasks(tasks)
        assert [t.id for t in ready] == ["1"]

    def test_unblocked_by_done_parent(self):
        tasks = [_task("1", status=TaskStatus.DONE), _task("2", parent_id="1")]
        ready = get_ready_tasks(tasks)
        assert [t.id for t in ready] == ["2"]

    def test_in_progress_parent_blocks(self):
        tasks = [_task("1", status=TaskStatus.IN_PROGRESS), _task("2", parent_id="1")]
        ready = get_ready_tasks(tasks)
        assert ready == []

    def test_skips_non_open_tasks(self):
        """Only OPEN tasks can be ready."""
        tasks = [
            _task("1", status=TaskStatus.DONE),
            _task("2", parent_id="1", status=TaskStatus.IN_PROGRESS),
            _task("3", parent_id="1"),
        ]
        ready = get_ready_tasks(tasks)
        assert [t.id for t in ready] == ["3"]

    def test_chain_only_first_ready(self):
        """A->B->C, only A is ready."""
        tasks = [_task("1"), _task("2", parent_id="1"), _task("3", parent_id="2")]
        ready = get_ready_tasks(tasks)
        assert [t.id for t in ready] == ["1"]

    def test_parent_outside_list(self):
        """Task with parent_id pointing to unknown task — not ready (parent not DONE)."""
        tasks = [_task("1", parent_id="99")]
        ready = get_ready_tasks(tasks)
        assert ready == []
