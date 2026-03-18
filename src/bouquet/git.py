"""Git worktree operations via subprocess."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


# Git env vars that can leak from parent processes (e.g. pre-commit hooks)
# and interfere with subprocess git commands targeting a different repo.
_GIT_ENV_VARS = (
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_WORK_TREE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


class GitError(Exception):
    """Raised when a git command fails."""


def _clean_env() -> dict[str, str]:
    """Return a copy of the environment with interfering GIT_* vars removed."""
    return {k: v for k, v in os.environ.items() if k not in _GIT_ENV_VARS}


def _run(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the result."""
    try:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            env=_clean_env(),
        )
    except subprocess.CalledProcessError as e:
        raise GitError(f"git {' '.join(args)} failed: {e.stderr.strip()}") from e


def is_git_repo(path: Path) -> bool:
    """Check if path is inside a git repository."""
    try:
        _run(["rev-parse", "--git-dir"], cwd=path)
        return True
    except GitError:
        return False


def get_repo_root(path: Path) -> Path:
    """Return the root directory of the git repository."""
    result = _run(["rev-parse", "--show-toplevel"], cwd=path)
    return Path(result.stdout.strip())


def branch_exists(branch: str, cwd: Path) -> bool:
    """Check if a branch already exists (local)."""
    try:
        _run(["rev-parse", "--verify", f"refs/heads/{branch}"], cwd=cwd)
        return True
    except GitError:
        return False


def create_worktree(
    repo_path: Path,
    worktree_path: Path,
    branch: str,
    base_branch: str = "main",
) -> Path:
    """Create a new git worktree with a new branch.

    If the branch already exists, checks it out in the worktree.
    Returns the path to the created worktree.
    """
    if branch_exists(branch, repo_path):
        _run(["worktree", "add", str(worktree_path), branch], cwd=repo_path)
    else:
        _run(
            ["worktree", "add", "-b", branch, str(worktree_path), base_branch],
            cwd=repo_path,
        )
    return worktree_path


def remove_worktree(repo_path: Path, worktree_path: Path) -> None:
    """Remove a git worktree."""
    _run(["worktree", "remove", str(worktree_path), "--force"], cwd=repo_path)


def list_worktrees(repo_path: Path) -> list[dict[str, str]]:
    """List all git worktrees, returning dicts with 'path', 'head', 'branch' keys."""
    result = _run(["worktree", "list", "--porcelain"], cwd=repo_path)
    worktrees: list[dict[str, str]] = []
    current: dict[str, str] = {}

    for line in result.stdout.splitlines():
        if not line.strip():
            if current:
                worktrees.append(current)
                current = {}
            continue
        if line.startswith("worktree "):
            current["path"] = line.split(" ", 1)[1]
        elif line.startswith("HEAD "):
            current["head"] = line.split(" ", 1)[1]
        elif line.startswith("branch "):
            # e.g. "branch refs/heads/main" → "main"
            ref = line.split(" ", 1)[1]
            current["branch"] = ref.removeprefix("refs/heads/")
        elif line == "bare":
            current["bare"] = "true"
        elif line == "detached":
            current["detached"] = "true"

    if current:
        worktrees.append(current)

    return worktrees
