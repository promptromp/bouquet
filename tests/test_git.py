"""Tests for git worktree operations."""

from __future__ import annotations

from pathlib import Path

import pytest

from bouquet.git import (
    GitError,
    branch_exists,
    create_worktree,
    get_repo_root,
    is_git_repo,
    list_worktrees,
    remove_worktree,
)


def test_is_git_repo(tmp_git_repo: Path) -> None:
    assert is_git_repo(tmp_git_repo) is True


def test_is_not_git_repo(tmp_path: Path) -> None:
    assert is_git_repo(tmp_path) is False


def test_get_repo_root(tmp_git_repo: Path) -> None:
    root = get_repo_root(tmp_git_repo)
    assert root == tmp_git_repo


def test_branch_exists(tmp_git_repo: Path) -> None:
    assert branch_exists("main", tmp_git_repo) is True
    assert branch_exists("nonexistent", tmp_git_repo) is False


def test_create_and_list_worktree(tmp_git_repo: Path) -> None:
    wt_path = tmp_git_repo.parent / "worktree-test"
    create_worktree(tmp_git_repo, wt_path, "feature/test", "main")

    assert wt_path.exists()
    assert (wt_path / "README.md").exists()

    worktrees = list_worktrees(tmp_git_repo)
    branches = [wt.get("branch", "") for wt in worktrees]
    assert "feature/test" in branches


def test_remove_worktree(tmp_git_repo: Path) -> None:
    wt_path = tmp_git_repo.parent / "worktree-rm"
    create_worktree(tmp_git_repo, wt_path, "feature/rm-test", "main")
    assert wt_path.exists()

    remove_worktree(tmp_git_repo, wt_path)
    assert not wt_path.exists()


def test_create_worktree_existing_branch(tmp_git_repo: Path) -> None:
    # Create branch first via worktree, remove it, then re-use existing branch
    wt_path1 = tmp_git_repo.parent / "wt-existing1"
    create_worktree(tmp_git_repo, wt_path1, "feature/reuse", "main")
    remove_worktree(tmp_git_repo, wt_path1)

    # Branch still exists, create worktree using it
    wt_path2 = tmp_git_repo.parent / "wt-existing2"
    create_worktree(tmp_git_repo, wt_path2, "feature/reuse", "main")
    assert wt_path2.exists()


def test_create_worktree_conflict(tmp_git_repo: Path) -> None:
    wt_path = tmp_git_repo.parent / "wt-conflict"
    create_worktree(tmp_git_repo, wt_path, "feature/conflict", "main")

    # Creating at the same path should fail
    with pytest.raises(GitError):
        create_worktree(tmp_git_repo, wt_path, "feature/conflict2", "main")
