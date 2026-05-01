"""WorktreeManager — composes git, tmux, and bootstrap for full worktree lifecycle."""

from __future__ import annotations

import contextlib
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from bouquet import git
from bouquet.bootstrap import SetupCommandsError, _run_setup_and_capture_env, bootstrap_worktree
from bouquet.config import BouquetSettings
from bouquet.models import SessionState, WorktreeInfo, WorktreeStatus
from bouquet.tasks.base import Task, TaskQueueBackend, TaskStatus
from bouquet.template import render_template
from bouquet.tmux import TmuxManager


logger = logging.getLogger(__name__)


_AGENT_STARTUP_DELAY = 3  # seconds to wait for agent process to initialize
_BRANCH_SANITIZE_PATTERN = re.compile(r"[^a-z0-9]+")
_BRANCH_MAX_LENGTH = 40


def sanitize_branch_name(title: str) -> str:
    """Sanitize a title into a valid branch name component."""
    return _BRANCH_SANITIZE_PATTERN.sub("-", title.lower())[:_BRANCH_MAX_LENGTH].strip("-")


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
        """Compute a tmux window name for a branch.

        Uses the full branch name with ``/`` replaced by ``-`` so that
        ``feature/auth`` and ``bugfix/auth`` produce distinct names.
        """
        return branch.replace("/", "-")

    def _allocate_index(self) -> int:
        """Return the lowest positive integer not used by any existing worktree."""
        used = {w.index for w in self.state.worktrees if w.index > 0}
        idx = 1
        while idx in used:
            idx += 1
        return idx

    def _build_template_variables(self, info: WorktreeInfo) -> dict[str, object]:
        """Build the context dict for template rendering."""
        return {
            "BOUQUET_WORKTREE_INDEX": info.index,
            "BOUQUET_WORKTREE_BRANCH": info.branch,
            "BOUQUET_WORKTREE_PATH": str(info.path),
            "BOUQUET_PROJECT_NAME": self.settings.project.name,
        }

    def _setup_window(self, info: WorktreeInfo) -> None:
        """Bootstrap worktree, create tmux window with services, and launch agent.

        Assumes the git worktree already exists at ``info.path``.  Mutates
        *info* in place (sets ``tmux_window_id`` and ``status``).
        """
        wt_path = info.path

        # 1. Bootstrap the worktree (returns env delta from setup_commands).
        # Build template vars once; forwarded to bootstrap (for setup_commands)
        # and reused directly by service panes below.
        tpl_vars = self._build_template_variables(info)
        env_delta = bootstrap_worktree(
            repo_path=self.repo_path,
            worktree_path=wt_path,
            config=self.settings.bootstrap,
            python=self.settings.project.languages.python,
            javascript=self.settings.project.languages.javascript,
            template_vars=tpl_vars,
        )

        # 2. Apply setup env vars to tmux session so service panes inherit them
        if env_delta:
            for key, value in env_delta.items():
                self.tmux.set_session_environment(self.session_name, key, value)

        # 3. Create tmux window and capture agent pane ID before service splits
        win_name = self._window_name(info.branch)
        window = self.tmux.create_window(
            session_name=self.session_name,
            window_name=win_name,
            start_directory=wt_path,
        )
        info.tmux_window_id = window.window_id
        agent_pane = window.active_pane
        info.agent_pane_id = agent_pane.pane_id if agent_pane else None
        info.status = WorktreeStatus.ACTIVE

        # 4. Set up service panes (if any)
        services = self.settings.services
        if services:
            rendered_cmds = [render_template(svc.command, tpl_vars) for svc in services]
            self.tmux.setup_service_panes(
                window=window,
                service_commands=rendered_cmds,
                start_directory=wt_path,
                layout=self.settings.tmux.layout,
            )

        # 5. Launch agent command in the agent pane
        profile = self.settings.agent.resolve_profile(info.agent_profile)
        agent_cmd = profile.command
        if profile.args:
            agent_cmd += " " + " ".join(profile.args)
        if info.agent_pane_id:
            self.tmux.send_keys_to_pane(info.agent_pane_id, agent_cmd)
        else:
            if info.tmux_window_id is None:
                raise RuntimeError("tmux_window_id not set after window creation")
            self.tmux.send_keys_to_window_id(
                session_name=self.session_name,
                window_id=info.tmux_window_id,
                keys=agent_cmd,
            )

    def create(
        self,
        branch: str,
        base_branch: str | None = None,
        agent_profile: str | None = None,
    ) -> WorktreeInfo:
        """Create a worktree, tmux window, bootstrap it, and launch the agent."""
        base = base_branch or self.settings.project.base_branch
        wt_path = self._worktree_path(branch)

        # Reuse a pre-registered placeholder (from TUI) or create a new entry
        info = self.state.find_worktree(branch)
        if info is not None:
            info.path = wt_path
            info.status = WorktreeStatus.CREATING
        else:
            info = WorktreeInfo(
                branch=branch,
                path=wt_path,
                status=WorktreeStatus.CREATING,
                created_at=datetime.now(),
            )
            self.state.worktrees.append(info)
        info.index = self._allocate_index()
        info.agent_profile = agent_profile
        self.state.save()

        try:
            # Create git worktree
            wt_path.parent.mkdir(parents=True, exist_ok=True)
            git.create_worktree(self.repo_path, wt_path, branch, base)

            # Bootstrap, tmux window, services, agent
            self._setup_window(info)

        except Exception:
            info.status = WorktreeStatus.ERROR
            raise
        finally:
            self.state.save()

        return info

    def adopt_existing(self) -> list[WorktreeInfo]:
        """Discover existing git worktrees and adopt them into the session.

        Introspects ``git worktree list``, skips the main worktree (the repo
        itself), and fully initialises each adopted worktree: bootstrap,
        tmux window with service panes, and agent launch — just like
        :meth:`create` but without the ``git worktree add`` step.
        """
        existing_branches = {w.branch for w in self.state.worktrees}
        git_worktrees = git.list_worktrees(self.repo_path)
        adopted: list[WorktreeInfo] = []

        for wt in git_worktrees:
            wt_path = Path(wt.get("path", ""))
            branch = wt.get("branch", "")

            # Skip the main worktree (the repo itself)
            if wt_path.resolve() == self.repo_path.resolve():
                continue

            # Skip bare/detached worktrees
            if not branch or wt.get("bare") or wt.get("detached"):
                continue

            # Skip worktrees we already track
            if branch in existing_branches:
                continue

            info = WorktreeInfo(
                branch=branch,
                path=wt_path,
                status=WorktreeStatus.CREATING,
                created_at=datetime.now(),
                index=self._allocate_index(),
            )

            try:
                self._setup_window(info)
            except Exception:
                info.status = WorktreeStatus.IDLE

            self.state.worktrees.append(info)
            adopted.append(info)

        if adopted:
            self.state.save()

        return adopted

    def remove(self, branch: str) -> None:
        """Remove a worktree and its associated tmux window.

        If ``BootstrapConfig.teardown_commands`` is configured, runs them
        in the worktree's path *before* killing tmux/removing the git
        worktree, so user code can reach the still-on-disk checkout.

        Teardown is best-effort — if commands fail, the failure is logged
        (file logger from ``bouquet.log`` plus stderr) but the rest of the
        cleanup proceeds.  Rationale: a transient infra failure
        (e.g. external service down) shouldn't block the local cleanup of
        tmux + git worktree, which the user can always retry from the
        command line.
        """
        # Find the worktree info
        info = self.state.find_worktree(branch)
        if info is None:
            return

        info.status = WorktreeStatus.REMOVING
        self.state.save()

        # Run teardown_commands BEFORE killing tmux / removing git worktree,
        # so the worktree path still exists for user cleanup logic.
        teardown_cmds = self.settings.bootstrap.teardown_commands
        if teardown_cmds and info.path.exists():
            tpl_vars = self._build_template_variables(info)
            try:
                _run_setup_and_capture_env(
                    teardown_cmds,
                    info.path,
                    template_vars=tpl_vars,
                    phase="teardown_commands",
                )
            except SetupCommandsError as exc:
                logger.warning(
                    "teardown_commands for %s failed (continuing with worktree removal): %s",
                    branch,
                    exc,
                )

        # Kill tmux window — prefer window ID (unique) over window name
        if info.tmux_window_id:
            with contextlib.suppress(Exception):
                self.tmux.kill_window_by_id(self.session_name, info.tmux_window_id)
        else:
            win_name = self._window_name(branch)
            with contextlib.suppress(Exception):
                self.tmux.kill_window(self.session_name, win_name)

        # Remove git worktree
        with contextlib.suppress(Exception):
            git.remove_worktree(self.repo_path, info.path)

        # Remove from state
        self.state.remove_worktree(branch)
        self.state.save()

    def remove_all(self) -> None:
        """Remove all managed worktrees."""
        for wt in list(self.state.worktrees):
            self.remove(wt.branch)

    def switch_to(self, branch: str) -> None:
        """Switch to the tmux window for a given branch."""
        info = self.state.find_worktree(branch)
        if info and info.tmux_window_id:
            self.tmux.switch_to_window_by_id(self.session_name, info.tmux_window_id)
        else:
            win_name = self._window_name(branch)
            self.tmux.switch_to_window(self.session_name, win_name)

    def pick_up_task(
        self,
        task: Task,
        backend: TaskQueueBackend,
        auto_branch_prefix: str = "task/",
        agent_profile: str | None = None,
    ) -> WorktreeInfo:
        """Pick up a task: create a worktree, mark it in-progress, and send the prompt."""
        # Generate branch name
        sanitized = sanitize_branch_name(task.title)
        branch = f"{auto_branch_prefix}{task.id}-{sanitized}"

        # Mark task in-progress
        backend.update_status(task.id, TaskStatus.IN_PROGRESS, branch=branch)

        # Create worktree
        info = self.create(branch, agent_profile=agent_profile)
        info.task_id = task.id
        self.state.save()

        # Wait for agent to start, then send the task prompt
        time.sleep(_AGENT_STARTUP_DELAY)
        prompt = self._build_task_prompt(task)
        if info.agent_pane_id:
            self.tmux.send_keys_to_pane(info.agent_pane_id, prompt)
        elif info.tmux_window_id:
            self.tmux.send_keys_to_window_id(
                session_name=self.session_name,
                window_id=info.tmux_window_id,
                keys=prompt,
            )

        return info

    @staticmethod
    def _build_task_prompt(task: Task) -> str:
        """Build the prompt string to send to an agent for a task."""
        parts = [f"Task: {task.title}"]
        if task.description:
            parts.append("")
            parts.append(task.description)
        if task.url:
            parts.append("")
            parts.append(f"Reference: {task.url}")
        return "\n".join(parts)

    def list_active(self) -> list[WorktreeInfo]:
        """Return the list of active worktrees."""
        return list(self.state.worktrees)
