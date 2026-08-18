"""The domain stays pure, typed, and free of foreign vocabulary.

Enforces ARCH-002 (no I/O-capable import), ARCH-013 (no framework or transport
types in domain signatures), TYPE-002 (no `Any`), TYPE-006 (closed sets are
enumerations, not literal unions) and TYPE-007 (domain values are frozen and
slotted).

The import half overlaps with the import-linter contract deliberately: that one
sees the transitive graph, this one sees the line and can name it.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from . import Check, Finding, is_test_path, main

## Anything that can reach outside the process, or make a result irreproducible.
IO_MODULES = frozenset({
    "os", "io", "pathlib", "socket", "subprocess", "shutil", "tempfile",
    "sqlite3", "http", "urllib", "requests", "httpx", "asyncio", "threading",
    "multiprocessing", "random", "secrets", "time", "datetime", "logging",
    "argparse", "sys", "pickle", "webbrowser",
})

## Types owned by a framework or a transport. A domain modelled in these is
## coupled to them at every call site (ARCH-013).
FOREIGN_TYPES = frozenset({
    "Namespace", "Request", "Response", "Session", "Connection", "Cursor",
    "BaseModel", "Element", "ElementTree", "DataFrame", "Series", "ndarray",
})


class DomainPurityCheck(Check):
    """Rejects a domain module that reaches outside itself or borrows a foreign type.

    Also rejects an unfrozen domain dataclass and a closed set written as a
    literal union, in three independent passes over the same tree.

    Applies to nothing else. A file whose *first* layer segment is not `domain`,
    and any test file, is parsed and then let through untouched -- so a domain
    package nested under `adapters/` is never examined at all.
    """

    ## Invoked as `python -m checks.domain_purity`.
    name = "domain_purity"
    ## The law/ARCH and law/TYPE rules this mechanism decides.
    rules = ("ARCH-002", "ARCH-013", "TYPE-002", "TYPE-006", "TYPE-007")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for one module, silent outside the domain layer.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; anything but `domain` is skipped
        @return findings from the import, annotation and dataclass passes in turn
        """
        if layer != "domain" or is_test_path(path):
            return
        yield from self._imports(tree, path)
        yield from self._annotations(tree, path)
        yield from self._dataclasses(tree, path)

    def _imports(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report each import whose root package can reach outside the process.

        Matching is on the root package, so `os.path` is judged as `os`, and a
        module imported for a pure helper is caught along with the rest -- the
        rule is about what the dependency permits, not what this line uses.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return one ARCH-002 finding per offending name, so `import os, sys`
            yields two, both at the statement's line
        """
        for node in ast.walk(tree):
            for module, lineno in _imported_modules(node):
                root = module.split(".", 1)[0]
                if root in IO_MODULES:
                    yield Finding(
                        "ARCH-002", path, lineno,
                        f"domain imports `{module}`, which can perform I/O",
                        "Move the effect behind a port and take it as a parameter (ARCH-005).",
                    )

    def _annotations(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report `Any`, borrowed types and literal unions in function signatures.

        Only parameters and returns are examined. A local variable's annotation
        binds nobody; a signature's is the contract every caller is held to.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return TYPE-002, ARCH-013 and TYPE-006 findings, at the annotation's line
        """
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for annotation in _annotations_of(node):
                for name in _names_in(annotation):
                    if name == "Any":
                        yield Finding(
                            "TYPE-002", path, annotation.lineno,
                            "`Any` in a domain signature",
                            "Name the real type; `Any` disables every downstream guarantee.",
                        )
                    elif name in FOREIGN_TYPES:
                        yield Finding(
                            "ARCH-013", path, annotation.lineno,
                            f"framework or transport type `{name}` in a domain signature",
                            "Translate to a domain type at the boundary (ARCH-014).",
                        )
                if _is_literal_union(annotation):
                    yield Finding(
                        "TYPE-006", path, annotation.lineno,
                        "closed set written as a union of literals",
                        "Use an enumeration; it has one definition site exhaustiveness follows.",
                    )

    def _dataclasses(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a domain dataclass declared without both `frozen` and `slots`.

        A keyword given a non-literal value counts as absent, since the check
        cannot prove what it evaluates to and must not assume the safe answer.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return one TYPE-007 finding per class, naming which keywords are missing
        """
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for decorator in node.decorator_list:
                if not _is_dataclass(decorator):
                    continue
                kwargs = _decorator_kwargs(decorator)
                missing = [k for k in ("frozen", "slots") if kwargs.get(k) is not True]
                if missing:
                    yield Finding(
                        "TYPE-007", path, node.lineno,
                        f"domain dataclass `{node.name}` is not {' and '.join(missing)}",
                        "Use @dataclass(frozen=True, slots=True); a value that can drift "
                        "between validation and use cannot be named in an error.",
                    )


def _imported_modules(node: ast.AST) -> Iterator[tuple[str, int]]:
    """The modules one statement brings in, each with the line that brought it.

    Relative imports yield nothing. A sibling module can of course reach an
    effect in turn, but that is a transitive fact only the import-linter contract
    can see; this one answers for the line in front of it.

    @param node any node; only import statements produce anything
    @return each imported module's dotted name paired with its line
    """
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name, node.lineno
    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        yield node.module, node.lineno


def _annotations_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.expr]:
    """Every annotation that forms part of a function's published contract.

    Positional-only, positional-or-keyword and keyword-only parameters, plus
    `*args`, `**kwargs` and the return. Positions left unannotated are simply
    absent; a missing annotation is the type checker's business, not this
    check's.

    @param node the function definition
    @return the annotation expressions, parameters first and the return last
    """
    args = node.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
        if arg is not None and arg.annotation is not None:
            yield arg.annotation
    if node.returns is not None:
        yield node.returns


def _names_in(annotation: ast.expr) -> Iterator[str]:
    """Every identifier mentioned anywhere inside an annotation.

    A dotted name contributes every segment it is built from, so `pd.DataFrame`
    yields both `DataFrame` and `pd`. That is what lets a foreign type be
    recognized by its own name, however the module in front of it was aliased.

    @param annotation the annotation expression
    @return the bare identifiers, in traversal order, duplicates included
    """
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr


def _is_literal_union(annotation: ast.expr) -> bool:
    """Whether an annotation spells a closed set out as constants inline.

    A one-member `Literal` passes: it pins a single value rather than declaring a
    set of cases that later code must stay exhaustive over. A member that is not
    a constant also passes, since the set is then not closed in the first place.

    @param annotation the annotation expression, searched to any depth
    @return True when some nested `Literal` holds more than one constant
    """
    for node in ast.walk(annotation):
        if not isinstance(node, ast.Subscript):
            continue
        base = node.value
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        if name != "Literal":
            continue
        target = node.slice
        members = target.elts if isinstance(target, ast.Tuple) else [target]
        if len(members) > 1 and all(isinstance(m, ast.Constant) for m in members):
            return True
    return False


def _is_dataclass(decorator: ast.expr) -> bool:
    """Whether a decorator is `dataclass`, written bare or called with keywords.

    Recognized by the name on the line, so an alias or a locally wrapped
    decorator escapes. The check reports on what a reader of the file can see.

    @param decorator one entry of a class's decorator list
    @return True when the trailing identifier is `dataclass`
    """
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
    return name == "dataclass"


def _decorator_kwargs(decorator: ast.expr) -> dict[str, object]:
    """The literal keyword arguments a decorator was applied with.

    A value the tree cannot evaluate -- a name, a call, `**kwargs` -- is omitted
    rather than guessed. The constants that survive are returned raw, so a caller
    asking for `frozen=True` must compare against `True` itself: `frozen=1` is
    true enough for Python and is not the declaration the rule asks for.

    @param decorator one entry of a class's decorator list
    @return keyword name mapped to its constant value; empty when not a call
    """
    if not isinstance(decorator, ast.Call):
        return {}
    return {
        kw.arg: kw.value.value
        for kw in decorator.keywords
        if kw.arg is not None and isinstance(kw.value, ast.Constant)
    }


if __name__ == "__main__":
    raise SystemExit(main(DomainPurityCheck()))
