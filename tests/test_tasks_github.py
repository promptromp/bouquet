"""Tests for the GitHubIssuesBackend task queue."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from bouquet.github import GitHubError
from bouquet.tasks.base import TaskStatus
from bouquet.tasks.github import GitHubIssuesBackend, _strip_branch_marker


def _make_issue(
    number: int = 1,
    title: str = "Test issue",
    body: str = "",
    state: str = "OPEN",
    labels: list[str] | None = None,
    url: str = "https://github.com/org/repo/issues/1",
) -> dict:
    """Build a gh-style issue JSON dict."""
    return {
        "number": number,
        "title": title,
        "body": body,
        "state": state,
        "labels": [{"name": lbl} for lbl in (labels or ["bouquet"])],
        "createdAt": "2026-03-20T10:00:00Z",
        "updatedAt": "2026-03-20T10:00:00Z",
        "url": url,
    }


@patch("bouquet.tasks.github.gh_available", return_value=True)
def test_init_succeeds_with_gh(mock_gh: MagicMock) -> None:
    backend = GitHubIssuesBackend(label_filter="bouquet")
    assert backend._label_filter == "bouquet"


@patch("bouquet.tasks.github.gh_available", return_value=False)
def test_init_raises_without_gh(mock_gh: MagicMock) -> None:
    with pytest.raises(GitHubError, match="gh CLI is not installed"):
        GitHubIssuesBackend()


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_list_tasks(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issues = [_make_issue(1, "First"), _make_issue(2, "Second")]
    mock_run.return_value = json.dumps(issues)
    backend = GitHubIssuesBackend()

    tasks = backend.list_tasks()
    assert len(tasks) == 2
    assert tasks[0].title == "First"
    assert tasks[1].title == "Second"
    assert tasks[0].source == "github"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_list_tasks_filter_open(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issues = [
        _make_issue(1, "Open", labels=["bouquet"]),
        _make_issue(2, "In progress", labels=["bouquet", "in-progress"]),
    ]
    mock_run.return_value = json.dumps(issues)
    backend = GitHubIssuesBackend()

    tasks = backend.list_tasks(status=TaskStatus.OPEN)
    assert len(tasks) == 1
    assert tasks[0].title == "Open"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_list_tasks_filter_in_progress(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issues = [
        _make_issue(1, "Open", labels=["bouquet"]),
        _make_issue(2, "In progress", labels=["bouquet", "in-progress"]),
    ]
    mock_run.return_value = json.dumps(issues)
    backend = GitHubIssuesBackend()

    tasks = backend.list_tasks(status=TaskStatus.IN_PROGRESS)
    assert len(tasks) == 1
    assert tasks[0].title == "In progress"
    assert tasks[0].status == TaskStatus.IN_PROGRESS


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_list_tasks_filter_done(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issues = [_make_issue(1, "Done issue", state="CLOSED")]
    mock_run.return_value = json.dumps(issues)
    backend = GitHubIssuesBackend()

    tasks = backend.list_tasks(status=TaskStatus.DONE)
    assert len(tasks) == 1
    assert tasks[0].status == TaskStatus.DONE
    mock_run.assert_called_once()
    # Should have passed --state closed
    call_args = mock_run.call_args[0]
    assert "closed" in call_args


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_get_task(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.return_value = json.dumps(_make_issue(42, "My task"))
    backend = GitHubIssuesBackend()

    task = backend.get_task("42")
    assert task is not None
    assert task.id == "42"
    assert task.title == "My task"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_get_task_not_found(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.side_effect = subprocess.CalledProcessError(1, "gh")
    backend = GitHubIssuesBackend()

    assert backend.get_task("999") is None


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_get_task_wrong_label(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.return_value = json.dumps(_make_issue(1, "Wrong", labels=["other"]))
    backend = GitHubIssuesBackend()

    assert backend.get_task("1") is None


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_create_task(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.return_value = json.dumps(_make_issue(5, "New task"))
    backend = GitHubIssuesBackend()

    task = backend.create_task("New task", description="Some details")
    assert task.id == "5"
    assert task.title == "New task"
    call_args = mock_run.call_args[0]
    assert "--title" in call_args
    assert "--body" in call_args


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_create_task_with_labels(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.return_value = json.dumps(_make_issue(6, "Labeled", labels=["bouquet", "bug"]))
    backend = GitHubIssuesBackend()

    task = backend.create_task("Labeled", labels=["bug"])
    assert "bug" in task.labels
    # bouquet label is filtered out of task.labels
    assert "bouquet" not in task.labels


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_update_status_to_done(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    # First call: close, second: remove label, third: get_task (view)
    mock_run.side_effect = [
        "",  # close
        "",  # remove label
        json.dumps(_make_issue(1, "Done", state="CLOSED")),  # get_task
    ]
    backend = GitHubIssuesBackend()

    task = backend.update_status("1", TaskStatus.DONE)
    assert task.status == TaskStatus.DONE
    assert mock_run.call_args_list[0][0] == ("issue", "close", "1")


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_update_status_to_in_progress(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.side_effect = [
        "",  # reopen
        "",  # add label
        json.dumps(_make_issue(1, "Working", labels=["bouquet", "in-progress"])),  # get_task
    ]
    backend = GitHubIssuesBackend()

    task = backend.update_status("1", TaskStatus.IN_PROGRESS)
    assert task.status == TaskStatus.IN_PROGRESS


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_update_status_with_branch(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issue_no_branch = _make_issue(1, "Task", body="Original description")
    issue_with_branch = _make_issue(1, "Task", body="Original description\n<!-- bouquet:branch:task/1-fix -->")
    mock_run.side_effect = [
        "",  # close
        "",  # remove label
        json.dumps(issue_no_branch),  # get_task for branch update
        "",  # edit body
        json.dumps(issue_with_branch),  # final get_task
    ]
    backend = GitHubIssuesBackend()

    task = backend.update_status("1", TaskStatus.DONE, branch="task/1-fix")
    assert task.branch == "task/1-fix"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_issue_to_task_extracts_branch(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issue = _make_issue(1, "Branched", body="Description\n<!-- bouquet:branch:task/1-branched -->")
    backend = GitHubIssuesBackend()

    task = backend._issue_to_task(issue)
    assert task.branch == "task/1-branched"
    assert "bouquet:branch" not in task.description


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_issue_to_task_url(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issue = _make_issue(1, "With URL", url="https://github.com/org/repo/issues/1")
    backend = GitHubIssuesBackend()

    task = backend._issue_to_task(issue)
    assert task.url == "https://github.com/org/repo/issues/1"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_reconcile_stale(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    issues = [
        _make_issue(1, "Active", labels=["bouquet", "in-progress"], body="<!-- bouquet:branch:task/1-active -->"),
        _make_issue(2, "Stale", labels=["bouquet", "in-progress"], body="<!-- bouquet:branch:task/2-stale -->"),
    ]
    # Call 1: list_tasks(IN_PROGRESS)
    # Call 2-5: update_status for stale task (reopen, remove label, get_task)
    stale_after_reset = _make_issue(2, "Stale", labels=["bouquet"], body="<!-- bouquet:branch:task/2-stale -->")
    mock_run.side_effect = [
        json.dumps(issues),  # list_tasks
        "",  # reopen
        "",  # remove label
        json.dumps(stale_after_reset),  # get_task after update
    ]
    backend = GitHubIssuesBackend()

    reset = backend.reconcile_stale({"task/1-active"})
    assert len(reset) == 1
    assert reset[0].id == "2"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_delete_task_closes_issue(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.return_value = ""
    backend = GitHubIssuesBackend()

    backend.delete_task("10")
    mock_run.assert_called_once_with("issue", "close", "10", "--reason", "not planned")


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_list_tasks_empty(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    mock_run.return_value = "[]"
    backend = GitHubIssuesBackend()

    assert backend.list_tasks() == []


def test_strip_branch_marker() -> None:
    assert _strip_branch_marker("Hello\n<!-- bouquet:branch:task/1 -->") == "Hello"
    assert _strip_branch_marker("<!-- bouquet:branch:x -->") == ""
    assert _strip_branch_marker("No marker here") == "No marker here"


@patch("bouquet.tasks.github.gh_available", return_value=True)
@patch("bouquet.tasks.github._run_gh")
def test_labels_exclude_internal(mock_run: MagicMock, mock_gh: MagicMock) -> None:
    """bouquet and in-progress labels should be filtered from task.labels."""
    issue = _make_issue(1, "Task", labels=["bouquet", "in-progress", "bug", "p1"])
    backend = GitHubIssuesBackend()

    task = backend._issue_to_task(issue)
    assert "bouquet" not in task.labels
    assert "in-progress" not in task.labels
    assert task.labels == ["bug", "p1"]
