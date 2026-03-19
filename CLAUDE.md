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
       ├─► github.py      gh CLI wrapper for PR URL lookup
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
- **Activity polling** — `ActivityMonitor` runs every 2s in the TUI via `set_interval` + `@work(thread=True)`. SHA256 hashing of pane content; hash change → RUNNING, stable 3+ polls → IDLE (or WAITING if a permission prompt is detected).
- **Agent profiles** — `AgentConfig.resolve_profile(name)` resolves a named profile or falls back to the top-level `command`/`args`. Backward-compatible: old configs without `profiles` work unchanged.
- **Bootstrap setup commands** — `BootstrapConfig.setup_commands` runs shell commands in a single bash context before dependency installation. Env vars exported by these commands are captured (via a `python3` JSON dump to a temp file — portable across macOS/Linux) and propagated to deps install subprocesses and the tmux session (via `set_environment`). Use case: private registry auth (e.g. AWS CodeArtifact tokens).
- **Bootstrap python_version** — Optional `BootstrapConfig.python_version` runs `uv python pin <version>` in the worktree before dependency installation. Ensures consistent Python version across worktrees regardless of what's available on the system.
- **GitHub PR lookup** — `github.py` is a thin `gh` CLI wrapper (same pattern as `git.py`). PR URLs are cached per branch in `WorktreeDetailPanel._pr_cache` (simple dict, no TTL). The `gh` CLI is optional — missing `gh` degrades gracefully with no PR field shown and no error. Lookups run in a `@work(thread=True, group="pr-lookup")` worker so rapid cursor movement cancels stale lookups. PR links use Rich `[link=URL]` markup (OSC 8 terminal hyperlinks).
- **services-top layout** — Default tmux layout (`TmuxConfig.layout = "services-top"`). Arranges service panes in an equal-width horizontal row across the top (~40%) with the agent pane spanning full width at the bottom (~60%). Implemented via custom splits in `TmuxManager._setup_services_top()`, not a tmux built-in layout. Any other layout value is passed through to `select_layout` as a standard tmux layout name.

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
- No interactive tmux or TUI rendering tests — TUI is tested at widget/data level only

## Important Instructions

- **Update docs after major changes.** After adding or changing functionality, check if README.md, CLAUDE.md, and docs/ need updating. Keep usage examples, architecture diagrams, and design decisions current.
- **No backward compatibility shims.** Do not add compatibility wrappers, re-exports, renamed-but-kept-around variables, or `# removed` comments unless explicitly asked. If something is unused, delete it.
- **Add tests with new functionality.** When adding new features or modifying behavior, add or update unit tests to cover the changes. Check existing test files for patterns to follow.
