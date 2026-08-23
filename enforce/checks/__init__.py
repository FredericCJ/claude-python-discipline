"""AST checks for discipline rules no off-the-shelf linter enforces.

Each module here implements one `[check:<name>]` mechanism named by a rule in
`discipline/law/`. Run one directly::

    python -m checks.domain_purity src/

Or all of them::

    python -m checks src/

Every check emits findings carrying the rule id, so the output can be acted on
without consulting the rules first -- the same property `law/DIAG` requires of
program errors. Every check has a proof-of-failure test in `test_checks.py`; a
check never observed to fail has not been shown to check anything (`FLOW-007`).
"""

from __future__ import annotations

import argparse
import ast
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import project

# Import annotation-only collection protocols without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation, at a source location."""

    ## The rule the violation is against, so the finding can be acted on without
    ## looking anything up first.
    rule_id: str
    ## The file the violation was found in, as it was handed to the check.
    path: Path
    ## Where in that file, 1-indexed to match every editor and traceback.
    line: int
    ## What is wrong, phrased to stand alone without the rule's text beside it.
    message: str
    ## What to do instead, citing the rule that says so where one applies.
    remediation: str
    ## Stable mechanism-specific diagnostic. The rule id states the obligation;
    ## this id distinguishes independently actionable failure predicates under it.
    diagnostic_id: str | None = None

    def render(self, root: Path | None = None) -> str:
        """Format the finding as a diagnostic line with its remedy beneath.

        A path that does not lie under `root` is shown in full rather than
        refused; a display convenience must not turn into a failure mode.

        @param root a directory to shorten the path against, or None to leave it
        @return two lines, the first in the `path:line: RULE message` form editors
            and CI logs already know how to jump from
        """
        # Start with the complete supplied path so shortening remains optional.
        shown = self.path
        # Attempt shortening only when the caller supplied a display root.
        if root is not None:
            # Ignore an unconfined display path while attempting a relative spelling.
            with suppress(ValueError):
                # Replace the display path only when it lies beneath the requested root.
                shown = self.path.relative_to(root)
        # Select a stable rule-only or rule-plus-mechanism diagnostic identity.
        identity = (
            self.rule_id if self.diagnostic_id is None
            else f"{self.rule_id}/{self.diagnostic_id}"
        )
        # Render the primary diagnostic and concrete remediation as two adjacent lines.
        return (
            f"{shown.as_posix()}:{self.line}: {identity} {self.message}\n"
            f"    -> {self.remediation}"
        )


class Check(ABC):
    """One mechanism, applied to a set of files.

    A subclass declares which rules it decides and implements `run`. Two walkers
    are provided and cover everything so far: `ModuleCheck` for a rule about
    Python, `TextCheck` for a rule whose subject is not Python at all.

    That second case is not an afterthought. `ALLOC-002` is about dispatch
    records, which are markdown; the five `law/LEARN` rules are about a JSONL
    ledger; `DEP-007` is about the provenance header on any generated file. A
    framework that could only parse Python would have left twenty-one rules
    unmechanizable for a reason that has nothing to do with the rules.
    """

    ## The `[check:<name>]` token the rules are tagged with, which is also the
    ## module this class lives in. The two must stay spelled the same, or a rule
    ## no longer names a command anyone can run.
    name: str
    ## Rule-id elements in deterministic summary order that this mechanism decides.
    rules: tuple[str, ...]

    ## What the project under examination says about its own conventions -- its
    ## layer vocabulary and its documentation engine. Set by `main` from the tree
    ## being checked; the default is in force when a check is constructed
    ## directly, which is how the proof-of-failure tests get canonical layers
    ## without writing a project file for every fixture.
    declaration: project.Declaration = project.DEFAULT

    @abstractmethod
    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Collect what this mechanism finds across every file under `paths`.

        @param paths file-or-directory elements in caller traversal order
        @return finding elements grouped by file in stable walk order
        """


class TextCheck(Check):
    """A mechanism whose subject is a file this repository does not parse.

    Reads each matching file as text and hands it to `visit_text`. A file that
    cannot be decoded is reported rather than skipped: a check that silently
    passes over what it cannot read is a check that passes.
    """

    ## File-suffix elements in deterministic matching order that this text check examines;
    ## the narrow sequence prevents incidental text from becoming a rule subject.
    suffixes: tuple[str, ...] = (".md",)

    @abstractmethod
    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for one file's contents.

        @param text the file's decoded contents
        @param path the file it was read from, for the finding's location
        @return finding elements in checker-defined order, one per violation
        """

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Read every matching file and collect what `visit_text` reports.

        @param paths file-or-directory elements in caller traversal order
        @return finding elements in stable file walk then checker order
        """
        # Accumulate finding elements in the same deterministic order as file traversal.
        findings: list[Finding] = []
        # Visit each matching file-path element in stable traversal order.
        for path in iter_files(paths, self.suffixes):
            # Decode one immutable source snapshot for the text-specific checker.
            try:
                # Read strict UTF-8 so undecodable inputs become explicit findings.
                text = path.read_text(encoding="utf-8")
            # Convert filesystem and decoding failures into the common finding channel.
            except (OSError, UnicodeDecodeError) as exc:
                # Append the localized unreadable-file diagnostic at the current walk position.
                findings.append(
                    Finding(
                        rule_id="CHECK-000", path=path, line=1,
                        message=f"could not read: {exc}",
                        remediation="No check can run on this file; fix or exclude it.",
                    )
                )
                # Advance because no text-specific visitor can inspect this file.
                continue
            # Extend the ordered aggregate with this file's visitor findings.
            findings.extend(self.visit_text(text, path))
        # Return every finding in stable file and visitor order.
        return findings


class ModuleCheck(Check):
    """A mechanism whose subject is Python source.

    A subclass implements `visit_module`; walking the tree, parsing and surviving
    a broken file are handled here so every check reports the same way.
    """

    @abstractmethod
    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for one parsed module.

        @param tree the module's syntax tree
        @param path the file it was parsed from, for the finding's location
        @param layer the architectural layer the path sits in, or 'unknown'
        @return finding elements in checker-defined order, one per violation
        """

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Collect what this mechanism finds across every file under `paths`.

        A file that will not parse becomes a CHECK-000 finding instead of an
        exception: one broken file must not hide the violations in the rest.

        @param paths file-or-directory elements in caller traversal order
        @return finding elements grouped by file in stable walk order
        """
        # Accumulate finding elements in the same deterministic order as Python-file traversal.
        findings: list[Finding] = []
        # Visit each Python file-path element in stable traversal order.
        for path in iter_python_files(paths):
            # Parse one immutable source snapshot for the AST-specific checker.
            try:
                # Build the syntax tree from strict UTF-8 source and preserve its filename.
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            # Convert syntax failures into the common finding channel.
            except SyntaxError as exc:
                # Append the localized parse diagnostic at the current walk position.
                findings.append(
                    Finding(
                        rule_id="CHECK-000",
                        path=path,
                        line=exc.lineno or 1,
                        message=f"could not parse: {exc.msg}",
                        remediation="Fix the syntax error; no check can run on this file.",
                    )
                )
                # Advance because no AST-specific visitor can inspect this module.
                continue
            # Extend the ordered aggregate with this module's layer-aware visitor findings.
            findings.extend(
                self.visit_module(tree, path, layer_of(path, self.declaration))
            )
        # Return every finding in stable file and visitor order.
        return findings


def iter_files(paths: Sequence[Path], suffixes: Sequence[str]) -> Iterator[Path]:
    """Every file under the given paths whose suffix matches, in stable order.

    A file named explicitly is yielded whatever its suffix: a caller pointing at
    one file has already said which file it means, and second-guessing that would
    make a check impossible to run on demand.

    @param paths file-or-directory elements in caller traversal order
    @param suffixes file-suffix elements in caller matching order
    @return each matching file element, with directory contents sorted
    """
    # Freeze the suffix elements in caller order for repeated membership checks.
    wanted = tuple(suffixes)
    # Expand each caller path element in the order supplied.
    for entry in paths:
        # An explicitly named file bypasses suffix filtering by contract.
        if entry.is_file():
            # Yield the exact explicit file at its caller-selected position.
            yield entry
        # Directory inputs contribute recursively sorted matching descendants.
        elif entry.is_dir():
            # Consider each descendant path element in lexical order.
            for path in sorted(entry.rglob("*")):
                # Yield only regular files whose suffix belongs to the requested set.
                if path.is_file() and path.suffix in wanted:
                    # Emit the matched descendant at its stable traversal position.
                    yield path


def iter_python_files(paths: Sequence[Path]) -> Iterator[Path]:
    """Every `.py` file under the given paths, in stable order.

    Order is fixed so two runs over the same tree produce the same output and a
    diff between them means something changed.

    @param paths file-or-directory elements in caller traversal order; others are skipped
    @return each Python-file element, with directory contents sorted
    """
    # Expand each caller path element in the order supplied.
    for entry in paths:
        # An explicit file contributes only when it is Python source.
        if entry.is_file() and entry.suffix == ".py":
            # Yield the exact explicit Python file at its caller-selected position.
            yield entry
        # Directory inputs contribute every recursively sorted Python descendant.
        elif entry.is_dir():
            # Delegate the stable ordered descendant sequence directly to the caller.
            yield from sorted(entry.rglob("*.py"))


## Canonical layer-name elements in architecture order, re-exported from ``project`` so
## segment matching and declaration validation cannot disagree.
LAYERS = project.CANONICAL_LAYERS


def layer_of(path: Path, declaration: project.Declaration = project.DEFAULT) -> str:
    """Which architectural layer a file belongs to, or 'unknown'.

    The first matching segment wins, reading from the root, so
    `adapters/domain/rules.py` is judged `adapters` and never `domain`. Nesting a
    layer inside another therefore hides the inner one from every layer-scoped
    check.

    A project that names its layers differently maps them in its declaration, and
    is then checked rather than skipped. Before that existed, a codebase laid out
    as `services/` and `composition/` came back clean from every layer-scoped
    check because none of its files resolved to a layer at all -- a silence that
    read exactly like conformance.

    @param path the file, absolute or relative
    @param declaration the project's own layer vocabulary; the default maps the
        canonical names onto themselves
    @return the canonical layer name, or 'unknown' when no segment names one
    """
    # Resolve through the project vocabulary and expose explicit unknown ownership on absence.
    return declaration.role_of(path) or "unknown"


def is_test_path(path: Path) -> bool:
    """Whether a file is test code, by directory or by filename.

    Checks exempt these wholesale: a test may legitimately write the very shape
    it exists to pin, and flagging it would make the rule unenforceable.

    @param path the file
    @return true when it sits under ``tests`` or its name starts with ``test_``;
        false otherwise
    """
    # Classify either a conventional test directory segment or test-module filename.
    return "tests" in path.parts or path.name.startswith("test_")


def describe(start: Path, explicit: Path | None = None) -> project.Declaration:
    """Load the project's declaration and say what it leaves inactive.

    Announcing is the whole point of doing this here rather than inside `run`. A
    check that quietly stops applying two of its rules reports less and looks the
    same, which is the failure this declaration exists to make impossible.

    @param start the path being checked, searched upward for a declaration
    @param explicit a declaration named on the command line, which wins
    @return the declaration in force, after printing what it narrows
    """
    # Load the nearest or explicitly selected project declaration once.
    declaration = project.load(start, explicit)
    # Announce whether the checker is using legacy defaults or authored policy.
    if declaration.source is None:
        # Warn that absence is tolerated only for a direct legacy check, never the v5 gate.
        print("  no local [tool.agent-discipline] declaration found; "
              "direct check is using legacy defaults, but a v5 project gate must fail")
    # A resolved declaration is printed so quiet narrowing cannot masquerade as coverage.
    else:
        # Print the exact declaration path selected by discovery or explicit override.
        print(f"  declaration: {declaration.source}")
    # Announce each narrowing-note element in declaration-defined order.
    for note in declaration.narrowed():
        # Prefix every narrowing so logs remain machine- and human-scannable.
        print(f"  narrowed: {note}")
    # Return the exact declaration whose posture was announced.
    return declaration


def main(check: Check, argv: Sequence[str] | None = None) -> int:
    """Standard entry point shared by every check module.

    Prints a summary naming the rules decided, so a run that found nothing still
    says what it proved rather than only that it was quiet.

    @param check the mechanism to run
    @param argv argument-string elements in caller order, or None to read ``sys.argv``
    @return 0 when nothing was found, 1 when anything was

    @par Effects
    Reads command-line state when ``argv`` is None, loads project files through
    ``describe``, mutates the check's active declaration, reads governed inputs through the
    check, and prints diagnostics plus one summary in that order.
    """
    # Build the common command-line grammar from the mechanism's own description.
    parser = argparse.ArgumentParser(description=check.__doc__ or check.name)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("src")])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--project", type=Path,
        help="a pyproject.toml carrying [tool.agent-discipline]; the only way to "
             "check a tree whose own project file cannot be edited",
    )
    # Parse caller-supplied arguments or the process argument vector.
    args = parser.parse_args(argv)
    # Apply the conventional source default when the explicit list is empty.
    paths = args.paths or [Path("src")]

    # Publish the announced declaration to the checker before it reads any input.
    check.declaration = describe(paths[0], args.project)
    # Execute the mechanism across path elements in caller order.
    findings = check.run(paths)
    # Print each finding element in deterministic checker order.
    for finding in findings:
        # Render paths relative to the requested display root where possible.
        print(finding.render(args.root))
    # Join rule-id elements in declared summary order.
    rules = ", ".join(check.rules)
    # Print a non-vacuous summary even when the finding sequence is empty.
    print(f"\n{check.name}: {len(findings)} finding(s) [{rules}]")
    # Translate finding presence into the stable two-state process result.
    return 1 if findings else 0
