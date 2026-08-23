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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

## The repository root, one level up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Where the pre-migration fingerprints live. Regenerating this after a real code
## change is legitimate; regenerating it to silence gate 1 defeats the point.
BASELINE_PATH: Final = REPO_ROOT / "tools" / "doc_baseline.json"

## Directories the migration covers. The reference package is included because it
## is the worked example an adopter reads: documentation that is exemplary
## everywhere except in the thing held up as the example would be a poor joke.
##
## `enforce` is named whole rather than by subdirectory. The subdirectory form
## listed checks, fitness and fixtures, and `enforce/discrimination.py` -- a
## mechanism in exactly the same sense -- landed beside them and outside the gate.
## That is the second time a new mechanism was written outside `COVERED`; naming
## the parent closes the shape rather than the instance.
## Each COVERED element represents one governed path; traversal order is preserved.
COVERED: Final[tuple[str, ...]] = ("tools", "enforce")

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
        # Return a single line naming the gate, the file and the problem to the caller.
        return f"  [{self.gate}] {self.path}: {self.detail}"


def iter_python(paths: Sequence[Path]) -> Iterator[Path]:
    """Every Python file under the given paths, in stable order.

    @param paths files or directories to walk
        Each paths element represents one repository path; traversal order is preserved.
    @return each Python file found, sorted
    """
    # Inspect caller-declared paths in order so duplicate or overlapping inputs stay observable.
    for entry in paths:
        # Yield an explicitly named Python file without expanding its parent directory.
        if entry.is_file() and entry.suffix == ".py":
            yield entry
        # Expand only existing directories; missing paths intentionally contribute no files.
        elif entry.is_dir():
            # Sort recursive discovery so fingerprints and diagnostics are reproducible.
            for path in sorted(entry.rglob("*.py")):
                # Exclude interpreter caches from the governed source set.
                if "__pycache__" not in path.parts:
                    yield path


def covered_paths(root: Path) -> list[Path]:
    """The directories the migration is responsible for.

    @param root the repository root
    @return the covered directories that exist
    """
    # Resolve declared coverage entries while omitting optional roots that are absent.
    return [root / name for name in COVERED if (root / name).exists()]


def strip_documentation(tree: ast.Module) -> ast.Module:
    """A copy of `tree` with every docstring removed.

    Comments never enter the tree at all, so removing docstrings leaves exactly
    the executable code. Two trees that match after this have identical
    behaviour, whatever their documentation says.

    @param tree the parsed module
    @return the same module with docstring expressions dropped
    """
    # Examine every syntax owner that could contain a leading docstring expression.
    for node in ast.walk(tree):
        # Read the node's statement suite without assuming every AST node owns one.
        body = getattr(node, "body", None)
        # Stop stripping when the syntax owner has no executable statement list.
        if not isinstance(body, list) or not body:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Recurse only into syntax owners that can contain documented statement suites.
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Only the first statement can carry a Python docstring.
        first = body[0]
        # Recognize the exact expression shape Python treats as a docstring.
        if (isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)):
            # Remove it rather than substitute for it. Replacing a docstring
            # with a placeholder makes *adding* one change the body length, so
            # every documented function would look like a code change -- which
            # is exactly the false positive this gate must not produce.
            del body[0]
            # Keep the mutated suite representable when documentation was its entire body.
            if not body:
                body.append(ast.Pass())
    # Return the same module with docstring expressions dropped to the caller.
    return tree


def fingerprint(path: Path) -> str:
    """A stable signature of a file's code, ignoring all documentation.

    @param path the file to fingerprint
    @return the dumped syntax tree with docstrings stripped
    """
    # Parse the Python source into the syntax tree used for structural fingerprinting.
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Return the dumped syntax tree with docstrings stripped to the caller.
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
        # Map each schema-field key to its serialized string value; insertion order is
        # deliberately irrelevant because the enclosing document is emitted with sorted keys.
        out = {"fingerprint": self.fingerprint, "ref": self.ref}
        # Omit an absent reason so untouched entries remain distinguishable on disk.
        if self.reason is not None:
            # Attach the mandatory explanation carried by an intentional re-record.
            out["reason"] = self.reason
        # Return a mapping with `fingerprint`, `ref` and, when present, `reason` to the caller.
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
        # Upgrade a legacy bare fingerprint using the document-level reference.
        if isinstance(raw, str):
            # Return the parsed entry to the caller.
            return BaselineEntry(fingerprint=raw, ref=default_ref)
        # Return the parsed entry to the caller.
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
    # Ask Git for the checked-out identity without treating a non-repository as exceptional.
    shown = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, encoding="utf-8", cwd=root, check=False,
    )
    # Return the resolved commit sha, or `"working-tree"` when git cannot to the caller.
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
    # Preserve the sentinel when no commit identity was available to validate.
    if head == "working-tree":
        # Return `head` when the file matches that commit, else `"working-tree"` to the caller.
        return head
    # Verify that the named file is unchanged before attributing it to the commit.
    shown = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        ["git", "status", "--porcelain", "--", name],
        capture_output=True, encoding="utf-8", cwd=root, check=False,
    )
    # Use honest working-tree provenance when Git failed or reported any file change.
    if shown.returncode != 0 or shown.stdout.strip():
        # Return `head` when the file matches that commit, else `"working-tree"` to the caller.
        return "working-tree"
    # Return `head` when the file matches that commit, else `"working-tree"` to the caller.
    return head


def _write_baseline_document(
    files: dict[str, BaselineEntry], note: str | None = None,
) -> None:
    """Serialize a complete set of entries to `BASELINE_PATH`.

    @param files every file's entry, keyed by repository-relative path
        Treat files as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param note free-text context to carry at the top level; omitted when `None`

    @par Effects
    Replaces `tools/doc_baseline.json` only after the complete deterministic
    payload has been assembled in memory.
    """
    # Map each top-level schema key to its JSON payload value; key order is deliberately
    # irrelevant because serialization sorts it.
    document: dict[str, object] = {"generated_by": "tools/docgate.py"}
    # Preserve a note only when the caller supplied one.
    if note is not None:
        # Attach the optional context before serializing the complete document.
        document["note"] = note
    # Serialize entries by portable path in stable order for reviewable diffs.
    document["files"] = {name: entry.to_json() for name, entry in sorted(files.items())}
    # Replace the baseline in one write only after the complete payload exists.
    BASELINE_PATH.write_text(
        json.dumps(document, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
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
    # Capture one candidate commit identity for every clean file in this snapshot.
    head = _current_ref(root)
    # Map each repository-relative path key to its provenance-bearing fingerprint value;
    # insertion order is deliberately irrelevant because serialization sorts the keys.
    files: dict[str, BaselineEntry] = {}
    # Fingerprint every governed file in deterministic discovery order.
    for path in iter_python(covered_paths(root)):
        # Key the snapshot by a platform-neutral repository-relative path.
        name = _relative(path, root)
        # Bind code shape to the strongest provenance the current file can honestly claim.
        files[name] = BaselineEntry(
            fingerprint=fingerprint(path), ref=_ref_for(name, root, head),
        )
    _write_baseline_document(files)
    # Return how many files were fingerprinted to the caller.
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
    # Map each repository-relative path key to its historical fingerprint entry; insertion
    # order is deliberately irrelevant because serialization sorts the keys.
    files: dict[str, BaselineEntry] = {}
    # Query each currently governed path against the historical tree in stable order.
    for path in iter_python(covered_paths(root)):
        # Address Git objects with the repository-relative POSIX spelling.
        name = _relative(path, root)
        # Read source bytes from the requested revision without changing the working tree.
        shown = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            ["git", "show", f"{ref}:{name}"],
            capture_output=True, encoding="utf-8", cwd=root, check=False,
        )
        # Ignore current files absent from the historical tree because no old shape exists.
        if shown.returncode != 0:
            # Advance after classifying the path as post-reference source.
            continue
        # Parse the Python source into the syntax tree used for structural fingerprinting.
        tree = ast.parse(shown.stdout, filename=name)
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        fp = ast.dump(strip_documentation(tree), annotate_fields=False)
        # Attribute the historical fingerprint directly to the requested revision.
        files[name] = BaselineEntry(fingerprint=fp, ref=ref)
    _write_baseline_document(files)
    # Return how many files were fingerprinted to the caller.
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
        Each paths element represents one repository path; traversal order is preserved.
    @param reason why these files' fingerprints no longer match their
        original recording -- required, and rejected if blank
    @return how many entries were re-recorded
    @throws ValueError if `reason` is empty or whitespace, or if there is no
        existing baseline to update
    """
    # Refuse baseline re-recording unless the caller supplies a nonblank audit reason.
    if not reason or not reason.strip():
        # Localize the invariant failure before propagating it to API and CLI callers.
        no_reason = "a reason is required to re-record a baseline entry"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ValueError(no_reason)
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    existing = load_baseline()
    # Refuse comparison or update when no recorded baseline exists.
    if not existing:
        # Localize the missing-oracle failure before any replacement can be written.
        no_baseline = "no baseline recorded; run --baseline (with no paths) first"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ValueError(no_baseline)
    # Preserve the immutable revision identity used as provenance for this comparison.
    head = _current_ref(root)
    # Expand caller paths once so the update count and actual writes share one target set.
    targets = list(iter_python(paths))
    # Copy existing entries so unrelated fingerprints and provenance remain untouched.
    files = dict(existing)
    # Replace only selected entries, preserving deterministic discovery order.
    for path in targets:
        # Use the same portable key as the existing baseline document.
        name = _relative(path, root)
        # Record the new code shape together with truthful provenance and the audit reason.
        files[name] = BaselineEntry(
            fingerprint=fingerprint(path),
            ref=_ref_for(name, root, head),
            reason=reason,
        )
    # Preserve the optional baseline note while re-recording selected entries.
    note = _load_note()
    _write_baseline_document(files, note=note)
    # Return how many entries were re-recorded to the caller.
    return len(targets)


def _load_note() -> str | None:
    """The free-text note currently on record, if any.

    @return the top-level `note`, or `None` when there is no baseline or no note
    """
    # An absent baseline cannot carry optional document context.
    if not BASELINE_PATH.exists():
        # Return the top-level `note`, or `None` when there is no baseline or no note to the
        # caller.
        return None
    # Return the top-level `note`, or `None` when there is no baseline or no note to the caller.
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8")).get("note")


def load_baseline() -> dict[str, BaselineEntry]:
    """The recorded baseline entries, or an empty mapping when none exist.

    @return file path mapped to its recorded entry
    """
    # Treat an absent baseline as an empty oracle for callers that validate preconditions.
    if not BASELINE_PATH.exists():
        # Return file path mapped to its recorded entry to the caller.
        return {}
    # Decode the complete baseline document before adapting individual entries.
    document = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    # Preserve the document-level reference used only by the legacy flat-entry format.
    default_ref = document.get("ref", "working-tree")
    # Return file path mapped to its recorded entry to the caller.
    return {
        name: BaselineEntry.from_json(raw, default_ref)
        # Upgrade every stored value while retaining its repository-relative path key.
        for name, raw in document.get("files", {}).items()
    }


def _relative(path: Path, root: Path) -> str:
    """A repository-relative key for a file, whatever form it arrived in.

    @param path the file
    @param root the repository root
    @return the relative POSIX path, or the absolute one if it lies outside
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Return the relative POSIX path, or the absolute one if it lies outside to the caller.
        return path.resolve().relative_to(root).as_posix()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError:
        # Return the relative POSIX path, or the absolute one if it lies outside to the caller.
        return path.as_posix()


def check_behaviour(paths: Sequence[Path], root: Path) -> Iterator[Failure]:
    """Gate 1: the code is what it was before the documentation was written.

    @param paths the files to check
        Each paths element represents one repository path; traversal order is preserved.
    @param root the repository root
    @return one failure per file whose code changed
    """
    # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
    baseline = load_baseline()
    # Refuse comparison or update when no recorded baseline exists.
    if not baseline:
        yield Failure("behaviour", "-", "no baseline recorded; run --baseline first")
        # Return one failure per file whose code changed to the caller.
        return
    # Compare each selected file against the matching recorded fingerprint.
    for path in paths:
        # Translate the selected file to its baseline lookup key.
        name = _relative(path, root)
        # Look up the only historical shape relevant to this repository-relative path.
        entry = baseline.get(name)
        # A newly governed file has no prior behavior that this oracle can compare.
        if entry is None:
            # Advance after classifying the file as new since baseline creation.
            continue
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Preserve the documentation-stripped behavior fingerprint used for comparison.
            current = fingerprint(path)
        # Preserve the caught failure that explains why the external result is unusable.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except SyntaxError as exc:
            yield Failure("behaviour", name, f"does not parse: {exc.msg} at line {exc.lineno}")
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Report behavior drift when the current fingerprint differs from its recorded identity.
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
        Each paths element represents one repository path; traversal order is preserved.
    @param root the repository root
    @return one failure per reported finding
    """
    # Return the empty-result contract when the caller selected no governed paths.
    if not paths:
        # Return one failure per reported finding to the caller.
        return
    # Execute the named checker with this interpreter so imports match the active environment.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        [sys.executable, "-m", f"checks.{module}", *(str(p) for p in paths)],
        capture_output=True, text=True, cwd=root / "enforce", check=False,
    )
    # Parse each checker output line in emission order.
    for line in finished.stdout.splitlines():
        # Retain only top-level finding lines, excluding indented remedies and summaries.
        if ":" in line and not line.startswith((" ", "\t")) and "finding(s)" not in line:
            yield Failure(module, *_split_location(line, root))


def run_ruff(paths: Sequence[Path], root: Path) -> Iterator[Failure]:
    """Run the pydocstyle presence and shape rules.

    @param paths the files to check
        Each paths element represents one repository path; traversal order is preserved.
    @param root the repository root
    @return one failure per reported diagnostic
    """
    # Return the empty-result contract when the caller selected no governed paths.
    if not paths:
        # Return one failure per reported diagnostic to the caller.
        return
    # Run only the pydocstyle subset used by this gate and force parseable output.
    finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        [_ruff(), "check", "--no-cache", "--select", RUFF_RULES,
         "--output-format", "concise", *(str(p) for p in paths)],
        capture_output=True, text=True, cwd=root, check=False,
        # ruff colourizes even when stdout is a pipe, and the escape codes break
        # every attempt to parse a location out of the line.
        env={**os.environ, "NO_COLOR": "1"},
    )
    # Normalize each emitted diagnostic in original order.
    for raw in finished.stdout.splitlines():
        # Strip terminal color escapes before parsing the source location.
        line = _ANSI.sub("", raw)
        # A Python source location distinguishes diagnostics from Ruff summaries.
        if ".py:" in line:
            yield Failure("ruff", *_split_location(line, root))


def _ruff() -> str:
    """The ruff executable, found beside the interpreter rather than on PATH.

    A subprocess does not inherit an activated environment's PATH reliably, and
    a gate that cannot find its linter reports success by accident.

    @return an absolute path to ruff, or the bare name as a last resort
    """
    # Probe environment-relative executable locations in platform-neutral preference order.
    for candidate in (
        Path(sys.executable).parent / "ruff.exe",
        Path(sys.executable).parent / "ruff",
        Path(sys.executable).parent / "Scripts" / "ruff.exe",
    ):
        # Use the first installed candidate rather than an unrelated executable on PATH.
        if candidate.exists():
            # Return an absolute path to ruff, or the bare name as a last resort to the caller.
            return str(candidate)
    # Return an absolute path to ruff, or the bare name as a last resort to the caller.
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
        # Return the path and the remaining message to the caller.
        return "-", line.strip()
    where = Path(found.group("path"))
    try:
        # Convert an in-repository location to a portable relative display path.
        shown = where.resolve().relative_to(root).as_posix()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (ValueError, OSError):
        # Fall back to the basename when resolution or confinement cannot be established.
        shown = where.name
    return f"{shown}:{found.group('line')}", found.group("rest").lstrip(": ").strip()


def gate(paths: Sequence[Path], root: Path) -> list[Failure]:
    """Every gate, over the given files.

    @param paths the files to check
        Each paths element represents one repository path; traversal order is preserved.
    @param root the repository root
    @return every failure found, behaviour first
    """
    # Expand paths once so all gate mechanisms inspect the identical ordered file set.
    files = list(iter_python(paths))
    # Return every failure found, behaviour first to the caller.
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
    # A non-empty path list selects the audited subset re-recording workflow.
    if args.paths:
        # A subset re-record. This is the path that must never be silent:
        # rerecord_baseline refuses outright when reason is missing or blank,
        # so there is no way to reach a written file without one.
        if not args.reason:
            parser.error("--reason is required when re-recording specific "
                          "files with --baseline (a full --baseline with no "
                          "paths does not need one)")
        # Each element is one resolved CLI target path; argument order is preserved.
        paths = [p if p.is_absolute() else (root / p) for p in args.paths]
        try:
            # Re-record the validated target set and retain its non-vacuity count.
            count = rerecord_baseline(root, paths, args.reason)
        # Preserve the caught failure that explains why the external result is unusable.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ValueError as exc:
            parser.error(str(exc))
        print(f"re-recorded {count} fingerprint(s) in "
              f"{BASELINE_PATH.relative_to(root).as_posix()} -- {args.reason}")
        return 0
    # A historical ref selects source from Git rather than the working tree.
    if args.from_ref:
        print(f"recorded {write_baseline_from_ref(root, args.from_ref)} fingerprint(s) "
              f"from {args.from_ref} in "
              f"{BASELINE_PATH.relative_to(root).as_posix()}")
        # Return 0; every path either prints a result or exits through `parser.error` to the
        # caller.
        return 0
    print(f"recorded {write_baseline(root)} fingerprint(s) in "
          f"{BASELINE_PATH.relative_to(root).as_posix()}")
    # Return 0; every path either prints a result or exits through `parser.error` to the caller.
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 when every gate passes, 1 otherwise
    """
    # Normalize console encoding before any diagnostic is emitted on Windows.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Configure the command-line parser that defines this tool's invocation contract.
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
    # Capture the validated invocation arguments that govern this execution.
    args = parser.parse_args(argv)
    # Canonicalize the selected root once for every subsequent confinement calculation.
    root = args.root.resolve()

    # Baseline modes terminate before any documentation checks are scheduled.
    if args.baseline:
        # Return the aggregate process status to the command-line boundary.
        return _run_baseline(args, parser, root)

    # Select all governed roots or explicit CLI paths while preserving argument order.
    targets = (covered_paths(root) if args.all or not args.paths
               else [p if p.is_absolute() else (root / p) for p in args.paths])
    # Collect all failures in gate order so the report preserves causal priority.
    failures = gate(targets, root)
    # Return success only when no localized gate failure remains.
    if not failures:
        # Count expanded source files so a successful result is visibly non-vacuous.
        count = len(list(iter_python(targets)))
        print(f"documentation gate: {count} file(s) clean")
        # Return the aggregate process status to the command-line boundary.
        return 0

    # Map each gate-name key to its failure-count value; insertion order is deliberately
    # irrelevant because reporting sorts the keys.
    by_gate: dict[str, int] = {}
    # Aggregate every failure before truncating detailed display.
    for failure in failures:
        # Increment the mechanism-specific count without losing first occurrence.
        by_gate[failure.gate] = by_gate.get(failure.gate, 0) + 1
    # Render at most two hundred detailed findings to keep CI logs bounded.
    for failure in failures[:200]:
        print(failure.render())
    # Announce suppressed detail when the bounded report omitted failures.
    if len(failures) > 200:
        print(f"  ... and {len(failures) - 200} more")
    # Print gate counts in lexical order so equivalent failures produce identical output.
    print("\n" + ", ".join(f"{gate_name}={n}" for gate_name, n in sorted(by_gate.items())))
    print(f"documentation gate: {len(failures)} failure(s)")
    # Return the aggregate process status to the command-line boundary.
    return 1


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
