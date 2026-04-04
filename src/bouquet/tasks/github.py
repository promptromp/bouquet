"""GitHub Issues-backed task queue."""

from __future__ import annotations

import contextlib
import json
import re
import subprocess
from datetime import datetime

from bouquet.github import GitHubError, gh_available
from bouquet.tasks.base import Task, TaskBackendError, TaskQueueBackend, TaskStatus
from bouquet.tasks.dag import detect_cycle


_BRANCH_MARKER = re.compile(r"<!-- bouquet:branch:(.+?) -->")
_PARENT_MARKER = re.compile(r"<!-- bouquet:parent:(.+?) -->")
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

        # Extract parent from body marker
        parent_id: str | None = None
        pm = _PARENT_MARKER.search(body)
        if pm:
            parent_id = pm.group(1)

        return Task(
            id=str(issue["number"]),
            title=issue["title"],
            description=_strip_bouquet_markers(body),
            status=status,
            branch=branch,
            parent_id=parent_id,
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

    def create_task(
        self,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
        parent_id: str | None = None,
    ) -> Task:
        if parent_id is not None and self.get_task(parent_id) is None:
            raise TaskBackendError(f"Parent task {parent_id} does not exist")

        body = description
        if parent_id is not None:
            marker = f"<!-- bouquet:parent:{parent_id} -->"
            body = f"{body}\n{marker}" if body else marker

        args = ["issue", "create", "--title", title, "--label", self._label_filter]
        if body:
            args.extend(["--body", body])
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
            try:
                raw = _run_gh("issue", "view", task_id, "--json", "body")
                body = json.loads(raw).get("body") or ""
            except subprocess.CalledProcessError:
                body = ""
            marker = f"<!-- bouquet:branch:{branch} -->"
            if _BRANCH_MARKER.search(body):
                body = _BRANCH_MARKER.sub(marker, body)
            else:
                body = f"{body}\n{marker}" if body else marker
            _run_gh("issue", "edit", task_id, "--body", body)

        task = self.get_task(task_id)
        if task is None:
            raise TaskBackendError(f"Task {task_id} not found after update")
        return task

    def delete_task(self, task_id: str) -> None:
        # Orphan children: remove parent marker from child issues
        children = self.get_children(task_id)
        for child in children:
            child_task = self.get_task(child.id)
            if child_task is not None:
                # Re-read raw body from the issue (description has markers stripped)
                try:
                    raw = _run_gh("issue", "view", child.id, "--json", "body")
                    child_body = json.loads(raw).get("body") or ""
                except subprocess.CalledProcessError:
                    continue
                new_body = _PARENT_MARKER.sub("", child_body).strip()
                with contextlib.suppress(subprocess.CalledProcessError):
                    _run_gh("issue", "edit", child.id, "--body", new_body)
        with contextlib.suppress(subprocess.CalledProcessError):
            _run_gh("issue", "close", task_id, "--reason", "not planned")

    def set_parent(self, task_id: str, parent_id: str | None) -> Task:
        task = self.get_task(task_id)
        if task is None:
            raise TaskBackendError(f"Task {task_id} not found")
        if parent_id is not None and self.get_task(parent_id) is None:
            raise TaskBackendError(f"Parent task {parent_id} does not exist")
        if parent_id is not None:
            all_tasks = self.list_tasks()
            if detect_cycle(all_tasks, task_id, parent_id):
                raise TaskBackendError(f"Setting parent {parent_id} on task {task_id} would create a cycle")

        # Read raw body (with markers intact)
        try:
            raw = _run_gh("issue", "view", task_id, "--json", "body")
            body = json.loads(raw).get("body") or ""
        except subprocess.CalledProcessError:
            body = ""

        if parent_id is not None:
            marker = f"<!-- bouquet:parent:{parent_id} -->"
            if _PARENT_MARKER.search(body):
                body = _PARENT_MARKER.sub(marker, body)
            else:
                body = f"{body}\n{marker}" if body else marker
        else:
            body = _PARENT_MARKER.sub("", body).strip()

        _run_gh("issue", "edit", task_id, "--body", body)
        result = self.get_task(task_id)
        if result is None:
            raise TaskBackendError(f"Task {task_id} not found after update")
        return result


def _strip_bouquet_markers(body: str) -> str:
    """Remove bouquet markers (branch, parent) from issue body for display."""
    body = _BRANCH_MARKER.sub("", body)
    body = _PARENT_MARKER.sub("", body)
    return body.strip()
