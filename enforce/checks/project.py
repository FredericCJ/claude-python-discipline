"""The bounded declaration every v5 project check consumes.

The declaration describes one governed repository, not a collection of
switches. It names whether that repository delivers an application or one
component, where its production Python lives, how those paths map to the five
hexagonal roles, which additive local capabilities it owns, and which
documentation syntax it deliberately uses.

    [tool.agent-discipline]
    unit = "component"             # application | component
    source_roots = ["src"]
    doc_engine = "doxygen"
    documentation_model = "documentation-model.json"

    [tool.agent-discipline.capabilities]
    network_io = true               # every v4 key is an explicit boolean

    [tool.agent-discipline.roles]
    domain = ["src/example/domain"]
    application = ["src/example/app"]
    ports = ["src/example/ports"]
    adapters = ["src/example/adapters"]
    shell = ["src/example/shell"]

Paths are repository-relative and explicit. A path that is not covered by a
role is therefore observable rather than silently classified as ``unknown``.
The older segment-alias table is still parsed so the v3 migrator can explain it,
but v4 projects use ``roles``.

Repository confinement is part of this model. The nearest ``pyproject.toml`` is
the root boundary even when it carries no discipline table; loading never walks
through it into a parent/meta-repository, and an explicit project file is
accepted only when it is that nearest file.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never

# Import the static mapping contract without a runtime collection dependency.
if TYPE_CHECKING:
    from collections.abc import Mapping


class UnitKind(StrEnum):
    """The two repository shapes governed by the discipline."""

    ## Repository owning the complete delivered application.
    APPLICATION = "application"
    ## One independently testable component repository.
    COMPONENT = "component"


class Capability(StrEnum):
    """Repository-local facts that activate additional v4 obligations."""

    ## The deliverable exposes a supported programmatic or command interface.
    PUBLIC_API = "public_api"
    ## Production behavior reads or changes a filesystem owned or supplied locally.
    FILESYSTEM_IO = "filesystem_io"
    ## The repository owns durable state and its compatibility or recovery.
    PERSISTENT_STATE = "persistent_state"
    ## Authored inputs produce reviewable derived artifacts.
    GENERATED_ARTIFACTS = "generated_artifacts"
    ## Production behavior opens, accepts, or uses network communication.
    NETWORK_IO = "network_io"
    ## Production behavior creates another operating-system process.
    LAUNCHES_SUBPROCESSES = "launches_subprocesses"
    ## Lifecycle authority for launched children remains in this repository.
    OWNS_SUBPROCESS_LIFECYCLE = "owns_subprocess_lifecycle"
    ## Production behavior admits overlapping tasks, threads, or processes.
    CONCURRENCY = "concurrency"
    ## Production behavior can irreversibly change external or durable state.
    DESTRUCTIVE_EFFECTS = "destructive_effects"
    ## A published response or completion latency has a finite local budget.
    BOUNDED_LATENCY = "bounded_latency"
    ## The repository intentionally handles classified or secret-bearing data.
    SENSITIVE_DATA = "sensitive_data"


class DeclarationError(ValueError):
    """A stable project-declaration diagnostic.

    @param diagnostic_id durable code identifying the rejected proposition
    @param source project file carrying the invalid value
    @param detail human-readable explanation and remediation clue
    """

    ## Stable diagnostic namespace for rejected project declarations.
    code = "discipline.project.invalid"

    def __init__(self, diagnostic_id: str, source: Path, detail: str) -> None:
        """Build a declaration failure without baking formatting into call sites.

        @param diagnostic_id durable code identifying the rejected proposition
        @param source project file carrying the invalid value
        @param detail human-readable explanation and remediation clue
        """
        # Initialize the standard exception message from the stable id, owner, and detail.
        super().__init__(f"{diagnostic_id} {source}: {detail}")
        # Retain the stable schema diagnostic for machine-readable gate output.
        self.diagnostic_id = diagnostic_id
        # Retain the exact owning project artifact for localized remediation.
        self.source = source


def _reject(diagnostic_id: str, source: Path, detail: str) -> Never:
    """Raise one declaration diagnostic without duplicating exception mechanics.

    @param diagnostic_id durable code identifying the rejected proposition
    @param source project file carrying the invalid value
    @param detail human-readable explanation and remediation clue
    @return never; this helper always raises
    @throws DeclarationError unconditionally
    """
    # Translate the localized proposition into the sole typed declaration-error channel.
    raise DeclarationError(diagnostic_id, source, detail)


## Mapping whose each public role-name key resolves to its internal check-layer value;
## insertion order is the canonical role presentation order. Executable roles retain ``app``
## internally for compatibility with the AST
## checks written before v4. The declaration spells the role ``application``;
## users should not have to learn an implementation abbreviation.
ROLE_TO_LAYER: Final[dict[str, str]] = {
    "domain": "domain",
    "application": "app",
    "ports": "ports",
    "adapters": "adapters",
    "shell": "shell",
}
## Public role-name elements in stable canonical presentation order.
CANONICAL_ROLES: Final[tuple[str, ...]] = tuple(ROLE_TO_LAYER)
## Legacy internal layer-name elements in stable role presentation order for v3 AST checks.
CANONICAL_LAYERS: Final[tuple[str, ...]] = tuple(ROLE_TO_LAYER.values())
## Unordered engine-name set whose sole element is the structured engine supported by v5.
DOC_ENGINES: Final[frozenset[str]] = frozenset({"doxygen"})
## Unordered retired-engine set whose each element receives actionable v4-to-v5 migration guidance.
LEGACY_DOC_ENGINES: Final[frozenset[str]] = frozenset({"sphinx", "none"})
## TOML table name beneath ``tool``.
TABLE: Final = "agent-discipline"
## One top-level Python import identifier, excluding dotted module paths.
IMPORT_ROOT: Final = re.compile(r"^[A-Za-z_]\w*$")
## Capability-enum elements in canonical declaration and rendering order.
CAPABILITIES: Final[tuple[Capability, ...]] = tuple(Capability)


def _relative_path(raw: object, *, field_name: str, source: Path) -> PurePosixPath:
    """Validate and normalize one repository-relative declaration path.

    @param raw value read from TOML
    @param field_name declaration field used in a diagnostic
    @param source project file that owns the value
    @return a normalized POSIX path
    @throws ValueError when the path could escape or identify the repository root
    """
    # A path must first be non-empty text before lexical confinement is meaningful.
    if not isinstance(raw, str) or not raw.strip():
        # Reject absent, scalar, and whitespace-only values at the exact declaration field.
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} entries must be non-empty strings",
        )
    # Normalize separator spelling into a platform-independent relative path candidate.
    candidate = PurePosixPath(raw.replace("\\", "/"))
    # True means an absolute, drive-qualified, or parent-traversing shape; false is relative.
    unsafe_shape = any(
        (candidate.is_absolute(), bool(PureWindowsPath(raw).drive), ".." in candidate.parts)
    )
    # Refuse every syntactically unsafe path before publishing repository ownership.
    if unsafe_shape:
        # Reject with the exact field and submitted spelling for actionable remediation.
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} path {raw!r} must stay inside the repository",
        )
    # Retain each meaningful path component in source order while removing local-dot noise.
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    # The repository root itself is too broad for a declared artifact or ownership boundary.
    if not parts:
        # Reject the normalized-empty candidate at its exact declaration field.
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} may not name the repository root",
        )
    # Reconstruct the normalized repository-relative POSIX path from ordered components.
    return PurePosixPath(*parts)


def _path_tuple(
    raw: object,
    *,
    field_name: str,
    source: Path,
) -> tuple[PurePosixPath, ...]:
    """Parse a non-empty TOML array of unique repository-relative paths.

    @param raw value read from TOML
    @param field_name declaration field used in a diagnostic
    @param source project file that owns the value
    @return unique path elements in declaration order
    @throws ValueError when the value is not a valid non-empty path array
    """
    # A path collection must be a non-empty array before element validation begins.
    if not isinstance(raw, list) or not raw:
        # Reject absent, scalar, and empty arrays at the exact declaration field.
        _reject(
            "DISC-PROJECT-003",
            source,
            f"{field_name} must be a non-empty array of source paths",
        )
    # Confine and normalize each path element while preserving declaration order.
    paths = tuple(_relative_path(value, field_name=field_name, source=source) for value in raw)
    # Duplicate normalized paths have no independent meaning and create ambiguous ownership.
    if len(set(paths)) != len(paths):
        # Reject rather than silently deduplicating and changing declaration intent.
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} contains a duplicate path",
        )
    # Return the unique confined path elements in authored declaration order.
    return paths


@dataclass(frozen=True, slots=True)
class Declaration:
    """What one repository says about its governed unit and local conventions."""

    ## None exists only for the conspicuous undeclared fallback used by direct
    ## check invocations. The canonical project gate refuses that fallback.
    unit: UnitKind | None = None
    ## Production-root path elements in declaration order, relative to ``source.parent``.
    source_roots: tuple[PurePosixPath, ...] = ()
    ## Canonical local architecture record relative to the repository root.
    architecture: PurePosixPath | None = None
    ## Contract implementation and behavioral-evidence registry.
    contract_conformance: PurePosixPath | None = None
    ## Repository-local lifecycle, budget, outcome, and platform model.
    operational_model: PurePosixPath | None = None
    ## Repository-local trust-boundary and data-classification model.
    security_model: PurePosixPath | None = None
    ## Content-bound semantic and adversarial review artifact.
    adversarial_review: PurePosixPath | None = None
    ## Project-owned scope, vocabulary, naming, and semantic-property model.
    documentation_model: PurePosixPath | None = None
    ## Unordered capability set whose each enabled element adds operational/security obligations.
    capabilities: frozenset[Capability] = frozenset()
    ## Mapping from each canonical role-name key to ordered repository-relative path values;
    ## mapping insertion order follows declaration order.
    role_paths: Mapping[str, tuple[PurePosixPath, ...]] = field(default_factory=dict)
    ## Independently substitutable adapter-boundary path elements in declaration order.
    adapter_boundaries: tuple[PurePosixPath, ...] = ()
    ## Mapping from each legacy segment key to its canonical layer value; mapping order is unused.
    layers: Mapping[str, str] = field(default_factory=dict)
    ## Mapping from each foreign import-root key to its one owning adapter-path value;
    ## mapping insertion order follows declaration order.
    foreign_ownership: Mapping[str, PurePosixPath] = field(default_factory=dict)
    ## Documentation comment syntax selected by the repository.
    doc_engine: str = "none"
    ## True when the repository explicitly selected the syntax; false for the legacy fallback.
    doc_engine_declared: bool = False
    ## True when every teaching artifact is deliberately projected; false for ordinary scope.
    pedagogical_full_projection: bool = False
    ## The project file this declaration was parsed from.
    source: Path | None = None

    @property
    def root(self) -> Path | None:
        """The governed repository root, when a declaration was loaded.

        @return the directory containing the declaring ``pyproject.toml``
        """
        # Return the declaration's parent boundary, or None when no project artifact was loaded.
        return None if self.source is None else self.source.parent

    def canonical(self, segment: str) -> str | None:
        """The legacy canonical layer named by one path segment, if any.

        @param segment one path segment
        @return the canonical layer, or None when it is not a v3 layer alias
        """
        # An explicit legacy alias mapping takes precedence over canonical spelling.
        if segment in self.layers:
            # Return the mapped internal layer value for this exact segment key.
            return self.layers[segment]
        # Canonical internal layer spellings map to themselves.
        if segment in CANONICAL_LAYERS:
            # Return the unchanged canonical segment.
            return segment
        # None means the path segment names no v3 layer alias or canonical layer.
        return None

    def role_of(self, path: Path) -> str | None:
        """Resolve a source path against the explicit v4 role paths.

        Explicit role paths replace segment guessing. When no v4 role table is
        present, the v3 segment vocabulary remains available solely to migration
        and direct legacy checks.

        @param path source file or directory to classify
        @return the check-layer name, or None when no role owns the path
        @par Effects Resolves filesystem paths without modifying repository state.
        """
        # Prefer explicit v4 role ownership whenever both role paths and repository root exist.
        if self.role_paths and self.root is not None:
            # Resolve the candidate relative to the governed repository boundary.
            try:
                # Hold the platform path relative to the exact project root.
                relative = path.resolve().relative_to(self.root.resolve())
            # A path outside the repository cannot belong to any declared local role.
            except ValueError:
                # Return the explicit unowned alternative.
                return None
            # Convert the relative candidate to the POSIX spelling used by declarations.
            candidate = PurePosixPath(relative.as_posix())
            # Collect each owning internal role-layer value in role and prefix declaration order.
            matches = [
                ROLE_TO_LAYER[role]
                for role, prefixes in self.role_paths.items()
                for prefix in prefixes
                if candidate == prefix or candidate.is_relative_to(prefix)
            ]
            # Exactly one owner resolves classification; zero or overlap remains observable as None.
            return matches[0] if len(matches) == 1 else None
        # Legacy declarations classify by each platform path segment in lexical order.
        for part in path.parts:
            # Resolve the segment through explicit aliases and canonical layer spellings.
            canonical = self.canonical(part)
            # The first recognized segment provides the legacy classification.
            if canonical is not None:
                # Return the resolved internal layer without scanning later segments.
                return canonical
        # A direct module file may encode the legacy layer in its filename stem.
        if path.suffix:
            # Resolve the stem through the same legacy alias vocabulary.
            return self.canonical(path.stem)
        # None means neither explicit v4 roles nor legacy path segments own this path.
        return None

    def source_paths(self) -> tuple[Path, ...]:
        """The declared production roots as absolute local paths.

        @return absolute production-path elements in declaration order, or an empty sequence
            for the undeclared fallback
        """
        # An undeclared fallback has no repository boundary against which to resolve roots.
        if self.root is None:
            # Return the ordered empty path sequence.
            return ()
        # Resolve each repository-relative production root while preserving declaration order.
        return tuple(self.root / Path(root.as_posix()) for root in self.source_roots)

    def architecture_path(self) -> Path | None:
        """The declared local architecture record as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        # Resolve the optional architecture spelling through the one repository boundary helper.
        return self._artifact_path(self.architecture)

    def contract_conformance_path(self) -> Path | None:
        """The declared conformance registry as an absolute local path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        # Resolve the optional registry spelling through the one repository boundary helper.
        return self._artifact_path(self.contract_conformance)

    def operational_model_path(self) -> Path | None:
        """The declared local operational model as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        # Resolve the optional operational-model spelling through the one boundary helper.
        return self._artifact_path(self.operational_model)

    def security_model_path(self) -> Path | None:
        """The declared local security model as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        # Resolve the optional security-model spelling through the one boundary helper.
        return self._artifact_path(self.security_model)

    def adversarial_review_path(self) -> Path | None:
        """The declared adversarial review artifact as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        # Resolve the optional review spelling through the one repository boundary helper.
        return self._artifact_path(self.adversarial_review)

    def documentation_model_path(self) -> Path | None:
        """Resolve the project-owned documentation model.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        # Resolve the optional documentation-model spelling through the one boundary helper.
        return self._artifact_path(self.documentation_model)

    def _artifact_path(self, relative: PurePosixPath | None) -> Path | None:
        """Resolve one optional declaration artifact inside the repository boundary.

        @param relative confined repository-relative artifact spelling, or None when undeclared
        @return absolute local artifact path, or None when root or spelling is absent
        """
        # Hold the declared repository boundary, or None for the direct-check fallback.
        root = self.root
        # Missing root or artifact spelling yields the explicit unavailable alternative.
        if root is None or relative is None:
            # Return None without constructing a path outside a declared repository.
            return None
        # Join the confined POSIX spelling to the one local repository boundary.
        return root / Path(relative.as_posix())

    def has(self, capability: Capability) -> bool:
        """Whether one additive project capability is active.

        @param capability fact whose obligations are being selected
        @return true only when the manifest explicitly enables it
        """
        # True means the closed capability element was explicitly enabled; false means disabled.
        return capability in self.capabilities

    def _documentation_notes(self) -> tuple[str, ...]:
        """Visible consequences of the engine declaration in force.

        @return note elements ordered as undeclared-selection then incompatible-engine consequence
        """
        # Accumulate each visible consequence in stable declaration-then-engine order.
        notes: list[str] = []
        # A false declaration flag means direct checks are using a non-project fallback.
        if not self.doc_engine_declared:
            # Append the explicit gate refusal before any engine-specific consequence.
            notes.append(
                "DISC-PROJECT-007 doc_engine is undeclared; direct checks use 'none', "
                "but a v5 project gate must refuse this repository"
            )
        # Any engine other than Doxygen is incompatible with the closed v5 project contract.
        if self.doc_engine != "doxygen":
            # Append actionable migration guidance after the declaration-presence note.
            notes.append(
                f"DISC-PROJECT-021 doc_engine is {self.doc_engine!r}; v5 requires "
                "'doxygen'. Run the v5 migration to replace the former sphinx/none choice."
            )
        # Freeze each note element in its stable explanatory order.
        return tuple(notes)

    def narrowed(self) -> tuple[str, ...]:
        """Facts a direct check invocation could not decide from this declaration.

        @return note elements in declaration-field order, one per missing or narrowed fact
        """
        # Accumulate each undecided declaration fact in stable schema-field order.
        notes: list[str] = []
        # Missing unit leaves application-versus-component scope undecided.
        if self.unit is None:
            # Append the exact unit declaration refusal first.
            notes.append(
                "DISC-PROJECT-001 unit is undeclared; a v4 project gate must refuse this repository"
            )
        # An empty production-root sequence leaves source ownership undecided.
        if not self.source_roots:
            # Append the source-root coverage consequence after unit scope.
            notes.append(
                "DISC-PROJECT-003 source_roots are undeclared; source-role coverage is undecided"
            )
        # Missing architecture path leaves local design projection undecided.
        if self.architecture is None:
            # Append the architecture-artifact consequence in schema order.
            notes.append(
                "DISC-PROJECT-014 architecture is undeclared; local design views are undecided"
            )
        # Missing conformance registry leaves typed implementation evidence undecided.
        if self.contract_conformance is None:
            # Append the contract-conformance consequence in schema order.
            notes.append(
                "DISC-PROJECT-015 contract_conformance is undeclared; typed "
                "implementation and shared-suite evidence are undecided"
            )
        # Missing operational model leaves lifecycle and budget propositions undecided.
        if self.operational_model is None:
            # Append the operational-model consequence in schema order.
            notes.append(
                "DISC-PROJECT-018 operational_model is undeclared; lifecycle, "
                "budgets, outcomes, identity, and platform support are undecided"
            )
        # Missing security model leaves trust and classification propositions undecided.
        if self.security_model is None:
            # Append the security-model consequence in schema order.
            notes.append(
                "DISC-PROJECT-019 security_model is undeclared; trust boundaries "
                "and data classification are undecided"
            )
        # Missing review artifact leaves semantic challenge and closure undecided.
        if self.adversarial_review is None:
            # Append the adversarial-review consequence in schema order.
            notes.append(
                "DISC-PROJECT-020 adversarial_review is undeclared; semantic review "
                "scope, freshness, objections, and closure are undecided"
            )
        # Missing documentation model leaves ownership and vocabulary undecided.
        if self.documentation_model is None:
            # Append the documentation-model consequence in schema order.
            notes.append(
                "DISC-PROJECT-022 documentation_model is undeclared; governed "
                "documentation scopes and project vocabulary are undecided"
            )
        # Missing declaration source means no complete explicit capability table was parsed.
        if self.source is None:
            # Append the capability-declaration consequence after local artifact paths.
            notes.append(
                "DISC-PROJECT-016 capabilities are undeclared; additive local "
                "operational obligations are undecided"
            )
        # Append documentation-engine consequences after all general declaration facts.
        notes.extend(self._documentation_notes())
        # Freeze every note element in the stable user-facing diagnostic order.
        return tuple(notes)


## Conspicuously incomplete fallback used only by direct legacy check calls.
DEFAULT: Final = Declaration()


def find_project_file(start: Path) -> Path | None:
    """Find the nearest repository-defining ``pyproject.toml``.

    @param start file or directory inside the repository
    @return the nearest project file, or None when no ancestor has one
    @par Effects Resolves and inspects filesystem paths without modifying them.
    """
    # Resolve the starting subject to a stable absolute path.
    here = start.resolve()
    # File subjects begin ancestor search from their containing directory.
    if here.is_file():
        # Replace the file subject with its immediate parent directory.
        here = here.parent
    # Inspect the starting directory then each ancestor in nearest-first order.
    for directory in (here, *here.parents):
        # Form the conventional project declaration candidate at this boundary.
        candidate = directory / "pyproject.toml"
        # The first existing file is the nearest repository-defining project artifact.
        if candidate.is_file():
            # Return immediately so search never crosses a nearer repository boundary.
            return candidate
    # None means no ancestor directory contains a project declaration.
    return None


def find_declaration(start: Path) -> Path | None:
    """Return the nearest project file only when it carries the discipline table.

    The search deliberately stops at the first project file. Skipping it and
    reading an ancestor would make a component inherit its parent repository's
    unit, paths, and verdict.

    @param start file or directory inside the repository
    @return its project file, or None when that file has no declaration
    @par Effects Resolves and reads the nearest project file without modifying it.
    """
    # Locate the nearest repository-defining project artifact without crossing it.
    candidate = find_project_file(start)
    # A path outside any Python project has no discipline declaration.
    if candidate is None:
        # Return the explicit undeclared alternative.
        return None
    # Decode the nearest project while containing access and TOML syntax failures.
    try:
        # Hold the complete decoded TOML mapping with source field order preserved.
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    # An unreadable or malformed nearest project still blocks ancestor inheritance.
    except (OSError, tomllib.TOMLDecodeError):
        # Return no declaration rather than crossing into a parent repository.
        return None
    # Return the nearest project only when its tool mapping owns the discipline table.
    return candidate if TABLE in data.get("tool", {}) else None


def _parse_roles(
    table: Mapping[str, object],
    path: Path,
    roots: tuple[PurePosixPath, ...],
) -> dict[str, tuple[PurePosixPath, ...]]:
    """Parse role paths and reject unknown, overlapping, or out-of-root entries.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order follows the declaration
    @param path declaring project file
    @param roots production-root path elements in declaration order
    @return mapping from each canonical role-name key to ordered path values;
        mapping insertion order follows declaration order
    @throws ValueError when paths do not form an unambiguous local partition
    """
    # Select the decoded roles object, defaulting absence to an ordered empty mapping.
    raw_roles = table.get("roles") or {}
    # Role ownership must be represented by a TOML table rather than a scalar or array.
    if not isinstance(raw_roles, dict):
        # Reject at the one owning declaration field.
        _reject("DISC-PROJECT-005", path, "roles must be a TOML table")
    # Build an unordered set whose each element is an unrecognized role-name key.
    unknown = set(raw_roles) - set(CANONICAL_ROLES)
    # Unknown roles might be misspelled ownership boundaries and cannot be ignored.
    if unknown:
        # Reject with sorted unknown elements and canonical expected elements.
        _reject(
            "DISC-PROJECT-005",
            path,
            f"unknown roles {', '.join(sorted(unknown))}; expected {', '.join(CANONICAL_ROLES)}",
        )
    # Parse each role key to its unique confined path elements in TOML insertion order.
    parsed = {
        role: _path_tuple(raw, field_name=f"roles.{role}", source=path)
        for role, raw in raw_roles.items()
    }
    # Flatten each role/path pair element in role insertion then path declaration order.
    owners: list[tuple[str, PurePosixPath]] = [
        (role, role_path) for role, paths in parsed.items() for role_path in paths
    ]
    # Validate every role/path owner pair against production roots and every other owner.
    for role, role_path in owners:
        # Each role path must equal or descend from at least one declared production root.
        if not any(role_path == root or role_path.is_relative_to(root) for root in roots):
            # Reject the exact role/path pair that lies beyond production ownership.
            _reject(
                "DISC-PROJECT-006",
                path,
                f"roles.{role} path {role_path} lies outside source_roots",
            )
        # Preserve each overlapping other-role description in owner-list order.
        conflicts = [
            f"{other}:{other_path}"
            for other, other_path in owners
            if (other, other_path) != (role, role_path)
            and (role_path.is_relative_to(other_path) or other_path.is_relative_to(role_path))
        ]
        # Any ancestor relation gives one source path multiple role owners.
        if conflicts:
            # Reject the current path with every conflicting role/path element.
            _reject(
                "DISC-PROJECT-006",
                path,
                f"roles.{role} path {role_path} overlaps {', '.join(conflicts)}",
            )
    # Return canonical role keys and their ordered confined path elements.
    return parsed


def _parse_foreign_ownership(
    table: Mapping[str, object],
    path: Path,
    roots: tuple[PurePosixPath, ...],
    roles: Mapping[str, tuple[PurePosixPath, ...]],
    boundaries: tuple[PurePosixPath, ...],
) -> dict[str, PurePosixPath]:
    """Parse direct foreign-import ownership records.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order follows the declaration
    @param path declaring project file
    @param roots production-root path elements in declaration order
    @param roles mapping from each canonical role key to ordered path values; mapping order follows
        declaration order
    @param boundaries adapter-boundary path elements in declaration order
    @return mapping from each import-root key to its single adapter-path value;
        mapping insertion order follows declaration order
    @throws DeclarationError when an import or owner is ambiguous or misplaced
    """
    # Select the raw ownership array, defaulting absence to an ordered empty sequence.
    raw_records = table.get("foreign_dependencies") or []
    # Foreign ownership must be represented as an array of record tables.
    if not isinstance(raw_records, list):
        # Reject a scalar or table impostor at the one owning declaration field.
        _reject(
            "DISC-PROJECT-010",
            path,
            "foreign_dependencies must be an array of TOML tables",
        )
    # Map each import-root key to one confined owner value in declaration insertion order.
    parsed: dict[str, PurePosixPath] = {}
    # Select adapter-role path elements in declaration order, or an empty sequence when absent.
    adapter_paths = roles.get("adapters", ())
    # Parse every foreign-dependency record element with its stable array index.
    for index, raw_record in enumerate(raw_records):
        # Each record must be a table before field-level validation can proceed.
        if not isinstance(raw_record, dict):
            # Reject the exact indexed scalar or array impostor.
            _reject(
                "DISC-PROJECT-010",
                path,
                f"foreign_dependencies[{index}] must be a TOML table",
            )
        # Build an unordered set whose each element is an unrecognized record field.
        unknown = set(raw_record) - {"import_name", "owner"}
        # Unknown fields might be misspelled ownership facts and cannot be ignored.
        if unknown:
            # Reject with sorted unknown-field elements for deterministic remediation.
            _reject(
                "DISC-PROJECT-010",
                path,
                f"foreign_dependencies[{index}] has unknown fields {', '.join(sorted(unknown))}",
            )
        # Read the raw import root without coercing its type or accepting dotted modules.
        import_name = raw_record.get("import_name")
        # One complete Python identifier is required as the direct import boundary.
        if not isinstance(import_name, str) or IMPORT_ROOT.fullmatch(import_name) is None:
            # Reject the exact indexed import-name field.
            _reject(
                "DISC-PROJECT-011",
                path,
                f"foreign_dependencies[{index}].import_name must be one Python import root",
            )
        # Each import root has exactly one owner in the local declaration.
        if import_name in parsed:
            # Reject the later duplicate rather than replacing its prior owner.
            _reject(
                "DISC-PROJECT-011",
                path,
                f"foreign import {import_name!r} has more than one owner",
            )
        # Parse and confine the record's repository-relative owner path.
        owner = _relative_path(
            raw_record.get("owner"),
            field_name=f"foreign_dependencies[{index}].owner",
            source=path,
        )
        # The owner must equal or descend from one declared adapter-role path element.
        if not any(owner == adapter or owner.is_relative_to(adapter) for adapter in adapter_paths):
            # Reject ownership assigned to domain, application, ports, shell, or unowned paths.
            _reject(
                "DISC-PROJECT-012",
                path,
                f"owner {owner} for {import_name!r} is not inside a declared adapter role",
            )
        # When boundaries exist, the owner must lie inside one substitutable unit.
        if boundaries and not any(
            owner == boundary or owner.is_relative_to(boundary) for boundary in boundaries
        ):
            # Reject an adapter owner that is too broad for the declared component partition.
            _reject(
                "DISC-PROJECT-012",
                path,
                f"owner {owner} for {import_name!r} is not inside a declared adapter boundary",
            )
        # Every foreign owner remains inside the repository's declared production roots.
        if not any(owner == root or owner.is_relative_to(root) for root in roots):
            # Reject an otherwise adapter-shaped owner outside production scope.
            _reject(
                "DISC-PROJECT-012",
                path,
                f"owner {owner} for {import_name!r} lies outside source_roots",
            )
        # Publish the validated import-root/owner pair after every confinement predicate passes.
        parsed[import_name] = owner
    # Return each validated import-root key and owner value in declaration insertion order.
    return parsed


def _parse_adapter_boundaries(
    table: Mapping[str, object],
    path: Path,
    roles: Mapping[str, tuple[PurePosixPath, ...]],
) -> tuple[PurePosixPath, ...]:
    """Parse the independently substitutable boundaries inside adapters.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order follows the declaration
    @param path declaring project file
    @param roles mapping from each canonical role key to ordered path values; mapping order follows
        declaration order
    @return adapter-boundary path elements in declaration order, possibly empty for v3 migration
    @throws DeclarationError when a boundary lies outside or overlaps another
    """
    # Read the optional raw boundary array without coercing its shape.
    raw = table.get("adapter_boundaries")
    # Absence preserves the explicit v3 migration alternative of no adapter partition.
    if raw is None:
        # Return the ordered empty boundary sequence.
        return ()
    # Parse each unique confined boundary path in declaration order.
    boundaries = _path_tuple(raw, field_name="adapter_boundaries", source=path)
    # Select adapter-role path elements in declaration order, or an empty sequence when absent.
    adapter_paths = roles.get("adapters", ())
    # Validate every declared boundary against adapter ownership and every sibling boundary.
    for boundary in boundaries:
        # A boundary must equal or descend from at least one adapter-role path.
        if not any(
            boundary == adapter or boundary.is_relative_to(adapter) for adapter in adapter_paths
        ):
            # Reject the exact boundary that lies outside adapter ownership.
            _reject(
                "DISC-PROJECT-013",
                path,
                f"adapter boundary {boundary} lies outside the adapters role",
            )
        # Preserve each other overlapping boundary in declaration order.
        overlaps = [
            other
            for other in boundaries
            if other != boundary
            and (boundary.is_relative_to(other) or other.is_relative_to(boundary))
        ]
        # Ancestor-related boundaries are not independently substitutable ownership units.
        if overlaps:
            # Reject the exact boundary with each conflicting path element.
            _reject(
                "DISC-PROJECT-013",
                path,
                f"adapter boundary {boundary} overlaps {', '.join(map(str, overlaps))}",
            )
    # Return unique non-overlapping boundary elements in authored declaration order.
    return boundaries


def _required_json_path(
    table: Mapping[str, object],
    path: Path,
    *,
    field_name: str,
    diagnostic_id: str,
    details: tuple[str, str],
) -> PurePosixPath:
    """Parse one required repository-local JSON artifact path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @param field_name exact declaration key whose value is parsed
    @param diagnostic_id stable refusal code for this artifact proposition
    @param details two message elements in missing-then-invalid order for actionable refusal
    @return validated repository-relative JSON path
    """
    # Unpack the two refusal-message elements in missing-then-invalid order.
    missing_detail, invalid_detail = details
    # Read the required raw artifact spelling without coercing its type.
    raw = table.get(field_name)
    # Absence fails the field-specific project proposition before path parsing.
    if raw is None:
        # Reject with the caller-authored actionable missing-field detail.
        _reject(diagnostic_id, path, missing_detail)
    # Parse and confine the artifact spelling inside the governed repository.
    artifact = _relative_path(raw, field_name=field_name, source=path)
    # Canonical project models and registries use JSON as their machine-readable form.
    if artifact.suffix != ".json":
        # Reject with the caller-authored field-specific artifact detail.
        _reject(diagnostic_id, path, invalid_detail)
    # Return the confined repository-relative JSON path.
    return artifact


def _parse_architecture(table: Mapping[str, object], path: Path) -> PurePosixPath:
    """Parse the canonical local architecture-model path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    # Parse the architecture field through the shared required-JSON artifact contract.
    return _required_json_path(
        table,
        path,
        field_name="architecture",
        diagnostic_id="DISC-PROJECT-014",
        details=(
            "architecture is required and must name the canonical local JSON model",
            "architecture must name the repository-local canonical JSON model",
        ),
    )


def _parse_contract_conformance(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the local contract-conformance registry path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    # Parse the conformance field through the shared required-JSON artifact contract.
    return _required_json_path(
        table,
        path,
        field_name="contract_conformance",
        diagnostic_id="DISC-PROJECT-015",
        details=(
            "contract_conformance is required and must name the local JSON registry",
            "contract_conformance must name a repository-local JSON registry",
        ),
    )


def _parse_capabilities(
    table: Mapping[str, object],
    path: Path,
) -> frozenset[Capability]:
    """Parse the complete closed capability table.

    Every fact is written as a boolean, including false facts. Absence is not
    treated as false because that would make a newly introduced capability a
    silent waiver in every existing repository.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order follows the declaration
    @param path declaring project file
    @return unordered capability set whose each element is explicitly enabled
    @throws DeclarationError when the table is absent, partial, extended, or non-boolean
    """
    # Read the required raw capability table without coercing its shape.
    raw = table.get("capabilities")
    # Capabilities must be represented by one complete TOML key/Boolean mapping.
    if not isinstance(raw, dict):
        # Reject absence, scalar, and array impostors at the owning table.
        _reject(
            "DISC-PROJECT-016",
            path,
            "capabilities must be a complete TOML table of explicit booleans",
        )
    # Build the unordered set whose each element is one required capability field name.
    expected = {item.value for item in CAPABILITIES}
    # Build the unordered set whose each element is a required field absent from the table.
    missing = expected - set(raw)
    # Build the unordered set whose each element is an unrecognized table key.
    unknown = set(raw) - expected
    # Missing fields silently waive obligations and unknown fields might be misspellings.
    if missing or unknown:
        # Reject with independently sorted missing and unknown element sequences.
        _reject(
            "DISC-PROJECT-016",
            path,
            f"capabilities missing={sorted(missing)}, unknown={sorted(unknown)}",
        )
    # Preserve each non-Boolean field name in lexical order for deterministic diagnostics.
    invalid = sorted(name for name, value in raw.items() if not isinstance(value, bool))
    # Every explicit fact must be exactly true or false rather than a truthy scalar.
    if invalid:
        # Reject with each invalid field-name element in lexical order.
        _reject(
            "DISC-PROJECT-017",
            path,
            f"capabilities must be booleans: {', '.join(invalid)}",
        )
    # Return an unordered set containing exactly each capability whose explicit value is true.
    return frozenset(item for item in CAPABILITIES if raw[item.value] is True)


def _parse_operational_model(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the canonical repository-local operational model path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    # Parse the operational field through the shared required-JSON artifact contract.
    return _required_json_path(
        table,
        path,
        field_name="operational_model",
        diagnostic_id="DISC-PROJECT-018",
        details=(
            "operational_model is required and must name the local JSON model",
            "operational_model must name a repository-local JSON model",
        ),
    )


def _parse_security_model(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the canonical repository-local security model path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    # Parse the security field through the shared required-JSON artifact contract.
    return _required_json_path(
        table,
        path,
        field_name="security_model",
        diagnostic_id="DISC-PROJECT-019",
        details=(
            "security_model is required and must name the local JSON model",
            "security_model must name a repository-local JSON model",
        ),
    )


def _parse_adversarial_review(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the repository-local structured review path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    # Parse the review field through the shared required-JSON artifact contract.
    return _required_json_path(
        table,
        path,
        field_name="adversarial_review",
        diagnostic_id="DISC-PROJECT-020",
        details=(
            "adversarial_review is required and must name the local JSON artifact",
            "adversarial_review must name a repository-local JSON artifact",
        ),
    )


def _parse_documentation_model(table: Mapping[str, object], path: Path) -> PurePosixPath:
    """Parse the repository-local documentation-model path.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    # Parse the documentation field through the shared required-JSON artifact contract.
    return _required_json_path(
        table,
        path,
        field_name="documentation_model",
        diagnostic_id="DISC-PROJECT-022",
        details=(
            (
                "documentation_model is required; add "
                'documentation_model = "documentation-model.json" and copy the v5 template'
            ),
            "documentation_model must name a repository-local JSON artifact",
        ),
    )


def _parse_doc_engine(table: Mapping[str, object], path: Path) -> str:
    """Parse one explicit documentation syntax selection.

    @param table mapping whose each key names a discipline field and each value is decoded TOML;
        mapping iteration order is deliberately unused
    @param path declaring project file
    @return doxygen
    """
    # Read the required engine spelling without accepting an implicit fallback.
    raw = table.get("doc_engine")
    # Absence would silently deactivate structured documentation checks.
    if raw is None:
        # Reject at the exact project field with the one accepted engine spelling.
        _reject(
            "DISC-PROJECT-007",
            path,
            "doc_engine is required and must be doxygen",
        )
    # Normalize the decoded scalar to text for closed-vocabulary comparison.
    engine = str(raw)
    # Retired v4 engines receive specific migration guidance rather than an unknown-value error.
    if engine in LEGACY_DOC_ENGINES:
        # Reject with the structural v5 migration steps needed before source authoring.
        _reject(
            "DISC-PROJECT-021",
            path,
            f"doc_engine {engine!r} was valid before v5; replace it with 'doxygen', "
            "add documentation_model, and migrate entity comments before rerunning the gate",
        )
    # Any spelling outside the sole v5 engine set is unknown to this package.
    if engine not in DOC_ENGINES:
        # Reject with the closed accepted vocabulary.
        _reject(
            "DISC-PROJECT-007",
            path,
            f"doc_engine {engine!r} is unknown; v5 accepts only 'doxygen'",
        )
    # Return the validated sole engine spelling.
    return engine


def parse(path: Path) -> Declaration:
    """Read one v5 declaration, refusing missing and unknown values.

    @param path project file to read
    @return the validated declaration
    @throws ValueError when its unit, paths, roles, or documentation engine are invalid
    @par Effects Reads the project file without modifying repository state.
    """
    # Decode the exact UTF-8 project text to a TOML key/value mapping in source order.
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    # Select the discipline field/value mapping, defaulting absent nested tables to empty mappings.
    table = data.get("tool", {}).get(TABLE, {})
    # The discipline declaration must be a TOML table before field parsing begins.
    if not isinstance(table, dict):
        # Reject scalar or array impostors at the exact table path.
        _reject(
            "DISC-PROJECT-001",
            path,
            f"[tool.{TABLE}] must be a TOML table",
        )

    # Read the required governed repository-unit spelling without coercion.
    raw_unit = table.get("unit")
    # Absence leaves application-versus-component scope undecidable.
    if raw_unit is None:
        # Reject with the closed two-alternative unit vocabulary.
        _reject(
            "DISC-PROJECT-001",
            path,
            "unit is required (application or component)",
        )
    # Convert the declared unit spelling to the closed repository-shape enumeration.
    try:
        # Hold the validated application or independently developed component alternative.
        unit = UnitKind(raw_unit)
    # Translate an unknown spelling into the stable unit diagnostic.
    except ValueError:
        # Reject without guessing the intended repository scope.
        _reject(
            "DISC-PROJECT-002",
            path,
            f"unit {raw_unit!r} is not application or component",
        )

    # Parse each production-root path element in declaration order.
    roots = _path_tuple(table.get("source_roots"), field_name="source_roots", source=path)
    # Parse the confined canonical architecture-model artifact.
    architecture = _parse_architecture(table, path)
    # Parse the confined contract-conformance registry artifact.
    contract_conformance = _parse_contract_conformance(table, path)
    # Parse the complete capability table to an unordered enabled-fact set.
    capabilities = _parse_capabilities(table, path)
    # Parse the sole explicit v5 structured documentation engine.
    engine = _parse_doc_engine(table, path)

    # Read the optional pedagogical projection flag, defaulting absent to the false alternative.
    projection = table.get("pedagogical_full_projection", False)
    # The projection state must be exactly true or false.
    if not isinstance(projection, bool):
        # Reject truthy scalar impostors at the exact declaration field.
        _reject(
            "DISC-PROJECT-008",
            path,
            "pedagogical_full_projection must be true or false",
        )

    # Map each legacy segment key to its internal layer value in declaration insertion order.
    layers: dict[str, str] = {}
    # Select the optional legacy layers table, defaulting absence to an empty mapping.
    raw_layers = table.get("layers") or {}
    # Legacy layer aliases must be represented by a TOML table.
    if not isinstance(raw_layers, dict):
        # Reject a scalar or array impostor at the exact declaration field.
        _reject("DISC-PROJECT-005", path, "layers must be a TOML table")
    # Validate every segment-key/layer-value pair in TOML insertion order.
    for segment, target in raw_layers.items():
        # Alias targets must belong to the closed legacy internal layer vocabulary.
        if target not in CANONICAL_LAYERS:
            # Join each known layer-name element in canonical presentation order.
            known = ", ".join(CANONICAL_LAYERS)
            # Reject the exact alias pair with the closed vocabulary.
            _reject(
                "DISC-PROJECT-005",
                path,
                f"layer {segment!r} maps to {target!r}, which is not one of {known}",
            )
        # Publish the normalized textual alias key and value after validation.
        layers[str(segment)] = str(target)

    # Parse explicit role ownership against ordered production-root elements.
    roles = _parse_roles(table, path, roots)
    # Parse independently substitutable adapter boundaries against role ownership.
    boundaries = _parse_adapter_boundaries(table, path, roles)
    # Construct the complete immutable declaration after every independent field validates.
    return Declaration(
        unit=unit,
        source_roots=roots,
        architecture=architecture,
        contract_conformance=contract_conformance,
        operational_model=_parse_operational_model(table, path),
        security_model=_parse_security_model(table, path),
        adversarial_review=_parse_adversarial_review(table, path),
        documentation_model=_parse_documentation_model(table, path),
        capabilities=capabilities,
        role_paths=roles,
        adapter_boundaries=boundaries,
        layers=layers,
        foreign_ownership=_parse_foreign_ownership(
            table,
            path,
            roots,
            roles,
            boundaries,
        ),
        doc_engine=engine,
        doc_engine_declared=True,
        pedagogical_full_projection=projection,
        source=path.resolve(),
    )


def load(start: Path, explicit: Path | None = None) -> Declaration:
    """Load the declaration without crossing the nearest repository boundary.

    @param start path inside the governed repository
    @param explicit optional project file; it must equal the nearest project file
    @return the declaration, or ``DEFAULT`` when the nearest project has none
    @throws ValueError when an explicit path points outside the governed repository
    @par Effects Resolves and reads local project files without modifying them.
    """
    # Locate the nearest repository-defining project artifact for confinement comparison.
    nearest = find_project_file(start)
    # An explicit project path must equal that exact nearest boundary.
    if explicit is not None:
        # Resolve the caller-supplied project path before comparing identities.
        chosen = explicit.resolve()
        # Missing nearest project or unequal identity would cross a repository boundary.
        if nearest is None or chosen != nearest.resolve():
            # Reject at the explicit artifact with the resolved starting subject.
            _reject(
                "DISC-PROJECT-009",
                chosen,
                f"not the nearest pyproject.toml for {start.resolve()}",
            )
        # Parse the exact confined explicit project after identity validation.
        return parse(chosen)
    # Discover a discipline declaration only at the nearest project boundary.
    found = find_declaration(start)
    # Parse the found declaration, or return the conspicuous direct-check fallback alternative.
    return parse(found) if found is not None else DEFAULT
