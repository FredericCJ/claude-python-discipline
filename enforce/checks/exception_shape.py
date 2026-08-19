"""Exceptions form one narrow hierarchy, and grouped failures stay grouped.

Enforces `ERR-006` (every exception the package defines descends from one base of
its own, not from a scattering of built-ins) and `ERR-010` (several failures
gathered together propagate as an `ExceptionGroup`, not as the first one found).

`ERR-006` is what makes `except PackageError` a meaningful thing for a caller to
write. A package raising a bare `ValueError` here and a bare `RuntimeError` there
gives a caller no way to catch *its* failures without also catching the standard
library's.

**What this decides and what it does not.** It decides that every locally defined
exception reaches a single local root, and that a loop accumulating errors does
not then raise only one of them. It cannot decide whether the root is the *right*
root, nor whether a group's members are related.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Built-ins a package base may itself descend from. A package root inheriting
## from one of these is correct and expected; a *leaf* doing so is the defect.
ROOT_BASES = frozenset({"Exception", "BaseException"})


class ExceptionShapeCheck(ModuleCheck):
    """Reports exceptions outside the package's own hierarchy, and split groups."""

    ## Invoked as `python -m checks.exception_shape`.
    name = "exception_shape"
    ## The law/ERR rules this check decides.
    rules = ("ERR-006", "ERR-010")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for hierarchy shape and for ungrouped accumulations.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- both rules bind everywhere
        @return findings for each defect found
        """
        if is_test_path(path):
            return
        yield from self._hierarchy(tree, path)
        yield from self._groups(tree, path)

    def _hierarchy(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report an exception deriving straight from a built-in other than the root.

        A module defining exactly one exception is not reported: a single type
        deriving from `Exception` *is* a one-class hierarchy, and demanding a base
        above it would be ceremony.

        @param tree the module's syntax tree
        @param path the file it came from
        @return one finding per leaf outside the local hierarchy
        """
        classes = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and _bases_of(n)]
        local = {n.name for n in classes}
        exceptions = [n for n in classes if _is_exception(n, local)]
        if len(exceptions) <= 1:
            return
        for node in exceptions:
            bases = _bases_of(node)
            if any(base in local for base in bases):
                continue
            if any(base in ROOT_BASES for base in bases):
                continue  # a package root; there is one, and this may be it
            yield Finding(
                "ERR-006", path, node.lineno,
                f"exception {node.name} derives from {', '.join(bases)}, outside "
                f"this module's own hierarchy",
                "Derive it from the package's base error type. A caller cannot "
                "catch a package's failures without one root to name.",
            )

    def _groups(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a loop that collects errors and then raises only one.

        The shape looked for is narrow on purpose: a list accumulated inside a
        loop, and afterwards a `raise` of an indexed element of it. That is the
        idiom `ERR-010` exists to catch, and matching it exactly keeps the check
        from guessing at every list in the file.

        @param tree the module's syntax tree
        @param path the file it came from
        @return one finding per accumulation raised singly
        """
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            collected = {
                call.func.value.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "append"
                and isinstance(call.func.value, ast.Name)
            }
            for raised in ast.walk(node):
                if not isinstance(raised, ast.Raise) or raised.exc is None:
                    continue
                target = _subscript_base(raised.exc)
                if target is not None and target in collected:
                    yield Finding(
                        "ERR-010", path, raised.lineno,
                        f"{node.name}() gathers failures into `{target}` and raises "
                        f"one of them",
                        "Raise an ExceptionGroup over the whole list. Reporting the "
                        "first of several failures hides the rest until it is fixed.",
                    )


def _bases_of(node: ast.ClassDef) -> list[str]:
    """The trailing identifier of each base a class names.

    @param node the class definition
    @return one name per base, dotted paths reduced to their final segment
    """
    names = []
    for base in node.bases:
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        if name:
            names.append(name)
    return names


def _is_exception(node: ast.ClassDef, local: set[str]) -> bool:
    """Whether a class is an exception type.

    @param node the class definition
    @param local class names defined in the same module
    @return True when a base is a built-in exception or looks like one
    """
    return any(
        base in ROOT_BASES or base.endswith(("Error", "Exception"))
        or (base in local and base != node.name)
        for base in _bases_of(node)
    )


def _subscript_base(expr: ast.expr) -> str | None:
    """The name being indexed, when an expression indexes a plain name.

    @param expr the raised expression
    @return the indexed name, or None when the expression is not a subscript
    """
    if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
        return expr.value.id
    return None


if __name__ == "__main__":
    raise SystemExit(main(ExceptionShapeCheck()))
