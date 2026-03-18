# bouquet

An orchestration layer for agentic coding.

Uses best-of-breed approach to support multiplexing agentic coding tasks:

* Use [git worktrees]() for supporting concurrent development on multiple features touching same repository
* Uses [direnv]() for managing configuration via environment variables of services
* Uses [tmux]() and [tmuxinator]() for supporting remote control and intuitive development workflow where coding agents need to use dev servers (e.g. running daemons/API services) locally and have easy access to their input and output (E.g. via tmux send-keys and pane capture)
* Uses OS and Language-specific mechanisms for speed and efficiency (`uv` for Python, `pnpm` for JavaScript, Copy-on-write for APFS/macOS etc.)
* Supports a configuration file-based usage for easy scaffolding per project (using TOML configuration file format).


## Installation

Make sure you have the needed OS packages installed, minimally:

* tmux (on macOS `brew install tmux`)
* direnv (on macOS `brew install direnv`) — optional, for env var management
* relevant languages package managers (e.g. `uv`, `pnpm`)

Then install bouquet:

```bash
# From the repo root
uv sync

# Or install via pip
pip install -e .
```


## Usage

### Initialize a project

Generate a `.bouquet.toml` configuration file in your repo:

```bash
bouquet init --repo /path/to/your/repo
```

This creates a `.bouquet.toml` template. Edit it to configure your project name, languages, agent command, bootstrap settings, and tmux preferences.

### Start a session

```bash
bouquet start my-project --repo /path/to/your/repo
```

This will:
1. Create a tmux session named `bouquet-my-project`
2. Launch the orchestrator TUI in window 0
3. Attach you to the session

You can also point to a specific config file:

```bash
bouquet start my-project --repo /path/to/repo --config /path/to/.bouquet.toml
```

### Using the TUI

Once inside the tmux session, the orchestrator TUI in window 0 provides:

| Key       | Action                                      |
|-----------|---------------------------------------------|
| `N`       | Create a new worktree (opens branch dialog) |
| `Enter`   | Switch to the selected worktree's window    |
| `D`       | Delete the selected worktree and its window |
| `R`       | Refresh the worktree list                   |
| `Q`       | Quit the TUI                                |

When you create a new worktree, bouquet will:
- Create a git worktree with a new branch
- Bootstrap the environment (copy `.env` files, CoW-clone `.venv`/`node_modules`)
- Open a new tmux window in the worktree directory
- Auto-launch the configured agent command (e.g. `claude`)

Switch back to the orchestrator at any time with `Ctrl-b 0` (tmux default).

### Stop a session

```bash
bouquet stop my-project
```

This cleans up all managed git worktrees, kills the tmux session, and removes the session state file.


## Overview

`bouquet` strings together a few frameworks and technologies to support an intuitive and powerful workflow for multi-agent development orchestration.

A single logical `project` (typically corresponding to a single code repository, e.g. Git repo) is associated with a `configuration` (via TOML file) that lets user specify a few relevant parameters (project languages, dev servers, e.g. CLI invocation for one or more services such as API service, daemon, etc. which we'd want to run locally for development).
`bouquet` then exposes a CLI that lets users bootstrap a `session` - a tmux session configured tmuxinator config language, with a layout consisting of the dev servers as configured and an agentic coding tool (e.g. Claude Code). multiple windows would be created in the session, each corresponding to a logical git worktree / feature branch to allow for easy work on multiple features at once, while still easily switching between them within context of a single tmux session.
Additionally, the first window fo the tmux session consists of an orchestration agent - a TUI that shows high-level summary of activity across all worktrees / windows for the current project, as well as allowing to dispatch commands / tasks and spawn new windows in the session corresponding to new features/worktrees.


The Conceptual Stack
┌─────────────────────────────────────────┐
│         Orchestration Layer             │  ← coordinates agents, tasks, merges
├─────────────────────────────────────────┤
│         Session / Mux Layer             │  ← tmux, process management
├─────────────────────────────────────────┤
│         Isolation Layer                 │  ← git worktrees + env isolation
├─────────────────────────────────────────┤
│         Environment Layer               │  ← venv/node_modules/env vars
└─────────────────────────────────────────┘
