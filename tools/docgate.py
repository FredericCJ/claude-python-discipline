"""One command that decides whether a file's documentation is finished.

    python tools/docgate.py --baseline          # record what the code is, before
    python tools/docgate.py tools/learn.py      # is this file done?
    python tools/docgate.py --all               # the whole tree

Exists to give the documentation migration a single, deterministic stop
condition. An agent asked to document a file should not have to assemble three
commands and a judgement about whether it broke something; it runs this, and the
answer is yes or no with the reasons attached.

Four gates, in order of what they protect:

1. **Behaviour is unchanged.** Every file's abstract syntax tree, with docstrings
   stripped, must match the baseline recorded before the migration began. This is
   the oracle that matters: it proves only documentation moved. Comments never
   reach the tree, so they are free by construction.
2. `checks.doc_coverage` -- nothing undocumented (DOC-001, DOC-002).
3. `checks.doc_style` -- no restated types, no restated names (DOC-008, DOC-009).
4. `ruff` -- the pydocstyle presence and shape rules (DOC-001, DOC-006).

Doxygen itself (DOC-007, DOC-010) is the fifth gate and runs over the tree as a
whole rather than per file, so it is not included here.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Where the pre-migration fingerprints live. Regenerating this after a real code
## change is legitimate; regenerating it to silence gate 1 defeats the point.
BASELINE_PATH: Final = REPO_ROOT / "tools" / "doc_baseline.json"

## Directories the migration covers.
COVERED: Final[tuple[str, ...]] = ("tools", "enforce/checks")

## Files that are tooling for the gate itself, or have no elements to document.
EXCLUDED: Final[frozenset[str]] = frozenset({"doc_baseline.json"})

## The pydocstyle rules that carry DOC-001 and DOC-006.
## Terminal colour codes. ruff emits them even to a pipe and even with
## NO_COLOR set, so the only reliable move is to strip them before parsing.
_ANSI: Final = re.compile("\x1b\[[0-9;]*m")

_LOCATION: Final = re.compile(
    r"^(?P<path>.+?\.py):(?P<line>\d+)(?::\d+)?(?P<rest>.*)$"
)

## The pydocstyle rules that carry DOC-001 and DOC-006.
RUFF_RULES: Final = "D100,D101,D102,D103,D104,D105,D106,D107,D205,D400,D415"


@dataclass(frozen=True, slots=True)
class Failure:
    """One reason a file is not finished."""

    ## Which gate rejected it.
    gate: str
    ## The file, repository-relative.
    path: str
    ## What is wrong, already phrased as something to act on.
    detail: str

    def render(self) -> str:
        """Format the failure for a terminal.

        @return a single line naming the gate, the file and the problem
        """
        return f"  [{self.gate}] {self.path}: {self.detail}"


def iter_python(paths: Sequence[Path]) -> Iterator[Path]:
    """Every Python file under the given paths, in stable order.

    @param paths files or directories to walk
    @return each Python file found, sorted
    """
    for entry in paths:
        if entry.is_file() and entry.suffix == ".py":
            yield entry
        elif entry.is_dir():
            for path in sorted(entry.rglob("*.py")):
                if "__pycache__" not in path.parts:
                    yield path


def covered_paths(root: Path) -> list[Path]:
    """The directories the migration is responsible for.

    @param root the repository root
    @return the covered directories that exist
    """
    return [root / name for name in COVERED if (root / name).exists()]


def strip_documentation(tree: ast.Module) -> ast.Module:
    """A copy of `tree` with every docstring removed.

    Comments never enter the tree at all, so removing docstrings leaves exactly
    the executable code. Two trees that match after this have identical
    behaviour, whatever their documentation says.

    @param tree the parsed module
    @return the same module with docstring expressions dropped
    """
    for node in ast.walk(tree):
        body = getattr(node, "body", None)
        if not isinstance(body, list) or not body:
            continue
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        first = body[0]
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            # A body cannot be empty; a bare pass keeps the tree well formed and
            # is equivalent for the comparison's purpose.
            body[0] = ast.Pass()
    return tree


def fingerprint(path: Path) -> str:
    """A stable signature of a file's code, ignoring all documentation.

    @param path the file to fingerprint
    @return the dumped syntax tree with docstrings stripped
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return ast.dump(strip_documentation(tree), annotate_fields=False)


def write_baseline(root: Path) -> int:
    """Record the current code shape of every covered file.

    @param root the repository root
    @return how many files were fingerprinted
    """
    prints = {
        _relative(path, root): fingerprint(path)
        for path in iter_python(covered_paths(root))
    }
    BASELINE_PATH.write_text(
        json.dumps({"generated_by": "tools/docgate.py", "files": prints},
                   indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return len(prints)


def load_baseline() -> dict[str, str]:
    """The recorded fingerprints, or an empty mapping when none exist.

    @return file path mapped to its recorded fingerprint
    """
    if not BASELINE_PATH.exists():
        return {}
    return dict(json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("files", {}))


def _relative(path: Path, root: Path) -> str:
    """A repository-relative key for a file, whatever form it arrived in.

    @param path the file
    @param root the repository root
    @return the relative POSIX path, or the absolute one if it lies outside
    """
    try:
        return path.resolve().relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def check_behaviour(paths: Sequence[Path], root: Path) -> Iterator[Failure]:
    """Gate 1: the code is what it was before the documentation was written.

    @param paths the files to check
    @param root the repository root
    @return one failure per file whose code changed
    """
    baseline = load_baseline()
    if not baseline:
        yield Failure("behaviour", "-", "no baseline recorded; run --baseline first")
        return
    for path in paths:
        name = _relative(path, root)
        recorded = baseline.get(name)
        if recorded is None:
            continue  # a new file has nothing to have changed from
        try:
            current = fingerprint(path)
        except SyntaxError as exc:
            yield Failure("behaviour", name, f"does not parse: {exc.msg} at line {exc.lineno}")
            continue
        if current != recorded:
            yield Failure(
                "behaviour", name,
                "the code changed, not just its documentation -- revert the "
                "non-comment edits, or re-record the baseline if the change was intended",
            )


def run_check(module: str, paths: Sequence[Path], root: Path) -> Iterator[Failure]:
    """Run one of the AST checks over the given paths.

    @param module the check module name under `checks`
    @param paths the files to check
    @param root the repository root
    @return one failure per reported finding
    """
    if not paths:
        return
    finished = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [sys.executable, "-m", f"checks.{module}", *(str(p) for p in paths)],
        capture_output=True, text=True, cwd=root / "enforce", check=False,
    )
    for line in finished.stdout.splitlines():
        if ":" in line and not line.startswith((" ", "\t")) and "finding(s)" not in line:
            yield Failure(module, *_split_location(line, root))


def run_ruff(paths: Sequence[Path], root: Path) -> Iterator[Failure]:
    """Run the pydocstyle presence and shape rules.

    @param paths the files to check
    @param root the repository root
    @return one failure per reported diagnostic
    """
    if not paths:
        return
    finished = subprocess.run(  # noqa: S603 - fixed argv, no shell
        [_ruff(), "check", "--no-cache", "--select", RUFF_RULES,
         "--output-format", "concise", *(str(p) for p in paths)],
        capture_output=True, text=True, cwd=root, check=False,
        # ruff colourizes even when stdout is a pipe, and the escape codes break
        # every attempt to parse a location out of the line.
        env={**os.environ, "NO_COLOR": "1"},
    )
    for raw in finished.stdout.splitlines():
        line = _ANSI.sub("", raw)
        if ".py:" in line:
            yield Failure("ruff", *_split_location(line, root))


def _ruff() -> str:
    """The ruff executable, found beside the interpreter rather than on PATH.

    A subprocess does not inherit an activated environment's PATH reliably, and
    a gate that cannot find its linter reports success by accident.

    @return an absolute path to ruff, or the bare name as a last resort
    """
    for candidate in (
        Path(sys.executable).parent / "ruff.exe",
        Path(sys.executable).parent / "ruff",
        Path(sys.executable).parent / "Scripts" / "ruff.exe",
    ):
        if candidate.exists():
            return str(candidate)
    return "ruff"


def _split_location(line: str, root: Path) -> tuple[str, str]:
    """Split a `path:line: message` diagnostic into path and message.

    @param line the diagnostic
    @param root the repository root, for relative display
    @return the path and the remaining message
    """
    # A Windows path starts `C:\...`, so splitting on the first colon loses the
    # drive. Anchor on the `.py:<line>` pair instead.
    found = _LOCATION.match(line)
    if found is None:
        return "-", line.strip()
    where = Path(found.group("path"))
    try:
        shown = where.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        shown = where.name
    return f"{shown}:{found.group('line')}", found.group("rest").lstrip(": ").strip()


def gate(paths: Sequence[Path], root: Path) -> list[Failure]:
    """Every gate, over the given files.

    @param paths the files to check
    @param root the repository root
    @return every failure found, behaviour first
    """
    files = list(iter_python(paths))
    return [
        *check_behaviour(files, root),
        *run_check("doc_coverage", files, root),
        *run_check("doc_style", files, root),
        *run_ruff(files, root),
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 when every gate passes, 1 otherwise
    """
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Decide whether documentation is finished.")
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--all", action="store_true", help="check every covered file")
    parser.add_argument("--baseline", action="store_true",
                        help="record the current code shape and exit")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.baseline:
        print(f"recorded {write_baseline(root)} fingerprint(s) in "
              f"{BASELINE_PATH.relative_to(root).as_posix()}")
        return 0

    targets = (covered_paths(root) if args.all or not args.paths
               else [p if p.is_absolute() else (root / p) for p in args.paths])
    failures = gate(targets, root)
    if not failures:
        count = len(list(iter_python(targets)))
        print(f"documentation gate: {count} file(s) clean")
        return 0

    by_gate: dict[str, int] = {}
    for failure in failures:
        by_gate[failure.gate] = by_gate.get(failure.gate, 0) + 1
    for failure in failures[:200]:
        print(failure.render())
    if len(failures) > 200:
        print(f"  ... and {len(failures) - 200} more")
    print("\n" + ", ".join(f"{gate_name}={n}" for gate_name, n in sorted(by_gate.items())))
    print(f"documentation gate: {len(failures)} failure(s)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
