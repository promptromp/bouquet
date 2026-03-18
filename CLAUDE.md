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
CLI (Click) → bouquet start/stop/init
  └─► WorktreeManager (worktree.py — glue layer)
       ├─► git.py         subprocess calls for worktree CRUD
       ├─► tmux.py        libtmux wrapper for session/window lifecycle
       ├─► bootstrap.py   env file copy, CoW clone .venv/node_modules, dep install
       └─► TUI (tui/app.py — Textual app in tmux window 0)
            └─► spawns worktree windows via WorktreeManager
```

**Key flow:** `bouquet start` creates a tmux session, launches the TUI in window 0, then the TUI drives `WorktreeManager.create()` which chains git worktree creation → bootstrap → tmux window → agent launch via `send_keys`.

**The TUI runs inside tmux** but controls tmux via libtmux's server socket API (no terminal conflict). Switching to a worktree window hides the TUI; return with `Ctrl-b 0`.

## Key Design Decisions

- **`git.py` strips `GIT_*` env vars** (`_clean_env()`) before subprocess calls. This prevents pre-commit hook context from leaking into worktree operations. Do not remove this.
- **TUI uses `@work(thread=True)`** for create/remove operations to avoid blocking the Textual event loop. Use `self.call_from_thread()` to update UI from workers.
- **State persists to `~/.local/state/bouquet/{project}.json`** so `bouquet stop` can clean up even if the TUI crashes.
- **Bootstrap errors are suppressed** (`contextlib.suppress`) — partial setup is acceptable when tools are missing.
- **Worktree paths** are computed as `{repo_parent}/.bouquet-worktrees/{branch-with-slashes-replaced}`.

## Configuration

Config search order: `--config` flag → `.bouquet.toml` in repo root → `~/.config/bouquet/config.toml` → defaults. All config models are Pydantic v2 in `config.py`.

## Code Style

- Line length: 120, target Python 3.12
- Ruff rules: E, F, UP, B, SIM, I, PLC
- Double quotes, isort with `combine-as-imports`, 2 blank lines after imports
- First-party package: `bouquet`

## Testing Patterns

- `tmp_git_repo` fixture creates a real git repo with initial commit in a temp dir
- `mock_tmux` fixture (MagicMock) avoids real tmux dependency in WorktreeManager tests
- Tests that monkeypatch `SessionState.state_dir` redirect state persistence to temp dirs
- No interactive tmux or TUI rendering tests — TUI is tested at widget/data level only
