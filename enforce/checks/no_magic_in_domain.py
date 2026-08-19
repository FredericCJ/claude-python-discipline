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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Builtins that decide at run time what a reader cannot decide at read time.
## `getattr` and `setattr` are included only when the attribute name is computed:
## `getattr(x, "name", None)` is a readable default, not metaprogramming.
DYNAMIC = frozenset({"eval", "exec", "compile", "globals", "locals", "vars",
                     "__import__"})

## Attribute access resolved at run time; reported only with a computed name.
COMPUTED_ACCESS = frozenset({"getattr", "setattr", "delattr", "hasattr"})

## Hooks that make a class's behaviour undiscoverable from its body.
MAGIC_METHODS = frozenset({"__getattr__", "__getattribute__", "__setattr__",
                           "__new__", "__init_subclass__", "__set_name__"})

## The layer where the four questions must stay answerable.
GOVERNED = "domain"


class NoMagicInDomainCheck(ModuleCheck):
    """Reports metaprogramming in the domain that hides what runs."""

    ## Invoked as `python -m checks.no_magic_in_domain`.
    name = "no_magic_in_domain"
    ## The law/ARCH rule this check decides.
    rules = ("ARCH-015",)

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for each construct that defers a decision to run time.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; only the domain is governed
        @return one finding per construct
        """
        if layer != GOVERNED or is_test_path(path):
            return

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                yield from self._call(node, path)
            elif isinstance(node, ast.ClassDef):
                yield from self._class(node, path)

    def _call(self, node: ast.Call, path: Path) -> Iterator[Finding]:
        """Report a dynamic builtin, or attribute access by a computed name.

        @param node the call expression
        @param path the file it came from
        @return one finding per offending call
        """
        name = getattr(node.func, "id", "")
        if name in DYNAMIC:
            yield Finding(
                "ARCH-015", path, node.lineno,
                f"the domain calls `{name}()`",
                "What runs must be answerable by reading. A mechanism needing a "
                "debugger to trace defeats every diagnostic downstream of it.",
            )
        elif name in COMPUTED_ACCESS and len(node.args) >= 2:  # ruff: ignore[magic-value-comparison] - object and name
            attribute = node.args[1]
            if not (isinstance(attribute, ast.Constant) and isinstance(attribute.value, str)):
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
        @return one finding per offending construct
        """
        for keyword in node.keywords:
            if keyword.arg == "metaclass":
                yield Finding(
                    "ARCH-015", path, node.lineno,
                    f"domain class {node.name} declares a metaclass",
                    "A metaclass changes what a class *is* somewhere else in the "
                    "tree. Build the type plainly, where its behaviour is visible.",
                )
        for statement in node.body:
            if (isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and statement.name in MAGIC_METHODS):
                yield Finding(
                    "ARCH-015", path, statement.lineno,
                    f"domain class {node.name} defines `{statement.name}`",
                    "It intercepts access that reads as ordinary, so what runs is "
                    "no longer what the call site appears to say.",
                )


if __name__ == "__main__":
    raise SystemExit(main(NoMagicInDomainCheck()))
