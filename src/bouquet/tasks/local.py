"""SQLite-backed local task queue."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from bouquet.tasks.base import Task, TaskBackendError, TaskQueueBackend, TaskStatus


class LocalBackend(TaskQueueBackend):
    """Task queue backed by a local SQLite database."""

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (
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

    def _row_to_task(self, row: sqlite3.Row) -> Task:
        return Task(
            id=str(row["id"]),
            title=row["title"],
            description=row["description"],
            status=TaskStatus(row["status"]),
            branch=row["branch"],
            labels=json.loads(row["labels"]),
            source="local",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        if status is not None:
            rows = self._conn.execute("SELECT * FROM tasks WHERE status = ? ORDER BY id", (status.value,)).fetchall()
        else:
            rows = self._conn.execute("SELECT * FROM tasks ORDER BY id").fetchall()
        return [self._row_to_task(row) for row in rows]

    def get_task(self, task_id: str) -> Task | None:
        row = self._conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return self._row_to_task(row) if row else None

    def create_task(self, title: str, description: str = "", labels: list[str] | None = None) -> Task:
        now = datetime.now().isoformat()
        labels_json = json.dumps(labels or [])
        cursor = self._conn.execute(
            "INSERT INTO tasks (title, description, labels, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (title, description, labels_json, now, now),
        )
        self._conn.commit()
        task_id = str(cursor.lastrowid)
        task = self.get_task(task_id)
        if task is None:
            raise TaskBackendError(f"Failed to retrieve created task {task_id}")
        return task

    def update_status(self, task_id: str, status: TaskStatus, branch: str | None = None) -> Task:
        now = datetime.now().isoformat()
        if branch is not None:
            self._conn.execute(
                "UPDATE tasks SET status = ?, branch = ?, updated_at = ? WHERE id = ?",
                (status.value, branch, now, task_id),
            )
        else:
            self._conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
                (status.value, now, task_id),
            )
        self._conn.commit()
        task = self.get_task(task_id)
        if task is None:
            raise TaskBackendError(f"Task {task_id} not found")
        return task

    def delete_task(self, task_id: str) -> None:
        self._conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self._conn.commit()
