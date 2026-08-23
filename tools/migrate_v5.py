"""Preview or apply the conservative v4-to-v5 documentation migration.

The migration changes only mechanically decidable project facts: it selects
Doxygen, declares the project-owned documentation model, names a local
``Doxyfile``, and creates missing canonical artifacts. It does not invent
semantic comments, naming grammars, abbreviations, generated-code ownership, or
semantic properties. Those remain explicit authoring work reported by the
aggregate checks after migration.

Run without ``--apply`` to inspect every byte that would change::

    python .agent/tools/migrate_v5.py --root .
    python .agent/tools/migrate_v5.py --root . --apply
"""

from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Literal

# Import annotation-only collection contracts without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Successful process outcome.
EXIT_OK: Final = 0
## Refused process outcome used when any blocking diagnostic exists.
EXIT_BLOCKED: Final = 2
## Package root both upstream and below an installed ``.agent`` directory.
BUNDLE_ROOT: Final = Path(__file__).resolve().parent.parent
## Canonical Doxygen posture shipped by the package.
DOXYGEN_TEMPLATE: Final = BUNDLE_ROOT / "enforce" / "Doxyfile"
## Exact v4 main-table facts needed before a v5-only edit is safe.
V4_FIELDS: Final[frozenset[str]] = frozenset({
    "unit",
    "source_roots",
    "architecture",
    "contract_conformance",
    "operational_model",
    "security_model",
    "adversarial_review",
    "doc_engine",
})
## Exact table-header shape used to locate bounded TOML table bodies.
TABLE_HEADER: Final = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(?:#.*)?$")
## Scalar-assignment shape used to locate one key within a bounded table body.
SCALAR_ASSIGNMENT: Final = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z0-9_-]+)\s*=")
## Repository subtrees that cannot be inferred to be project-owned maintenance code.
IGNORED_DISCOVERY_PARTS: Final[frozenset[str]] = frozenset({
    ".agent",
    ".git",
    ".venv",
    "build",
    "dist",
    "node_modules",
    "__pycache__",
})


class MigrationError(ValueError):
    """A migration plan cannot be applied without losing or inventing intent.

    @param detail concrete refusal reason
    """

    ## Stable diagnostic namespace for unsafe or ambiguous structural migration.
    code = "discipline.migration.v5_refused"

    def __init__(self, detail: str) -> None:
        """Build a typed refusal from already-localized detail.

        @param detail concrete refusal reason
        """
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One stable migration observation.

    @param diagnostic_id stable code suitable for automation
    @param severity error blocks application; warning names follow-up authorship
    @param detail concrete explanation and remediation
    """

    ## Stable machine-readable migration outcome identifier.
    diagnostic_id: str
    ## Blocking error or non-blocking authorship warning; errors prevent application.
    severity: Literal["error", "warning"]
    ## Localized cause and the action required from the adopter.
    detail: str


@dataclass(frozen=True, slots=True)
class ArtifactChange:
    """One auxiliary artifact in the migration transaction.

    @param path confined artifact path
    @param before exact previous bytes, or None when absent
    @param after exact desired bytes
    """

    ## Repository-confined destination whose bytes are guarded.
    path: Path
    ## Exact bytes observed while planning, or None when the artifact was absent.
    before: bytes | None
    ## Exact bytes to publish if the guard still matches.
    after: bytes

    @property
    def changed(self) -> bool:
        """Whether applying the artifact would change repository state.

        @return true for a new artifact or different bytes
        """
        # Distinguish a creation or byte replacement from an already-current artifact.
        return self.before != self.after


@dataclass(frozen=True, slots=True)
class MigrationPlan:
    """A deterministic v4-to-v5 preview and its guarded writes.

    @param root governed repository root
    @param project_file exact project declaration
    @param before exact declaration bytes before migration
    @param after exact declaration bytes after migration
    @param artifacts auxiliary local artifacts and their expected prior bytes
    @param diagnostics stable observations in discovery order
    """

    ## Absolute repository boundary for every planned path.
    root: Path
    ## Exact project declaration published after auxiliary artifacts.
    project_file: Path
    ## Declaration bytes captured before planning.
    before: bytes
    ## Desired declaration bytes after the structural migration.
    after: bytes
    ## Artifact changes in deterministic publication order; each element guards prior bytes.
    artifacts: tuple[ArtifactChange, ...]
    ## Diagnostics in discovery order; each element is a stable refusal or follow-up action.
    diagnostics: tuple[Diagnostic, ...]

    @property
    def blocked(self) -> bool:
        """Whether any diagnostic forbids application.

        @return true when at least one error exists
        """
        # Reduce the ordered diagnostics to the two-state application decision.
        return any(item.severity == "error" for item in self.diagnostics)

    @property
    def changed(self) -> bool:
        """Whether the project declaration or an auxiliary artifact differs.

        @return true when application has at least one write
        """
        # Include both the declaration and every ordered auxiliary artifact in the delta.
        return self.before != self.after or any(item.changed for item in self.artifacts)


@dataclass(frozen=True, slots=True)
class MigrationInputs:
    """Validated structural inputs used by declaration and artifact rendering.

    @param source_roots exact v4 production roots
    @param model_spelling declaration spelling of the documentation model
    @param model_path confined model path, or None after a diagnostic
    @param doxyfile_spelling gate spelling of the Doxyfile
    @param doxyfile_path confined Doxyfile path, or None after a diagnostic
    """

    ## Production roots in declared order; each element is repository-relative.
    source_roots: tuple[PurePosixPath, ...]
    ## Project-relative documentation-model spelling retained in TOML.
    model_spelling: str
    ## Confined model destination, or None when path validation refused it.
    model_path: Path | None
    ## Project-relative Doxyfile spelling retained in TOML.
    doxyfile_spelling: str
    ## Confined Doxyfile destination, or None when path validation refused it.
    doxyfile_path: Path | None


def _table(document: Mapping[str, object], *names: str) -> Mapping[str, object]:
    """Walk decoded TOML tables without accepting scalar impostors.

    @param document decoded TOML mapping whose keys name fields and whose values are
        decoded TOML values; key iteration order is deliberately unused
    @param names table path segments
    @return requested table, or an empty mapping when absent or malformed
    """
    # Track the table-like object reached after each ordered path segment.
    current: object = document
    # Descend through the named TOML path in caller-declared order.
    for name in names:
        # A scalar at an intermediate segment makes the requested table absent.
        if not isinstance(current, dict):
            # Normalize malformed or absent tables to the caller's empty-table contract.
            return {}
        # Advance to the next segment while preserving an absent segment as an empty table.
        current = current.get(name, {})
    # Expose only mapping-shaped terminal values to downstream field readers.
    return current if isinstance(current, dict) else {}


def _newline(text: str) -> str:
    """Preserve the project declaration's existing line-ending convention.

    @param text complete declaration text
    @return CRLF when present, otherwise LF
    """
    # Preserve CRLF when it is present; otherwise use the canonical LF alternative.
    return "\r\n" if "\r\n" in text else "\n"


def _table_span(lines: Sequence[str], table: str) -> tuple[int, int] | None:
    """Locate one exact TOML table by line indexes.

    @param lines ordered declaration line elements, each retaining its newline bytes
    @param table exact dotted table name
    @return half-open body span, or None when the table is absent
    """
    # Hold the first body-line index, or None until the exact table is encountered.
    start: int | None = None
    # Examine each declaration line in source order so the half-open span is stable.
    for index, line in enumerate(lines):
        # Parse only table-header lines while retaining the original source sequence.
        matched = TABLE_HEADER.match(line.rstrip("\r\n"))
        # Non-header content cannot start or terminate the requested table.
        if matched is None:
            # Continue the ordered scan until a structural boundary appears.
            continue
        # The next header terminates a table body already found.
        if start is not None:
            # Return the discovered body before interpreting the following table name.
            return start, index
        # Record the body start only for the exact dotted table requested by the caller.
        if matched.group(1).strip() == table:
            # Store the first body-line index immediately after the matched header.
            start = index + 1
    # Extend a final table to end-of-file, or report that no exact header existed.
    return None if start is None else (start, len(lines))


def _set_scalar(text: str, table: str, key: str, rendered: str) -> str:
    """Set one scalar inside one exact table while preserving all other bytes.

    @param text complete TOML text
    @param table exact dotted table name
    @param key scalar key to replace or append
    @param rendered TOML value spelling
    @return text containing the requested assignment
    @throws MigrationError when duplicate assignments make ownership ambiguous
    """
    # Retain the declaration's line-ending convention for every inserted line.
    newline = _newline(text)
    # Represent each source line with its terminator in original declaration order.
    lines = text.splitlines(keepends=True)
    # Locate the exact table body that may own the scalar assignment.
    span = _table_span(lines, table)
    # Append a missing table without disturbing any existing declaration bytes.
    if span is None:
        # Complete a non-empty unterminated final line before adding TOML structure.
        if text and not text.endswith(("\n", "\r")):
            # Extend only the local rendering with the declaration's established terminator.
            text += newline
        # Separate the new table from prior content unless a blank line already does so.
        separator = "" if not text or text.endswith(newline * 2) else newline
        # Publish the new table and assignment as the final declaration section.
        return text + separator + f"[{table}]{newline}{key} = {rendered}{newline}"
    # Unpack the half-open body indexes that bound candidate assignments.
    start, end = span
    # Preserve each matching assignment index in source order for ambiguity detection.
    matches = [
        index
        for index in range(start, end)
        if (assignment := SCALAR_ASSIGNMENT.match(lines[index])) is not None
        and assignment.group("key") == key
    ]
    # Multiple owners make a byte-preserving scalar edit unsafe.
    if len(matches) > 1:
        # Localize the exact conflicting table and key for the migration refusal.
        detail = f"[{table}] contains duplicate {key!r} assignments"
        # Refuse instead of selecting an arbitrary declaration occurrence.
        raise MigrationError(detail)
    # Render the one canonical assignment with the preserved newline convention.
    replacement = f"{key} = {rendered}{newline}"
    # Replace an existing unique assignment in place.
    if matches:
        # Replace the one matched source position without moving surrounding table content.
        lines[matches[0]] = replacement
    # Otherwise insert before trailing blank lines in the owning table body.
    else:
        # Start at the next table boundary or end-of-file.
        insertion = end
        # Walk backward over blank separators so the new key remains inside the table.
        while insertion > start and not lines[insertion - 1].strip():
            # Move the insertion boundary toward the final non-blank table element.
            insertion -= 1
        # Add the missing scalar at the stable end of existing table content.
        lines.insert(insertion, replacement)
    # Reassemble the declaration without normalizing untouched source lines.
    return "".join(lines)


def _confined(root: Path, raw: object, field: str) -> tuple[Path | None, Diagnostic | None]:
    """Resolve one non-root repository-relative path without permitting escape.

    @param root governed repository root
    @param raw decoded path spelling
    @param field owning declaration field
    @return resolved path and no diagnostic, or no path and a blocking diagnostic
    @par Effects Reads filesystem path resolution state without modifying repository data.
    """
    # Reject absent, non-text, and whitespace-only spellings as one empty-path defect.
    if not isinstance(raw, str) or not raw.strip():
        # Return the blocking diagnostic in-band so all path defects can be accumulated.
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", f"{field} is empty")
    # Normalize slash spelling into a platform-independent repository-relative candidate.
    candidate = PurePosixPath(raw.replace("\\", "/"))
    # True means one unsafe absolute, drive, or parent-traversal form exists; false is relative.
    unsafe_shape = any(
        (candidate.is_absolute(), bool(PureWindowsPath(raw).drive), ".." in candidate.parts)
    )
    # Refuse every unsafe syntactic path form before filesystem resolution.
    if unsafe_shape:
        # Preserve the submitted spelling in the actionable confinement diagnostic.
        detail = f"{field}={raw!r} must be a non-root path inside the repository"
        # Report the unsafe candidate without resolving or writing it.
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", detail)
    # Retain meaningful path components in caller order while removing local-dot noise.
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    # The repository root itself is too broad to own either generated artifact.
    if not parts:
        # Name the exact field whose spelling collapsed to the forbidden root.
        detail = f"{field} may not name the repository root"
        # Return a blocking refusal rather than broadening the write target.
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", detail)
    # Resolve the normalized components against the one governed repository boundary.
    resolved = (root / Path(*parts)).resolve()
    # Verify resolved containment even when links or platform normalization intervene.
    try:
        resolved.relative_to(root.resolve())
    # Translate a containment failure into the stable migration diagnostic channel.
    except ValueError:
        # Explain the resolution result without exposing an unconfined path as writable.
        detail = f"{field}={raw!r} resolves outside the repository"
        # Return the refused state and leave repository state unchanged.
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", detail)
    # Admit the confined absolute destination with no diagnostic alternative.
    return resolved, None


def _source_roots(table: Mapping[str, object]) -> tuple[PurePosixPath, ...]:
    """Read the already-required v4 production roots.

    @param table decoded discipline mapping whose keys name fields and whose values are
        decoded TOML values; key iteration order is deliberately unused
    @return normalized source-root paths
    @throws MigrationError when the v4 field is not a non-empty string array
    @par Effects Does not modify external state; reads only the supplied decoded mapping.
    """
    # Read the untrusted TOML value before constructing any path representation.
    raw = table.get("source_roots")
    # The TOML value must first be an array before element semantics can be inspected.
    if not isinstance(raw, list):
        # Localize the v4 contract violation used by the caller's stable diagnostic.
        detail = "source_roots must be a non-empty array of strings"
        # Stop structural rendering because no production scope can be inferred safely.
        raise MigrationError(detail)
    # An empty array supplies no production boundary for generated project artifacts.
    if not raw:
        # Localize the v4 contract violation used by the caller's stable diagnostic.
        detail = "source_roots must be a non-empty array of strings"
        # Stop structural rendering because no production scope can be inferred safely.
        raise MigrationError(detail)
    # Every array element must be text; true means all are paths, false finds a scalar impostor.
    if not all(isinstance(item, str) for item in raw):
        # Localize the v4 contract violation used by the caller's stable diagnostic.
        detail = "source_roots must be a non-empty array of strings"
        # Stop structural rendering because no production scope can be inferred safely.
        raise MigrationError(detail)
    # Preserve each declared root's order while normalizing cross-platform slash spelling.
    roots = tuple(PurePosixPath(str(item).replace("\\", "/")) for item in raw)
    # A duplicate root has no distinct semantic owner and makes scope publication ambiguous.
    if len(set(roots)) != len(roots):
        # Name the duplicate-set defect without guessing which occurrence to discard.
        detail = "source_roots contains duplicates"
        # Refuse the ambiguous declaration rather than silently deduplicating it.
        raise MigrationError(detail)
    # Return the ordered, duplicate-free production-root elements.
    return roots


def _scope_payload(
    root: Path,
    document: Mapping[str, object],
    source_roots: Sequence[PurePosixPath],
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    """Derive only conventional, mechanically attributable documentation scopes.

    @param root governed repository root
    @param document decoded project mapping whose keys name tables and whose values are
        decoded TOML values; key iteration order is deliberately unused
    @param source_roots production-root elements in declaration order
    @return scope records and Python paths still requiring ownership review
    @par Effects Reads repository directories and Python-file names without changing them.
    """
    # Seed the ordered scope array with one governed production element per declared root.
    scopes: list[dict[str, str]] = [
        {"path": path.as_posix(), "kind": "production", "ownership": "governed"}
        for path in source_roots
    ]
    # Read pytest's optional declaration table as the strongest test-scope evidence.
    pytest_table = _table(document, "tool", "pytest", "ini_options")
    # Preserve each declared test path in TOML order, or an empty collection when absent.
    raw_testpaths = pytest_table.get("testpaths", [])
    # Normalize every textual test-path element in declaration order; malformed shapes mean none.
    testpaths = (
        tuple(PurePosixPath(str(item).replace("\\", "/")) for item in raw_testpaths)
        if isinstance(raw_testpaths, list)
        else ()
    )
    # Infer the conventional tests directory only when pytest supplied no explicit alternative.
    if not testpaths and (root / "tests").is_dir():
        # Record the single conventional test element as an ordered one-item sequence.
        testpaths = (PurePosixPath("tests"),)
    # Build candidate scope pairs in deterministic test-first order; each pair is path and kind.
    candidates = [
        (path, "tests") for path in testpaths
    ]
    # Treat a conventional tools subtree as repository-owned maintenance when it exists.
    if (root / "tools").is_dir():
        # Append maintenance after every explicit test scope to retain stable publication order.
        candidates.append((PurePosixPath("tools"), "maintenance"))
    # Add each root-level Python module as a maintenance scope in sorted filename order.
    candidates.extend(
        (PurePosixPath(path.name), "maintenance") for path in sorted(root.glob("*.py"))
    )
    # Classify each candidate without duplicating a broader production or prior scope.
    for scope_path, kind in candidates:
        # A candidate nested under production already inherits governed ownership.
        if any(
            scope_path == existing or scope_path.is_relative_to(existing)
            for existing in source_roots
        ):
            # Skip the redundant narrower record while retaining candidate scan order.
            continue
        # Avoid publishing the same exact scope twice when discovery channels overlap.
        if any(record["path"] == scope_path.as_posix() for record in scopes):
            # Preserve the first mechanically attributed kind and continue discovery.
            continue
        # Publish one governed record for the newly attributable path and its repository role.
        scopes.append(
            {"path": scope_path.as_posix(), "kind": kind, "ownership": "governed"}
        )

    # Freeze each published scope path in output order for the coverage census.
    covered = tuple(PurePosixPath(record["path"]) for record in scopes)
    # Accumulate each repository-relative Python path requiring review in sorted order.
    uncovered: list[str] = []
    # Inspect every Python file in deterministic repository path order.
    for source_file in sorted(root.rglob("*.py")):
        # Convert the candidate to the POSIX spelling used by the documentation model.
        relative = PurePosixPath(source_file.relative_to(root).as_posix())
        # Omit known environment, package, build, and cache subtrees from ownership inference.
        if IGNORED_DISCOVERY_PARTS & set(relative.parts):
            # Continue the census without presenting ignored infrastructure as adopter source.
            continue
        # Retain only files outside every mechanically attributable scope.
        if not any(relative == scope or relative.is_relative_to(scope) for scope in covered):
            # Append the exact path for an explicit governed/generated/foreign author decision.
            uncovered.append(relative.as_posix())
    # Return stable scope-record elements followed by stable uncovered-path elements.
    return scopes, tuple(uncovered)


def _model_bytes(scopes: Sequence[Mapping[str, str]]) -> bytes:
    """Render a strict starter model without inventing project vocabulary.

    @param scopes mechanically attributable scope-record elements in publication order
    @return canonical UTF-8 JSON bytes
    """
    # Assemble the closed schema while preserving each scope record in caller order.
    payload = {
        "schema_version": 1,
        "engine": "doxygen",
        "scopes": list(scopes),
        "controlled_abbreviations": [],
        "identifier_grammars": [],
        "generated_names": {"markers": ["generated", "derived"], "mappings": {}},
        "semantic_properties": [],
    }
    # Encode the starter model as deterministic indented UTF-8 with one final newline.
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _doxyfile_bytes(project_name: str, source_roots: Sequence[PurePosixPath]) -> bytes:
    """Specialize the shipped canonical Doxygen posture for one project.

    @param project_name declared distribution name
    @param source_roots exact production-root elements in declaration order consumed by the gate
    @return canonical UTF-8 configuration bytes
    @throws MigrationError when the package template is absent or malformed
    @par Effects Reads the package's canonical Doxyfile without modifying it.
    """
    # Read the package-owned canonical posture as the sole configuration source.
    try:
        # Hold the complete canonical configuration text for bounded scalar specialization.
        text = DOXYGEN_TEMPLATE.read_text(encoding="utf-8")
    # Translate template access failures into the migration's stable refusal type.
    except OSError as problem:
        # Preserve the operating-system detail needed to repair package installation.
        detail = f"cannot read canonical Doxyfile: {problem}"
        # Chain the original access failure beneath the adopter-facing migration error.
        raise MigrationError(detail) from problem
    # Render every production-root element in declared order as a quoted Doxygen input.
    input_value = " ".join(json.dumps(path.as_posix()) for path in source_roots)
    # Quote the distribution name so whitespace and punctuation remain one Doxygen value.
    name_value = json.dumps(project_name)
    # Replace the unique project-name assignment while counting structural matches.
    text, project_count = re.subn(
        r"(?m)^PROJECT_NAME\s*=.*$", f"PROJECT_NAME           = {name_value}", text
    )
    # Replace the unique input assignment with the ordered declared source roots.
    text, input_count = re.subn(
        r"(?m)^INPUT\s*=.*$", f"INPUT                  = {input_value}", text
    )
    # Both assignments must have exactly one owner in the canonical template.
    if project_count != 1 or input_count != 1:
        # Identify the malformed package artifact without guessing a replacement location.
        detail = "canonical Doxyfile lacks unique PROJECT_NAME or INPUT assignments"
        # Refuse specialization because partial replacement would publish a misleading gate.
        raise MigrationError(detail)
    # Encode the specialized configuration without changing any other template bytes.
    return text.encode("utf-8")


def _artifact(path: Path, desired: bytes) -> ArtifactChange:
    """Capture the current bytes that guard one later write.

    @param path confined artifact path
    @param desired desired bytes when the artifact is absent
    @return no-op for an existing artifact, otherwise a creation change
    @par Effects Reads existing artifact bytes when the destination is already a file.
    """
    # Capture each existing byte exactly; None distinguishes an absent destination.
    before = path.read_bytes() if path.is_file() else None
    # Preserve an existing artifact byte-for-byte and create only when it was absent.
    return ArtifactChange(path, before, desired if before is None else before)


def _migration_inputs(
    root: Path,
    document: Mapping[str, object],
    diagnostics: list[Diagnostic],
) -> MigrationInputs:
    """Validate v4 structural facts and resolve v5 artifact paths.

    @param root governed repository root
    @param document decoded project mapping whose keys name tables and whose values are
        decoded TOML values; key iteration order is deliberately unused
    @param diagnostics mutable diagnostic elements retained in discovery order
    @return structural migration inputs, including absent paths after refusals
    """
    # Select the one v4 discipline table that owns every structural input.
    discipline = _table(document, "tool", "agent-discipline")
    # Preserve missing required field names in lexical order for deterministic diagnostics.
    missing = sorted(V4_FIELDS - set(discipline))
    # An incomplete v4 declaration cannot establish a safe v5 migration base.
    if missing:
        # Accumulate the structural refusal while continuing to discover independent defects.
        diagnostics.append(Diagnostic(
            "MIGRATE-V5-001_NOT_V4",
            "error",
            "the v4 declaration is incomplete; missing " + ", ".join(missing),
        ))
    # Parse source roots independently so their own shape defect is reported once.
    try:
        # Hold each normalized production-root element in declaration order.
        source_roots = _source_roots(discipline)
    # Convert the typed parse refusal into the ordered diagnostic channel.
    except MigrationError as problem:
        # Append the exact v4 shape failure after the missing-field census.
        diagnostics.append(Diagnostic("MIGRATE-V5-001_NOT_V4", "error", str(problem)))
        # Use an empty ordered sequence with no root elements so later planning is inert.
        source_roots = ()
    # Validate every production-root element in its declaration order.
    for index, source_root in enumerate(source_roots):
        # Resolve only for confinement validation; the original POSIX spelling remains canonical.
        _path, source_problem = _confined(
            root, source_root.as_posix(), f"source_roots[{index}]"
        )
        # Accumulate each unsafe root rather than hiding later independent path defects.
        if source_problem is not None:
            # Retain diagnostic order aligned with the source-root declaration.
            diagnostics.append(source_problem)

    # Default a missing model declaration to the canonical local artifact spelling.
    raw_model = discipline.get("documentation_model", "documentation-model.json")
    # Retain the exact scalar spelling that will be written into the declaration.
    model_spelling = str(raw_model)
    # Resolve the model destination and its mutually exclusive confinement diagnostic.
    model_path, model_problem = _confined(root, raw_model, "documentation_model")
    # Add an unsafe model path to the shared ordered refusal sequence.
    if model_problem is not None:
        diagnostics.append(model_problem)
    # Read the optional gate table without accepting a scalar impostor.
    gate = _table(document, "tool", "agent-discipline-gate")
    # Default a missing Doxyfile field to the canonical repository-root spelling.
    raw_doxyfile = gate.get("doxyfile", "Doxyfile")
    # Retain the declaration spelling separately from its confined absolute destination.
    doxyfile_spelling = str(raw_doxyfile)
    # Resolve the Doxyfile destination and its mutually exclusive confinement diagnostic.
    doxyfile_path, doxyfile_problem = _confined(root, raw_doxyfile, "doxyfile")
    # Add an unsafe Doxyfile path after earlier structural diagnostics.
    if doxyfile_problem is not None:
        diagnostics.append(doxyfile_problem)
    # Freeze all ordered roots, spellings, and validated optional destinations for rendering.
    return MigrationInputs(
        source_roots,
        model_spelling,
        model_path,
        doxyfile_spelling,
        doxyfile_path,
    )


def _render_project(text: str, inputs: MigrationInputs) -> str:
    """Render the three mechanically decidable v5 declaration fields.

    @param text complete v4 project text
    @param inputs validated migration inputs
    @return project text selecting Doxygen and both local artifacts
    """
    # Select Doxygen first in the main discipline table while preserving unrelated bytes.
    rendered = _set_scalar(text, "tool.agent-discipline", "doc_engine", '"doxygen"')
    # Attach the confined project-owned model using its retained relative spelling.
    rendered = _set_scalar(
        rendered,
        "tool.agent-discipline",
        "documentation_model",
        json.dumps(inputs.model_spelling),
    )
    # Point the project gate at the confined Doxyfile and return the complete declaration.
    return _set_scalar(
        rendered,
        "tool.agent-discipline-gate",
        "doxyfile",
        json.dumps(inputs.doxyfile_spelling),
    )


def _plan_artifacts(
    root: Path,
    document: Mapping[str, object],
    inputs: MigrationInputs,
    diagnostics: list[Diagnostic],
) -> tuple[ArtifactChange, ...]:
    """Plan missing model and Doxyfile artifacts without replacing project bytes.

    @param root governed repository root
    @param document decoded project mapping whose keys name tables and whose values are
        decoded TOML values; key iteration order is deliberately unused
    @param inputs validated paths and production roots
    @param diagnostics mutable diagnostic elements retained in discovery order
    @return artifact plans in publication order
    @par Effects Reads repository paths, existing artifacts, and the canonical package Doxyfile.
    """
    # Accumulate each artifact-change element in required model-then-Doxyfile order.
    artifacts: list[ArtifactChange] = []
    # A valid non-empty root set and confined model destination permit model planning.
    if inputs.source_roots and inputs.model_path is not None:
        # Derive ordered scopes and ordered paths that still need explicit ownership review.
        scopes, uncovered = _scope_payload(root, document, inputs.source_roots)
        # Preserve an existing model or plan the deterministic minimal starter artifact.
        artifacts.append(_artifact(inputs.model_path, _model_bytes(scopes)))
        # Uncovered repository Python requires a human ownership classification.
        if uncovered:
            # Append one warning whose elements retain deterministic repository path order.
            diagnostics.append(Diagnostic(
                "MIGRATE-V5-004_SCOPE_REVIEW",
                "warning",
                "classify these Python paths as governed, generated, or foreign in the model: "
                + ", ".join(uncovered),
            ))
    # A valid non-empty root set and confined Doxyfile destination permit gate planning.
    if inputs.source_roots and inputs.doxyfile_path is not None:
        # Read distribution identity from the project table, falling back to repository name.
        project = _table(document, "project")
        # Normalize the selected identity to text for deterministic Doxygen rendering.
        project_name = str(project.get("name", root.name))
        # Specialize the package template with the name and ordered production-root elements.
        desired = _doxyfile_bytes(project_name, inputs.source_roots)
        # Preserve an existing gate artifact or plan creation of the specialized bytes.
        artifacts.append(_artifact(inputs.doxyfile_path, desired))
        # Existing project policy requires manual comparison rather than silent replacement.
        if inputs.doxyfile_path.is_file():
            # Record the exact retained artifact and the capabilities its owner must verify.
            diagnostics.append(Diagnostic(
                "MIGRATE-V5-005_DOXYFILE_REVIEW",
                "warning",
                "the existing Doxyfile was preserved; compare it with .agent/enforce/Doxyfile "
                "and require the declared source roots, warnings-as-errors, and relation output",
            ))
    # Freeze the ordered artifact elements before the plan becomes externally visible.
    return tuple(artifacts)


def plan(root: Path) -> MigrationPlan:
    """Build a deterministic migration without modifying the repository.

    @param root governed v4 repository root
    @return complete project and auxiliary-artifact plan
    @par Effects Reads the project declaration, repository inventory, package Doxyfile, and
        any pre-existing target artifacts without modifying them.
    """
    # Canonicalize the repository boundary once for every later confinement comparison.
    root = root.resolve()
    # Fix the project declaration location at the governed repository root.
    project_file = root / "pyproject.toml"
    # Accumulate each diagnostic element in deterministic discovery order.
    diagnostics: list[Diagnostic] = []
    # Decode the declaration while preserving its exact pre-migration bytes.
    try:
        # Capture exact bytes, decoded text, and its key/value TOML mapping as one read step.
        before = project_file.read_bytes()
        text = before.decode("utf-8")
        document = tomllib.loads(text)
    # Collapse access, encoding, and syntax failures into the one non-v4 refusal channel.
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as problem:
        # Capture the concrete failed read or decode operation for adopter remediation.
        diagnostic = Diagnostic(
            "MIGRATE-V5-001_NOT_V4", "error", f"cannot read pyproject.toml: {problem}"
        )
        # Return a blocked plan with empty ordered artifacts and no invented declaration bytes.
        return MigrationPlan(root, project_file, b"", b"", (), (diagnostic,))
    # Resolve validated structural inputs while accumulating independent declaration defects.
    inputs = _migration_inputs(root, document, diagnostics)
    # Render only the three bounded scalar edits over the exact decoded source.
    try:
        # Hold the complete post-migration declaration text without publishing it.
        after_text = _render_project(text, inputs)
    # Preserve the original declaration when bounded editing finds structural ambiguity.
    except MigrationError as problem:
        # Append the exact edit refusal after input-validation diagnostics.
        diagnostics.append(Diagnostic("MIGRATE-V5-001_NOT_V4", "error", str(problem)))
        # Retain original text so a blocked preview never proposes a partial declaration edit.
        after_text = text
    # Plan model and Doxyfile artifacts from validated inputs without changing the repository.
    artifacts = _plan_artifacts(root, document, inputs, diagnostics)
    # Re-read the decoded discipline table to decide whether authorship guidance is needed.
    discipline = _table(document, "tool", "agent-discipline")
    # True means both v5 structural declarations pre-existed; false means semantic follow-up.
    already_structural_v5 = (
        discipline.get("doc_engine") == "doxygen" and "documentation_model" in discipline
    )
    # A structurally migrated v4 project still needs explicit semantic authoring and review.
    if not already_structural_v5:
        # Name the non-mechanical work and the exact aggregate command that inventories it.
        diagnostics.append(Diagnostic(
            "MIGRATE-V5-003_AUTHORING_REQUIRED",
            "warning",
            "the structural migration cannot invent semantic comments or project vocabulary; "
            "run `python -m checks src tests --root . --project pyproject.toml` and "
            "author every reported v5 obligation",
        ))
    # Freeze declaration bytes, ordered artifacts, and ordered diagnostics as one guarded plan.
    return MigrationPlan(
        root,
        project_file,
        before,
        after_text.encode("utf-8"),
        artifacts,
        tuple(diagnostics),
    )


def _diff(path: Path, before: bytes | None, after: bytes, root: Path) -> list[str]:
    """Render one artifact as a complete unified diff.

    @param path artifact path
    @param before previous bytes, or None for a new file
    @param after desired bytes
    @param root governed repository root used for display
    @return diff lines retaining their newline terminators
    """
    # Present the artifact by its repository-relative POSIX path on every host.
    relative = path.relative_to(root).as_posix()
    # Represent prior text as ordered newline-retaining elements, or no elements if absent.
    old = [] if before is None else before.decode("utf-8").splitlines(keepends=True)
    # Represent desired text as ordered newline-retaining elements for exact unified output.
    new = after.decode("utf-8").splitlines(keepends=True)
    # Materialize the ordered unified-diff line elements for later terminal composition.
    return list(difflib.unified_diff(old, new, fromfile=relative, tofile=relative))


def preview(migration: MigrationPlan) -> str:
    """Render diagnostics and complete diffs without changing the repository.

    @param migration immutable migration plan
    @return terminal-ready preview
    """
    # Render each diagnostic as one ordered terminal line before any byte diffs.
    lines = [
        f"{item.severity.upper()} {item.diagnostic_id}: {item.detail}"
        for item in migration.diagnostics
    ]
    # Include the project diff first when its desired bytes differ from the guarded input.
    if migration.before != migration.after:
        # Extend output with each unified-diff line in declaration-first order.
        lines.extend(_diff(
            migration.project_file,
            migration.before,
            migration.after,
            migration.root,
        ))
    # Append changed auxiliary artifacts in their deterministic publication order.
    for artifact in migration.artifacts:
        # Existing byte-identical artifacts contribute no redundant preview section.
        if artifact.changed:
            # Extend output with every ordered diff line for this changed artifact.
            lines.extend(_diff(artifact.path, artifact.before, artifact.after, migration.root))
    # A byte-identical, diagnostic-only v5 plan receives an explicit no-change outcome.
    if not migration.changed:
        # Append the terminal status after any warnings so neither is hidden.
        lines.append("already v5; no changes")
    # Remove retained diff terminators, join ordered lines once, and guarantee one final newline.
    return "\n".join(line.rstrip("\n") for line in lines) + "\n"


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace one file through a same-directory temporary file.

    @param path destination path
    @param content exact bytes to publish
    @par Effects Creates missing parent directories, writes and synchronizes one temporary
        file, replaces the destination as one namespace update with respect to concurrent
        readers, and removes the private temporary directory afterward.
    """
    # Ensure the confined destination's parent hierarchy exists before temporary allocation.
    path.parent.mkdir(parents=True, exist_ok=True)
    # Bound cleanup to one private same-directory workspace on the destination filesystem.
    with tempfile.TemporaryDirectory(prefix=f".{path.name}.v5-", dir=path.parent) as workspace:
        # Name the sole temporary artifact inside the cleanup-owned workspace.
        temporary = Path(workspace) / path.name
        # Open a new binary stream whose context owns descriptor closure.
        with temporary.open("xb") as stream:
            # Publish the exact planned bytes into the private temporary artifact.
            stream.write(content)
            # Push Python's userspace buffer before requesting operating-system synchronization.
            stream.flush()
            # Synchronize the complete temporary contents before making the destination visible.
            os.fsync(stream.fileno())
        # Replace the destination as one namespace update with respect to concurrent readers.
        temporary.replace(path)


def apply(migration: MigrationPlan) -> None:
    """Apply one still-current, non-blocked plan with the declaration last.

    @param migration preview returned by `plan`
    @throws MigrationError for blockers or repository changes since planning
    @par Effects Reads every guarded destination, creates or replaces changed auxiliary
        artifacts in plan order, then replaces the project declaration last.
    """
    # A true blocked state means application is forbidden; false permits freshness checks.
    if migration.blocked:
        # Localize the refusal without attempting any destination read or write.
        detail = "migration has blocking diagnostics"
        # Stop before side effects because the preview already contains exact blocker details.
        raise MigrationError(detail)
    # Read the declaration's current bytes, or None if it disappeared after planning.
    current_project = (
        migration.project_file.read_bytes() if migration.project_file.is_file() else None
    )
    # Refuse when the guarded declaration snapshot no longer matches repository state.
    if current_project != migration.before:
        # Name the stale declaration independently from any auxiliary artifact guard.
        detail = "pyproject.toml changed after the migration was planned"
        # Preserve concurrent edits by refusing the entire application transaction.
        raise MigrationError(detail)
    # Validate every auxiliary artifact against its expected prior bytes in plan order.
    for artifact in migration.artifacts:
        # Capture current bytes, with None retaining the absent-destination state.
        current = artifact.path.read_bytes() if artifact.path.is_file() else None
        # Any mismatch means repository state changed after the preview was produced.
        if current != artifact.before:
            # Identify the exact stale artifact without exposing an unguarded write path.
            detail = f"{artifact.path.name} changed after planning"
            # Refuse before publishing any planned artifact so the transaction remains intact.
            raise MigrationError(detail)
    # Publish changed auxiliary artifacts in deterministic plan order before their declaration.
    for artifact in migration.artifacts:
        # Byte-identical artifacts require no write and retain their original metadata.
        if artifact.changed:
            # Publish the exact desired bytes as one replacement relative to concurrent readers.
            _atomic_write(artifact.path, artifact.after)
    # Publish the declaration last so it never points at artifacts that have not been created.
    if migration.before != migration.after:
        # Replace the declaration as one namespace update with respect to concurrent readers.
        _atomic_write(migration.project_file, migration.after)


def main(argv: Sequence[str] | None = None) -> int:
    """Preview or apply one v4-to-v5 documentation migration.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return zero after preview/application, two after a blocking diagnostic
    @par Effects Reads the governed project and package templates, writes the preview to
        standard output, and with `--apply` publishes the guarded migration artifacts.
    """
    # Define the stable command surface independently from repository project parsing.
    parser = argparse.ArgumentParser(
        description="Preview or apply the conservative v4-to-v5 documentation migration."
    )
    # Accept one repository boundary, defaulting to the caller's current working directory.
    parser.add_argument("--root", type=Path, default=Path.cwd())
    # Keep preview as the default and require an explicit flag for repository mutation.
    parser.add_argument("--apply", action="store_true")
    # Parse either the supplied sequence elements in order or the process argument vector.
    arguments = parser.parse_args(argv)
    # Build one immutable guarded plan before producing output or applying changes.
    migration = plan(arguments.root)
    # Publish the complete deterministic preview before any possible repository mutation.
    print(preview(migration), end="")
    # A true blocked state returns the stable refusal status; false may preview or apply.
    if migration.blocked:
        # Signal a structural refusal without attempting any planned write.
        return EXIT_BLOCKED
    # Apply only when the caller explicitly requested mutation after reviewing the preview.
    if arguments.apply:
        # Recheck every guard and publish auxiliary artifacts before the declaration.
        apply(migration)
        # Confirm the completed mutation on standard output for scripts and developers.
        print("applied v5 project declaration and missing canonical documentation artifacts")
    # Both a successful preview and a successful application share the stable zero status.
    return EXIT_OK


# Execute the command boundary only when this module is launched as the program.
if __name__ == "__main__":
    # Translate the command result into the process exit status at the sole script boundary.
    raise SystemExit(main())
