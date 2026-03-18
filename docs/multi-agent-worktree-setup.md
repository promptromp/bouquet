# Multi-Agent Agentic Coding: Git Worktrees & Isolated Environments

A guide to spawning and managing multiple parallel Claude Code (or similar agentic coding) sessions across isolated git worktrees, with fast environment bootstrapping.

---

## The Conceptual Stack

```
┌─────────────────────────────────────────┐
│         Orchestration Layer             │  ← coordinates agents, tasks, merges
├─────────────────────────────────────────┤
│         Session / Mux Layer             │  ← tmux, process management
├─────────────────────────────────────────┤
│         Isolation Layer                 │  ← git worktrees + env isolation
├─────────────────────────────────────────┤
│         Environment Layer               │  ← venv/node_modules/env vars
└─────────────────────────────────────────┘
```

---

## Layer 1: Isolation — Git Worktrees

The foundation. `git worktree add` gives you a separate working directory per branch, sharing the `.git` object store. Key properties:

- Each worktree has its own `HEAD`, index, and working tree
- They share history and refs — no repo cloning overhead
- You can have unlimited worktrees for a single repo

```bash
# Canonical pattern
git worktree add ../myrepo-feature-foo -b feature/foo
git worktree list  # inspect
git worktree remove ../myrepo-feature-foo  # teardown
```

> **Friction point:** worktrees don't automatically get their own env setup — that's the bootstrapping problem to solve.

---

## Layer 2: Environment Isolation

### `direnv` — per-directory env vars

The standard answer for env var isolation. Drop an `.envrc` in each worktree root:

```bash
# .envrc (auto-loaded/unloaded on cd)
export DATABASE_URL="postgresql://localhost/myapp_feature_foo"
export OPENAI_API_KEY="..."
layout python3  # auto-creates/activates venv
```

With `layout python3` (or `layout node`), direnv handles venv creation and activation transparently.

### `mise` (formerly rtx) — runtime version management

Replaces pyenv + nvm + many others. Per-directory `.mise.toml`:

```toml
[tools]
python = "3.12.3"
node = "22.0.0"

[env]
PYTHONPATH = "src"
```

mise integrates with direnv natively and is faster than asdf. Ensures each worktree pins its runtime versions independently.

### Python venv

If not using direnv's `layout python3`:

```bash
python -m venv .venv  # in worktree root, .gitignored
source .venv/bin/activate
pip install -e ".[dev]"
```

### `.envrc` + `.env` discipline

- `.env.example` committed
- `.env` gitignored, manually maintained
- `.envrc` committed, sources `.env` and sets worktree-specific overrides

---

## Layer 3: Session / Mux Layer

### tmux with named sessions per worktree

```bash
# one session per worktree, named after the branch
tmux new-session -d -s "feat-foo" -c "/path/to/worktree-feat-foo"
tmux send-keys -t "feat-foo" "claude" Enter
```

### `tmuxp` — YAML-driven session templates

```yaml
# .tmuxp/worktree.yaml
session_name: "{{ session_name }}"
start_directory: "{{ worktree_path }}"
windows:
  - window_name: claude
    panes: [claude]
  - window_name: shell
    panes: [""]
  - window_name: logs
    panes: ["tail -f logs/dev.log"]
```

---

## Layer 4: Orchestration

### `claude-squad`

Most purpose-built tool for this use case. Manages multiple Claude Code instances across git worktrees with tmux, with a TUI for monitoring. Think of it as a Claude-specific process supervisor with worktree lifecycle management.

```bash
squad start  # spawns agent in new worktree
squad list   # see all running agents + their branches
```

### Claude Code's native subagent model

Claude Code has a `Task` tool that lets an orchestrator Claude spawn subagents:

```
Orchestrator Claude (high-level planning)
  ├── Task → Agent A (worktree-a, feature branch)
  ├── Task → Agent B (worktree-b, different concern)
  └── Task → Agent C (worktree-c, tests/review)
```

The orchestrator doesn't touch code — it decomposes and coordinates. Drivable programmatically via the Claude Code SDK.

### Homegrown orchestration script

```python
#!/usr/bin/env python3
"""Worktree bootstrapper for multi-agent Claude Code sessions."""

import subprocess
import shutil
from pathlib import Path
from dataclasses import dataclass

@dataclass
class WorktreeSpec:
    branch: str
    task_description: str
    base_branch: str = "main"

def bootstrap_worktree(repo_root: Path, spec: WorktreeSpec) -> Path:
    worktree_path = repo_root.parent / f"{repo_root.name}-{spec.branch.replace('/', '-')}"

    # 1. Create worktree
    subprocess.run([
        "git", "worktree", "add", str(worktree_path), "-b", spec.branch
    ], cwd=repo_root, check=True)

    # 2. Copy env files (never committed)
    for env_file in [".env", ".env.local"]:
        src = repo_root / env_file
        if src.exists():
            shutil.copy(src, worktree_path / env_file)

    # 3. Install dependencies (fast if using uv/pnpm with shared cache)
    subprocess.run(["uv", "sync"], cwd=worktree_path, check=True)
    subprocess.run(["pnpm", "install"], cwd=worktree_path, check=True)

    # 4. Spawn tmux session
    session = spec.branch.replace("/", "-")
    subprocess.run([
        "tmux", "new-session", "-d", "-s", session, "-c", str(worktree_path)
    ])
    subprocess.run([
        "tmux", "send-keys", "-t", session,
        f'claude --task "{spec.task_description}"', "Enter"
    ])

    return worktree_path
```

### Other practical considerations

- **Shared vs. isolated services:** Share Docker Compose services (Postgres, Redis) with per-worktree databases/namespaces; isolate the app process, venv, and node_modules.
- **Port management:** Each dev server needs its own port. Assign port ranges by convention (e.g. worktree index × 1000 + base port) or use a port allocator.
- **Merge strategy:** Agents don't coordinate on conflicts automatically — keep a human or orchestrator in the loop before merging parallel branches.

---

## Fast Environment Cloning: Avoiding Re-Installation

### The Core Insight

Maintain a canonical "golden" env, then **clone it** rather than installing fresh per worktree.

### macOS APFS: `cp -c` (clonefile CoW)

Uses the `clonefile(2)` syscall — creates a Copy-on-Write clone at the filesystem level. Cost is essentially zero until pages are actually written.

```bash
cp -Rc /path/to/main-worktree/node_modules /path/to/new-worktree/node_modules
cp -Rc /path/to/main-worktree/.venv        /path/to/new-worktree/.venv
```

After clone, run a quick `npm ci --prefer-offline` or `uv sync --frozen` to catch lockfile drift — nearly always a no-op.

**Caveat:** Python venvs embed absolute paths in `pyvenv.cfg`. Use `uv venv --relocatable` or just re-run `uv sync --frozen` (sub-second with warm cache).

### Linux: `cp --reflink` (btrfs / XFS)

```bash
cp --reflink=auto -r node_modules /path/to/new-worktree/node_modules
cp --reflink=auto -r .venv        /path/to/new-worktree/.venv
```

`--reflink=auto` falls back to a regular copy on non-supporting filesystems (ext4 doesn't support it; btrfs/XFS do).

### Hardlinks: `cp -rl`

Works on any filesystem. pnpm already does this internally via its content-addressable store (`~/.pnpm-store`).

```bash
cp -rl /main-worktree/node_modules /new-worktree/node_modules
```

> **Warning:** A write to a hardlinked file modifies it in *all* locations. Safe for `node_modules` since you're not editing package source, but be aware. Clonefiles/reflinks are strictly safer.

### Symlink the Entire Directory

Simplest approach if worktrees share the same dep tree (branches haven't diverged on deps):

```bash
ln -s /main-worktree/node_modules /new-worktree/node_modules
ln -s /main-worktree/.venv        /new-worktree/.venv
```

Detect lockfile drift and promote to a full clone when needed:

```bash
if diff -q main-worktree/package-lock.json new-worktree/package-lock.json > /dev/null; then
    ln -s ...              # safe to symlink
else
    cp -Rc ... && npm ci --prefer-offline  # needs own copy
fi
```

### `uv` — Already CoW-Aware

`uv` is designed for this use case:

- Global content-addressed cache at `~/.cache/uv` — packages stored once, hard-linked into venvs
- `uv sync --frozen` with warm cache typically runs in < 1 second (validation only)
- `uv venv --relocatable` makes venvs path-independent so CoW clones just work

```bash
# Bootstrap once in main worktree
uv sync

# In new worktree: clone then validate (sub-second)
cp -Rc ../main-worktree/.venv .venv
uv sync --frozen  # validates, installs any delta only
```

### Nix / devenv / devbox: The Nuclear Option

If willing to invest in setup, Nix gives you a single content-addressed store (`/nix/store`) with zero per-worktree overhead. Environments are just sets of symlinks into the store.

```nix
# devenv.nix — shared across all worktrees of a project
{ pkgs, ... }: {
  languages.python.enable = true;
  languages.python.version = "3.12";
  languages.javascript.enable = true;
  packages = [ pkgs.redis ];
}
```

`devenv shell` in any worktree gives you the same env, near-instantly, with no copying at all. Tradeoff: Nix learning curve and imperfect compatibility with arbitrary pip/npm packages.

`devbox` (Nix under the hood, friendlier API) or `mise` with a shared tool cache are lighter-weight alternatives.

---

## Complete Bootstrap Script

```bash
#!/usr/bin/env bash
# new-worktree.sh — fast worktree bootstrap using CoW cloning

set -euo pipefail

REPO_ROOT="$(git rev-parse --show-toplevel)"
BRANCH="${1:?Usage: new-worktree.sh <branch-name>}"
WORKTREE_PATH="${REPO_ROOT}/../$(basename "$REPO_ROOT")-${BRANCH//\//-}"
CANONICAL_WORKTREE="${REPO_ROOT}"  # main worktree is the golden env

git worktree add "$WORKTREE_PATH" -b "$BRANCH"

# CoW clone deps — clonefile on macOS, reflink on Linux
clone_dir() {
    local src="$1" dst="$2"
    if [[ "$OSTYPE" == darwin* ]]; then
        cp -Rc "$src" "$dst"
    else
        cp --reflink=auto -r "$src" "$dst"
    fi
}

# Clone node_modules if lockfile matches canonical
if [[ -f "$WORKTREE_PATH/package-lock.json" ]] && \
   diff -q "$CANONICAL_WORKTREE/package-lock.json" \
           "$WORKTREE_PATH/package-lock.json" &>/dev/null; then
    clone_dir "$CANONICAL_WORKTREE/node_modules" "$WORKTREE_PATH/node_modules"
else
    (cd "$WORKTREE_PATH" && pnpm install --prefer-offline)
fi

# Clone .venv if lockfile matches
if [[ -f "$WORKTREE_PATH/uv.lock" ]] && \
   diff -q "$CANONICAL_WORKTREE/uv.lock" "$WORKTREE_PATH/uv.lock" &>/dev/null; then
    clone_dir "$CANONICAL_WORKTREE/.venv" "$WORKTREE_PATH/.venv"
    (cd "$WORKTREE_PATH" && uv sync --frozen)  # validate + patch any delta
else
    (cd "$WORKTREE_PATH" && uv sync)
fi

# Copy non-committed env files
for f in .env .env.local; do
    [[ -f "$CANONICAL_WORKTREE/$f" ]] && cp "$CANONICAL_WORKTREE/$f" "$WORKTREE_PATH/$f"
done

# Spawn tmux session
SESSION="${BRANCH//\//-}"
tmux new-session -d -s "$SESSION" -c "$WORKTREE_PATH"
tmux send-keys -t "$SESSION" "claude" Enter

echo "✓ Worktree at $WORKTREE_PATH, tmux session: $SESSION"
```

The **lockfile diff check** is the key gate — if lockfiles match, CoW clone is safe and validation is near-instant. If they diverge, fall back to a proper install (still fast with warm caches).

---

## Recommended Starting Point

1. **`direnv` + `mise`** — env/runtime isolation (set up first, foundational)
2. **`uv`** for Python deps, **`pnpm`** for Node (fast installs + warm-cache validation)
3. **`claude-squad`** — orchestration wrapper for Claude Code sessions
4. The bootstrap script above — wraps worktree creation, CoW cloning, env file copy, and tmux session launch

Evolve toward a richer orchestration layer (Python bootstrapper, Claude Code subagent delegation) as your patterns solidify.
