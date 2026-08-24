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

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered root-base set whose each element may directly anchor a package hierarchy.
ROOT_BASES = frozenset({"Exception", "BaseException"})


class ExceptionShapeCheck(ModuleCheck):
    """Reports exceptions outside the package's own hierarchy, and split groups."""

    ## Invoked as `python -m checks.exception_shape`.
    name = "exception_shape"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ERR-006", "ERR-010")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for hierarchy shape and for ungrouped accumulations.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- both rules bind everywhere
        @return finding elements in hierarchy then grouped-failure order
        """
        # Tests may intentionally construct malformed exception hierarchies and groups.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Report hierarchy defects before grouped-propagation defects.
        yield from self._hierarchy(tree, path)
        yield from self._groups(tree, path)

    def _hierarchy(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report an exception deriving straight from a built-in other than the root.

        A module defining exactly one exception is not reported: a single type
        deriving from `Exception` *is* a one-class hierarchy, and demanding a base
        above it would be ceremony.

        @param tree the module's syntax tree
        @param path the file it came from
        @return finding elements in AST walk order, one per leaf outside the hierarchy
        """
        # Collect class elements with at least one resolvable base in AST walk order.
        classes = [n for n in ast.walk(tree)
                   if isinstance(n, ast.ClassDef) and _bases_of(n)]
        # Build an unordered set whose each element is a locally defined class name.
        local = {n.name for n in classes}
        # Preserve class walk order while selecting each exception-like class element.
        exceptions = [n for n in classes if _is_exception(n, local)]
        # A zero- or one-class exception family is already a complete narrow hierarchy.
        if len(exceptions) <= 1:
            # Stop iteration without demanding a ceremonial second base class.
            return

        # Inspect each exception-class element in deterministic walk order.
        for node in exceptions:
            # Collect terminal base-name elements in authored base order.
            bases = _bases_of(node)
            # Inheritance from any local class keeps this node inside the local hierarchy.
            if any(base in local for base in bases):
                # Advance to the next exception class.
                continue
            # Direct inheritance from a built-in exception identifies a possible package root.
            if any(base in ROOT_BASES for base in bases):
                # Advance because one package root is necessary and valid.
                continue
            # Yield the outside-hierarchy finding with base elements in declaration order.
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
        @return finding elements in function then raise walk order
        """
        # Inspect callable bodies for deferred aggregation followed by exception propagation.
        for node in ast.walk(tree):
            # Only callable bodies can contain both accumulation and later propagation.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Advance without scanning unrelated syntax as a function body.
                continue
            # Build an unordered set whose each element is a list name receiving ``append``.
            collected = {
                call.func.value.id
                for call in ast.walk(node)
                if isinstance(call, ast.Call)
                and isinstance(call.func, ast.Attribute)
                and call.func.attr == "append"
                and isinstance(call.func.value, ast.Name)
            }
            # Inspect each nested syntax-node element in deterministic function walk order.
            for raised in ast.walk(node):
                # Only raises with an explicit expression can select one collected element.
                if not isinstance(raised, ast.Raise) or raised.exc is None:
                    # Advance to the next nested syntax node.
                    continue
                # Resolve the plain container name indexed by the raised expression, if any.
                target = _subscript_base(raised.exc)
                # Indexing a known accumulation proves one of several failures is discarded.
                if target is not None and target in collected:
                    # Yield the ungrouped-propagation finding at the raise statement.
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
    @return base-name elements in authored order, dotted paths reduced to final segments
    """
    # Accumulate non-empty terminal base-name elements in declaration order.
    names = []
    # Inspect each base-expression element in authored order.
    for base in node.bases:
        # Resolve a qualified terminal attribute or bare identifier.
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        # Complex base expressions without a terminal name are outside the narrow predicate.
        if name:
            # Append the resolved base identity at its declaration position.
            names.append(name)
    # Return the ordered base-name sequence.
    return names


def _is_exception(node: ast.ClassDef, local: set[str]) -> bool:
    """Whether a class is an exception type.

    @param node the class definition
    @param local unordered set whose each element is a class name defined in this module
    @return true when a base is a built-in exception or looks like one; false otherwise
    """
    # Reduce authored base-name elements to the conservative exception-shape predicate.
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
    # Match only direct indexing of a bare accumulation name.
    if isinstance(expr, ast.Subscript) and isinstance(expr.value, ast.Name):
        # Return the container identifier selected by the subscript.
        return expr.value.id
    # Other expressions do not prove that one collected failure was selected.
    return None


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(ExceptionShapeCheck()))
