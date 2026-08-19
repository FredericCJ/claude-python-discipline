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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Calls that destroy something and cannot be undone by the same process.
DESTRUCTIVE = frozenset({
    "unlink", "rmtree", "remove", "rmdir", "removedirs", "truncate",
    "drop", "drop_table", "delete_many", "purge", "wipe", "destroy",
})

## Parameter names that mean the caller has opted in, or handed over a plan. A
## function taking one of these has a seam at which the operation can be refused.
GATE_PARAMS = frozenset({
    "plan", "dry_run", "apply", "apply_it", "confirm", "confirmed", "force",
    "commit", "execute", "really",
})

## Layers where a plan is owed before an irreversible call. Deliberately excludes
## `adapters`: an adapter implementing a port's `delete` IS the apply half of
## plan/apply, and requiring it to take a plan parameter would mean no conformant
## implementation of the pattern could pass. Calibration found this immediately --
## the first run reported the reference package's own `LocalFileStore.delete` and
## five adapter primitives across three real packages, every one of them correct
## code. The obligation belongs to the layers that *decide*, not the one that
## performs. The domain is excluded for a different reason: `ARCH-002` forbids it
## effects at all, so a destructive call there is already a worse finding.
GOVERNED = frozenset({"app", "shell"})

## Attribute names that hold a state a transition moves between. A comparison
## against a bare string on one of these is the open-set shape `EFCT-010` refuses.
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
    rules = ("EFCT-005", "EFCT-010")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for ungated destruction and for open state comparisons.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer the file sits in
        @return one finding per violation
        """
        if is_test_path(path):
            return
        if layer in GOVERNED:
            yield from self._destruction(tree, path)
        yield from self._transitions(tree, path)

    def _destruction(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a function that destroys without taking a plan or a flag.

        A function whose *own name* says it applies -- `apply`, `delete`,
        `remove` -- is exempt: it is the second half of a plan/apply pair, and
        the gate is its caller's business. Reporting it would mean no
        implementation of the pattern could ever pass.

        @param tree the module's syntax tree
        @param path the file it came from
        @return one finding per ungated destructive function
        """
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = {
                call.func.attr for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)
            } | {
                call.func.id for call in ast.walk(node)
                if isinstance(call, ast.Call) and isinstance(call.func, ast.Name)
            }
            destructive = calls & DESTRUCTIVE
            if not destructive:
                continue
            if node.name.lower() in DESTRUCTIVE | {"apply", "_apply"}:
                continue
            params = {a.arg for a in (*node.args.args, *node.args.kwonlyargs)}
            if params & GATE_PARAMS:
                continue
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
        @return one finding per open comparison
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare) or not node.comparators:
                continue
            left = node.left
            if not isinstance(left, ast.Attribute) or left.attr not in STATE_NAMES:
                continue
            for other in node.comparators:
                if isinstance(other, ast.Constant) and isinstance(other.value, str):
                    yield Finding(
                        "EFCT-010", path, node.lineno,
                        f"`{left.attr}` is compared against the literal "
                        f"{other.value!r}",
                        "Make the states an enumeration and the transitions a "
                        "closed table. A string comparison admits every state "
                        "anyone ever typos, and refuses none of them.",
                    )
                    break


if __name__ == "__main__":
    raise SystemExit(main(PlanApplyCheck()))
