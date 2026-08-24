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
from typing import TYPE_CHECKING, Final

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Unordered I/O-module set whose each root-name element can escape or add nondeterminism.
IO_MODULES = frozenset({
    "os", "io", "pathlib", "socket", "subprocess", "shutil", "tempfile",
    "sqlite3", "http", "urllib", "requests", "httpx", "asyncio", "threading",
    "multiprocessing", "random", "secrets", "time", "datetime", "logging",
    "argparse", "sys", "pickle", "webbrowser",
})

## Names inside an I/O-capable module that provably cannot perform I/O, so
## importing one is not the exposure `ARCH-002` describes. The rule forbids
## importing what *can* reach outside the process; a name that cannot is simply
## not the subject.
##
## Found by running this check against a real codebase that had reasoned about
## exactly this. `PurePosixPath` exists in the standard library *because* it
## cannot touch the filesystem -- that is the entire point of the Pure variants,
## and flagging one told a careful author to stop using the tool designed for
## the situation. `date` and `datetime` imported as TYPES are the same case:
## `date.today()` reads a clock, which is `ARCH-005` and `EFCT-003`'s territory,
## while the annotation is inert.
##
## The set is deliberately short and every pair element is defensible from the
## standard library's own documentation. It is not a place to park an import
## somebody finds inconvenient.
## Each unordered pair contains an I/O module root then one provably pure imported name.
PURE_NAMES: frozenset[tuple[str, str]] = frozenset({
    ("pathlib", "PurePath"),
    ("pathlib", "PurePosixPath"),
    ("pathlib", "PureWindowsPath"),
    ("datetime", "date"),
    ("datetime", "datetime"),
    ("datetime", "time"),
    ("datetime", "timedelta"),
    ("datetime", "timezone"),
    ("datetime", "UTC"),
})

## Unordered mutable-collection set whose each type-name element is forbidden in domain inputs.
## These are types a domain signature may not take for a parameter the
## callee does not own (`TYPE-008`). A mutable collection in a signature is an
## undeclared output channel: the caller cannot tell from the type whether their
## list comes back changed, and the day it does the defect is attributed to
## whoever read it rather than whoever wrote it.
##
## The read-only counterparts -- `Sequence`, `Mapping`, `Set`, `Iterable`,
## `frozenset` -- say the same thing about the shape and one more thing about the
## ownership.
MUTABLE_COLLECTIONS: Final[frozenset[str]] = frozenset({
    "list", "dict", "set", "bytearray", "List", "Dict", "Set",
    "MutableSequence", "MutableMapping", "MutableSet",
})

## Unordered foreign-type set whose each name element couples domain contracts to technology.
FOREIGN_TYPES = frozenset({
    "Namespace", "Request", "Response", "Session", "Connection", "Cursor",
    "BaseModel", "Element", "ElementTree", "DataFrame", "Series", "ndarray",
})


class DomainPurityCheck(ModuleCheck):
    """Rejects a domain module that reaches outside itself or borrows a foreign type.

    Also rejects an unfrozen domain dataclass and a closed set written as a
    literal union, in three independent passes over the same tree.

    Applies to nothing else. A file whose *first* layer segment is not `domain`,
    and any test file, is parsed and then let through untouched -- so a domain
    package nested under `adapters/` is never examined at all.
    """

    ## Invoked as `python -m checks.domain_purity`.
    name = "domain_purity"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ARCH-002", "ARCH-013", "TYPE-002", "TYPE-006", "TYPE-007",
             "TYPE-008")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for one module, silent outside the domain layer.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; anything but `domain` is skipped
        @return finding elements in import, base, annotation, then dataclass pass order
        """
        # Only non-test domain code owns the combined purity and value-shape obligations.
        if layer != "domain" or is_test_path(path):
            # Stop iteration outside the exact architectural subject.
            return
        # Run each independent predicate family in stable diagnostic order.
        yield from self._imports(tree, path)
        yield from self._base_classes(tree, path)
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
        # Inspect import statements for infrastructure dependencies entering the domain.
        for node in ast.walk(tree):
            # Inspect each imported module/name/line tuple element in statement order.
            for module, name, lineno in _imported_modules(node):
                # Normalize a dotted spelling to its top-level package root.
                root = module.split(".", 1)[0]
                # Imports outside the closed I/O-capable root set satisfy this predicate.
                if root not in IO_MODULES:
                    # Advance to the next imported element.
                    continue
                # A named import explicitly proven pure does not expose the module's effects.
                if name is not None and (root, name) in PURE_NAMES:
                    # Advance without reporting the carefully bounded exemption.
                    continue
                # Yield the effect-capable import finding at its exact statement line.
                yield Finding(
                    "ARCH-002", path, lineno,
                    f"domain imports `{module}`, which can perform I/O",
                    "Move the effect behind a port and take it as a parameter (ARCH-005).",
                )

    def _base_classes(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report a domain class that INHERITS a framework or transport type.

        The gap this closes was found by holding the check against a real
        codebase whose four domains are modelled entirely in `pydantic.BaseModel`.
        `BaseModel` was already listed in `FOREIGN_TYPES` and the check reported
        nothing, because it only ever examined annotations -- and inheritance is
        how a domain actually acquires a framework. import-linter's ARCH-004
        contract caught the same coupling from the other side, which is the
        overlap this module's docstring claims and is here the only reason it was
        noticed at all.

        Inheriting is strictly worse than annotating: every instance carries the
        framework's construction, validation and serialization semantics, and no
        call site can opt out.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return one ARCH-013 finding per offending base, at the class statement
        """
        # Inspect domain classes for inheritance from infrastructure-owned bases.
        for node in ast.walk(tree):
            # Only class definitions publish inheritance semantics.
            if not isinstance(node, ast.ClassDef):
                # Skip non-callable syntax because it owns no parameter or return annotation.
                continue
            # Inspect each base-expression element in authored declaration order.
            for base in node.bases:
                # Resolve a qualified terminal attribute or bare base identifier.
                named = getattr(base, "attr", getattr(base, "id", ""))
                # Inheritance from any closed foreign type imports its construction semantics.
                if named in FOREIGN_TYPES:
                    # Yield the framework-inheritance finding at the class statement.
                    yield Finding(
                        "ARCH-013", path, node.lineno,
                        f"domain class `{node.name}` inherits `{named}`, "
                        f"a framework type",
                        "Model the value with a plain frozen dataclass and convert at "
                        "the boundary; a domain that IS a framework type cannot be "
                        "constructed, compared or serialized without it.",
                    )

    def _annotations(self, tree: ast.Module, path: Path) -> Iterator[Finding]:
        """Report `Any`, borrowed types and literal unions in function signatures.

        Only parameters and returns are examined. A local variable's annotation
        binds nobody; a signature's is the contract every caller is held to.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @return TYPE-002, ARCH-013 and TYPE-006 findings, at the annotation's line
        """
        # Inspect callable annotations for mutable, dynamic, or infrastructure types.
        for node in ast.walk(tree):
            # Only callable definitions publish parameter and return contracts.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip non-class syntax because it cannot carry a dataclass decorator.
                continue
            # Returns are excluded: handing back a fresh list is ordinary and
            # owns nothing of the caller's. The rule is about a parameter the
            # callee does not own, so only parameters are examined.
            # Build an unordered set whose each element is one parameter-annotation node identity.
            parameters = set(_annotations_of(node, returns=False))
            # Inspect each contract annotation element in parameter-then-return order.
            for annotation in _annotations_of(node):
                # Inspect each identifier element in deterministic annotation walk order.
                for name in _names_in(annotation):
                    # Any disables all downstream type guarantees.
                    if name == "Any":
                        # Yield the untyped-contract finding at the annotation line.
                        yield Finding(
                            "TYPE-002", path, annotation.lineno,
                            "`Any` in a domain signature",
                            "Name the real type; `Any` disables every downstream guarantee.",
                        )
                    # Foreign transport/framework vocabulary couples every domain caller.
                    elif name in FOREIGN_TYPES:
                        # Yield the borrowed-type finding at the annotation line.
                        yield Finding(
                            "ARCH-013", path, annotation.lineno,
                            f"framework or transport type `{name}` in a domain signature",
                            "Translate to a domain type at the boundary (ARCH-014).",
                        )
                    # Mutable input collections expose undeclared caller-owned output channels.
                    elif name in MUTABLE_COLLECTIONS and annotation in parameters:
                        # Yield the mutable-input finding at the parameter annotation line.
                        yield Finding(
                            "TYPE-008", path, annotation.lineno,
                            f"mutable `{name}` in a domain parameter",
                            "Take `Sequence`, `Mapping` or `Set`. A mutable "
                            "collection in a signature is an undeclared output "
                            "channel the caller cannot see.",
                        )
                # Multi-member literal unions encode a closed set without one enum authority.
                if _is_literal_union(annotation):
                    # Yield the non-enumerated closed-set finding at the annotation line.
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
        # Inspect domain classes for the required frozen and slotted dataclass options.
        for node in ast.walk(tree):
            # Only class definitions can carry dataclass decorators.
            if not isinstance(node, ast.ClassDef):
                # Skip syntax that cannot carry a dataclass decorator.
                continue
            # Inspect each decorator-expression element in authored order.
            for decorator in node.decorator_list:
                # Non-dataclass decorators do not establish the domain value-shape contract.
                if not _is_dataclass(decorator):
                    # Advance to the next decorator.
                    continue
                # Map each literal decorator-keyword key to its value in authored order.
                kwargs = _decorator_kwargs(decorator)
                # Preserve required-key order while collecting each absent true declaration.
                missing = [k for k in ("frozen", "slots") if kwargs.get(k) is not True]
                # Either missing property permits mutation or dynamic attribute state.
                if missing:
                    # Yield one aggregate dataclass finding in required-key order.
                    yield Finding(
                        "TYPE-007", path, node.lineno,
                        f"domain dataclass `{node.name}` is not {' and '.join(missing)}",
                        "Use @dataclass(frozen=True, slots=True); a value that can drift "
                        "between validation and use cannot be named in an error.",
                    )


def _imported_modules(node: ast.AST) -> Iterator[tuple[str, str | None, int]]:
    """What one statement brings in: the module, the bound name, and the line.

    Relative imports yield nothing. A sibling module can of course reach an
    effect in turn, but that is a transitive fact only the import-linter contract
    can see; this one answers for the line in front of it.

    The bound name is carried because `import pathlib` and
    `from pathlib import PurePosixPath` are different claims. The first takes the
    whole module and everything it can do; the second takes one name, and that
    name may be provably incapable of the thing the rule forbids. `None` means
    the statement took the module itself, where no such exemption can apply.

    @param node any node; only import statements produce anything
    @return module/name/line tuple elements in authored alias order
    """
    # Direct imports expose complete modules rather than individually bounded names.
    if isinstance(node, ast.Import):
        # Inspect each import-alias element in authored order.
        for alias in node.names:
            # Yield the complete module spelling, no bound-name exemption, and source line.
            yield alias.name, None, node.lineno
    # Absolute from-imports expose individually named objects that may be proven pure.
    elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
        # Inspect each imported alias element in authored order.
        for alias in node.names:
            # Yield the module spelling, imported name, and source line.
            yield node.module, alias.name, node.lineno


def _annotations_of(node: ast.FunctionDef | ast.AsyncFunctionDef, *,
                    returns: bool = True) -> Iterator[ast.expr]:
    """Every annotation that forms part of a function's published contract.

    Positional-only, positional-or-keyword and keyword-only parameters, plus
    `*args`, `**kwargs` and the return. Positions left unannotated are simply
    absent; a missing annotation is the type checker's business, not this
    check's.

    @param node the function definition
    @param returns true to include the return annotation; false for parameters only.
        `TYPE-008` is about
        a parameter the callee does not own, and handing back a fresh list owns
        nothing of the caller's, so that rule asks for parameters alone
    @return annotation-expression elements in parameter order with optional return last
    """
    # Select the complete Python argument declaration.
    args = node.args
    # Inspect positional-only, positional, keyword-only, vararg, and kwarg elements in order.
    for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg):
        # Only present argument nodes carrying annotations belong to the published type view.
        if arg is not None and arg.annotation is not None:
            # Yield the parameter annotation at its contract position.
            yield arg.annotation
    # Append the return annotation only when requested and explicitly present.
    if returns and node.returns is not None:
        # Yield the return contract after all parameter annotations.
        yield node.returns


def _names_in(annotation: ast.expr) -> Iterator[str]:
    """Every identifier mentioned anywhere inside an annotation.

    A dotted name contributes every segment it is built from, so `pd.DataFrame`
    yields both `DataFrame` and `pd`. That is what lets a foreign type be
    recognized by its own name, however the module in front of it was aliased.

    @param annotation the annotation expression
    @return identifier elements in deterministic AST traversal order, duplicates included
    """
    # Inspect each nested syntax-node element in deterministic annotation walk order.
    for node in ast.walk(annotation):
        # Bare names contribute their complete identifier.
        if isinstance(node, ast.Name):
            # Yield the bare identifier at its traversal position.
            yield node.id
        # Qualified names contribute their terminal attribute as the type identity.
        elif isinstance(node, ast.Attribute):
            # Yield the terminal attribute at its traversal position.
            yield node.attr


def _is_literal_union(annotation: ast.expr) -> bool:
    """Whether an annotation spells a closed set out as constants inline.

    A one-member `Literal` passes: it pins a single value rather than declaring a
    set of cases that later code must stay exhaustive over. A member that is not
    a constant also passes, since the set is then not closed in the first place.

    @param annotation the annotation expression, searched to any depth
    @return true when some nested ``Literal`` holds multiple constants; false otherwise
    """
    # Inspect each nested syntax-node element in deterministic annotation walk order.
    for node in ast.walk(annotation):
        # Only subscript expressions can apply Literal to member values.
        if not isinstance(node, ast.Subscript):
            # Skip syntax that cannot apply Literal to member values.
            continue
        # Select the subscripted base expression.
        base = node.value
        # Resolve a bare or qualified terminal base identifier.
        name = base.id if isinstance(base, ast.Name) else getattr(base, "attr", "")
        # Other generic types do not declare an inline literal case set.
        if name != "Literal":
            # Advance to the next nested subscript.
            continue
        # Select the literal's slice expression containing its member declarations.
        target = node.slice
        # Normalize tuple and single member forms into authored member order.
        members = target.elts if isinstance(target, ast.Tuple) else [target]
        # More than one constant member is the exact closed inline-set shape.
        if len(members) > 1 and all(isinstance(m, ast.Constant) for m in members):
            # Accept immediately at the first matching nested Literal.
            return True
    # No nested Literal declares multiple constant member elements.
    return False


def _is_dataclass(decorator: ast.expr) -> bool:
    """Whether a decorator is `dataclass`, written bare or called with keywords.

    Recognized by the name on the line, so an alias or a locally wrapped
    decorator escapes. The check reports on what a reader of the file can see.

    @param decorator one entry of a class's decorator list
    @return true when the trailing identifier is ``dataclass``; false otherwise
    """
    # Called decorators expose their identity through the called function expression.
    node = decorator.func if isinstance(decorator, ast.Call) else decorator
    # Resolve a bare or qualified terminal decorator identifier.
    name = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
    # Match the exact conventional dataclass spelling.
    return name == "dataclass"


def _decorator_kwargs(decorator: ast.expr) -> dict[str, object]:
    """The literal keyword arguments a decorator was applied with.

    A value the tree cannot evaluate -- a name, a call, `**kwargs` -- is omitted
    rather than guessed. The constants that survive are returned raw, so a caller
    asking for `frozen=True` must compare against `True` itself: `frozen=1` is
    true enough for Python and is not the declaration the rule asks for.

    @param decorator one entry of a class's decorator list
    @return mapping from each keyword-name key to its literal value preserving authored order;
        empty when the decorator is not a call
    """
    # Bare decorators carry no explicit keyword configuration.
    if not isinstance(decorator, ast.Call):
        # Return an insertion-ordered empty mapping.
        return {}
    # Map each explicit literal keyword-name key to its raw constant value in authored order.
    return {
        kw.arg: kw.value.value
        for kw in decorator.keywords
        if kw.arg is not None and isinstance(kw.value, ast.Constant)
    }


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(DomainPurityCheck()))
