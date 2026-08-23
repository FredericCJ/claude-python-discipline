"""Parse and validate the project-owned v5 documentation model.

The package owns this schema. The consuming repository owns every path,
abbreviation, naming grammar, generated-name boundary, and semantic-property
record inside it. Unknown fields fail so a misspelling cannot become a waiver.
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never

from . import Check, Finding, iter_python_files, project

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

## Exact top-level vocabulary for schema version one.
MODEL_FIELDS: Final = frozenset({
    "schema_version",
    "engine",
    "scopes",
    "controlled_abbreviations",
    "identifier_grammars",
    "generated_names",
    "semantic_properties",
})
## Python identifier token accepted for controlled abbreviations and mappings.
IDENTIFIER_TOKEN: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ScopeKind(StrEnum):
    """Why a governed Python path exists in the repository."""

    ## Delivered runtime code.
    PRODUCTION = "production"
    ## Executable verification code.
    TESTS = "tests"
    ## Repository-owned build, migration, release, or checking code.
    MAINTENANCE = "maintenance"


class Ownership(StrEnum):
    """Whether the repository authors documentation at one path."""

    ## Repository-owned Python held directly to the documentation rules.
    GOVERNED = "governed"
    ## Derived Python whose generator owns conformance.
    GENERATED = "generated"
    ## Third-party or vendored Python outside local authorship.
    FOREIGN = "foreign"


class SemanticPropertyKind(StrEnum):
    """Mechanically declared semantic property vocabulary."""

    ## Measurement unit such as milliseconds or bytes.
    UNIT = "unit"
    ## Text or binary encoding.
    ENCODING = "encoding"
    ## Allowed numeric or symbolic interval.
    RANGE = "range"
    ## Boundary or temporary representation.
    REPRESENTATION = "representation"


class DocumentationModelError(ValueError):
    """A stable documentation-model diagnostic."""

    def __init__(self, diagnostic_id: str, source: Path, detail: str) -> None:
        """Preserve the rejected proposition and its owning artifact.

        @param diagnostic_id stable schema diagnostic
        @param source model or declaration path
        @param detail actionable explanation
        """
        super().__init__(f"{diagnostic_id} {source}: {detail}")
        self.diagnostic_id = diagnostic_id
        self.source = source


def _reject(diagnostic_id: str, source: Path, detail: str) -> Never:
    """Raise one stable model diagnostic.

    @param diagnostic_id stable schema diagnostic
    @param source model or declaration path
    @param detail actionable explanation
    @return never
    @throws DocumentationModelError unconditionally
    """
    raise DocumentationModelError(diagnostic_id, source, detail)


@dataclass(frozen=True, slots=True)
class Scope:
    """One repository-relative Python ownership boundary."""

    ## Constrained repository-relative directory or file.
    path: PurePosixPath
    ## Production, test, or maintenance purpose.
    kind: ScopeKind
    ## Local, generated, or foreign ownership.
    ownership: Ownership


@dataclass(frozen=True, slots=True)
class Abbreviation:
    """One controlled token with one meaning in declared scopes."""

    ## Exact token spelling accepted in identifiers.
    token: str
    ## Uncontracted project meaning.
    meaning: str
    ## Paths in which this meaning applies.
    scopes: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class IdentifierGrammar:
    """Optional lexical grammar for one governed scope."""

    ## Path on which the grammar applies.
    scope: PurePosixPath
    ## Full-match regular expression for governed identifiers.
    pattern: str
    ## Broad-to-specific semantic dimensions named by the pattern.
    dimensions: tuple[str, ...]
    ## Names explicitly outside the grammar, kept reviewable in the model.
    exclusions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedNames:
    """Markers and exact derived-to-canonical vocabulary mappings."""

    ## Identifier tokens that make a derived name visibly generated.
    markers: tuple[str, ...]
    ## Derived identifier to canonical domain term.
    mappings: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class SemanticProperty:
    """One identifier pattern whose documentation carries a declared property."""

    ## Shell-style identifier pattern, such as `*_ms`.
    identifier_pattern: str
    ## Property category required in the owning documentation.
    property: SemanticPropertyKind
    ## Exact project-owned semantic value expected in prose.
    value: str
    ## Governed paths on which the declaration applies.
    scopes: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class DocumentationModel:
    """Complete versioned project-owned evident-source declaration."""

    ## Schema identity and sole structured engine.
    schema_version: int
    engine: str
    ## Complete local, generated, and foreign scope partition.
    scopes: tuple[Scope, ...]
    ## Local naming and property declarations.
    abbreviations: tuple[Abbreviation, ...]
    identifier_grammars: tuple[IdentifierGrammar, ...]
    generated_names: GeneratedNames
    semantic_properties: tuple[SemanticProperty, ...]
    ## Artifact from which this value was parsed.
    source: Path

    def ownership_of(self, candidate: Path, root: Path) -> Ownership | None:
        """Resolve a path through the most-specific declared scope.

        @param candidate repository-owned file or directory
        @param root governed repository root
        @return most-specific ownership, or None outside every scope
        """
        try:
            relative = PurePosixPath(candidate.resolve().relative_to(root.resolve()).as_posix())
        except ValueError:
            return None
        matching = [
            scope
            for scope in self.scopes
            if relative == scope.path or relative.is_relative_to(scope.path)
        ]
        if not matching:
            return None
        return max(matching, key=lambda scope: len(scope.path.parts)).ownership

    def governed_files(self, root: Path) -> tuple[Path, ...]:
        """Enumerate Python whose most-specific owner is the repository.

        @param root governed repository root
        @return stable, duplicate-free file sequence
        """
        candidates = {
            path.resolve()
            for scope in self.scopes
            if scope.ownership is not Ownership.FOREIGN
            for path in iter_python_files((root / Path(scope.path.as_posix()),))
        }
        return tuple(
            path
            for path in sorted(candidates)
            if self.ownership_of(path, root) is not Ownership.FOREIGN
        )

    def abbreviation_for(self, token: str, relative: PurePosixPath) -> Abbreviation | None:
        """Resolve an exact token in the most-specific applicable scope.

        @param token identifier token to interpret
        @param relative repository-relative source path
        @return owning abbreviation record, or None when undeclared
        """
        matching = [
            abbreviation
            for abbreviation in self.abbreviations
            if abbreviation.token == token
            and any(
                relative == scope or relative.is_relative_to(scope) for scope in abbreviation.scopes
            )
        ]
        if not matching:
            return None
        return max(matching, key=lambda item: max(len(scope.parts) for scope in item.scopes))

    def properties_for(
        self, identifier: str, relative: PurePosixPath
    ) -> tuple[SemanticProperty, ...]:
        """Select declared properties for one name at one source path.

        @param identifier local or entity name
        @param relative repository-relative source path
        @return every applicable property in model order
        """
        return tuple(
            item
            for item in self.semantic_properties
            if fnmatch.fnmatchcase(identifier, item.identifier_pattern)
            and any(relative == scope or relative.is_relative_to(scope) for scope in item.scopes)
        )


def _object(raw: object, source: Path, location: str) -> Mapping[str, object]:
    """Narrow a decoded JSON value to an object.

    @param raw decoded value
    @param source model path
    @param location diagnostic field path
    @return mapping value
    @throws DocumentationModelError when the value is not an object
    """
    if not isinstance(raw, dict):
        _reject("DOCMODEL-002", source, f"{location} must be an object")
    return raw


def _closed(
    raw: Mapping[str, object], allowed: set[str] | frozenset[str], source: Path, location: str
) -> None:
    """Reject misspelled or future fields until the schema names them.

    @param raw decoded object
    @param allowed exact field vocabulary
    @param source model path
    @param location diagnostic object path
    """
    unknown = sorted(set(raw) - set(allowed))
    if unknown:
        _reject("DOCMODEL-003", source, f"{location} has unknown fields {unknown}")


def _path(raw: object, source: Path, location: str) -> PurePosixPath:
    """Parse one confined, non-root repository-relative path.

    @param raw decoded path value
    @param source model path
    @param location diagnostic field path
    @return normalized POSIX path
    """
    if not isinstance(raw, str) or not raw.strip():
        _reject("DOCMODEL-004", source, f"{location} must be a non-empty path")
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if candidate.is_absolute() or PureWindowsPath(raw).drive or ".." in candidate.parts:
        _reject("DOCMODEL-004", source, f"{location} must stay inside the repository")
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    if not parts:
        _reject("DOCMODEL-004", source, f"{location} may not name the repository root")
    return PurePosixPath(*parts)


def _strings(raw: object, source: Path, location: str, *, empty: bool = False) -> tuple[str, ...]:
    """Parse a unique array of non-empty strings.

    @param raw decoded array
    @param source model path
    @param location diagnostic field path
    @param empty whether an empty list is meaningful
    @return immutable strings in declaration order
    """
    if not isinstance(raw, list) or (not raw and not empty):
        _reject("DOCMODEL-005", source, f"{location} must be a non-empty string array")
    values = tuple(raw)
    if any(not isinstance(value, str) or not value.strip() for value in values):
        _reject("DOCMODEL-005", source, f"{location} contains a non-string or empty value")
    strings = tuple(str(value) for value in values)
    if len(set(strings)) != len(strings):
        _reject("DOCMODEL-005", source, f"{location} contains duplicates")
    return strings


def _scopes(raw: object, source: Path) -> tuple[Scope, ...]:
    """Parse the complete source ownership partition.

    @param raw decoded scopes array
    @param source model path
    @return validated scopes
    """
    if not isinstance(raw, list) or not raw:
        _reject("DOCMODEL-006", source, "scopes must be a non-empty array")
    scopes: list[Scope] = []
    for index, item in enumerate(raw):
        record = _object(item, source, f"scopes[{index}]")
        _closed(record, {"path", "kind", "ownership"}, source, f"scopes[{index}]")
        try:
            kind = ScopeKind(str(record.get("kind", "")))
            ownership = Ownership(str(record.get("ownership", "")))
        except ValueError as problem:
            _reject(
                "DOCMODEL-006", source, f"scopes[{index}] has unknown kind or ownership: {problem}"
            )
        scopes.append(
            Scope(_path(record.get("path"), source, f"scopes[{index}].path"), kind, ownership)
        )
    if len({scope.path for scope in scopes}) != len(scopes):
        _reject("DOCMODEL-006", source, "scope paths must be unique")
    if not any(scope.ownership is Ownership.GOVERNED for scope in scopes):
        _reject("DOCMODEL-006", source, "at least one scope must be governed")
    return tuple(scopes)


def _scope_paths(raw: object, source: Path, location: str) -> tuple[PurePosixPath, ...]:
    """Parse a non-empty array of confined scope paths.

    @param raw decoded array
    @param source model path
    @param location diagnostic field path
    @return normalized paths
    """
    values = _strings(raw, source, location)
    paths = tuple(_path(value, source, location) for value in values)
    if len(set(paths)) != len(paths):
        _reject("DOCMODEL-005", source, f"{location} contains duplicate paths")
    return paths


def _abbreviations(raw: object, source: Path) -> tuple[Abbreviation, ...]:
    """Parse controlled vocabulary and reject overlapping meanings.

    @param raw decoded abbreviation array
    @param source model path
    @return validated abbreviation records
    """
    if not isinstance(raw, list):
        _reject("DOCMODEL-007", source, "controlled_abbreviations must be an array")
    records: list[Abbreviation] = []
    for index, item in enumerate(raw):
        location = f"controlled_abbreviations[{index}]"
        record = _object(item, source, location)
        _closed(record, {"token", "meaning", "scopes"}, source, location)
        token = record.get("token")
        meaning = record.get("meaning")
        if not isinstance(token, str) or IDENTIFIER_TOKEN.fullmatch(token) is None:
            _reject("DOCMODEL-007", source, f"{location}.token is not an identifier token")
        if not isinstance(meaning, str) or not meaning.strip():
            _reject("DOCMODEL-007", source, f"{location}.meaning must be non-empty")
        records.append(
            Abbreviation(
                token, meaning, _scope_paths(record.get("scopes"), source, f"{location}.scopes")
            )
        )
    for index, left in enumerate(records):
        for right in records[index + 1 :]:
            if (
                left.token == right.token
                and left.meaning != right.meaning
                and _overlap(left.scopes, right.scopes)
            ):
                _reject(
                    "DOCMODEL-008",
                    source,
                    f"abbreviation {left.token!r} has two meanings in overlapping scopes",
                )
    return tuple(records)


def _overlap(left: Sequence[PurePosixPath], right: Sequence[PurePosixPath]) -> bool:
    """Whether either path set contains an ancestor of the other.

    @param left first path set
    @param right second path set
    @return true when their scopes intersect lexically
    """
    return any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for a in left for b in right)


def _grammars(raw: object, source: Path) -> tuple[IdentifierGrammar, ...]:
    """Parse optional scope-specific identifier grammars.

    @param raw decoded grammar array
    @param source model path
    @return validated grammar records
    """
    if not isinstance(raw, list):
        _reject("DOCMODEL-009", source, "identifier_grammars must be an array")
    records: list[IdentifierGrammar] = []
    for index, item in enumerate(raw):
        location = f"identifier_grammars[{index}]"
        record = _object(item, source, location)
        _closed(record, {"scope", "pattern", "dimensions", "exclusions"}, source, location)
        pattern = record.get("pattern")
        if not isinstance(pattern, str) or not pattern:
            _reject("DOCMODEL-009", source, f"{location}.pattern must be non-empty")
        try:
            compiled = re.compile(pattern)
        except re.error as problem:
            _reject("DOCMODEL-009", source, f"{location}.pattern is invalid: {problem}")
        dimensions = _strings(record.get("dimensions"), source, f"{location}.dimensions")
        if tuple(compiled.groupindex) != dimensions:
            _reject(
                "DOCMODEL-009",
                source,
                f"{location}.dimensions must equal named regex groups in broad-to-specific order",
            )
        records.append(
            IdentifierGrammar(
                _path(record.get("scope"), source, f"{location}.scope"),
                pattern,
                dimensions,
                _strings(
                    record.get("exclusions", []), source, f"{location}.exclusions", empty=True
                ),
            )
        )
    if len({record.scope for record in records}) != len(records):
        _reject("DOCMODEL-009", source, "identifier grammar scopes must be unique")
    return tuple(records)


def _generated_names(raw: object, source: Path) -> GeneratedNames:
    """Parse generated vocabulary markers and exact mappings.

    @param raw decoded generated-name object
    @param source model path
    @return validated generated-name model
    """
    record = _object(raw, source, "generated_names")
    _closed(record, {"markers", "mappings"}, source, "generated_names")
    markers = _strings(record.get("markers"), source, "generated_names.markers")
    mappings = _object(record.get("mappings"), source, "generated_names.mappings")
    for generated, canonical in mappings.items():
        if (
            not isinstance(generated, str)
            or IDENTIFIER_TOKEN.fullmatch(generated) is None
            or not isinstance(canonical, str)
            or not canonical.strip()
        ):
            _reject(
                "DOCMODEL-010",
                source,
                "generated-name mappings require identifier keys and non-empty canonical terms",
            )
        if not any(marker in generated.split("_") for marker in markers):
            _reject(
                "DOCMODEL-010",
                source,
                f"generated mapping {generated!r} carries none of the declared markers",
            )
    return GeneratedNames(markers, {str(key): str(value) for key, value in mappings.items()})


def _properties(raw: object, source: Path) -> tuple[SemanticProperty, ...]:
    """Parse project-declared mechanically inferable semantic properties.

    @param raw decoded property array
    @param source model path
    @return validated property records
    """
    if not isinstance(raw, list):
        _reject("DOCMODEL-011", source, "semantic_properties must be an array")
    records: list[SemanticProperty] = []
    for index, item in enumerate(raw):
        location = f"semantic_properties[{index}]"
        record = _object(item, source, location)
        _closed(record, {"identifier_pattern", "property", "value", "scopes"}, source, location)
        pattern = record.get("identifier_pattern")
        value = record.get("value")
        if not isinstance(pattern, str) or not pattern:
            _reject("DOCMODEL-011", source, f"{location}.identifier_pattern must be non-empty")
        if not isinstance(value, str) or not value.strip():
            _reject("DOCMODEL-011", source, f"{location}.value must be non-empty")
        try:
            property_kind = SemanticPropertyKind(str(record.get("property", "")))
        except ValueError as problem:
            _reject("DOCMODEL-011", source, f"{location}.property is unknown: {problem}")
        records.append(
            SemanticProperty(
                pattern,
                property_kind,
                value,
                _scope_paths(record.get("scopes"), source, f"{location}.scopes"),
            )
        )
    return tuple(records)


def parse(path: Path, declaration: project.Declaration) -> DocumentationModel:
    """Decode a strict model and verify its relationship to the declaration.

    @param path local JSON model
    @param declaration owning project declaration
    @return complete typed documentation model
    @throws DocumentationModelError for any absent, unknown, or inconsistent field
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as problem:
        _reject("DOCMODEL-001", path, f"cannot decode JSON: {problem}")
    root = _object(payload, path, "model")
    _closed(root, MODEL_FIELDS, path, "model")
    if root.get("schema_version") != 1:
        _reject("DOCMODEL-001", path, "schema_version must equal 1")
    if root.get("engine") != "doxygen" or declaration.doc_engine != "doxygen":
        _reject("DOCMODEL-001", path, "model and project must both select doxygen")
    scopes = _scopes(root.get("scopes"), path)
    for source_root in declaration.source_roots:
        if not any(
            scope.ownership is Ownership.GOVERNED
            and (source_root == scope.path or source_root.is_relative_to(scope.path))
            for scope in scopes
        ):
            _reject(
                "DOCMODEL-012",
                path,
                f"declared source root {source_root} has no governed documentation scope",
            )
    return DocumentationModel(
        schema_version=1,
        engine="doxygen",
        scopes=scopes,
        abbreviations=_abbreviations(root.get("controlled_abbreviations"), path),
        identifier_grammars=_grammars(root.get("identifier_grammars"), path),
        generated_names=_generated_names(root.get("generated_names"), path),
        semantic_properties=_properties(root.get("semantic_properties"), path),
        source=path,
    )


def load(declaration: project.Declaration) -> DocumentationModel:
    """Load the model named by one validated project declaration.

    @param declaration owning project declaration
    @return complete typed model
    @throws DocumentationModelError when no local model is declared
    """
    path = declaration.documentation_model_path()
    if path is None:
        source = declaration.source or Path("pyproject.toml")
        _reject("DOCMODEL-001", source, "documentation_model is not declared")
    return parse(path, declaration)


class DocumentationModelCheck(Check):
    """Expose model-schema failures through the ordinary custom-check gate."""

    ## Invoked as `python -m checks.documentation_model` through package discovery.
    name = "documentation_model"
    ## The project-owned model obligation this mechanism decides.
    rules = ("DOC-022",)

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Validate the declared model once, independently from source count.

        @param _paths ordinary check paths, unused because the declaration owns the artifact
        @return one actionable schema finding, or none
        """
        if self.declaration.source is None:
            return []
        try:
            load(self.declaration)
        except DocumentationModelError as problem:
            return [
                Finding(
                    "DOC-022",
                    problem.source,
                    1,
                    str(problem),
                    "Correct the model against enforce/templates/documentation-model.json; "
                    "unknown fields and escaping paths are never ignored.",
                    diagnostic_id=problem.diagnostic_id,
                )
            ]
        return []


def governed_modules(
    declaration: project.Declaration,
) -> Iterator[tuple[Path, str]]:
    """Yield every governed Python file and its repository-relative path.

    @param declaration owning project declaration
    @return file and POSIX-relative path pairs in stable order
    """
    model = load(declaration)
    root = declaration.root
    if root is None:
        return
    for path in model.governed_files(root):
        yield path, path.resolve().relative_to(root.resolve()).as_posix()


def governed_paths(declaration: project.Declaration, fallback: Sequence[Path]) -> tuple[Path, ...]:
    """Select model-governed files while leaving model errors to their owner.

    Other documentation checks use the ordinary production roots when the model
    itself is invalid. `DocumentationModelCheck` reports that root defect once;
    dependent checks do not crash or emit a cascade against an unreadable model.

    @param declaration owning project declaration
    @param fallback paths supplied to the ordinary check runner
    @return governed Python files, or the unchanged fallback
    """
    if declaration.source is None:
        return tuple(fallback)
    try:
        model = load(declaration)
    except DocumentationModelError:
        return tuple(fallback)
    root = declaration.root
    return tuple(fallback) if root is None else model.governed_files(root)
