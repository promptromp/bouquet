"""Bootstrap a worktree: copy env files, clone virtualenvs, install deps."""

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


def bootstrap_worktree(
    repo_path: Path,
    worktree_path: Path,
    config: BootstrapConfig,
    python: bool = True,
    javascript: bool = False,
) -> None:
    """Bootstrap a newly created worktree.

    1. Copy environment files from the main repo
    2. CoW-clone virtualenv / node_modules if enabled
    3. Run dependency install commands
    """
    # 1. Copy env files
    for env_file in config.copy_env_files:
        src = repo_path / env_file
        _copy_file(src, worktree_path / env_file)

    # 2. CoW clone dependency directories
    if config.use_cow_clone:
        if python:
            venv_src = repo_path / ".venv"
            venv_dst = worktree_path / ".venv"
            if venv_src.exists() and not venv_dst.exists():
                _cow_clone(venv_src, venv_dst)

        if javascript:
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
