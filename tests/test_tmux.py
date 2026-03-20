"""Tests for TmuxManager — unit tests with mocked libtmux."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from bouquet.tmux import TmuxError, TmuxManager


@pytest.fixture
def mock_server() -> MagicMock:
    """Return a mock libtmux.Server."""
    return MagicMock()


@pytest.fixture
def tmux(mock_server: MagicMock) -> TmuxManager:
    """Return a TmuxManager with a mocked server."""
    with patch("bouquet.tmux.libtmux.Server", return_value=mock_server):
        mgr = TmuxManager()
    return mgr


def _server(tmux: TmuxManager) -> Any:
    """Return the (mock) server with Any type to avoid mypy attr-defined errors."""
    return tmux.server


# --- session lifecycle ---


def test_session_exists_true(tmux: TmuxManager) -> None:
    _server(tmux).has_session.return_value = True
    assert tmux.session_exists("bouquet-test") is True
    _server(tmux).has_session.assert_called_once_with("bouquet-test")


def test_session_exists_false(tmux: TmuxManager) -> None:
    _server(tmux).has_session.return_value = False
    assert tmux.session_exists("bouquet-test") is False


def test_create_session(tmux: TmuxManager) -> None:
    _server(tmux).has_session.return_value = False
    mock_session = MagicMock()
    _server(tmux).new_session.return_value = mock_session

    result = tmux.create_session("bouquet-test", start_directory="/tmp", window_name="main")

    assert result is mock_session
    _server(tmux).new_session.assert_called_once_with(
        session_name="bouquet-test",
        window_name="main",
        start_directory="/tmp",
    )
    # Should clean up venv env vars
    mock_session.remove_environment.assert_any_call("VIRTUAL_ENV")
    mock_session.remove_environment.assert_any_call("VIRTUAL_ENV_PROMPT")


def test_create_session_already_exists(tmux: TmuxManager) -> None:
    _server(tmux).has_session.return_value = True
    with pytest.raises(TmuxError, match="already exists"):
        tmux.create_session("bouquet-test")


def test_get_session(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    _server(tmux).sessions.get.return_value = mock_session

    result = tmux.get_session("bouquet-test")
    assert result is mock_session
    _server(tmux).sessions.get.assert_called_once_with(session_name="bouquet-test")


def test_get_session_not_found(tmux: TmuxManager) -> None:
    _server(tmux).sessions.get.return_value = None
    with pytest.raises(TmuxError, match="not found"):
        tmux.get_session("missing")


def test_kill_session(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    _server(tmux).sessions.get.return_value = mock_session

    tmux.kill_session("bouquet-test")
    mock_session.kill.assert_called_once()


def test_kill_session_already_gone(tmux: TmuxManager) -> None:
    _server(tmux).sessions.get.return_value = None
    # Should not raise
    tmux.kill_session("missing")


# --- pane-ID-based operations ---


def test_send_keys_to_pane(tmux: TmuxManager) -> None:
    mock_pane = MagicMock()
    _server(tmux).panes.get.return_value = mock_pane

    tmux.send_keys_to_pane("%42", "echo hello", enter=True)

    _server(tmux).panes.get.assert_called_once_with(pane_id="%42")
    mock_pane.send_keys.assert_called_once_with("echo hello", enter=True)


def test_send_keys_to_pane_not_found(tmux: TmuxManager) -> None:
    _server(tmux).panes.get.return_value = None
    with pytest.raises(TmuxError, match="Pane '%99' not found"):
        tmux.send_keys_to_pane("%99", "test")


def test_capture_pane_by_id(tmux: TmuxManager) -> None:
    mock_pane = MagicMock()
    mock_pane.capture_pane.return_value = ["line1", "line2", "line3"]
    _server(tmux).panes.get.return_value = mock_pane

    result = tmux.capture_pane_by_id("%42")

    assert result == "line1\nline2\nline3"
    _server(tmux).panes.get.assert_called_once_with(pane_id="%42")


def test_capture_pane_by_id_not_found(tmux: TmuxManager) -> None:
    _server(tmux).panes.get.return_value = None
    result = tmux.capture_pane_by_id("%99")
    assert result == ""


# --- window-ID-based operations ---


def test_send_keys_to_window_id(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_pane = MagicMock()
    mock_window.active_pane = mock_pane
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    tmux.send_keys_to_window_id("bouquet-test", "@1", "echo test")

    mock_pane.send_keys.assert_called_once_with("echo test", enter=True)


def test_send_keys_to_window_id_not_found(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_session.windows.get.return_value = None
    _server(tmux).sessions.get.return_value = mock_session

    with pytest.raises(TmuxError, match="Window '@1' not found"):
        tmux.send_keys_to_window_id("bouquet-test", "@1", "test")


def test_send_keys_to_window_id_no_pane(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_window.active_pane = None
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    with pytest.raises(TmuxError, match="No active pane"):
        tmux.send_keys_to_window_id("bouquet-test", "@1", "test")


def test_kill_window_by_id(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    tmux.kill_window_by_id("bouquet-test", "@1")

    mock_window.kill.assert_called_once()


def test_kill_window_by_id_not_found(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_session.windows.get.return_value = None
    _server(tmux).sessions.get.return_value = mock_session

    # Should not raise when window doesn't exist
    tmux.kill_window_by_id("bouquet-test", "@99")


def test_switch_to_window_by_id(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    tmux.switch_to_window_by_id("bouquet-test", "@1")

    mock_window.select.assert_called_once()


def test_switch_to_window_by_id_not_found(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_session.windows.get.return_value = None
    _server(tmux).sessions.get.return_value = mock_session

    with pytest.raises(TmuxError, match="Window '@1' not found"):
        tmux.switch_to_window_by_id("bouquet-test", "@1")


# --- name-based operations ---


def test_send_keys_by_name(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_pane = MagicMock()
    mock_window.active_pane = mock_pane
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    tmux.send_keys("bouquet-test", "orchestrator", "hello")

    mock_pane.send_keys.assert_called_once_with("hello", enter=True)


def test_kill_window_by_name(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    tmux.kill_window("bouquet-test", "my-window")

    mock_window.kill.assert_called_once()


# --- capture_pane (window-based) ---


def test_capture_pane(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_pane = MagicMock()
    mock_pane.capture_pane.return_value = ["hello", "world"]
    mock_window.active_pane = mock_pane
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    result = tmux.capture_pane("bouquet-test", "@1")
    assert result == "hello\nworld"


def test_capture_pane_no_active_pane(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_window.active_pane = None
    mock_session.windows.get.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    result = tmux.capture_pane("bouquet-test", "@1")
    assert result == ""


# --- misc ---


def test_is_inside_tmux_true(tmux: TmuxManager, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TMUX", "/tmp/tmux-1000/default,12345,0")
    assert tmux.is_inside_tmux() is True


def test_is_inside_tmux_false(tmux: TmuxManager, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TMUX", raising=False)
    assert tmux.is_inside_tmux() is False


def test_set_session_environment(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    _server(tmux).sessions.get.return_value = mock_session

    tmux.set_session_environment("bouquet-test", "MY_VAR", "hello")

    mock_session.set_environment.assert_called_once_with("MY_VAR", "hello")


def test_create_window(tmux: TmuxManager) -> None:
    mock_session = MagicMock()
    mock_window = MagicMock()
    mock_session.new_window.return_value = mock_window
    _server(tmux).sessions.get.return_value = mock_session

    result = tmux.create_window("bouquet-test", "my-window", start_directory="/tmp")

    assert result is mock_window
    mock_session.new_window.assert_called_once_with(window_name="my-window", start_directory="/tmp")
