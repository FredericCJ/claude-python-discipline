"""Inside the domain, the four questions stay answerable by reading.

Enforces `ARCH-015`: what runs, when, what state it changes, and what happens
when it fails, must all be answerable from the source without executing it.

This is `CONF-014`'s resolution, and it is a hard exclusion rather than a
preference. A mechanism that requires a debugger to trace defeats every
diagnostic guarantee downstream of it: an envelope naming a layer is worth
nothing if nobody can say what ran in that layer without stepping through it.

Scoped to the domain alone. An adapter may need `getattr` to bridge a foreign
library's shape, and the shell may build a parser dynamically; the core is where
the guarantee has to hold, because the core is what every diagnosis points at.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered dynamic-builtin set whose each element hides a decision until runtime;
## computed attribute access is handled separately.
DYNAMIC = frozenset({"eval", "exec", "compile", "globals", "locals", "vars",
                     "__import__"})

## Unordered access-builtin set whose each element is reported only with a computed name.
COMPUTED_ACCESS = frozenset({"getattr", "setattr", "delattr", "hasattr"})

## Unordered magic-method set whose each element makes class behavior undiscoverable locally.
MAGIC_METHODS = frozenset({"__getattr__", "__getattribute__", "__setattr__",
                           "__new__", "__init_subclass__", "__set_name__"})

## The layer where the four questions must stay answerable.
GOVERNED = "domain"


class NoMagicInDomainCheck(ModuleCheck):
    """Reports metaprogramming in the domain that hides what runs."""

    ## Invoked as `python -m checks.no_magic_in_domain`.
    name = "no_magic_in_domain"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ARCH-015",)

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for each construct that defers a decision to run time.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; only the domain is governed
        @return finding elements in AST walk order, one per hidden-runtime construct
        """
        # Only non-test domain code owns the strong readability exclusion.
        if layer != GOVERNED or is_test_path(path):
            # Stop iteration outside the rule's exact architectural subject.
            return

        # Inspect calls for dynamic builtins forbidden inside the domain layer.
        for node in ast.walk(tree):
            # Delegate calls to the closed dynamic-builtin classifier.
            if isinstance(node, ast.Call):
                # Yield each call-level finding at this AST position.
                yield from self._call(node, path)
            # Delegate classes to metaclass and magic-hook inspection.
            elif isinstance(node, ast.ClassDef):
                # Yield each class-level finding at this AST position.
                yield from self._class(node, path)

    def _call(self, node: ast.Call, path: Path) -> Iterator[Finding]:
        """Report a dynamic builtin, or attribute access by a computed name.

        @param node the call expression
        @param path the file it came from
        @return zero or one finding element for the offending call
        """
        # Select a bare called identifier, leaving qualified calls unmatched.
        name = getattr(node.func, "id", "")
        # Closed dynamic builtins always hide what implementation runs.
        if name in DYNAMIC:
            # Yield the direct dynamic-call finding at its source line.
            yield Finding(
                "ARCH-015", path, node.lineno,
                f"the domain calls `{name}()`",
                "What runs must be answerable by reading. A mechanism needing a "
                "debugger to trace defeats every diagnostic downstream of it.",
            )
        # Computed-access builtins are permitted only when their attribute name is literal.
        elif name in COMPUTED_ACCESS and len(node.args) >= 2:  # ruff: ignore[magic-value-comparison] - object and name
            # Select the second positional argument that carries attribute identity.
            attribute = node.args[1]
            # Any non-string-literal attribute makes runtime access impossible to enumerate.
            if not (isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)):
                # Yield the computed-attribute finding at its call site.
                yield Finding(
                    "ARCH-015", path, node.lineno,
                    f"the domain calls `{name}()` with a computed attribute name",
                    "Name the attribute literally, or model the choice as a closed "
                    "set. A computed name is a branch no reader can enumerate.",
                )

    def _class(self, node: ast.ClassDef, path: Path) -> Iterator[Finding]:
        """Report a metaclass, or a hook that intercepts ordinary access.

        @param node the class definition
        @param path the file it came from
        @return finding elements in keyword then class-body order, one per offending construct
        """
        # Inspect each class-keyword element in authored order for metaclass selection.
        for keyword in node.keywords:
            # An explicit metaclass moves class construction behavior outside the body.
            if keyword.arg == "metaclass":
                # Yield the metaclass finding at the class definition.
                yield Finding(
                    "ARCH-015", path, node.lineno,
                    f"domain class {node.name} declares a metaclass",
                    "A metaclass changes what a class *is* somewhere else in the "
                    "tree. Build the type plainly, where its behaviour is visible.",
                )
        # Inspect each class-body statement element in source order for intercepting hooks.
        for statement in node.body:
            # Report only function definitions whose name belongs to the closed hook set.
            if (isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and statement.name in MAGIC_METHODS):
                # Yield the hidden-access finding at the exact method definition.
                yield Finding(
                    "ARCH-015", path, statement.lineno,
                    f"domain class {node.name} defines `{statement.name}`",
                    "It intercepts access that reads as ordinary, so what runs is "
                    "no longer what the call site appears to say.",
                )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(NoMagicInDomainCheck()))
