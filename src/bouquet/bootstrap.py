"""Bootstrap a worktree: copy env files, install deps, configure direnv."""

from __future__ import annotations

import contextlib
import platform
import shutil
import subprocess
from pathlib import Path

from bouquet.config import BootstrapConfig


def _copy_file(src: Path, dst: Path) -> None:
    """Copy a file if the source exists."""
    if src.exists():
        shutil.copy2(src, dst)


def _cow_clone(src: Path, dst: Path) -> bool:
    """Attempt a copy-on-write clone of a directory.

    Returns True if CoW succeeded, False if it fell back to regular copy.
    """
    if not src.exists() or not src.is_dir():
        return False

    system = platform.system()
    try:
        if system == "Darwin":
            # macOS APFS: cp -c for CoW clone
            subprocess.run(
                ["cp", "-a", "-c", str(src), str(dst)],
                check=True,
                capture_output=True,
            )
            return True
        elif system == "Linux":
            # Linux (btrfs/xfs): cp --reflink=auto
            subprocess.run(
                ["cp", "-a", "--reflink=auto", str(src), str(dst)],
                check=True,
                capture_output=True,
            )
            return True
    except subprocess.CalledProcessError:
        pass

    # Fallback: regular copy
    if not dst.exists():
        shutil.copytree(src, dst)
    return False


def _direnv_allow(worktree_path: Path) -> None:
    """Run `direnv allow` in the worktree if an .envrc exists."""
    envrc = worktree_path / ".envrc"
    if not envrc.exists():
        return
    with contextlib.suppress(FileNotFoundError):
        subprocess.run(
            ["direnv", "allow"],
            cwd=worktree_path,
            capture_output=True,
            check=False,
        )


def bootstrap_worktree(
    repo_path: Path,
    worktree_path: Path,
    config: BootstrapConfig,
    python: bool = True,
    javascript: bool = False,
) -> None:
    """Bootstrap a newly created worktree.

    1. Copy environment files from the main repo
    2. CoW-clone node_modules if enabled (skip .venv — it contains
       hardcoded paths that break in a new location; let the deps
       command create a fresh venv instead)
    3. Run dependency install commands
    4. Allow direnv if configured
    """
    # 1. Copy env files (.env, .env.local, .envrc, etc.)
    for env_file in config.copy_env_files:
        src = repo_path / env_file
        _copy_file(src, worktree_path / env_file)

    # 2. CoW clone node_modules only (not .venv — venvs have hardcoded
    #    absolute paths in pyvenv.cfg and activation scripts that break
    #    when relocated; `uv sync` recreates them correctly and fast)
    if config.use_cow_clone and javascript:
        nm_src = repo_path / "node_modules"
        nm_dst = worktree_path / "node_modules"
        if nm_src.exists() and not nm_dst.exists():
            _cow_clone(nm_src, nm_dst)

    # 3. Run dependency install commands
    if python and config.python_deps_command:
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(
                config.python_deps_command.split(),
                cwd=worktree_path,
                capture_output=True,
                check=False,
            )

    if javascript and config.node_deps_command:
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(
                config.node_deps_command.split(),
                cwd=worktree_path,
                capture_output=True,
                check=False,
            )

    # 4. Allow direnv
    if config.direnv_allow:
        _direnv_allow(worktree_path)
