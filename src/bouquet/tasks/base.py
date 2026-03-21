"""Task model and abstract backend for the task queue system."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class TaskBackendError(Exception):
    """Raised when a task backend operation fails."""


class TaskStatus(StrEnum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class Task(BaseModel):
    id: str
    title: str
    description: str = ""
    status: TaskStatus = TaskStatus.OPEN
    branch: str | None = None
    labels: list[str] = Field(default_factory=list)
    source: str = "local"
    url: str | None = None
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class TaskQueueBackend(ABC):
    """Abstract base class for task queue backends."""

    @abstractmethod
    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        """List tasks, optionally filtered by status."""

    @abstractmethod
    def get_task(self, task_id: str) -> Task | None:
        """Get a single task by ID."""

    @abstractmethod
    def create_task(self, title: str, description: str = "", labels: list[str] | None = None) -> Task:
        """Create a new task."""

    @abstractmethod
    def update_status(self, task_id: str, status: TaskStatus, branch: str | None = None) -> Task:
        """Update a task's status and optionally set its branch."""

    @abstractmethod
    def delete_task(self, task_id: str) -> None:
        """Delete a task."""

    def reconcile_stale(self, active_branches: set[str]) -> list[Task]:
        """Reset IN_PROGRESS tasks whose branches are not in active_branches back to OPEN.

        Returns the list of tasks that were reset.
        """
        in_progress = self.list_tasks(status=TaskStatus.IN_PROGRESS)
        reset: list[Task] = []
        for task in in_progress:
            if task.branch not in active_branches:
                self.update_status(task.id, TaskStatus.OPEN)
                reset.append(task)
        return reset
