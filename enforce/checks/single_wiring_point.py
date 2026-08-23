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

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered composition-module set whose each basename element may name concrete adapters.
COMPOSITION_ROOTS = frozenset({"composition", "wiring", "container", "main",
                               "bootstrap", "__main__"})

## Unordered governed-layer set whose each element may name adapters only under its rules.
GOVERNED = frozenset({"domain", "app", "shell"})

## Unordered storage-type set whose each name element leaks infrastructure into a public API.
STORAGE_TYPES = frozenset({"Row", "Cursor", "Connection", "Session", "ResultSet",
                           "Document", "Record", "Blob", "Response", "Request"})


class SingleWiringPointCheck(ModuleCheck):
    """Reports a concrete adapter named outside the composition root."""

    ## Invoked as `python -m checks.single_wiring_point`.
    name = "single_wiring_point"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("API-003", "ARCH-011")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for adapter imports outside the root, and storage in signatures.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer the file sits in
        @return finding elements in adapter-import then signature order
        """
        # Tests may deliberately name concrete substitutes and infrastructure-shaped fixtures.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Governed non-root modules may not import an adapters package.
        if layer in GOVERNED and path.stem not in COMPOSITION_ROOTS:
            # Yield adapter-import findings in AST walk order.
            yield from self._adapter_imports(tree, path, layer)
        # Application and shell public operations must speak domain vocabulary.
        if layer in {"app", "shell"}:
            # Yield storage-signature findings after wiring findings.
            yield from self._storage_in_signatures(tree, path)

    def _adapter_imports(self, tree: ast.Module, path: Path,
                         layer: str) -> Iterator[Finding]:
        """Report an import reaching into an adapters package.

        @param tree the module's syntax tree
        @param path the file it came from
        @param layer the layer, named in the message
        @return finding elements in AST walk order, one per offending import
        """
        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Render import and from-import modules into a normalized searchable spelling.
            module = (
                node.module if isinstance(node, ast.ImportFrom) and node.module
                else " ".join(a.name for a in node.names) if isinstance(node, ast.Import)
                else ""
            )
            # Non-import syntax contributes an empty spelling and is irrelevant.
            if not module:
                # Advance to the next syntax node.
                continue
            # Any exact adapters path segment proves concrete infrastructure coupling.
            if any(part == "adapters" for part in module.replace(" ", ".").split(".")):
                # Yield the import finding at the exact statement line.
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
        @return finding elements in function, annotation, then syntax walk order
        """
        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Only callable definitions publish type signatures.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Advance without interpreting unrelated syntax nodes.
                continue
            # Private helpers do not form the published API subject of this rule.
            if node.name.startswith("_"):
                # Advance to the next callable definition.
                continue
            # Collect each positional-parameter annotation element in declaration order.
            annotations = [a.annotation for a in node.args.args if a.annotation]
            # A return annotation follows parameter annotations in signature scan order.
            if node.returns is not None:
                # Append the return contract to the ordered annotation sequence.
                annotations.append(node.returns)
            # Inspect each annotation-expression element in signature order.
            for annotation in annotations:
                # Inspect each nested syntax-node element in deterministic AST walk order.
                for named in ast.walk(annotation):
                    # Resolve a qualified terminal attribute or bare type identifier.
                    name = (
                        named.attr if isinstance(named, ast.Attribute)
                        else named.id if isinstance(named, ast.Name)
                        else ""
                    )
                    # Closed storage vocabulary in any nested position leaks infrastructure.
                    if name in STORAGE_TYPES:
                        # Yield one finding for this public signature.
                        yield Finding(
                            "API-003", path, node.lineno,
                            f"public {node.name}() names the storage type `{name}` "
                            f"in its signature",
                            "Translate to a domain value at the boundary. A public "
                            "operation speaking the store couples every caller to it.",
                        )
                        # Stop nested scanning so one signature reports once per annotation.
                        break


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(SingleWiringPointCheck()))
