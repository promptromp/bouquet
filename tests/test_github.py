"""Tests for github.py — gh CLI wrapper."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from bouquet.github import GitHubError, PRStatus, gh_available, lookup_pr_info


def test_gh_available_when_present() -> None:
    with patch("bouquet.github.shutil.which", return_value="/usr/bin/gh"):
        assert gh_available() is True


def test_gh_available_when_missing() -> None:
    with patch("bouquet.github.shutil.which", return_value=None):
        assert gh_available() is False


# --- lookup_pr_info tests ---


def _gh_pr_json(
    *,
    number: int = 1,
    state: str = "OPEN",
    is_draft: bool = False,
    checks: list[dict] | None = None,
) -> str:
    """Build a gh pr view JSON response."""
    data = {
        "number": number,
        "url": f"https://github.com/org/repo/pull/{number}",
        "title": f"PR #{number}",
        "state": state,
        "isDraft": is_draft,
        "mergeable": "MERGEABLE",
        "statusCheckRollup": checks or [],
    }
    return json.dumps(data)


def test_lookup_pr_info_open_no_checks() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_gh_pr_json(number=10), stderr=""
        )
        info = lookup_pr_info("feature/x")
        assert info is not None
        assert info.number == 10
        assert info.status == PRStatus.READY


def test_lookup_pr_info_draft() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_gh_pr_json(is_draft=True), stderr=""
        )
        info = lookup_pr_info("feature/x")
        assert info is not None
        assert info.status == PRStatus.DRAFT


def test_lookup_pr_info_merged() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_gh_pr_json(state="MERGED"), stderr=""
        )
        info = lookup_pr_info("feature/x")
        assert info is not None
        assert info.status == PRStatus.MERGED


def test_lookup_pr_info_checks_passing() -> None:
    checks = [{"status": "COMPLETED", "conclusion": "SUCCESS"}]
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_gh_pr_json(checks=checks), stderr=""
        )
        info = lookup_pr_info("feature/x")
        assert info is not None
        assert info.status == PRStatus.READY


def test_lookup_pr_info_checks_failing() -> None:
    checks = [
        {"status": "COMPLETED", "conclusion": "SUCCESS"},
        {"status": "COMPLETED", "conclusion": "FAILURE"},
    ]
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_gh_pr_json(checks=checks), stderr=""
        )
        info = lookup_pr_info("feature/x")
        assert info is not None
        assert info.status == PRStatus.CHECKS_FAILING


def test_lookup_pr_info_checks_pending() -> None:
    checks = [
        {"status": "COMPLETED", "conclusion": "SUCCESS"},
        {"status": "IN_PROGRESS", "conclusion": ""},
    ]
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=_gh_pr_json(checks=checks), stderr=""
        )
        info = lookup_pr_info("feature/x")
        assert info is not None
        assert info.status == PRStatus.CHECKS_PENDING


def test_lookup_pr_info_no_pr() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")),
    ):
        assert lookup_pr_info("no-pr") is None


def test_lookup_pr_info_gh_missing() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=False),
        pytest.raises(GitHubError),
    ):
        lookup_pr_info("feature/x")
