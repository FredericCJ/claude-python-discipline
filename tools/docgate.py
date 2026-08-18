"""One command that decides whether a file's documentation is finished.

    python tools/docgate.py --baseline          # record what the code is, before
    python tools/docgate.py tools/learn.py      # is this file done?
    python tools/docgate.py --all               # the whole tree
    python tools/docgate.py --baseline tools/x.py --reason "..."   # re-record one file

Exists to give the documentation migration a single, deterministic stop
condition. An agent asked to document a file should not have to assemble three
commands and a judgement about whether it broke something; it runs this, and the
answer is yes or no with the reasons attached.

Four gates, in order of what they protect:

1. **Behaviour is unchanged.** Every file's abstract syntax tree, with docstrings
   stripped, must match the baseline recorded before the migration began. This is
   the oracle that matters: it proves only documentation moved. Comments never
   reach the tree, so they are free by construction.

   The baseline is only as trustworthy as its own provenance, so every entry
   carries the git ref its fingerprint was taken from and, when it was
   re-recorded rather than inherited from that original ref, a mandatory
   reason. `--baseline <paths> --reason "..."` is the only way to touch a
   subset of an existing baseline; there is no way to reach a written file
   through that path without a reason attached (`rerecord_baseline` refuses).
   A recorded ref is a checkable claim: `git show <ref>:<path>`, fingerprinted,
   must equal the entry. It therefore names a commit only for a file that
   matches that commit, and the sentinel `working-tree` for one that does not.

   The remaining hole is deliberate and is not closed here: a full
   `--baseline` with no paths rewrites every entry from scratch, dropping the
   reasons, the original refs and the note, and it asks for no justification.
   It exists so a fresh baseline can be established at all. Against an existing
   baseline it is the laundering path — reviewing a diff of this file is what
   catches its use, not the tool.
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

## The repository root, one level up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Where the pre-migration fingerprints live. Regenerating this after a real code
## change is legitimate; regenerating it to silence gate 1 defeats the point.
BASELINE_PATH: Final = REPO_ROOT / "tools" / "doc_baseline.json"

## Directories the migration covers.
COVERED: Final[tuple[str, ...]] = ("tools", "enforce/checks")

## Files that are tooling for the gate itself, or have no elements to document.
EXCLUDED: Final[frozenset[str]] = frozenset({"doc_baseline.json"})

## Terminal colour codes. ruff emits them even to a pipe and even with
## NO_COLOR set, so the only reliable move is to strip them before parsing.
_ANSI: Final = re.compile("\x1b\\[[0-9;]*m")

## A `path:line[:col]` prefix, anchored on the `.py:` pair so a Windows
## drive letter is not mistaken for the end of the path.
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
            # Remove it rather than substitute for it. Replacing a docstring
            # with a placeholder makes *adding* one change the body length, so
            # every documented function would look like a code change -- which
            # is exactly the false positive this gate must not produce.
            del body[0]
            if not body:
                body.append(ast.Pass())
    return tree


def fingerprint(path: Path) -> str:
    """A stable signature of a file's code, ignoring all documentation.

    @param path the file to fingerprint
    @return the dumped syntax tree with docstrings stripped
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return ast.dump(strip_documentation(tree), annotate_fields=False)


## The provenance an individual re-record must carry: which files changed, at
## what ref, and why. `docgate.py --baseline <paths> --reason "..."` is the
## only way to touch a subset of an existing baseline -- the reason is
## mandatory so a silent re-baseline (the exact failure this format exists to
## prevent) cannot happen by omission. See DOC-002 for the ## block obligation
## this dataclass's fields inherit even though frozen dataclasses are not the
## element the rule names -- documented here as ordinary attributes below.
@dataclass(frozen=True, slots=True)
class BaselineEntry:
    """One file's recorded behaviour fingerprint and where it came from."""

    ## The dumped, docstring-stripped syntax tree, as returned by `fingerprint`.
    fingerprint: str
    ## The git revision the fingerprint was taken from, or the sentinel
    ## `"working-tree"` when it was taken from an uncommitted tree (a
    ## re-record performed before the change that prompted it was committed).
    ref: str
    ## Why this entry was re-recorded rather than inherited from the
    ## baseline's original ref. `None` for an entry that has never been
    ## touched since the baseline it belongs to was first written.
    reason: str | None = None

    def to_json(self) -> dict[str, str]:
        """Render the entry in its on-disk shape.

        @return a mapping with `fingerprint`, `ref` and, when present, `reason`
        """
        out = {"fingerprint": self.fingerprint, "ref": self.ref}
        if self.reason is not None:
            out["reason"] = self.reason
        return out

    @staticmethod
    def from_json(raw: dict[str, str] | str, default_ref: str) -> BaselineEntry:
        """Parse one stored entry, accepting the pre-provenance flat string too.

        @param raw either `{"fingerprint", "ref", "reason"?}` or, for a
            baseline written before this format, a bare fingerprint string
        @param default_ref the ref to attribute to a bare fingerprint string,
            since the old format recorded it once at the top level
        @return the parsed entry
        """
        if isinstance(raw, str):
            return BaselineEntry(fingerprint=raw, ref=default_ref)
        return BaselineEntry(
            fingerprint=raw["fingerprint"],
            ref=raw.get("ref", default_ref),
            reason=raw.get("reason"),
        )


def _current_ref(root: Path) -> str:
    """The commit the working tree is currently checked out at.

    @param root the repository root
    @return the resolved commit sha, or `"working-tree"` when git cannot
        answer (no repository, detached tooling, and the like) -- an honest
        admission of "unknown" rather than a fabricated sha
    """
    shown = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, encoding="utf-8", cwd=root, check=False,
    )
    return shown.stdout.strip() if shown.returncode == 0 else "working-tree"


def _ref_for(name: str, root: Path, head: str) -> str:
    """The revision a file's fingerprint may honestly be attributed to.

    Attributing a fingerprint to the checked-out commit is only true when that
    file is identical to the commit. Fingerprinting a modified — or untracked —
    file and stamping it with the commit sha records a claim an auditor can
    disprove in one `git show`, and disproving it looks exactly like the
    laundering this format exists to expose. Anything not provably clean is
    therefore attributed to the sentinel instead.

    @param name the file, repository-relative, as it is keyed in the baseline
    @param root the repository root
    @param head the resolved commit sha, or the sentinel when git could not answer
    @return `head` when the file matches that commit, else `"working-tree"`
    """
    if head == "working-tree":
        return head
    shown = subprocess.run(  # noqa: S603 - fixed argv, no shell
        ["git", "status", "--porcelain", "--", name],
        capture_output=True, encoding="utf-8", cwd=root, check=False,
    )
    if shown.returncode != 0 or shown.stdout.strip():
        return "working-tree"
    return head


def _write_baseline_document(
    files: dict[str, BaselineEntry], note: str | None = None,
) -> None:
    """Serialize a complete set of entries to `BASELINE_PATH`.

    @param files every file's entry, keyed by repository-relative path
    @param note free-text context to carry at the top level; omitted when `None`
    """
    document: dict[str, object] = {"generated_by": "tools/docgate.py"}
    if note is not None:
        document["note"] = note
    document["files"] = {name: entry.to_json() for name, entry in sorted(files.items())}
    BASELINE_PATH.write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n", encoding="utf-8",
    )


def write_baseline(root: Path) -> int:
    """Record the current code shape of every covered file, from scratch.

    This replaces the entire baseline, dropping every recorded reason, every
    original ref and the note along with them; each entry's provenance becomes
    the checked-out commit, or `"working-tree"` for a file that does not match
    it. Use `rerecord_baseline` instead to update only the files that actually
    changed; that path requires a reason and leaves the rest of the baseline,
    and its history, untouched.

    @param root the repository root
    @return how many files were fingerprinted
    """
    head = _current_ref(root)
    files: dict[str, BaselineEntry] = {}
    for path in iter_python(covered_paths(root)):
        name = _relative(path, root)
        files[name] = BaselineEntry(
            fingerprint=fingerprint(path), ref=_ref_for(name, root, head),
        )
    _write_baseline_document(files)
    return len(files)


def write_baseline_from_ref(root: Path, ref: str) -> int:
    """Record the code shape as it was at a git revision, from scratch.

    Used when establishing (or wholly re-establishing) the baseline against a
    specific commit rather than the working tree -- for example the
    pre-migration state the behaviour oracle is meant to guard.

    @param root the repository root
    @param ref the git revision to read the files from
    @return how many files were fingerprinted
    """
    files: dict[str, BaselineEntry] = {}
    for path in iter_python(covered_paths(root)):
        name = _relative(path, root)
        shown = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "show", f"{ref}:{name}"],
            capture_output=True, encoding="utf-8", cwd=root, check=False,
        )
        if shown.returncode != 0:
            continue  # a file added since the reference has nothing to compare to
        tree = ast.parse(shown.stdout, filename=name)
        fp = ast.dump(strip_documentation(tree), annotate_fields=False)
        files[name] = BaselineEntry(fingerprint=fp, ref=ref)
    _write_baseline_document(files)
    return len(files)


def rerecord_baseline(root: Path, paths: Sequence[Path], reason: str) -> int:
    """Re-record a subset of an existing baseline, each entry carrying why.

    The mandatory reason is the mechanism, not a convention: there is no code
    path in this module that writes a re-recorded entry without one. That is
    what makes a re-baseline that quietly launders a real behaviour change
    detectable -- it cannot happen silently, only with an explanation attached
    for a reviewer to judge.

    @param root the repository root
    @param paths the files to re-record; every other entry is left untouched
    @param reason why these files' fingerprints no longer match their
        original recording -- required, and rejected if blank
    @return how many entries were re-recorded
    @throws ValueError if `reason` is empty or whitespace, or if there is no
        existing baseline to update
    """
    if not reason or not reason.strip():
        no_reason = "a reason is required to re-record a baseline entry"
        raise ValueError(no_reason)
    existing = load_baseline()
    if not existing:
        no_baseline = "no baseline recorded; run --baseline (with no paths) first"
        raise ValueError(no_baseline)
    head = _current_ref(root)
    targets = list(iter_python(paths))
    files = dict(existing)
    for path in targets:
        name = _relative(path, root)
        files[name] = BaselineEntry(
            fingerprint=fingerprint(path),
            ref=_ref_for(name, root, head),
            reason=reason,
        )
    note = _load_note()
    _write_baseline_document(files, note=note)
    return len(targets)


def _load_note() -> str | None:
    """The free-text note currently on record, if any.

    @return the top-level `note`, or `None` when there is no baseline or no note
    """
    if not BASELINE_PATH.exists():
        return None
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("note")


def load_baseline() -> dict[str, BaselineEntry]:
    """The recorded baseline entries, or an empty mapping when none exist.

    @return file path mapped to its recorded entry
    """
    if not BASELINE_PATH.exists():
        return {}
    document = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    default_ref = document.get("ref", "working-tree")  # pre-provenance format
    return {
        name: BaselineEntry.from_json(raw, default_ref)
        for name, raw in document.get("files", {}).items()
    }


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
        entry = baseline.get(name)
        if entry is None:
            continue  # a new file has nothing to have changed from
        try:
            current = fingerprint(path)
        except SyntaxError as exc:
            yield Failure("behaviour", name, f"does not parse: {exc.msg} at line {exc.lineno}")
            continue
        if current != entry.fingerprint:
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


def _run_baseline(args: argparse.Namespace, parser: argparse.ArgumentParser, root: Path) -> int:
    """Handle every `--baseline` variant: fresh, from a ref, or a subset re-record.

    Split out of `main` so the three-way branch it replaces does not push the
    dispatcher itself over the project's complexity ceiling.

    @param args the parsed command line
    @param parser used to report a usage error via `parser.error`, which exits
    @param root the repository root
    @return 0; every path either prints a result or exits through `parser.error`
    """
    if args.paths:
        # A subset re-record. This is the path that must never be silent:
        # rerecord_baseline refuses outright when reason is missing or blank,
        # so there is no way to reach a written file without one.
        if not args.reason:
            parser.error("--reason is required when re-recording specific "
                          "files with --baseline (a full --baseline with no "
                          "paths does not need one)")
        paths = [p if p.is_absolute() else (root / p) for p in args.paths]
        try:
            count = rerecord_baseline(root, paths, args.reason)
        except ValueError as exc:
            parser.error(str(exc))
        print(f"re-recorded {count} fingerprint(s) in "
              f"{BASELINE_PATH.relative_to(root).as_posix()} -- {args.reason}")
        return 0
    if args.from_ref:
        print(f"recorded {write_baseline_from_ref(root, args.from_ref)} fingerprint(s) "
              f"from {args.from_ref} in "
              f"{BASELINE_PATH.relative_to(root).as_posix()}")
        return 0
    print(f"recorded {write_baseline(root)} fingerprint(s) in "
          f"{BASELINE_PATH.relative_to(root).as_posix()}")
    return 0


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
    parser.add_argument("--from-ref", metavar="REF",
                        help="with --baseline and no paths, fingerprint that git "
                             "revision instead of the working tree")
    parser.add_argument("--reason", metavar="TEXT",
                        help="required with --baseline plus one or more paths: why "
                             "these entries are being re-recorded rather than left "
                             "at their original ref")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.baseline:
        return _run_baseline(args, parser, root)

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
