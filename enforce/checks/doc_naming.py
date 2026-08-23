"""Enforce the project-owned identifier and generated-vocabulary model."""

from __future__ import annotations

import ast
import operator
import re
from dataclasses import dataclass
from itertools import starmap
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final

from . import Finding, ModuleCheck, main
from .documentation_model import (
    DocumentationModel,
    DocumentationModelError,
    IdentifierGrammar,
    governed_paths,
    load,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Uppercase token shape sufficiently unambiguous to treat as an abbreviation.
ABBREVIATION_SHAPE: Final = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
## Camel-case tokenization preserves initialisms such as HTTP in HTTPClient.
CAMEL_TOKEN: Final = re.compile(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+")
## Names whose spelling is fixed by Python rather than project vocabulary.
LANGUAGE_NAMES: Final = frozenset({"self", "cls", "args", "kwargs"})


@dataclass(frozen=True, slots=True)
class Identifier:
    """One definition or binding subject to project naming rules."""

    ## Exact spelling and source position.
    name: str
    line: int


class DocNamingCheck(ModuleCheck):
    """Report grammar, abbreviation, and generated-name boundary violations."""

    ## Invoked as `python -m checks.doc_naming`.
    name = "doc_naming"
    ## Project grammar, controlled vocabulary, and generated-boundary rules.
    rules = ("DOC-023", "DOC-024", "DOC-025")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect every model-governed Python file.

        @param paths ordinary source-root fallback
        @return naming findings, or none while the model owner reports its own failure
        """
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Apply the local model to every binding and definition in one file.

        @param tree parsed module
        @param path source file
        @param _layer architectural layer, unused
        @return exact naming findings
        """
        try:
            model = load(self.declaration)
        except DocumentationModelError:
            return
        root = self.declaration.root
        if root is None:
            return
        relative = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())
        identifiers = _identifiers(tree)
        grammar = _grammar_for(model, relative)
        for identifier in identifiers:
            if identifier.name in LANGUAGE_NAMES or _dunder(identifier.name):
                continue
            if (
                grammar is not None
                and identifier.name not in grammar.exclusions
                and re.fullmatch(grammar.pattern, identifier.name) is None
            ):
                yield Finding(
                    "DOC-023",
                    path,
                    identifier.line,
                    f"identifier `{identifier.name}` violates the grammar for {grammar.scope}",
                    "Rename it to match the declared broad-to-specific dimensions, or "
                    "record a narrow exclusion in documentation-model.json.",
                    diagnostic_id="IDENTIFIER_GRAMMAR",
                )
            yield from _abbreviation_findings(identifier, path, relative, model)
            yield from _generated_findings(identifier, path, model)


def _identifiers(tree: ast.Module) -> tuple[Identifier, ...]:
    """Collect definition and binding names without duplicate AST contexts.

    @param tree parsed module
    @return stable identifiers ordered by source line and spelling
    """
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            found.add((node.name, node.lineno))
            found.update((argument.arg, argument.lineno) for argument in _arguments(node))
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            found.add((node.id, node.lineno))
        elif (
            isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
            and node.name is not None
        ):
            found.add((node.name, node.lineno))
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            found.add((node.rest, node.lineno))
    return tuple(starmap(Identifier, sorted(found, key=operator.itemgetter(1, 0))))


def _arguments(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> tuple[ast.arg, ...]:
    """Return callable arguments while admitting class nodes in one dispatch.

    @param node definition node
    @return complete callable arguments, or none for a class
    """
    if isinstance(node, ast.ClassDef):
        return ()
    arguments = node.args
    return (
        *arguments.posonlyargs,
        *arguments.args,
        *arguments.kwonlyargs,
        *((arguments.vararg,) if arguments.vararg is not None else ()),
        *((arguments.kwarg,) if arguments.kwarg is not None else ()),
    )


def _grammar_for(model: DocumentationModel, relative: PurePosixPath) -> IdentifierGrammar | None:
    """Resolve the most-specific grammar for one file.

    @param model project documentation model
    @param relative repository-relative source path
    @return owning grammar, or None when the project declares no grammar here
    """
    matching = [
        grammar
        for grammar in model.identifier_grammars
        if relative == grammar.scope or relative.is_relative_to(grammar.scope)
    ]
    return max(matching, key=lambda item: len(item.scope.parts)) if matching else None


def _tokens(identifier: str) -> tuple[str, ...]:
    """Split snake and camel spelling while preserving initialisms.

    @param identifier Python identifier
    @return lexical tokens in source order
    """
    return tuple(
        token
        for segment in identifier.strip("_").split("_")
        for token in (CAMEL_TOKEN.findall(segment) or [segment])
        if token
    )


def _abbreviation_findings(
    identifier: Identifier,
    path: Path,
    relative: PurePosixPath,
    model: DocumentationModel,
) -> Iterator[Finding]:
    """Report undeclared initialisms and non-canonical declared spellings.

    @param identifier source identifier
    @param path source file
    @param relative repository-relative source path
    @param model project documentation model
    @return controlled-vocabulary findings
    """
    applicable = [
        item
        for item in model.abbreviations
        if any(relative == scope or relative.is_relative_to(scope) for scope in item.scopes)
    ]
    for token in _tokens(identifier.name):
        exact = model.abbreviation_for(token, relative)
        same_fold = [item for item in applicable if item.token.casefold() == token.casefold()]
        if exact is not None:
            continue
        if same_fold:
            canonical = same_fold[0].token
            yield Finding(
                "DOC-024",
                path,
                identifier.line,
                f"identifier `{identifier.name}` spells controlled abbreviation "
                f"`{token}` instead of `{canonical}`",
                f"Use `{canonical}` exactly, or change its one scoped declaration and "
                "all uses together.",
                diagnostic_id="ABBREVIATION_SPELLING",
            )
        elif ABBREVIATION_SHAPE.fullmatch(token) and not _constant_style(identifier.name):
            yield Finding(
                "DOC-024",
                path,
                identifier.line,
                f"identifier `{identifier.name}` uses undeclared abbreviation `{token}`",
                "Declare its one meaning and scopes in documentation-model.json, or spell "
                "the concept without an abbreviation.",
                diagnostic_id="ABBREVIATION_UNDECLARED",
            )


def _constant_style(identifier: str) -> bool:
    """Whether Python's constant convention uppercased every lexical word.

    An all-uppercase identifier does not reveal which tokens are abbreviations:
    ``SECONDS_PER_DAY`` and ``API_CLIENT`` have the same syntax. Declared tokens
    still receive exact-spelling checks above, but undeclared-token detection is
    confined to mixed-case shapes such as ``APIClient`` where an initialism is
    mechanically distinguishable from an ordinary word.

    @param identifier complete Python name
    @return true when every cased character is uppercase
    """
    letters = "".join(character for character in identifier if character.isalpha())
    return bool(letters) and letters.isupper()


def _generated_findings(
    identifier: Identifier, path: Path, model: DocumentationModel
) -> Iterator[Finding]:
    """Require every visibly generated identifier to map to canonical vocabulary.

    @param identifier source identifier
    @param path source file
    @param model project documentation model
    @return one missing-boundary finding when applicable
    """
    tokens = set(_tokens(identifier.name))
    markers = set(model.generated_names.markers)
    if not tokens.intersection(markers):
        return
    if identifier.name in model.generated_names.mappings:
        return
    yield Finding(
        "DOC-025",
        path,
        identifier.line,
        f"generated identifier `{identifier.name}` has no canonical-term mapping",
        "Add its exact derived-to-canonical mapping to documentation-model.json; "
        "generated vocabulary may not silently become domain vocabulary.",
        diagnostic_id="GENERATED_MAPPING_MISSING",
    )


def _dunder(name: str) -> bool:
    """Whether Python itself reserves the identifier spelling.

    @param name identifier
    @return true for double-underscore names
    """
    return name.startswith("__") and name.endswith("__")


if __name__ == "__main__":
    raise SystemExit(main(DocNamingCheck()))
