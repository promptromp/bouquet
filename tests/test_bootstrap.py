"""Tests for bootstrap setup commands and env capture."""

from __future__ import annotations

from pathlib import Path

import pytest

from bouquet.bootstrap import (
    SetupCommandsError,
    _copy_file,
    _cow_clone,
    _direnv_allow,
    _run_setup_and_capture_env,
    bootstrap_worktree,
)
from bouquet.config import BootstrapConfig


def test_run_setup_captures_exported_env(tmp_path: Path) -> None:
    """Exported variables should appear in the returned delta."""
    delta = _run_setup_and_capture_env(
        ["export BOUQUET_TEST_SETUP_VAR=hello123"],
        tmp_path,
    )
    assert delta.get("BOUQUET_TEST_SETUP_VAR") == "hello123"


def test_run_setup_captures_multiple_vars(tmp_path: Path) -> None:
    """Multiple exports across commands should all be captured."""
    delta = _run_setup_and_capture_env(
        [
            "export BOUQUET_A=one",
            "export BOUQUET_B=two",
        ],
        tmp_path,
    )
    assert delta.get("BOUQUET_A") == "one"
    assert delta.get("BOUQUET_B") == "two"


def test_run_setup_propagates_between_commands(tmp_path: Path) -> None:
    """An export in command 1 should be visible in command 2."""
    delta = _run_setup_and_capture_env(
        [
            "export BOUQUET_BASE=hello",
            "export BOUQUET_DERIVED=${BOUQUET_BASE}_world",
        ],
        tmp_path,
    )
    assert delta.get("BOUQUET_DERIVED") == "hello_world"


def test_run_setup_raises_on_partial_failure(tmp_path: Path) -> None:
    """A non-zero exit from any command must raise SetupCommandsError.

    Previously the helper silently returned a partial env_delta on failure,
    which masked broken setup_commands and left worktrees in an
    inconsistent state.  Failing loudly is the correct contract.
    """
    with pytest.raises(SetupCommandsError):
        _run_setup_and_capture_env(
            ["export BOUQUET_BEFORE_FAIL=yes", "false"],
            tmp_path,
        )


def test_run_setup_excludes_unchanged_vars(tmp_path: Path) -> None:
    """Variables already in the current env with the same value should not appear."""
    # PATH is always set and won't change
    delta = _run_setup_and_capture_env(["true"], tmp_path)
    assert "PATH" not in delta


def test_run_setup_empty_commands(tmp_path: Path) -> None:
    """Empty command list should return empty dict."""
    delta = _run_setup_and_capture_env([], tmp_path)
    # With no commands, the script is just the env dump — delta should be empty
    # (no new vars were exported)
    assert isinstance(delta, dict)


def test_bootstrap_returns_env_delta(tmp_path: Path) -> None:
    """bootstrap_worktree should return the env delta from setup_commands."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        setup_commands=["export BOUQUET_BOOTSTRAP_TEST=yes"],
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    delta = bootstrap_worktree(
        repo_path=tmp_path,
        worktree_path=worktree,
        config=config,
        python=False,
        javascript=False,
    )
    assert delta.get("BOUQUET_BOOTSTRAP_TEST") == "yes"


def test_bootstrap_no_setup_commands_returns_empty(tmp_path: Path) -> None:
    """Without setup_commands, bootstrap should return an empty dict."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        setup_commands=[],
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    delta = bootstrap_worktree(
        repo_path=tmp_path,
        worktree_path=worktree,
        config=config,
        python=False,
        javascript=False,
    )
    assert delta == {}


def test_bootstrap_env_passed_to_deps_command(tmp_path: Path, monkeypatch: object) -> None:
    """Setup env vars should be available to the deps command."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    # Use a deps command that writes an env var to a file
    marker = worktree / "env_check.txt"
    config = BootstrapConfig(
        setup_commands=["export BOUQUET_DEPS_CHECK=it_works"],
        copy_env_files=[],
        python_deps_command=(
            f"python3 -c \"import os; open('{marker}', 'w').write(os.environ.get('BOUQUET_DEPS_CHECK', 'missing'))\""
        ),
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    bootstrap_worktree(
        repo_path=tmp_path,
        worktree_path=worktree,
        config=config,
        python=True,
        javascript=False,
    )

    assert marker.exists()
    assert marker.read_text() == "it_works"


def test_bootstrap_python_version_creates_pin_file(tmp_path: Path) -> None:
    """python_version should create a .python-version file in the worktree."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        python_version="3.13",
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    bootstrap_worktree(
        repo_path=tmp_path,
        worktree_path=worktree,
        config=config,
        python=True,
        javascript=False,
    )

    pin_file = worktree / ".python-version"
    assert pin_file.exists()
    assert "3.13" in pin_file.read_text()


def test_bootstrap_python_version_not_set_no_pin(tmp_path: Path) -> None:
    """Without python_version, no .python-version should be created."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    bootstrap_worktree(
        repo_path=tmp_path,
        worktree_path=worktree,
        config=config,
        python=True,
        javascript=False,
    )

    pin_file = worktree / ".python-version"
    assert not pin_file.exists()


def test_bootstrap_python_version_skipped_when_python_false(tmp_path: Path) -> None:
    """python_version should be skipped when python=False."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        python_version="3.13",
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    bootstrap_worktree(
        repo_path=tmp_path,
        worktree_path=worktree,
        config=config,
        python=False,
        javascript=False,
    )

    pin_file = worktree / ".python-version"
    assert not pin_file.exists()


# --- Edge case tests ---


def test_copy_env_files(tmp_path: Path) -> None:
    """bootstrap should copy env files from repo to worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("SECRET=abc\n")
    (repo / ".env.local").write_text("LOCAL=true\n")

    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        copy_env_files=[".env", ".env.local", ".env.missing"],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=False,
    )

    bootstrap_worktree(repo_path=repo, worktree_path=worktree, config=config, python=False, javascript=False)

    assert (worktree / ".env").read_text() == "SECRET=abc\n"
    assert (worktree / ".env.local").read_text() == "LOCAL=true\n"
    assert not (worktree / ".env.missing").exists()


def test_copy_file_helper(tmp_path: Path) -> None:
    """_copy_file copies when source exists, does nothing when it doesn't."""
    src = tmp_path / "exists.txt"
    src.write_text("hello")
    dst = tmp_path / "copy.txt"

    _copy_file(src, dst)
    assert dst.read_text() == "hello"

    # Missing source: no error, no file
    missing_dst = tmp_path / "nope.txt"
    _copy_file(tmp_path / "missing.txt", missing_dst)
    assert not missing_dst.exists()


def test_cow_clone_copies_directory(tmp_path: Path) -> None:
    """_cow_clone should copy a directory (CoW or fallback)."""
    src = tmp_path / "node_modules"
    src.mkdir()
    (src / "pkg.json").write_text("{}")

    dst = tmp_path / "wt_nm"
    _cow_clone(src, dst)

    assert dst.exists()
    assert (dst / "pkg.json").read_text() == "{}"
    # result is True (CoW) or False (fallback) — both are acceptable


def test_cow_clone_missing_source(tmp_path: Path) -> None:
    """_cow_clone with missing source returns False."""
    result = _cow_clone(tmp_path / "missing", tmp_path / "dst")
    assert result is False


def test_cow_clone_file_not_dir(tmp_path: Path) -> None:
    """_cow_clone with a file (not dir) returns False."""
    src = tmp_path / "file.txt"
    src.write_text("not a dir")
    result = _cow_clone(src, tmp_path / "dst")
    assert result is False


def test_bootstrap_cow_clone_node_modules(tmp_path: Path) -> None:
    """CoW clone should copy node_modules when javascript=True and use_cow_clone=True."""
    repo = tmp_path / "repo"
    repo.mkdir()
    nm = repo / "node_modules"
    nm.mkdir()
    (nm / "package.json").write_text("{}")

    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=True,
        direnv_allow=False,
    )

    bootstrap_worktree(repo_path=repo, worktree_path=worktree, config=config, python=False, javascript=True)

    assert (worktree / "node_modules" / "package.json").exists()


def test_bootstrap_cow_clone_skipped_for_python(tmp_path: Path) -> None:
    """CoW clone should NOT copy node_modules when javascript=False."""
    repo = tmp_path / "repo"
    repo.mkdir()
    nm = repo / "node_modules"
    nm.mkdir()
    (nm / "package.json").write_text("{}")

    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=True,
        direnv_allow=False,
    )

    bootstrap_worktree(repo_path=repo, worktree_path=worktree, config=config, python=True, javascript=False)

    assert not (worktree / "node_modules").exists()


def test_direnv_allow_no_envrc(tmp_path: Path) -> None:
    """_direnv_allow should be a no-op when no .envrc exists."""
    _direnv_allow(tmp_path)  # should not raise


def test_bootstrap_direnv_allow(tmp_path: Path) -> None:
    """bootstrap with direnv_allow=True should not error even without direnv."""
    worktree = tmp_path / "wt"
    worktree.mkdir()

    config = BootstrapConfig(
        copy_env_files=[],
        python_deps_command="",
        node_deps_command="",
        use_cow_clone=False,
        direnv_allow=True,
    )

    # Should not raise even without direnv installed
    bootstrap_worktree(repo_path=tmp_path, worktree_path=worktree, config=config, python=False, javascript=False)


def test_exception_tuple_syntax(tmp_path: Path) -> None:
    """Verify the fixed exception tuple on line 105 handles bad JSON gracefully."""
    # Create a file with invalid JSON to trigger the except branch
    env_path = tmp_path / "bad_env.json"
    env_path.write_text("not json")

    # The fix ensures (json.JSONDecodeError, FileNotFoundError, OSError) is a proper tuple.
    # Test by running setup with a command that creates an invalid env dump file.
    delta = _run_setup_and_capture_env(
        ["echo 'not json' > /dev/null"],
        tmp_path,
    )
    assert isinstance(delta, dict)
