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

# Import static collection contracts without runtime package dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

## Unordered field-name set whose each element is allowed at schema-version-one model root.
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

    ## Stable diagnostic namespace for rejected documentation-model propositions.
    code = "discipline.documentation_model.invalid"

    def __init__(self, diagnostic_id: str, source: Path, detail: str) -> None:
        """Preserve the rejected proposition and its owning artifact.

        @param diagnostic_id stable schema diagnostic
        @param source model or declaration path
        @param detail actionable explanation
        """
        # Initialize the standard exception message from the stable id, owner, and detail.
        super().__init__(f"{diagnostic_id} {source}: {detail}")
        # Retain the stable schema diagnostic for machine-readable gate output.
        self.diagnostic_id = diagnostic_id
        # Retain the exact owning artifact for localized remediation.
        self.source = source


def _reject(diagnostic_id: str, source: Path, detail: str) -> Never:
    """Raise one stable model diagnostic.

    @param diagnostic_id stable schema diagnostic
    @param source model or declaration path
    @param detail actionable explanation
    @return never
    @throws DocumentationModelError unconditionally
    """
    # Translate the localized proposition into the sole typed schema-error channel.
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
    ## Scope-path elements in declaration order within which this meaning applies.
    scopes: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class IdentifierGrammar:
    """Optional lexical grammar for one governed scope."""

    ## Path on which the grammar applies.
    scope: PurePosixPath
    ## Full-match regular expression for governed identifiers.
    pattern: str
    ## Semantic-dimension elements in required broad-to-specific order named by the pattern.
    dimensions: tuple[str, ...]
    ## Identifier elements explicitly outside the grammar in declaration order for review.
    exclusions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GeneratedNames:
    """Markers and exact derived-to-canonical vocabulary mappings."""

    ## Marker-token elements in declaration order that make a derived name visible.
    markers: tuple[str, ...]
    ## Mapping from each exact derived identifier key to its canonical domain-term value;
    ## mapping iteration order is deliberately unused.
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
    ## Governed scope-path elements in declaration order on which the property applies.
    scopes: tuple[PurePosixPath, ...]


@dataclass(frozen=True, slots=True)
class DocumentationModel:
    """Complete versioned project-owned evident-source declaration."""

    ## Integer schema identity for this closed model shape.
    schema_version: int
    ## Sole structured documentation engine selected by the model.
    engine: str
    ## Scope-record elements in declaration order forming the complete ownership partition.
    scopes: tuple[Scope, ...]
    ## Controlled-abbreviation record elements retained in declaration order.
    abbreviations: tuple[Abbreviation, ...]
    ## Identifier-grammar record elements retained in declaration order.
    identifier_grammars: tuple[IdentifierGrammar, ...]
    ## Generated-name markers and exact canonical-term mappings.
    generated_names: GeneratedNames
    ## Semantic-property record elements retained in declaration order.
    semantic_properties: tuple[SemanticProperty, ...]
    ## Artifact from which this value was parsed.
    source: Path

    def ownership_of(self, candidate: Path, root: Path) -> Ownership | None:
        """Resolve a path through the most-specific declared scope.

        @param candidate repository-owned file or directory
        @param root governed repository root
        @return most-specific ownership, or None outside every scope
        @par Effects Resolves filesystem paths without modifying repository state.
        """
        # Resolve the candidate against the repository and convert it to model POSIX spelling.
        try:
            # Hold the repository-relative path used for lexical scope membership.
            relative = PurePosixPath(candidate.resolve().relative_to(root.resolve()).as_posix())
        # A candidate resolving outside the repository belongs to no declared scope.
        except ValueError:
            # Return the explicit unowned alternative without inspecting scope records.
            return None
        # Collect each matching scope record in declaration order from broad and narrow paths.
        matching = [
            scope
            for scope in self.scopes
            if relative == scope.path or relative.is_relative_to(scope.path)
        ]
        # No matching scope means the candidate lies outside the documented ownership partition.
        if not matching:
            # Return the explicit unowned alternative.
            return None
        # Select the deepest path element count so the most-specific declared scope wins.
        return max(matching, key=lambda scope: len(scope.path.parts)).ownership

    def governed_files(self, root: Path) -> tuple[Path, ...]:
        """Enumerate Python whose most-specific owner is the repository.

        @param root governed repository root
        @return file elements sorted by path with duplicates removed
        @par Effects Resolves and enumerates declared filesystem paths without modifying them.
        """
        # Build an unordered set whose each element is a resolved non-foreign Python candidate.
        candidates = {
            path.resolve()
            for scope in self.scopes
            if scope.ownership is not Ownership.FOREIGN
            for path in iter_python_files((root / Path(scope.path.as_posix()),))
        }
        # Sort each unique candidate and retain only files whose most-specific owner is non-foreign.
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
        # Collect each exact-token declaration applicable to this source path in model order.
        matching = [
            abbreviation
            for abbreviation in self.abbreviations
            if abbreviation.token == token
            and any(
                relative == scope or relative.is_relative_to(scope) for scope in abbreviation.scopes
            )
        ]
        # No applicable declaration leaves this token outside controlled vocabulary.
        if not matching:
            # Return the explicit undeclared alternative.
            return None
        # Select the record containing the deepest applicable scope path.
        return max(matching, key=lambda item: max(len(scope.parts) for scope in item.scopes))

    def properties_for(
        self, identifier: str, relative: PurePosixPath
    ) -> tuple[SemanticProperty, ...]:
        """Select declared properties for one name at one source path.

        @param identifier local or entity name
        @param relative repository-relative source path
        @return applicable property-record elements in model declaration order
        """
        # Filter records by exact identifier glob and lexical source-scope membership.
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
    @return mapping whose each key is a JSON field name and each value is decoded data;
        source order is preserved by the decoder
    @throws DocumentationModelError when the value is not an object
    """
    # A non-object value cannot supply the named fields expected at this schema location.
    if not isinstance(raw, dict):
        # Reject with the exact object path rather than coercing a scalar or array.
        _reject("DOCMODEL-002", source, f"{location} must be an object")
    # Return the decoded key/value mapping with its JSON source order intact.
    return raw


def _closed(
    raw: Mapping[str, object], allowed: set[str] | frozenset[str], source: Path, location: str
) -> None:
    """Reject misspelled or future fields until the schema names them.

    @param raw decoded object mapping whose each key names a field and each value is decoded;
        mapping iteration order is deliberately unused
    @param allowed unordered field-name set whose each element is allowed at this location
    @param source model path
    @param location diagnostic object path
    """
    # Compute every unrecognized field name and sort the elements for stable diagnostics.
    unknown = sorted(set(raw) - set(allowed))
    # Any unknown field might be a misspelled obligation and therefore blocks parsing.
    if unknown:
        # Reject with the exact object path and sorted unknown-field elements.
        _reject("DOCMODEL-003", source, f"{location} has unknown fields {unknown}")


def _path(raw: object, source: Path, location: str) -> PurePosixPath:
    """Parse one confined, non-root repository-relative path.

    @param raw decoded path value
    @param source model path
    @param location diagnostic field path
    @return normalized POSIX path
    """
    # A path must first be non-empty text before lexical confinement is meaningful.
    if not isinstance(raw, str) or not raw.strip():
        # Reject absent, scalar, and whitespace-only spellings at the exact field path.
        _reject("DOCMODEL-004", source, f"{location} must be a non-empty path")
    # Normalize separator spelling into a platform-independent relative path candidate.
    candidate = PurePosixPath(raw.replace("\\", "/"))
    # True means an absolute, drive-qualified, or parent-traversing shape; false is relative.
    unsafe_shape = any(
        (candidate.is_absolute(), bool(PureWindowsPath(raw).drive), ".." in candidate.parts)
    )
    # Refuse every syntactically unsafe path before publishing model ownership.
    if unsafe_shape:
        # Reject with the exact field path and repository-containment requirement.
        _reject("DOCMODEL-004", source, f"{location} must stay inside the repository")
    # Retain each meaningful path component in source order while removing local-dot noise.
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    # The repository root itself is too broad to serve as a scoped ownership record.
    if not parts:
        # Reject the normalized-empty candidate at its exact field path.
        _reject("DOCMODEL-004", source, f"{location} may not name the repository root")
    # Reconstruct the normalized repository-relative POSIX path from ordered components.
    return PurePosixPath(*parts)


def _strings(raw: object, source: Path, location: str, *, empty: bool = False) -> tuple[str, ...]:
    """Parse a unique array of non-empty strings.

    @param raw decoded array
    @param source model path
    @param location diagnostic field path
    @param empty true when an empty array is meaningful; false when at least one element is required
    @return unique string elements in declaration order
    """
    # Require an array and, unless explicitly permitted, at least one element.
    if not isinstance(raw, list) or (not raw and not empty):
        # Reject the shape at its exact schema field path.
        _reject("DOCMODEL-005", source, f"{location} must be a non-empty string array")
    # Freeze each decoded array element in declaration order before type validation.
    values = tuple(raw)
    # Every element must be non-empty text; one invalid value rejects the complete array.
    if any(not isinstance(value, str) or not value.strip() for value in values):
        # Reject without coercing scalar elements into misleading text.
        _reject("DOCMODEL-005", source, f"{location} contains a non-string or empty value")
    # Convert the type-narrowed values to immutable strings in declaration order.
    strings = tuple(str(value) for value in values)
    # Duplicate elements carry no independent meaning and make exact ownership ambiguous.
    if len(set(strings)) != len(strings):
        # Reject rather than silently deduplicating and changing declaration intent.
        _reject("DOCMODEL-005", source, f"{location} contains duplicates")
    # Return the unique string elements in their authored declaration order.
    return strings


def _scopes(raw: object, source: Path) -> tuple[Scope, ...]:
    """Parse the complete source ownership partition.

    @param raw decoded scopes array
    @param source model path
    @return validated scope-record elements in declaration order
    """
    # Ownership requires a non-empty array before record validation can begin.
    if not isinstance(raw, list) or not raw:
        # Reject absent, scalar, and empty partitions at the one owning field.
        _reject("DOCMODEL-006", source, "scopes must be a non-empty array")
    # Accumulate each validated scope record in authored declaration order.
    scopes: list[Scope] = []
    # Parse every raw scope element with its stable array index.
    for index, item in enumerate(raw):
        # Localize the current record for all nested schema diagnostics.
        record = _object(item, source, f"scopes[{index}]")
        # Reject misspelled fields before interpreting any record values.
        _closed(record, {"path", "kind", "ownership"}, source, f"scopes[{index}]")
        # Parse the two closed enumerations together so either unknown value is localized once.
        try:
            # Convert the declared purpose spelling to the closed scope-kind enumeration.
            kind = ScopeKind(str(record.get("kind", "")))
            # Convert the declared authorship spelling to the closed ownership enumeration.
            ownership = Ownership(str(record.get("ownership", "")))
        # Translate an unknown enumeration spelling into the stable scope diagnostic.
        except ValueError as problem:
            # Reject the exact indexed record while retaining the enum conversion detail.
            _reject(
                "DOCMODEL-006", source, f"scopes[{index}] has unknown kind or ownership: {problem}"
            )
        # Append the confined path, closed purpose, and closed ownership as one scope record.
        scopes.append(
            Scope(_path(record.get("path"), source, f"scopes[{index}].path"), kind, ownership)
        )
    # Exact duplicate paths would create two owners at the same specificity.
    if len({scope.path for scope in scopes}) != len(scopes):
        # Reject rather than selecting one duplicate record by declaration order.
        _reject("DOCMODEL-006", source, "scope paths must be unique")
    # At least one governed record is required so the model cannot waive the complete repository.
    if not any(scope.ownership is Ownership.GOVERNED for scope in scopes):
        # Reject a partition consisting only of generated or foreign ownership.
        _reject("DOCMODEL-006", source, "at least one scope must be governed")
    # Freeze the unique validated scope elements in authored order.
    return tuple(scopes)


def _scope_paths(raw: object, source: Path, location: str) -> tuple[PurePosixPath, ...]:
    """Parse a non-empty array of confined scope paths.

    @param raw decoded array
    @param source model path
    @param location diagnostic field path
    @return unique normalized path elements in declaration order
    """
    # Parse the raw array as unique non-empty string elements in declaration order.
    values = _strings(raw, source, location)
    # Confine and normalize every string element while preserving declaration order.
    paths = tuple(_path(value, source, location) for value in values)
    # Normalization can collapse distinct spellings to one path and must not choose silently.
    if len(set(paths)) != len(paths):
        # Reject the complete field rather than silently deduplicating normalized elements.
        _reject("DOCMODEL-005", source, f"{location} contains duplicate paths")
    # Return unique confined path elements in authored declaration order.
    return paths


def _abbreviations(raw: object, source: Path) -> tuple[Abbreviation, ...]:
    """Parse controlled vocabulary and reject overlapping meanings.

    @param raw decoded abbreviation array
    @param source model path
    @return validated abbreviation-record elements in declaration order
    """
    # Controlled vocabulary may be empty but must always be represented as an array.
    if not isinstance(raw, list):
        # Reject scalar or object impostors at the one owning field.
        _reject("DOCMODEL-007", source, "controlled_abbreviations must be an array")
    # Accumulate each validated abbreviation record in authored declaration order.
    records: list[Abbreviation] = []
    # Parse every raw abbreviation element with its stable array index.
    for index, item in enumerate(raw):
        # Build the exact indexed schema path used by every nested diagnostic.
        location = f"controlled_abbreviations[{index}]"
        # Require the current array element to be an object mapping.
        record = _object(item, source, location)
        # Reject misspelled fields before interpreting record values.
        _closed(record, {"token", "meaning", "scopes"}, source, location)
        # Read the raw abbreviation token without coercing its type.
        token = record.get("token")
        # Read the raw expanded meaning without coercing its type.
        meaning = record.get("meaning")
        # Tokens must be text matching one complete Python identifier shape.
        if not isinstance(token, str) or IDENTIFIER_TOKEN.fullmatch(token) is None:
            # Reject the exact token field rather than normalizing invalid vocabulary.
            _reject("DOCMODEL-007", source, f"{location}.token is not an identifier token")
        # Meanings must be non-empty authored text.
        if not isinstance(meaning, str) or not meaning.strip():
            # Reject the exact meaning field rather than accepting an unexplained token.
            _reject("DOCMODEL-007", source, f"{location}.meaning must be non-empty")
        # Append the token, meaning, and ordered confined scope elements as one record.
        records.append(
            Abbreviation(
                token, meaning, _scope_paths(record.get("scopes"), source, f"{location}.scopes")
            )
        )
    # Compare each record with every later record exactly once for conflicting scope overlap.
    for index, left in enumerate(records):
        # Preserve later-record declaration order while excluding self and prior comparisons.
        for right in records[index + 1 :]:
            # Equal tokens may repeat only when meanings agree or their scope paths do not overlap.
            if (
                left.token == right.token
                and left.meaning != right.meaning
                and _overlap(left.scopes, right.scopes)
            ):
                # Reject two scoped meanings because a source identifier would be ambiguous.
                _reject(
                    "DOCMODEL-008",
                    source,
                    f"abbreviation {left.token!r} has two meanings in overlapping scopes",
                )
    # Freeze all validated abbreviation-record elements in authored order.
    return tuple(records)


def _overlap(left: Sequence[PurePosixPath], right: Sequence[PurePosixPath]) -> bool:
    """Whether either path set contains an ancestor of the other.

    @param left first scope-path elements in declaration order
    @param right second scope-path elements in declaration order
    @return true when their scopes intersect lexically
    """
    # True means any cross-product pair is equal or ancestor-related; false means disjoint scopes.
    return any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for a in left for b in right)


def _grammars(raw: object, source: Path) -> tuple[IdentifierGrammar, ...]:
    """Parse optional scope-specific identifier grammars.

    @param raw decoded grammar array
    @param source model path
    @return validated grammar-record elements in declaration order
    """
    # Scope-specific grammar declarations may be empty but must be represented as an array.
    if not isinstance(raw, list):
        # Reject scalar or object impostors at the one owning field.
        _reject("DOCMODEL-009", source, "identifier_grammars must be an array")
    # Accumulate each validated grammar record in authored declaration order.
    records: list[IdentifierGrammar] = []
    # Parse every raw grammar element with its stable array index.
    for index, item in enumerate(raw):
        # Build the exact indexed schema path used by every nested diagnostic.
        location = f"identifier_grammars[{index}]"
        # Require the current array element to be an object mapping.
        record = _object(item, source, location)
        # Reject misspelled fields before interpreting record values.
        _closed(record, {"scope", "pattern", "dimensions", "exclusions"}, source, location)
        # Read the raw regular-expression spelling without coercing its type.
        pattern = record.get("pattern")
        # Grammar patterns must be non-empty authored text.
        if not isinstance(pattern, str) or not pattern:
            # Reject the exact pattern field before attempting compilation.
            _reject("DOCMODEL-009", source, f"{location}.pattern must be non-empty")
        # Compile the full-match grammar while containing invalid-regex failures.
        try:
            # Hold the compiled expression used to inspect named semantic dimensions.
            compiled = re.compile(pattern)
        # Translate a regex syntax failure into the stable indexed grammar diagnostic.
        except re.error as problem:
            # Reject the exact pattern while retaining the compiler detail for remediation.
            _reject("DOCMODEL-009", source, f"{location}.pattern is invalid: {problem}")
        # Parse each declared dimension name in required broad-to-specific order.
        dimensions = _strings(record.get("dimensions"), source, f"{location}.dimensions")
        # Named regex groups must exactly equal the dimension elements in the same order.
        if tuple(compiled.groupindex) != dimensions:
            # Reject divergence because the grammar could otherwise reorder semantic dimensions.
            _reject(
                "DOCMODEL-009",
                source,
                f"{location}.dimensions must equal named regex groups in broad-to-specific order",
            )
        # Append the confined scope, compiled spelling, dimensions, and ordered exclusions.
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
    # Exact duplicate scopes would create two equally specific grammar owners.
    if len({record.scope for record in records}) != len(records):
        # Reject rather than selecting one grammar by declaration order.
        _reject("DOCMODEL-009", source, "identifier grammar scopes must be unique")
    # Freeze every validated grammar-record element in authored declaration order.
    return tuple(records)


def _generated_names(raw: object, source: Path) -> GeneratedNames:
    """Parse generated vocabulary markers and exact mappings.

    @param raw decoded generated-name object
    @param source model path
    @return validated generated-name model
    """
    # Require the generated-name field to be an object mapping.
    record = _object(raw, source, "generated_names")
    # Reject misspelled fields before parsing markers or canonical mappings.
    _closed(record, {"markers", "mappings"}, source, "generated_names")
    # Parse each visible marker-token element in declaration order.
    markers = _strings(record.get("markers"), source, "generated_names.markers")
    # Parse the exact-name mapping whose keys are derived identifiers and values canonical terms.
    mappings = _object(record.get("mappings"), source, "generated_names.mappings")
    # Validate every derived-name key and canonical-term value in JSON insertion order.
    for mapped_name, canonical in mappings.items():
        # Both sides must be non-empty text and the key must be a complete identifier.
        if (
            not isinstance(mapped_name, str)
            or IDENTIFIER_TOKEN.fullmatch(mapped_name) is None
            or not isinstance(canonical, str)
            or not canonical.strip()
        ):
            # Reject the entire mapping field because coercion would invent vocabulary.
            _reject(
                "DOCMODEL-010",
                source,
                "generated-name mappings require identifier keys and non-empty canonical terms",
            )
        # Every mapped identifier must visibly contain at least one declared marker token.
        if not any(marker in mapped_name.split("_") for marker in markers):
            # Reject a mapping that would relabel ordinary project vocabulary as derived.
            _reject(
                "DOCMODEL-010",
                source,
                f"generated mapping {mapped_name!r} carries none of the declared markers",
            )
    # Preserve marker element order and each exact derived-key/canonical-value mapping pair.
    return GeneratedNames(markers, {str(key): str(value) for key, value in mappings.items()})


def _properties(raw: object, source: Path) -> tuple[SemanticProperty, ...]:
    """Parse project-declared mechanically inferable semantic properties.

    @param raw decoded property array
    @param source model path
    @return validated semantic-property record elements in declaration order
    """
    # Semantic-property declarations may be empty but must be represented as an array.
    if not isinstance(raw, list):
        # Reject scalar or object impostors at the one owning field.
        _reject("DOCMODEL-011", source, "semantic_properties must be an array")
    # Accumulate each validated property record in authored declaration order.
    records: list[SemanticProperty] = []
    # Parse every raw property element with its stable array index.
    for index, item in enumerate(raw):
        # Build the exact indexed schema path used by every nested diagnostic.
        location = f"semantic_properties[{index}]"
        # Require the current array element to be an object mapping.
        record = _object(item, source, location)
        # Reject misspelled fields before interpreting record values.
        _closed(record, {"identifier_pattern", "property", "value", "scopes"}, source, location)
        # Read the raw shell-style identifier pattern without coercing its type.
        pattern = record.get("identifier_pattern")
        # Read the exact project-owned semantic value without coercing its type.
        value = record.get("value")
        # Identifier patterns must be non-empty authored text.
        if not isinstance(pattern, str) or not pattern:
            # Reject the exact pattern field before any scope allocation.
            _reject("DOCMODEL-011", source, f"{location}.identifier_pattern must be non-empty")
        # Semantic values must be non-empty authored text.
        if not isinstance(value, str) or not value.strip():
            # Reject the exact value field rather than accepting a contentless obligation.
            _reject("DOCMODEL-011", source, f"{location}.value must be non-empty")
        # Convert the property spelling to the schema's closed semantic-property enumeration.
        try:
            # Hold the typed category used by downstream semantic-content findings.
            property_kind = SemanticPropertyKind(str(record.get("property", "")))
        # Translate an unknown category into the stable indexed property diagnostic.
        except ValueError as problem:
            # Reject the exact property field while retaining the enum conversion detail.
            _reject("DOCMODEL-011", source, f"{location}.property is unknown: {problem}")
        # Append the pattern, category, value, and ordered confined scope elements.
        records.append(
            SemanticProperty(
                pattern,
                property_kind,
                value,
                _scope_paths(record.get("scopes"), source, f"{location}.scopes"),
            )
        )
    # Freeze every validated semantic-property record in authored declaration order.
    return tuple(records)


def parse(path: Path, declaration: project.Declaration) -> DocumentationModel:
    """Decode a strict model and verify its relationship to the declaration.

    @param path local JSON model
    @param declaration owning project declaration
    @return complete typed documentation model
    @throws DocumentationModelError for any absent, unknown, or inconsistent field
    @par Effects Reads the local JSON artifact without modifying repository state.
    """
    # Decode the exact UTF-8 model while containing access, encoding, and JSON syntax failures.
    try:
        # Hold the complete decoded JSON value before narrowing it to the closed object schema.
        payload = json.loads(path.read_text(encoding="utf-8"))
    # Translate every model-read failure into the stable root diagnostic channel.
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as problem:
        # Reject the model artifact while retaining the concrete decode detail.
        _reject("DOCMODEL-001", path, f"cannot decode JSON: {problem}")
    # Narrow the decoded root to a field/value mapping with source order preserved.
    root = _object(payload, path, "model")
    # Reject every unknown top-level field before interpreting versioned content.
    _closed(root, MODEL_FIELDS, path, "model")
    # Schema version one is the sole model shape understood by this package.
    if root.get("schema_version") != 1:
        # Reject missing, differently typed, or future version values explicitly.
        _reject("DOCMODEL-001", path, "schema_version must equal 1")
    # Both project and model must select the one v5 structured documentation engine.
    if root.get("engine") != "doxygen" or declaration.doc_engine != "doxygen":
        # Reject any split-brain or retired-engine combination.
        _reject("DOCMODEL-001", path, "model and project must both select doxygen")
    # Parse each scope-record element in declaration order as the ownership partition.
    scopes = _scopes(root.get("scopes"), path)
    # Verify every declared production-root element has a governed enclosing documentation scope.
    for source_root in declaration.source_roots:
        # Absence of any governed equal/ancestor scope leaves production outside documentation law.
        if not any(
            scope.ownership is Ownership.GOVERNED
            and (source_root == scope.path or source_root.is_relative_to(scope.path))
            for scope in scopes
        ):
            # Reject the exact production root rather than silently narrowing governed coverage.
            _reject(
                "DOCMODEL-012",
                path,
                f"declared source root {source_root} has no governed documentation scope",
            )
    # Construct the complete typed model from all independently validated ordered sections.
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
    @par Effects Resolves and reads the declared model artifact without modifying it.
    """
    # Resolve the optional project-relative model path through the validated declaration.
    path = declaration.documentation_model_path()
    # A v5 declaration without a local model cannot own source documentation semantics.
    if path is None:
        # Prefer the concrete declaration source, falling back to its conventional filename.
        source = declaration.source or Path("pyproject.toml")
        # Reject at the project artifact that must acquire the missing field.
        _reject("DOCMODEL-001", source, "documentation_model is not declared")
    # Decode and cross-check the resolved local model against its owning declaration.
    return parse(path, declaration)


class DocumentationModelCheck(Check):
    """Expose model-schema failures through the ordinary custom-check gate."""

    ## Invoked as `python -m checks.documentation_model` through package discovery.
    name = "documentation_model"
    ## Ordered one-element rule-id sequence for the project-owned model obligation.
    rules = ("DOC-022",)

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Validate the declared model once, independently from source count.

        @param _paths path elements in caller order, unused because the declaration owns the model
        @return an empty sequence or one actionable schema-finding element
        @par Effects Resolves and reads the declared model artifact without modifying it.
        """
        # A legacy or synthetic declaration with no source has no v5 model artifact to validate.
        if self.declaration.source is None:
            # Return the ordered empty finding sequence.
            return []
        # Parse the complete model so any schema defect is captured through its typed channel.
        try:
            # Discard the valid model value because this check owns only its accept/refuse result.
            load(self.declaration)
        # Convert one typed schema refusal into the ordinary custom-check finding contract.
        except DocumentationModelError as problem:
            # Return the sole localized finding with the original stable diagnostic subtype.
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
        # A fully valid model contributes no finding elements.
        return []


def governed_modules(
    declaration: project.Declaration,
) -> Iterator[tuple[Path, str]]:
    """Yield every governed Python file and its repository-relative path.

    @param declaration owning project declaration
    @return file/relative-path pair elements in sorted governed-file order
    @par Effects Resolves and enumerates declared filesystem paths without modifying them.
    """
    # Load the typed ownership model before enumerating any source path.
    model = load(declaration)
    # Resolve the governed repository boundary from the same project declaration.
    root = declaration.root
    # A synthetic declaration without a root cannot produce repository-relative module pairs.
    if root is None:
        # End the iterator without yielding any path element.
        return
    # Enumerate each governed file in the model's stable sorted order.
    for path in model.governed_files(root):
        # Yield the absolute file and its repository-relative POSIX spelling as one pair.
        yield path, path.resolve().relative_to(root.resolve()).as_posix()


def governed_paths(declaration: project.Declaration, fallback: Sequence[Path]) -> tuple[Path, ...]:
    """Select model-governed files while respecting an explicit narrow target.

    The aggregate gate passes the declaration's production roots and therefore
    expands to every governed production, test, and maintenance scope. A caller
    naming another file or directory receives the intersection with the model,
    which keeps focused inventory and editor invocations usable. Other checks use
    the supplied fallback unchanged when the model is invalid; its owning check
    reports the root defect once rather than causing a dependent-check crash.

    @param declaration owning project declaration
    @param fallback path elements supplied in caller order to the ordinary check runner
    @return governed file elements in sorted order, or fallback elements in caller order
    @par Effects Resolves and enumerates declared filesystem paths without modifying them.
    """
    # A legacy or synthetic declaration cannot name a v5 model, so preserve caller scope.
    if declaration.source is None:
        # Freeze the fallback elements in their supplied order.
        return tuple(fallback)
    # Load the typed ownership model while containing its separately reported schema failure.
    try:
        # Hold the valid model used to select complete governed source ownership.
        model = load(declaration)
    # A malformed model leaves dependent checks on their explicit caller scope.
    except DocumentationModelError:
        # Freeze the fallback elements in their supplied order.
        return tuple(fallback)
    # Resolve the governed repository boundary from the parsed project declaration.
    root = declaration.root
    # A synthetic declaration without a root cannot expand repository ownership.
    if root is None:
        # Freeze the fallback elements in their supplied order.
        return tuple(fallback)
    # Enumerate each governed Python file in stable sorted model order.
    governed = model.governed_files(root)
    # Resolve each requested path element while preserving caller order.
    requested = tuple(path.resolve() for path in fallback)
    # Resolve each declared production-root element in declaration order.
    production = tuple(path.resolve() for path in declaration.source_paths())
    # Aggregate-gate input exactly equals production roots and therefore requests all model scopes.
    if requested == production:
        # Return the complete stable governed-file sequence, including tests and maintenance.
        return governed
    # Preserve stable governed order while selecting files under any explicitly requested target.
    return tuple(
        path
        for path in governed
        if any(path == target or path.is_relative_to(target) for target in requested)
    )
