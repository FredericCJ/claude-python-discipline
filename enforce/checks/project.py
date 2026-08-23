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

    def __init__(self, diagnostic_id: str, source: Path, detail: str) -> None:
        """Build a declaration failure without baking formatting into call sites.

        @param diagnostic_id durable code identifying the rejected proposition
        @param source project file carrying the invalid value
        @param detail human-readable explanation and remediation clue
        """
        super().__init__(f"{diagnostic_id} {source}: {detail}")
        self.diagnostic_id = diagnostic_id
        self.source = source


def _reject(diagnostic_id: str, source: Path, detail: str) -> Never:
    """Raise one declaration diagnostic without duplicating exception mechanics.

    @param diagnostic_id durable code identifying the rejected proposition
    @param source project file carrying the invalid value
    @param detail human-readable explanation and remediation clue
    @return never; this helper always raises
    @throws DeclarationError unconditionally
    """
    raise DeclarationError(diagnostic_id, source, detail)


## Executable roles retain ``app`` internally for compatibility with the AST
## checks written before v4. The declaration spells the role ``application``;
## users should not have to learn an implementation abbreviation.
ROLE_TO_LAYER: Final[dict[str, str]] = {
    "domain": "domain",
    "application": "app",
    "ports": "ports",
    "adapters": "adapters",
    "shell": "shell",
}
## Public declaration role names, in stable presentation order.
CANONICAL_ROLES: Final[tuple[str, ...]] = tuple(ROLE_TO_LAYER)
## Legacy internal layer values consumed by v3 AST checks.
CANONICAL_LAYERS: Final[tuple[str, ...]] = tuple(ROLE_TO_LAYER.values())
## The sole structured documentation engine supported by v5.
DOC_ENGINES: Final[frozenset[str]] = frozenset({"doxygen"})
LEGACY_DOC_ENGINES: Final[frozenset[str]] = frozenset({"sphinx", "none"})
## TOML table name beneath ``tool``.
TABLE: Final = "agent-discipline"
## One top-level Python import identifier, excluding dotted module paths.
IMPORT_ROOT: Final = re.compile(r"^[A-Za-z_]\w*$")
## Closed capability vocabulary in canonical rendering order.
CAPABILITIES: Final[tuple[Capability, ...]] = tuple(Capability)


def _relative_path(raw: object, *, field_name: str, source: Path) -> PurePosixPath:
    """Validate and normalize one repository-relative declaration path.

    @param raw value read from TOML
    @param field_name declaration field used in a diagnostic
    @param source project file that owns the value
    @return a normalized POSIX path
    @throws ValueError when the path could escape or identify the repository root
    """
    if not isinstance(raw, str) or not raw.strip():
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} entries must be non-empty strings",
        )
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if candidate.is_absolute() or PureWindowsPath(raw).drive or ".." in candidate.parts:
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} path {raw!r} must stay inside the repository",
        )
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    if not parts:
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} may not name the repository root",
        )
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
    @return paths in declaration order
    @throws ValueError when the value is not a valid non-empty path array
    """
    if not isinstance(raw, list) or not raw:
        _reject(
            "DISC-PROJECT-003",
            source,
            f"{field_name} must be a non-empty array of source paths",
        )
    paths = tuple(_relative_path(value, field_name=field_name, source=source) for value in raw)
    if len(set(paths)) != len(paths):
        _reject(
            "DISC-PROJECT-004",
            source,
            f"{field_name} contains a duplicate path",
        )
    return paths


@dataclass(frozen=True, slots=True)
class Declaration:
    """What one repository says about its governed unit and local conventions."""

    ## None exists only for the conspicuous undeclared fallback used by direct
    ## check invocations. The canonical project gate refuses that fallback.
    unit: UnitKind | None = None
    ## Production roots relative to ``source.parent``.
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
    ## Explicit facts that add operational and security obligations.
    capabilities: frozenset[Capability] = frozenset()
    ## Canonical role name to repository-relative directory paths.
    role_paths: Mapping[str, tuple[PurePosixPath, ...]] = field(default_factory=dict)
    ## Independently substitutable boundaries inside the broader adapters role.
    adapter_boundaries: tuple[PurePosixPath, ...] = ()
    ## Legacy v3 segment aliases, retained only for migration and direct fixtures.
    layers: Mapping[str, str] = field(default_factory=dict)
    ## Import root to its one repository-relative owning adapter boundary.
    foreign_ownership: Mapping[str, PurePosixPath] = field(default_factory=dict)
    ## Documentation comment syntax selected by the repository.
    doc_engine: str = "none"
    ## Whether the repository explicitly selected that syntax rather than using fallback.
    doc_engine_declared: bool = False
    ## Whether this repository deliberately projects every teaching artifact.
    pedagogical_full_projection: bool = False
    ## The project file this declaration was parsed from.
    source: Path | None = None

    @property
    def root(self) -> Path | None:
        """The governed repository root, when a declaration was loaded.

        @return the directory containing the declaring ``pyproject.toml``
        """
        return None if self.source is None else self.source.parent

    def canonical(self, segment: str) -> str | None:
        """The legacy canonical layer named by one path segment, if any.

        @param segment one path segment
        @return the canonical layer, or None when it is not a v3 layer alias
        """
        if segment in self.layers:
            return self.layers[segment]
        if segment in CANONICAL_LAYERS:
            return segment
        return None

    def role_of(self, path: Path) -> str | None:
        """Resolve a source path against the explicit v4 role paths.

        Explicit role paths replace segment guessing. When no v4 role table is
        present, the v3 segment vocabulary remains available solely to migration
        and direct legacy checks.

        @param path source file or directory to classify
        @return the check-layer name, or None when no role owns the path
        """
        if self.role_paths and self.root is not None:
            try:
                relative = path.resolve().relative_to(self.root.resolve())
            except ValueError:
                return None
            candidate = PurePosixPath(relative.as_posix())
            matches = [
                ROLE_TO_LAYER[role]
                for role, prefixes in self.role_paths.items()
                for prefix in prefixes
                if candidate == prefix or candidate.is_relative_to(prefix)
            ]
            return matches[0] if len(matches) == 1 else None
        for part in path.parts:
            canonical = self.canonical(part)
            if canonical is not None:
                return canonical
        if path.suffix:
            return self.canonical(path.stem)
        return None

    def source_paths(self) -> tuple[Path, ...]:
        """The declared production roots as absolute local paths.

        @return resolved paths, or an empty tuple for the undeclared fallback
        """
        if self.root is None:
            return ()
        return tuple(self.root / Path(root.as_posix()) for root in self.source_roots)

    def architecture_path(self) -> Path | None:
        """The declared local architecture record as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        if self.root is None or self.architecture is None:
            return None
        return self.root / Path(self.architecture.as_posix())

    def contract_conformance_path(self) -> Path | None:
        """The declared conformance registry as an absolute local path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        if self.root is None or self.contract_conformance is None:
            return None
        return self.root / Path(self.contract_conformance.as_posix())

    def operational_model_path(self) -> Path | None:
        """The declared local operational model as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        if self.root is None or self.operational_model is None:
            return None
        return self.root / Path(self.operational_model.as_posix())

    def security_model_path(self) -> Path | None:
        """The declared local security model as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        if self.root is None or self.security_model is None:
            return None
        return self.root / Path(self.security_model.as_posix())

    def adversarial_review_path(self) -> Path | None:
        """The declared adversarial review artifact as an absolute path.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        if self.root is None or self.adversarial_review is None:
            return None
        return self.root / Path(self.adversarial_review.as_posix())

    def documentation_model_path(self) -> Path | None:
        """Resolve the project-owned documentation model.

        @return local JSON path, or None for the undeclared direct-check fallback
        """
        if self.root is None or self.documentation_model is None:
            return None
        return self.root / Path(self.documentation_model.as_posix())

    def has(self, capability: Capability) -> bool:
        """Whether one additive project capability is active.

        @param capability fact whose obligations are being selected
        @return true only when the manifest explicitly enables it
        """
        return capability in self.capabilities

    def _documentation_notes(self) -> tuple[str, ...]:
        """Visible consequences of the engine declaration in force.

        @return undeclared and engine-specific narrowing notes
        """
        notes: list[str] = []
        if not self.doc_engine_declared:
            notes.append(
                "DISC-PROJECT-007 doc_engine is undeclared; direct checks use 'none', "
                "but a v5 project gate must refuse this repository"
            )
        if self.doc_engine != "doxygen":
            notes.append(
                f"DISC-PROJECT-021 doc_engine is {self.doc_engine!r}; v5 requires "
                "'doxygen'. Run the v5 migration to replace the former sphinx/none choice."
            )
        return tuple(notes)

    def narrowed(self) -> tuple[str, ...]:
        """Facts a direct check invocation could not decide from this declaration.

        @return one visible note per missing or deliberately narrowed declaration
        """
        notes: list[str] = []
        if self.unit is None:
            notes.append(
                "DISC-PROJECT-001 unit is undeclared; a v4 project gate must refuse this repository"
            )
        if not self.source_roots:
            notes.append(
                "DISC-PROJECT-003 source_roots are undeclared; source-role coverage is undecided"
            )
        if self.architecture is None:
            notes.append(
                "DISC-PROJECT-014 architecture is undeclared; local design views are undecided"
            )
        if self.contract_conformance is None:
            notes.append(
                "DISC-PROJECT-015 contract_conformance is undeclared; typed "
                "implementation and shared-suite evidence are undecided"
            )
        if self.operational_model is None:
            notes.append(
                "DISC-PROJECT-018 operational_model is undeclared; lifecycle, "
                "budgets, outcomes, identity, and platform support are undecided"
            )
        if self.security_model is None:
            notes.append(
                "DISC-PROJECT-019 security_model is undeclared; trust boundaries "
                "and data classification are undecided"
            )
        if self.adversarial_review is None:
            notes.append(
                "DISC-PROJECT-020 adversarial_review is undeclared; semantic review "
                "scope, freshness, objections, and closure are undecided"
            )
        if self.documentation_model is None:
            notes.append(
                "DISC-PROJECT-022 documentation_model is undeclared; governed "
                "documentation scopes and project vocabulary are undecided"
            )
        if self.source is None:
            notes.append(
                "DISC-PROJECT-016 capabilities are undeclared; additive local "
                "operational obligations are undecided"
            )
        notes.extend(self._documentation_notes())
        return tuple(notes)


## Conspicuously incomplete fallback used only by direct legacy check calls.
DEFAULT: Final = Declaration()


def find_project_file(start: Path) -> Path | None:
    """Find the nearest repository-defining ``pyproject.toml``.

    @param start file or directory inside the repository
    @return the nearest project file, or None when no ancestor has one
    """
    here = start.resolve()
    if here.is_file():
        here = here.parent
    for directory in (here, *here.parents):
        candidate = directory / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def find_declaration(start: Path) -> Path | None:
    """Return the nearest project file only when it carries the discipline table.

    The search deliberately stops at the first project file. Skipping it and
    reading an ancestor would make a component inherit its parent repository's
    unit, paths, and verdict.

    @param start file or directory inside the repository
    @return its project file, or None when that file has no declaration
    """
    candidate = find_project_file(start)
    if candidate is None:
        return None
    try:
        data = tomllib.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    return candidate if TABLE in data.get("tool", {}) else None


def _parse_roles(
    table: Mapping[str, object],
    path: Path,
    roots: tuple[PurePosixPath, ...],
) -> dict[str, tuple[PurePosixPath, ...]]:
    """Parse role paths and reject unknown, overlapping, or out-of-root entries.

    @param table the ``tool.agent-discipline`` table
    @param path declaring project file
    @param roots declared production roots
    @return canonical role paths
    @throws ValueError when paths do not form an unambiguous local partition
    """
    raw_roles = table.get("roles") or {}
    if not isinstance(raw_roles, dict):
        _reject("DISC-PROJECT-005", path, "roles must be a TOML table")
    unknown = set(raw_roles) - set(CANONICAL_ROLES)
    if unknown:
        _reject(
            "DISC-PROJECT-005",
            path,
            f"unknown roles {', '.join(sorted(unknown))}; expected {', '.join(CANONICAL_ROLES)}",
        )
    parsed = {
        role: _path_tuple(raw, field_name=f"roles.{role}", source=path)
        for role, raw in raw_roles.items()
    }
    owners: list[tuple[str, PurePosixPath]] = [
        (role, role_path) for role, paths in parsed.items() for role_path in paths
    ]
    for role, role_path in owners:
        if not any(role_path == root or role_path.is_relative_to(root) for root in roots):
            _reject(
                "DISC-PROJECT-006",
                path,
                f"roles.{role} path {role_path} lies outside source_roots",
            )
        conflicts = [
            f"{other}:{other_path}"
            for other, other_path in owners
            if (other, other_path) != (role, role_path)
            and (role_path.is_relative_to(other_path) or other_path.is_relative_to(role_path))
        ]
        if conflicts:
            _reject(
                "DISC-PROJECT-006",
                path,
                f"roles.{role} path {role_path} overlaps {', '.join(conflicts)}",
            )
    return parsed


def _parse_foreign_ownership(
    table: Mapping[str, object],
    path: Path,
    roots: tuple[PurePosixPath, ...],
    roles: Mapping[str, tuple[PurePosixPath, ...]],
    boundaries: tuple[PurePosixPath, ...],
) -> dict[str, PurePosixPath]:
    """Parse direct foreign-import ownership records.

    @param table the ``tool.agent-discipline`` table
    @param path declaring project file
    @param roots declared production roots
    @param roles validated role paths
    @param boundaries declared independently substitutable adapter boundaries
    @return import root to its single owning adapter path
    @throws DeclarationError when an import or owner is ambiguous or misplaced
    """
    raw_records = table.get("foreign_dependencies") or []
    if not isinstance(raw_records, list):
        _reject(
            "DISC-PROJECT-010",
            path,
            "foreign_dependencies must be an array of TOML tables",
        )
    parsed: dict[str, PurePosixPath] = {}
    adapter_paths = roles.get("adapters", ())
    for index, raw_record in enumerate(raw_records):
        if not isinstance(raw_record, dict):
            _reject(
                "DISC-PROJECT-010",
                path,
                f"foreign_dependencies[{index}] must be a TOML table",
            )
        unknown = set(raw_record) - {"import_name", "owner"}
        if unknown:
            _reject(
                "DISC-PROJECT-010",
                path,
                f"foreign_dependencies[{index}] has unknown fields {', '.join(sorted(unknown))}",
            )
        import_name = raw_record.get("import_name")
        if not isinstance(import_name, str) or IMPORT_ROOT.fullmatch(import_name) is None:
            _reject(
                "DISC-PROJECT-011",
                path,
                f"foreign_dependencies[{index}].import_name must be one Python import root",
            )
        if import_name in parsed:
            _reject(
                "DISC-PROJECT-011",
                path,
                f"foreign import {import_name!r} has more than one owner",
            )
        owner = _relative_path(
            raw_record.get("owner"),
            field_name=f"foreign_dependencies[{index}].owner",
            source=path,
        )
        if not any(owner == adapter or owner.is_relative_to(adapter) for adapter in adapter_paths):
            _reject(
                "DISC-PROJECT-012",
                path,
                f"owner {owner} for {import_name!r} is not inside a declared adapter role",
            )
        if boundaries and not any(
            owner == boundary or owner.is_relative_to(boundary) for boundary in boundaries
        ):
            _reject(
                "DISC-PROJECT-012",
                path,
                f"owner {owner} for {import_name!r} is not inside a declared adapter boundary",
            )
        if not any(owner == root or owner.is_relative_to(root) for root in roots):
            _reject(
                "DISC-PROJECT-012",
                path,
                f"owner {owner} for {import_name!r} lies outside source_roots",
            )
        parsed[import_name] = owner
    return parsed


def _parse_adapter_boundaries(
    table: Mapping[str, object],
    path: Path,
    roles: Mapping[str, tuple[PurePosixPath, ...]],
) -> tuple[PurePosixPath, ...]:
    """Parse the independently substitutable boundaries inside adapters.

    @param table the ``tool.agent-discipline`` table
    @param path declaring project file
    @param roles validated role paths
    @return declared adapter boundary paths, possibly empty for v3 migration
    @throws DeclarationError when a boundary lies outside or overlaps another
    """
    raw = table.get("adapter_boundaries")
    if raw is None:
        return ()
    boundaries = _path_tuple(raw, field_name="adapter_boundaries", source=path)
    adapter_paths = roles.get("adapters", ())
    for boundary in boundaries:
        if not any(
            boundary == adapter or boundary.is_relative_to(adapter) for adapter in adapter_paths
        ):
            _reject(
                "DISC-PROJECT-013",
                path,
                f"adapter boundary {boundary} lies outside the adapters role",
            )
        overlaps = [
            other
            for other in boundaries
            if other != boundary
            and (boundary.is_relative_to(other) or other.is_relative_to(boundary))
        ]
        if overlaps:
            _reject(
                "DISC-PROJECT-013",
                path,
                f"adapter boundary {boundary} overlaps {', '.join(map(str, overlaps))}",
            )
    return boundaries


def _parse_architecture(table: Mapping[str, object], path: Path) -> PurePosixPath:
    """Parse the canonical local architecture-model path.

    @param table the ``tool.agent-discipline`` table
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    raw = table.get("architecture")
    if raw is None:
        _reject(
            "DISC-PROJECT-014",
            path,
            "architecture is required and must name the canonical local JSON model",
        )
    architecture = _relative_path(raw, field_name="architecture", source=path)
    if architecture.suffix != ".json":
        _reject(
            "DISC-PROJECT-014",
            path,
            "architecture must name the repository-local canonical JSON model",
        )
    return architecture


def _parse_contract_conformance(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the local contract-conformance registry path.

    @param table the ``tool.agent-discipline`` table
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    raw = table.get("contract_conformance")
    if raw is None:
        _reject(
            "DISC-PROJECT-015",
            path,
            "contract_conformance is required and must name the local JSON registry",
        )
    conformance = _relative_path(
        raw,
        field_name="contract_conformance",
        source=path,
    )
    if conformance.suffix != ".json":
        _reject(
            "DISC-PROJECT-015",
            path,
            "contract_conformance must name a repository-local JSON registry",
        )
    return conformance


def _parse_capabilities(
    table: Mapping[str, object],
    path: Path,
) -> frozenset[Capability]:
    """Parse the complete closed capability table.

    Every fact is written as a boolean, including false facts. Absence is not
    treated as false because that would make a newly introduced capability a
    silent waiver in every existing repository.

    @param table decoded discipline declaration
    @param path declaring project file
    @return enabled capability facts
    @throws DeclarationError when the table is absent, partial, extended, or non-boolean
    """
    raw = table.get("capabilities")
    if not isinstance(raw, dict):
        _reject(
            "DISC-PROJECT-016",
            path,
            "capabilities must be a complete TOML table of explicit booleans",
        )
    expected = {item.value for item in CAPABILITIES}
    missing = expected - set(raw)
    unknown = set(raw) - expected
    if missing or unknown:
        _reject(
            "DISC-PROJECT-016",
            path,
            f"capabilities missing={sorted(missing)}, unknown={sorted(unknown)}",
        )
    invalid = sorted(name for name, value in raw.items() if not isinstance(value, bool))
    if invalid:
        _reject(
            "DISC-PROJECT-017",
            path,
            f"capabilities must be booleans: {', '.join(invalid)}",
        )
    return frozenset(item for item in CAPABILITIES if raw[item.value] is True)


def _parse_operational_model(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the canonical repository-local operational model path.

    @param table decoded discipline declaration
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    raw = table.get("operational_model")
    if raw is None:
        _reject(
            "DISC-PROJECT-018",
            path,
            "operational_model is required and must name the local JSON model",
        )
    model = _relative_path(raw, field_name="operational_model", source=path)
    if model.suffix != ".json":
        _reject(
            "DISC-PROJECT-018",
            path,
            "operational_model must name a repository-local JSON model",
        )
    return model


def _parse_security_model(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the canonical repository-local security model path.

    @param table decoded discipline declaration
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    raw = table.get("security_model")
    if raw is None:
        _reject(
            "DISC-PROJECT-019",
            path,
            "security_model is required and must name the local JSON model",
        )
    model = _relative_path(raw, field_name="security_model", source=path)
    if model.suffix != ".json":
        _reject(
            "DISC-PROJECT-019",
            path,
            "security_model must name a repository-local JSON model",
        )
    return model


def _parse_adversarial_review(
    table: Mapping[str, object],
    path: Path,
) -> PurePosixPath:
    """Parse the repository-local structured review path.

    @param table decoded discipline declaration
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    raw = table.get("adversarial_review")
    if raw is None:
        _reject(
            "DISC-PROJECT-020",
            path,
            "adversarial_review is required and must name the local JSON artifact",
        )
    review = _relative_path(raw, field_name="adversarial_review", source=path)
    if review.suffix != ".json":
        _reject(
            "DISC-PROJECT-020",
            path,
            "adversarial_review must name a repository-local JSON artifact",
        )
    return review


def _parse_documentation_model(table: Mapping[str, object], path: Path) -> PurePosixPath:
    """Parse the repository-local documentation-model path.

    @param table decoded discipline declaration
    @param path declaring project file
    @return validated repository-relative JSON path
    """
    raw = table.get("documentation_model")
    if raw is None:
        _reject(
            "DISC-PROJECT-022",
            path,
            "documentation_model is required; add "
            'documentation_model = "documentation-model.json" and copy the v5 template',
        )
    model = _relative_path(raw, field_name="documentation_model", source=path)
    if model.suffix != ".json":
        _reject(
            "DISC-PROJECT-022",
            path,
            "documentation_model must name a repository-local JSON artifact",
        )
    return model


def _parse_doc_engine(table: Mapping[str, object], path: Path) -> str:
    """Parse one explicit documentation syntax selection.

    @param table decoded discipline declaration
    @param path declaring project file
    @return doxygen
    """
    raw = table.get("doc_engine")
    if raw is None:
        _reject(
            "DISC-PROJECT-007",
            path,
            "doc_engine is required and must be doxygen",
        )
    engine = str(raw)
    if engine in LEGACY_DOC_ENGINES:
        _reject(
            "DISC-PROJECT-021",
            path,
            f"doc_engine {engine!r} was valid before v5; replace it with 'doxygen', "
            "add documentation_model, and migrate entity comments before rerunning the gate",
        )
    if engine not in DOC_ENGINES:
        _reject(
            "DISC-PROJECT-007",
            path,
            f"doc_engine {engine!r} is unknown; v5 accepts only 'doxygen'",
        )
    return engine


def parse(path: Path) -> Declaration:
    """Read one v4 declaration, refusing missing and unknown values.

    @param path project file to read
    @return the validated declaration
    @throws ValueError when its unit, paths, roles, or documentation engine are invalid
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get(TABLE, {})
    if not isinstance(table, dict):
        _reject(
            "DISC-PROJECT-001",
            path,
            f"[tool.{TABLE}] must be a TOML table",
        )

    raw_unit = table.get("unit")
    if raw_unit is None:
        _reject(
            "DISC-PROJECT-001",
            path,
            "unit is required (application or component)",
        )
    try:
        unit = UnitKind(raw_unit)
    except ValueError:
        _reject(
            "DISC-PROJECT-002",
            path,
            f"unit {raw_unit!r} is not application or component",
        )

    roots = _path_tuple(table.get("source_roots"), field_name="source_roots", source=path)
    architecture = _parse_architecture(table, path)
    contract_conformance = _parse_contract_conformance(table, path)
    capabilities = _parse_capabilities(table, path)
    engine = _parse_doc_engine(table, path)

    projection = table.get("pedagogical_full_projection", False)
    if not isinstance(projection, bool):
        _reject(
            "DISC-PROJECT-008",
            path,
            "pedagogical_full_projection must be true or false",
        )

    layers: dict[str, str] = {}
    raw_layers = table.get("layers") or {}
    if not isinstance(raw_layers, dict):
        _reject("DISC-PROJECT-005", path, "layers must be a TOML table")
    for segment, target in raw_layers.items():
        if target not in CANONICAL_LAYERS:
            known = ", ".join(CANONICAL_LAYERS)
            _reject(
                "DISC-PROJECT-005",
                path,
                f"layer {segment!r} maps to {target!r}, which is not one of {known}",
            )
        layers[str(segment)] = str(target)

    roles = _parse_roles(table, path, roots)
    boundaries = _parse_adapter_boundaries(table, path, roles)
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
    """
    nearest = find_project_file(start)
    if explicit is not None:
        chosen = explicit.resolve()
        if nearest is None or chosen != nearest.resolve():
            _reject(
                "DISC-PROJECT-009",
                chosen,
                f"not the nearest pyproject.toml for {start.resolve()}",
            )
        return parse(chosen)
    found = find_declaration(start)
    return parse(found) if found is not None else DEFAULT
