"""Tests for the agent adapter layer."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bouquet.agents.base import AgentResponse
from bouquet.agents.claude_code import ClaudeCodeAdapter


# --- AgentResponse ---


def test_agent_response_ok() -> None:
    resp = AgentResponse(worktree_branch="feat/a", result="done")
    assert resp.ok is True


def test_agent_response_error() -> None:
    resp = AgentResponse(worktree_branch="feat/a", result="", error="failed")
    assert resp.ok is False


# --- ClaudeCodeAdapter._build_command ---


def test_build_command_basic() -> None:
    adapter = ClaudeCodeAdapter()
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = adapter._build_command("hello")
    assert cmd == ["/usr/bin/claude", "-p", "hello", "--output-format", "json"]


def test_build_command_with_options() -> None:
    adapter = ClaudeCodeAdapter(allowed_tools=["Read", "Bash"], max_turns=5)
    with patch("shutil.which", return_value="/usr/bin/claude"):
        cmd = adapter._build_command("test")
    assert "--allowedTools" in cmd
    assert "Read,Bash" in cmd
    assert "--max-turns" in cmd
    assert "5" in cmd


def test_build_command_missing_claude() -> None:
    adapter = ClaudeCodeAdapter()
    with patch("shutil.which", return_value=None), pytest.raises(FileNotFoundError):
        adapter._build_command("hello")


# --- ClaudeCodeAdapter._parse_response ---


def test_parse_response_json() -> None:
    data = {"result": "All good", "session_id": "abc-123", "cost_usd": 0.005}
    resp = ClaudeCodeAdapter._parse_response(json.dumps(data), "feat/x", 1500)
    assert resp.ok
    assert resp.result == "All good"
    assert resp.session_id == "abc-123"
    assert resp.cost_usd == 0.005
    assert resp.duration_ms == 1500


def test_parse_response_plain_text_fallback() -> None:
    resp = ClaudeCodeAdapter._parse_response("just plain text", "feat/y", 500)
    assert resp.ok
    assert resp.result == "just plain text"
    assert resp.session_id is None


# --- ClaudeCodeAdapter.send (mocked subprocess) ---


@pytest.fixture
def adapter() -> ClaudeCodeAdapter:
    return ClaudeCodeAdapter()


@pytest.mark.asyncio
async def test_send_success(adapter: ClaudeCodeAdapter) -> None:
    output = json.dumps({"result": "summary here", "session_id": "s1"})
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(output.encode(), b""))
    mock_proc.returncode = 0

    with (
        patch("shutil.which", return_value="/usr/bin/claude"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        resp = await adapter.send("summarize", Path("/tmp/wt"), branch="feat/a")

    assert resp.ok
    assert resp.result == "summary here"
    assert resp.worktree_branch == "feat/a"


@pytest.mark.asyncio
async def test_send_nonzero_exit(adapter: ClaudeCodeAdapter) -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(b"", b"something went wrong"))
    mock_proc.returncode = 1

    with (
        patch("shutil.which", return_value="/usr/bin/claude"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        resp = await adapter.send("fail", Path("/tmp/wt"), branch="feat/b")

    assert not resp.ok
    assert "something went wrong" in resp.error  # type: ignore[operator]


@pytest.mark.asyncio
async def test_send_timeout(adapter: ClaudeCodeAdapter) -> None:
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(side_effect=TimeoutError())
    mock_proc.kill = MagicMock()

    with (
        patch("shutil.which", return_value="/usr/bin/claude"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        resp = await adapter.send("slow", Path("/tmp/wt"), branch="feat/c", timeout=1)

    assert not resp.ok
    assert "Timed out" in resp.error  # type: ignore[operator]
    mock_proc.kill.assert_called_once()


# --- broadcast ---


@pytest.mark.asyncio
async def test_broadcast_parallel(adapter: ClaudeCodeAdapter) -> None:
    output = json.dumps({"result": "ok"})
    mock_proc = AsyncMock()
    mock_proc.communicate = AsyncMock(return_value=(output.encode(), b""))
    mock_proc.returncode = 0

    targets = [("feat/a", Path("/tmp/a")), ("feat/b", Path("/tmp/b"))]

    with (
        patch("shutil.which", return_value="/usr/bin/claude"),
        patch("asyncio.create_subprocess_exec", return_value=mock_proc),
    ):
        results = await adapter.broadcast("hello", targets)

    assert len(results) == 2
    assert all(r.ok for r in results)
    assert {r.worktree_branch for r in results} == {"feat/a", "feat/b"}
