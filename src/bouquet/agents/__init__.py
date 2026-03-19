"""Agent adapters for interacting with coding agent CLIs."""

from bouquet.agents.base import AgentAdapter, AgentResponse
from bouquet.agents.claude_code import ClaudeCodeAdapter


__all__ = ["AgentAdapter", "AgentResponse", "ClaudeCodeAdapter"]
