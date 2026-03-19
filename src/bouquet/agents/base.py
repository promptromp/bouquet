"""Abstract base class for agent adapters."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AgentResponse:
    """Response from an agent command."""

    worktree_branch: str
    result: str
    session_id: str | None = None
    error: str | None = None
    cost_usd: float | None = None
    duration_ms: int | None = None
    metadata: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.error is None


class AgentAdapter(ABC):
    """Base class for coding agent adapters.

    Subclasses wrap a specific CLI tool (claude, codex, etc.) and
    provide a uniform interface for sending prompts and collecting
    structured responses.
    """

    @abstractmethod
    async def send(
        self,
        prompt: str,
        cwd: Path,
        *,
        branch: str = "",
        timeout: float | None = None,
    ) -> AgentResponse:
        """Send a prompt to the agent at *cwd* and return its response."""

    async def broadcast(
        self,
        prompt: str,
        worktrees: list[tuple[str, Path]],
        *,
        timeout: float | None = None,
    ) -> list[AgentResponse]:
        """Send *prompt* to all worktrees in parallel and collect responses."""
        tasks = [self.send(prompt, cwd, branch=branch, timeout=timeout) for branch, cwd in worktrees]
        return list(await asyncio.gather(*tasks))
