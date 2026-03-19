"""Safe template rendering for service commands.

Supports ``{{ expr }}`` placeholders where *expr* may reference known
variables and use basic arithmetic (``+``, ``-``, ``*``).  No function
calls, attribute access, or imports are allowed.
"""

from __future__ import annotations

import ast
import re
from typing import Any


class TemplateError(Exception):
    """Raised when template rendering fails."""


# AST node types we allow inside {{ }} expressions.
_SAFE_NODES = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.UnaryOp,
    ast.USub,
)

_TEMPLATE_RE = re.compile(r"\{\{(.+?)\}\}")


def _safe_eval(expr: str, variables: dict[str, Any]) -> Any:
    """Evaluate *expr* in a restricted context allowing only arithmetic on known variables."""
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise TemplateError(f"Invalid template expression: {expr!r}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            raise TemplateError(f"Disallowed construct in template expression: {ast.dump(node)}")

    # Only expose the provided variables — no builtins.
    try:
        return eval(compile(tree, "<template>", "eval"), {"__builtins__": {}}, variables)  # noqa: S307
    except NameError as exc:
        raise TemplateError(f"Unknown variable in template expression: {exc}") from exc
    except Exception as exc:
        raise TemplateError(f"Error evaluating template expression {expr!r}: {exc}") from exc


def render_template(template: str, variables: dict[str, Any]) -> str:
    """Replace all ``{{ expr }}`` placeholders in *template* with evaluated results."""

    def _replace(match: re.Match[str]) -> str:
        return str(_safe_eval(match.group(1), variables))

    return _TEMPLATE_RE.sub(_replace, template)
