"""Claude Code adapter — wraps ``claude -p`` for headless interaction."""

from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from bouquet.agents.base import AgentAdapter, AgentResponse


class ClaudeCodeAdapter(AgentAdapter):
    """Interact with Claude Code via ``claude -p --output-format json``."""

    def __init__(
        self,
        *,
        allowed_tools: list[str] | None = None,
        max_turns: int | None = None,
    ) -> None:
        self.allowed_tools = allowed_tools
        self.max_turns = max_turns

    def _build_command(self, prompt: str) -> list[str]:
        claude_bin = shutil.which("claude")
        if claude_bin is None:
            raise FileNotFoundError("claude CLI not found on PATH")

        cmd = [claude_bin, "-p", prompt, "--output-format", "json"]
        if self.allowed_tools:
            cmd.extend(["--allowedTools", ",".join(self.allowed_tools)])
        if self.max_turns is not None:
            cmd.extend(["--max-turns", str(self.max_turns)])
        return cmd

    async def send(
        self,
        prompt: str,
        cwd: Path,
        *,
        branch: str = "",
        timeout: float | None = None,
    ) -> AgentResponse:
        """Run ``claude -p`` in *cwd* and return the parsed response."""
        cmd = self._build_command(prompt)
        start = time.monotonic()

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=cwd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as exc:
            return AgentResponse(
                worktree_branch=branch,
                result="",
                error=str(exc),
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            return AgentResponse(
                worktree_branch=branch,
                result="",
                error=f"Timed out after {timeout}s",
                duration_ms=int((time.monotonic() - start) * 1000),
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        if proc.returncode != 0:
            return AgentResponse(
                worktree_branch=branch,
                result="",
                error=stderr.decode(errors="replace").strip() or f"Exit code {proc.returncode}",
                duration_ms=duration_ms,
            )

        return self._parse_response(stdout.decode(errors="replace"), branch, duration_ms)

    @staticmethod
    def _parse_response(raw: str, branch: str, duration_ms: int) -> AgentResponse:
        """Parse the JSON output from ``claude -p --output-format json``."""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Fall back to treating raw output as plain text
            return AgentResponse(
                worktree_branch=branch,
                result=raw.strip(),
                duration_ms=duration_ms,
            )

        return AgentResponse(
            worktree_branch=branch,
            result=data.get("result", ""),
            session_id=data.get("session_id"),
            cost_usd=data.get("cost_usd"),
            duration_ms=duration_ms,
            metadata={k: v for k, v in data.items() if k not in ("result", "session_id", "cost_usd")},
        )
