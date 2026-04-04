"""Task queue system — pluggable backends for managing work items."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bouquet.tasks.base import Task, TaskBackendError, TaskQueueBackend, TaskStatus
from bouquet.tasks.dag import detect_cycle, get_ready_tasks, topo_sort


if TYPE_CHECKING:
    from bouquet.config import TaskQueueConfig


def create_backend(config: TaskQueueConfig, project_name: str) -> TaskQueueBackend:
    """Create a task queue backend from configuration."""
    from bouquet.models import SessionState  # noqa: PLC0415
    from bouquet.tasks.local import LocalBackend  # noqa: PLC0415

    if config.backend == "github":
        from bouquet.tasks.github import GitHubIssuesBackend  # noqa: PLC0415

        return GitHubIssuesBackend(label_filter=config.label_filter)

    db_path = config.sqlite_path or str(SessionState.state_dir() / f"{project_name}.tasks.db")
    return LocalBackend(db_path=db_path)


__all__ = [
    "Task",
    "TaskBackendError",
    "TaskQueueBackend",
    "TaskStatus",
    "create_backend",
    "detect_cycle",
    "get_ready_tasks",
    "topo_sort",
]
