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

* direnv (on macOS `brew install direnv`)
* tmux (on macOS `brew install tmux`)
* tmuxinator (on macOS `brew install tmuxinator`)
* relevant languages package managers (e.g. `uv`, `pnpm`)


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

