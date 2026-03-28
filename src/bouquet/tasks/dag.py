"""DAG utilities for task dependency management.

Pure functions operating on lists of Task objects — no backend dependency.
"""

from __future__ import annotations

from collections import deque

from bouquet.tasks.base import Task, TaskStatus


def detect_cycle(tasks: list[Task], child_id: str, proposed_parent_id: str) -> bool:
    """Check whether setting child_id's parent to proposed_parent_id would create a cycle.

    Walks up from proposed_parent_id following parent_id links.  If we reach
    child_id, there is a cycle.  Also catches self-cycles.
    """
    if child_id == proposed_parent_id:
        return True

    parent_map: dict[str, str | None] = {t.id: t.parent_id for t in tasks}
    current: str | None = proposed_parent_id
    while current is not None:
        if current == child_id:
            return True
        current = parent_map.get(current)
    return False


def topo_sort(tasks: list[Task]) -> list[Task]:
    """Return tasks in topological order (parents before children).

    Uses Kahn's algorithm.  Raises ``ValueError`` if cycles exist
    (defensive — cycles should be prevented at write time).
    """
    task_by_id: dict[str, Task] = {t.id: t for t in tasks}
    children: dict[str, list[str]] = {t.id: [] for t in tasks}
    in_degree: dict[str, int] = {t.id: 0 for t in tasks}

    for t in tasks:
        if t.parent_id is not None and t.parent_id in task_by_id:
            children[t.parent_id].append(t.id)
            in_degree[t.id] += 1

    queue: deque[str] = deque(tid for tid, deg in in_degree.items() if deg == 0)
    result: list[Task] = []

    while queue:
        tid = queue.popleft()
        result.append(task_by_id[tid])
        for child_id in children[tid]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                queue.append(child_id)

    if len(result) != len(tasks):
        raise ValueError("Cycle detected in task dependency graph")

    return result


def get_ready_tasks(tasks: list[Task]) -> list[Task]:
    """Return OPEN tasks whose dependencies are satisfied.

    A task is ready if it is OPEN and either has no parent or its parent
    is DONE.
    """
    status_by_id: dict[str, TaskStatus] = {t.id: t.status for t in tasks}
    return [
        t
        for t in tasks
        if t.status == TaskStatus.OPEN
        and (t.parent_id is None or status_by_id.get(t.parent_id) == TaskStatus.DONE)
    ]
