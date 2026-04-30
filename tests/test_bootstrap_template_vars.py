"""BOUQUET_* template vars must be visible inside setup_commands shell."""

from __future__ import annotations

from pathlib import Path

from bouquet.bootstrap import _run_setup_and_capture_env


def test_setup_commands_see_bouquet_template_vars(tmp_path: Path) -> None:
    """setup_commands shell must have BOUQUET_WORKTREE_INDEX and friends in env."""
    marker = tmp_path / "marker.txt"
    commands = [
        f'echo "$BOUQUET_WORKTREE_INDEX" > "{marker}"',
        f'echo "$BOUQUET_WORKTREE_BRANCH" >> "{marker}"',
        f'echo "$BOUQUET_PROJECT_NAME" >> "{marker}"',
    ]
    template_vars = {
        "BOUQUET_WORKTREE_INDEX": 7,
        "BOUQUET_WORKTREE_BRANCH": "feature/parallel",
        "BOUQUET_WORKTREE_PATH": str(tmp_path),
        "BOUQUET_PROJECT_NAME": "glo-arena",
    }

    _run_setup_and_capture_env(commands, cwd=tmp_path, template_vars=template_vars)

    contents = marker.read_text().splitlines()
    assert contents == ["7", "feature/parallel", "glo-arena"]


def test_setup_commands_render_template_placeholders(tmp_path: Path) -> None:
    """setup_commands strings must support {{ BOUQUET_WORKTREE_INDEX }} substitution."""
    marker = tmp_path / "rendered.txt"
    commands = [
        f'echo "{{{{ BOUQUET_WORKTREE_INDEX }}}}" > "{marker}"',
        f'echo "{{{{ 8000 + BOUQUET_WORKTREE_INDEX }}}}" >> "{marker}"',
    ]
    template_vars = {
        "BOUQUET_WORKTREE_INDEX": 3,
        "BOUQUET_WORKTREE_BRANCH": "x",
        "BOUQUET_WORKTREE_PATH": str(tmp_path),
        "BOUQUET_PROJECT_NAME": "x",
    }

    _run_setup_and_capture_env(commands, cwd=tmp_path, template_vars=template_vars)

    assert marker.read_text().splitlines() == ["3", "8003"]


def test_template_vars_do_not_appear_in_env_delta(tmp_path: Path) -> None:
    """BOUQUET_* template vars injected for the shell must not pollute the returned delta."""
    template_vars = {
        "BOUQUET_WORKTREE_INDEX": 5,
        "BOUQUET_WORKTREE_BRANCH": "feature/x",
        "BOUQUET_WORKTREE_PATH": str(tmp_path),
        "BOUQUET_PROJECT_NAME": "myproject",
    }
    # The shell does nothing user-visible -> delta should be empty.
    delta = _run_setup_and_capture_env(["true"], cwd=tmp_path, template_vars=template_vars)
    for key in template_vars:
        assert key not in delta, f"{key} leaked into env delta"
