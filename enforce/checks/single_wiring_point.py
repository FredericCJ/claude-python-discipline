"""Concrete adapters are chosen in one place, and the public surface speaks the domain.

Enforces `ARCH-011` (adapters are selected at one composition root; no other
module names a concrete adapter class) and `API-003` (public operations speak the
domain, not the store).

Replaceability that requires edits in several places is not replaceability. The
single root is what makes substituting a fake in a test the *same operation* as
substituting one in production -- one argument, one call site -- rather than a
parallel wiring path that can drift.

**How a concrete adapter is recognised.** By where it is defined: a class under
`adapters/`. The check reads the import graph, so a module importing a name from
an `adapters` package is naming a concrete adapter, whatever the class is called.
That is more reliable than matching names like `*Adapter`, which a codebase is
free not to use -- and the reference package does not.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Module basenames treated as the composition root. A file named for wiring is
## allowed -- required, in fact -- to name every concrete adapter there is.
COMPOSITION_ROOTS = frozenset({"composition", "wiring", "container", "main",
                               "bootstrap", "__main__"})

## Layers that may not name a concrete adapter. The shell may, but only in its
## composition root; adapters name themselves; tests substitute deliberately.
GOVERNED = frozenset({"domain", "app", "shell"})

## Names that indicate a storage or transport vocabulary leaking into a public
## signature. `API-003` is about a public operation returning a row, a cursor or
## a response rather than a domain value.
STORAGE_TYPES = frozenset({"Row", "Cursor", "Connection", "Session", "ResultSet",
                           "Document", "Record", "Blob", "Response", "Request"})


class SingleWiringPointCheck(ModuleCheck):
    """Reports a concrete adapter named outside the composition root."""

    ## Invoked as `python -m checks.single_wiring_point`.
    name = "single_wiring_point"
    ## The law/ARCH and law/API rules this check decides.
    rules = ("API-003", "ARCH-011")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for adapter imports outside the root, and storage in signatures.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer the file sits in
        @return one finding per violation
        """
        if is_test_path(path):
            return
        if layer in GOVERNED and path.stem not in COMPOSITION_ROOTS:
            yield from self._adapter_imports(tree, path, layer)
        if layer in {"app", "shell"}:
            yield from self._storage_in_signatures(tree, path)

    def _adapter_imports(self, tree: ast.Module, path: Path,
                         layer: str) -> Iterator[Finding]:
        """Report an import reaching into an adapters package.

        @param tree the module's syntax tree
        @param path the file it came from
        @param layer the layer, named in the message
        @return one finding per offending import
        """
        for node in ast.walk(tree):
            module = (
                node.module if isinstance(node, ast.ImportFrom) and node.module
                else " ".join(a.name for a in node.names) if isinstance(node, ast.Import)
                else ""
            )
            if not module:
                continue
            if any(part == "adapters" for part in module.replace(" ", ".").split(".")):
                yield Finding(
                    "ARCH-011", path, node.lineno,
                    f"{layer} names a concrete adapter by importing `{module}`",
                    "Move the selection to the composition root and take the port "
                    "as a parameter. Replaceability that needs edits in several "
                    "places is not replaceability.",
                )

    def _storage_in_signatures(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a public function whose signature names a storage type.

        Private helpers are exempt: `API-003` is about the *published* surface,
        and an internal function shuttling a cursor is the adapter doing its job.

        @param tree the module's syntax tree
        @param path the file it came from
        @return one finding per offending signature
        """
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("_"):
                continue
            annotations = [a.annotation for a in node.args.args if a.annotation]
            if node.returns is not None:
                annotations.append(node.returns)
            for annotation in annotations:
                for named in ast.walk(annotation):
                    name = (
                        named.attr if isinstance(named, ast.Attribute)
                        else named.id if isinstance(named, ast.Name)
                        else ""
                    )
                    if name in STORAGE_TYPES:
                        yield Finding(
                            "API-003", path, node.lineno,
                            f"public {node.name}() names the storage type `{name}` "
                            f"in its signature",
                            "Translate to a domain value at the boundary. A public "
                            "operation speaking the store couples every caller to it.",
                        )
                        break


if __name__ == "__main__":
    raise SystemExit(main(SingleWiringPointCheck()))
