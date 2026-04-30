"""BOUQUET_* template vars must be visible inside setup_commands shell."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from bouquet import log as bouquet_log
from bouquet.bootstrap import SetupCommandsError, _run_setup_and_capture_env


def test_setup_commands_see_bouquet_template_vars(tmp_path: Path) -> None:
    """setup_commands shell must have BOUQUET_WORKTREE_INDEX and friends in env."""
    marker = tmp_path / "marker.txt"
    commands = [
        f'echo "$BOUQUET_WORKTREE_INDEX" > "{marker}"',
        f'echo "$BOUQUET_WORKTREE_BRANCH" >> "{marker}"',
        f'echo "$BOUQUET_PROJECT_NAME" >> "{marker}"',
    ]
    template_vars = {
        "BOUQUET_WORKTREE_INDEX": 7,
        "BOUQUET_WORKTREE_BRANCH": "feature/parallel",
        "BOUQUET_WORKTREE_PATH": str(tmp_path),
        "BOUQUET_PROJECT_NAME": "myproject",
    }

    _run_setup_and_capture_env(commands, cwd=tmp_path, template_vars=template_vars)

    contents = marker.read_text().splitlines()
    assert contents == ["7", "feature/parallel", "myproject"]


def test_setup_commands_render_template_placeholders(tmp_path: Path) -> None:
    """setup_commands strings must support {{ BOUQUET_WORKTREE_INDEX }} substitution."""
    marker = tmp_path / "rendered.txt"
    commands = [
        f'echo "{{{{ BOUQUET_WORKTREE_INDEX }}}}" > "{marker}"',
        f'echo "{{{{ 8000 + BOUQUET_WORKTREE_INDEX }}}}" >> "{marker}"',
    ]
    template_vars = {
        "BOUQUET_WORKTREE_INDEX": 3,
        "BOUQUET_WORKTREE_BRANCH": "x",
        "BOUQUET_WORKTREE_PATH": str(tmp_path),
        "BOUQUET_PROJECT_NAME": "x",
    }

    _run_setup_and_capture_env(commands, cwd=tmp_path, template_vars=template_vars)

    assert marker.read_text().splitlines() == ["3", "8003"]


def test_template_vars_do_not_appear_in_env_delta(tmp_path: Path) -> None:
    """BOUQUET_* template vars injected for the shell must not pollute the returned delta."""
    template_vars = {
        "BOUQUET_WORKTREE_INDEX": 5,
        "BOUQUET_WORKTREE_BRANCH": "feature/x",
        "BOUQUET_WORKTREE_PATH": str(tmp_path),
        "BOUQUET_PROJECT_NAME": "myproject",
    }
    # The shell does nothing user-visible -> delta should be empty.
    delta = _run_setup_and_capture_env(["true"], cwd=tmp_path, template_vars=template_vars)
    for key in template_vars:
        assert key not in delta, f"{key} leaked into env delta"


def test_setup_commands_failure_raises(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    """Non-zero exit from any command must raise SetupCommandsError."""
    commands = [
        "true",
        "echo 'about to fail' && false",
        # This third command must NOT run (the && chain short-circuits) — its
        # presence verifies we don't paper over the failure by always running
        # everything.
        "touch /tmp/bouquet-should-not-be-created-by-test",
    ]

    with pytest.raises(SetupCommandsError) as exc:
        _run_setup_and_capture_env(commands, cwd=tmp_path)

    assert "exit code 1" in str(exc.value)

    err = capfd.readouterr().err
    assert "setup_commands failed (exit 1)" in err
    assert "about to fail" in err  # captured stdout was surfaced
    assert "worktree bootstrap aborted" in err

    # Sanity: the third command was indeed skipped.
    assert not Path("/tmp/bouquet-should-not-be-created-by-test").exists()


def test_setup_commands_failure_surfaces_stderr(tmp_path: Path, capfd: pytest.CaptureFixture[str]) -> None:
    """Subprocess stderr must be surfaced on failure so users can debug."""
    with pytest.raises(SetupCommandsError):
        _run_setup_and_capture_env(
            ['echo "bad stuff happened" >&2; exit 7'],
            cwd=tmp_path,
        )

    err = capfd.readouterr().err
    assert "exit 7" in err
    assert "bad stuff happened" in err


def test_setup_commands_failure_writes_to_log_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When bouquet.log.configure has been called, failure stdout/stderr land in the file log."""
    # Redirect ~/.local/state/bouquet/ into tmp_path and reset.
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bouquet_logger = logging.getLogger("bouquet")
    for h in list(bouquet_logger.handlers):
        bouquet_logger.removeHandler(h)
        h.close()
    bouquet_log.LOG_FILE = None

    log_file = bouquet_log.configure("logsmoke", level="DEBUG")

    with pytest.raises(SetupCommandsError) as exc:
        _run_setup_and_capture_env(
            ['echo "stdout marker"; echo "stderr marker" >&2; exit 9'],
            cwd=tmp_path,
        )

    # The exception message must point users at the log file.
    assert str(log_file) in str(exc.value)
    assert "exit code 9" in str(exc.value)

    # Flush handlers and verify the captured output landed in the file.
    for h in bouquet_logger.handlers:
        h.flush()
    contents = log_file.read_text()
    assert "stdout marker" in contents
    assert "stderr marker" in contents
    assert "exit 9" in contents
    assert "ERROR" in contents

    # Cleanup: close handlers so the file isn't kept open across tests.
    for h in list(bouquet_logger.handlers):
        bouquet_logger.removeHandler(h)
        h.close()
    bouquet_log.LOG_FILE = None


def test_setup_commands_failure_message_unconfigured_logging(tmp_path: Path) -> None:
    """If bouquet.log.configure was never called, the exception message is the basic form."""
    # Ensure no handlers are attached (other tests may leave state behind).
    bouquet_logger = logging.getLogger("bouquet")
    for h in list(bouquet_logger.handlers):
        bouquet_logger.removeHandler(h)
        h.close()
    bouquet_log.LOG_FILE = None

    with pytest.raises(SetupCommandsError) as exc:
        _run_setup_and_capture_env(["exit 5"], cwd=tmp_path)

    msg = str(exc.value)
    assert msg == "setup_commands failed with exit code 5"
    assert "see " not in msg  # no log file pointer when unconfigured
