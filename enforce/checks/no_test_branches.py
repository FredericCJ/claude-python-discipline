"""Production code never branches on knowing it is under test.

Enforces ARCH-012.

Testability comes from the seam, not from the code recognizing its caller. A
branch that only runs under test is a branch nothing verifies in production, and
the two paths diverge silently from the day it is written.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING, Final

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered test-signal set whose each normalized name element means the process is testing.
TEST_SIGNALS = frozenset({
    "test", "testing", "test_mode", "testmode", "pytest", "unittest",
    "ci", "debug_mode", "is_test", "under_test", "dry_test", "mock",
})

## Unordered test-module set whose each root-name element may be used as a runner detector.
## Matched on the
## root package, so the dotted `unittest.mock` entry can never be hit on its own
## -- `unittest` already decides it, and the entry is kept only as documentation
## of the idiom.
TEST_MODULES = frozenset({"pytest", "unittest", "unittest.mock", "hypothesis"})


class NoTestBranchesCheck(ModuleCheck):
    """Rejects production code that behaves differently once it recognizes a test.

    Every layer is examined; test files are exempt, since naming the test
    machinery is exactly their job.
    """

    ## Invoked as `python -m checks.no_test_branches`.
    name = "no_test_branches"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ARCH-012",)

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for both shapes of test detection in one module.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- the rule binds everywhere
        @return finding elements for environment branches then runner probes
        """
        # Test modules legitimately depend on and branch around test machinery.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Report environment/flag signal branches before module-presence probes.
        yield from self._env_branches(tree, path)
        yield from self._module_detection(tree, path)

    def _env_branches(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a conditional whose test mentions a known test signal.

        At most one finding per condition: several signals in the same test
        describe one defect, and repeating it teaches the reader nothing.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return finding elements in AST walk order, at most one per offending condition
        """
        # Inspect production conditionals for branches controlled by test-only state.
        for node in ast.walk(tree):
            # Only statement and expression conditionals create divergent production behavior.
            if not isinstance(node, (ast.If, ast.IfExp)):
                # Advance without interpreting unrelated syntax nodes.
                continue
            # A matching literal matters only when the condition reads a plausible switch.
            if not _reads_a_switch(node.test):
                # Advance without mistaking domain vocabulary for environment detection.
                continue
            # Inspect each normalized test-signal element in condition walk order.
            for signal in _test_signals_in(node.test):
                # Yield one branch finding naming the first reliable signal.
                yield Finding(
                    "ARCH-012", path, node.lineno,
                    f"production branch keyed on a test signal (`{signal}`)",
                    "Inject a port and substitute it at the composition root (ARCH-011); "
                    "a branch only tests take is a branch production never exercises.",
                )
                # Stop after the first signal so one branch reports once.
                break

    def _module_detection(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report the two idioms that ask the runtime whether a test runner is here.

        A comparison against `sys.modules`, and a `try`-import of a test package
        guarded by `ImportError`. Both make a test dependency's presence a fact
        the program acts on.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return finding elements in AST walk and comparison-before-import order, located at
            the enclosing comparison or `try`, which is where a reader can see the branch
        """
        # Inspect comparisons and protected imports for test-runner presence checks.
        for node in ast.walk(tree):
            # Comparisons may ask whether a test runner is already loaded.
            if isinstance(node, ast.Compare):
                # Inspect each nested comparison syntax-node element in walk order.
                for sub in ast.walk(node):
                    # A direct ``sys.modules`` access is the reliable runner-probe shape.
                    if _is_sys_modules_probe(sub):
                        # Yield the module-table probe finding at the enclosing comparison.
                        yield Finding(
                            "ARCH-012", path, node.lineno,
                            "production code detects a test runner via sys.modules",
                            "Remove the detection; substitute behaviour at the seam instead.",
                        )
            # Try statements may branch on whether a test-only dependency imports.
            if isinstance(node, ast.Try):
                # Inspect each handler element in authored clause order.
                for handler in node.handlers:
                    # Import-failure handling plus guarded test import forms the detector.
                    if _catches_import_error(handler) and _imports_test_module(node.body):
                        # Yield the importability-probe finding at the enclosing try statement.
                        yield Finding(
                            "ARCH-012", path, node.lineno,
                            "production code branches on whether a test package imports",
                            "Remove the probe; a test dependency must not shape production "
                            "behaviour.",
                        )


## Where a test signal can actually come from. A condition must read one of these
## before a string inside it counts as test detection.
##
## This guard exists because the check reported `zone == "test"` in a real
## codebase whose domain classifies source files into zones -- `ports`, `test`,
## and so on. The string "test" there is a value in a taxonomy the program is
## reasoning ABOUT, not a signal about the process it is running IN. `ARCH-012`
## forbids production code that behaves differently once it recognises a test;
## comparing a domain value that happens to spell "test" recognises nothing.
##
## The distinction is the whole rule: a test signal is something the ENVIRONMENT
## tells the program. A literal on its own tells it nothing.
## Unordered switch-source set whose each name element can carry environment-provided signals.
_SWITCH_SOURCES: Final[frozenset[str]] = frozenset({
    "environ", "getenv", "argv", "flags", "settings", "config", "options",
})


def _reads_a_switch(expr: ast.expr) -> bool:
    """Whether a condition reads something that could carry a test signal.

    Satisfied by an environment or argv read, or by a name or attribute that is
    itself one of the known signals -- `if is_test:` needs no second witness,
    because the name IS the switch.

    @param expr the condition expression
    @return true when the condition consults a plausible signal source; false otherwise
    """
    # Inspect each nested syntax-node element in deterministic condition walk order.
    for node in ast.walk(expr):
        # A bare known signal name is itself a complete switch read.
        if isinstance(node, ast.Name) and node.id.lower() in TEST_SIGNALS:
            # Accept at the first reliable direct-name signal.
            return True
        # A known signal attribute or known configuration source is also a switch read.
        if isinstance(node, ast.Attribute) and (
            node.attr.lower() in TEST_SIGNALS or node.attr in _SWITCH_SOURCES
        ):
            # Accept at the first reliable attribute signal.
            return True
        # Calls may read environment/configuration through a recognized terminal name.
        if isinstance(node, ast.Call):
            # Resolve a terminal attribute or bare called identifier.
            named = getattr(node.func, "attr", getattr(node.func, "id", ""))
            # Recognized readers establish switch provenance.
            if named in _SWITCH_SOURCES or named in {"getenv", "get"}:
                # Accept at the first reliable call-based source.
                return True
        # Subscripts may read an environment/configuration mapping directly.
        if isinstance(node, ast.Subscript):
            # Select the indexed container expression.
            inner = node.value
            # A recognized container identity establishes switch provenance.
            if getattr(inner, "attr", getattr(inner, "id", "")) in _SWITCH_SOURCES:
                # Accept at the first reliable mapping source.
                return True
    # No syntax element reads a plausible environment-provided switch.
    return False


def _test_signals_in(expr: ast.expr) -> Iterator[str]:
    """Every mention of a known test signal inside a condition.

    A string constant is normalized before matching -- trimmed, lowercased,
    leading dashes stripped, remaining dashes turned into underscores -- so
    `--test-mode` and `TEST_MODE` both land. A name or an attribute matches on
    its identifier alone, whatever it was read from.

    @param expr the condition expression, searched to any depth
    @return signal elements as written in source, in deterministic AST traversal order
    """
    # Inspect each nested syntax-node element in deterministic condition walk order.
    for node in ast.walk(expr):
        # Normalize string literal switches across case, leading dashes, and separators.
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            # Match only normalized values belonging to the closed signal set.
            if node.value.strip().lower().lstrip("-").replace("-", "_") in TEST_SIGNALS:
                # Yield the exact authored literal spelling.
                yield node.value
        # Bare signal names retain their exact identifier spelling.
        elif isinstance(node, ast.Name) and node.id.lower() in TEST_SIGNALS:
            # Yield the exact authored bare name.
            yield node.id
        # Signal attributes retain their exact terminal spelling.
        elif isinstance(node, ast.Attribute) and node.attr.lower() in TEST_SIGNALS:
            # Yield the exact authored terminal attribute.
            yield node.attr


def _is_sys_modules_probe(node: ast.AST) -> bool:
    """Whether a node reads the loaded-module table, the usual runner detector.

    The literal name `sys` is required, so an aliased import slips through. That
    is the false negative this shape accepts in exchange for never accusing an
    unrelated `.modules` attribute.

    @param node any node
    @return true when it is an attribute access spelled ``sys.modules``; false otherwise
    """
    # Reject every shape except a terminal ``modules`` attribute access.
    if not isinstance(node, ast.Attribute) or node.attr != "modules":
        # The syntax cannot be the claimed module-table probe.
        return False
    # Require the unaliased ``sys`` receiver to avoid unrelated modules attributes.
    return isinstance(node.value, ast.Name) and node.value.id == "sys"


def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Whether a handler is positioned to absorb a failed import.

    @param handler the `except` clause
    @return true when ``ImportError`` or ``ModuleNotFoundError`` is named plainly among
        its type elements; false otherwise
    """
    # A bare handler states no import-failure type and is outside this narrow predicate.
    if handler.type is None:
        # Reject the handler from importability-probe classification.
        return False
    # Normalize a tuple of types or one type into authored expression order.
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    # Accept when any bare-name element belongs to the closed import-failure set.
    return any(isinstance(n, ast.Name) and n.id in {"ImportError", "ModuleNotFoundError"}
               for n in nodes)


def _imports_test_module(body: list[ast.stmt]) -> bool:
    """Whether a guarded block pulls in a test package directly.

    Only statements at the block's own level count; an import buried inside a
    nested function is not the availability probe this looks for. Matching is on
    the root package, so `unittest.mock` answers to `unittest`.

    @param body guarded statement elements in source order
    @return true when any statement imports a test-only package; false otherwise
    """
    # Inspect each guarded top-level statement element in source order.
    for stmt in body:
        # Direct imports may carry several module aliases in authored order.
        if isinstance(stmt, ast.Import):
            # Match each imported root name against the closed test-module set.
            if any(a.name.split(".", 1)[0] in TEST_MODULES for a in stmt.names):
                # Accept at the first direct test-module import.
                return True
        # From-imports supply one module spelling when not relative-only.
        elif (
            isinstance(stmt, ast.ImportFrom)
            and stmt.module
            and stmt.module.split(".", 1)[0] in TEST_MODULES
        ):
            # Accept at the first from-import whose root belongs to the test-module set.
            return True
    # No guarded top-level statement imports a recognized test-only package.
    return False


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(NoTestBranchesCheck()))
