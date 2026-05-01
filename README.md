<p align="center">
  <img src="docs/logo.png" alt="bouquet logo" width="320">
</p>

# bouquet

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
- [GitHub CLI](https://cli.github.com/) (optional, `brew install gh` — enables PR links in TUI and GitHub Issues task backend)
- [direnv](https://direnv.net/) (optional, `brew install direnv`)
- Language package managers as needed (`uv`, `pnpm`)

## Installation

```bash
# Run without installing
uvx pybouquet --help

# Or install via pip
pip install pybouquet

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
| `a` | Toggle auto-accept for selected worktree (auto-sends "y" at permission prompts) |
| `A` | Toggle autopilot mode (auto-schedules tasks by dependency order) |
| `P` | Send a prompt to selected or all agent terminal(s) via tmux send-keys |
| `T` | Request a status summary from all agents (captures responses) |
| `C` | Create a new task in the task queue |
| `X` | Pick up the highlighted task (creates worktree and sends task to agent) |
| `M` | Complete the highlighted task (optionally remove the associated worktree) |
| `Backspace` | Delete the highlighted task from the queue |
| `R` | Refresh the worktree list and task queue |
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

Cleans up all managed worktrees, resets any in-progress tasks back to open, kills the tmux session, and removes state.

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

The same template variables are also available in `[bootstrap]` `setup_commands`, `post_deps_commands`, and `teardown_commands` — both as `{{ … }}` placeholders and as plain shell env vars (`$BOUQUET_WORKTREE_INDEX`, etc.) — so setup/teardown scripts can provision and reclaim per-worktree resources (databases, queues, …) without external coordination.

No services defined = single pane with just the agent (backward compatible).

### Bootstrap hooks: `setup_commands` vs `post_deps_commands` vs `teardown_commands`

The three `[bootstrap]` hook lists run at different points in the worktree lifecycle:

| Hook | When | On failure | Typical use |
|---|---|---|---|
| `setup_commands` | **Before** `python_deps_command` / `node_deps_command` | **Loud** — raises `SetupCommandsError`, worktree → `ERROR` | private-registry auth (CodeArtifact tokens), provisioning per-worktree DBs / queues |
| `post_deps_commands` | **After** deps install, before `direnv_allow` (so `.venv` / `node_modules` exist) | **Loud** — same as setup_commands | `uv run migrate upgrade head`, asset compilation, anything that needs the project's tooling |
| `teardown_commands` | **Before** tmux window kill + git worktree removal (so the on-disk checkout is still reachable) | **Best-effort** — failures logged, cleanup proceeds | reclaiming external per-worktree resources at remove time (drop DBs, delete queues) |

`setup_commands` and `post_deps_commands` also have **env-capture**: any `export FOO=bar` lines in the user's commands are captured and propagated into both subsequent install commands and the tmux session, so service panes inherit them.

See [docs/configuration.md](docs/configuration.md#bootstrap) for the full reference.

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

## Task Queue

Define a backlog of tasks that agents pick up automatically. Two backends are supported:

### Local (SQLite) — default

Tasks are stored in `~/.local/state/bouquet/<project>.tasks.db`. No external dependencies.

```toml
[task_queue]
backend = "local"
auto_branch_prefix = "task/"
```

### GitHub Issues

Uses your repo's GitHub Issues as the task source. Requires `gh` CLI authenticated.

```toml
[task_queue]
backend = "github"
label_filter = "bouquet"     # only issues with this label appear as tasks
auto_branch_prefix = "task/"
```

**Status mapping:** OPEN = open issue, IN_PROGRESS = open issue + `in-progress` label, DONE = closed issue.

### Task workflow

1. **Create** (`c`) — opens a dialog to create a task with an optional parent dependency
2. **Pick up** (`x`) — creates a worktree from the task, marks it in-progress, and sends the task description to the agent
3. **Complete** (`m`) — marks the task as done, optionally removes the associated worktree
4. **Reconciliation** — on startup, tasks stuck as in-progress (from a crash or quit) are automatically reset to open if their worktree no longer exists

### Task Dependencies

Tasks can declare a parent dependency, forming a DAG. A task with an unsatisfied dependency shows as **blocked** in the queue and cannot be picked up until its parent is done. Cycles are rejected at creation time.

### Autopilot

Press `A` to toggle autopilot mode. When active, bouquet automatically:

- Picks up tasks whose dependencies are satisfied (or have none)
- Runs up to `max_autopilot_concurrency` tasks in parallel (default 3)
- Enables auto-accept on all autopilot-created worktrees
- Auto-completes tasks when their agent goes idle (~10 seconds)
- Cascades: completing a parent unblocks its children for the next scheduling cycle

```toml
[task_queue]
max_autopilot_concurrency = 3    # max parallel worktrees
autopilot_auto_complete = true   # auto-complete IDLE tasks
```

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

## Logs & Troubleshooting

Bouquet writes a rotating log file to `~/.local/state/bouquet/<project>.log` (5 MB × 3 backups). `bouquet start` prints the path to stderr on launch.

When a worktree creation fails — most often because a `setup_commands` or `post_deps_commands` step exited non-zero — the TUI shows a terse toast (`Error creating worktree: …`) but the captured stdout and stderr from your bash commands land in the log file, along with the phase name (`setup_commands` vs `post_deps_commands`), cwd, and exit code. Tail it to debug:

```sh
tail -f ~/.local/state/bouquet/<project>.log
```

The `SetupCommandsError` raised on failure includes the log file path in its message, so the toast will point you there directly.

`teardown_commands` failures are best-effort and don't block worktree removal — they log a `WARNING`-level line in the same log file, so check there if a worktree was removed but external resources weren't reclaimed.

Pass `--log-level=DEBUG` to `bouquet start` for more verbose output (e.g. each rendered `setup_commands` / `post_deps_commands` / `teardown_commands` line):

```sh
bouquet start --log-level=DEBUG
```

---

## Architecture

```
The Conceptual Stack
┌─────────────────────────────────────────┐
│         Orchestration Layer             │  ← TUI, agent coordination, task queue
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
