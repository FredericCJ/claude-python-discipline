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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


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

    A subclass declares which rules it decides and implements `visit_module`;
    walking the tree, parsing and surviving a broken file are handled here so
    every check reports the same way.
    """

    ## The `[check:<name>]` token the rules are tagged with, which is also the
    ## module this class lives in. The two must stay spelled the same, or a rule
    ## no longer names a command anyone can run.
    name: str
    ## Every rule this mechanism decides, printed with the summary so a reader
    ## knows what a clean run actually proved.
    rules: tuple[str, ...]

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
            findings.extend(self.visit_module(tree, path, layer_of(path)))
        return findings


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
## layer is a directory, so it is visible in every traceback frame.
LAYERS = ("domain", "app", "adapters", "shell")


def layer_of(path: Path) -> str:
    """Which architectural layer a file belongs to, or 'unknown'.

    The first matching segment wins, reading from the root, so
    `adapters/domain/rules.py` is judged `adapters` and never `domain`. Nesting a
    layer inside another therefore hides the inner one from every layer-scoped
    check.

    @param path the file, absolute or relative
    @return the layer's directory name, or 'unknown' when no segment names one
    """
    for part in path.parts:
        if part in LAYERS:
            return part
    return "unknown"


def is_test_path(path: Path) -> bool:
    """Whether a file is test code, by directory or by filename.

    Checks exempt these wholesale: a test may legitimately write the very shape
    it exists to pin, and flagging it would make the rule unenforceable.

    @param path the file
    @return True when it sits under `tests` or its name starts with `test_`
    """
    return "tests" in path.parts or path.name.startswith("test_")


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
    args = parser.parse_args(argv)

    findings = check.run(args.paths or [Path("src")])
    for finding in findings:
        print(finding.render(args.root))
    rules = ", ".join(check.rules)
    print(f"\n{check.name}: {len(findings)} finding(s) [{rules}]")
    return 1 if findings else 0
