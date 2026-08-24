"""Parse at the boundary; try the operation; do not mistake a shape for a contract.

Enforces `ERR-011` (parse at the boundary, do not validate in the interior),
`ERR-013` (try the operation rather than pre-checking the world), `TYPE-005` (a
constrained type is a wrapper with a parsing constructor), `TYPE-010` (a runtime
protocol check is not a contract check), `TYPE-011` and `TYPE-012`.

**What this decides.** Three shapes, each unambiguous:

* `NewType`, which `CONF-015` retired. A `NewType` has no constructor and
  validates nothing, so it announces a constraint it cannot enforce -- the exact
  opposite of what `TYPE-005` asks for.
* `isinstance` against a `Protocol`. It answers "does this object have these
  method names", which is not the question. A fake with the right names and the
  wrong semantics passes; `TYPE-010` exists because that check reads like a
  contract check and is not one.
* Look-before-you-leap: probing the world, then acting on the answer. The gap
  between the two is where the file gets deleted by someone else, and the
  handler you needed anyway is the one that would have worked.

**What it does not decide.** `ERR-011`'s deeper claim -- that validation happens
at the boundary rather than scattered through the interior -- needs to know which
values crossed a boundary, which an AST check cannot see. `TYPE-011` and
`TYPE-012` are about who *can* enforce a constraint, which is a judgement.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered probe-call set whose each element asks a question stale by the next operation.
PROBES = frozenset({"exists", "isfile", "isdir", "islink", "access", "is_file",
                    "is_dir", "can_read", "can_write", "has_key"})

## Unordered leap-call set whose each element after a probe forms look-before-you-leap.
LEAPS = frozenset({"open", "read_text", "read_bytes", "unlink", "rmdir", "mkdir",
                   "write_text", "write_bytes", "remove", "rename", "replace"})

## Unordered protocol-marker set whose each element denotes structural rather than runtime type.
PROTOCOL_BASES = frozenset({"Protocol", "runtime_checkable"})


class BoundaryParsingCheck(ModuleCheck):
    """Reports NewType, isinstance against a Protocol, and look-before-you-leap."""

    ## Invoked as `python -m checks.boundary_parsing`.
    name = "boundary_parsing"
    ## The law/ERR and law/TYPE rules this check decides.
    ## Narrowed to what this check can actually REPORT. ERR-011, TYPE-011 and TYPE-012 were named
    ## here and never emitted, so they counted as `mechanized` while being
    ## decided by nothing -- and this module's own docstring said so in prose.
    ## `V080` rises as a result, which is the true number.
    ## Rule-id elements in deterministic reporting order actually decided here.
    rules = ("ERR-013", "TYPE-005", "TYPE-010")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for each of the three shapes.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- all three bind everywhere
        @return finding elements in AST walk and call-before-branch order
        """
        # Tests may intentionally construct the three prohibited boundary shapes.
        if is_test_path(path):
            # Stop iteration for the explicit test-code exemption.
            return
        # Build an unordered set whose each element is a locally declared protocol name.
        protocols = _protocol_names(tree)
        # Inspect calls that define NewType aliases or runtime-checkable protocols.
        for node in ast.walk(tree):
            # Calls may define a NewType or perform runtime protocol checking.
            if isinstance(node, ast.Call):
                # Yield any call-shape finding at this walk position.
                yield from self._call(node, path, protocols)
            # Positive branches may probe state before attempting an operation.
            elif isinstance(node, ast.If):
                # Yield any look-before-you-leap finding at this walk position.
                yield from self._leap(node, path)

    def _call(self, node: ast.Call, path: Path,
              protocols: set[str]) -> Iterator[Finding]:
        """Report `NewType` and `isinstance` against a structural contract.

        @param node the call expression
        @param path the file it came from
        @param protocols unordered set whose each element is a Protocol class defined here
        @return finding elements in checked-expression walk order, at most one per call
        """
        # Resolve the terminal called identifier for closed-shape classification.
        name = _called(node)
        # NewType announces a constraint while providing no parsing constructor.
        if name == "NewType":
            # Yield the unenforced-constrained-type finding at the call site.
            yield Finding(
                "TYPE-005", path, node.lineno,
                "`NewType` announces a constraint it cannot enforce",
                "Use a frozen wrapper with a parsing constructor. A NewType has "
                "no constructor, so nothing validates and the distinct type is "
                "a comment the checker happens to read.",
            )
        # Two-argument isinstance may misuse a locally declared Protocol as semantic proof.
        elif name == "isinstance" and len(node.args) == 2:  # ruff: ignore[magic-value-comparison] - isinstance takes two
            # Select the asserted runtime type expression.
            checked = node.args[1]
            # Inspect each nested syntax-node element in deterministic expression walk order.
            for named in ast.walk(checked):
                # A local protocol name proves the runtime check is structural only.
                if isinstance(named, ast.Name) and named.id in protocols:
                    # Yield one shape-not-contract finding at the isinstance call.
                    yield Finding(
                        "TYPE-010", path, node.lineno,
                        f"`isinstance` against the protocol `{named.id}` is a "
                        f"shape check, not a contract check",
                        "It answers whether the names are present, which a fake "
                        "with the wrong semantics also satisfies. Test against "
                        "the port's contract suite instead.",
                    )
                    # Stop after the first matching protocol so one call reports once.
                    break

    def _leap(self, node: ast.If, path: Path) -> Iterator[Finding]:
        """Report a probe of the world followed by the operation it guarded.

        Only the positive branch is examined. `if not p.exists(): create(p)` is
        a legitimate shape -- it acts on absence rather than racing to use
        presence -- and reporting it would make the check unusable.

        @param node the conditional
        @param path the file it came from
        @return zero or one finding element when a probe guards an anticipated operation
        """
        # A negated probe acts on absence and is outside the positive-race predicate.
        if any(isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)
               for n in ast.walk(node.test)):
            # Stop without misclassifying legitimate create-on-absence control flow.
            return
        # Build an unordered set whose each element is a called name in the condition.
        probed = {_called(n) for n in ast.walk(node.test) if isinstance(n, ast.Call)}
        # A condition without a recognized world-state probe cannot form the target race.
        if not probed & PROBES:
            # Stop without scanning the positive branch for unrelated operations.
            return
        # Build an unordered set whose each element is a called name in the positive branch.
        leapt = {_called(n) for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                 if isinstance(n, ast.Call)}
        # Intersect branch calls with the closed anticipated-operation set.
        taken = leapt & LEAPS
        # A recognized probe followed by a recognized leap exposes a race window.
        if taken:
            # Yield one aggregate race finding with both call-name sets sorted.
            yield Finding(
                "ERR-013", path, node.lineno,
                f"probes with {', '.join(sorted(probed & PROBES))} then calls "
                f"{', '.join(sorted(taken))}",
                "Try the operation and handle its failure. Between the probe and "
                "the call the answer can change, and the handler you needed "
                "anyway is the one that would have worked.",
            )


def _protocol_names(tree: ast.Module) -> set[str]:
    """Classes in this module that are structural contracts.

    @param tree the module's syntax tree
    @return unordered set whose each element names a class deriving from ``Protocol``
    """
    # Accumulate an unordered set whose each element is one local protocol class name.
    found: set[str] = set()
    # Inspect class definitions for local protocol bases and runtime-checkable decorators.
    for node in ast.walk(tree):
        # Only class definitions can declare protocol bases or decorators.
        if not isinstance(node, ast.ClassDef):
            # Skip non-class syntax because it cannot declare a local protocol.
            continue
        # Build an unordered set whose each element is a terminal base-class name.
        names = {
            (b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", ""))
            for b in node.bases
        }
        # Build an unordered set whose each element is a terminal decorator name.
        decorators = {_called(d) if isinstance(d, ast.Call) else
                      getattr(d, "id", "") for d in node.decorator_list}
        # Either structural base or runtime-checkable marker makes the class a protocol.
        if names & PROTOCOL_BASES or decorators & PROTOCOL_BASES:
            # Add the unique local class identity to the protocol-name set.
            found.add(node.name)
    # Return every discovered protocol identity without implied order.
    return found


def _called(node: ast.expr) -> str:
    """The trailing identifier of whatever an expression calls or names.

    @param node the expression
    @return the name, or the empty string when there is none
    """
    # Select the called function expression or the supplied naming expression itself.
    target = node.func if isinstance(node, ast.Call) else node
    # Qualified expressions expose their terminal attribute identifier.
    if isinstance(target, ast.Attribute):
        # Return the final attribute spelling.
        return target.attr
    # Return a bare identifier or empty text for another expression form.
    return getattr(target, "id", "")


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(BoundaryParsingCheck()))
