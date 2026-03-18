"""WorktreeManager — composes git, tmux, and bootstrap for full worktree lifecycle."""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path

from bouquet import git
from bouquet.bootstrap import bootstrap_worktree
from bouquet.config import BouquetSettings
from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus
from bouquet.tmux import TmuxManager


class WorktreeManager:
    """High-level orchestrator for creating/removing worktree-backed tmux windows."""

    def __init__(
        self,
        settings: BouquetSettings,
        state: SessionState,
        tmux: TmuxManager | None = None,
    ) -> None:
        self.settings = settings
        self.state = state
        self.tmux = tmux or TmuxManager()
        self.repo_path = Path(self.settings.project.repo_path).resolve()

    @property
    def session_name(self) -> str:
        return self.state.tmux_session_name

    def _worktree_path(self, branch: str) -> Path:
        """Compute the worktree directory path for a branch."""
        safe_name = branch.replace("/", "-")
        return self.repo_path.parent / ".bouquet-worktrees" / safe_name

    def _window_name(self, branch: str) -> str:
        """Compute a tmux window name for a branch."""
        # Use the last segment of the branch for brevity
        return branch.rsplit("/", maxsplit=1)[-1]

    def create(self, branch: str, base_branch: str | None = None) -> WorktreeInfo:
        """Create a worktree, tmux window, bootstrap it, and launch the agent."""
        base = base_branch or self.settings.project.base_branch
        wt_path = self._worktree_path(branch)

        # Create worktree info and track it
        info = WorktreeInfo(
            branch=branch,
            path=wt_path,
            status=WorktreeStatus.CREATING,
            created_at=datetime.now(),
        )
        self.state.worktrees.append(info)
        self.state.save()

        try:
            # 1. Create git worktree
            wt_path.parent.mkdir(parents=True, exist_ok=True)
            git.create_worktree(self.repo_path, wt_path, branch, base)

            # 2. Bootstrap the worktree
            bootstrap_worktree(
                repo_path=self.repo_path,
                worktree_path=wt_path,
                config=self.settings.bootstrap,
                python=self.settings.project.languages.python,
                javascript=self.settings.project.languages.javascript,
            )

            # 3. Create tmux window
            win_name = self._window_name(branch)
            window = self.tmux.create_window(
                session_name=self.session_name,
                window_name=win_name,
                start_directory=wt_path,
            )
            info.tmux_window_id = window.window_id
            info.status = WorktreeStatus.ACTIVE

            # 4. Launch agent command in the new window
            agent_cmd = self.settings.agent.command
            if self.settings.agent.args:
                agent_cmd += " " + " ".join(self.settings.agent.args)
            self.tmux.send_keys(
                session_name=self.session_name,
                window_name=win_name,
                keys=agent_cmd,
            )

        except Exception:
            info.status = WorktreeStatus.ERROR
            raise
        finally:
            self.state.save()

        return info

    def remove(self, branch: str) -> None:
        """Remove a worktree and its associated tmux window."""
        # Find the worktree info
        info = next((w for w in self.state.worktrees if w.branch == branch), None)
        if info is None:
            return

        info.status = WorktreeStatus.REMOVING
        self.state.save()

        # Kill tmux window
        win_name = self._window_name(branch)
        with contextlib.suppress(Exception):
            self.tmux.kill_window(self.session_name, win_name)

        # Remove git worktree
        with contextlib.suppress(Exception):
            git.remove_worktree(self.repo_path, info.path)

        # Remove from state
        self.state.worktrees = [w for w in self.state.worktrees if w.branch != branch]
        self.state.save()

    def remove_all(self) -> None:
        """Remove all managed worktrees."""
        for wt in list(self.state.worktrees):
            self.remove(wt.branch)

    def switch_to(self, branch: str) -> None:
        """Switch to the tmux window for a given branch."""
        win_name = self._window_name(branch)
        self.tmux.switch_to_window(self.session_name, win_name)

    def list_active(self) -> list[WorktreeInfo]:
        """Return the list of active worktrees."""
        return list(self.state.worktrees)
