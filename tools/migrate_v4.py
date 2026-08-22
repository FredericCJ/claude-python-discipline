"""Preview or apply the conservative v3-to-v4 project-declaration migration.

The migrator changes only the contiguous ``[tool.agent-discipline]`` table
family in ``pyproject.toml``. It derives source-role paths from the existing
tree and legacy aliases, and translates uniquely attributable ``ARCH-004``
import contracts into v4 adapter-boundary ownership records. It never guesses
the governed unit or semantic architecture content.

Run without ``--apply`` to print the complete diff without writing:

    python tools/migrate_v4.py --root PATH --unit application
    python tools/migrate_v4.py --root PATH --unit component --apply
"""

from __future__ import annotations

import argparse
import ast
import difflib
import json
import os
import re
import sys
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

## Public role spelling to the v3 internal spelling accepted in alias values.
ROLE_TARGETS: Final[dict[str, str]] = {
    "domain": "domain",
    "app": "application",
    "application": "application",
    "ports": "ports",
    "adapters": "adapters",
    "shell": "shell",
}
## Table headers that begin the only bytes this tool may replace.
DISCIPLINE_HEADER: Final = "tool.agent-discipline"
## A TOML table header, including array-of-table syntax.
TABLE_HEADER: Final = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")
## Stable exit status for a plan that cannot be applied safely.
EXIT_BLOCKED: Final = 2
## Stable exit status for a successful preview or application.
EXIT_OK: Final = 0
## A package-root module has exactly the package and filename path parts.
PACKAGE_ROOT_PARTS: Final = 2


class MigrationError(ValueError):
    """A migration plan cannot be applied without losing intent."""


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One stable migration observation.

    @param diagnostic_id stable code suitable for tests and automation
    @param severity error blocks apply; warning requires subsequent authoring
    @param detail actionable explanation
    """

    ## Stable code suitable for tests and automation.
    diagnostic_id: str
    ## Error blocks apply; warning requires subsequent authoring or review.
    severity: Literal["error", "warning"]
    ## Actionable explanation.
    detail: str


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """A complete, deterministic preview for one project file."""

    ## Governed repository root.
    root: Path
    ## Project file whose bounded table may change.
    project_file: Path
    ## Exact bytes before migration.
    before: bytes
    ## Exact bytes after migration, equal to before for a no-op.
    after: bytes
    ## Diagnostics in stable discovery order.
    diagnostics: tuple[Diagnostic, ...]

    @property
    def blocked(self) -> bool:
        """Whether applying this plan would require a semantic guess.

        @return true when at least one error diagnostic exists
        """
        return any(item.severity == "error" for item in self.diagnostics)

    @property
    def changed(self) -> bool:
        """Whether the bounded project declaration differs.

        @return true when apply would replace bytes
        """
        return self.before != self.after


@dataclass(frozen=True, slots=True)
class DeclarationDraft:
    """The structural v4 declaration facts a v3 tree can expose."""

    ## Explicit operator-selected repository shape.
    unit: str
    ## Existing production import roots.
    roots: tuple[PurePosixPath, ...]
    ## Complete inferred production role partition.
    roles: Mapping[str, Sequence[PurePosixPath]]
    ## Independently selectable adapter package or module paths.
    boundaries: tuple[PurePosixPath, ...]
    ## Legacy foreign imports with one observed owning boundary.
    ownership: Mapping[str, PurePosixPath]
    ## Existing documentation engine selection.
    doc_engine: str
    ## Existing deliberate teaching-projection posture.
    pedagogical: bool


def _header_name(line: str) -> str | None:
    """Return the normalized TOML table name on one line.

    @param line source line including or excluding its newline
    @return table path without brackets, or None for ordinary content
    """
    matched = TABLE_HEADER.match(line.rstrip("\r\n"))
    return None if matched is None else matched.group(1).strip()


def _discipline_span(text: str) -> tuple[int, int] | None:
    """Locate the contiguous discipline table family by character offset.

    @param text complete project file
    @return half-open span, or None when v3 was never configured
    """
    lines = text.splitlines(keepends=True)
    starts: list[int] = []
    offset = 0
    for line in lines:
        starts.append(offset)
        offset += len(line)
    start_line: int | None = None
    end_line = len(lines)
    for index, line in enumerate(lines):
        name = _header_name(line)
        if start_line is None:
            if name == DISCIPLINE_HEADER:
                start_line = index
            continue
        if name is not None and not name.startswith(f"{DISCIPLINE_HEADER}."):
            end_line = index
            break
    if start_line is None:
        return None
    start = starts[start_line]
    end = starts[end_line] if end_line < len(starts) else len(text)
    return start, end


def _source_roots(document: Mapping[str, object], root: Path) -> tuple[PurePosixPath, ...]:
    """Derive import roots from build metadata or the conventional source tree.

    @param document decoded project TOML
    @param root governed repository root
    @return existing repository-relative source roots
    """
    tool = document.get("tool", {})
    if isinstance(tool, dict):
        setuptools = tool.get("setuptools", {})
        if isinstance(setuptools, dict):
            packages = setuptools.get("packages", {})
            if isinstance(packages, dict):
                find = packages.get("find", {})
                if isinstance(find, dict):
                    where = find.get("where")
                    if isinstance(where, list) and where:
                        return tuple(PurePosixPath(str(item)) for item in where)
    if (root / "src").is_dir():
        return (PurePosixPath("src"),)
    return ()


def _declaration_table(document: Mapping[str, object]) -> Mapping[str, object]:
    """Read the decoded discipline table without accepting a scalar impostor.

    @param document decoded pyproject
    @return declaration mapping, or an empty mapping for absent or invalid input
    """
    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        return {}
    table = tool.get("agent-discipline", {})
    return table if isinstance(table, dict) else {}


def _confined_roots(
    root: Path,
    candidates: Sequence[PurePosixPath],
) -> tuple[tuple[PurePosixPath, ...], list[Diagnostic]]:
    """Reject source roots that could make migration inspect another checkout.

    @param root governed repository root
    @param candidates roots derived from local build metadata
    @return safe roots and one diagnostic per rejected spelling or resolution
    """
    safe: list[PurePosixPath] = []
    diagnostics: list[Diagnostic] = []
    for candidate in candidates:
        spelling = candidate.as_posix()
        lexical_escape = (
            candidate.is_absolute()
            or bool(PureWindowsPath(spelling).drive)
            or ".." in candidate.parts
            or not tuple(part for part in candidate.parts if part not in {"", "."})
        )
        try:
            (root / Path(spelling)).resolve().relative_to(root.resolve())
            resolved_escape = False
        except ValueError:
            resolved_escape = True
        if lexical_escape or resolved_escape:
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-008_EXTERNAL_PATH",
                    "error",
                    f"source root {spelling!r} escapes the governed repository",
                )
            )
        else:
            safe.append(candidate)
    return tuple(safe), diagnostics


def _legacy_aliases(table: Mapping[str, object]) -> dict[str, str]:
    """Translate canonical segments and a v3 layers table to public role names.

    @param table decoded discipline declaration
    @return source segment to v4 role
    @throws ValueError when a legacy target has no v4 meaning
    """
    aliases = {
        "domain": "domain",
        "app": "application",
        "application": "application",
        "ports": "ports",
        "adapters": "adapters",
        "shell": "shell",
    }
    raw = table.get("layers", {})
    if not isinstance(raw, dict):
        detail = "the v3 layers declaration is not a TOML table"
        raise MigrationError(detail)
    for segment, target in raw.items():
        role = ROLE_TARGETS.get(str(target))
        if role is None:
            detail = f"legacy layer {segment!r} has unknown target {target!r}"
            raise MigrationError(detail)
        aliases[str(segment)] = role
    return aliases


def _role_prefix(
    relative: PurePosixPath,
    aliases: Mapping[str, str],
) -> tuple[str, PurePosixPath] | None:
    """Find the explicit path prefix that explains one Python file's role.

    @param relative file path beneath one source root
    @param aliases source segment to role
    @return role and role-owning prefix, or None when inference is unsafe
    """
    parts = relative.parts
    for index, part in enumerate(parts[:-1]):
        role = aliases.get(part)
        if role is not None:
            return role, PurePosixPath(*parts[: index + 1])
    stem_role = aliases.get(PurePosixPath(parts[-1]).stem)
    if stem_role is not None:
        return stem_role, relative
    if len(parts) == PACKAGE_ROOT_PARTS and parts[-1] in {"__init__.py", "__main__.py"}:
        return "shell", relative
    return None


def _discover_roles(
    root: Path,
    source_roots: Sequence[PurePosixPath],
    aliases: Mapping[str, str],
) -> tuple[dict[str, tuple[PurePosixPath, ...]], list[Diagnostic]]:
    """Partition every production Python file into inferred v4 role paths.

    @param root governed repository root
    @param source_roots declared import roots
    @param aliases v3 segment vocabulary
    @return role paths and fail-closed diagnostics
    """
    found: dict[str, set[PurePosixPath]] = {role: set() for role in ROLE_TARGETS.values()}
    diagnostics: list[Diagnostic] = []
    for source_root in source_roots:
        absolute = root / Path(source_root.as_posix())
        if not absolute.is_dir():
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-002_SOURCE_ROOT",
                    "error",
                    f"inferred source root {source_root} does not exist",
                )
            )
            continue
        for path in sorted(absolute.rglob("*.py")):
            if "__pycache__" in path.parts:
                continue
            relative = PurePosixPath(path.relative_to(absolute).as_posix())
            classified = _role_prefix(relative, aliases)
            if classified is None:
                diagnostics.append(
                    Diagnostic(
                        "MIGRATE-V4-003_UNMAPPED_SOURCE",
                        "error",
                        f"{source_root / relative} has no v3 role; move it or map its segment",
                    )
                )
                continue
            role, prefix = classified
            found[role].add(source_root / prefix)
    compact = {role: tuple(sorted(paths, key=str)) for role, paths in found.items() if paths}
    return compact, diagnostics


def _adapter_boundaries(
    root: Path,
    role_paths: Mapping[str, Sequence[PurePosixPath]],
) -> tuple[PurePosixPath, ...]:
    """Infer independently selectable children of each adapter role path.

    @param root governed repository root
    @param role_paths inferred role mapping
    @return non-overlapping adapter package or module paths
    """
    boundaries: set[PurePosixPath] = set()
    for adapter in role_paths.get("adapters", ()):
        absolute = root / Path(adapter.as_posix())
        if absolute.is_file():
            boundaries.add(adapter)
            continue
        candidates: set[PurePosixPath] = set()
        if absolute.is_dir():
            for child in sorted(absolute.iterdir()):
                is_package = child.is_dir() and any(child.rglob("*.py"))
                is_module = child.suffix == ".py" and child.name != "__init__.py"
                if is_package or is_module:
                    candidates.add(adapter / child.name)
        boundaries.update(candidates or {adapter})
    return tuple(sorted(boundaries, key=str))


def _contracts(document: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
    """Yield decoded import-linter contracts from one TOML document.

    @param document decoded standalone or inline configuration
    @return mapping records, silently excluding malformed non-record values
    """
    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        return ()
    importlinter = tool.get("importlinter", {})
    if not isinstance(importlinter, dict):
        return ()
    raw = importlinter.get("contracts", [])
    if not isinstance(raw, list):
        return ()
    return tuple(item for item in raw if isinstance(item, dict))


def _legacy_foreign_names(root: Path, project: Mapping[str, object]) -> tuple[str, ...]:
    """Collect import roots named by v3 ``ARCH-004`` contracts.

    @param root governed repository root
    @param project decoded pyproject, which may hold inline contracts
    @return unique import roots in lexical order
    """
    documents: list[Mapping[str, object]] = [project]
    standalone = root / "importlinter.toml"
    if standalone.is_file():
        documents.append(tomllib.loads(standalone.read_text(encoding="utf-8")))
    names: set[str] = set()
    for document in documents:
        for contract in _contracts(document):
            if "ARCH-004" not in str(contract.get("name", "")):
                continue
            forbidden = contract.get("forbidden_modules", [])
            if isinstance(forbidden, list):
                names.update(str(item).partition(".")[0] for item in forbidden)
    return tuple(sorted(name for name in names if name))


def _import_roots(path: Path) -> set[str]:
    """Read direct absolute import roots from one module.

    @param path Python module
    @return imported top-level names; malformed source produces an empty set
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        return set()
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.partition(".")[0])
    return roots


def _containing_boundary(
    path: Path,
    root: Path,
    boundaries: Sequence[PurePosixPath],
) -> PurePosixPath | None:
    """Find the one inferred adapter boundary containing a source file.

    @param path source module
    @param root governed repository root
    @param boundaries inferred adapter boundaries
    @return containing boundary or None outside all of them
    """
    relative = PurePosixPath(path.relative_to(root).as_posix())
    matches = [
        boundary
        for boundary in boundaries
        if relative == boundary or relative.is_relative_to(boundary)
    ]
    return matches[0] if len(matches) == 1 else None


def _foreign_ownership(
    root: Path,
    source_roots: Sequence[PurePosixPath],
    boundaries: Sequence[PurePosixPath],
    names: Sequence[str],
) -> tuple[dict[str, PurePosixPath], list[Diagnostic]]:
    """Translate each observed v3 foreign import to one owning boundary.

    @param root governed repository root
    @param source_roots production import roots
    @param boundaries inferred adapter boundaries
    @param names import roots registered by ARCH-004
    @return unique ownership records and ambiguity diagnostics
    """
    holders: dict[str, list[Path]] = {name: [] for name in names}
    for source_root in source_roots:
        absolute = root / Path(source_root.as_posix())
        if not absolute.is_dir():
            continue
        for path in sorted(absolute.rglob("*.py")):
            imported = _import_roots(path)
            for name in names:
                if name in imported:
                    holders[name].append(path)
    ownership: dict[str, PurePosixPath] = {}
    diagnostics: list[Diagnostic] = []
    for name in names:
        paths = holders[name]
        if not paths:
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-005_STALE_IMPORT_CONTRACT",
                    "warning",
                    f"ARCH-004 names {name!r}, but production source imports no such root",
                )
            )
            continue
        owners = {_containing_boundary(path, root, boundaries) for path in paths}
        if None in owners or len(owners) != 1:
            locations = ", ".join(str(path.relative_to(root)) for path in paths)
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-004_AMBIGUOUS_OWNER",
                    "error",
                    f"{name!r} is imported at {locations}; one adapter boundary cannot be inferred",
                )
            )
            continue
        ownership[name] = next(owner for owner in owners if owner is not None)
    return ownership, diagnostics


def _toml_string(value: str) -> str:
    """Render a string using TOML-compatible JSON quoting.

    @param value arbitrary string
    @return quoted scalar
    """
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: Sequence[PurePosixPath]) -> str:
    """Render repository paths as one deterministic TOML array.

    @param values repository-relative paths
    @return TOML array
    """
    return "[" + ", ".join(_toml_string(value.as_posix()) for value in values) + "]"


def _render_declaration(
    draft: DeclarationDraft,
    newline: str,
) -> str:
    """Render the complete v4 declaration table family.

    @param draft inferred structural facts
    @param newline original project line ending
    @return deterministic TOML block
    """
    lines = [
        "[tool.agent-discipline]",
        f"unit = {_toml_string(draft.unit)}",
        f"source_roots = {_toml_array(draft.roots)}",
        'architecture = "architecture.json"',
        f"doc_engine = {_toml_string(draft.doc_engine)}",
        f"pedagogical_full_projection = {str(draft.pedagogical).lower()}",
    ]
    if draft.boundaries:
        lines.append(f"adapter_boundaries = {_toml_array(draft.boundaries)}")
    lines.extend(["", "[tool.agent-discipline.roles]"])
    for role in ("domain", "application", "ports", "adapters", "shell"):
        paths = draft.roles.get(role)
        if paths:
            lines.append(f"{role} = {_toml_array(paths)}")
    for name, owner in sorted(draft.ownership.items()):
        lines.extend([
            "",
            "[[tool.agent-discipline.foreign_dependencies]]",
            f"import_name = {_toml_string(name)}",
            f"owner = {_toml_string(owner.as_posix())}",
        ])
    return newline.join(lines) + newline


def _draft(
    root: Path,
    document: Mapping[str, object],
    table: Mapping[str, object],
    unit: str | None,
) -> tuple[DeclarationDraft, list[Diagnostic]]:
    """Derive all structural facts and diagnostics from one v3 repository.

    @param root governed repository root
    @param document decoded pyproject
    @param table decoded v3 declaration table
    @param unit explicit operator-selected unit kind
    @return renderable draft and diagnostics
    """
    diagnostics: list[Diagnostic] = []
    if unit not in {"application", "component"}:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-001_UNIT_REQUIRED",
                "error",
                "choose --unit application or --unit component; repository intent is not inferred",
            )
        )
    roots, root_diagnostics = _confined_roots(root, _source_roots(document, root))
    diagnostics.extend(root_diagnostics)
    if not roots and not root_diagnostics:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-002_SOURCE_ROOT",
                "error",
                "no source root can be derived from build metadata or an existing src directory",
            )
        )
    known_v3_fields = {"doc_engine", "pedagogical_full_projection", "layers"}
    unknown_v3_fields = set(table) - known_v3_fields
    if unknown_v3_fields:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                "partial or unknown declaration fields would be lost: "
                + ", ".join(sorted(unknown_v3_fields)),
            )
        )
    try:
        aliases = _legacy_aliases(table)
    except MigrationError as problem:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                str(problem),
            )
        )
        aliases = {}
    roles, role_diagnostics = _discover_roles(root, roots, aliases)
    diagnostics.extend(role_diagnostics)
    boundaries = _adapter_boundaries(root, roles)
    ownership, owner_diagnostics = _foreign_ownership(
        root,
        roots,
        boundaries,
        _legacy_foreign_names(root, document),
    )
    diagnostics.extend(owner_diagnostics)
    diagnostics.append(
        Diagnostic(
            "MIGRATE-V4-007_ARCHITECTURE_AUTHORING_REQUIRED",
            "warning",
            "author architecture.json from the v4 template; semantic decisions are never inferred",
        )
    )
    return DeclarationDraft(
        unit=unit or "application",
        roots=roots,
        roles=roles,
        boundaries=boundaries,
        ownership=ownership,
        doc_engine=str(table.get("doc_engine", "none")),
        pedagogical=bool(table.get("pedagogical_full_projection", False)),
    ), diagnostics


def plan(root: Path, unit: str | None) -> MigrationPlan:
    """Build a deterministic migration plan without writing.

    @param root governed repository root
    @param unit explicit application or component kind
    @return complete plan, including blocking diagnostics
    """
    governed = root.resolve()
    project_file = governed / "pyproject.toml"
    before = project_file.read_bytes()
    text = before.decode("utf-8")
    document = tomllib.loads(text)
    table = _declaration_table(document)
    if all(key in table for key in ("unit", "source_roots", "architecture", "roles")):
        return MigrationPlan(governed, project_file, before, before, ())
    draft, diagnostics = _draft(governed, document, table, unit)

    span = _discipline_span(text)
    if span is None:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                "pyproject.toml has no [tool.agent-discipline] table to migrate conservatively",
            )
        )
        return MigrationPlan(governed, project_file, before, before, tuple(diagnostics))
    start, end = span
    newline = "\r\n" if "\r\n" in text else "\n"
    rendered = _render_declaration(draft, newline)
    after_text = text[:start] + rendered + text[end:]
    return MigrationPlan(
        governed,
        project_file,
        before,
        after_text.encode("utf-8"),
        tuple(diagnostics),
    )


def preview(migration: MigrationPlan) -> str:
    """Render diagnostics and a unified diff for review.

    @param migration complete migration plan
    @return stable human-readable preview
    """
    lines = [
        f"{item.severity.upper()} {item.diagnostic_id}: {item.detail}"
        for item in migration.diagnostics
    ]
    if migration.changed:
        before = migration.before.decode("utf-8").splitlines(keepends=True)
        after = migration.after.decode("utf-8").splitlines(keepends=True)
        lines.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile=str(migration.project_file),
                tofile=str(migration.project_file),
            )
        )
    else:
        lines.append("NO CHANGES")
    return "\n".join(line.rstrip("\n") for line in lines) + "\n"


def apply(migration: MigrationPlan) -> None:
    """Atomically apply a reviewed, unblocked declaration plan.

    @param migration plan produced against the current project bytes
    @throws ValueError when diagnostics block migration or source bytes drifted
    """
    if migration.blocked:
        detail = "migration has blocking diagnostics"
        raise MigrationError(detail)
    current = migration.project_file.read_bytes()
    if current != migration.before:
        detail = "pyproject.toml changed after preview; build a new plan"
        raise MigrationError(detail)
    if not migration.changed:
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".pyproject-v4-",
        suffix=".toml",
        dir=migration.project_file.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(migration.after)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(migration.project_file)
    finally:
        temporary = Path(temporary_name)
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    """Preview or apply one v3 declaration migration.

    @param argv command-line arguments, or None for sys.argv
    @return zero for a usable plan, two for a blocked one
    """
    parser = argparse.ArgumentParser(
        description="Preview or apply the conservative v3-to-v4 declaration migration."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--unit", choices=("application", "component"))
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args(argv)
    migration = plan(arguments.root, arguments.unit)
    sys.stdout.write(preview(migration))
    if migration.blocked:
        return EXIT_BLOCKED
    if arguments.apply:
        apply(migration)
        print("APPLIED" if migration.changed else "ALREADY CURRENT")
    else:
        print("DRY RUN; pass --apply to write")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
