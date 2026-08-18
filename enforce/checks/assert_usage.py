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
    """Rejects an assertion that is really guarding the outside world.

    Three signals, any one sufficient: the condition calls something that reads
    from outside, it names a parameter of the enclosing function, or its message
    is worded as a refusal to a user rather than a claim about the program.
    """

    ## Invoked as `python -m checks.assert_usage`.
    name = "assert_usage"
    ## The rules this mechanism decides. Findings cite ERR-012, the boundary
    ## half; DIAG-009 is the same prohibition seen from the diagnostics side.
    rules = ("DIAG-009", "ERR-012")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield a finding for each assertion that is load-bearing in production.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer, unused -- `-O` strips assertions
            from every layer alike
        @return one ERR-012 finding per suspect assertion, naming the evidence in
            its message; one per enclosing function for an assertion inside a
            nested one, see `_asserts`
        """
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
        """Decide whether an assertion is validating, and name what gave it away.

        Evidence in the condition outranks evidence in the message, which is
        read only when the condition looks clean -- what a test inspects is
        harder to argue with than how its failure is worded. Within the
        condition the first match in walk order wins, so the phrase names one
        signal and not every signal present.

        @param node the assertion
        @param params the enclosing function's parameters, `self` and `cls` aside
        @return a phrase naming the evidence, or None when it reads as a genuine
            internal impossibility
        """
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
    """Every assertion, paired with the name of its enclosing function.

    An assertion outside every function is skipped entirely, not merely judged on
    less evidence: the parameter signal has nothing to compare against, and the
    other two are never reached either. An assertion inside a nested function is
    reported once per enclosing function, which over-reports rather than losing
    it under the wrong parameter set.

    @param tree the module's syntax tree
    @return each enclosing function's name paired with an assertion inside it
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Assert):
                yield node.name, sub


def _parameters_by_function(tree: ast.Module) -> dict[str, frozenset[str]]:
    """What a caller can control, for every function in a module.

    `self` and `cls` are left out: an assertion about them speaks to the object's
    own state, not to anything supplied from outside. Two functions sharing a
    name -- a method and a free function, an overload pair -- collide, and the
    last definition wins.

    @param tree the module's syntax tree
    @return each function's name mapped to its caller-supplied parameter names
    """
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
    """The bare name invoked, discarding whatever it was reached through.

    `json.loads(...)` and `payload.loads(...)` both answer `loads`, which is what
    lets the table of external calls stay a short list of verbs.

    @param node the call expression
    @return the identifier, or the empty string when the callee is an expression
    """
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    return getattr(func, "attr", "")


def _message_text(node: ast.Assert) -> str:
    """Whatever of an assertion's message is readable without running it.

    An f-string yields only its literal segments, joined by spaces. A message
    whose wording lives entirely in an interpolated value therefore reads as
    empty, and the message signal cannot fire on it.

    @param node the assertion
    @return the literal text, or the empty string for no message, a non-string
        message, or one made only of interpolations
    """
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
