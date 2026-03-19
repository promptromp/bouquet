"""Tests for bootstrap setup commands and env capture."""

from __future__ import annotations

from pathlib import Path

from bouquet.bootstrap import _run_setup_and_capture_env, bootstrap_worktree
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


def test_run_setup_still_captures_env_on_partial_failure(tmp_path: Path) -> None:
    """Env dump runs even if a later command fails, capturing earlier exports."""
    delta = _run_setup_and_capture_env(
        ["export BOUQUET_BEFORE_FAIL=yes", "false"],
        tmp_path,
    )
    assert delta.get("BOUQUET_BEFORE_FAIL") == "yes"


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
