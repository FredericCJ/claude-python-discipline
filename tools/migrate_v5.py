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

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable successful and refused process outcomes.
EXIT_OK: Final = 0
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
## Table header and scalar assignment shapes used for bounded text edits.
TABLE_HEADER: Final = re.compile(r"^\s*\[\s*([^\]]+?)\s*\]\s*(?:#.*)?$")
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

    diagnostic_id: str
    severity: Literal["error", "warning"]
    detail: str


@dataclass(frozen=True, slots=True)
class ArtifactChange:
    """One auxiliary artifact in the migration transaction.

    @param path confined artifact path
    @param before exact previous bytes, or None when absent
    @param after exact desired bytes
    """

    path: Path
    before: bytes | None
    after: bytes

    @property
    def changed(self) -> bool:
        """Whether applying the artifact would change repository state.

        @return true for a new artifact or different bytes
        """
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

    root: Path
    project_file: Path
    before: bytes
    after: bytes
    artifacts: tuple[ArtifactChange, ...]
    diagnostics: tuple[Diagnostic, ...]

    @property
    def blocked(self) -> bool:
        """Whether any diagnostic forbids application.

        @return true when at least one error exists
        """
        return any(item.severity == "error" for item in self.diagnostics)

    @property
    def changed(self) -> bool:
        """Whether the project declaration or an auxiliary artifact differs.

        @return true when application has at least one write
        """
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

    source_roots: tuple[PurePosixPath, ...]
    model_spelling: str
    model_path: Path | None
    doxyfile_spelling: str
    doxyfile_path: Path | None


def _table(document: Mapping[str, object], *names: str) -> Mapping[str, object]:
    """Walk decoded TOML tables without accepting scalar impostors.

    @param document decoded TOML document
    @param names table path segments
    @return requested table, or an empty mapping when absent or malformed
    """
    current: object = document
    for name in names:
        if not isinstance(current, dict):
            return {}
        current = current.get(name, {})
    return current if isinstance(current, dict) else {}


def _newline(text: str) -> str:
    """Preserve the project declaration's existing line-ending convention.

    @param text complete declaration text
    @return CRLF when present, otherwise LF
    """
    return "\r\n" if "\r\n" in text else "\n"


def _table_span(lines: Sequence[str], table: str) -> tuple[int, int] | None:
    """Locate one exact TOML table by line indexes.

    @param lines declaration lines retaining newline bytes
    @param table exact dotted table name
    @return half-open body span, or None when the table is absent
    """
    start: int | None = None
    for index, line in enumerate(lines):
        matched = TABLE_HEADER.match(line.rstrip("\r\n"))
        if matched is None:
            continue
        if start is not None:
            return start, index
        if matched.group(1).strip() == table:
            start = index + 1
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
    newline = _newline(text)
    lines = text.splitlines(keepends=True)
    span = _table_span(lines, table)
    if span is None:
        if text and not text.endswith(("\n", "\r")):
            text += newline
        separator = "" if not text or text.endswith(newline * 2) else newline
        return text + separator + f"[{table}]{newline}{key} = {rendered}{newline}"
    start, end = span
    matches = [
        index
        for index in range(start, end)
        if (assignment := SCALAR_ASSIGNMENT.match(lines[index])) is not None
        and assignment.group("key") == key
    ]
    if len(matches) > 1:
        detail = f"[{table}] contains duplicate {key!r} assignments"
        raise MigrationError(detail)
    replacement = f"{key} = {rendered}{newline}"
    if matches:
        lines[matches[0]] = replacement
    else:
        insertion = end
        while insertion > start and not lines[insertion - 1].strip():
            insertion -= 1
        lines.insert(insertion, replacement)
    return "".join(lines)


def _confined(root: Path, raw: object, field: str) -> tuple[Path | None, Diagnostic | None]:
    """Resolve one non-root repository-relative path without permitting escape.

    @param root governed repository root
    @param raw decoded path spelling
    @param field owning declaration field
    @return resolved path and no diagnostic, or no path and a blocking diagnostic
    """
    if not isinstance(raw, str) or not raw.strip():
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", f"{field} is empty")
    candidate = PurePosixPath(raw.replace("\\", "/"))
    if candidate.is_absolute() or PureWindowsPath(raw).drive or ".." in candidate.parts:
        detail = f"{field}={raw!r} must be a non-root path inside the repository"
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", detail)
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    if not parts:
        detail = f"{field} may not name the repository root"
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", detail)
    resolved = (root / Path(*parts)).resolve()
    try:
        resolved.relative_to(root.resolve())
    except ValueError:
        detail = f"{field}={raw!r} resolves outside the repository"
        return None, Diagnostic("MIGRATE-V5-002_UNSAFE_PATH", "error", detail)
    return resolved, None


def _source_roots(table: Mapping[str, object]) -> tuple[PurePosixPath, ...]:
    """Read the already-required v4 production roots.

    @param table decoded discipline main table
    @return normalized source-root paths
    @throws MigrationError when the v4 field is not a non-empty string array
    """
    raw = table.get("source_roots")
    if not isinstance(raw, list) or not raw or not all(isinstance(item, str) for item in raw):
        detail = "source_roots must be a non-empty array of strings"
        raise MigrationError(detail)
    roots = tuple(PurePosixPath(str(item).replace("\\", "/")) for item in raw)
    if len(set(roots)) != len(roots):
        detail = "source_roots contains duplicates"
        raise MigrationError(detail)
    return roots


def _scope_payload(
    root: Path,
    document: Mapping[str, object],
    source_roots: Sequence[PurePosixPath],
) -> tuple[list[dict[str, str]], tuple[str, ...]]:
    """Derive only conventional, mechanically attributable documentation scopes.

    @param root governed repository root
    @param document decoded project configuration
    @param source_roots declared production roots
    @return scope records and Python paths still requiring ownership review
    """
    scopes: list[dict[str, str]] = [
        {"path": path.as_posix(), "kind": "production", "ownership": "governed"}
        for path in source_roots
    ]
    pytest_table = _table(document, "tool", "pytest", "ini_options")
    raw_testpaths = pytest_table.get("testpaths", [])
    testpaths = (
        tuple(PurePosixPath(str(item).replace("\\", "/")) for item in raw_testpaths)
        if isinstance(raw_testpaths, list)
        else ()
    )
    if not testpaths and (root / "tests").is_dir():
        testpaths = (PurePosixPath("tests"),)
    candidates = [
        (path, "tests") for path in testpaths
    ]
    if (root / "tools").is_dir():
        candidates.append((PurePosixPath("tools"), "maintenance"))
    candidates.extend(
        (PurePosixPath(path.name), "maintenance") for path in sorted(root.glob("*.py"))
    )
    for scope_path, kind in candidates:
        if any(
            scope_path == existing or scope_path.is_relative_to(existing)
            for existing in source_roots
        ):
            continue
        if any(record["path"] == scope_path.as_posix() for record in scopes):
            continue
        scopes.append(
            {"path": scope_path.as_posix(), "kind": kind, "ownership": "governed"}
        )

    covered = tuple(PurePosixPath(record["path"]) for record in scopes)
    uncovered: list[str] = []
    for source_file in sorted(root.rglob("*.py")):
        relative = PurePosixPath(source_file.relative_to(root).as_posix())
        if IGNORED_DISCOVERY_PARTS & set(relative.parts):
            continue
        if not any(relative == scope or relative.is_relative_to(scope) for scope in covered):
            uncovered.append(relative.as_posix())
    return scopes, tuple(uncovered)


def _model_bytes(scopes: Sequence[Mapping[str, str]]) -> bytes:
    """Render a strict starter model without inventing project vocabulary.

    @param scopes mechanically attributable repository scopes
    @return canonical UTF-8 JSON bytes
    """
    payload = {
        "schema_version": 1,
        "engine": "doxygen",
        "scopes": list(scopes),
        "controlled_abbreviations": [],
        "identifier_grammars": [],
        "generated_names": {"markers": ["generated", "derived"], "mappings": {}},
        "semantic_properties": [],
    }
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _doxyfile_bytes(project_name: str, source_roots: Sequence[PurePosixPath]) -> bytes:
    """Specialize the shipped canonical Doxygen posture for one project.

    @param project_name declared distribution name
    @param source_roots exact production roots consumed by the project gate
    @return canonical UTF-8 configuration bytes
    @throws MigrationError when the package template is absent or malformed
    """
    try:
        text = DOXYGEN_TEMPLATE.read_text(encoding="utf-8")
    except OSError as problem:
        detail = f"cannot read canonical Doxyfile: {problem}"
        raise MigrationError(detail) from problem
    input_value = " ".join(json.dumps(path.as_posix()) for path in source_roots)
    name_value = json.dumps(project_name)
    text, project_count = re.subn(
        r"(?m)^PROJECT_NAME\s*=.*$", f"PROJECT_NAME           = {name_value}", text
    )
    text, input_count = re.subn(
        r"(?m)^INPUT\s*=.*$", f"INPUT                  = {input_value}", text
    )
    if project_count != 1 or input_count != 1:
        detail = "canonical Doxyfile lacks unique PROJECT_NAME or INPUT assignments"
        raise MigrationError(detail)
    return text.encode("utf-8")


def _artifact(path: Path, desired: bytes) -> ArtifactChange:
    """Capture the current bytes that guard one later write.

    @param path confined artifact path
    @param desired desired bytes when the artifact is absent
    @return no-op for an existing artifact, otherwise a creation change
    """
    before = path.read_bytes() if path.is_file() else None
    return ArtifactChange(path, before, desired if before is None else before)


def _migration_inputs(
    root: Path,
    document: Mapping[str, object],
    diagnostics: list[Diagnostic],
) -> MigrationInputs:
    """Validate v4 structural facts and resolve v5 artifact paths.

    @param root governed repository root
    @param document decoded project declaration
    @param diagnostics mutable stable diagnostic sequence
    @return structural migration inputs, including absent paths after refusals
    """
    discipline = _table(document, "tool", "agent-discipline")
    missing = sorted(V4_FIELDS - set(discipline))
    if missing:
        diagnostics.append(Diagnostic(
            "MIGRATE-V5-001_NOT_V4",
            "error",
            "the v4 declaration is incomplete; missing " + ", ".join(missing),
        ))
    try:
        source_roots = _source_roots(discipline)
    except MigrationError as problem:
        diagnostics.append(Diagnostic("MIGRATE-V5-001_NOT_V4", "error", str(problem)))
        source_roots = ()
    for index, source_root in enumerate(source_roots):
        _path, source_problem = _confined(
            root, source_root.as_posix(), f"source_roots[{index}]"
        )
        if source_problem is not None:
            diagnostics.append(source_problem)

    raw_model = discipline.get("documentation_model", "documentation-model.json")
    model_spelling = str(raw_model)
    model_path, model_problem = _confined(root, raw_model, "documentation_model")
    if model_problem is not None:
        diagnostics.append(model_problem)
    gate = _table(document, "tool", "agent-discipline-gate")
    raw_doxyfile = gate.get("doxyfile", "Doxyfile")
    doxyfile_spelling = str(raw_doxyfile)
    doxyfile_path, doxyfile_problem = _confined(root, raw_doxyfile, "doxyfile")
    if doxyfile_problem is not None:
        diagnostics.append(doxyfile_problem)
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
    rendered = _set_scalar(text, "tool.agent-discipline", "doc_engine", '"doxygen"')
    rendered = _set_scalar(
        rendered,
        "tool.agent-discipline",
        "documentation_model",
        json.dumps(inputs.model_spelling),
    )
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
    @param document decoded project declaration
    @param inputs validated paths and production roots
    @param diagnostics mutable stable diagnostic sequence
    @return artifact plans in publication order
    """
    artifacts: list[ArtifactChange] = []
    if inputs.source_roots and inputs.model_path is not None:
        scopes, uncovered = _scope_payload(root, document, inputs.source_roots)
        artifacts.append(_artifact(inputs.model_path, _model_bytes(scopes)))
        if uncovered:
            diagnostics.append(Diagnostic(
                "MIGRATE-V5-004_SCOPE_REVIEW",
                "warning",
                "classify these Python paths as governed, generated, or foreign in the model: "
                + ", ".join(uncovered),
            ))
    if inputs.source_roots and inputs.doxyfile_path is not None:
        project = _table(document, "project")
        project_name = str(project.get("name", root.name))
        desired = _doxyfile_bytes(project_name, inputs.source_roots)
        artifacts.append(_artifact(inputs.doxyfile_path, desired))
        if inputs.doxyfile_path.is_file():
            diagnostics.append(Diagnostic(
                "MIGRATE-V5-005_DOXYFILE_REVIEW",
                "warning",
                "the existing Doxyfile was preserved; compare it with .agent/enforce/Doxyfile "
                "and require the declared source roots, warnings-as-errors, and relation output",
            ))
    return tuple(artifacts)


def plan(root: Path) -> MigrationPlan:
    """Build a deterministic migration without modifying the repository.

    @param root governed v4 repository root
    @return complete project and auxiliary-artifact plan
    """
    root = root.resolve()
    project_file = root / "pyproject.toml"
    diagnostics: list[Diagnostic] = []
    try:
        before = project_file.read_bytes()
        text = before.decode("utf-8")
        document = tomllib.loads(text)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as problem:
        diagnostic = Diagnostic(
            "MIGRATE-V5-001_NOT_V4", "error", f"cannot read pyproject.toml: {problem}"
        )
        return MigrationPlan(root, project_file, b"", b"", (), (diagnostic,))
    inputs = _migration_inputs(root, document, diagnostics)
    try:
        after_text = _render_project(text, inputs)
    except MigrationError as problem:
        diagnostics.append(Diagnostic("MIGRATE-V5-001_NOT_V4", "error", str(problem)))
        after_text = text
    artifacts = _plan_artifacts(root, document, inputs, diagnostics)
    discipline = _table(document, "tool", "agent-discipline")
    if discipline.get("doc_engine") != "doxygen" or "documentation_model" not in discipline:
        diagnostics.append(Diagnostic(
            "MIGRATE-V5-003_AUTHORING_REQUIRED",
            "warning",
            "the structural migration cannot invent semantic comments or project vocabulary; "
            "run `python -m checks src tests --root . --project pyproject.toml` and "
            "author every reported v5 obligation",
        ))
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
    relative = path.relative_to(root).as_posix()
    old = [] if before is None else before.decode("utf-8").splitlines(keepends=True)
    new = after.decode("utf-8").splitlines(keepends=True)
    return list(difflib.unified_diff(old, new, fromfile=relative, tofile=relative))


def preview(migration: MigrationPlan) -> str:
    """Render diagnostics and complete diffs without changing the repository.

    @param migration immutable migration plan
    @return terminal-ready preview
    """
    lines = [
        f"{item.severity.upper()} {item.diagnostic_id}: {item.detail}"
        for item in migration.diagnostics
    ]
    if migration.before != migration.after:
        lines.extend(_diff(
            migration.project_file,
            migration.before,
            migration.after,
            migration.root,
        ))
    for artifact in migration.artifacts:
        if artifact.changed:
            lines.extend(_diff(artifact.path, artifact.before, artifact.after, migration.root))
    if not migration.changed:
        lines.append("already v5; no changes")
    return "\n".join(line.rstrip("\n") for line in lines) + "\n"


def _atomic_write(path: Path, content: bytes) -> None:
    """Replace one file through a same-directory temporary file.

    @param path destination path
    @param content exact bytes to publish
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.v5-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply(migration: MigrationPlan) -> None:
    """Apply one still-current, non-blocked plan with the declaration last.

    @param migration preview returned by `plan`
    @throws MigrationError for blockers or repository changes since planning
    """
    if migration.blocked:
        detail = "migration has blocking diagnostics"
        raise MigrationError(detail)
    current_project = (
        migration.project_file.read_bytes() if migration.project_file.is_file() else None
    )
    if current_project != migration.before:
        detail = "pyproject.toml changed after the migration was planned"
        raise MigrationError(detail)
    for artifact in migration.artifacts:
        current = artifact.path.read_bytes() if artifact.path.is_file() else None
        if current != artifact.before:
            detail = f"{artifact.path.name} changed after planning"
            raise MigrationError(detail)
    for artifact in migration.artifacts:
        if artifact.changed:
            _atomic_write(artifact.path, artifact.after)
    if migration.before != migration.after:
        _atomic_write(migration.project_file, migration.after)


def main(argv: Sequence[str] | None = None) -> int:
    """Preview or apply one v4-to-v5 documentation migration.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return zero after preview/application, two after a blocking diagnostic
    """
    parser = argparse.ArgumentParser(
        description="Preview or apply the conservative v4-to-v5 documentation migration."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--apply", action="store_true")
    arguments = parser.parse_args(argv)
    migration = plan(arguments.root)
    print(preview(migration), end="")
    if migration.blocked:
        return EXIT_BLOCKED
    if arguments.apply:
        apply(migration)
        print("applied v5 project declaration and missing canonical documentation artifacts")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
