"""Bootstrap a worktree: copy env files, install deps, configure direnv."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bouquet import log as bouquet_log
from bouquet.config import BootstrapConfig
from bouquet.template import render_template


logger = logging.getLogger(__name__)


class SetupCommandsError(RuntimeError):
    """Raised when one of ``BootstrapConfig.setup_commands`` exits non-zero.

    The bash subprocess's captured stdout and stderr are written to bouquet's
    log file (``~/.local/state/bouquet/{project}.log`` once
    :func:`bouquet.log.configure` has been called) and to bouquet's own
    stderr.  When raised in TUI mode, stderr is captured by Textual — the
    log file is the durable record, and this exception's ``__str__``
    points the user at it.
    """


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


def _run_setup_and_capture_env(
    commands: list[str],
    cwd: Path,
    template_vars: dict[str, object] | None = None,
) -> dict[str, str]:
    """Run setup commands in a single bash shell and return the environment delta.

    Executes all *commands* sequentially in one ``bash -c`` invocation so that
    ``export`` statements in earlier commands are visible to later ones.  After
    all commands finish, the resulting environment is dumped to a temp file as
    JSON (via a ``python3`` one-liner) and diffed against the env the
    subprocess started with.  Returns only those variables that were **added**
    or **changed** by the commands.

    *template_vars* are rendered into ``{{ ... }}`` placeholders inside each
    command string AND exported into the bash subprocess's environment so
    plain ``$VAR`` references work too.  This lets setup_commands reference
    ``BOUQUET_WORKTREE_INDEX`` etc. either via templating or via shell vars.

    If any command exits non-zero, the captured stdout and stderr are dumped
    to bouquet's own stderr and :class:`SetupCommandsError` is raised so the
    caller can mark the worktree as ERROR rather than continuing with a
    partially-bootstrapped state.
    """
    template_vars = template_vars or {}
    rendered = [render_template(cmd, template_vars) for cmd in commands]

    fd, env_path = tempfile.mkstemp(prefix="bouquet-env-", suffix=".json")
    os.close(fd)

    try:
        env_dump = f"python3 -c \"import json,os; json.dump(dict(os.environ), open('{env_path}', 'w'))\""
        # Run user commands chained with && so the first failure short-circuits.
        # Capture their exit code BEFORE the env dump so we can both:
        #   (a) preserve whatever env vars they did export (best-effort)
        #   (b) propagate the user-commands' failure as the bash subprocess's exit code
        # so the Python caller can detect failure and raise.
        user_script = " && ".join(rendered)
        full_script = f"{user_script}\n_BOUQUET_USER_RC=$?\n{env_dump}\nexit $_BOUQUET_USER_RC\n"

        # Build env: parent env + BOUQUET_* template vars (stringified).
        subproc_env = {**os.environ, **{k: str(v) for k, v in template_vars.items()}}

        logger.info("running %d setup_command(s) in %s", len(rendered), cwd)
        for cmd in rendered:
            logger.debug("  setup_command: %s", cmd)

        result = subprocess.run(
            ["bash", "-c", full_script],
            cwd=cwd,
            capture_output=True,
            check=False,
            env=subproc_env,
        )

        if result.returncode != 0:
            stdout = result.stdout.decode(errors="replace") if result.stdout else ""
            stderr = result.stderr.decode(errors="replace") if result.stderr else ""

            # File log — durable, full diagnostic.  This is the source of
            # truth in TUI mode where stderr is captured by Textual.
            logger.error(
                "setup_commands failed (exit %d) in %s\n--- stdout ---\n%s\n--- stderr ---\n%s",
                result.returncode,
                cwd,
                stdout or "(empty)",
                stderr or "(empty)",
            )

            # Stderr framing — for direct (non-TUI) CLI invocation.
            sys.stderr.write(f"\n[bouquet] setup_commands failed (exit {result.returncode}) in {cwd}\n")
            if stdout:
                sys.stderr.write(f"--- setup_commands stdout ---\n{stdout}")
                if not stdout.endswith("\n"):
                    sys.stderr.write("\n")
            if stderr:
                sys.stderr.write(f"--- setup_commands stderr ---\n{stderr}")
                if not stderr.endswith("\n"):
                    sys.stderr.write("\n")
            sys.stderr.write("[bouquet] worktree bootstrap aborted\n\n")
            sys.stderr.flush()

            # Exception message includes the log file path so the TUI's
            # error toast (which only shows __str__) is actionable.
            log_file = bouquet_log.get_log_file()
            msg = f"setup_commands failed with exit code {result.returncode}"
            if log_file is not None:
                msg += f" — see {log_file} for details"
            raise SetupCommandsError(msg)

        logger.info("setup_commands completed successfully")

        try:
            with open(env_path) as f:
                result_env: dict[str, str] = json.load(f)
        except json.JSONDecodeError, FileNotFoundError, OSError:
            return {}

        # Diff against the env the subprocess actually started with.  This
        # naturally excludes the injected BOUQUET_* template vars (they
        # cancel out in the diff) — only changes the user's commands made
        # remain.
        return {k: v for k, v in result_env.items() if subproc_env.get(k) != v}
    finally:
        Path(env_path).unlink(missing_ok=True)


def bootstrap_worktree(
    repo_path: Path,
    worktree_path: Path,
    config: BootstrapConfig,
    python: bool = True,
    javascript: bool = False,
    template_vars: dict[str, object] | None = None,
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

    *template_vars* (e.g. ``BOUQUET_WORKTREE_INDEX``) are forwarded to
    :func:`_run_setup_and_capture_env` so setup_commands can reference them
    as shell env vars or ``{{ ... }}`` template placeholders.

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
        env_delta = _run_setup_and_capture_env(
            config.setup_commands,
            worktree_path,
            template_vars=template_vars,
        )

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
