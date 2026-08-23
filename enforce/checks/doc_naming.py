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

# Import static traversal and path contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Uppercase token shape sufficiently unambiguous to treat as an abbreviation.
ABBREVIATION_SHAPE: Final = re.compile(r"^[A-Z][A-Z0-9]{1,7}$")
## Camel-case tokenization preserves initialisms such as HTTP in HTTPClient.
CAMEL_TOKEN: Final = re.compile(r"[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+")
## Unordered identifier set whose each element has spelling fixed by Python itself.
LANGUAGE_NAMES: Final = frozenset({"self", "cls", "args", "kwargs"})


@dataclass(frozen=True, slots=True)
class Identifier:
    """One definition or binding subject to project naming rules."""

    ## Exact Python identifier spelling subject to the naming model.
    name: str
    ## One-based source line at which the identifier is defined or bound.
    line: int


class DocNamingCheck(ModuleCheck):
    """Report grammar, abbreviation, and generated-name boundary violations."""

    ## Invoked as `python -m checks.doc_naming`.
    name = "doc_naming"
    ## Ordered rule-id elements for grammar, controlled vocabulary, and generated boundaries.
    rules = ("DOC-023", "DOC-024", "DOC-025")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect every model-governed Python file.

        @param paths fallback path elements in caller order when no valid model owns discovery
        @return finding elements in governed-file order, or none while the model owner fails
        """
        # Delegate the model-governed path sequence to the shared one-pass module runner.
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Apply the local model to every binding and definition in one file.

        @param tree parsed module
        @param path source file
        @param _layer architectural layer, unused
        @return exact naming finding elements in source identifier order
        @par Effects Resolves repository paths and reads the documentation model without mutation.
        """
        # Load the strict project-owned vocabulary before inspecting any identifier.
        try:
            # Hold the complete typed model that owns grammar and vocabulary decisions.
            model = load(self.declaration)
        # Let the model-owning check report a malformed declaration exactly once.
        except DocumentationModelError:
            # Suppress dependent naming output because no valid policy can be applied.
            return
        # Resolve the repository boundary from the same parsed project declaration.
        root = self.declaration.root
        # A synthetic declaration without a root has no repository-relative naming scope.
        if root is None:
            # Produce no dependent finding when scope ownership cannot be established.
            return
        # Express the source as the repository-relative POSIX path used by model scopes.
        relative = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())
        # Preserve each definition and binding record in stable source-line order.
        identifiers = _identifiers(tree)
        # Select the most-specific applicable grammar, or None when the project declares none.
        grammar = _grammar_for(model, relative)
        # Apply all independent naming propositions to each identifier in source order.
        for identifier in identifiers:
            # Python-reserved names and double-underscore protocol names are outside project policy.
            if identifier.name in LANGUAGE_NAMES or _dunder(identifier.name):
                # Continue with the next source identifier without emitting project findings.
                continue
            # A scoped grammar applies unless this exact name has a declared narrow exclusion.
            if (
                grammar is not None
                and identifier.name not in grammar.exclusions
                and re.fullmatch(grammar.pattern, identifier.name) is None
            ):
                # Report the violated scope and direct the owner to rename or declare the exception.
                yield Finding(
                    "DOC-023",
                    path,
                    identifier.line,
                    f"identifier `{identifier.name}` violates the grammar for {grammar.scope}",
                    "Rename it to match the declared broad-to-specific dimensions, or "
                    "record a narrow exclusion in documentation-model.json.",
                    diagnostic_id="IDENTIFIER_GRAMMAR",
                )
            # Independently validate abbreviation spelling and declaration in this source scope.
            yield from _abbreviation_findings(identifier, path, relative, model)
            # Independently enforce the generated-name boundary for marker-prefixed vocabulary.
            yield from _generated_findings(identifier, path, model)


def _identifiers(tree: ast.Module) -> tuple[Identifier, ...]:
    """Collect definition and binding names without duplicate AST contexts.

    @param tree parsed module
    @return identifier elements ordered by source line then spelling
    """
    # Accumulate each spelling/line pair in a deliberately unordered set to deduplicate contexts.
    found: set[tuple[str, int]] = set()
    # Visit every node to census definitions, parameters, stores, handlers, and pattern captures.
    for node in ast.walk(tree):
        # Definitions contribute their own name and each callable argument name.
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # Record the definition at its one-based source line.
            found.add((node.name, node.lineno))
            # Add every callable argument pair; class definitions deliberately yield none.
            found.update((argument.arg, argument.lineno) for argument in _arguments(node))
        # Store-context names cover ordinary assignment, loops, and comprehension targets.
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            # Record the stored identifier without duplicating another AST exposure.
            found.add((node.id, node.lineno))
        # Exception and pattern nodes carry captures as strings rather than Name stores.
        elif (
            isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar))
            and node.name is not None
        ):
            # Record the non-null capture spelling at its owning source line.
            found.add((node.name, node.lineno))
        # Mapping-pattern rest captures also use a string-valued AST field.
        elif isinstance(node, ast.MatchMapping) and node.rest is not None:
            # Record the rest capture at the mapping pattern's source position.
            found.add((node.rest, node.lineno))
    # Sort each unique pair by line then spelling and construct immutable identifier records.
    return tuple(starmap(Identifier, sorted(found, key=operator.itemgetter(1, 0))))


def _arguments(
    node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef,
) -> tuple[ast.arg, ...]:
    """Return callable arguments while admitting class nodes in one dispatch.

    @param node definition node
    @return argument elements in signature order, or an empty sequence for a class
    """
    # Class definitions have no callable signature arguments to add to the census.
    if isinstance(node, ast.ClassDef):
        # Return the ordered empty sequence for the class alternative.
        return ()
    # Retain the callable's parsed argument groups for one ordered flattening.
    arguments = node.args
    # Concatenate positional, keyword-only, variadic, and keyword-capture elements in
    # signature order.
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
    # Collect each applicable grammar record while retaining declaration order.
    matching = [
        grammar
        for grammar in model.identifier_grammars
        if relative == grammar.scope or relative.is_relative_to(grammar.scope)
    ]
    # Prefer the deepest scope path; no matching element means naming remains unconstrained here.
    return max(matching, key=lambda item: len(item.scope.parts)) if matching else None


def _tokens(identifier: str) -> tuple[str, ...]:
    """Split snake and camel spelling while preserving initialisms.

    @param identifier Python identifier
    @return lexical token elements in source order
    """
    # Flatten underscore segments into camel-aware tokens while retaining lexical order.
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
    @return controlled-vocabulary finding elements in lexical token order
    """
    # Collect each abbreviation declaration applicable to this path in model order.
    applicable = [
        item
        for item in model.abbreviations
        if any(relative == scope or relative.is_relative_to(scope) for scope in item.scopes)
    ]
    # Validate every identifier token in lexical source order.
    for token in _tokens(identifier.name):
        # Resolve an exact canonical token for the current repository-relative scope.
        exact = model.abbreviation_for(token, relative)
        # Preserve each case-insensitive declaration match in model order for spelling diagnosis.
        same_fold = [item for item in applicable if item.token.casefold() == token.casefold()]
        # An exact scoped declaration fully satisfies controlled vocabulary.
        if exact is not None:
            # Continue with the next lexical token without redundant spelling checks.
            continue
        # A case-insensitive declaration proves this token has non-canonical spelling.
        if same_fold:
            # Select the first applicable declaration's one canonical token spelling.
            canonical = same_fold[0].token
            # Emit an exact-spelling finding without changing declaration meaning.
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
        # Mixed-case initialism shapes without any declaration have unknown meaning.
        elif ABBREVIATION_SHAPE.fullmatch(token) and not _constant_style(identifier.name):
            # Require one scoped meaning or an unabbreviated identifier spelling.
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
    # Retain each alphabetic character in identifier order while ignoring separators and digits.
    letters = "".join(character for character in identifier if character.isalpha())
    # True means at least one letter exists and every letter is uppercase; false is mixed/lowercase.
    return bool(letters) and letters.isupper()


def _generated_findings(
    identifier: Identifier, path: Path, model: DocumentationModel
) -> Iterator[Finding]:
    """Require every marker-prefixed identifier to map to canonical vocabulary.

    @param identifier source identifier
    @param path source file
    @param model project documentation model
    @return one missing-boundary finding when applicable
    """
    # Preserve each lexical identifier token in source order for leading-marker classification.
    tokens = _tokens(identifier.name)
    # Build an unordered set whose each element is a project-declared generated-name marker.
    markers = set(model.generated_names.markers)
    # An empty token sequence or non-marker first token denotes authored project vocabulary.
    if not tokens or tokens[0] not in markers:
        # Produce no generated-boundary finding for ordinary vocabulary.
        return
    # An exact mapping preserves the marker-prefixed name's canonical project origin.
    if identifier.name in model.generated_names.mappings:
        # Produce no finding when the declared boundary is complete.
        return
    # Report the exact unmapped identifier at its definition or binding position.
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
    # True means both reserved delimiters exist; false means project naming may apply.
    return name.startswith("__") and name.endswith("__")


# Run the standalone naming check only at this module's process boundary.
if __name__ == "__main__":
    # Convert the check runner's stable result into the process exit status.
    raise SystemExit(main(DocNamingCheck()))
