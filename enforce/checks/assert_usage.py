"""Assertions guard internal invariants, never anything that must run in production.

Enforces DIAG-009 and ERR-012.

Assertions are removed under optimized bytecode. A boundary check written as one
is unguarded in exactly the deployment that removed it -- a correctness hole and
a security hole at once, and one that emits nothing when it opens.

The heuristic: an assertion whose condition mentions a value that entered from
outside the function is validation wearing an assertion's clothes.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from . import Check, Finding, is_test_path, main

## Calls that mean "this value came from outside" -- if one appears in an
## assertion's condition, the assertion is validating external input.
EXTERNAL_CALLS = frozenset({
    "input", "getenv", "environ", "loads", "load", "read", "read_text",
    "read_bytes", "get", "json", "parse", "recv", "readline", "readlines",
})

## Words in the assertion message that mark it as a user-facing refusal rather
## than an internal impossibility.
VALIDATION_WORDS = frozenset({
    "must", "required", "invalid", "expected", "missing", "provide",
    "permission", "denied", "unauthorized", "forbidden", "allowed",
})


class AssertUsageCheck(Check):
    name = "assert_usage"
    rules = ("DIAG-009", "ERR-012")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        if is_test_path(path):
            return
        params = _parameters_by_function(tree)
        for func, node in _asserts(tree):
            reason = self._why_suspect(node, params.get(func, frozenset()))
            if reason is not None:
                yield Finding(
                    "ERR-012", path, node.lineno,
                    f"assertion is validating {reason}",
                    "Make it an ordinary check returning a typed error; assertions vanish "
                    "under `python -O` and this one would cease to exist.",
                )

    def _why_suspect(self, node: ast.Assert, params: frozenset[str]) -> str | None:
        for sub in ast.walk(node.test):
            if isinstance(sub, ast.Call):
                name = _call_name(sub)
                if name in EXTERNAL_CALLS:
                    return f"a value read from outside (`{name}`)"
            if isinstance(sub, ast.Name) and sub.id in params:
                return f"a parameter (`{sub.id}`)"
        message = _message_text(node)
        hit = VALIDATION_WORDS & set(message.lower().replace(",", " ").split())
        if hit:
            return f"input, judging by its message ({sorted(hit)[0]!r})"
        return None


def _asserts(tree: ast.Module) -> Iterator[tuple[str, ast.Assert]]:
    """Every assertion, paired with the name of its enclosing function."""
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert):
                yield node.name, sub


def _parameters_by_function(tree: ast.Module) -> dict[str, frozenset[str]]:
    result: dict[str, frozenset[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        args = node.args
        names = {
            a.arg
            for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            if a.arg not in {"self", "cls"}
        }
        result[node.name] = frozenset(names)
    return result


def _call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return getattr(func, "attr", "")


def _message_text(node: ast.Assert) -> str:
    if isinstance(node.msg, ast.Constant) and isinstance(node.msg.value, str):
        return node.msg.value
    if isinstance(node.msg, ast.JoinedStr):
        return " ".join(
            v.value for v in node.msg.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    return ""


if __name__ == "__main__":
    raise SystemExit(main(AssertUsageCheck()))
