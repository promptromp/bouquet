"""Shared test fixtures."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

import bouquet.models as models_mod
from bouquet.config import BouquetSettings
from bouquet.tasks.local import LocalBackend


@pytest.fixture
def tmp_git_repo(tmp_path: Path) -> Path:
    """Create a temporary git repository with an initial commit."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "main"], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    # Create initial commit so we have a branch
    readme = repo / "README.md"
    readme.write_text("# Test Repo\n")
    subprocess.run(["git", "add", "."], cwd=repo, capture_output=True, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial commit"],
        cwd=repo,
        capture_output=True,
        check=True,
    )
    return repo


@pytest.fixture
def sample_settings(tmp_git_repo: Path) -> BouquetSettings:
    """Return a BouquetSettings configured for the temp repo."""
    settings = BouquetSettings()
    settings.project.name = "test-project"
    settings.project.repo_path = str(tmp_git_repo)
    settings.project.base_branch = "main"
    return settings


@pytest.fixture
def mock_state_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect SessionState.state_dir to a temp directory."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    monkeypatch.setattr(
        models_mod.SessionState,
        "state_dir",
        classmethod(lambda cls: state_dir),
    )
    return state_dir


@pytest.fixture
def local_backend(tmp_path: Path) -> LocalBackend:
    """Return a LocalBackend backed by a temp SQLite database."""
    return LocalBackend(db_path=str(tmp_path / "tasks.db"))


@pytest.fixture
def bouquet_toml(tmp_git_repo: Path) -> Path:
    """Write a .bouquet.toml in the temp repo and return its path."""
    config = tmp_git_repo / ".bouquet.toml"
    config.write_text("""\
[project]
name = "my-test-project"
repo_path = "."
base_branch = "main"

[project.languages]
python = true
javascript = false

[agent]
command = "echo"
args = ["hello"]

[bootstrap]
copy_env_files = []
python_deps_command = ""
node_deps_command = ""
use_cow_clone = false
direnv_allow = false

[tmux]
session_prefix = "bouquet"
""")
    return config
