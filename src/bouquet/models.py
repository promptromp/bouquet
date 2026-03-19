"""Data models for worktree and session state."""

from __future__ import annotations

import json
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field


class WorktreeStatus(StrEnum):
    CREATING = "creating"
    ACTIVE = "active"
    RUNNING = "running"
    WAITING = "waiting"
    IDLE = "idle"
    ERROR = "error"
    REMOVING = "removing"


class WorktreeInfo(BaseModel):
    branch: str
    path: Path
    tmux_window_id: str | None = None
    status: WorktreeStatus = WorktreeStatus.CREATING
    created_at: datetime = Field(default_factory=datetime.now)
    index: int = 0
    agent_profile: str | None = None


class SessionState(BaseModel):
    project_name: str
    tmux_session_name: str
    repo_path: Path
    worktrees: list[WorktreeInfo] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)

    @classmethod
    def state_dir(cls) -> Path:
        """Return the state directory, creating it if needed."""
        d = Path.home() / ".local" / "state" / "bouquet"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @classmethod
    def state_file(cls, project_name: str) -> Path:
        return cls.state_dir() / f"{project_name}.json"

    def save(self) -> None:
        """Persist session state to disk."""
        path = self.state_file(self.project_name)
        path.write_text(self.model_dump_json(indent=2))

    @classmethod
    def load(cls, project_name: str) -> SessionState | None:
        """Load session state from disk, or None if not found."""
        path = cls.state_file(project_name)
        if not path.exists():
            return None
        data = json.loads(path.read_text())
        return cls.model_validate(data)

    def delete_state(self) -> None:
        """Remove the state file."""
        path = self.state_file(self.project_name)
        if path.exists():
            path.unlink()
