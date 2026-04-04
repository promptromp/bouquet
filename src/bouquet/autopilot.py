"""Autopilot controller — schedules tasks from the DAG automatically."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bouquet.tasks.dag import get_ready_tasks


if TYPE_CHECKING:
    from bouquet.models import SessionState
    from bouquet.tasks.base import Task, TaskQueueBackend


class AutopilotController:
    """Drives task execution by monitoring the DAG and scheduling work.

    The controller does **not** own threads.  It provides a pure ``tick()``
    method that the TUI poll loop calls every cycle.  Ready tasks are
    returned for the caller to dispatch via its own threading model.
    """

    def __init__(
        self,
        backend: TaskQueueBackend,
        max_concurrency: int = 3,
        auto_branch_prefix: str = "task/",
    ) -> None:
        self._backend = backend
        self._max_concurrency = max(1, max_concurrency)
        self._auto_branch_prefix = auto_branch_prefix
        self._active = False
        self._picked_up_ids: set[str] = set()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def max_concurrency(self) -> int:
        return self._max_concurrency

    @max_concurrency.setter
    def max_concurrency(self, value: int) -> None:
        self._max_concurrency = max(1, value)

    def start(self) -> None:
        self._active = True

    def stop(self) -> None:
        self._active = False
        self._picked_up_ids.clear()

    def tick(self, session_state: SessionState) -> list[Task]:
        """Run one scheduling cycle.

        Returns a list of OPEN tasks that are ready to be dispatched
        (dependencies satisfied, concurrency slots available).  The caller
        is responsible for actually picking them up via ``WorktreeManager``.

        Guards against double-pickup via an internal ``_picked_up_ids`` set
        that tracks tasks between ``tick()`` returning them and the
        background thread completing the pickup.
        """
        if not self._active:
            return []

        # Count currently active task worktrees
        active_task_count = sum(1 for wt in session_state.worktrees if wt.task_id is not None)
        available_slots = self._max_concurrency - active_task_count
        if available_slots <= 0:
            return []

        # Get tasks ready to execute (OPEN + dependencies satisfied)
        all_tasks = self._backend.list_tasks()
        ready = get_ready_tasks(all_tasks)

        # Filter out tasks already picked up (in-flight between tick and worker completion)
        ready = [t for t in ready if t.id not in self._picked_up_ids]

        to_pick_up = ready[:available_slots]
        for task in to_pick_up:
            self._picked_up_ids.add(task.id)

        return to_pick_up

    def on_task_completed(self, task_id: str) -> None:
        """Called when a task transitions to DONE.

        Clears tracking so the next ``tick()`` can discover newly
        unblocked children.
        """
        self._picked_up_ids.discard(task_id)
