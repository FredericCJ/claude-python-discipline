"""Every element carries a documentation comment, including the ones with no docstring slot.

Enforces DOC-001 (modules, classes, callables), DOC-002 (module constants, class
attributes, dataclass fields, enum members) and DOC-003 (checked in the ordinary
gate, not in a documentation job).

The division of labour matters. ruff's D1 rules see docstrings and nothing else;
Doxygen sees both forms but only runs where it is installed. This check is the
only one that can require a `##` block on a bare assignment, and the only one
that runs everywhere. See discipline/fact/doxygen.md.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from pathlib import Path

from . import Check, Finding, is_test_path, main

## Names that carry no contract of their own and are documented by their owner.
EXEMPT_NAMES = frozenset({"__all__", "__version__", "__author__", "_", "__"})

## Decorators that mark a class whose annotated attributes are its public shape.
FIELD_CLASS_DECORATORS = frozenset({"dataclass", "define", "frozen"})


class DocCoverageCheck(Check):
    """Report elements with no documentation comment of any accepted form."""

    ## Invoked as `python -m checks.doc_coverage`.
    name = "doc_coverage"
    ## The law/DOC rules this check decides.
    rules = ("DOC-001", "DOC-002", "DOC-003")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield one finding per undocumented element in `tree`.

        @param tree the parsed module
        @param path the file it came from, used for reporting
        @param layer the architectural layer, unused here
        @return findings for every element lacking documentation
        """
        source = path.read_text(encoding="utf-8").splitlines()

        if ast.get_docstring(tree) is None:
            yield Finding(
                "DOC-001", path, 1,
                "module has no docstring",
                'Open the file with a """! summary; it is what every index shows.',
            )

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                yield from self._class(node, path, source)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from self._callable(node, path)

        yield from self._module_values(tree, path, source)

    def _callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                  path: Path) -> Iterator[Finding]:
        """Report a function or method with no docstring.

        @param node the callable
        @param path the file it came from
        @return one finding when the docstring is absent
        """
        if ast.get_docstring(node) is not None or _is_overload(node):
            return
        yield Finding(
            "DOC-001", path, node.lineno,
            f"{node.name}() has no docstring",
            "State what it guarantees: parameters, result, and when it fails.",
        )

    def _class(self, node: ast.ClassDef, path: Path,
               source: list[str]) -> Iterator[Finding]:
        """Report an undocumented class and any undocumented attribute in it.

        @param node the class definition
        @param path the file it came from
        @param source the file's lines, for finding `##` blocks
        @return findings for the class and its attributes
        """
        if ast.get_docstring(node) is None:
            yield Finding(
                "DOC-001", path, node.lineno,
                f"class {node.name} has no docstring",
                "State what the type represents and what holds of every instance.",
            )
        is_enum = any(_name_of(base).endswith(("Enum", "Flag")) for base in node.bases)
        for statement in node.body:
            for target, lineno in _named_assignments(statement):
                if target in EXEMPT_NAMES or (target.startswith("__") and not is_enum):
                    continue
                if _has_hash_block(source, lineno) or _has_trailing_block(source, lineno):
                    continue
                what = "enum member" if is_enum else "attribute"
                yield Finding(
                    "DOC-002", path, lineno,
                    f"{what} {node.name}.{target} has no `##` comment",
                    "Python has no docstring slot here; document it with a ## block above.",
                )

    def _module_values(self, tree: ast.Module, path: Path,
                       source: list[str]) -> Iterator[Finding]:
        """Report module-level constants with no `##` block.

        @param tree the parsed module
        @param path the file it came from
        @param source the file's lines, for finding `##` blocks
        @return findings for undocumented module-level values
        """
        for statement in tree.body:
            for target, lineno in _named_assignments(statement):
                # Private module values are documented too: "every element" is the
                # rule, and Doxygen reports them under EXTRACT_PRIVATE. Two
                # mechanisms disagreeing is worse than either one alone.
                if target in EXEMPT_NAMES:
                    continue
                if _has_hash_block(source, lineno) or _has_trailing_block(source, lineno):
                    continue
                yield Finding(
                    "DOC-002", path, lineno,
                    f"module constant {target} has no `##` comment",
                    "Document it with a ## block above; a bare name states nothing.",
                )


def _named_assignments(statement: ast.stmt) -> Iterator[tuple[str, int]]:
    """Names bound by one statement, with the line each was bound on.

    @param statement a statement from a module or class body
    @return pairs of bound name and line number
    """
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        yield statement.target.id, statement.lineno
    elif isinstance(statement, ast.Assign):
        for target in statement.targets:
            if isinstance(target, ast.Name):
                yield target.id, statement.lineno


def _has_hash_block(source: list[str], lineno: int) -> bool:
    """Whether a `##` comment block sits immediately above `lineno`.

    @param source the file's lines
    @param lineno the 1-based line of the element
    @return True when a ## block precedes it, allowing intervening `#` continuation
    """
    index = lineno - 2
    while index >= 0:
        line = source[index].strip()
        if line.startswith("##"):
            return True
        # A Doxygen block opens with ## and continues with plain #, so keep
        # walking up through continuation lines before giving up.
        if line.startswith("#"):
            index -= 1
            continue
        break
    return False


def _has_trailing_block(source: list[str], lineno: int) -> bool:
    """Whether a `##<` block documents the element on its own line.

    @param source the file's lines
    @param lineno the 1-based line of the element
    @return True when the line carries a trailing ##< comment
    """
    if 0 <= lineno - 1 < len(source):
        return "##<" in source[lineno - 1]
    return False


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    r"""Whether a callable is a typing overload stub, which documents nothing.

    @param node the callable
    @return True when it carries an \@overload decorator
    """
    return any(_name_of(d) in {"overload", "typing.overload"} for d in node.decorator_list)


def _name_of(node: ast.expr) -> str:
    """A dotted name for an expression used as a decorator or base class.

    @param node the expression
    @return its dotted name, or the empty string when it is not a name
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_name_of(node.value)}.{node.attr}".lstrip(".")
    if isinstance(node, ast.Call):
        return _name_of(node.func)
    return ""


if __name__ == "__main__":
    raise SystemExit(main(DocCoverageCheck()))
