"""Activity detection for worktree agents via tmux pane scraping."""

from __future__ import annotations

import hashlib
import re

from bouquet.models import WorktreeStatus
from bouquet.tmux import TmuxManager


# Patterns that indicate an agent is waiting for user input.
_PROMPT_PATTERNS = [
    re.compile(r"\[Y/n\]", re.IGNORECASE),
    re.compile(r"\[y/N\]", re.IGNORECASE),
    re.compile(r"\(y/n\)", re.IGNORECASE),
    re.compile(r"Do you want to proceed\?", re.IGNORECASE),
    re.compile(r"This command requires approval", re.IGNORECASE),
    re.compile(r"Allow\?", re.IGNORECASE),
    re.compile(r"Approve\?", re.IGNORECASE),
]

# Statuses eligible for activity polling.
POLLABLE_STATUSES = frozenset(
    {
        WorktreeStatus.ACTIVE,
        WorktreeStatus.RUNNING,
        WorktreeStatus.WAITING,
        WorktreeStatus.IDLE,
    }
)


class ActivityMonitor:
    """Monitors tmux pane output to infer agent activity status.

    Polls pane content, hashes it, and compares to the previous hash:
    - Hash changed → ``RUNNING``
    - Stable for *stability_threshold* consecutive polls → ``WAITING`` (if
      a permission prompt is detected) or ``IDLE``
    - First poll → ``RUNNING``
    """

    def __init__(self, tmux: TmuxManager, stability_threshold: int = 3) -> None:
        self._tmux = tmux
        self._stability_threshold = stability_threshold
        self._hashes: dict[str, str] = {}
        self._stable_count: dict[str, int] = {}

    def check(self, session_name: str, window_id: str, agent_pane_id: str | None = None) -> WorktreeStatus:
        """Check a single pane and return the inferred status."""
        try:
            if agent_pane_id:
                content = self._tmux.capture_pane_by_id(agent_pane_id)
            else:
                content = self._tmux.capture_pane(session_name, window_id)
        except Exception:
            return WorktreeStatus.ERROR

        current_hash = hashlib.sha256(content.encode()).hexdigest()
        last_hash = self._hashes.get(window_id)
        self._hashes[window_id] = current_hash

        if last_hash is None:
            self._stable_count[window_id] = 0
            return WorktreeStatus.RUNNING

        if current_hash != last_hash:
            self._stable_count[window_id] = 0
            return WorktreeStatus.RUNNING

        self._stable_count[window_id] = self._stable_count.get(window_id, 0) + 1

        if self._stable_count[window_id] >= self._stability_threshold:
            if self._has_permission_prompt(content):
                return WorktreeStatus.WAITING
            return WorktreeStatus.IDLE

        return WorktreeStatus.RUNNING

    @staticmethod
    def _has_permission_prompt(content: str) -> bool:
        """Return True if the last few lines contain a known permission prompt."""
        last_lines = "\n".join(content.splitlines()[-10:])
        return any(p.search(last_lines) for p in _PROMPT_PATTERNS)

    def remove(self, window_id: str) -> None:
        """Remove tracking state for a window (e.g. after worktree removal)."""
        self._hashes.pop(window_id, None)
        self._stable_count.pop(window_id, None)
