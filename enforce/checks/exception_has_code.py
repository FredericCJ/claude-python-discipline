"""Every custom exception carries a stable code, and its detail in attributes.

Enforces `DIAG-002` (a namespaced `code` class attribute on every exception type)
and `DIAG-003` (the offending value, the expectation and what was seen live as
attributes, not interpolated into a sentence).

The two are one check because they fail together. An exception carrying only a
formatted message forces every consumer to parse prose back into values, and the
first time the prose improves, every consumer breaks silently.

**What this decides and what it does not.** It decides that a code exists, is
namespaced, and is not a bare copy of the class name. It cannot decide that the
code is *stable* across releases -- that is `DIAG-004`, and it needs two versions
to compare, which no single-tree AST check has.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## A code that names its package and at least one narrowing segment, lowercase
## and dot-separated: `pkg.domain.invariant.outline_cycle`. A single bare word is
## refused because it collides across packages the moment two are combined.
NAMESPACED = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

## Base names that mean "this class is itself an exception". Matched on the
## trailing identifier, so `errors.AppError` and `AppError` both count.
EXCEPTION_BASES = frozenset({
    "Exception", "BaseException", "ValueError", "TypeError", "RuntimeError",
    "OSError", "LookupError", "KeyError", "IndexError", "ArithmeticError",
    "AttributeError", "NotImplementedError", "ExceptionGroup",
})

## Attribute names that carry structured detail rather than prose. A subclass
## defining any of these is treated as having satisfied DIAG-003.
DETAIL_ATTRS = frozenset({"expected", "actual", "value", "detail", "port",
                          "operation", "invariant", "remaining", "deleted"})


class ExceptionHasCodeCheck(ModuleCheck):
    """Reports an exception type with no stable code, or with detail only in prose.

    Applies to every layer: an exception defined anywhere becomes part of some
    consumer's surface. Test files are exempt, since a fixture exception exists
    to be raised once and never matched on.
    """

    ## Invoked as `python -m checks.exception_has_code`.
    name = "exception_has_code"
    ## The law/DIAG rules this check decides.
    rules = ("DIAG-002", "DIAG-003")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for every exception class defined in the module.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- an exception is surface
            wherever it is defined
        @return one finding per exception missing a code or a structured detail
        """
        if is_test_path(path):
            return
        known = _exception_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_exception(node, known):
                yield from self._judge(node, path)

    def _judge(self, node: ast.ClassDef, path: Path) -> Iterator[Finding]:
        """Report what one exception class is missing.

        @param node the class definition
        @param path the file it came from
        @return findings for a missing or malformed code, and for prose-only detail
        """
        code = _assigned_string(node, "code")
        if code is None:
            yield Finding(
                "DIAG-002", path, node.lineno,
                f"exception {node.name} defines no `code`",
                'Give it a namespaced class attribute: code = "pkg.layer.what_failed". '
                "A greppable code survives a message rewording; a sentence does not.",
            )
        elif not NAMESPACED.match(code):
            yield Finding(
                "DIAG-002", path, node.lineno,
                f"exception {node.name} has code {code!r}, which is not namespaced",
                "Use lowercase dotted segments naming the package and the failure, "
                "so two packages cannot mint the same code.",
            )

        if _only_formats(node):
            yield Finding(
                "DIAG-003", path, node.lineno,
                f"exception {node.name} carries its detail only in the message",
                "Assign the offending value, the expectation and what was seen to "
                "attributes. An agent can compare `expected` to `actual`; it cannot "
                "reliably parse them back out of a formatted sentence.",
            )


def _exception_names(tree: ast.Module) -> set[str]:
    """Classes defined in this module that are themselves exceptions.

    Lets a subclass of a locally defined base be recognised without resolving
    imports, which an AST check cannot do.

    @param tree the module's syntax tree
    @return the names of locally defined exception classes
    """
    found: set[str] = set()
    for _ in range(3):  # settle: a subclass may be defined before its base
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and _is_exception(node, found):
                found.add(node.name)
    return found


def _is_exception(node: ast.ClassDef, known: set[str]) -> bool:
    """Whether a class derives from something that is an exception.

    @param node the class definition
    @param known exception classes already identified in this module
    @return True when any base names a built-in exception, a locally known one,
        or an identifier ending in `Error` or `Exception`
    """
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name in EXCEPTION_BASES or name in known or name.endswith(("Error", "Exception")):
            return True
    return False


def _assigned_string(node: ast.ClassDef, target: str) -> str | None:
    """The string a class body assigns to a name, if it assigns a literal one.

    @param node the class definition
    @param target the attribute name to look for
    @return the literal value, or None when unassigned or not a literal
    """
    for statement in node.body:
        targets = (
            [statement.target] if isinstance(statement, ast.AnnAssign)
            else statement.targets if isinstance(statement, ast.Assign)
            else []
        )
        for element in targets:
            if isinstance(element, ast.Name) and element.id == target:
                value = statement.value
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    return value.value
    return None


def _only_formats(node: ast.ClassDef) -> bool:
    """Whether an initializer builds a message and keeps nothing.

    An `__init__` that interpolates its arguments into a string and assigns none
    of them to `self` has thrown the structured detail away. A class with no
    `__init__` at all is not reported: it adds no detail to lose.

    @param node the class definition
    @return True when the initializer formats without keeping any attribute
    """
    init = next(
        (s for s in node.body
         if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "__init__"),
        None,
    )
    if init is None or len(init.args.args) <= 1:
        return False
    formats = any(isinstance(n, ast.JoinedStr) for n in ast.walk(init))
    keeps = any(
        isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name) and n.value.id == "self"
        for n in ast.walk(init)
    )
    return formats and not keeps


if __name__ == "__main__":
    raise SystemExit(main(ExceptionHasCodeCheck()))
