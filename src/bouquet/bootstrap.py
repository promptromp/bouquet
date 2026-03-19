"""Bootstrap a worktree: copy env files, install deps, configure direnv."""

from __future__ import annotations

import contextlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
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


def _run_setup_and_capture_env(commands: list[str], cwd: Path) -> dict[str, str]:
    """Run setup commands in a single bash shell and return the environment delta.

    Executes all *commands* sequentially in one ``bash -c`` invocation so that
    ``export`` statements in earlier commands are visible to later ones.  After
    all commands finish, the resulting environment is dumped to a temp file as
    JSON (via a ``python3`` one-liner) and diffed against the current process
    environment.

    Returns only those variables that were **added** or **changed** by the
    commands.
    """
    fd, env_path = tempfile.mkstemp(prefix="bouquet-env-", suffix=".json")
    os.close(fd)

    try:
        # Use python3 to dump the resulting env as JSON — portable across
        # macOS and Linux (macOS `env` doesn't support `-0`).
        env_dump = f"python3 -c \"import json,os; json.dump(dict(os.environ), open('{env_path}', 'w'))\""
        # Chain user commands with && (each depends on prior success), but
        # always run the env dump via ; so we capture whatever was exported
        # even if a later command (e.g. `aws codeartifact login`) fails.
        script = " && ".join(commands) + "; " + env_dump
        subprocess.run(
            ["bash", "-c", script],
            cwd=cwd,
            capture_output=True,
            check=False,
        )

        try:
            with open(env_path) as f:
                result_env: dict[str, str] = json.load(f)
        except json.JSONDecodeError, FileNotFoundError, OSError:
            return {}

        current = dict(os.environ)
        return {k: v for k, v in result_env.items() if current.get(k) != v}
    finally:
        Path(env_path).unlink(missing_ok=True)


def bootstrap_worktree(
    repo_path: Path,
    worktree_path: Path,
    config: BootstrapConfig,
    python: bool = True,
    javascript: bool = False,
) -> dict[str, str]:
    """Bootstrap a newly created worktree.

    1. Copy environment files from the main repo
    2. CoW-clone node_modules if enabled (skip .venv — it contains
       hardcoded paths that break in a new location; let the deps
       command create a fresh venv instead)
    3. Run setup commands and capture env delta
    4. Pin Python version if configured
    5. Run dependency install commands (with setup env applied)
    6. Allow direnv if configured

    Returns a dict of environment variables that were added or changed by
    the setup commands (empty dict if none).
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

    # 3. Run setup commands and capture env delta
    env_delta: dict[str, str] = {}
    if config.setup_commands:
        env_delta = _run_setup_and_capture_env(config.setup_commands, worktree_path)

    # Build env for deps commands: current env + setup delta
    deps_env = {**os.environ, **env_delta} if env_delta else None

    # 4. Pin Python version if configured (before deps so uv uses it)
    if python and config.python_version:
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(
                ["uv", "python", "pin", config.python_version],
                cwd=worktree_path,
                env=deps_env,
                capture_output=True,
                check=False,
            )

    # 5. Run dependency install commands (shell=True to support compound
    #    commands like "cd subdir && pnpm install")
    if python and config.python_deps_command:
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(
                config.python_deps_command,
                cwd=worktree_path,
                env=deps_env,
                capture_output=True,
                check=False,
                shell=True,
            )

    if javascript and config.node_deps_command:
        with contextlib.suppress(FileNotFoundError):
            subprocess.run(
                config.node_deps_command,
                cwd=worktree_path,
                env=deps_env,
                capture_output=True,
                check=False,
                shell=True,
            )

    # 6. Allow direnv
    if config.direnv_allow:
        _direnv_allow(worktree_path)

    return env_delta
