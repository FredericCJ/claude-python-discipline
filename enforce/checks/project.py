"""The bounded declaration every v4 project check consumes.

The declaration describes one governed repository, not a collection of
switches. It names whether that repository delivers an application or one
component, where its production Python lives, how those paths map to the five
hexagonal roles, and which documentation syntax it deliberately uses.

    [tool.agent-discipline]
    unit = "component"             # application | component
    source_roots = ["src"]
    doc_engine = "doxygen"         # doxygen | sphinx | none

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

import tomllib
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never

if TYPE_CHECKING:
    from collections.abc import Mapping


class UnitKind(StrEnum):
    """The two repository shapes governed by the discipline."""

    APPLICATION = "application"
    COMPONENT = "component"


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
CANONICAL_ROLES: Final[tuple[str, ...]] = tuple(ROLE_TO_LAYER)
CANONICAL_LAYERS: Final[tuple[str, ...]] = tuple(ROLE_TO_LAYER.values())
DOC_ENGINES: Final[frozenset[str]] = frozenset({"doxygen", "sphinx", "none"})
TABLE: Final = "agent-discipline"


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
            "DISC-PROJECT-004", source,
            f"{field_name} entries must be non-empty strings",
        )
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if (
        candidate.is_absolute()
        or PureWindowsPath(raw).drive
        or ".." in candidate.parts
    ):
        _reject(
            "DISC-PROJECT-004", source,
            f"{field_name} path {raw!r} must stay inside the repository",
        )
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    if not parts:
        _reject(
            "DISC-PROJECT-004", source,
            f"{field_name} may not name the repository root",
        )
    return PurePosixPath(*parts)


def _path_tuple(
    raw: object, *, field_name: str, source: Path,
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
            "DISC-PROJECT-003", source,
            f"{field_name} must be a non-empty array of source paths",
        )
    paths = tuple(
        _relative_path(value, field_name=field_name, source=source) for value in raw
    )
    if len(set(paths)) != len(paths):
        _reject(
            "DISC-PROJECT-004", source,
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
    ## Canonical role name to repository-relative directory paths.
    role_paths: Mapping[str, tuple[PurePosixPath, ...]] = field(default_factory=dict)
    ## Legacy v3 segment aliases, retained only for migration and direct fixtures.
    layers: Mapping[str, str] = field(default_factory=dict)
    doc_engine: str = "none"
    pedagogical_full_projection: bool = False
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

    def narrowed(self) -> tuple[str, ...]:
        """Facts a direct check invocation could not decide from this declaration.

        @return one visible note per missing or deliberately narrowed declaration
        """
        notes: list[str] = []
        if self.unit is None:
            notes.append(
                "DISC-PROJECT-001 unit is undeclared; a v4 project gate must "
                "refuse this repository"
            )
        if not self.source_roots:
            notes.append(
                "DISC-PROJECT-003 source_roots are undeclared; source-role "
                "coverage is undecided"
            )
        if self.doc_engine != "doxygen":
            notes.append(
                f"DOC-002 and DOC-007 are inactive: doc_engine is {self.doc_engine!r}, "
                "so the @param and ## forms are not required. DOC-001 and DOC-003 "
                "still require every required contract element to be documented."
            )
        return tuple(notes)


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
            "DISC-PROJECT-005", path,
            f"unknown roles {', '.join(sorted(unknown))}; "
            f"expected {', '.join(CANONICAL_ROLES)}",
        )
    parsed = {
        role: _path_tuple(raw, field_name=f"roles.{role}", source=path)
        for role, raw in raw_roles.items()
    }
    owners: list[tuple[str, PurePosixPath]] = [
        (role, role_path) for role, paths in parsed.items() for role_path in paths
    ]
    for role, role_path in owners:
        if not any(
            role_path == root or role_path.is_relative_to(root) for root in roots
        ):
            _reject(
                "DISC-PROJECT-006", path,
                f"roles.{role} path {role_path} lies outside source_roots",
            )
        conflicts = [
            f"{other}:{other_path}"
            for other, other_path in owners
            if (other, other_path) != (role, role_path)
            and (
                role_path.is_relative_to(other_path)
                or other_path.is_relative_to(role_path)
            )
        ]
        if conflicts:
            _reject(
                "DISC-PROJECT-006", path,
                f"roles.{role} path {role_path} overlaps {', '.join(conflicts)}",
            )
    return parsed


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
            "DISC-PROJECT-001", path, f"[tool.{TABLE}] must be a TOML table",
        )

    raw_unit = table.get("unit")
    if raw_unit is None:
        _reject(
            "DISC-PROJECT-001", path, "unit is required (application or component)",
        )
    try:
        unit = UnitKind(raw_unit)
    except ValueError:
        _reject(
            "DISC-PROJECT-002", path,
            f"unit {raw_unit!r} is not application or component",
        )

    roots = _path_tuple(
        table.get("source_roots"), field_name="source_roots", source=path
    )
    engine = str(table.get("doc_engine", "none"))
    if engine not in DOC_ENGINES:
        known = ", ".join(sorted(DOC_ENGINES))
        _reject(
            "DISC-PROJECT-007", path,
            f"doc_engine {engine!r} is not one of {known}",
        )

    projection = table.get("pedagogical_full_projection", False)
    if not isinstance(projection, bool):
        _reject(
            "DISC-PROJECT-008", path,
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
                "DISC-PROJECT-005", path,
                f"layer {segment!r} maps to {target!r}, which is not one of {known}",
            )
        layers[str(segment)] = str(target)

    return Declaration(
        unit=unit,
        source_roots=roots,
        role_paths=_parse_roles(table, path, roots),
        layers=layers,
        doc_engine=engine,
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
                "DISC-PROJECT-009", chosen,
                f"not the nearest pyproject.toml for {start.resolve()}",
            )
        return parse(chosen)
    found = find_declaration(start)
    return parse(found) if found is not None else DEFAULT
