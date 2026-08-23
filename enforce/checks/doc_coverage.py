"""Every element carries a documentation comment, including the ones with no docstring slot.

Enforces DOC-001 (modules, classes, callables), DOC-002 (module constants, class
attributes, dataclass fields, enum members), DOC-007 (Doxygen parameter/result
records), DOC-014 (the engine selection is explicit), and DOC-016 (every local
binding resolves to ordinary semantic narration). DOC-003 is the separate
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
from .comment_association import associate, bindings, comment_blocks, semantic_associations
from .documentation_model import governed_paths

# Import static traversal and path contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Unordered name set whose each element carries no contract beyond its owner.
EXEMPT_NAMES = frozenset({"__all__", "__version__", "__author__", "_", "__"})

## A documented parameter, however the meaning is phrased after the name.
_DOC_PARAM = re.compile(r"@param\s+\**(\w+)")

## A documented result, in either spelling Doxygen accepts.
_DOC_RETURN = re.compile(r"@(?:returns?|retval)\b")

## Unordered decorator-name set whose each element marks fields as the class's public shape.
FIELD_CLASS_DECORATORS = frozenset({"dataclass", "define", "frozen"})


class DocCoverageCheck(ModuleCheck):
    """Report elements with no documentation comment of any accepted form."""

    ## Invoked as `python -m checks.doc_coverage`.
    name = "doc_coverage"
    ## The law/DOC rules this check decides.
    ## DOC-003 belongs to the gate that schedules this mechanism; the remaining
    ## Each ordered id is a predicate this class itself can report.
    rules = ("DOC-001", "DOC-002", "DOC-007", "DOC-014", "DOC-016")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Report an undeclared engine once, then inspect documentation content.

        @param paths project path elements in caller order, used as fallback and subject evidence
        @return finding elements ordered with the declaration defect before source findings
        """
        # Run entity and binding coverage over the model-governed source sequence first.
        findings = super().run(governed_paths(self.declaration, paths))
        # An explicit engine satisfies DOC-014; an empty fallback has no declaration subject.
        if self.declaration.doc_engine_declared or not paths:
            # Return the ordered source findings without an engine-selection prefix.
            return findings
        # Prefer the declaration artifact, falling back to the caller's first path element.
        subject = self.declaration.source or paths[0]
        # Directory input reports the exact conventional declaration path needing an edit.
        if subject.is_dir():
            # Point the finding at the project file rather than an imprecise directory.
            subject /= "pyproject.toml"
        # Prefix the ordered source findings with the one actionable engine declaration defect.
        return [
            Finding(
                "DOC-014",
                subject,
                1,
                "project declares no documentation engine",
                "Set doc_engine explicitly to doxygen in [tool.agent-discipline]. "
                "An implicit default can silently deactivate structured checks.",
                diagnostic_id="DOC_ENGINE_UNDECLARED",
            ),
            *findings,
        ]

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield one finding per undocumented element in `tree`.

        @param tree the parsed module
        @param path the file it came from, used for reporting
        @param _layer the architectural layer, unused here
        @return finding elements in AST order for every undocumented entity or binding
        @par Effects Reads the governed source file without modifying repository state.
        """
        # Read the source once for Doxygen blocks and ordinary-comment association.
        text = path.read_text(encoding="utf-8")
        # Preserve each source line in lexical order without newline terminators.
        source = text.splitlines()
        # Preserve each ordinary implementation-comment block in lexical source order.
        ordinary_blocks = comment_blocks(text)
        # Resolve suite-aware semantic owners once for all local binding subjects.
        associations = semantic_associations(tree, text, ordinary_blocks)

        # A missing module contract leaves the generated documentation index unnamed.
        if ast.get_docstring(tree) is None:
            # Report the module at line one with the Doxygen-readable summary remediation.
            yield Finding(
                "DOC-001",
                path,
                1,
                "module has no docstring",
                'Open the file with a """! summary; it is what every index shows.',
            )

        # DOC-002 and DOC-007 describe one engine's comment syntax -- the `##`
        # block and the `@param`/`@return` tags Doxygen reads. DOC-001 and
        # DOC-003 describe whether an element is documented at all, which is
        # engine-independent. Applying all four unconditionally produced 1,064
        # findings of form against 18 of substance on a codebase documenting in
        # another convention; a check with that ratio gets switched off.
        # True means Doxygen forms are required; false retains engine-independent entity checks.
        forms = self.declaration.doc_engine == "doxygen"

        # Inspect every nested definition for callable and class entity coverage.
        for node in ast.walk(tree):
            # Class definitions own their contract and applicable field/attribute documentation.
            if isinstance(node, ast.ClassDef):
                # Yield each class or attribute finding while preserving traversal order.
                yield from self._class(node, path, source, forms=forms)
            # Function and asynchronous function definitions share callable completeness rules.
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Yield each callable and structured-signature finding in traversal order.
                yield from self._callable(node, path, forms=forms)

        # Doxygen projects additionally require module-value entity blocks.
        if forms:
            # Yield each undocumented module assignment in source statement order.
            yield from self._module_values(tree, path, source)

        # Inspect every local binding subject in stable source position and name order.
        for binding in bindings(tree):
            # Reuse suite-aware ownership, falling back to direct adjacency for isolated nodes.
            association = associations.get(
                binding.owner_node, associate(binding.owner_node, ordinary_blocks)
            )
            # A unique owner fully satisfies the mechanically decidable association proposition.
            if association.owner is not None:
                # Continue to the next local binding without duplicating semantic-content checks.
                continue
            # Multiple candidates require an explicit one-owner repair.
            if association.ambiguous:
                # Define the precise ambiguity wording used in the eventual finding.
                problem = "has multiple possible implementation-comment owners"
                # Explain how to reduce candidate ownership to one stable block.
                remedy = (
                    "Remove the competing comment or move one block directly above the "
                    "semantic step so this binding has exactly one owner."
                )
                # Select the stable diagnostic subtype for ambiguous local ownership.
                diagnostic = "LOCAL_BINDING_AMBIGUOUS"
            # No candidate requires a new ordinary semantic-step comment.
            else:
                # Define the precise absence wording used in the eventual finding.
                problem = "has no associated implementation comment"
                # Explain the owner location and semantic content required for this binding.
                remedy = (
                    "Add one ordinary `#` block immediately above its semantic step; "
                    "state what the value represents in that operation."
                )
                # Select the stable diagnostic subtype for undocumented local ownership.
                diagnostic = "LOCAL_BINDING_UNDOCUMENTED"
            # Emit one localized binding finding with its shape, name, and exact remediation.
            yield Finding(
                "DOC-016",
                path,
                binding.line,
                f"{binding.shape} `{binding.name}` {problem}",
                remedy,
                diagnostic_id=diagnostic,
            )

    def _callable(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef, path: Path, *, forms: bool
    ) -> Iterator[Finding]:
        """Report a function or method with no docstring.

        @param node the callable
        @param path the file it came from
        @param forms true when Doxygen requires `@param`/`@return` completeness;
            false when another engine leaves those structured forms unchecked
        @return one finding when the docstring is absent, plus DOC-007 findings
            under an engine that reads the tags
        """
        # Typing overload stubs borrow the concrete implementation's callable contract.
        if _is_overload(node):
            # Produce no duplicate documentation demand for a signature-only stub.
            return
        # Read the callable's cleaned entity contract from its Python docstring slot.
        docstring = ast.get_docstring(node)
        # An absent callable contract fails entity coverage before structured completeness.
        if docstring is None:
            # Report the callable at its definition with the contract content required.
            yield Finding(
                "DOC-001",
                path,
                node.lineno,
                f"{node.name}() has no docstring",
                "State what it guarantees: parameters, result, and when it fails.",
            )
            # Stop because parameter/result completeness has no documentation owner to inspect.
            return
        # A Doxygen project requires mechanically parseable parameter and result records.
        if forms:
            # Yield each missing structured field from the present callable contract.
            yield from _completeness(node, docstring, path)

    def _class(
        self, node: ast.ClassDef, path: Path, source: list[str], *, forms: bool
    ) -> Iterator[Finding]:
        """Report an undocumented class and any undocumented attribute in it.

        @param node the class definition
        @param path the file it came from
        @param source ordered source-line elements, each inspected for adjacent `##` blocks
        @param forms true when Doxygen requires attribute `##` blocks; false when
            another engine retains only the engine-independent class contract
        @return findings for the class and, under a `##`-reading engine, its
            attributes
        """
        # Every class has a Python docstring slot regardless of the structured engine form.
        if ast.get_docstring(node) is None:
            # Report the missing type representation and invariant contract.
            yield Finding(
                "DOC-001",
                path,
                node.lineno,
                f"class {node.name} has no docstring",
                "State what the type represents and what holds of every instance.",
            )
        # Non-Doxygen projects are not held to a hash-block syntax their engine cannot read.
        if not forms:
            # Stop after the engine-independent class entity check.
            return
        # True means a base class marks assignments as enum members; false means attributes.
        is_enum = any(_name_of(base).endswith(("Enum", "Flag")) for base in node.bases)
        # Inspect each direct class-body statement in source order.
        for statement in node.body:
            # Inspect every simple named assignment exposed by this statement.
            for target, lineno in _named_assignments(statement):
                # Exempt owner-documented protocol names and non-enum double-underscore machinery.
                if target in EXEMPT_NAMES or (target.startswith("__") and not is_enum):
                    # Continue with the next class value without demanding redundant prose.
                    continue
                # Either an immediately preceding block or a same-line trailing block owns it.
                if _has_hash_block(source, lineno) or _has_trailing_block(source, lineno):
                    # Continue when Doxygen can attach the present value documentation.
                    continue
                # Choose the user-facing entity category from the closed enum/class alternative.
                what = "enum member" if is_enum else "attribute"
                # Report the exact class value and its required Doxygen allocation form.
                yield Finding(
                    "DOC-002",
                    path,
                    lineno,
                    f"{what} {node.name}.{target} has no `##` comment",
                    "Python has no docstring slot here; document it with a ## block above.",
                )

    def _module_values(self, tree: ast.Module, path: Path, source: list[str]) -> Iterator[Finding]:
        """Report module-level constants with no `##` block.

        @param tree the parsed module
        @param path the file it came from
        @param source ordered source-line elements, each inspected for adjacent `##` blocks
        @return findings for undocumented module-level values
        """
        # Inspect each direct module-body statement in source order.
        for statement in tree.body:
            # Inspect every simple named assignment exposed by this statement.
            for target, lineno in _named_assignments(statement):
                # Private module values are documented too: "every element" is the
                # rule, and Doxygen reports them under EXTRACT_PRIVATE. Two
                # mechanisms disagreeing is worse than either one alone.
                # Owner-documented protocol names carry no independent entity contract.
                if target in EXEMPT_NAMES:
                    # Continue to the next module value without redundant documentation.
                    continue
                # Either an immediately preceding block or a same-line trailing block owns it.
                if _has_hash_block(source, lineno) or _has_trailing_block(source, lineno):
                    # Continue when Doxygen can attach the present value documentation.
                    continue
                # Report the exact undocumented module value and its allocation form.
                yield Finding(
                    "DOC-002",
                    path,
                    lineno,
                    f"module constant {target} has no `##` comment",
                    "Document it with a ## block above; a bare name states nothing.",
                )


def _completeness(
    node: ast.FunctionDef | ast.AsyncFunctionDef, docstring: str, path: Path
) -> Iterator[Finding]:
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
    @return finding elements in signature order, followed by a missing-result finding
    """
    # Collect each documented parameter name as an unordered membership set.
    documented = set(_DOC_PARAM.findall(docstring))
    # Inspect caller-supplied parameter names in signature order, except pytest fixtures.
    for name in () if node.name.startswith("test_") else _parameter_names(node):
        # A missing name has no Doxygen parameter record in the callable contract.
        if name not in documented:
            # Report the exact parameter and the structured record spelling needed.
            yield Finding(
                "DOC-007",
                path,
                node.lineno,
                f"{node.name}(): parameter `{name}` is not documented",
                f"Add `@param {name} <what it means>` -- the signature already carries its type.",
            )
    # A value-returning annotation requires a Doxygen result record in the same contract.
    if _returns_a_value(node) and not _DOC_RETURN.search(docstring):
        # Report one result omission independently from every parameter omission.
        yield Finding(
            "DOC-007",
            path,
            node.lineno,
            f"{node.name}(): the result is not documented",
            "Add `@return <what the value signifies>`.",
        )


def _parameter_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> Iterator[str]:
    """Every parameter a caller supplies, in signature order.

    @param node the callable
    @return parameter-name elements in signature order, excluding implicit self and cls
    """
    # Retain the parsed argument groups for ordered flattening across parameter kinds.
    args = node.args
    # Yield positional and keyword-only parameter elements in signature order.
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
        # Instance and class receivers are implicit owners rather than caller-supplied values.
        if arg.arg not in {"self", "cls"}:
            # Expose the exact caller-facing parameter spelling.
            yield arg.arg
    # Inspect optional variadic and keyword-capture parameters in their declared order.
    for variadic in (args.vararg, args.kwarg):
        # A missing variadic slot contributes no parameter name.
        if variadic is not None:
            # Expose the present variadic parameter spelling after fixed parameters.
            yield variadic.arg


def _returns_a_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether the callable's annotation promises something back.

    An unannotated function is not pressed for an @return: the missing
    annotation is a typing defect that TYPE-001 owns, and reporting it twice
    under two rules helps nobody.

    @param node the callable
    @return True when the return annotation is anything but None
    """
    # Hold the parsed return annotation, or None for an unannotated callable.
    returns = node.returns
    # An unannotated callable delegates the entire missing-contract defect to TYPE-001.
    if returns is None:
        # False means DOC-007 must not duplicate the typing finding.
        return False
    # True means the annotation promises a value; false is the explicit None alternative.
    return not (isinstance(returns, ast.Constant) and returns.value is None)


def _named_assignments(statement: ast.stmt) -> Iterator[tuple[str, int]]:
    """Names bound by one statement, with the line each was bound on.

    @param statement a statement from a module or class body
    @return bound-name/line pair elements in assignment-target order
    """
    # An annotated simple name contributes one entity and its statement line.
    if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
        # Expose the annotated target as one ordered assignment record.
        yield statement.target.id, statement.lineno
    # A plain assignment may expose more than one simple target in source order.
    elif isinstance(statement, ast.Assign):
        # Inspect each assignment target element in its written order.
        for target in statement.targets:
            # Attribute, subscript, and destructuring targets are not module/class named entities.
            if isinstance(target, ast.Name):
                # Expose the simple target and shared statement line as one record.
                yield target.id, statement.lineno


def _has_hash_block(source: list[str], lineno: int) -> bool:
    """Whether a `##` comment block sits immediately above `lineno`.

    @param source ordered source-line elements used for upward adjacency inspection
    @param lineno the 1-based line of the element
    @return True when a ## block precedes it, allowing intervening `#` continuation
    """
    # Start at the zero-based line immediately preceding the entity assignment.
    index = lineno - 2
    # Walk upward only through the contiguous comment block that could own the entity.
    while index >= 0:
        # Normalize indentation and surrounding whitespace for comment-form classification.
        line = source[index].strip()
        # A Doxygen opener anywhere in the contiguous block establishes entity ownership.
        if line.startswith("##"):
            # True means the immediately preceding comment block is Doxygen-readable.
            return True
        # A Doxygen block opens with ## and continues with plain #, so keep
        # walking up through continuation lines before giving up.
        if line.startswith("#"):
            # Continue through plain continuation lines toward the required `##` opener.
            index -= 1
            # Re-evaluate the preceding contiguous source element.
            continue
        # Non-comment syntax or a blank line terminates possible block ownership.
        break
    # False means no immediately preceding Doxygen block owns this assignment.
    return False


def _has_trailing_block(source: list[str], lineno: int) -> bool:
    """Whether a `##<` block documents the element on its own line.

    @param source ordered source-line elements used for same-line inspection
    @param lineno the 1-based line of the element
    @return True when the line carries a trailing ##< comment
    """
    # Validate the one-based line against the available ordered source elements.
    if 0 <= lineno - 1 < len(source):
        # True means the assignment line contains Doxygen's trailing entity marker.
        return "##<" in source[lineno - 1]
    # An out-of-range line cannot carry a trailing documentation block.
    return False


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    r"""Whether a callable is a typing overload stub, which documents nothing.

    @param node the callable
    @return True when it carries an \@overload decorator
    """
    # True means any decorator element names the typing overload marker; false is concrete code.
    return any(_name_of(d) in {"overload", "typing.overload"} for d in node.decorator_list)


def _name_of(node: ast.expr) -> str:
    """A dotted name for an expression used as a decorator or base class.

    @param node the expression
    @return its dotted name, or the empty string when it is not a name
    """
    # A simple name is already the complete dotted representation.
    if isinstance(node, ast.Name):
        # Expose the identifier spelling directly.
        return node.id
    # An attribute extends its recursively resolved owner name.
    if isinstance(node, ast.Attribute):
        # Join owner and attribute while removing a leading dot from unknown owners.
        return f"{_name_of(node.value)}.{node.attr}".lstrip(".")
    # A decorator factory or parameterized base is named by its called expression.
    if isinstance(node, ast.Call):
        # Recurse into the callee while ignoring arguments irrelevant to identity.
        return _name_of(node.func)
    # Other expressions have no stable dotted name for this check.
    return ""


# Run the standalone coverage check only at this module's process boundary.
if __name__ == "__main__":
    # Convert the check runner's stable result into the process exit status.
    raise SystemExit(main(DocCoverageCheck()))
