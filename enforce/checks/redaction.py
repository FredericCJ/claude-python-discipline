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

## Logger methods that emit a record.
EMITTERS = frozenset({"debug", "info", "warning", "warn", "error", "critical",
                      "exception", "fatal", "log"})

## Envelope fields that carry a value verbatim, and are therefore where an
## unredacted secret would arrive.
VERBATIM_FIELDS = frozenset({"value", "actual", "detail", "input", "argument"})


class RedactionCheck(ModuleCheck):
    """Reports a secret-named value passed to a logger or placed in an envelope."""

    ## Invoked as `python -m checks.redaction`.
    name = "redaction"
    ## The law/DIAG rule this check decides.
    rules = ("DIAG-014",)

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for secrets reaching a log or an envelope.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- the rule binds everywhere
        @return one finding per exposure
        """
        if is_test_path(path):
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and _is_log_call(node):
                yield from self._logged(node, path)
            elif isinstance(node, ast.Dict):
                yield from self._envelope(node, path)

    def _logged(self, node: ast.Call, path: Path) -> Iterator[Finding]:
        """Report a secret-named value handed to a logger.

        @param node the logging call
        @param path the file it came from
        @return one finding per secret named in the call
        """
        for name in sorted(_secret_names(node)):
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
        @return one finding per exposure
        """
        for key, value in zip(node.keys, node.values, strict=False):
            if not (isinstance(key, ast.Constant) and isinstance(key.value, str)):
                continue
            if key.value not in VERBATIM_FIELDS:
                continue
            for name in sorted(_secret_names(value)):
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
    @return True when it calls a logging level on some object
    """
    return isinstance(node.func, ast.Attribute) and node.func.attr in EMITTERS


def _secret_names(node: ast.AST) -> set[str]:
    """Every secret-looking identifier reachable from an expression.

    Reads bare names and attribute tails alike, so `password` and
    `credentials.token` both surface.

    @param node the expression to scan
    @return the offending identifiers
    """
    found: set[str] = set()
    for inner in ast.walk(node):
        if isinstance(inner, ast.Name) and SECRET_WORDS.search(inner.id):
            found.add(inner.id)
        elif isinstance(inner, ast.Attribute) and SECRET_WORDS.search(inner.attr):
            found.add(inner.attr)
        elif isinstance(inner, ast.Constant) and isinstance(inner.value, str):
            continue
    return found


if __name__ == "__main__":
    raise SystemExit(main(RedactionCheck()))
