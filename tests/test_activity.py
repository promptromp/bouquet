"""Tests for ActivityMonitor."""

from __future__ import annotations

from unittest.mock import MagicMock

from bouquet.activity import ActivityMonitor
from bouquet.models import WorktreeStatus


def _make_monitor(*, stability_threshold: int = 3) -> tuple[ActivityMonitor, MagicMock]:
    """Return an ActivityMonitor with a mocked TmuxManager."""
    tmux = MagicMock()
    monitor = ActivityMonitor(tmux, stability_threshold=stability_threshold)
    return monitor, tmux


def test_first_poll_returns_running() -> None:
    monitor, tmux = _make_monitor()
    tmux.capture_pane.return_value = "hello world"
    assert monitor.check("sess", "@1") == WorktreeStatus.RUNNING


def test_hash_change_returns_running() -> None:
    monitor, tmux = _make_monitor()
    tmux.capture_pane.side_effect = ["output-1", "output-2"]
    monitor.check("sess", "@1")  # first poll
    assert monitor.check("sess", "@1") == WorktreeStatus.RUNNING


def test_stable_output_returns_idle() -> None:
    monitor, tmux = _make_monitor(stability_threshold=2)
    tmux.capture_pane.return_value = "stable content"
    monitor.check("sess", "@1")  # first poll → RUNNING
    monitor.check("sess", "@1")  # stable 1
    monitor.check("sess", "@1")  # stable 2 → threshold reached
    assert monitor.check("sess", "@1") == WorktreeStatus.IDLE


def test_permission_prompt_returns_waiting() -> None:
    monitor, tmux = _make_monitor(stability_threshold=2)
    content = "some output\nDo you want to proceed? [Y/n]"
    tmux.capture_pane.return_value = content
    monitor.check("sess", "@1")  # first poll
    monitor.check("sess", "@1")  # stable 1
    assert monitor.check("sess", "@1") == WorktreeStatus.WAITING


def test_capture_error_returns_error() -> None:
    monitor, tmux = _make_monitor()
    tmux.capture_pane.side_effect = Exception("tmux gone")
    assert monitor.check("sess", "@1") == WorktreeStatus.ERROR


def test_hash_change_resets_stability() -> None:
    monitor, tmux = _make_monitor(stability_threshold=2)
    # Build up stability
    tmux.capture_pane.return_value = "content-a"
    monitor.check("sess", "@1")  # first
    monitor.check("sess", "@1")  # stable 1
    # Now change
    tmux.capture_pane.return_value = "content-b"
    assert monitor.check("sess", "@1") == WorktreeStatus.RUNNING
    # One more stable poll should not yet be idle (threshold=2)
    assert monitor.check("sess", "@1") == WorktreeStatus.RUNNING


def test_remove_cleans_state() -> None:
    monitor, tmux = _make_monitor()
    tmux.capture_pane.return_value = "content"
    monitor.check("sess", "@1")
    monitor.remove("@1")
    # After remove, next check acts like first poll
    assert monitor.check("sess", "@1") == WorktreeStatus.RUNNING


def test_multiple_windows_tracked_independently() -> None:
    monitor, tmux = _make_monitor(stability_threshold=1)
    tmux.capture_pane.return_value = "content"
    monitor.check("sess", "@1")  # first poll for @1
    monitor.check("sess", "@2")  # first poll for @2
    # @1 is now stable (threshold=1), @2 just started
    assert monitor.check("sess", "@1") == WorktreeStatus.IDLE
    assert monitor.check("sess", "@2") == WorktreeStatus.IDLE


def test_has_permission_prompt_patterns() -> None:
    assert ActivityMonitor._has_permission_prompt("Allow? [Y/n]")
    assert ActivityMonitor._has_permission_prompt("line1\nline2\nApprove?")
    assert ActivityMonitor._has_permission_prompt("(y/n)")
    assert not ActivityMonitor._has_permission_prompt("normal output")
