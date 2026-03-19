<p align="center">
  <img src="docs/logo.png" alt="bouquet logo" width="400">
</p>

# bouquet

--------------------------------------------------------------------------------

[![CI](https://github.com/promptromp/bouquet/actions/workflows/ci.yml/badge.svg)](https://github.com/promptromp/bouquet/actions/workflows/ci.yml)

> **Warning — Alpha Software**
> Bouquet is under active development. APIs, config format, and CLI behavior may change without notice. Use at your own risk.

An orchestration layer for **multi-agent coding** — multiplexing coding agents across git worktrees with isolated services, all in one tmux session.

```bash
cd my-project
bouquet start              # TUI launches, create worktrees, agents spin up
```

### Key Features

| | Feature | Details |
|---|---|---|
| 🌿 | **Git worktree isolation** | Each feature branch gets its own worktree, venv, and node_modules — no cross-contamination |
| 🖥️ | **Multi-pane services** | Run API servers, workers, frontends alongside the agent with automatic port offsetting per worktree |
| 🤖 | **Agent orchestration** | TUI in tmux window 0 to create, switch, and manage worktree-backed agent windows |
| 📋 | **Task queue** | Define a backlog of tasks that get automatically delegated to worktrees — agents pick up work without manual intervention |
| 🔧 | **Rich configuration** | Expressive `.bouquet.toml` with template expressions (`{{ 8000 + BOUQUET_WORKTREE_INDEX }}`), per-worktree variables, agent profiles, and multi-service layouts |
| ⚡ | **Fast bootstrap** | CoW-clones `.venv`/`node_modules` (APFS), copies `.env` files, runs `uv sync`/`pnpm install` |
| 🔌 | **Agent-agnostic** | Named profiles let you mix Claude, Aider, Codex, or any CLI agent — even different agents per worktree |

---

## Requirements

- Python 3.14+
- [tmux](https://github.com/tmux/tmux) (`brew install tmux`)
- [direnv](https://direnv.net/) (optional, `brew install direnv`)
- Language package managers as needed (`uv`, `pnpm`)

## Installation

```bash
# Run without installing
uvx bouquet --help

# Or install via pip
pip install bouquet

# Or from source (development)
git clone https://github.com/promptromp/bouquet.git
cd bouquet
uv sync
```

---

## Quick Start

### 1. Initialize

```bash
cd /path/to/your/repo
bouquet init
```

Creates a `.bouquet.toml` template. Edit it to configure your project.

### 2. Start a session

```bash
bouquet start
```

This will:
1. Create a tmux session (`bouquet-<project-name>`)
2. Launch the orchestrator TUI in window 0
3. Adopt any existing git worktrees
4. Attach you to the session

You can also pass arguments explicitly:

```bash
bouquet start my-project --repo /path/to/repo --config /path/to/.bouquet.toml
```

### 3. Use the TUI

| Key | Action |
|---|---|
| `N` | Create a new worktree (opens branch dialog with optional agent profile selector) |
| `S` / `Enter` | Switch to the selected worktree's window |
| `D` | Delete the selected worktree and its window |
| `P` | Send a prompt to selected or all agent terminal(s) via tmux send-keys |
| `T` | Request a status summary from all agents (captures responses) |
| `R` | Refresh the worktree list |
| `Q` | Quit (with confirmation — kills the session) |

When you create a worktree, bouquet will:
- Create a git worktree with a new branch
- Bootstrap the environment (copy `.env` files, CoW-clone `.venv`/`node_modules`)
- Open a new tmux window with service panes (if configured)
- Launch the agent (e.g. `claude`) in pane 0

Switch back to the orchestrator: `Ctrl-b 0`.

### 4. Stop

```bash
bouquet stop
```

Cleans up all managed worktrees, kills the tmux session, and removes state.

---

## Services

Run dev servers alongside the agent in each worktree window. Define them in `.bouquet.toml`:

```toml
[[services]]
name = "api"
command = "uv run uvicorn app.main:app --reload --port {{ 8000 + BOUQUET_WORKTREE_INDEX }}"

[[services]]
name = "frontend"
command = "npm run dev -- --port {{ 3000 + BOUQUET_WORKTREE_INDEX }}"

[tmux]
layout = "main-vertical"
```

Each worktree gets a unique index (1, 2, 3, ...) so services bind to different ports automatically.

### Template Variables

| Variable | Type | Example |
|---|---|---|
| `BOUQUET_WORKTREE_INDEX` | int | `1`, `2`, `3` |
| `BOUQUET_WORKTREE_BRANCH` | str | `feature/auth` |
| `BOUQUET_WORKTREE_PATH` | str | `/path/to/.bouquet-worktrees/feature-auth` |
| `BOUQUET_PROJECT_NAME` | str | `my-project` |

Arithmetic supported: `{{ 8000 + BOUQUET_WORKTREE_INDEX }}` → `8001`.

No services defined = single pane with just the agent (backward compatible).

---

## Agent Profiles

Named agent configurations so you can switch between Claude, Aider, Codex, etc. per worktree:

```toml
[agent]
command = "claude"
default_profile = "claude"

[[agent.profiles]]
name = "claude"
command = "claude"

[[agent.profiles]]
name = "aider"
command = "aider"
args = ["--model", "claude-sonnet-4-20250514"]
```

When profiles are defined, the TUI's new-worktree dialog shows a profile selector. If no profiles are defined, the top-level `command`/`args` are used (backward compatible).

---

## Activity Detection

Bouquet polls each agent's tmux pane every 2 seconds to infer real-time status:

| Status | Meaning |
|---|---|
| **● running** (green) | Agent output is actively changing |
| **◆ waiting** (yellow) | Agent output stopped and a permission prompt was detected |
| **○ idle** (dim) | Agent output hasn't changed for several polls |

This replaces the static "active" status with live feedback. The TUI table updates automatically.

---

### Pane Layout

With `layout = "main-vertical"` and two services:

```
┌──────────────────┬────────────┐
│                  │   api      │
│   agent (claude) ├────────────┤
│                  │  frontend  │
└──────────────────┴────────────┘
```

---

## Architecture

```
The Conceptual Stack
┌─────────────────────────────────────────┐
│         Orchestration Layer             │  ← TUI, agent coordination
├─────────────────────────────────────────┤
│         Session / Mux Layer             │  ← tmux sessions, windows, panes
├─────────────────────────────────────────┤
│         Isolation Layer                 │  ← git worktrees + env isolation
├─────────────────────────────────────────┤
│         Environment Layer               │  ← venv/node_modules/env vars
└─────────────────────────────────────────┘
```

---

## Related Projects

Bouquet draws inspiration from and complements several tools in the multi-agent coding space:

- **[claude-squad](https://github.com/smtg-ai/claude-squad)** — A Go-based TUI for managing multiple Claude Code instances in parallel. Claude-squad focuses on running agents side-by-side with a clean terminal UI. Bouquet goes further with declarative multi-service layouts (API servers, frontends, workers per worktree), a rich template-based configuration language with per-worktree variable expansion, and a task queue for automatic work delegation across agents.

- **[ruflo](https://github.com/ruvnet/ruflo)** — A Rust-based agentic workflow orchestrator with a focus on DAG-based task execution and CI/CD integration. Ruflo takes a pipeline-oriented approach to agent coordination, while bouquet is designed around the developer's local workflow — git worktrees, tmux sessions, and interactive TUI management with live activity detection.

- **[Claude Code Agent Teams](https://code.claude.com/docs/en/agent-teams)** — Anthropic's experimental built-in feature for coordinating multiple Claude Code agents. Agent Teams operates within the Claude Code runtime itself. Bouquet is agent-agnostic (works with Claude, Aider, Codex, or any CLI tool), provides full control over environment isolation, service orchestration, and configuration through `.bouquet.toml`.
