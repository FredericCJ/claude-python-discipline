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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from . import project

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

    def render(self, root: Path | None = None) -> str:
        """Format the finding as a diagnostic line with its remedy beneath.

        A path that does not lie under `root` is shown in full rather than
        refused; a display convenience must not turn into a failure mode.

        @param root a directory to shorten the path against, or None to leave it
        @return two lines, the first in the `path:line: RULE message` form editors
            and CI logs already know how to jump from
        """
        shown = self.path
        if root is not None:
            try:
                shown = self.path.relative_to(root)
            except ValueError:
                pass
        return (
            f"{shown.as_posix()}:{self.line}: {self.rule_id} {self.message}\n"
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
    ## Every rule this mechanism decides, printed with the summary so a reader
    ## knows what a clean run actually proved.
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

        @param paths files or directories to walk
        @return every finding, grouped by file in walk order
        """


class TextCheck(Check):
    """A mechanism whose subject is a file this repository does not parse.

    Reads each matching file as text and hands it to `visit_text`. A file that
    cannot be decoded is reported rather than skipped: a check that silently
    passes over what it cannot read is a check that passes.
    """

    ## Suffixes this check examines. Narrow on purpose -- a text check walking
    ## everything would report a rule's subject wherever a word happened to
    ## appear, which is how a check earns being switched off.
    suffixes: tuple[str, ...] = (".md",)

    @abstractmethod
    def visit_text(self, text: str, path: Path) -> Iterator[Finding]:
        """Yield findings for one file's contents.

        @param text the file's decoded contents
        @param path the file it was read from, for the finding's location
        @return one finding per violation
        """

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Read every matching file and collect what `visit_text` reports.

        @param paths files or directories to walk
        @return every finding, in walk order
        """
        findings: list[Finding] = []
        for path in iter_files(paths, self.suffixes):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                findings.append(
                    Finding(
                        rule_id="CHECK-000", path=path, line=1,
                        message=f"could not read: {exc}",
                        remediation="No check can run on this file; fix or exclude it.",
                    )
                )
                continue
            findings.extend(self.visit_text(text, path))
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
        @return one finding per violation, in whatever order suits the check
        """

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Collect what this mechanism finds across every file under `paths`.

        A file that will not parse becomes a CHECK-000 finding instead of an
        exception: one broken file must not hide the violations in the rest.

        @param paths files or directories to walk
        @return every finding, grouped by file in walk order
        """
        findings: list[Finding] = []
        for path in iter_python_files(paths):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                findings.append(
                    Finding(
                        rule_id="CHECK-000",
                        path=path,
                        line=exc.lineno or 1,
                        message=f"could not parse: {exc.msg}",
                        remediation="Fix the syntax error; no check can run on this file.",
                    )
                )
                continue
            findings.extend(
                self.visit_module(tree, path, layer_of(path, self.declaration))
            )
        return findings


def iter_files(paths: Sequence[Path], suffixes: Sequence[str]) -> Iterator[Path]:
    """Every file under the given paths whose suffix matches, in stable order.

    A file named explicitly is yielded whatever its suffix: a caller pointing at
    one file has already said which file it means, and second-guessing that would
    make a check impossible to run on demand.

    @param paths a mix of files and directories
    @param suffixes the suffixes to collect when walking a directory
    @return each matching file, directories expanded and sorted
    """
    wanted = tuple(suffixes)
    for entry in paths:
        if entry.is_file():
            yield entry
        elif entry.is_dir():
            for path in sorted(entry.rglob("*")):
                if path.is_file() and path.suffix in wanted:
                    yield path


def iter_python_files(paths: Sequence[Path]) -> Iterator[Path]:
    """Every `.py` file under the given paths, in stable order.

    Order is fixed so two runs over the same tree produce the same output and a
    diff between them means something changed.

    @param paths a mix of files and directories; anything else is skipped
    @return each Python file, directories expanded and sorted
    """
    for entry in paths:
        if entry.is_file() and entry.suffix == ".py":
            yield entry
        elif entry.is_dir():
            yield from sorted(entry.rglob("*.py"))


## The layer names `law/ARCH` defines. A path segment match is deliberate: the
## layer is a directory, so it is visible in every traceback frame. Re-exported
## from `project` so there is one list rather than two that can disagree.
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
    for part in path.parts:
        canonical = declaration.canonical(part)
        if canonical is not None:
            return canonical
    # The final component is tried again without its suffix, because a shell is
    # not always a package. A program of a few thousand lines commonly puts its
    # entry point and its wiring at the package root as `cli.py` and
    # `composition.py`, and no directory segment then names the layer at all.
    # Found by running this against a real four-package codebase shaped exactly
    # that way: both files resolved to 'unknown', so every layer-scoped check
    # skipped the shell -- which is the layer where the effects are.
    if path.suffix:
        return declaration.canonical(path.stem) or "unknown"
    return "unknown"


def is_test_path(path: Path) -> bool:
    """Whether a file is test code, by directory or by filename.

    Checks exempt these wholesale: a test may legitimately write the very shape
    it exists to pin, and flagging it would make the rule unenforceable.

    @param path the file
    @return True when it sits under `tests` or its name starts with `test_`
    """
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
    declaration = project.load(start, explicit)
    if declaration.source is None:
        print("  no [tool.agent-discipline] declaration found; "
              "assuming the canonical layers and no documentation engine")
    else:
        print(f"  declaration: {declaration.source}")
    for note in declaration.narrowed():
        print(f"  narrowed: {note}")
    return declaration


def main(check: Check, argv: Sequence[str] | None = None) -> int:
    """Standard entry point shared by every check module.

    Prints a summary naming the rules decided, so a run that found nothing still
    says what it proved rather than only that it was quiet.

    @param check the mechanism to run
    @param argv command-line arguments, or None to read `sys.argv`
    @return 0 when nothing was found, 1 when anything was
    """
    parser = argparse.ArgumentParser(description=check.__doc__ or check.name)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("src")])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument(
        "--project", type=Path,
        help="a pyproject.toml carrying [tool.agent-discipline]; the only way to "
             "check a tree whose own project file cannot be edited",
    )
    args = parser.parse_args(argv)
    paths = args.paths or [Path("src")]

    check.declaration = describe(paths[0], args.project)
    findings = check.run(paths)
    for finding in findings:
        print(finding.render(args.root))
    rules = ", ".join(check.rules)
    print(f"\n{check.name}: {len(findings)} finding(s) [{rules}]")
    return 1 if findings else 0
