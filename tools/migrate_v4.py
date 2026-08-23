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
        # Treat the current item as the candidate element consumed by the enclosing
        # Details: transformation.
        # Return true when at least one error diagnostic exists to the caller.
        return any(item.severity == "error" for item in self.diagnostics)

    @property
    def changed(self) -> bool:
        """Whether the bounded project declaration differs.

        @return true when apply would replace bytes
        """
        # Return true when apply would replace bytes to the caller.
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
    # Preserve the optional pattern match that carries the reported analysis count.
    matched = TABLE_HEADER.match(line.rstrip("\r\n"))
    # Return table path without brackets, or None for ordinary content to the caller.
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
    # Locate the structural boundary used to parse the external result safely.
    offset = 0
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance discipline span through the current input element in declared order.
    for line in lines:
        starts.append(offset)
        # Locate the structural boundary used to parse the external result safely.
        offset += len(line)
    # Compute start line using None for later discipline span logic.
    start_line: int | None = None
    # Compute end line using len for later discipline span logic.
    end_line = len(lines)
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance discipline span through the current input element in declared order.
    for index, line in enumerate(lines):
        # Normalize the current repository path to its portable baseline key spelling.
        name = _header_name(line)
        # Use the absence path when start line has no available value.
        if start_line is None:
            # Select the guarded path only after `name == DISCIPLINE_HEADER` is satisfied.
            if name == DISCIPLINE_HEADER:
                # Compute start line using index for later discipline span logic.
                start_line = index
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `name is not None and (not
        # Details: name.startswith(f'{DISCIPLINE_HEADER}.'))` is satisfied.
        if name is not None and not name.startswith(f"{DISCIPLINE_HEADER}."):
            # Compute end line using index for later discipline span logic.
            end_line = index
            # Stop the scan once the decisive match has been established.
            break
    # Use the absence path when start line has no available value.
    if start_line is None:
        # Return half-open span, or None when v3 was never configured to the caller.
        return None
    # Locate the structural boundary used to parse the external result safely.
    start = starts[start_line]
    # Compute end using starts[end_line] if end_line < len(starts) else len(text) for later
    # Details: discipline span logic.
    end = starts[end_line] if end_line < len(starts) else len(text)
    # Return half-open span, or None when v3 was never configured to the caller.
    return start, end


def _source_roots(document: Mapping[str, object], root: Path) -> tuple[PurePosixPath, ...]:
    """Derive import roots from build metadata or the conventional source tree.

    @param document decoded project TOML
        Each key is a TOML field and each value is its decoded content; mapping key order is
        deliberately unused.
    @param root governed repository root
    @return existing repository-relative source roots
    """
    # Compute tool using document.get for later source roots logic.
    tool = document.get("tool", {})
    # Select the guarded path only after `isinstance(tool, dict)` is satisfied.
    if isinstance(tool, dict):
        # Compute setuptools using tool.get for later source roots logic.
        setuptools = tool.get("setuptools", {})
        # Select the guarded path only after `isinstance(setuptools, dict)` is satisfied.
        if isinstance(setuptools, dict):
            # Compute packages using setuptools.get for later source roots logic.
            packages = setuptools.get("packages", {})
            # Select the guarded path only after `isinstance(packages, dict)` is satisfied.
            if isinstance(packages, dict):
                # Compute find using packages.get for later source roots logic.
                find = packages.get("find", {})
                # Select the guarded path only after `isinstance(find, dict)` is satisfied.
                if isinstance(find, dict):
                    # Compute where using find.get for later source roots logic.
                    where = find.get("where")
                    # Select the guarded path only after `isinstance(where, list) and where` is
                    # Details: satisfied.
                    if isinstance(where, list) and where:
                        # Treat the current item as the candidate element consumed by the
                        # Details: enclosing transformation.
                        # Return existing repository-relative source roots to the caller.
                        return tuple(PurePosixPath(str(item)) for item in where)
    # Refuse the target when its declared source directory is absent.
    if (root / "src").is_dir():
        # Return existing repository-relative source roots to the caller.
        return (PurePosixPath("src"),)
    # Return existing repository-relative source roots to the caller.
    return ()


def _declaration_table(document: Mapping[str, object]) -> Mapping[str, object]:
    """Read the decoded discipline table without accepting a scalar impostor.

    @param document decoded pyproject
        Each key is a TOML field and each value is its decoded content; mapping key order is
        deliberately unused.
    @return declaration mapping, or an empty mapping for absent or invalid input
    """
    # Compute tool using document.get for later declaration table logic.
    tool = document.get("tool", {})
    # Select the empty-or-disabled path when isinstance(tool, dict) has no usable value.
    if not isinstance(tool, dict):
        # Return declaration mapping, or an empty mapping for absent or invalid input to the
        # Details: caller.
        return {}
    # Compute table using tool.get for later declaration table logic.
    table = tool.get("agent-discipline", {})
    # Return declaration mapping, or an empty mapping for absent or invalid input to the caller.
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
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    # Advance confined roots through the current input element in declared order.
    for candidate in candidates:
        # Compute spelling using candidate.as posix for later confined roots logic.
        spelling = candidate.as_posix()
        # Unpack lexical escape, part using ( for later confined roots logic.
        lexical_escape = (
            candidate.is_absolute()
            or bool(PureWindowsPath(spelling).drive)
            or ".." in candidate.parts
            or not tuple(part for part in candidate.parts if part not in {"", "."})
        )
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            (root / Path(spelling)).resolve().relative_to(root.resolve())
            # True enables resolved escape; false selects its disabled alternative.
            resolved_escape = False
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ValueError:
            # True enables resolved escape; false selects its disabled alternative.
            resolved_escape = True
        # Select the guarded path only after `lexical_escape or resolved_escape` is satisfied.
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
    # Return safe roots and one diagnostic per rejected spelling or resolution to the caller.
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
    # Retain the immutable source representation consumed by subsequent analysis.
    raw = table.get("layers", {})
    # Select the empty-or-disabled path when isinstance(raw, dict) has no usable value.
    if not isinstance(raw, dict):
        # Compute detail using "the v3 layers declaration is not a TOML table" for later legacy
        # Details: aliases logic.
        detail = "the v3 layers declaration is not a TOML table"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise MigrationError(detail)
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Advance legacy aliases through the current input element in declared order.
    for segment, target in raw.items():
        # Compute role using ROLE TARGETS.get for later legacy aliases logic.
        role = ROLE_TARGETS.get(str(target))
        # Use the absence path when role has no available value.
        if role is None:
            # Compute detail using f"legacy layer {segment!r} has unknown target {target!r}" for
            # Details: later legacy aliases logic.
            detail = f"legacy layer {segment!r} has unknown target {target!r}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise MigrationError(detail)
        # Update  legacy aliases state only after the required source facts are available.
        aliases[str(segment)] = role
    # Return source segment to v4 role to the caller.
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
    # Compute parts using relative.parts for later role prefix logic.
    parts = relative.parts
    # Locate the structural boundary used to parse the external result safely.
    # Advance role prefix through the current input element in declared order.
    for index, part in enumerate(parts[:-1]):
        # Compute role using aliases.get for later role prefix logic.
        role = aliases.get(part)
        # Use the available-value path only when role is present.
        if role is not None:
            # Return role and role-owning prefix, or None when inference is unsafe to the
            # Details: caller.
            return role, PurePosixPath(*parts[: index + 1])
    # Compute stem role using aliases.get for later role prefix logic.
    stem_role = aliases.get(PurePosixPath(parts[-1]).stem)
    # Use the available-value path only when stem role is present.
    if stem_role is not None:
        # Return role and role-owning prefix, or None when inference is unsafe to the caller.
        return stem_role, relative
    # Select the guarded path only after `len(parts) == PACKAGE_ROOT_PARTS and parts[-1] in
    # Details: {'__init__.py', '__main__.py'}` is satisfied.
    if len(parts) == PACKAGE_ROOT_PARTS and parts[-1] in {"__init__.py", "__main__.py"}:
        # Return role and role-owning prefix, or None when inference is unsafe to the caller.
        return "shell", relative
    # Return role and role-owning prefix, or None when inference is unsafe to the caller.
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
    # Select source root as the current element from source_roots while discover roles preserves
    # Details: traversal order.
    # Advance discover roles through the current input element in declared order.
    for source_root in source_roots:
        # Compute absolute using root / Path(source_root.as_posix()) for later discover roles
        # Details: logic.
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
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Resolve the repository-confined path used by this operation before filesystem access.
        # Advance discover roles through the current input element in declared order.
        for path in sorted(absolute.rglob("*.py")):
            # Select the guarded path only after `'__pycache__' in path.parts` is satisfied.
            if "__pycache__" in path.parts:
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Compute relative using PurePosixPath for later discover roles logic.
            relative = PurePosixPath(path.relative_to(absolute).as_posix())
            # Compute classified using  role prefix for later discover roles logic.
            classified = _role_prefix(relative, aliases)
            # Use the absence path when classified has no available value.
            if classified is None:
                diagnostics.append(
                    Diagnostic(
                        "MIGRATE-V4-003_UNMAPPED_SOURCE",
                        "error",
                        f"{source_root / relative} has no v3 role; move it or map its segment",
                    )
                )
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Unpack prefix, role using classified for later discover roles logic.
            role, prefix = classified
            found[role].add(source_root / prefix)
    # Each compact key is a populated role and each value is its lexically sorted path tuple;
    # mapping key order is deliberately unused.
    compact = {role: tuple(sorted(paths, key=str)) for role, paths in found.items() if paths}
    # Return role paths and fail-closed diagnostics to the caller.
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
    # Select adapter as the current element from role_paths.get("adapters", ()) while adapter
    # Details: boundaries preserves traversal order.
    # Advance adapter boundaries through the current input element in declared order.
    for adapter in role_paths.get("adapters", ()):
        # Compute absolute using root / Path(adapter.as_posix()) for later adapter boundaries
        # Details: logic.
        absolute = root / Path(adapter.as_posix())
        # Select the regular-file path only when `absolute.is_file()` is satisfied.
        if absolute.is_file():
            boundaries.add(adapter)
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Collect unique candidates element values; their order is deliberately unordered.
        candidates: set[PurePosixPath] = set()
        # Refuse the target when its declared source directory is absent.
        if absolute.is_dir():
            # Select child as the current element from sorted(absolute.iterdir()) while adapter
            # Details: boundaries preserves traversal order.
            # Advance adapter boundaries through the current input element in declared order.
            for child in sorted(absolute.iterdir()):
                # Compute is package using child.is dir for later adapter boundaries logic.
                is_package = child.is_dir() and any(child.rglob("*.py"))
                # Compute is module using child.suffix == ".py" and child.name != "__init__.py"
                # Details: for later adapter boundaries logic.
                is_module = child.suffix == ".py" and child.name != "__init__.py"
                # Select the guarded path only after `is_package or is_module` is satisfied.
                if is_package or is_module:
                    candidates.add(adapter / child.name)
        boundaries.update(candidates or {adapter})
    # Return non-overlapping adapter package or module paths to the caller.
    return tuple(sorted(boundaries, key=str))


def _contracts(document: Mapping[str, object]) -> Iterable[Mapping[str, object]]:
    """Yield decoded import-linter contracts from one TOML document.

    @param document decoded standalone or inline configuration
        Each key is a TOML field and each value is its decoded content; mapping key order is
        deliberately unused.
    @return mapping records, silently excluding malformed non-record values
    """
    # Compute tool using document.get for later contracts logic.
    tool = document.get("tool", {})
    # Select the empty-or-disabled path when isinstance(tool, dict) has no usable value.
    if not isinstance(tool, dict):
        # Return mapping records, silently excluding malformed non-record values to the caller.
        return ()
    # Compute importlinter using tool.get for later contracts logic.
    importlinter = tool.get("importlinter", {})
    # Select the empty-or-disabled path when isinstance(importlinter, dict) has no usable value.
    if not isinstance(importlinter, dict):
        # Return mapping records, silently excluding malformed non-record values to the caller.
        return ()
    # Retain the immutable source representation consumed by subsequent analysis.
    raw = importlinter.get("contracts", [])
    # Select the empty-or-disabled path when isinstance(raw, list) has no usable value.
    if not isinstance(raw, list):
        # Return mapping records, silently excluding malformed non-record values to the caller.
        return ()
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Return mapping records, silently excluding malformed non-record values to the caller.
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
    # Compute standalone using root / "importlinter.toml" for later legacy foreign names logic.
    standalone = root / "importlinter.toml"
    # Select the regular-file path only when `standalone.is_file()` is satisfied.
    if standalone.is_file():
        documents.append(tomllib.loads(standalone.read_text(encoding="utf-8")))
    # Collect unique names element values; their order is deliberately unordered.
    names: set[str] = set()
    # Inspect each decoded configuration mapping in pyproject-then-standalone order.
    # Advance legacy foreign names through the current input element in declared order.
    for document in documents:
        # Select contract as the current element from _contracts(document) while legacy foreign
        # Details: names preserves traversal order.
        # Advance legacy foreign names through the current input element in declared order.
        for contract in _contracts(document):
            # Select the guarded path only after `'ARCH-004' not in str(contract.get('name',
            # Details: ''))` is satisfied.
            if "ARCH-004" not in str(contract.get("name", "")):
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Compute forbidden using contract.get for later legacy foreign names logic.
            forbidden = contract.get("forbidden_modules", [])
            # Select the guarded path only after `isinstance(forbidden, list)` is satisfied.
            if isinstance(forbidden, list):
                # Treat the current item as the candidate element consumed by the enclosing
                # Details: transformation.
                names.update(str(item).partition(".")[0] for item in forbidden)
    # Normalize the current repository path to its portable baseline key spelling.
    # Return unique import roots in lexical order to the caller.
    return tuple(sorted(name for name in names if name))


def _import_roots(path: Path) -> set[str]:
    """Read direct absolute import roots from one module.

    @param path Python module
    @return imported top-level names; malformed source produces an empty set
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Parse the Python source into the syntax tree used for structural fingerprinting.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, SyntaxError, UnicodeError):
        # Return imported top-level names; malformed source produces an empty set to the caller.
        return set()
    # Collect unique roots element values; their order is deliberately unordered.
    roots: set[str] = set()
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    # Advance import roots through the current input element in declared order.
    for node in ast.walk(tree):
        # Select the guarded path only after `isinstance(node, ast.Import)` is satisfied.
        if isinstance(node, ast.Import):
            # Select alias as the current element from node.names) while import roots preserves
            # Details: traversal order.
            roots.update(alias.name.partition(".")[0] for alias in node.names)
        # Select the guarded path only after `isinstance(node, ast.ImportFrom) and node.level ==
        # Details: 0 and node.module` is satisfied.
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.partition(".")[0])
    # Return imported top-level names; malformed source produces an empty set to the caller.
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
    # Compute relative using PurePosixPath for later containing boundary logic.
    relative = PurePosixPath(path.relative_to(root).as_posix())
    # Each matches element is one containing adapter boundary in supplied boundary order.
    matches = [
        boundary
        for boundary in boundaries
        if relative == boundary or relative.is_relative_to(boundary)
    ]
    # Return containing boundary or None outside all of them to the caller.
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
    # Select source root as the current element from source_roots while foreign ownership
    # Details: preserves traversal order.
    # Advance foreign ownership through the current input element in declared order.
    for source_root in source_roots:
        # Compute absolute using root / Path(source_root.as_posix()) for later foreign ownership
        # Details: logic.
        absolute = root / Path(source_root.as_posix())
        # Refuse the target when its declared source directory is absent.
        if not absolute.is_dir():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Resolve the repository-confined path used by this operation before filesystem access.
        # Advance foreign ownership through the current input element in declared order.
        for path in sorted(absolute.rglob("*.py")):
            # Compute imported using  import roots for later foreign ownership logic.
            imported = _import_roots(path)
            # Normalize the current repository path to its portable baseline key spelling.
            # Advance foreign ownership through the current input element in declared order.
            for name in names:
                # Select the guarded path only after `name in imported` is satisfied.
                if name in imported:
                    holders[name].append(path)
    # Each ownership key is a foreign import root and each value is its unique adapter boundary;
    # mapping key order is deliberately unused.
    ownership: dict[str, PurePosixPath] = {}
    # Each diagnostics element is one stale or ambiguous ownership report in import-name order.
    diagnostics: list[Diagnostic] = []
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance foreign ownership through the current input element in declared order.
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
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Collect unique owners element values; their order is deliberately unordered.
        owners = {_containing_boundary(path, root, boundaries) for path in paths}
        # Select the guarded path only after `None in owners or len(owners) != 1` is satisfied.
        if None in owners or len(owners) != 1:
            # Resolve the repository-confined path used by this operation before filesystem
            # Details: access.
            locations = ", ".join(str(path.relative_to(root)) for path in paths)
            diagnostics.append(
                Diagnostic(
                    "MIGRATE-V4-004_AMBIGUOUS_OWNER",
                    "error",
                    f"{name!r} is imported at {locations}; one adapter boundary cannot be inferred",
                )
            )
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select owner as the current element from owners if owner is not None) while foreign
        # Details: ownership preserves traversal order.
        # Update  foreign ownership state only after the required source facts are available.
        ownership[name] = next(owner for owner in owners if owner is not None)
    # Return unique ownership records and ambiguity diagnostics to the caller.
    return ownership, diagnostics


def _toml_string(value: str) -> str:
    """Render a string using TOML-compatible JSON quoting.

    @param value arbitrary string
    @return quoted scalar
    """
    # Return quoted scalar to the caller.
    return json.dumps(value, ensure_ascii=False)


def _toml_array(values: Sequence[PurePosixPath]) -> str:
    """Render repository paths as one deterministic TOML array.

    @param values repository-relative paths
        Each element is one path rendered in caller-provided order.
    @return TOML array
    """
    # Treat the current value as the candidate element consumed by the enclosing transformation.
    # Return tOML array to the caller.
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
    # Each lines element represents one decoded record; lexical order is preserved.
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
    # Select the guarded path only after `draft.boundaries` is satisfied.
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
    # Select role as the current element from ("domain", "application", "ports", "adapters",
    # Details: "shell") while render declaration preserves traversal order.
    # Advance render declaration through the current input element in declared order.
    for role in ("domain", "application", "ports", "adapters", "shell"):
        # Preserve paths element values in deterministic source order.
        paths = draft.roles.get(role)
        # Handle the non-empty or enabled paths state.
        if paths:
            lines.append(f"{role} = {_toml_array(paths)}")
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance render declaration through the current input element in declared order.
    for name, owner in sorted(draft.ownership.items()):
        lines.extend([
            "",
            "[[tool.agent-discipline.foreign_dependencies]]",
            f"import_name = {_toml_string(name)}",
            f"owner = {_toml_string(owner.as_posix())}",
        ])
    # Return deterministic TOML block to the caller.
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
    # Select the guarded path only after `unit not in {'application', 'component'}` is
    # Details: satisfied.
    if unit not in {"application", "component"}:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-001_UNIT_REQUIRED",
                "error",
                "choose --unit application or --unit component; repository intent is not inferred",
            )
        )
    # Unpack root diagnostics, roots using  confined roots for later draft logic.
    roots, root_diagnostics = _confined_roots(root, _source_roots(document, root))
    diagnostics.extend(root_diagnostics)
    # Select the empty-or-disabled path when roots and (not root diagnostics) has no usable
    # Details: value.
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
    # Compute unknown v3 fields using set for later draft logic.
    unknown_v3_fields = set(table) - known_v3_fields
    # Handle the non-empty or enabled unknown v3 fields state.
    if unknown_v3_fields:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                "partial or unknown declaration fields would be lost: "
                + ", ".join(sorted(unknown_v3_fields)),
            )
        )
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute aliases using  legacy aliases for later draft logic.
        aliases = _legacy_aliases(table)
    # Bind problem to the current value used by the next draft decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
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
    # Unpack role diagnostics, roles using  discover roles for later draft logic.
    roles, role_diagnostics = _discover_roles(root, roots, aliases)
    diagnostics.extend(role_diagnostics)
    # Compute boundaries using  adapter boundaries for later draft logic.
    boundaries = _adapter_boundaries(root, roles)
    # Unpack owner diagnostics, ownership using  foreign ownership for later draft logic.
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
    # Return renderable draft and diagnostics to the caller.
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
    # Compute governed using root.resolve for later plan logic.
    governed = root.resolve()
    # Resolve the repository-confined path used by this operation before filesystem access.
    project_file = governed / "pyproject.toml"
    # Compute before using project file.read bytes for later plan logic.
    before = project_file.read_bytes()
    # Retain the immutable source representation consumed by subsequent analysis.
    text = before.decode("utf-8")
    # Decode pyproject keys to TOML values; mapping key order is deliberately unused.
    document = tomllib.loads(text)
    # Compute table using  declaration table for later plan logic.
    table = _declaration_table(document)
    # Treat the current key as the candidate element consumed by the enclosing transformation.
    # Select the guarded path only after `all((key in table for key in ('unit', 'source_roots',
    # Details: 'architecture', 'contract_conformance', 'operational_model', 'security_model',
    # Details: 'adversarial_review', 'capabilities', 'roles')))` is satisfied.
    if all(
        key in table
        for key in (
            "unit", "source_roots", "architecture", "contract_conformance",
            "operational_model", "security_model", "adversarial_review",
            "capabilities", "roles",
        )
    ):
        # Return complete plan, including blocking diagnostics to the caller.
        return MigrationPlan(governed, project_file, before, before, ())
    # Preserve finding-record elements in checker emission order for the final verdict.
    draft, diagnostics = _draft(governed, document, table, unit)

    # Compute span using  discipline span for later plan logic.
    span = _discipline_span(text)
    # Use the absence path when span has no available value.
    if span is None:
        diagnostics.append(
            Diagnostic(
                "MIGRATE-V4-006_LEGACY_DECLARATION",
                "error",
                "pyproject.toml has no [tool.agent-discipline] table to migrate conservatively",
            )
        )
        # Return complete plan, including blocking diagnostics to the caller.
        return MigrationPlan(governed, project_file, before, before, tuple(diagnostics))
    # Locate the structural boundary used to parse the external result safely.
    start, end = span
    # Compute newline using "\r\n" if "\r\n" in text else "\n" for later plan logic.
    newline = "\r\n" if "\r\n" in text else "\n"
    # Compute rendered using  render declaration for later plan logic.
    rendered = _render_declaration(draft, newline)
    # Compute after text using text[:start] + rendered + text[end:] for later plan logic.
    after_text = text[:start] + rendered + text[end:]
    # Return complete plan, including blocking diagnostics to the caller.
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
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        f"{item.severity.upper()} {item.diagnostic_id}: {item.detail}"
        for item in migration.diagnostics
    ]
    # Select the guarded path only after `migration.changed` is satisfied.
    if migration.changed:
        # Compute before using migration.before.decode for later preview logic.
        before = migration.before.decode("utf-8").splitlines(keepends=True)
        # Compute after using migration.after.decode for later preview logic.
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
    # Preserve the current decoded diagnostic line before location normalization.
    # Return stable human-readable preview to the caller.
    return "\n".join(line.rstrip("\n") for line in lines) + "\n"


def apply(migration: MigrationPlan) -> None:
    """Atomically apply a reviewed, unblocked declaration plan.

    @param migration plan produced against the current project bytes
    @throws ValueError when diagnostics block migration or source bytes drifted

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Select the guarded path only after `migration.blocked` is satisfied.
    if migration.blocked:
        # Compute detail using "migration has blocking diagnostics" for later apply logic.
        detail = "migration has blocking diagnostics"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise MigrationError(detail)
    # Preserve the documentation-stripped behavior fingerprint used for comparison.
    current = migration.project_file.read_bytes()
    # Select the guarded path only after `current != migration.before` is satisfied.
    if current != migration.before:
        # Compute detail using "pyproject.toml changed after preview; build a new plan" for
        # Details: later apply logic.
        detail = "pyproject.toml changed after preview; build a new plan"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise MigrationError(detail)
    # Select the empty-or-disabled path when migration.changed has no usable value.
    if not migration.changed:
        # Return the completed apply result to its caller.
        return
    # Unpack descriptor, temporary name using tempfile.mkstemp for later apply logic.
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".pyproject-v4-",
        suffix=".toml",
        dir=migration.project_file.parent,
    )
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Bind stream to the current value used by the next apply decision.
        # Confine the acquired resource to this operation and release it on every exit.
        with os.fdopen(descriptor, "wb") as stream:
            # Publish the externally visible effect after all required inputs are ready.
            stream.write(migration.after)
            # Publish the externally visible effect after all required inputs are ready.
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary_name).replace(migration.project_file)
    finally:
        # Compute temporary using Path for later apply logic.
        temporary = Path(temporary_name)
        # Select the existing-artifact path only when `temporary.exists()` is satisfied.
        if temporary.exists():
            # Publish the externally visible effect after all required inputs are ready.
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    """Preview or apply one v3 declaration migration.

    @param argv command-line arguments, or None for sys.argv
    @return zero for a usable plan, two for a blocked one

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(
        description="Preview or apply the conservative v3-to-v4 declaration migration."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--unit", choices=("application", "component"))
    parser.add_argument("--apply", action="store_true")
    # Capture the validated invocation arguments that govern this execution.
    arguments = parser.parse_args(argv)
    # Compute migration using plan for later main logic.
    migration = plan(arguments.root, arguments.unit)
    # Publish the externally visible effect after all required inputs are ready.
    sys.stdout.write(preview(migration))
    # Select the guarded path only after `migration.blocked` is satisfied.
    if migration.blocked:
        # Return the aggregate process status to the command-line boundary.
        return EXIT_BLOCKED
    # Select the guarded path only after `arguments.apply` is satisfied.
    if arguments.apply:
        apply(migration)
        print("APPLIED" if migration.changed else "ALREADY CURRENT")
    else:
        print("DRY RUN; pass --apply to write")
    # Return the aggregate process status to the command-line boundary.
    return EXIT_OK


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Propagate the localized failure so callers cannot mistake it for success.
    raise SystemExit(main())
