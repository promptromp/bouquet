# Configuration

Bouquet is configured via a `.bouquet.toml` file in your repository root. Run `bouquet init` to generate a starter template.

**Config search order:** `--config` flag → `.bouquet.toml` in repo root → `~/.config/bouquet/config.toml` → defaults.

## Minimal Example

```toml
[project]
name = "my-project"

[agent]
command = "claude"
```

## Full Example

```toml
[project]
name = "my-project"

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

[[services]]
name = "api"
command = "uv run uvicorn app.main:app --reload --port {{ 8000 + BOUQUET_WORKTREE_INDEX }}"

[[services]]
name = "frontend"
command = "npm run dev -- --port {{ 3000 + BOUQUET_WORKTREE_INDEX }}"

[tmux]
layout = "services-top"

[bootstrap]
python_version = "3.14"
setup_commands = ["echo 'hello'"]
copy_env_files = [".env"]
cow_clone_dirs = [".venv", "node_modules"]
install_commands = ["uv sync"]

[task_queue]
backend = "local"
auto_branch_prefix = "task/"
```

## Sections

### `[project]`

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Project name. Defaults to the repository directory name. |

### `[agent]`

| Key | Type | Description |
|-----|------|-------------|
| `command` | string | Agent CLI command (e.g. `claude`, `aider`, `codex`) |
| `args` | list | Additional arguments passed to the agent command |
| `default_profile` | string | Name of the default agent profile |

### `[[agent.profiles]]`

Named agent configurations so you can switch between agents per worktree.

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Profile name shown in the TUI selector |
| `command` | string | Agent CLI command |
| `args` | list | Additional arguments |

### `[[services]]`

Dev servers that run alongside the agent in each worktree window.

| Key | Type | Description |
|-----|------|-------------|
| `name` | string | Service name (shown in pane title) |
| `command` | string | Shell command to run the service. Supports template expressions. |

### `[tmux]`

| Key | Type | Description |
|-----|------|-------------|
| `layout` | string | Pane layout. `"services-top"` (default) puts services in a row at the top. Any other value is passed to tmux `select-layout`. |

### `[bootstrap]`

| Key | Type | Description |
|-----|------|-------------|
| `python_version` | string | Runs `uv python pin <version>` before dependency installation |
| `setup_commands` | list | Shell commands run before dependency installation. Exported env vars are captured and propagated. |
| `copy_env_files` | list | Files copied from the main repo to the worktree (e.g. `.env`) |
| `cow_clone_dirs` | list | Directories cloned via Copy-on-Write (APFS) instead of full copy |
| `install_commands` | list | Dependency install commands (e.g. `uv sync`, `pnpm install`) |

### `[task_queue]`

| Key | Type | Description |
|-----|------|-------------|
| `backend` | string | `"local"` (SQLite, default) or `"github"` (GitHub Issues) |
| `label_filter` | string | For GitHub backend: only issues with this label appear as tasks (default `"bouquet"`) |
| `auto_branch_prefix` | string | Prefix for auto-generated branch names when picking up tasks |

## Template Variables

Template expressions use `{{ expr }}` syntax with arithmetic support.

| Variable | Type | Example |
|----------|------|---------|
| `BOUQUET_WORKTREE_INDEX` | int | `1`, `2`, `3` |
| `BOUQUET_WORKTREE_BRANCH` | str | `feature/auth` |
| `BOUQUET_WORKTREE_PATH` | str | `/path/to/.bouquet-worktrees/feature-auth` |
| `BOUQUET_PROJECT_NAME` | str | `my-project` |

Example: `{{ 8000 + BOUQUET_WORKTREE_INDEX }}` → `8001` for worktree index 1.
