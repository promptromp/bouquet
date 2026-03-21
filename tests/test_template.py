"""Tests for the safe template engine."""

from __future__ import annotations

import pytest

from bouquet.template import TemplateError, render_template


VARIABLES = {
    "BOUQUET_WORKTREE_INDEX": 3,
    "BOUQUET_WORKTREE_BRANCH": "feature/auth",
    "BOUQUET_WORKTREE_PATH": "/wt/feature-auth",
    "BOUQUET_PROJECT_NAME": "myproject",
}


# --- basic substitution ---


def test_simple_variable() -> None:
    assert render_template("{{ BOUQUET_WORKTREE_INDEX }}", VARIABLES) == "3"


def test_string_variable() -> None:
    assert render_template("branch={{ BOUQUET_WORKTREE_BRANCH }}", VARIABLES) == "branch=feature/auth"


def test_no_placeholders() -> None:
    assert render_template("plain command", VARIABLES) == "plain command"


def test_multiple_placeholders() -> None:
    tpl = "{{ BOUQUET_PROJECT_NAME }}:{{ BOUQUET_WORKTREE_INDEX }}"
    assert render_template(tpl, VARIABLES) == "myproject:3"


# --- arithmetic ---


def test_addition() -> None:
    assert render_template("--port {{ 8000 + BOUQUET_WORKTREE_INDEX }}", VARIABLES) == "--port 8003"


def test_subtraction() -> None:
    assert render_template("{{ BOUQUET_WORKTREE_INDEX - 1 }}", VARIABLES) == "2"


def test_multiplication() -> None:
    assert render_template("{{ BOUQUET_WORKTREE_INDEX * 10 }}", VARIABLES) == "30"


def test_negative_unary() -> None:
    assert render_template("{{ -BOUQUET_WORKTREE_INDEX }}", VARIABLES) == "-3"


def test_compound_arithmetic() -> None:
    assert render_template("{{ 3000 + BOUQUET_WORKTREE_INDEX * 10 }}", VARIABLES) == "3030"


# --- safety ---


def test_rejects_function_call() -> None:
    with pytest.raises(TemplateError, match="Disallowed"):
        render_template("{{ print(1) }}", VARIABLES)


def test_rejects_import() -> None:
    with pytest.raises(TemplateError, match="Disallowed|Invalid"):
        render_template("{{ __import__('os') }}", VARIABLES)


def test_rejects_attribute_access() -> None:
    with pytest.raises(TemplateError, match="Disallowed"):
        render_template("{{ BOUQUET_WORKTREE_PATH.__class__ }}", VARIABLES)


def test_rejects_subscript() -> None:
    with pytest.raises(TemplateError, match="Disallowed"):
        render_template("{{ BOUQUET_WORKTREE_PATH[0] }}", VARIABLES)


def test_rejects_lambda() -> None:
    with pytest.raises(TemplateError, match="Disallowed|Invalid"):
        render_template("{{ (lambda: 1)() }}", VARIABLES)


def test_unknown_variable() -> None:
    with pytest.raises(TemplateError, match="Unknown variable"):
        render_template("{{ UNKNOWN }}", {})


def test_syntax_error() -> None:
    with pytest.raises(TemplateError, match="Invalid"):
        render_template("{{ 1 + }}", VARIABLES)


# --- edge cases ---


def test_empty_template() -> None:
    assert render_template("", VARIABLES) == ""


def test_whitespace_in_expression() -> None:
    assert render_template("{{  BOUQUET_WORKTREE_INDEX  }}", VARIABLES) == "3"


def test_expression_embedded_in_command() -> None:
    tpl = "uvicorn app:main --port {{ 8000 + BOUQUET_WORKTREE_INDEX }} --reload"
    assert render_template(tpl, VARIABLES) == "uvicorn app:main --port 8003 --reload"


# --- zero-value index ---


def test_zero_index_variable() -> None:
    variables = {**VARIABLES, "BOUQUET_WORKTREE_INDEX": 0}
    assert render_template("{{ BOUQUET_WORKTREE_INDEX }}", variables) == "0"


def test_zero_index_in_arithmetic() -> None:
    variables = {**VARIABLES, "BOUQUET_WORKTREE_INDEX": 0}
    assert render_template("{{ 8000 + BOUQUET_WORKTREE_INDEX }}", variables) == "8000"
