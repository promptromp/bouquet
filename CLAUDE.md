# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Development Commands

```bash
uv sync                              # Install all dependencies (uses uv.lock)
uv run pytest tests/ -v              # Run full test suite
uv run pytest tests/test_git.py -v   # Run a single test file
uv run pytest tests/test_git.py::test_create_and_list_worktree  # Run a single test
ruff check --fix src/ tests/         # Lint with auto-fix
ruff format src/ tests/              # Format code
mypy src/ tests/                     # Type-check
pre-commit run --all-files           # Run all pre-commit hooks
uv run bouquet --help                # Run CLI
```

Pre-commit hooks run on every commit: ruff check+format, mypy (with pydantic plugin), and pytest. Install with `pre-commit install`.

## Architecture

Bouquet is an orchestration layer for multi-agent coding that composes four concerns:

```
CLI (Click) → bouquet start/stop/init (args optional, infers from cwd + .bouquet.toml)
  └─► WorktreeManager (worktree.py — glue layer)
       ├─► git.py         subprocess calls for worktree CRUD
       ├─► tmux.py        libtmux wrapper for session/window/pane lifecycle
       ├─► template.py    safe {{ expr }} rendering for service commands
       ├─► bootstrap.py   setup commands + env capture, env file copy, CoW clone, dep install
       ├─► activity.py    ActivityMonitor — pane scraping for live status
       ├─► github.py      gh CLI wrapper for PR info + status lookup
       ├─► tasks/         pluggable task queue (LocalBackend, GitHubIssuesBackend)
       └─► TUI (tui/app.py — Textual app in tmux window 0)
            └─► spawns worktree windows via WorktreeManager
```

**Key flow:** `bouquet start` creates a tmux session, launches the TUI in window 0, then the TUI drives `WorktreeManager.create()` which chains git worktree creation → bootstrap → tmux window → service pane setup → agent launch via `send_keys`.

**The TUI runs inside tmux** but controls tmux via libtmux's server socket API (no terminal conflict). Switching to a worktree window hides the TUI; return with `Ctrl-b 0`.

## Key Design Decisions

- **`git.py` strips `GIT_*` env vars** (`_clean_env()`) before subprocess calls. This prevents pre-commit hook context from leaking into worktree operations. Do not remove this.
- **TUI uses `@work(thread=True)`** for create/remove operations to avoid blocking the Textual event loop. Use `self.call_from_thread()` to update UI from workers.
- **State persists to `~/.local/state/bouquet/{project}.json`** so `bouquet stop` can clean up even if the TUI crashes.
- **Bootstrap errors are suppressed** (`contextlib.suppress`) — partial setup is acceptable when tools are missing.
- **Worktree paths** are computed as `{repo_parent}/.bouquet-worktrees/{branch-with-slashes-replaced}`.
- **Worktree indices** are slot-based with reuse (lowest unused positive int). Stored in `WorktreeInfo.index`. Used for port offsetting in service templates.
- **Template engine** (`template.py`) uses `ast.parse` with a whitelist of safe nodes — no Jinja2 dependency. Only arithmetic on known variables is allowed.
- **CLI args are optional** — `bouquet start`/`stop` default to cwd as repo and read project name from `.bouquet.toml`. Errors clearly if not in a git repo or no config found.
- **Window names use full branch** — `_window_name()` replaces `/` with `-` (e.g. `feature/auth` → `feature-auth`). Previous behavior used only the last segment, causing collisions.
- **Window-ID-based tmux operations** — `TmuxManager` has both name-based (legacy) and ID-based methods. Prefer ID-based (`send_keys_to_window_id`, `switch_to_window_by_id`, `kill_window_by_id`) to avoid window name collisions.
- **Activity polling** — `ActivityMonitor` runs every 2s in the TUI via `set_interval` + `@work(thread=True)`. SHA256 hashing of pane content; hash change → RUNNING, stable 3+ polls → IDLE (or WAITING if a permission prompt is detected). Prompt detection scans the last 10 lines (not 5 — Claude Code permission menus are 7+ lines tall). The poll worker re-checks `wt.status in POLLABLE_STATUSES` before overwriting, preventing race conditions where a REMOVING/CREATING status gets clobbered by an ERROR from a dying pane.
- **Agent profiles** — `AgentConfig.resolve_profile(name)` resolves a named profile or falls back to the top-level `command`/`args`. Backward-compatible: old configs without `profiles` work unchanged.
- **Bootstrap setup commands** — `BootstrapConfig.setup_commands` runs shell commands in a single bash context before dependency installation. Each command string is rendered through `template.render_template()` (`{{ BOUQUET_WORKTREE_INDEX }}` etc.) and the same vars are also exported into the bash subprocess as plain shell env vars (`$BOUQUET_*`), so callers can pick whichever form reads better. Env vars exported by the user's commands are captured (via a `python3` JSON dump to a temp file — portable across macOS/Linux) and propagated to deps install subprocesses and the tmux session (via `set_environment`). The captured-delta diff is scoped against `subproc_env` (not `os.environ`) so the injected `BOUQUET_*` vars cancel out and never leak into the delta. Use cases: private registry auth (e.g. AWS CodeArtifact tokens), per-worktree resource provisioning (databases, message queues, cache namespaces).
- **Bootstrap python_version** — Optional `BootstrapConfig.python_version` runs `uv python pin <version>` in the worktree before dependency installation. Ensures consistent Python version across worktrees regardless of what's available on the system.
- **GitHub PR status** — `github.py` provides `lookup_pr_info()` returning a `PRInfo` dataclass with `number`, `url`, `title`, and `status` (a `PRStatus` enum: DRAFT, OPEN, CHECKS_FAILING, CHECKS_PENDING, READY, MERGED, CLOSED). Status is derived from `gh pr view` JSON fields: `state`, `isDraft`, and `statusCheckRollup` (CI check conclusions). The detail panel shows `#42 ready to merge` with color-coded status. PR cache has a 30s TTL (`_PR_REFRESH_SECONDS`) so CI status refreshes automatically. The `gh` CLI is optional — missing `gh` degrades gracefully with no PR field shown and no error. Lookups run in a `@work(thread=True, group="pr-lookup")` worker so rapid cursor movement cancels stale lookups. `_refresh_table` also triggers lookups (not just `RowHighlighted`) to handle the case where `clear()+add_row()` doesn't re-fire the highlight event.- **services-top layout** — Default tmux layout (`TmuxConfig.layout = "services-top"`). Arranges service panes in an equal-width horizontal row across the top (~40%) with the agent pane spanning full width at the bottom (~60%). Implemented via custom splits in `TmuxManager._setup_services_top()`, not a tmux built-in layout. Any other layout value is passed through to `select_layout` as a standard tmux layout name.
- **Agent pane ID tracking** — `WorktreeInfo.agent_pane_id` stores the tmux pane ID (e.g. `%138`) of the agent pane, captured before service pane splits in `_setup_window`. All pane-targeted operations (activity polling, send-keys, capture) use `send_keys_to_pane` / `capture_pane_by_id` with this ID instead of `window.active_pane`, which could be any pane the user last clicked. Falls back to `window.active_pane` if `agent_pane_id` is `None` (backward compat with old state files).
- **Per-worktree auto-accept** — `WorktreeInfo.auto_accept` (default `False`) enables automatic acceptance of permission prompts. Logic lives in `_poll_activity_worker` (not `ActivityMonitor`) so the monitor stays a pure detection component. A `_recently_accepted` guard set prevents repeated sends while the prompt is still visible; entries are cleared when status leaves WAITING. Toggled per-worktree via `a` keybinding. Smart prompt detection (`_detect_accept_key`) parses pane content: for Claude Code numbered menus, prefers "Yes, and don't ask again" (option 2) over plain "Yes" (option 1); falls back to "y" for traditional `[Y/n]` prompts.
- **Task queue** — Pluggable backend system (`TaskQueueBackend` ABC in `src/bouquet/tasks/base.py`). Two backends: `LocalBackend` (SQLite, `~/.local/state/bouquet/{project}.tasks.db`) and `GitHubIssuesBackend` (`gh` CLI wrapper). Backend is synchronous; TUI wraps calls in `@work(thread=True)`. Task ID is always a string (SQLite rowids or GitHub issue numbers). Factory in `src/bouquet/tasks/__init__.py` creates the backend from `TaskQueueConfig`. Set `backend = "github"` in config to use GitHub Issues.
- **GitHub Issues backend** — Maps task status to GitHub: OPEN = open issue (no label), IN_PROGRESS = open issue + `in-progress` label, DONE = closed issue. Branch is stored as a hidden HTML comment in the issue body (`<!-- bouquet:branch:... -->`). The `label_filter` config (default `"bouquet"`) controls which issues are visible as tasks. Internal labels (`bouquet`, `in-progress`) are filtered from `task.labels`. Requires `gh` CLI authenticated; raises `GitHubError` on init if missing.
- **Task pickup** — `WorktreeManager.pick_up_task()` generates branch `{prefix}{id}-{sanitized_title}`, updates task status to IN_PROGRESS, creates worktree via `create()`, waits ~3s for agent startup, then sends task description via `send_keys_to_pane`. The prompt is sent AFTER the agent starts — no modification to the agent launch flow.
- **Task TUI keybindings** — `c` creates a task (opens `CreateTaskScreen` modal), `x` picks up the highlighted task in `TaskQueueTable`, `m` completes the highlighted task (opens `CompleteTaskScreen` — if a worktree is associated via `task_id`, offers to remove it too). Task table refreshes on mount, after create, after pickup, after complete, and on `r`.
- **Task state reconciliation** — IN_PROGRESS tasks with no matching worktree are reset to OPEN on startup and shutdown. On TUI `on_mount()`, `_reconcile_tasks()` first restores `task_id` links for adopted worktrees whose branches match IN_PROGRESS tasks, then resets remaining stale tasks via `TaskQueueBackend.reconcile_stale(active_branches)`. On `bouquet stop`, `reconcile_stale(set())` resets all IN_PROGRESS tasks before teardown. A task with `branch=None` is always considered stale.
- **Task dependencies** — Each task has an optional `parent_id: str | None` field expressing a single-parent dependency (forms a DAG). Cycle detection uses ancestor-walk in `tasks/dag.py:detect_cycle()` — O(depth) per check. Both `create_task(parent_id=)` and `set_parent()` validate: parent must exist, no cycles allowed, raises `TaskBackendError` on violation. `delete_task` orphans children (sets their `parent_id` to `None`). The `TaskQueueTable` shows a "Dep" column (`#parent_id` or `-`) and displays OPEN tasks with unsatisfied parents as `"◌ blocked"` in dim yellow. `CreateTaskScreen` has a `Select` widget listing non-DONE tasks as potential parents.
- **DAG utilities** — Pure functions in `src/bouquet/tasks/dag.py`: `detect_cycle(tasks, child_id, parent_id)` walks ancestor chain; `topo_sort(tasks)` uses Kahn's algorithm (raises `ValueError` on cycles); `get_ready_tasks(tasks)` returns OPEN tasks whose parent is `None` or `DONE`. All backend-agnostic, operating on `list[Task]`.
- **GitHub Issues parent storage** — Parent ID stored as hidden HTML comment `<!-- bouquet:parent:ID -->` in issue body, same pattern as branch marker. `_strip_bouquet_markers()` strips both branch and parent markers from description for display. `set_parent` and `delete_task` read raw body via `gh issue view --json body` to avoid losing markers that `task.description` has stripped.
- **Autopilot mode** — `AutopilotController` in `src/bouquet/autopilot.py` drives DAG-aware task scheduling. Stateful but non-blocking: TUI calls `tick(session_state)` every poll cycle (~2s). Returns OPEN tasks ready to dispatch (deps satisfied, concurrency slots available). Does NOT own threads — TUI dispatches via existing `@work(thread=True)` pattern. `_picked_up_ids` set prevents double-pickup between tick and worker completion. Toggled via `A` keybinding. `AutopilotIndicator` widget shows `[AUTOPILOT 2/3]` (active/max slots). Autopilot-created worktrees always have `auto_accept=True`. Auto-completion: when `autopilot_auto_complete=True` (default), task worktrees IDLE for 5+ consecutive polls (~10s) are automatically marked DONE. Config: `max_autopilot_concurrency` (default 3), `autopilot_auto_complete` (default `True`) in `[task_queue]`.
- **Autopilot threading invariants** — The autopilot scheduling code runs inside `_poll_activity_worker` (a background thread). Three critical invariants: (1) `session_state.worktrees` must only be mutated from the main thread — autopilot uses `call_from_thread(_autopilot_dispatch, ...)` to append placeholders on the main thread; (2) `_autopilot_idle_counts` must be cleared before attempting auto-completion (not after), so failures don't cause infinite retry loops every 2s; (3) `_autopilot_idle_counts` must be cleared in `action_toggle_autopilot` when stopping, so stale counts don't carry across stop/start cycles.

## Configuration

Config search order: `--config` flag → `.bouquet.toml` in repo root → `~/.config/bouquet/config.toml` → defaults. All config models are Pydantic v2 in `config.py`.

## Code Style

- Line length: 120, target Python 3.14
- Ruff rules: E, F, UP, B, SIM, I, PLC
- Double quotes, isort with `combine-as-imports`, 2 blank lines after imports
- First-party package: `bouquet`

## Testing Patterns

- `tmp_git_repo` fixture creates a real git repo with initial commit in a temp dir
- `mock_tmux` fixture (MagicMock) avoids real tmux dependency in WorktreeManager tests
- Tests that monkeypatch `SessionState.state_dir` redirect state persistence to temp dirs
- CLI tests use Click's `CliRunner` with mocked `TmuxManager` — no real tmux needed
- GitHub Issues backend tests mock `_run_gh` and `gh_available` — no real `gh` CLI or network calls
- No interactive tmux or TUI rendering tests — TUI is tested at widget/data level only

## Important Instructions

- **Update docs after major changes.** After adding or changing functionality, check if README.md, CLAUDE.md, and docs/ need updating. Keep usage examples, architecture diagrams, and design decisions current.
- **No backward compatibility shims.** Do not add compatibility wrappers, re-exports, renamed-but-kept-around variables, or `# removed` comments unless explicitly asked. If something is unused, delete it.
- **Add tests with new functionality.** When adding new features or modifying behavior, add or update unit tests to cover the changes. Check existing test files for patterns to follow.
