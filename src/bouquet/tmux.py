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

    def _get_window_by_id(self, session_name: str, window_id: str) -> libtmux.Window:
        """Look up a window by its unique tmux ID (e.g. ``@1``)."""
        session = self.get_session(session_name)
        window = session.windows.get(window_id=window_id)
        if window is None:
            raise TmuxError(f"Window '{window_id}' not found in session '{session_name}'")
        return window

    # --- name-based operations (legacy) ---

    def send_keys(
        self,
        session_name: str,
        window_name: str,
        keys: str,
        enter: bool = True,
    ) -> None:
        """Send keystrokes to a window's active pane (by window name)."""
        session = self.get_session(session_name)
        window = session.windows.get(window_name=window_name)
        if window is None:
            raise TmuxError(f"Window '{window_name}' not found in session '{session_name}'")
        pane = window.active_pane
        if pane is None:
            raise TmuxError(f"No active pane in window '{window_name}'")
        pane.send_keys(keys, enter=enter)

    def switch_to_window(self, session_name: str, window_name: str) -> None:
        """Switch the session's active window (by window name)."""
        session = self.get_session(session_name)
        window = session.windows.get(window_name=window_name)
        if window is None:
            raise TmuxError(f"Window '{window_name}' not found")
        window.select()

    def kill_window(self, session_name: str, window_name: str) -> None:
        """Kill a specific window (by window name)."""
        session = self.get_session(session_name)
        window = session.windows.get(window_name=window_name)
        if window:
            window.kill()

    # --- ID-based operations (preferred — avoids window name collisions) ---

    def send_keys_to_window_id(
        self,
        session_name: str,
        window_id: str,
        keys: str,
        enter: bool = True,
    ) -> None:
        """Send keystrokes to a window's active pane (by window ID)."""
        window = self._get_window_by_id(session_name, window_id)
        pane = window.active_pane
        if pane is None:
            raise TmuxError(f"No active pane in window '{window_id}'")
        pane.send_keys(keys, enter=enter)

    def switch_to_window_by_id(self, session_name: str, window_id: str) -> None:
        """Switch the session's active window (by window ID)."""
        window = self._get_window_by_id(session_name, window_id)
        window.select()

    def kill_window_by_id(self, session_name: str, window_id: str) -> None:
        """Kill a specific window (by window ID)."""
        session = self.get_session(session_name)
        window = session.windows.get(window_id=window_id)
        if window:
            window.kill()

    def set_session_environment(self, session_name: str, key: str, value: str) -> None:
        """Set an environment variable on the tmux session.

        Session-level env vars are inherited by all new panes/windows.
        """
        session = self.get_session(session_name)
        session.set_environment(key, value)

    def capture_pane(self, session_name: str, window_id: str) -> str:
        """Capture the content of the active pane in the given window (by window ID)."""
        window = self._get_window_by_id(session_name, window_id)
        pane = window.active_pane
        if pane is None:
            return ""
        lines = pane.capture_pane()
        return "\n".join(lines)

    # --- Pane-ID-based operations (preferred for targeting agent pane) ---

    def send_keys_to_pane(self, pane_id: str, keys: str, enter: bool = True) -> None:
        """Send keystrokes directly to a pane by its unique pane ID (e.g. ``%42``)."""
        pane = self.server.panes.get(pane_id=pane_id)
        if pane is None:
            raise TmuxError(f"Pane '{pane_id}' not found")
        pane.send_keys(keys, enter=enter)

    def capture_pane_by_id(self, pane_id: str) -> str:
        """Capture content from a specific pane by its unique pane ID."""
        pane = self.server.panes.get(pane_id=pane_id)
        if pane is None:
            return ""
        lines = pane.capture_pane()
        return "\n".join(lines)

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

    def setup_service_panes(
        self,
        window: libtmux.Window,
        service_commands: list[str],
        start_directory: str | Path,
        layout: str | None = None,
    ) -> list[libtmux.Pane]:
        """Split *window* into panes for each service and apply a layout.

        Pane 0 (the original pane) is left for the agent.  Each service
        gets a new pane created by splitting.  After all panes are created
        the specified tmux layout is applied.

        The special layout ``"services-top"`` arranges service panes in a
        horizontal row across the top of the window with the agent pane
        spanning the full width at the bottom (~60% height).  Any other
        value is passed to ``select_layout`` as a standard tmux layout.

        Returns the list of newly created service panes (not including pane 0).
        """
        panes: list[libtmux.Pane] = []
        first_pane = window.active_pane
        if first_pane is None:
            raise TmuxError("Window has no active pane")

        if layout == "services-top":
            panes = self._setup_services_top(first_pane, service_commands, start_directory)
        else:
            for cmd in service_commands:
                new_pane = first_pane.split(
                    direction=libtmux.constants.PaneDirection.Below,
                    start_directory=str(start_directory),
                )
                new_pane.send_keys(cmd, enter=True)
                panes.append(new_pane)

            if layout:
                window.select_layout(layout)

        return panes

    @staticmethod
    def _setup_services_top(
        agent_pane: libtmux.Pane,
        service_commands: list[str],
        start_directory: str | Path,
    ) -> list[libtmux.Pane]:
        """Create service panes in a row above the agent pane.

        Splits the agent pane horizontally, putting the first service above
        it (~40% top / 60% bottom).  Then splits the service area vertically
        into equal-width panes for each additional service.
        """
        panes: list[libtmux.Pane] = []
        n = len(service_commands)

        # First service: split above the agent pane (agent keeps 60%)
        first_svc = agent_pane.split(
            direction=libtmux.constants.PaneDirection.Above,
            start_directory=str(start_directory),
            size="40%",
        )
        first_svc.send_keys(service_commands[0], enter=True)
        panes.append(first_svc)

        # Remaining services: split the previous service pane to the right,
        # dividing the space evenly.
        prev = first_svc
        for j, cmd in enumerate(service_commands[1:], start=1):
            remaining = n - j
            pct = round(100 * remaining / (remaining + 1))
            new_pane = prev.split(
                direction=libtmux.constants.PaneDirection.Right,
                start_directory=str(start_directory),
                size=f"{pct}%",
            )
            new_pane.send_keys(cmd, enter=True)
            panes.append(new_pane)
            prev = new_pane

        return panes

    def attach_session(self, session_name: str) -> None:
        """Attach to a tmux session (replaces current process)."""
        tmux_bin = shutil.which("tmux")
        if tmux_bin is None:
            raise TmuxError("tmux binary not found")
        os.execvp(tmux_bin, ["tmux", "attach-session", "-t", session_name])
