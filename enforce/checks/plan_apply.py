"""Destructive work plans before it applies, and state machines are closed.

Enforces `EFCT-004` (mutating operations are commands, not raw writes),
`EFCT-005` (destructive operations plan before they apply), `EFCT-010` (state
transitions are explicit and closed) and `EFCT-011` (illegal transitions are
refused before any effect).

The rule exists because of a recorded incident: a directory-cleanup routine
destroyed 8,023 files while reporting success. What it lacked was not a test but
a *plan* -- a value naming what it was about to do, which a caller could inspect
and refuse before anything was removed.

**What this decides and what it does not.** It decides that a function performing
an irreversible operation takes a flag or a plan rather than doing it
unconditionally, and that a state transition is not written as a bare string
comparison. It cannot decide that a plan is *correct* -- only that the operation
is not performed without one.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered destructive-call set whose each element cannot be undone by the same process.
DESTRUCTIVE = frozenset({
    "unlink", "rmtree", "remove", "rmdir", "removedirs", "truncate",
    "drop", "drop_table", "delete_many", "purge", "wipe", "destroy",
})

## Unordered gate-parameter set whose each name element represents opt-in or an explicit plan.
GATE_PARAMS = frozenset({
    "plan", "dry_run", "apply", "apply_it", "confirm", "confirmed", "force",
    "commit", "execute", "really",
})

## Unordered governed-layer set whose each element owes a plan before irreversible calls.
## Deliberately excludes
## `adapters`: an adapter implementing a port's `delete` IS the apply half of
## plan/apply, and requiring it to take a plan parameter would mean no conformant
## implementation of the pattern could pass. Calibration found this immediately --
## the first run reported the reference package's own `LocalFileStore.delete` and
## five adapter primitives across three real packages, every one of them correct
## code. The obligation belongs to the layers that *decide*, not the one that
## performs. The domain is excluded for a different reason: `ARCH-002` forbids it
## effects at all, so a destructive call there is already a worse finding.
GOVERNED = frozenset({"app", "shell"})

## Unordered state-attribute set whose each name element must not use open string states.
STATE_NAMES = frozenset({"state", "status", "phase", "stage", "mode"})


class PlanApplyCheck(ModuleCheck):
    """Reports irreversible work done without a plan, and open state transitions."""

    ## Invoked as `python -m checks.plan_apply`.
    name = "plan_apply"
    ## The law/EFCT rules this check decides.
    ## Narrowed to what this check can actually REPORT. EFCT-004 and EFCT-011
    ## were named here and never emitted, so they counted as `mechanized` while
    ## being decided by nothing -- and this module's own docstring said so in
    ## prose. `V080` rises as a result, which is the true number.
    ## Rule-id elements in deterministic reporting order actually decided here.
    rules = ("EFCT-005", "EFCT-010")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for ungated destruction and for open state comparisons.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer the file sits in
        @return finding elements in destruction then transition order
        """
        # Tests may intentionally construct destructive and open-state counterexamples.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Only application and shell code decide whether irreversible work should happen.
        if layer in GOVERNED:
            # Yield ungated-destruction findings before general state findings.
            yield from self._destruction(tree, path)
        # State closure applies across every non-test architectural layer.
        yield from self._transitions(tree, path)

    def _destruction(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a function that destroys without taking a plan or a flag.

        A function whose *own name* says it applies -- `apply`, `delete`,
        `remove` -- is exempt: it is the second half of a plan/apply pair, and
        the gate is its caller's business. Reporting it would mean no
        implementation of the pattern could ever pass.

        @param tree the module's syntax tree
        @param path the file it came from
        @return finding elements in AST walk order, one per ungated destructive function
        """
        # Inspect callables for destructive operations lacking a caller-supplied plan.
        for node in ast.walk(tree):
            # Only callable bodies can own caller-provided plan parameters.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Advance without scanning unrelated syntax as a function body.
                continue
            # Build an unordered set whose each element is a called terminal function name.
            calls = {
                call.func.attr for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            } | {
                call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            # Intersect called names with the closed destructive-operation set.
            destructive = calls & DESTRUCTIVE
            # A function with no destructive call owes no plan gate.
            if not destructive:
                # Advance to the next callable definition.
                continue
            # Apply/delete-named functions are the execution half whose caller owns gating.
            if node.name.lower() in DESTRUCTIVE | {"apply", "_apply"}:
                # Advance without making conformant plan execution impossible.
                continue
            # Build an unordered set whose each element is a positional or keyword-only name.
            params = {a.arg for a in (*node.args.args, *node.args.kwonlyargs)}
            # Any recognized gate parameter provides a refusal seam for the caller.
            if params & GATE_PARAMS:
                # Advance because the function does not perform destruction unconditionally.
                continue
            # Yield the ungated-destruction finding with destructive names sorted for stability.
            yield Finding(
                "EFCT-005", path, node.lineno,
                f"{node.name}() calls {', '.join(sorted(destructive))} with no plan "
                f"and no opt-in parameter",
                "Compute a plan, return it, and perform it only when the caller "
                "asks. A cleanup routine once destroyed 8,023 files while "
                "reporting success; what it lacked was the plan, not a test.",
            )

    def _transitions(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a state compared against a bare string literal.

        @param tree the module's syntax tree
        @param path the file it came from
        @return finding elements in AST walk order, one per open comparison
        """
        # Inspect comparisons for state transitions against an open expected-value set.
        for node in ast.walk(tree):
            # Only comparisons with at least one right-hand operand can encode transitions.
            if not isinstance(node, ast.Compare) or not node.comparators:
                # Advance without interpreting unrelated syntax nodes.
                continue
            # Select the left comparison expression that may carry state identity.
            left = node.left
            # Only known state attributes are mechanically reliable transition signals.
            if not isinstance(left, ast.Attribute) or left.attr not in STATE_NAMES:
                # Advance without guessing the semantics of arbitrary names.
                continue
            # Inspect each comparator element in authored chained-comparison order.
            for other in node.comparators:
                # A bare string comparator creates an unbounded open state vocabulary.
                if isinstance(other, ast.Constant) and isinstance(other.value, str):
                    # Yield one open-state finding for this comparison.
                    yield Finding(
                        "EFCT-010", path, node.lineno,
                        f"`{left.attr}` is compared against the literal "
                        f"{other.value!r}",
                        "Make the states an enumeration and the transitions a "
                        "closed table. A string comparison admits every state "
                        "anyone ever typos, and refuses none of them.",
                    )
                    # Stop after the first literal so one comparison reports once.
                    break


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(PlanApplyCheck()))
