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

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## A code that names its package and at least one narrowing segment, lowercase
## and dot-separated: `pkg.domain.invariant.outline_cycle`. A single bare word is
## refused because it collides across packages the moment two are combined.
NAMESPACED = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

## Unordered exception-base set whose each terminal name element identifies an exception class.
EXCEPTION_BASES = frozenset({
    "Exception", "BaseException", "ValueError", "TypeError", "RuntimeError",
    "OSError", "LookupError", "KeyError", "IndexError", "ArithmeticError",
    "AttributeError", "NotImplementedError", "ExceptionGroup",
})

## Unordered detail-attribute set whose each name element carries structure rather than prose.
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
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("DIAG-002", "DIAG-003")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for every exception class defined in the module.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- an exception is surface
            wherever it is defined
        @return finding elements in class walk then code-before-detail order
        """
        # Tests may intentionally define minimal exception fixtures without published contracts.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Build an unordered set whose each element is a locally recognized exception name.
        known = _exception_names(tree)
        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Judge only class definitions recognized through built-in or local exception bases.
            if isinstance(node, ast.ClassDef) and _is_exception(node, known):
                # Yield stable-code then structured-detail findings for this class.
                yield from self._judge(node, path)

    def _judge(self, node: ast.ClassDef, path: Path) -> Iterator[Finding]:
        """Report what one exception class is missing.

        @param node the class definition
        @param path the file it came from
        @return finding elements in code then structured-detail order
        """
        # Resolve a literal class-level code assignment, or None for absence/non-literal form.
        code = _assigned_string(node, "code")
        # A custom exception without a code gives consumers no stable matching identity.
        if code is None:
            # Yield the missing-code finding at the class definition.
            yield Finding(
                "DIAG-002", path, node.lineno,
                f"exception {node.name} defines no `code`",
                'Give it a namespaced class attribute: code = "pkg.layer.what_failed". '
                "A greppable code survives a message rewording; a sentence does not.",
            )
        # A present code must include package and narrowing dotted segments.
        elif not NAMESPACED.match(code):
            # Yield the malformed-code finding at the class definition.
            yield Finding(
                "DIAG-002", path, node.lineno,
                f"exception {node.name} has code {code!r}, which is not namespaced",
                "Use lowercase dotted segments naming the package and the failure, "
                "so two packages cannot mint the same code.",
            )

        # Formatting initializer inputs without storing any attribute destroys structured detail.
        if _only_formats(node):
            # Yield the prose-only-detail finding at the class definition.
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
    @return unordered set whose each element names a locally defined exception class
    """
    # Accumulate an unordered set whose each element is one recognized exception identity.
    found: set[str] = set()
    # Repeat three bounded passes so a subclass defined before its base can settle.
    for _ in range(3):
        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Add any class whose bases reach built-in names or the current local set.
            if isinstance(node, ast.ClassDef) and _is_exception(node, found):
                # Add the unique class identity without changing existing membership.
                found.add(node.name)
    # Return every locally recognized exception identity without implied ordering.
    return found


def _is_exception(node: ast.ClassDef, known: set[str]) -> bool:
    """Whether a class derives from something that is an exception.

    @param node the class definition
    @param known unordered set whose each element is an exception class already identified here
    @return true when any base names a built-in exception, a locally known one, or an
        identifier ending in ``Error`` or ``Exception``; false otherwise
    """
    # Inspect each base-expression element in authored declaration order.
    for base in node.bases:
        # Resolve a qualified terminal attribute or bare base identifier.
        name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
        # Built-in, settled-local, and conventional exception names satisfy classification.
        if name in EXCEPTION_BASES or name in known or name.endswith(("Error", "Exception")):
            # Accept immediately when any base establishes exception ancestry.
            return True
    # No authored base establishes exception ancestry under the narrow predicate.
    return False


def _assigned_string(node: ast.ClassDef, target: str) -> str | None:
    """The string a class body assigns to a name, if it assigns a literal one.

    @param node the class definition
    @param target the attribute name to look for
    @return the literal value, or None when unassigned or not a literal
    """
    # Inspect each class-body statement element in source order.
    for statement in node.body:
        # Collect assignment-target elements in authored order for supported assignment forms.
        targets = (
            [statement.target] if isinstance(statement, ast.AnnAssign)
            else statement.targets if isinstance(statement, ast.Assign)
            else []
        )
        # Inspect each assignment-target element in authored order.
        for element in targets:
            # Only a bare target exactly matching the requested class attribute is relevant.
            if isinstance(element, ast.Name) and element.id == target:
                # Select the assigned expression from either assignment form.
                value = statement.value
                # Return only a literal string because computed codes are not statically stable.
                if isinstance(value, ast.Constant) and isinstance(value.value, str):
                    # Return the literal class-level code spelling.
                    return value.value
    # No supported class-body assignment supplied a literal value for the target.
    return None


def _only_formats(node: ast.ClassDef) -> bool:
    """Whether an initializer builds a message and keeps nothing.

    An `__init__` that interpolates its arguments into a string and assigns none
    of them to `self` has thrown the structured detail away. A class with no
    `__init__` at all is not reported: it adds no detail to lose.

    @param node the class definition
    @return true when the initializer formats without keeping any attribute; false otherwise
    """
    # Select the first initializer function element in class-body order, if any.
    init = next(
        (s for s in node.body
         if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef)) and s.name == "__init__"),
        None,
    )
    # No custom detail-bearing initializer means no input detail is demonstrably discarded.
    if init is None or len(init.args.args) <= 1:
        # Reject this class from the prose-only predicate.
        return False
    # Record whether any nested expression formats an f-string message.
    formats = any(isinstance(n, ast.JoinedStr) for n in ast.walk(init))
    # Record whether any nested store assigns structured state onto ``self``.
    keeps = any(
        isinstance(n, ast.Attribute) and isinstance(n.ctx, ast.Store)
        and isinstance(n.value, ast.Name) and n.value.id == "self"
        for n in ast.walk(init)
    )
    # Report only the conjunction of formatted prose and no retained instance detail.
    return formats and not keeps


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(ExceptionHasCodeCheck()))
