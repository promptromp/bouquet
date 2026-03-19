"""Tmux session and window management via libtmux."""

from __future__ import annotations

import contextlib
import os
import shutil
from pathlib import Path

import libtmux


class TmuxError(Exception):
    """Raised when a tmux operation fails."""


class TmuxManager:
    """Manages tmux sessions and windows for bouquet."""

    def __init__(self) -> None:
        self.server = libtmux.Server()

    def session_exists(self, session_name: str) -> bool:
        """Check if a tmux session with the given name exists."""
        return self.server.has_session(session_name)

    def create_session(
        self,
        session_name: str,
        start_directory: str | Path | None = None,
        window_name: str = "orchestrator",
    ) -> libtmux.Session:
        """Create a new tmux session."""
        if self.session_exists(session_name):
            raise TmuxError(f"Session '{session_name}' already exists")

        kwargs: dict = {
            "session_name": session_name,
            "window_name": window_name,
        }
        if start_directory:
            kwargs["start_directory"] = str(start_directory)

        session = self.server.new_session(**kwargs)

        # Clear Python venv env vars inherited from bouquet's own venv,
        # so worktree windows don't get confused by stale VIRTUAL_ENV.
        for var in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT"):
            with contextlib.suppress(Exception):
                session.remove_environment(var)

        return session

    def get_session(self, session_name: str) -> libtmux.Session:
        """Get an existing tmux session by name."""
        session = self.server.sessions.get(session_name=session_name)
        if session is None:
            raise TmuxError(f"Session '{session_name}' not found")
        return session

    def create_window(
        self,
        session_name: str,
        window_name: str,
        start_directory: str | Path | None = None,
    ) -> libtmux.Window:
        """Create a new window in the given session."""
        session = self.get_session(session_name)
        kwargs: dict = {"window_name": window_name}
        if start_directory:
            kwargs["start_directory"] = str(start_directory)
        window = session.new_window(**kwargs)
        return window

    def send_keys(
        self,
        session_name: str,
        window_name: str,
        keys: str,
        enter: bool = True,
    ) -> None:
        """Send keystrokes to a window's active pane."""
        session = self.get_session(session_name)
        window = session.windows.get(window_name=window_name)
        if window is None:
            raise TmuxError(f"Window '{window_name}' not found in session '{session_name}'")
        pane = window.active_pane
        if pane is None:
            raise TmuxError(f"No active pane in window '{window_name}'")
        pane.send_keys(keys, enter=enter)

    def switch_to_window(self, session_name: str, window_name: str) -> None:
        """Switch the session's active window."""
        session = self.get_session(session_name)
        window = session.windows.get(window_name=window_name)
        if window is None:
            raise TmuxError(f"Window '{window_name}' not found")
        window.select()

    def kill_window(self, session_name: str, window_name: str) -> None:
        """Kill a specific window."""
        session = self.get_session(session_name)
        window = session.windows.get(window_name=window_name)
        if window:
            window.kill()

    def kill_session(self, session_name: str) -> None:
        """Kill an entire tmux session."""
        try:
            session = self.get_session(session_name)
            session.kill()
        except TmuxError:
            pass  # Session already gone

    def is_inside_tmux(self) -> bool:
        """Check if we're currently running inside a tmux session."""
        return "TMUX" in os.environ

    def attach_session(self, session_name: str) -> None:
        """Attach to a tmux session (replaces current process)."""
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            raise TmuxError("tmux binary not found")
        os.execvp(tmux_bin, ["tmux", "attach-session", "-t", session_name])
