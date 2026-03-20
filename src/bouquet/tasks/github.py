"""GitHub Issues-backed task queue."""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
from datetime import datetime

from bouquet.github import GitHubError, gh_available
from bouquet.tasks.base import Task, TaskQueueBackend, TaskStatus


_BRANCH_MARKER = re.compile(r"<!-- bouquet:branch:(.+?) -->")
_IN_PROGRESS_LABEL = "in-progress"
_GH_ISSUE_FIELDS = "number,title,body,state,labels,createdAt,updatedAt,url"


def _run_gh(*args: str) -> str:
    """Run a gh CLI command and return stdout."""
    result = subprocess.run(
        ["gh", *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class GitHubIssuesBackend(TaskQueueBackend):
    """Task queue backed by GitHub Issues."""

    def __init__(self, label_filter: str = "bouquet") -> None:
        if not gh_available():
            raise GitHubError("gh CLI is not installed — required for GitHub Issues backend")
        self._label_filter = label_filter

    def _issue_to_task(self, issue: dict) -> Task:
        """Convert a gh JSON issue object to a Task."""
        labels = [lbl["name"] for lbl in issue.get("labels", [])]
        state = issue.get("state", "OPEN")
        body = issue.get("body") or ""

        # Determine status
        if state == "CLOSED":
            status = TaskStatus.DONE
        elif _IN_PROGRESS_LABEL in labels:
            status = TaskStatus.IN_PROGRESS
        else:
            status = TaskStatus.OPEN

        # Extract branch from body marker
        branch: str | None = None
        m = _BRANCH_MARKER.search(body)
        if m:
            branch = m.group(1)

        return Task(
            id=str(issue["number"]),
            title=issue["title"],
            description=_strip_branch_marker(body),
            status=status,
            branch=branch,
            labels=[lbl for lbl in labels if lbl not in (self._label_filter, _IN_PROGRESS_LABEL)],
            source="github",
            url=issue.get("url"),
            created_at=datetime.fromisoformat(issue["createdAt"]),
            updated_at=datetime.fromisoformat(issue["updatedAt"]),
        )

    def list_tasks(self, status: TaskStatus | None = None) -> list[Task]:
        if status == TaskStatus.DONE:
            gh_state = "closed"
        elif status is not None:
            gh_state = "open"
        else:
            gh_state = "all"

        raw = _run_gh(
            "issue",
            "list",
            "--label",
            self._label_filter,
            "--state",
            gh_state,
            "--json",
            _GH_ISSUE_FIELDS,
            "--limit",
            "100",
        )
        issues = json.loads(raw) if raw else []
        tasks = [self._issue_to_task(issue) for issue in issues]

        # Client-side filter for IN_PROGRESS vs OPEN (both are "open" in GitHub)
        if status == TaskStatus.IN_PROGRESS:
            tasks = [t for t in tasks if t.status == TaskStatus.IN_PROGRESS]
        elif status == TaskStatus.OPEN:
            tasks = [t for t in tasks if t.status == TaskStatus.OPEN]

        tasks.sort(key=lambda t: int(t.id))
        return tasks

    def get_task(self, task_id: str) -> Task | None:
        try:
            raw = _run_gh("issue", "view", task_id, "--json", _GH_ISSUE_FIELDS)
        except subprocess.CalledProcessError:
            return None
        issue = json.loads(raw)
        # Only return if it has our label filter
        raw_labels = [lbl["name"] for lbl in issue.get("labels", [])]
        if self._label_filter not in raw_labels:
            return None
        return self._issue_to_task(issue)

    def create_task(self, title: str, description: str = "", labels: list[str] | None = None) -> Task:
        args = ["issue", "create", "--title", title, "--label", self._label_filter]
        if description:
            args.extend(["--body", description])
        if labels:
            for label in labels:
                args.extend(["--label", label])
        raw = _run_gh(*args, "--json", _GH_ISSUE_FIELDS)
        issue = json.loads(raw)
        return self._issue_to_task(issue)

    def update_status(self, task_id: str, status: TaskStatus, branch: str | None = None) -> Task:
        if status == TaskStatus.DONE:
            _run_gh("issue", "close", task_id)
            with contextlib.suppress(subprocess.CalledProcessError):
                _run_gh("issue", "edit", task_id, "--remove-label", _IN_PROGRESS_LABEL)
        elif status == TaskStatus.IN_PROGRESS:
            with contextlib.suppress(subprocess.CalledProcessError):
                _run_gh("issue", "reopen", task_id)
            _run_gh("issue", "edit", task_id, "--add-label", _IN_PROGRESS_LABEL)
        elif status == TaskStatus.OPEN:
            with contextlib.suppress(subprocess.CalledProcessError):
                _run_gh("issue", "reopen", task_id)
            with contextlib.suppress(subprocess.CalledProcessError):
                _run_gh("issue", "edit", task_id, "--remove-label", _IN_PROGRESS_LABEL)

        # Store branch in issue body as a hidden marker
        if branch is not None:
            task = self.get_task(task_id)
            if task is not None:
                body = task.description
                marker = f"<!-- bouquet:branch:{branch} -->"
                if _BRANCH_MARKER.search(body):
                    body = _BRANCH_MARKER.sub(marker, body)
                else:
                    body = f"{body}\n{marker}" if body else marker
                _run_gh("issue", "edit", task_id, "--body", body)

        task = self.get_task(task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found after update")
        return task

    def delete_task(self, task_id: str) -> None:
        with contextlib.suppress(subprocess.CalledProcessError):
            _run_gh("issue", "close", task_id, "--reason", "not planned")

    def reconcile_stale(self, active_branches: set[str]) -> list[Task]:
        in_progress = self.list_tasks(status=TaskStatus.IN_PROGRESS)
        reset: list[Task] = []
        for task in in_progress:
            if task.branch not in active_branches:
                self.update_status(task.id, TaskStatus.OPEN)
                reset.append(task)
        return reset


def _strip_branch_marker(body: str) -> str:
    """Remove the bouquet branch marker from issue body for display."""
    return _BRANCH_MARKER.sub("", body).strip()
