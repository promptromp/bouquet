"""Configuration models and loading logic."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class LanguagesConfig(BaseModel):
    python: bool = True
    javascript: bool = False


class ProjectConfig(BaseModel):
    name: str = "default"
    repo_path: str = "."
    base_branch: str = "main"
    languages: LanguagesConfig = Field(default_factory=LanguagesConfig)


class AgentConfig(BaseModel):
    command: str = "claude"
    args: list[str] = Field(default_factory=list)


class BootstrapConfig(BaseModel):
    copy_env_files: list[str] = Field(default_factory=lambda: [".env", ".env.local", ".envrc"])
    python_deps_command: str = "uv sync"
    node_deps_command: str = "pnpm install"
    use_cow_clone: bool = True
    direnv_allow: bool = True


class ServiceConfig(BaseModel):
    name: str
    command: str


class TmuxConfig(BaseModel):
    session_prefix: str = "bouquet"
    layout: str | None = None


class BouquetSettings(BaseSettings):
    model_config = {"env_prefix": "BOUQUET_"}

    project: ProjectConfig = Field(default_factory=ProjectConfig)
    agent: AgentConfig = Field(default_factory=AgentConfig)
    bootstrap: BootstrapConfig = Field(default_factory=BootstrapConfig)
    tmux: TmuxConfig = Field(default_factory=TmuxConfig)
    services: list[ServiceConfig] = Field(default_factory=list)


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_config(
    config_path: Path | None = None,
    repo_path: Path | None = None,
) -> BouquetSettings:
    """Load configuration from file using search order:

    1. Explicit --config flag
    2. .bouquet.toml in repo root
    3. ~/.config/bouquet/config.toml
    4. Defaults
    """
    data: dict[str, Any] = {}

    if config_path and config_path.exists():
        data = _load_toml(config_path)
    else:
        # Search in repo root
        repo = repo_path or Path.cwd()
        repo_config = repo / ".bouquet.toml"
        if repo_config.exists():
            data = _load_toml(repo_config)
        else:
            # Search in user config dir
            user_config = Path.home() / ".config" / "bouquet" / "config.toml"
            if user_config.exists():
                data = _load_toml(user_config)

    settings = BouquetSettings(**data)

    # Override repo_path if provided via CLI
    if repo_path:
        settings.project.repo_path = str(repo_path)

    return settings


TEMPLATE_CONFIG = """\
[project]
name = "{name}"
repo_path = "."
base_branch = "main"

[project.languages]
python = true
javascript = false

[agent]
command = "claude"
args = []

[bootstrap]
copy_env_files = [".env", ".env.local", ".envrc"]
python_deps_command = "uv sync"
node_deps_command = "pnpm install"
use_cow_clone = true
direnv_allow = true

[tmux]
session_prefix = "bouquet"
# layout = "main-vertical"   # tmux layout: main-vertical, tiled, even-horizontal, etc.

# ---------------------------------------------------------------------------
# Services — optional processes to run alongside the agent in each worktree.
#
# Each [[services]] entry gets its own tmux pane. Commands support template
# variables inside {{{{ }}}} with arithmetic for automatic port offsetting:
#
#   BOUQUET_WORKTREE_INDEX   — unique int per worktree (1, 2, 3, ...)
#   BOUQUET_WORKTREE_BRANCH  — branch name, e.g. "feature/auth"
#   BOUQUET_WORKTREE_PATH    — absolute path to the worktree directory
#   BOUQUET_PROJECT_NAME     — project name from this config
#
# Examples:
#
# --- Python API server (unique port per worktree) ---
# [[services]]
# name = "api"
# command = "uv run uvicorn app.main:app --reload --port {{{{ 8000 + BOUQUET_WORKTREE_INDEX }}}}"
#
# --- Background worker (no port needed) ---
# [[services]]
# name = "worker"
# command = "uv run celery -A app.tasks worker --loglevel=info"
#
# --- Scheduler / beat process ---
# [[services]]
# name = "scheduler"
# command = "uv run celery -A app.tasks beat"
#
# --- Event consumer (e.g. FastStream / Kafka / RabbitMQ) ---
# [[services]]
# name = "events"
# command = "uv run faststream run app.events:app"
#
# --- Frontend dev server (unique port per worktree) ---
# [[services]]
# name = "frontend"
# command = "npm run dev -- --port {{{{ 3000 + BOUQUET_WORKTREE_INDEX }}}}"
#
# --- Database / docker-compose services ---
# [[services]]
# name = "infra"
# command = "docker compose up postgres redis"
#
# --- Custom log tail ---
# [[services]]
# name = "logs"
# command = "tail -f /tmp/{{{{ BOUQUET_PROJECT_NAME }}}}-{{{{ BOUQUET_WORKTREE_INDEX }}}}.log"
# ---------------------------------------------------------------------------
"""
