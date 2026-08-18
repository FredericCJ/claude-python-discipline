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
    name = "domain_purity"
    rules = ("ARCH-002", "ARCH-013", "TYPE-002", "TYPE-006", "TYPE-007")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        if layer != "domain" or is_test_path(path):
            return
        yield from self._imports(tree, path)
        yield from self._annotations(tree, path)
        yield from self._dataclasses(tree, path)

    def _imports(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
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
    if isinstance(node, ast.Import):
        for alias in node.names:
            yield alias.name, node.lineno
    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        yield node.module, node.lineno


def _annotations_of(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[ast.expr]:
    args = node.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
        if arg is not None and arg.annotation is not None:
            yield arg.annotation
    if node.returns is not None:
        yield node.returns


def _names_in(annotation: ast.expr) -> Iterator[str]:
    for node in ast.walk(annotation):
        if isinstance(node, ast.Name):
            yield node.id
        elif isinstance(node, ast.Attribute):
            yield node.attr


def _is_literal_union(annotation: ast.expr) -> bool:
    """`Literal["a", "b"]` with more than one member, or a union of Literals."""
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
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
    return name == "dataclass"


def _decorator_kwargs(decorator: ast.expr) -> dict[str, object]:
    if not isinstance(decorator, ast.Call):
        return {}
    return {
        kw.arg: kw.value.value
        for kw in decorator.keywords
        if kw.arg is not None and isinstance(kw.value, ast.Constant)
    }


if __name__ == "__main__":
    raise SystemExit(main(DomainPurityCheck()))
