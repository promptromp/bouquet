"""GitHub CLI (gh) wrapper for PR lookup."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class GitHubError(Exception):
    """Raised when gh is not available."""


def gh_available() -> bool:
    """Check if the GitHub CLI (gh) is on PATH."""
    return shutil.which("gh") is not None


def lookup_pr_url(branch: str, cwd: Path | None = None) -> str | None:
    """Look up the PR URL for a branch using gh.

    Returns the PR URL string, or None if no PR exists for the branch.
    Raises GitHubError if gh is not installed.
    """
    if not gh_available():
        raise GitHubError("gh CLI is not installed")
    try:
        result = subprocess.run(
            ["gh", "pr", "view", branch, "--json", "url", "--jq", ".url"],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
        )
        url = result.stdout.strip()
        return url if url else None
    except subprocess.CalledProcessError:
        return None
