"""Tests for github.py — gh CLI wrapper."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from bouquet.github import GitHubError, gh_available, lookup_pr_url


def test_gh_available_when_present() -> None:
    with patch("bouquet.github.shutil.which", return_value="/usr/bin/gh"):
        assert gh_available() is True


def test_gh_available_when_missing() -> None:
    with patch("bouquet.github.shutil.which", return_value=None):
        assert gh_available() is False


def test_lookup_pr_url_returns_url() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="https://github.com/org/repo/pull/42\n",
            stderr="",
        )
        url = lookup_pr_url("feature/auth")
        assert url == "https://github.com/org/repo/pull/42"
        mock_run.assert_called_once_with(
            ["gh", "pr", "view", "feature/auth", "--json", "url", "--jq", ".url"],
            cwd=None,
            capture_output=True,
            text=True,
            check=True,
        )


def test_lookup_pr_url_returns_none_on_no_pr() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run", side_effect=subprocess.CalledProcessError(1, "gh")),
    ):
        assert lookup_pr_url("no-pr-branch") is None


def test_lookup_pr_url_raises_when_gh_missing() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=False),
        pytest.raises(GitHubError, match="gh CLI is not installed"),
    ):
        lookup_pr_url("feature/auth")


def test_lookup_pr_url_passes_cwd() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="url\n", stderr="")
        lookup_pr_url("branch", cwd=Path("/my/repo"))
        assert mock_run.call_args[1]["cwd"] == Path("/my/repo")


def test_lookup_pr_url_returns_none_on_empty_stdout() -> None:
    with (
        patch("bouquet.github.gh_available", return_value=True),
        patch("bouquet.github.subprocess.run") as mock_run,
    ):
        mock_run.return_value = subprocess.CompletedProcess(args=[], returncode=0, stdout="  \n", stderr="")
        assert lookup_pr_url("branch") is None
