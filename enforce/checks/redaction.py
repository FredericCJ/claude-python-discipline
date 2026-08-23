"""Secrets and personal data never reach a log or a diagnostic envelope.

Enforces `DIAG-014`. The rule sits awkwardly beside everything else in
`law/DIAG`, which spends its length arguing that an error should carry *more*
detail: the offending value, the expectation, what was seen. This is the one
place that pulls the other way, and it wins where the two meet.

The failure is quiet and permanent. A credential interpolated into a log line is
in the log aggregator, the backup and whatever shipped the backup, and the fix is
not a code change but a rotation. An envelope's `value` field is exactly where it
happens, because that field is *for* the offending input.

**What this decides and what it does not.** It decides that a value whose *name*
says it is a secret is not passed to a logger or written into an envelope-shaped
dictionary. It cannot decide that a value named `payload` is not a token. Naming
is the only signal available to a syntax tree, which is why `DIAG-014` also keeps
a reviewer.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Identifier fragments that name something which must not be recorded. Matched
## on word parts so `api_key`, `authToken` and `user_password` all land.
SECRET_WORDS = re.compile(
    r"(password|passwd|secret|token|credential|api[_-]?key|apikey|private[_-]?key"
    r"|authorization|auth[_-]?header|session[_-]?id|ssn|passphrase)",
    re.IGNORECASE,
)

## Unordered logger-method set whose each element emits a record.
EMITTERS = frozenset({"debug", "info", "warning", "warn", "error", "critical",
                      "exception", "fatal", "log"})

## Unordered envelope-field set whose each key element carries a value verbatim.
VERBATIM_FIELDS = frozenset({"value", "actual", "detail", "input", "argument"})


class RedactionCheck(ModuleCheck):
    """Reports a secret-named value passed to a logger or placed in an envelope."""

    ## Invoked as `python -m checks.redaction`.
    name = "redaction"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("DIAG-014",)

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for secrets reaching a log or an envelope.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- the rule binds everywhere
        @return finding elements in AST walk order, one per exposure
        """
        # Tests may intentionally construct secret-shaped counterexamples.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Logging calls expose every secret-looking identifier reachable in arguments.
            if isinstance(node, ast.Call) and _is_log_call(node):
                # Yield log-exposure findings in sorted identifier order.
                yield from self._logged(node, path)
            # Dictionary literals may be diagnostic envelopes carrying verbatim values.
            elif isinstance(node, ast.Dict):
                # Yield envelope-exposure findings in field then sorted identifier order.
                yield from self._envelope(node, path)

    def _logged(self, node: ast.Call, path: Path) -> Iterator[Finding]:
        """Report a secret-named value handed to a logger.

        @param node the logging call
        @param path the file it came from
        @return finding elements in sorted identifier order, one per secret in the call
        """
        # Sort each discovered secret-name element for deterministic diagnostics.
        for name in sorted(_secret_names(node)):
            # Yield the log-exposure finding at the enclosing call line.
            yield Finding(
                "DIAG-014", path, node.lineno,
                f"`{name}` is passed to a logger",
                "Redact it before it is recorded. A credential in a log is in the "
                "aggregator and every backup of it, and the remedy is a rotation "
                "rather than a code change.",
            )

    def _envelope(self, node: ast.Dict, path: Path) -> Iterator[Finding]:
        """Report a secret-named value assigned to a verbatim envelope field.

        @param node the dictionary literal
        @param path the file it came from
        @return finding elements in field then sorted identifier order, one per exposure
        """
        # Pair each dictionary key/value element in authored field order.
        for key, value in zip(node.keys, node.values, strict=False):
            # Only literal string keys can match a stable envelope field identity.
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                # Advance without guessing a computed field's semantic role.
                continue
            # Fields outside the verbatim set are not claimed by this narrow predicate.
            if key.value not in VERBATIM_FIELDS:
                # Advance to the next authored field pair.
                continue
            # Sort each secret-name element reachable from the verbatim value expression.
            for name in sorted(_secret_names(value)):
                # Yield the envelope exposure at the enclosing dictionary line.
                yield Finding(
                    "DIAG-014", path, node.lineno,
                    f"`{name}` is written into the envelope's `{key.value}` field",
                    "That field is carried verbatim to whoever reads the error. "
                    "Redact the value and keep its shape -- a length, a prefix, a "
                    "hash -- which is what a diagnosis actually needs.",
                )


def _is_log_call(node: ast.Call) -> bool:
    """Whether a call emits a log record.

    @param node the call expression
    @return true when it calls a logging level on some object; false otherwise
    """
    # Match a method-style call whose terminal attribute belongs to the emitter set.
    return isinstance(node.func, ast.Attribute) and node.func.attr in EMITTERS


def _secret_names(node: ast.AST) -> set[str]:
    """Every secret-looking identifier reachable from an expression.

    Reads bare names and attribute tails alike, so `password` and
    `credentials.token` both surface.

    @param node the expression to scan
    @return unordered set whose each element is an offending identifier
    """
    # Accumulate an unordered set whose each element is one unique secret-looking name.
    found: set[str] = set()
    # Inspect each nested syntax-node element in deterministic AST walk order.
    for inner in ast.walk(node):
        # Bare names contribute their complete identifier when it looks sensitive.
        if isinstance(inner, ast.Name) and SECRET_WORDS.search(inner.id):
            # Add the unique bare identifier to the result set.
            found.add(inner.id)
        # Attribute access contributes only its terminal sensitive spelling.
        elif isinstance(inner, ast.Attribute) and SECRET_WORDS.search(inner.attr):
            # Add the unique attribute identifier to the result set.
            found.add(inner.attr)
        # String literals are deliberately ignored because syntax cannot classify their value.
        elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            # Advance without overclaiming secret classification from arbitrary text.
            continue
    # Return every unique discovered identifier without implied ordering.
    return found


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(RedactionCheck()))
