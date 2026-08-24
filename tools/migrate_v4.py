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

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

## Public role spelling to the v3 internal spelling accepted in alias values.
## Each key is an accepted v3 role spelling and each value is its canonical v4 role; mapping
## key order is deliberately unused.
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
    ## Each element is one migration diagnostic in structural discovery order.
    diagnostics: tuple[Diagnostic, ...]

    @property
    def blocked(self) -> bool:
        """Whether applying this plan would require a semantic guess.

        @return true when at least one error diagnostic exists
        """
        # Any error diagnostic forbids apply; warnings preserve a reviewable usable plan.
        return any(item.severity == "error" for item in self.diagnostics)

    @property
    def changed(self) -> bool:
        """Whether the bounded project declaration differs.

        @return true when apply would replace bytes
        """
        # Exact bytes, including line endings, decide whether atomic replacement is needed.
        return self.before != self.after


@dataclass(frozen=True, slots=True)
class DeclarationDraft:
    """The structural v4 declaration facts a v3 tree can expose."""

    ## Explicit operator-selected repository shape.
    unit: str
    ## Existing production import roots.
    ## Each element is one repository-relative import root in build-metadata order.
    roots: tuple[PurePosixPath, ...]
    ## Complete inferred production role partition.
    ## Each key is a canonical role and each value lists its lexically sorted source paths;
    ## mapping key order is deliberately unused.
    roles: Mapping[str, Sequence[PurePosixPath]]
    ## Independently selectable adapter package or module paths.
    ## Each element is one independently selectable adapter path in lexical order.
    boundaries: tuple[PurePosixPath, ...]
    ## Legacy foreign imports with one observed owning boundary.
    ## Each key is a foreign import root and each value is its unique adapter boundary; mapping
    ## key order is deliberately unused.
    ownership: Mapping[str, PurePosixPath]
    ## Existing documentation engine selection.
    doc_engine: str
    ## Existing deliberate teaching-projection posture.
    ## True enables pedagogical; false selects its disabled alternative.
    pedagogical: bool


def _header_name(line: str) -> str | None:
    """Return the normalized TOML table name on one line.

    @param line source line including or excluding its newline
    @return table path without brackets, or None for ordinary content
    """
    # Match only TOML table headers and expose their normalized table name.
    matched = TABLE_HEADER.match(line.rstrip("\r\n"))
    return None if matched is None else matched.group(1).strip()


def _discipline_span(text: str) -> tuple[int, int] | None:
    """Locate the contiguous discipline table family by character offset.

    @param text complete project file
    @return half-open span, or None when v3 was never configured
    """
    # Each lines element is one source line including its terminator, in lexical order.
    lines = text.splitlines(keepends=True)
    # Each starts element is the byte offset of its corresponding line, in lexical order.
    starts: list[int] = []
    # Start cumulative byte-offset construction at the beginning of project text.
    offset = 0
    for line in lines:
        starts.append(offset)
        # Advance the cumulative byte offset by this line's exact encoded character length.
        offset += len(line)
    start_line: int | None = None
    end_line = len(lines)
    # Each indexed line may start the declaration family or the first following TOML table.
    for index, line in enumerate(lines):
        # The normalized table name is absent for ordinary content lines.
        name = _header_name(line)
        # Start the replaceable span only at the exact root discipline table.
        if start_line is None:
            # Only the exact root discipline table begins the replaceable span.
            if name == DISCIPLINE_HEADER:
                # Retain this line index as the inclusive declaration-family start.
                start_line = index
            # Until that root appears, subordinate-looking text has no migration ownership.
            continue
        # A new unrelated table closes the contiguous discipline table family.
        if name is not None and not name.startswith(f"{DISCIPLINE_HEADER}."):
            # Retain this line index as the exclusive declaration-family end.
            end_line = index
            # End the replaceable discipline-table span at the next top-level table.
            break
    # Report absence to the planner instead of inventing an insertion location.
    if start_line is None:
        # Absence is reported to the planner, which supplies the actionable diagnostic.
        return None
    # Convert the identified table-line span into exact text byte boundaries.
    start = starts[start_line]
    end = starts[end_line] if end_line < len(starts) else len(text)
    return start, end


def _source_roots(document: Mapping[str, object], root: Path) -> tuple[PurePosixPath, ...]:
    """Derive import roots from build metadata or the conventional source tree.

    @param document decoded project TOML
        Each key is a TOML field and each value is its decoded content; mapping key order is
        deliberately unused.
    @param root governed repository root
    @return existing repository-relative source roots
    """
    # Walk the optional setuptools package-discovery tables without accepting scalar impostors.
    tool = document.get("tool", {})
    if isinstance(tool, dict):
        # Setuptools owns declared package discovery beneath the general tool namespace.
        setuptools = tool.get("setuptools", {})
        if isinstance(setuptools, dict):
            # Package configuration may itself be absent or a non-table legacy value.
            packages = setuptools.get("packages", {})
            if isinstance(packages, dict):
                # The find table is the only supported source-root declaration in this migration.
                find = packages.get("find", {})
                if isinstance(find, dict):
                    # Each where element is one build-declared source root in authored order.
                    where = find.get("where")
                    if isinstance(where, list) and where:
                        # Preserve declaration order while normalizing each root to POSIX syntax.
                        return tuple(PurePosixPath(str(item)) for item in where)
    # Refuse the target when its declared source directory is absent.
    if (root / "src").is_dir():
        # Conventional src layout is the sole fallback when build metadata is silent.
        return (PurePosixPath("src"),)
    # Empty forces the planner to report that it cannot infer production scope.
    return ()


def _declaration_table(document: Mapping[str, object]) -> Mapping[str, object]:
    """Read the decoded discipline table without accepting a scalar impostor.

    @param document decoded pyproject
        Each key is a TOML field and each value is its decoded content; mapping key order is
        deliberately unused.
    @return declaration mapping, or an empty mapping for absent or invalid input
    """
    # Decode only mapping-shaped tool and discipline tables from untrusted TOML structure.
    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        # A scalar tool value cannot contain a valid discipline declaration.
        return {}
    # Preserve the exact v3 table for field accounting and conservative translation.
    table = tool.get("agent-discipline", {})
    # Malformed scalar declarations contribute no trustworthy migration facts.
    return table if isinstance(table, dict) else {}


def _confined_roots(
    root: Path,
    candidates: Sequence[PurePosixPath],
) -> tuple[tuple[PurePosixPath, ...], list[Diagnostic]]:
    """Reject source roots that could make migration inspect another checkout.

    @param root governed repository root
    @param candidates roots derived from local build metadata
        Each element is one repository-relative source-root candidate in declaration order.
    @return safe roots and one diagnostic per rejected spelling or resolution
    """
    # Each safe element is one confined existing source root in candidate order.
    safe: list[PurePosixPath] = []
    # Each diagnostics element is one unsafe-root refusal in candidate order.
    diagnostics: list[Diagnostic] = []
    # Each candidate is checked lexically and after filesystem resolution before admission.
    for candidate in candidates:
        # Spelling is the portable authored form used by both Windows and POSIX escape checks.
        spelling = candidate.as_posix()
        # Lexical escape covers absolute, drive-qualified, parent, and empty-effective paths.
        lexical_escape = (
            candidate.is_absolute()
            or bool(PureWindowsPath(spelling).drive)
            or ".." in candidate.parts
            or not tuple(part for part in candidate.parts if part not in {"", "."})
        )
        try:
            (root / Path(spelling)).resolve().relative_to(root.resolve())
            # True enables resolved escape; false selects its disabled alternative.
            resolved_escape = False
        except ValueError:
            # True enables resolved escape; false selects its disabled alternative.
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
        Each key is a v3 declaration field and each value is decoded TOML content; mapping key
        order is deliberately unused.
    @return source segment to v4 role
    @throws ValueError when a legacy target has no v4 meaning
    """
    # Each aliases key is a source path segment and each value is its canonical role; mapping key
    # order is deliberately unused.
    aliases = {
        "domain": "domain",
        "app": "application",
        "application": "application",
        "ports": "ports",
        "adapters": "adapters",
        "shell": "shell",
    }
    # Read the legacy layer-role mapping without coercing malformed table shapes.
    raw = table.get("layers", {})
    if not isinstance(raw, dict):
        # Preserve one stable explanation for a structurally unusable legacy layers value.
        detail = "the v3 layers declaration is not a TOML table"
        raise MigrationError(detail)
    # Each legacy segment/target pair extends the canonical aliases after target validation.
    for segment, target in raw.items():
        # Translate legacy target vocabulary to the v4 canonical role name.
        role = ROLE_TARGETS.get(str(target))
        # Diagnose legacy layer targets that have no unambiguous v4 role mapping.
        if role is None:
            # Include both authored fields so the operator can repair the exact mapping.
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
        Each key is a source path segment and each value is its canonical role; mapping key order
        is deliberately unused.
    @return role and role-owning prefix, or None when inference is unsafe
    """
    # Search directory segments before applying the narrower module-stem and package fallbacks.
    parts = relative.parts
    # Each index/part pair is one possible explicit role boundary before the filename.
    for index, part in enumerate(parts[:-1]):
        # Resolve the current segment against canonical and v3-declared aliases.
        role = aliases.get(part)
        if role is not None:
            # The owning prefix ends exactly at the segment that supplied the role.
            return role, PurePosixPath(*parts[: index + 1])
    # Single-file role modules may encode the role in their stem rather than a directory.
    stem_role = aliases.get(PurePosixPath(parts[-1]).stem)
    if stem_role is not None:
        # A stem-classified module is its own role-owning boundary.
        return stem_role, relative
    # Top-level package entry points belong to shell only at the exact package-root depth.
    if len(parts) == PACKAGE_ROOT_PARTS and parts[-1] in {"__init__.py", "__main__.py"}:
        # Retain the individual entry-point file because no enclosing role directory exists.
        return "shell", relative
    # None forces discovery to report rather than guess an architectural role.
    return None


def _discover_roles(
    root: Path,
    source_roots: Sequence[PurePosixPath],
    aliases: Mapping[str, str],
) -> tuple[dict[str, tuple[PurePosixPath, ...]], list[Diagnostic]]:
    """Partition every production Python file into inferred v4 role paths.

    @param root governed repository root
    @param source_roots declared import roots
        Each element is one repository-relative import root in declaration order.
    @param aliases v3 segment vocabulary
        Each key is a source path segment and each value is its canonical role; mapping key order
        is deliberately unused.
    @return role paths and fail-closed diagnostics
    """
    # Each found key is a canonical role and each value is its unordered set of inferred paths;
    # mapping key order is deliberately unused.
    found: dict[str, set[PurePosixPath]] = {role: set() for role in ROLE_TARGETS.values()}
    # Each diagnostics element is one role-discovery refusal in source traversal order.
    diagnostics: list[Diagnostic] = []
    # Traverse each declared import root independently so diagnostics retain its identity.
    for source_root in source_roots:
        # Absolute is the confined filesystem directory corresponding to this declared root.
        absolute = root / Path(source_root.as_posix())
        # Refuse the target when its declared source directory is absent.
        if not absolute.is_dir():
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-002_SOURCE_ROOT",
                    "error",
                    f"inferred source root {source_root} does not exist",
                )
            )
            # Continue so other valid roots still receive a complete migration inventory.
            continue
        # Each path is one production Python module in lexical filesystem order.
        for path in sorted(absolute.rglob("*.py")):
            # Interpreter caches are derived artifacts, never production role evidence.
            if "__pycache__" in path.parts:
                # Exclude this artifact without affecting subsequent source modules.
                continue
            # Classify the source-root-relative module path through explicit segment aliases.
            relative = PurePosixPath(path.relative_to(absolute).as_posix())
            classified = _role_prefix(relative, aliases)
            # Require every governed Python path to belong to exactly one inferred role prefix.
            if classified is None:
                diagnostics.append(
                    Diagnostic(
                        "MIGRATE-V4-003_UNMAPPED_SOURCE",
                        "error",
                        f"{source_root / relative} has no v3 role; move it or map its segment",
                    )
                )
                # Keep inventorying so the preview lists every unmapped production module.
                continue
            role, prefix = classified
            found[role].add(source_root / prefix)
    # Each compact key is a populated role and each value is its lexically sorted path tuple;
    # mapping key order is deliberately unused.
    compact = {role: tuple(sorted(paths, key=str)) for role, paths in found.items() if paths}
    return compact, diagnostics


def _adapter_boundaries(
    root: Path,
    role_paths: Mapping[str, Sequence[PurePosixPath]],
) -> tuple[PurePosixPath, ...]:
    """Infer independently selectable children of each adapter role path.

    @param root governed repository root
    @param role_paths inferred role mapping
        Each key is a canonical role and each value lists its inferred paths; mapping key order
        is deliberately unused.
    @return non-overlapping adapter package or module paths
    """
    # Collect unique boundaries element values; their order is deliberately unordered.
    boundaries: set[PurePosixPath] = set()
    # Each adapter role path contributes itself or its independently selectable children.
    for adapter in role_paths.get("adapters", ()):
        # Resolve the inferred role path only for local filesystem shape inspection.
        absolute = root / Path(adapter.as_posix())
        # Select the regular-file path only when `absolute.is_file()` is satisfied.
        if absolute.is_file():
            boundaries.add(adapter)
            # A module adapter is already the smallest selectable boundary.
            continue
        # Collect unique candidates element values; their order is deliberately unordered.
        candidates: set[PurePosixPath] = set()
        # Refuse the target when its declared source directory is absent.
        if absolute.is_dir():
            # Each child is assessed as a package boundary or standalone module boundary.
            for child in sorted(absolute.iterdir()):
                # Package means a directory containing Python; module excludes package init.
                is_package = child.is_dir() and any(child.rglob("*.py"))
                is_module = child.suffix == ".py" and child.name != "__init__.py"
                # Only independently importable Python-bearing children become boundaries.
                if is_package or is_module:
                    candidates.add(adapter / child.name)
        boundaries.update(candidates or {adapter})
    return tuple(sorted(boundaries, key=str))


def _contracts(document: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
    """Yield decoded import-linter contracts from one TOML document.

    @param document decoded standalone or inline configuration
        Each key is a TOML field and each value is its decoded content; mapping key order is
        deliberately unused.
    @return mapping records, silently excluding malformed non-record values
    """
    # Walk only mapping-shaped inline import-linter structure.
    tool = document.get("tool", {})
    if not isinstance(tool, dict):
        # Malformed tool structure contains no safely enumerable contracts.
        return ()
    # Preserve the import-linter subtable separately from unrelated tools.
    importlinter = tool.get("importlinter", {})
    if not isinstance(importlinter, dict):
        # A scalar import-linter value cannot own contract records.
        return ()
    # Read legacy import contracts without accepting a non-array declaration.
    raw = importlinter.get("contracts", [])
    if not isinstance(raw, list):
        # Non-list contracts are structurally unusable and contribute nothing inferred.
        return ()
    # Each returned element is one mapping-shaped contract in authored order.
    return tuple(item for item in raw if isinstance(item, dict))


def _legacy_foreign_names(root: Path, project: Mapping[str, object]) -> tuple[str, ...]:
    """Collect import roots named by v3 ``ARCH-004`` contracts.

    @param root governed repository root
    @param project decoded pyproject, which may hold inline contracts
        Each key is a pyproject field and each value is its decoded content; mapping key order is
        deliberately unused.
    @return unique import roots in lexical order
    """
    # Each documents element is one decoded import-linter configuration, ordered as pyproject
    # then optional standalone file.
    documents: list[Mapping[str, object]] = [project]
    standalone = root / "importlinter.toml"
    # Select the regular-file path only when `standalone.is_file()` is satisfied.
    if standalone.is_file():
        documents.append(tomllib.loads(standalone.read_text(encoding="utf-8")))
    # Collect unique names element values; their order is deliberately unordered.
    names: set[str] = set()
    # Each document contributes standalone or inline contracts in deterministic source order.
    for document in documents:
        # Each contract is one mapping-shaped import-linter declaration.
        for contract in _contracts(document):
            # Only the legacy ARCH-004 registration contract carries foreign-root ownership data.
            if "ARCH-004" not in str(contract.get("name", "")):
                # Unrelated architectural contracts have no migration meaning here.
                continue
            # Forbidden module entries encode the registered third-party import roots.
            forbidden = contract.get("forbidden_modules", [])
            if isinstance(forbidden, list):
                # Each item contributes its top-level import name; set order is deliberately unused.
                names.update(str(item).partition(".")[0] for item in forbidden)
    return tuple(sorted(name for name in names if name))


def _import_roots(path: Path) -> set[str]:
    """Read direct absolute import roots from one module.

    @param path Python module
    @return imported top-level names; malformed source produces an empty set
    """
    # Parse without importing adopter code; unreadable modules provide no import evidence.
    try:
        # Parse the Python source into the syntax tree used for structural fingerprinting.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError, UnicodeError):
        # Unreadable source supplies no trustworthy import-ownership evidence.
        return set()
    # Collect unique roots element values; their order is deliberately unordered.
    roots: set[str] = set()
    # Inspect every syntax node for direct absolute import forms only.
    for node in ast.walk(tree):
        # Plain imports may contribute several aliases, each reduced to its top-level root.
        if isinstance(node, ast.Import):
            # Each alias contributes one imported root; set order is deliberately unused.
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        # Absolute from-imports contribute their declared module root; relatives are local.
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
        Each element is one adapter path; input order is deliberately irrelevant because the
        longest containing boundary wins.
    @return containing boundary or None outside all of them
    """
    # Compare a portable repository-relative file identity against every candidate boundary.
    relative = PurePosixPath(path.relative_to(root).as_posix())
    # Each matches element is one containing adapter boundary in supplied boundary order.
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
        Each element is one repository-relative import root in declaration order.
    @param boundaries inferred adapter boundaries
        Each element is one adapter path in lexical order.
    @param names import roots registered by ARCH-004
        Each element is one foreign top-level import name in lexical order.
    @return unique ownership records and ambiguity diagnostics
    """
    # Each holders key is a foreign import root and each value lists importing module paths in
    # source traversal order; mapping key order is deliberately unused.
    holders: dict[str, list[Path]] = {name: [] for name in names}
    # Walk every declared production root while tolerating roots already diagnosed as absent.
    for source_root in source_roots:
        # Absolute is the filesystem anchor used solely for deterministic module discovery.
        absolute = root / Path(source_root.as_posix())
        # Refuse the target when its declared source directory is absent.
        if not absolute.is_dir():
            # Role discovery owns the missing-root diagnostic, so ownership avoids duplication.
            continue
        # Each path is one production module inspected in lexical order.
        for path in sorted(absolute.rglob("*.py")):
            # Imported contains unique direct absolute roots for this module; set order is unused.
            imported = _import_roots(path)
            # Each name is one legacy-registered foreign root tested against this module.
            for name in names:
                # Record only observed import sites for later boundary attribution.
                if name in imported:
                    holders[name].append(path)
    # Each ownership key is a foreign import root and each value is its unique adapter boundary;
    # mapping key order is deliberately unused.
    ownership: dict[str, PurePosixPath] = {}
    # Each diagnostics element is one stale or ambiguous ownership report in import-name order.
    diagnostics: list[Diagnostic] = []
    for name in names:
        # Preserve paths element values in deterministic source order.
        paths = holders[name]
        # Return the empty-result contract when the caller selected no governed paths.
        if not paths:
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-005_STALE_IMPORT_CONTRACT",
                    "warning",
                    f"ARCH-004 names {name!r}, but production source imports no such root",
                )
            )
            # A stale registration has no owner to infer; continue with the remaining names.
            continue
        # Collect unique owners element values; their order is deliberately unordered.
        owners = {_containing_boundary(path, root, boundaries) for path in paths}
        if None in owners or len(owners) != 1:
            # Locations enumerate every importer so the operator can split or move ownership.
            locations = ", ".join(str(path.relative_to(root)) for path in paths)
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-004_AMBIGUOUS_OWNER",
                    "error",
                    f"{name!r} is imported at {locations}; one adapter boundary cannot be inferred",
                )
            )
            # Ambiguous ownership is retained as an error rather than selecting arbitrarily.
            continue
        ownership[name] = next(owner for owner in owners if owner is not None)
    return ownership, diagnostics


def _toml_string(value: str) -> str:
    """Render a string using TOML-compatible JSON quoting.

    @param value arbitrary string
    @return quoted scalar
    """
    # JSON string quoting is a compatible deterministic subset of TOML basic strings.
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: Sequence[PurePosixPath]) -> str:
    """Render repository paths as one deterministic TOML array.

    @param values repository-relative paths
        Each element is one path rendered in caller-provided order.
    @return TOML array
    """
    # Each element is one caller-ordered POSIX path rendered through the shared scalar encoder.
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
    # Assemble the complete replacement TOML declaration in canonical field order.
    lines = [
        "[tool.agent-discipline]",
        f"unit = {_toml_string(draft.unit)}",
        f"source_roots = {_toml_array(draft.roots)}",
        'architecture = "architecture.json"',
        'contract_conformance = "contract-conformance.json"',
        'operational_model = "operational-model.json"',
        'security_model = "security-model.json"',
        'adversarial_review = "adversarial-review.json"',
        f"doc_engine = {_toml_string(draft.doc_engine)}",
        f"pedagogical_full_projection = {str(draft.pedagogical).lower()}",
    ]
    if draft.boundaries:
        lines.append(f"adapter_boundaries = {_toml_array(draft.boundaries)}")
    lines.extend([
        "",
        "[tool.agent-discipline.capabilities]",
        "public_api = false",
        "filesystem_io = false",
        "persistent_state = false",
        "generated_artifacts = false",
        "network_io = false",
        "launches_subprocesses = false",
        "owns_subprocess_lifecycle = false",
        "concurrency = false",
        "destructive_effects = false",
        "bounded_latency = false",
        "sensitive_data = false",
        "",
        "[tool.agent-discipline.roles]",
    ])
    for role in ("domain", "application", "ports", "adapters", "shell"):
        # Preserve paths element values in deterministic source order.
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
        Each key is a pyproject field and each value is its decoded content; mapping key order is
        deliberately unused.
    @param table decoded v3 declaration table
        Each key is a v3 declaration field and each value is decoded TOML content; mapping key
        order is deliberately unused.
    @param unit explicit operator-selected unit kind
    @return renderable draft and diagnostics
    """
    # Each diagnostics element is one draft refusal or authoring warning in discovery order.
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
    # Collect unique known v3 fields element values; their order is deliberately unordered.
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
    # Decode legacy aliases while retaining a diagnostic and empty map for malformed declarations.
    try:
        # Translate legacy segment vocabulary before any production path is classified.
        aliases = _legacy_aliases(table)
    # Preserve the migration defect while continuing with an empty, non-guessing alias map.
    except MigrationError as problem:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                str(problem),
            )
        )
        # Preserve an empty segment-to-role mapping after malformed legacy aliases; mapping key
        # order is deliberately unused.
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
            "author architecture.json, contract-conformance.json, operational-model.json, "
            "security-model.json, and adversarial-review.json from the v4 templates; "
            "then run checks.capabilities because semantic intent is never inferred",
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
    # Canonicalize the repository boundary before resolving or reading the declaration.
    governed = root.resolve()
    project_file = governed / "pyproject.toml"
    before = project_file.read_bytes()
    # Decode the exact reviewed project bytes before locating the replaceable declaration span.
    text = before.decode("utf-8")
    # Decode pyproject keys to TOML values; mapping key order is deliberately unused.
    document = tomllib.loads(text)
    table = _declaration_table(document)
    # A declaration carrying every v4 structural field is already migration-complete.
    if all(
        key in table
        for key in (
            "unit", "source_roots", "architecture", "contract_conformance",
            "operational_model", "security_model", "adversarial_review",
            "capabilities", "roles",
        )
    ):
        # Preserve exact bytes and report a clean no-op plan for already current repositories.
        return MigrationPlan(governed, project_file, before, before, ())
    # Retain the drafted declaration and ordered migration diagnostics as one reviewed plan.
    draft, diagnostics = _draft(governed, document, table, unit)

    # Locate the only declaration span this migration is authorized to replace.
    span = _discipline_span(text)
    # Block migration when no exact legacy discipline table can be replaced safely.
    if span is None:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                "pyproject.toml has no [tool.agent-discipline] table to migrate conservatively",
            )
        )
        # Block with unchanged bytes because synthesizing a missing table would be a guess.
        return MigrationPlan(governed, project_file, before, before, tuple(diagnostics))
    # Unpack the reviewed table boundaries before constructing replacement bytes.
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
    # Lead the preview with ordered diagnostics before file identity and byte diff.
    lines = [
        f"{item.severity.upper()} {item.diagnostic_id}: {item.detail}"
        for item in migration.diagnostics
    ]
    # Include a byte-derived declaration diff only when the reviewed plan changes content.
    if migration.changed:
        # These ordered line sequences retain terminators for an accurate unified diff.
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
    # Normalize each diagnostic/diff element to one final report newline.
    return "\n".join(line.rstrip("\n") for line in lines) + "\n"


def apply(migration: MigrationPlan) -> None:
    """Atomically apply a reviewed, unblocked declaration plan.

    @param migration plan produced against the current project bytes
    @throws ValueError when diagnostics block migration or source bytes drifted

    @par Effects
    Atomically replaces only declarations whose planned source bytes still match; a blocked
    or drifted plan performs no migration writes.
    """
    # Never write a plan containing any diagnostic classified as an error.
    if migration.blocked:
        # Keep the public exception stable while detailed causes remain in the preview.
        detail = "migration has blocking diagnostics"
        raise MigrationError(detail)
    # Preserve the documentation-stripped behavior fingerprint used for comparison.
    current = migration.project_file.read_bytes()
    if current != migration.before:
        # Concurrent byte drift invalidates every offset and inference in the reviewed plan.
        detail = "pyproject.toml changed after preview; build a new plan"
        raise MigrationError(detail)
    if not migration.changed:
        # An already-current plan requires no temporary file or filesystem mutation.
        return
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".pyproject-v4-",
        suffix=".toml",
        dir=migration.project_file.parent,
    )
    try:
        # Bound the raw descriptor so every buffered byte is flushed and synced before replace.
        with os.fdopen(descriptor, "wb") as stream:
            # Write, flush, and fsync the complete reviewed bytes before atomic publication.
            stream.write(migration.after)
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(migration.project_file)
    finally:
        # Temporary names remain possible only when publication failed before replacement.
        temporary = Path(temporary_name)
        # Remove the allocated sibling temporary file if atomic replacement did not consume it.
        if temporary.exists():
            # Remove only this explicitly allocated sibling temporary artifact.
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    """Preview or apply one v3 declaration migration.

    @param argv command-line arguments, or None for sys.argv
    @return zero for a usable plan, two for a blocked one

    @par Effects
    Prints the migration preview and, only with ``--apply`` on an unblocked plan, atomically
    replaces the planned declaration files.
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(
        description="Preview or apply the conservative v3-to-v4 declaration migration."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--unit", choices=("application", "component"))
    parser.add_argument("--apply", action="store_true")
    # Parse preview/apply intent and the target unit before constructing the migration plan.
    arguments = parser.parse_args(argv)
    migration = plan(arguments.root, arguments.unit)
    sys.stdout.write(preview(migration))
    if migration.blocked:
        # Preserve the fail-closed planning verdict without attempting any migration writes.
        return EXIT_BLOCKED
    if arguments.apply:
        apply(migration)
        print("APPLIED" if migration.changed else "ALREADY CURRENT")
    else:
        print("DRY RUN; pass --apply to write")
    return EXIT_OK


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Surface blocked migration status to shell and CI callers.
    raise SystemExit(main())
