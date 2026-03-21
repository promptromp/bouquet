# Architecture

Bouquet is an orchestration layer for multi-agent coding that composes four concerns.

## The Stack

```
CLI (Click) → bouquet start/stop/init
  └─► WorktreeManager (worktree.py — glue layer)
       ├─► git.py         subprocess calls for worktree CRUD
       ├─► tmux.py        libtmux wrapper for session/window/pane lifecycle
       ├─► template.py    safe {{ expr }} rendering for service commands
       ├─► bootstrap.py   setup commands + env capture, env file copy, CoW clone, dep install
       ├─► activity.py    ActivityMonitor — pane scraping for live status
       ├─► github.py      gh CLI wrapper for PR URL lookup
       ├─► tasks/         pluggable task queue (LocalBackend, GitHubIssuesBackend)
       └─► TUI (tui/app.py — Textual app in tmux window 0)
            └─► spawns worktree windows via WorktreeManager
```

## Conceptual Layers

```mermaid
block-beta
    columns 1
    block:orchestration["Orchestration Layer"]
        A["TUI"] B["Agent Coordination"] C["Task Queue"]
    end
    block:session["Session / Mux Layer"]
        D["tmux sessions"] E["windows"] F["panes"]
    end
    block:isolation["Isolation Layer"]
        G["git worktrees"] H["env isolation"]
    end
    block:environment["Environment Layer"]
        I["venv / node_modules"] J["env vars"]
    end
```

## Key Flow

`bouquet start` creates a tmux session, launches the TUI in window 0, then the TUI drives `WorktreeManager.create()` which chains:

1. **Git worktree creation** — new branch + worktree directory
2. **Bootstrap** — setup commands, env capture, CoW clone, dependency install
3. **Tmux window** — new window with agent pane + service panes
4. **Agent launch** — `send_keys` to the agent pane

## Activity Detection

The `ActivityMonitor` polls each agent's tmux pane every 2 seconds:

- **SHA256 hash** of pane content; hash change → RUNNING
- **Stable 3+ polls** → IDLE (or WAITING if a permission prompt is detected)
- **Prompt detection** scans the last 10 lines for permission menus

## Task Queue

Pluggable backend system with two implementations:

| Backend | Storage | Status Mapping |
|---------|---------|----------------|
| **Local** | SQLite (`~/.local/state/bouquet/<project>.tasks.db`) | Direct status field |
| **GitHub Issues** | GitHub Issues via `gh` CLI | OPEN = open issue, IN_PROGRESS = `in-progress` label, DONE = closed |

### Task Lifecycle

```mermaid
stateDiagram-v2
    [*] --> OPEN: Create task
    OPEN --> IN_PROGRESS: Pick up (x)
    IN_PROGRESS --> DONE: Complete (m)
    IN_PROGRESS --> OPEN: Reconcile (stale)
```

## Pane Layouts

### `services-top` (default)

```
┌────────────┬────────────┐
│   api      │  frontend  │  ← services (~40%)
├────────────┴────────────┤
│       agent (claude)    │  ← agent (~60%)
└─────────────────────────┘
```

### `main-vertical`

```
┌──────────────────┬────────────┐
│                  │   api      │
│   agent (claude) ├────────────┤
│                  │  frontend  │
└──────────────────┴────────────┘
```
