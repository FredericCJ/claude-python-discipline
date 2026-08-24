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
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered external-call set whose each terminal name element marks outside input.
EXTERNAL_CALLS = frozenset({
    "input", "getenv", "environ", "loads", "load", "read", "read_text",
    "read_bytes", "get", "json", "parse", "recv", "readline", "readlines",
})

## Unordered validation-word set whose each element marks a user-facing refusal message.
VALIDATION_WORDS = frozenset({
    "must", "required", "invalid", "expected", "missing", "provide",
    "permission", "denied", "unauthorized", "forbidden", "allowed",
})


class AssertUsageCheck(ModuleCheck):
    """Rejects an assertion that is really guarding the outside world.

    Three signals, any one sufficient: the condition calls something that reads
    from outside, it names a parameter of the enclosing function, or its message
    is worded as a refusal to a user rather than a claim about the program.
    """

    ## Invoked as `python -m checks.assert_usage`.
    name = "assert_usage"
    ## The rules this mechanism decides, and it now REPORTS both. `ERR-012` is
    ## the boundary half and `DIAG-009` the diagnostics half of one prohibition;
    ## claiming both while emitting one left `DIAG-009` decided by nothing.
    ## Rule-id elements in deterministic reporting order actually emitted for each defect.
    rules = ("DIAG-009", "ERR-012")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield a finding for each assertion that is load-bearing in production.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- `-O` strips assertions
            from every layer alike
        @return finding elements in enclosing-function then assertion and rule order; each
            suspect assertion yields ``ERR-012`` then ``DIAG-009`` per enclosing function
        """
        # Tests legitimately use assertions as their executable oracle mechanism.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Map each function-name key to its unordered caller-parameter value set; last wins.
        params = _parameters_by_function(tree)
        # Inspect each enclosing-function/assertion pair in deterministic nested walk order.
        for func, node in _asserts(tree):
            # Select the first reliable validation signal under the enclosing parameter set.
            reason = self._why_suspect(node, params.get(func, frozenset()))
            # A suspect assertion violates both runtime presence and diagnostic obligations.
            if reason is not None:
                # Both ids, not one. `DIAG-009` and `ERR-012` are the same
                # prohibition from two sides, and the tuple above claimed both
                # while only `ERR-012` was ever emitted -- so `DIAG-009` was
                # counted decided and a reader grepping for it found nothing.
                # A finding should name every contract it breaks; that is what
                # makes it repairable from the output alone.
                # Emit each broken rule-id element in stable repair-oriented order.
                for rule_id in ("ERR-012", "DIAG-009"):
                    # Yield the rule-specific finding with the same concrete syntax evidence.
                    yield Finding(
                        rule_id, path, node.lineno,
                        f"assertion is validating {reason}",
                        "Make it an ordinary check returning a typed error; assertions "
                        "vanish under `python -O` and this one would cease to exist.",
                    )

    def _why_suspect(self, node: ast.Assert, params: frozenset[str]) -> str | None:
        """Decide whether an assertion is validating, and name what gave it away.

        Evidence in the condition outranks evidence in the message, which is
        read only when the condition looks clean -- what a test inspects is
        harder to argue with than how its failure is worded. Within the
        condition the first match in walk order wins, so the phrase names one
        signal and not every signal present.

        @param node the assertion
        @param params unordered set whose each element is an enclosing caller parameter,
            excluding ``self`` and ``cls``
        @return a phrase naming the evidence, or None when it reads as a genuine
            internal impossibility
        """
        # Inspect each condition syntax-node element in deterministic AST walk order.
        for sub in ast.walk(node.test):
            # Calls may directly read values from an external boundary.
            if isinstance(sub, ast.Call):
                # Resolve the terminal called identifier for closed-set matching.
                name = _call_name(sub)
                # A recognized reader proves the assertion validates outside input.
                if name in EXTERNAL_CALLS:
                    # Return the highest-precedence call-based evidence phrase.
                    return f"a value read from outside (`{name}`)"
            # A named caller parameter is itself external to the function's invariants.
            if isinstance(sub, ast.Name) and sub.id in params:
                # Return the first parameter-based evidence phrase in walk order.
                return f"a parameter (`{sub.id}`)"
        # Extract statically readable literal assertion-message text.
        message = _message_text(node)
        # Build an unordered set whose each element is a validation word in the message.
        hit = VALIDATION_WORDS & set(message.lower().replace(",", " ").split())
        # User-facing refusal vocabulary is the lowest-precedence validation signal.
        if hit:
            # Return the lexically first signal for deterministic wording.
            return f"input, judging by its message ({min(hit)!r})"
        # No reliable condition or message signal distinguishes this from an invariant.
        return None


def _asserts(tree: ast.Module) -> Iterator[tuple[str, ast.Assert]]:
    """Every assertion, paired with the name of its enclosing function.

    An assertion outside every function is skipped entirely, not merely judged on
    less evidence: the parameter signal has nothing to compare against, and the
    other two are never reached either. An assertion inside a nested function is
    reported once per enclosing function, which over-reports rather than losing
    it under the wrong parameter set.

    @param tree the module's syntax tree
    @return function-name/assertion pair elements in enclosing then nested AST walk order
    """
    # Inspect each syntax-node element in deterministic module walk order.
    for node in ast.walk(tree):
        # Only functions establish caller-controlled parameter context.
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Advance without pairing module-level assertions.
            continue
        # Inspect each nested syntax-node element in deterministic function walk order.
        for sub in ast.walk(node):
            # Pair every nested assertion with this enclosing function identity.
            if isinstance(sub, ast.Assert):
                # Yield the context/assertion pair at its walk position.
                yield node.name, sub


def _parameters_by_function(tree: ast.Module) -> dict[str, frozenset[str]]:
    """What a caller can control, for every function in a module.

    `self` and `cls` are left out: an assertion about them speaks to the object's
    own state, not to anything supplied from outside. Two functions sharing a
    name -- a method and a free function, an overload pair -- collide, and the
    last definition wins.

    @param tree the module's syntax tree
    @return mapping from each function-name key to its unordered caller-parameter value set;
        insertion order follows first definition and the last duplicate value wins
    """
    # Map each function-name key to its caller-parameter set in first-definition order.
    result: dict[str, frozenset[str]] = {}
    # Inspect each syntax-node element in deterministic module walk order.
    for node in ast.walk(tree):
        # Only function definitions own caller-supplied parameters.
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            # Skip non-callable syntax because it owns no caller-supplied parameters.
            continue
        # Select the complete Python argument declaration.
        args = node.args
        # Build an unordered set whose each element is a caller-controlled parameter name.
        names = {
            a.arg
            for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)
            if a.arg not in {"self", "cls"}
        }
        # Publish the immutable parameter set under function identity; a later duplicate wins.
        result[node.name] = frozenset(names)
    # Return the complete function-to-parameter mapping.
    return result


def _call_name(node: ast.Call) -> str:
    """The bare name invoked, discarding whatever it was reached through.

    `json.loads(...)` and `payload.loads(...)` both answer `loads`, which is what
    lets the table of external calls stay a short list of verbs.

    @param node the call expression
    @return the identifier, or the empty string when the callee is an expression
    """
    # Select the called expression without attempting import resolution.
    func = node.func
    # Bare function names expose their complete called identifier.
    if isinstance(func, ast.Name):
        # Return the bare lexical name.
        return func.id
    # Return a terminal attribute or empty text for another callee expression.
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
    # A literal string message is completely statically readable.
    if isinstance(node.msg, ast.Constant) and isinstance(node.msg.value, str):
        # Return the exact literal message text.
        return node.msg.value
    # An f-string exposes only its ordered constant text segments without execution.
    if isinstance(node.msg, ast.JoinedStr):
        # Join each literal segment element in source order with an explicit separator.
        return " ".join(
            v.value for v in node.msg.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    # Missing and dynamically produced messages expose no reliable wording signal.
    return ""


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(AssertUsageCheck()))
