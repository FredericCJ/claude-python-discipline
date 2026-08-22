"""Every element carries a documentation comment, including the ones with no docstring slot.

Enforces DOC-001 (modules, classes, callables), DOC-002 (module constants, class
attributes, dataclass fields, enum members), DOC-007 (Doxygen parameter/result
records), and DOC-014 (the engine selection is explicit). DOC-003 is the separate
gate obligation that schedules this mechanism outside a documentation-build job.

The division of labour matters. ruff's D1 rules see docstrings and nothing else;
Doxygen sees both forms but only runs where it is installed. This check is the
only one that can require a `##` block on a bare assignment, and the only one
that runs everywhere. See discipline/fact/doxygen.md.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, main

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Names that carry no contract of their own and are documented by their owner.
EXEMPT_NAMES = frozenset({"__all__", "__version__", "__author__", "_", "__"})

## A documented parameter, however the meaning is phrased after the name.
_DOC_PARAM = re.compile(r"@param\s+\**(\w+)")

## A documented result, in either spelling Doxygen accepts.
_DOC_RETURN = re.compile(r"@(?:returns?|retval)\b")

## Decorators that mark a class whose annotated attributes are its public shape.
FIELD_CLASS_DECORATORS = frozenset({"dataclass", "define", "frozen"})


class DocCoverageCheck(ModuleCheck):
    """Report elements with no documentation comment of any accepted form."""

    ## Invoked as `python -m checks.doc_coverage`.
    name = "doc_coverage"
    ## The law/DOC rules this check decides.
    ## DOC-003 belongs to the gate that schedules this mechanism; the remaining
    ## ids are predicates this class itself can report.
    rules = ("DOC-001", "DOC-002", "DOC-007", "DOC-014")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Report an undeclared engine once, then inspect documentation content.

        @param paths project source files or roots
        @return declaration finding followed by element findings
        """
        findings = super().run(paths)
        if self.declaration.doc_engine_declared or not paths:
            return findings
        subject = self.declaration.source or paths[0]
        if subject.is_dir():
            subject /= "pyproject.toml"
        return [
            Finding(
                "DOC-014", subject, 1,
                "project declares no documentation engine",
                "Set doc_engine explicitly to doxygen, sphinx, or none in "
                "[tool.agent-discipline]. An implicit default can silently "
                "deactivate engine-specific checks.",
                diagnostic_id="DOC_ENGINE_UNDECLARED",
            ),
            *findings,
        ]

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield one finding per undocumented element in `tree`.

        @param tree the parsed module
        @param path the file it came from, used for reporting
        @param _layer the architectural layer, unused here
        @return findings for every element lacking documentation
        """
        source = path.read_text(encoding="utf-8").splitlines()

        if ast.get_docstring(tree) is None:
            yield Finding(
                "DOC-001", path, 1,
                "module has no docstring",
                'Open the file with a """! summary; it is what every index shows.',
            )

        # DOC-002 and DOC-007 describe one engine's comment syntax -- the `##`
        # block and the `@param`/`@return` tags Doxygen reads. DOC-001 and
        # DOC-003 describe whether an element is documented at all, which is
        # engine-independent. Applying all four unconditionally produced 1,064
        # findings of form against 18 of substance on a codebase documenting in
        # another convention; a check with that ratio gets switched off.
        forms = self.declaration.doc_engine == "doxygen"

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                yield from self._class(node, path, source, forms=forms)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                yield from self._callable(node, path, forms=forms)

        if forms:
            yield from self._module_values(tree, path, source)

    def _callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef,
                  path: Path, *, forms: bool) -> Iterator[Finding]:
        """Report a function or method with no docstring.

        @param node the callable
        @param path the file it came from
        @param forms whether the declared engine reads `@param`/`@return`, which
            decides whether per-parameter completeness is checked at all
        @return one finding when the docstring is absent, plus DOC-007 findings
            under an engine that reads the tags
        """
        if _is_overload(node):
            return
        docstring = ast.get_docstring(node)
        if docstring is None:
            yield Finding(
                "DOC-001", path, node.lineno,
                f"{node.name}() has no docstring",
                "State what it guarantees: parameters, result, and when it fails.",
            )
            return
        if forms:
            yield from _completeness(node, docstring, path)

    def _class(self, node: ast.ClassDef, path: Path,
               source: list[str], *, forms: bool) -> Iterator[Finding]:
        """Report an undocumented class and any undocumented attribute in it.

        @param node the class definition
        @param path the file it came from
        @param source the file's lines, for finding `##` blocks
        @param forms whether the declared engine reads `##` blocks; when it does
            not, the class itself is still required to be documented but its
            attributes are not held to a syntax nothing reads
        @return findings for the class and, under a `##`-reading engine, its
            attributes
        """
        if ast.get_docstring(node) is None:
            yield Finding(
                "DOC-001", path, node.lineno,
                f"class {node.name} has no docstring",
                "State what the type represents and what holds of every instance.",
            )
        if not forms:
            return
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


def _completeness(node: ast.FunctionDef | ast.AsyncFunctionDef, docstring: str,
                  path: Path) -> Iterator[Finding]:
    """Report parameters and results a docstring leaves undocumented.

    Owned here rather than left to Doxygen because Doxygen's Python parser does
    not treat `-> None` as void: it demands an @return for a function that
    returns nothing, which was 142 false demands on this repository alone. This
    check reads the annotation and asks only for what is actually returned.

    A `test_` function's parameters are fixtures, supplied by name rather than
    by a caller. Their meaning belongs at the fixture, once, and restating it at
    each of 130 call sites is the filler DOC-013 exists to refuse. Helpers in a
    test file are ordinary callables and are held to the rule.

    @param node the documented callable
    @param docstring its docstring
    @param path the file it came from
    @return one finding per undocumented parameter, and one for a missing result
    """
    documented = set(_DOC_PARAM.findall(docstring))
    for name in () if node.name.startswith("test_") else _parameter_names(node):
        if name not in documented:
            yield Finding(
                "DOC-007", path, node.lineno,
                f"{node.name}(): parameter `{name}` is not documented",
                f"Add `@param {name} <what it means>` -- the signature already "
                f"carries its type.",
            )
    if _returns_a_value(node) and not _DOC_RETURN.search(docstring):
        yield Finding(
            "DOC-007", path, node.lineno,
            f"{node.name}(): the result is not documented",
            "Add `@return <what the value signifies>`.",
        )


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[str]:
    """Every parameter a caller supplies, in signature order.

    @param node the callable
    @return each parameter name, excluding the implicit self and cls
    """
    args = node.args
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        if arg.arg not in {"self", "cls"}:
            yield arg.arg
    for variadic in (args.vararg, args.kwarg):
        if variadic is not None:
            yield variadic.arg


def _returns_a_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the callable's annotation promises something back.

    An unannotated function is not pressed for an @return: the missing
    annotation is a typing defect that TYPE-001 owns, and reporting it twice
    under two rules helps nobody.

    @param node the callable
    @return True when the return annotation is anything but None
    """
    returns = node.returns
    if returns is None:
        return False
    return not (isinstance(returns, ast.Constant) and returns.value is None)


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
