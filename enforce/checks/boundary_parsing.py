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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Calls that ask the world a question whose answer is stale by the next line.
PROBES = frozenset({"exists", "isfile", "isdir", "islink", "access", "is_file",
                    "is_dir", "can_read", "can_write", "has_key"})

## Operations whose failure the probe was trying to avoid. A probe followed by
## one of these in the same branch is the look-before-you-leap shape.
LEAPS = frozenset({"open", "read_text", "read_bytes", "unlink", "rmdir", "mkdir",
                   "write_text", "write_bytes", "remove", "rename", "replace"})

## Bases that make a class a structural contract rather than a runtime type.
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
    rules = ("ERR-013", "TYPE-005", "TYPE-010")

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for each of the three shapes.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param _layer the architectural layer, unused -- all three bind everywhere
        @return one finding per violation
        """
        if is_test_path(path):
            return
        protocols = _protocol_names(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                yield from self._call(node, path, protocols)
            elif isinstance(node, ast.If):
                yield from self._leap(node, path)

    def _call(self, node: ast.Call, path: Path,
              protocols: set[str]) -> Iterator[Finding]:
        """Report `NewType` and `isinstance` against a structural contract.

        @param node the call expression
        @param path the file it came from
        @param protocols Protocol classes defined in this module
        @return one finding per offending call
        """
        name = _called(node)
        if name == "NewType":
            yield Finding(
                "TYPE-005", path, node.lineno,
                "`NewType` announces a constraint it cannot enforce",
                "Use a frozen wrapper with a parsing constructor. A NewType has "
                "no constructor, so nothing validates and the distinct type is "
                "a comment the checker happens to read.",
            )
        elif name == "isinstance" and len(node.args) == 2:  # ruff: ignore[magic-value-comparison] - isinstance takes two
            checked = node.args[1]
            for named in ast.walk(checked):
                if isinstance(named, ast.Name) and named.id in protocols:
                    yield Finding(
                        "TYPE-010", path, node.lineno,
                        f"`isinstance` against the protocol `{named.id}` is a "
                        f"shape check, not a contract check",
                        "It answers whether the names are present, which a fake "
                        "with the wrong semantics also satisfies. Test against "
                        "the port's contract suite instead.",
                    )
                    break

    def _leap(self, node: ast.If, path: Path) -> Iterator[Finding]:
        """Report a probe of the world followed by the operation it guarded.

        Only the positive branch is examined. `if not p.exists(): create(p)` is
        a legitimate shape -- it acts on absence rather than racing to use
        presence -- and reporting it would make the check unusable.

        @param node the conditional
        @param path the file it came from
        @return one finding when a probe guards the operation it anticipates
        """
        if any(isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not)
               for n in ast.walk(node.test)):
            return
        probed = {_called(n) for n in ast.walk(node.test) if isinstance(n, ast.Call)}
        if not probed & PROBES:
            return
        leapt = {_called(n) for n in ast.walk(ast.Module(body=node.body, type_ignores=[]))
                 if isinstance(n, ast.Call)}
        taken = leapt & LEAPS
        if taken:
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
    @return the names of classes deriving from `Protocol`
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        names = {
            (b.attr if isinstance(b, ast.Attribute) else getattr(b, "id", ""))
            for b in node.bases
        }
        decorators = {_called(d) if isinstance(d, ast.Call) else
                      getattr(d, "id", "") for d in node.decorator_list}
        if names & PROTOCOL_BASES or decorators & PROTOCOL_BASES:
            found.add(node.name)
    return found


def _called(node: ast.expr) -> str:
    """The trailing identifier of whatever an expression calls or names.

    @param node the expression
    @return the name, or the empty string when there is none
    """
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Attribute):
        return target.attr
    return getattr(target, "id", "")


if __name__ == "__main__":
    raise SystemExit(main(BoundaryParsingCheck()))
