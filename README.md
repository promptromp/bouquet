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
| ⚡ | **Fast bootstrap** | CoW-clones `.venv`/`node_modules` (APFS), copies `.env` files, runs `uv sync`/`pnpm install` |
| 🔧 | **Zero-arg CLI** | Just `cd` into your repo and run `bouquet start` — project name inferred from `.bouquet.toml` |

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
| `N` | Create a new worktree (opens branch dialog) |
| `S` / `Enter` | Switch to the selected worktree's window |
| `D` | Delete the selected worktree and its window |
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
