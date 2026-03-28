"""GitHub CLI (gh) wrapper for PR lookup."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class GitHubError(Exception):
    """Raised when gh is not available."""


class PRStatus(StrEnum):
    """High-level PR status derived from GitHub state + checks."""

    DRAFT = "draft"
    OPEN = "open"
    CHECKS_FAILING = "checks_failing"
    CHECKS_PENDING = "checks_pending"
    READY = "ready"
    MERGED = "merged"
    CLOSED = "closed"


@dataclass(frozen=True)
class PRInfo:
    """Rich PR information from GitHub."""

    number: int
    url: str
    title: str
    status: PRStatus


def gh_available() -> bool:
    """Check if the GitHub CLI (gh) is on PATH."""
    return shutil.which("gh") is not None


_PR_INFO_FIELDS = "number,url,title,state,isDraft,mergeable,statusCheckRollup"


def _derive_status(data: dict) -> PRStatus:
    """Derive a high-level PRStatus from raw gh JSON fields."""
    state = data.get("state", "")
    if state == "MERGED":
        return PRStatus.MERGED
    if state == "CLOSED":
        return PRStatus.CLOSED
    if data.get("isDraft"):
        return PRStatus.DRAFT

    # Check CI status from statusCheckRollup
    checks = data.get("statusCheckRollup") or []
    if checks:
        has_failure = any(c.get("conclusion") in ("FAILURE", "CANCELLED", "TIMED_OUT") for c in checks)
        has_pending = any(c.get("status") != "COMPLETED" for c in checks)
        if has_failure:
            return PRStatus.CHECKS_FAILING
        if has_pending:
            return PRStatus.CHECKS_PENDING

    # All checks passed (or no checks) and PR is open + not draft
    return PRStatus.READY


def lookup_pr_info(branch: str, cwd: Path | None = None) -> PRInfo | None:
    """Look up rich PR information for a branch using gh.

    Returns a PRInfo object, or None if no PR exists for the branch.
    Raises GitHubError if gh is not installed.
    """
    if not gh_available():
        raise GitHubError("gh CLI is not installed")
    try:
        result = subprocess.run(
            ["gh", "pr", "view", branch, "--json", _PR_INFO_FIELDS],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        data = json.loads(result.stdout)
    except subprocess.CalledProcessError, json.JSONDecodeError:
        return None

    return PRInfo(
        number=data["number"],
        url=data["url"],
        title=data.get("title", ""),
        status=_derive_status(data),
    )
