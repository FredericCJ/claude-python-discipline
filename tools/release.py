"""Build the redistributable archive of this discipline.

    python tools/release.py                  # -> dist/agent-discipline-v5.0.0.zip
    python tools/release.py --keep-staging    # leave the staged tree for inspection

The archive is produced by running the real installer against a scratch
repository, never by copying files by hand. What ships is therefore exactly what
`vendor.py install` produces, and a file the installer would not write cannot
reach an adopter because someone dragged a folder.

Unzipped at a repository root the archive yields `.agent/` -- the layout
`tools/integrate.py` expects, so nothing has to be moved afterwards -- plus two
documents at the root. Those are there because `.agent/` is a hidden directory:
an agent told "integrate the discipline that is already in this repo" has to be
able to see that something arrived.

The eleven-step gate runs first, from `tools/gate.py`: an archive is never cut
from a tree that fails it. Until v1.1.0 nothing here checked that, so a release
could be, and was, buildable from a tree with stale generated artifacts and a
failing suite. Four more gates then stand between the staged tree and the zip,
because a defective release ships silently to every adopter and cannot be
recalled:

1. **Pruning.** Caches, build products and databases are deleted from the staged
   tree and named in the output. The installer already skips them; this catches
   the case where it stops doing so.
2. **The ledger is empty.** The learning ledger is project-owned and every entry
   in this repository's own is about this repository, several naming absolute
   paths on the machine that wrote them. A release carrying them would hand each
   adopter another project's notes as if they were rules.
3. **Dependency closure.** Every Python distribution the canonical project gate
   can require has an exact pin in the shipped requirements file.
4. **Leak scan.** Every shipped text file is read and matched against absolute
   user paths, the building account's own identifiers, and credential shapes. A
   blocking match fails the build; a reviewable match is printed and counted.
"""

from __future__ import annotations

import argparse
import io
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Final

import gate
import vendor
from discipline_core import REPO_ROOT

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence

## Where the built archive is written. A build product, and gitignored as one.
DIST_DIR: Final = REPO_ROOT / "dist"

## Documents copied to the archive root, beside `.agent/`. The first is the
## pointer an agent reads on finding an unfamiliar repository; the second is the
## release's own account of itself, limits included.
## Each element is an archive-root document filename in copy and archive order.
ROOT_DOCUMENTS: Final[tuple[str, ...]] = (
    "INSTALL-DISCIPLINE.md",
    f"RELEASE-NOTES-{vendor.RELEASE}.md",
)

## Where the archive-root documents are authored, relative to the source
## checkout and tried in this order. `INSTALL-DISCIPLINE.md` lives under
## `packaging/` because it addresses someone who has just unzipped, which is
## nobody in this repository; the release notes live at the root because they
## are this repository's own record as well as the archive's.
## Each element is a repository-relative source directory in lookup-precedence order.
DOCUMENT_SOURCES: Final[tuple[str, ...]] = ("packaging", ".")

## Members that must exist in the finished archive. Each is load-bearing for one
## of the two scenarios, so their absence is a build failure and not a warning.
## Each element is an archive-relative path whose presence is checked in declaration order.
REQUIRED_MEMBERS: Final[tuple[str, ...]] = (
    ".agent/.dockerignore",
    ".agent/dev/Dockerfile",
    ".agent/dev/container-entrypoint.sh",
    ".agent/dev/docker.sh",
    ".agent/dev/windows.cmd",
    ".agent/dev/windows.ps1",
    ".agent/tools/integrate.py",
    ".agent/tools/migrate_v5.py",
    ".agent/discipline/KERNEL.md",
    ".agent/enforce/Doxyfile",
    ".agent/enforce/templates/documentation-model.json",
    ".agent/skills/python-discipline/SKILL.md",
    ".agent/INTEGRATION.md",
    ".agent/MANIFEST.json",
    ".agent/environment.yml",
    ".agent/requirements.txt",
    "INSTALL-DISCIPLINE.md",
)

## Python distributions needed by the vendored tools and every supported gate branch.
## Doxygen is checked separately as a native executable and cannot appear here.
REQUIRED_PYTHON_DISTRIBUTIONS: Final[frozenset[str]] = frozenset({
    "build",
    "cosmic-ray",
    "import-linter",
    "jsonschema",
    "mypy",
    "pyright",
    "pytest",
    "pytest-randomly",
    "pytest-socket",
    "pytest-timeout",
    "pyyaml",
    "ruff",
})
## PEP 503 normalization for names in the deliberately simple exact-pin manifest.
_DISTRIBUTION_PUNCTUATION: Final = re.compile(r"[-_.]+")

## Directories deleted from the staged tree wholesale.
PRUNED_DIRS: Final[frozenset[str]] = frozenset({
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache", ".hypothesis",
    ".import_linter_cache",
    ".git", "build", "dist", ".venv", "node_modules",
})

## File suffixes deleted from the staged tree: byte-compiled code, live
## databases, and archives that would nest a build inside a build.
PRUNED_SUFFIXES: Final[frozenset[str]] = frozenset({
    ".pyc", ".pyo", ".db", ".db-wal", ".db-shm", ".sqlite", ".sqlite3", ".zip",
})

## Anything under the vendored `learning/` other than these is a record from the
## building repository's own sessions and must not ship.
LEDGER_SEEDS: Final[frozenset[str]] = frozenset(vendor.LEARNING_SEED)

## Matches that fail the build. Shapes, not values: an absolute path rooted in a
## user's home directory identifies the machine it was written on, and the token
## prefixes are the published formats of credentials people paste by accident.
## Each element pairs a diagnostic label with a leak regex; scan order is preserved.
BLOCKING_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("windows user path", re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+", re.IGNORECASE)),
    # The lookbehind excludes `:` so a Windows path is reported once, by the
    # pattern above, rather than twice.
    ("posix home path", re.compile(r"(?<![\w.:])/(?:home|Users)/[A-Za-z0-9._-]+/")),
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("github token", re.compile(r"\b(?:ghp|gho|ghs|ghu|github_pat)_[A-Za-z0-9_]{20,}")),
    ("aws access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
    ("openai-style key", re.compile(r"\bsk-[A-Za-z0-9]{24,}")),
)

## Matches worth a human's eye that do not fail the build. An assignment that
## looks like a credential is usually an example in the corpus -- the rules about
## redaction have to show what redaction is for -- so the build reports these
## and leaves the judgement to the person reading the output.
## Each element pairs a diagnostic label with a review regex; scan order is preserved.
REVIEW_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("credential-shaped assignment", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|access[_-]?token|authorization)"
        r"\s*[:=]\s*[\"'][^\"']{6,}[\"']")),
    ("email address", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
)

## Members excused from a named blocking pattern, each with the reason that
## makes the excuse legitimate. An unjustified relaxation is a defect, so the
## reason is stored beside the entry and printed whenever one is used.
##
## The residual risk is stated rather than hidden: an entry excuses a whole file
## for one pattern, so a genuine leak of that same shape in that same file would
## pass. Every entry below names a file whose contents are synthetic by
## construction -- fixtures asserting that a guard rejects a shape, and the
## syntax-tree fingerprints of those fixtures.
## Each element gives an archive path, pattern label, and justification; declaration order is
## preserved for deterministic review output.
ALLOWED: Final[tuple[tuple[str, str, str], ...]] = (
    ("tools/test_learn.py", "github token",
     "proof-of-failure fixtures for learn.py's own credential guard (DIAG-014)"),
    ("tools/test_learn.py", "aws access key", "the same fixtures"),
    ("tools/test_learn.py", "private key", "the same fixtures"),
    ("tools/test_learn.py", "posix home path", "the same fixtures"),
    ("tools/test_release.py", "windows user path",
     "fixtures proving this scanner catches the shape"),
    ("tools/test_release.py", "posix home path", "the same fixtures"),
    ("tools/doc_baseline.json", "github token",
     "syntax-tree fingerprints, which carry those fixtures' string literals"),
    ("tools/doc_baseline.json", "aws access key", "the same fingerprints"),
    ("tools/doc_baseline.json", "private key", "the same fingerprints"),
    ("tools/doc_baseline.json", "posix home path", "the same fingerprints"),
    ("tools/doc_baseline.json", "windows user path", "the same fingerprints"),
)

## The fixed timestamp every member is stamped with. Zip entries carry an
## mtime, so stamping them from the clock would make two builds of the same
## corpus differ byte for byte and defeat any attempt to verify one (DEP-008).
## 1980-01-01 is the earliest a zip can represent.
## Each element is respectively year, month, day, hour, minute, then second; tuple order follows
## ``ZipInfo.date_time``.
ZIP_EPOCH: Final[tuple[int, int, int, int, int, int]] = (1980, 1, 1, 0, 0, 0)

## Regular file, readable by all, writable by the owner: what a checkout of the
## source repository has. Zip carries permissions in the high half of the field.
ZIP_FILE_MODE: Final = 0o644 << 16

## Directory, traversable by all. The low bit is the MS-DOS directory flag, which
## is what most extractors actually read.
ZIP_DIR_MODE: Final = (0o755 << 16) | 0x10


@dataclass(frozen=True, slots=True)
class Finding:
    """One pattern match in a file that is about to ship."""

    ## The file, as it will be named inside the archive.
    member: str
    ## Where in that file, counting from 1.
    line: int
    ## Which pattern matched, by its name in `BLOCKING_PATTERNS` or `REVIEW_PATTERNS`.
    pattern: str
    ## The matched text, trimmed for a terminal.
    excerpt: str

    def render(self) -> str:
        """Format the finding for a terminal.

        @return a single line naming the file, the line and what matched
        """
        # Return a single line naming the file, the line and what matched to the caller.
        return f"  {self.member}:{self.line}: {self.pattern}: {self.excerpt}"


## The shortest identifier worth matching. A one- or two-character login name
## would match most of the corpus and localize nothing.
MINIMUM_IDENTIFIER: Final = 3

## Identifiers that carry no signal because source is full of them. A machine or
## account named `main` turns the scan into a match on `def main(`, `__main__`
## and every mention of the branch, which is thousands of blocking findings and a
## build that can never complete on that host. Such an identifier is dropped, and
## `unusable_identifiers` reports the drop so a weaker scan is never a silent one.
COMMON_IDENTIFIERS: Final[frozenset[str]] = frozenset({
    "main", "master", "test", "tests", "build", "user", "users", "home", "src",
    "dev", "app", "apps", "root", "admin", "local", "temp", "tmp", "data",
    "code", "python", "windows", "linux", "darwin", "node", "run", "lib", "bin",
})

## Fixed disposable home authored into the container image rather than inherited from a builder.
PACKAGE_RUNTIME_HOME: Final = str(PurePosixPath("/", "tmp", "python-discipline-home"))
## Fixed public environment values authored by this package rather than inherited
## from the account or machine that happens to build it.
PACKAGE_OWNED_IDENTIFIERS: Final[frozenset[str]] = frozenset({
    PACKAGE_RUNTIME_HOME,
})


def build_identity() -> tuple[str | None, str | None, str | None]:
    """The account and machine this build is running as.

    Read here rather than in the scan so the same three values decide both the
    patterns and the report of what had to be dropped.

    @return the login name, the machine name and the home directory, each as the
        environment gives it or None where it says nothing
    """
    # Return the login name, the machine name and the home directory, each as the to the caller.
    return (
        os.environ.get("USERNAME") or os.environ.get("USER"),
        platform.node(),
        os.environ.get("USERPROFILE") or os.environ.get("HOME"),
    )


def _named_identifiers(
    username: str | None, hostname: str | None, home: str | None,
) -> tuple[tuple[str, str | None], ...]:
    """The three build identifiers under the labels findings are reported by.

    @param username the building account's login name
    @param hostname the building machine's name
    @param home the building account's home directory
    @return each value beside the label a finding would name it by
    """
    # Return each value beside the label a finding would name it by to the caller.
    return (("build username", username), ("build hostname", hostname),
            ("build home directory", home))


def _unusable_because(value: str | None) -> str | None:
    """Why an identifier cannot serve as a leak signal.

    @param value the identifier as the environment gave it
    @return the reason it is unusable, or None when it can be matched on
    """
    # Select the guarded path only after `value is None or not value.strip()` is satisfied.
    if value is None or not value.strip():
        # Return the reason it is unusable, or None when it can be matched on to the caller.
        return "absent"
    # Compute cleaned using value.strip for later unusable because logic.
    cleaned = value.strip()
    # Exclude a fixed package-owned sandbox value that cannot identify the current builder.
    if cleaned.replace("\\", "/").rstrip("/") in PACKAGE_OWNED_IDENTIFIERS:
        # Return the explicit non-identity reason for release diagnostics.
        return "fixed package-owned runtime path, not a builder identity"
    # Select the guarded path only after `len(cleaned) < MINIMUM_IDENTIFIER` is satisfied.
    if len(cleaned) < MINIMUM_IDENTIFIER:
        # Return the reason it is unusable, or None when it can be matched on to the caller.
        return f"shorter than {MINIMUM_IDENTIFIER} characters"
    # Select the guarded path only after `cleaned.lower() in COMMON_IDENTIFIERS` is satisfied.
    if cleaned.lower() in COMMON_IDENTIFIERS:
        # Return the reason it is unusable, or None when it can be matched on to the caller.
        return "too common in source to distinguish a leak from ordinary code"
    # Return the reason it is unusable, or None when it can be matched on to the caller.
    return None


def environment_literals(
    username: str | None, hostname: str | None, home: str | None,
) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Patterns for the identifiers of the account building the release.

    Derived from the environment rather than written down, so the scan protects
    whoever runs it and not only the machine it was first written on. Three kinds
    of value are dropped: absent ones, ones below `MINIMUM_IDENTIFIER`, and ones
    in `COMMON_IDENTIFIERS`.

    Each surviving pattern is bounded so it matches a whole identifier only. The
    bounds are lookarounds rather than `\\b`, because a home directory begins and
    ends with characters that `\\b` would place the boundary on the wrong side of.

    @param username the building account's login name
    @param hostname the building machine's name
    @param home the building account's home directory
    @return one case-insensitive pattern per usable identifier
    """
    # Treat the current label, value as the candidate element consumed by the enclosing
    # Details: transformation.
    # Return one case-insensitive pattern per usable identifier to the caller.
    return tuple(
        (label, re.compile(rf"(?<!\w){re.escape(value.strip())}(?!\w)", re.IGNORECASE))
        for label, value in _named_identifiers(username, hostname, home)
        if value is not None and _unusable_because(value) is None
    )


def unusable_identifiers(
    username: str | None, hostname: str | None, home: str | None,
) -> tuple[tuple[str, str, str], ...]:
    """Every identifier the scan was given and had to drop, with the reason.

    An absent value is not reported: there is nothing remarkable about a machine
    that does not set `USER`. A value that is present and still unusable is
    reported, because it means this build is being scanned with fewer signals
    than usual and nothing else would say so.

    @param username the building account's login name
    @param hostname the building machine's name
    @param home the building account's home directory
    @return the label, the value and the reason, for each present-but-unusable one
    """
    # Each dropped element is a label/value/refusal-reason triple in identifier-probe order.
    dropped = []
    # Treat the current label, value as the candidate element consumed by the enclosing
    # Details: transformation.
    # Advance unusable identifiers through the current input element in declared order.
    for label, value in _named_identifiers(username, hostname, home):
        # Select the guarded path only after `value is None or not value.strip()` is satisfied.
        if value is None or not value.strip():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute reason using  unusable because for later unusable identifiers logic.
        reason = _unusable_because(value)
        # Use the available-value path only when reason is present.
        if reason is not None:
            dropped.append((label, value.strip(), reason))
    # Return the label, the value and the reason, for each present-but-unusable one to the
    # Details: caller.
    return tuple(dropped)


def scan_text(
    member: str, text: str, patterns: Iterable[tuple[str, re.Pattern[str]]],
) -> Iterator[Finding]:
    """Every pattern match in one file's text.

    @param member the file, named as it will be inside the archive
    @param text the file's decoded contents
    @param patterns the named patterns to apply
    @return one finding per match, in line order
    """
    # Compute compiled using tuple for later scan text logic.
    compiled = tuple(patterns)
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance scan text through the current input element in declared order.
    for number, line in enumerate(text.splitlines(), start=1):
        # Select label, pattern as the current element from compiled while scan text preserves
        # Details: traversal order.
        # Advance scan text through the current input element in declared order.
        for label, pattern in compiled:
            # Preserve the optional pattern match that carries the reported analysis count.
            found = pattern.search(line)
            # Use the available-value path only when found is present.
            if found is not None:
                yield Finding(member, number, label, found.group(0)[:80])


def unsafe_members(names: Sequence[str]) -> list[str]:
    """Archive member names that would write outside the extraction directory.

    An absolute name, a drive letter or a `..` segment lets an archive place a
    file anywhere the unzipping user can write. No archive this tool builds
    should contain one; checking is how that stays true.

    @param names the member names to judge
        Each element is an archive path; input order is preserved among rejected names.
    @return every name that is absolute, drive-qualified or escapes upwards
    """
    # Normalize the current repository path to its portable baseline key spelling.
    # Return every name that is absolute, drive-qualified or escapes upwards to the caller.
    return [
        name for name in names
        if name.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:", name)
        or ".." in name.replace("\\", "/").split("/")
    ]


def stage(source: Path, staging: Path) -> tuple[int, list[str]]:
    """Install the discipline into a fresh repository the way an adopter would.

    The staging directory is made a git repository first, because that is the
    situation the installer is written for and a release must not be built in a
    situation nobody ships into.

    @param source the upstream checkout to install from
    @param staging an empty directory to install into
    @return how many upstream files the manifest records, and the installer's
            own notes about the project-owned half

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    staging.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        ["git", "init", "--quiet", str(staging)],
        capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    # Return how many upstream files the manifest records, and the installer's to the caller.
    return vendor.install(vendor.Plan(source.resolve(), staging.resolve()))


def prune(root: Path) -> list[str]:
    """Delete everything from a staged tree that must not ship.

    @param root the staged tree
    @return each deleted path, relative to `root`, in the order removed

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Each removed element is one pruned archive-relative path in deepest-first traversal order.
    removed: list[str] = []
    # Visit each staged path deepest-first so parent deletion cannot hide a child decision.
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        # Skip a child whose already-pruned parent removed it during the same traversal.
        if not path.exists():
            # Advance because a previously removed parent already consumed this path.
            continue
        # Compute relative using path.relative to for later prune logic.
        relative = path.relative_to(root).as_posix()
        # Refuse the target when its declared source directory is absent.
        if path.is_dir() and path.name in PRUNED_DIRS:
            shutil.rmtree(path)
            removed.append(f"{relative}/")
        # Select the regular-file path only when `path.is_file() and path.suffix in
        # Details: PRUNED_SUFFIXES` is satisfied.
        elif path.is_file() and path.suffix in PRUNED_SUFFIXES:
            # Publish the externally visible effect after all required inputs are ready.
            path.unlink()
            removed.append(relative)
    # Return each deleted path, relative to `root`, in the order removed to the caller.
    return removed


def ledger_problems(agent_dir: Path) -> list[str]:
    """Whatever in the staged `learning/` is not a seed.

    @param agent_dir the staged `.agent/` directory
    @return one line per file that would ship somebody else's learning, plus a
            line if the seeds themselves are missing
    """
    # Compute learning using agent_dir / "learning" for later ledger problems logic.
    learning = agent_dir / "learning"
    # Select the existing-artifact path only when `not learning.exists()` is satisfied.
    if not learning.exists():
        # Return one line per file that would ship somebody else's learning, plus a to the
        # Details: caller.
        return ["learning/ is missing; the installer did not seed it"]
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    problems = [
        f"learning/{path.relative_to(learning).as_posix()} is not a seed and must not ship"
        for path in sorted(learning.rglob("*")) if path.is_file()
        and path.relative_to(learning).as_posix() not in LEDGER_SEEDS
    ]
    # Unpack problems, seed using [ for later ledger problems logic.
    problems += [
        f"learning/{seed} is missing from the seeded ledger"
        for seed in sorted(LEDGER_SEEDS) if not (learning / seed).exists()
    ]
    # Return one line per file that would ship somebody else's learning, plus a to the caller.
    return problems


def requirement_problems(path: Path) -> list[str]:
    """Find absent, duplicate, or non-exact Python verifier requirements.

    The adopter manifest intentionally accepts only plain ``name==version`` lines.
    Environment markers and ranges could select different verifier bytes on two
    release platforms while both claimed to follow the same archive.

    @param path shipped requirements manifest
    @return stable diagnostics; empty only for complete exact pins
    """
    # Select the regular-file path only when `not path.is_file()` is satisfied.
    if not path.is_file():
        # Return stable diagnostics; empty only for complete exact pins to the caller.
        return [f"required dependency manifest is missing: {path}"]
    # Treat pins as mapping elements whose keys identify fields and values carry their content;
    # Details: key order is deliberately unused.
    pins: dict[str, str] = {}
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    problems: list[str] = []
    # Retain the immutable source representation consumed by subsequent analysis.
    # Advance requirement problems through the current input element in declared order.
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Preserve the current decoded diagnostic line before location normalization.
        line = raw.strip()
        # Select the empty-or-disabled path when line or line.startswith('#') has no usable
        # Details: value.
        if not line or line.startswith("#"):
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Normalize the current repository path to its portable baseline key spelling.
        name, separator, version = line.partition("==")
        # Compute normalized using  DISTRIBUTION PUNCTUATION.sub for later requirement problems
        # Details: logic.
        normalized = _DISTRIBUTION_PUNCTUATION.sub("-", name.strip()).lower()
        # Select the empty-or-disabled path when separator or not normalized or (not
        # Details: version.strip()) or (';' in version) has no usable value.
        if not separator or not normalized or not version.strip() or ";" in version:
            problems.append(f"requirements.txt:{number}: expected one exact name==version pin")
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `normalized in pins` is satisfied.
        if normalized in pins:
            problems.append(f"requirements.txt:{number}: duplicate pin for {normalized}")
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Update requirement problems state only after the required source facts are available.
        pins[normalized] = version.strip()
    # Format the relationship labels whose generated graph count is zero.
    problems.extend(
        f"requirements.txt: missing required distribution {missing}"
        for missing in sorted(REQUIRED_PYTHON_DISTRIBUTIONS - pins.keys())
    )
    # Return stable diagnostics; empty only for complete exact pins to the caller.
    return problems


def verify_requirements(agent_dir: Path) -> None:
    """Refuse a staged package whose adopter verifier set is incomplete.

    @param agent_dir staged `.agent` bundle
    @throws RuntimeError when the manifest is absent, floating, or incomplete
    """
    # Compute problems using requirement problems for later verify requirements logic.
    problems = requirement_problems(agent_dir / "requirements.txt")
    # Handle the non-empty or enabled problems state.
    if problems:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise RuntimeError(
            "the adopter dependency manifest is incomplete:\n  " + "\n  ".join(problems)
        )
    print(
        "adopter dependency manifest closes "
        f"{len(REQUIRED_PYTHON_DISTRIBUTIONS)} required Python distribution(s)"
    )


def members_of(root: Path) -> list[str]:
    """Every file in a staged tree, named as it will be in the archive.

    @param root the staged tree
    @return the member names, sorted, using forward slashes
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Return the member names, sorted, using forward slashes to the caller.
    return sorted(
        path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()
    )


def empty_dirs(root: Path) -> list[str]:
    """Directories in a staged tree that hold no file at any depth.

    A zip made only of files loses them, and one of them is load-bearing:
    `.agent/overrides/` is where a project puts its local waivers, and
    `vendor.py check` reports its absence as a broken install. An extractor
    creates a directory only if the archive names one.

    @param root the staged tree
    @return the directory names, sorted, each with a trailing slash
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Return the directory names, sorted, each with a trailing slash to the caller.
    return sorted(
        path.relative_to(root).as_posix() + "/"
        for path in root.rglob("*")
        if path.is_dir() and not any(child.is_file() for child in path.rglob("*"))
    )


def scan_tree(root: Path, members: Sequence[str]) -> tuple[list[Finding], list[str]]:
    """Read every member and match it against the leak patterns.

    @param root the staged tree
    @param members the member names to read
        Each element is one staged archive-relative path in archive order.
    @return every finding, blocking and reviewable together, and one note per
            file that could not be decoded as UTF-8
    """
    # Each patterns element pairs a diagnostic label with a regex, ordered as blocking, review,
    # then build-identity patterns.
    patterns = (
        *BLOCKING_PATTERNS,
        *REVIEW_PATTERNS,
        *environment_literals(*build_identity()),
    )
    # Each findings element is one emitted diagnostic mapping; checker order is preserved.
    findings: list[Finding] = []
    # Each undecodable element is one non-UTF-8 member path in archive order.
    undecodable: list[str] = []
    # Select member as the current element from members while scan tree preserves traversal
    # Details: order.
    # Advance scan tree through the current input element in declared order.
    for member in members:
        # Retain the immutable source representation consumed by subsequent analysis.
        raw = (root / member).read_bytes()
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Retain the immutable source representation consumed by subsequent analysis.
            text = raw.decode("utf-8")
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except UnicodeDecodeError:
            undecodable.append(member)
            # Advance after the current candidate has been conclusively excluded.
            continue
        findings.extend(scan_text(member, text, patterns))
    # Return every finding, blocking and reviewable together, and one note per to the caller.
    return findings, undecodable


def excuse(member: str, pattern: str) -> str | None:
    """The recorded reason a member is allowed to carry a blocking pattern.

    Matched on the archive member's tail, so an entry is written the way the
    file is named in the source tree (`tools/test_learn.py`) and still matches
    it wherever the installer places it (`.agent/tools/test_learn.py`).

    @param member the file, named as it is inside the archive
    @param pattern the name of the pattern that matched
    @return the recorded reason, or None when this match is not excused
    """
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance excuse through the current input element in declared order.
    for name, label, reason in ALLOWED:
        # Select the guarded path only after `pattern == label and (member == name or
        # Details: member.endswith(f'/{name}'))` is satisfied.
        if pattern == label and (member == name or member.endswith(f"/{name}")):
            # Return the recorded reason, or None when this match is not excused to the caller.
            return reason
    # Return the recorded reason, or None when this match is not excused to the caller.
    return None


def partition(findings: Sequence[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split findings into the ones that stop the build and the ones that do not.

    A finding does not stop the build when its pattern is reviewable rather than
    blocking, or when `ALLOWED` records a reason for that file to carry it.

    @param findings every finding from the scan
        Each findings element is one emitted diagnostic mapping; checker order is preserved.
    @return the blocking findings and the reviewable ones, each in scan order
    """
    # Collect unique reviewable element values; their order is deliberately unordered.
    reviewable = {label for label, _ in REVIEW_PATTERNS}
    # Each stops element is one unexcused blocking finding in scan order.
    stops: list[Finding] = []
    # Each seen element is one reviewable or excused finding in scan order.
    seen: list[Finding] = []
    # Select finding as the current element from findings while partition preserves traversal
    # Details: order.
    # Advance partition through the current input element in declared order.
    for finding in findings:
        # Compute passed using (finding.pattern in reviewable for later partition logic.
        passed = (finding.pattern in reviewable
                  or excuse(finding.member, finding.pattern) is not None)
        (seen if passed else stops).append(finding)
    # Return the blocking findings and the reviewable ones, each in scan order to the caller.
    return stops, seen


def copy_documents(source: Path, staging: Path) -> list[str]:
    """Place the archive-root documents beside the staged `.agent/`.

    @param source the upstream checkout, used to resolve the authored copies
    @param staging the staged tree
    @return the names copied, in archive order
    @throws FileNotFoundError if a required document has not been written
    """
    # Each copied element is one archive-root document name in required document order.
    copied: list[str] = []
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance copy documents through the current input element in declared order.
    for name in ROOT_DOCUMENTS:
        # Each candidates element is one possible authored source path in lookup-precedence order.
        candidates = [source / directory / name for directory in DOCUMENT_SOURCES]
        # Preserve the optional pattern match that carries the reported analysis count.
        found = next((path for path in candidates if path.is_file()), None)
        # Use the absence path when found has no available value.
        if found is None:
            # Format the relationship labels whose generated graph count is zero.
            missing = f"{name} is required at the archive root but was not found"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise FileNotFoundError(missing)
        shutil.copy2(found, staging / name)
        copied.append(name)
    # Return the names copied, in archive order to the caller.
    return copied


def write_archive(
    root: Path, members: Sequence[str], directories: Sequence[str], destination: Path,
) -> None:
    """Write the staged tree to a deterministic zip.

    Every entry is stamped with the same fixed time and mode, so two builds of
    the same corpus produce the same bytes and a published archive can be
    checked against a rebuild (DEP-008).

    @param root the staged tree
    @param members the member names to write, in the order they should appear
        Each element is one staged archive-relative file path in final archive order.
    @param directories names of directories to record explicitly, for the ones
                       that hold no file and would otherwise be lost
        Each element is one empty archive-relative directory path in final archive order.
    @param destination the archive to write, whose parent is created if absent

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Bind archive to the current value used by the next write archive decision.
    # Confine the acquired resource to this operation and release it on every exit.
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        # Normalize the current repository path to its portable baseline key spelling.
        # Advance write archive through the current input element in declared order.
        for name in directories:
            # Treat the current entry as the candidate element consumed by the enclosing
            # Details: transformation.
            entry = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            # Update write archive state only after the required source facts are available.
            entry.external_attr = ZIP_DIR_MODE
            archive.writestr(entry, b"")
        # Select member as the current element from members while write archive preserves
        # Details: traversal order.
        # Advance write archive through the current input element in declared order.
        for member in members:
            # Compute info using zipfile.ZipInfo for later write archive logic.
            info = zipfile.ZipInfo(member, date_time=ZIP_EPOCH)
            # Update write archive state only after the required source facts are available.
            info.compress_type = zipfile.ZIP_DEFLATED
            # Update write archive state only after the required source facts are available.
            info.external_attr = ZIP_FILE_MODE
            archive.writestr(info, (root / member).read_bytes())


def build(source: Path, destination: Path, staging: Path) -> tuple[int, list[Finding]]:
    """Stage, prune, verify, scan and write the archive.

    @param source the upstream checkout to install from
    @param destination the archive to write
    @param staging an empty directory to build in
    @return the number of members written, and every reviewable finding
    @throws RuntimeError if the ledger is not empty, a member path escapes the
            archive root, a required member is missing, or the scan finds
            anything blocking
    """
    # Preserve the observed item count used by the non-vacuity verdict.
    count, notes = stage(source, staging)
    print(f"staged {count} upstream file(s) into {staging}")
    # Preserve the optional baseline note while re-recording selected entries.
    # Advance build through the current input element in declared order.
    for note in notes:
        print(f"  {note}")

    # Compute removed using prune for later build logic.
    removed = prune(staging)
    print(f"pruned {len(removed)} path(s) that must not ship")
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Advance build through the current input element in declared order.
    for path in removed:
        print(f"  removed {path}")

    # Compute problems using ledger problems for later build logic.
    problems = ledger_problems(staging / ".agent")
    # Handle the non-empty or enabled problems state.
    if problems:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise RuntimeError("the ledger would not ship empty:\n  " + "\n  ".join(problems))
    print("ledger ships empty: seeds only")

    # Compute copied using copy documents for later build logic.
    copied = copy_documents(source, staging)
    print(f"archive root carries {', '.join(copied)}")

    # Compute members using members of for later build logic.
    members = members_of(staging)
    # Compute directories using empty dirs for later build logic.
    directories = empty_dirs(staging)
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance build through the current input element in declared order.
    for name in directories:
        print(f"recording empty directory {name}")
    # Compute escaping using unsafe members for later build logic.
    escaping = unsafe_members([*members, *directories])
    # Handle the non-empty or enabled escaping state.
    if escaping:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise RuntimeError("member path escapes the archive root: " + ", ".join(escaping))
    # Each absent element is one missing required-member path in declaration order.
    absent = [name for name in REQUIRED_MEMBERS if name not in members]
    # Handle the non-empty or enabled absent state.
    if absent:
        # Propagate the localized failure so callers cannot mistake it for success.
        raise RuntimeError("required member(s) missing: " + ", ".join(absent))
    verify_requirements(staging / ".agent")

    # Treat the current label, reason, value as the candidate element consumed by the enclosing
    # Details: transformation.
    # Advance build through the current input element in declared order.
    for label, value, reason in unusable_identifiers(*build_identity()):
        print(f"  leak scan dropped the {label} ({value!r}): {reason}")

    # Preserve finding-record elements in checker emission order for the final verdict.
    findings, undecodable = scan_tree(staging, members)
    # Select member as the current element from undecodable while build preserves traversal
    # Details: order.
    # Advance build through the current input element in declared order.
    for member in undecodable:
        print(f"  not UTF-8, shipped unread: {member}")
    # Unpack reviewable, stops using partition for later build logic.
    stops, reviewable = partition(findings)
    # Handle the non-empty or enabled stops state.
    if stops:
        # Select finding, rendered as the current element from stops) while build preserves
        # Details: traversal order.
        rendered = "\n".join(finding.render() for finding in stops)
        # Compute leaked using f"leak scan found {len(stops)} blocking match(es):\n{rendere for
        # Details: later build logic.
        leaked = f"leak scan found {len(stops)} blocking match(es):\n{rendered}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise RuntimeError(leaked)
    print(f"leak scan clean: {len(members)} member(s), "
          f"{len(reviewable)} reviewable match(es)")

    write_archive(staging, members, directories, destination)
    # Return the number of members written, and every reviewable finding to the caller.
    return len(members) + len(directories), reviewable


def run_gate(source: Path) -> list[str]:
    """Run the seven-step gate and report which steps refused.

    Until v1.1.0 nothing here checked it. The four gates in this module -- prune,
    empty ledger, dependency closure, and leak scan -- all ask whether the ARCHIVE
    is well formed, and
    none of them asks whether the corpus it was cut from is. An archive could be,
    and was, buildable from a tree whose tests failed and whose generated
    artifacts were stale.

    The tuple comes from `tools/gate.py`, the same one
    `enforce/fitness/test_meta.py` proves is runnable, so a step cannot be
    skipped here by being forgotten there.

    @param source the checkout to run the gate in
    @return the name of each step that did not exit 0, in gate order
    """
    # Each failed element names one unsuccessful gate step; execution order is preserved.
    failed: list[str] = []
    # Normalize the current repository path to its portable baseline key spelling.
    # Advance run gate through the current input element in declared order.
    for name, command in gate.GATE:
        # Preserve the external command representation and its observed completion outcome.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv from gate.GATE
            command, cwd=source, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        # Capture status as the completed run gate outcome for subsequent validation or
        # Details: publication.
        status = "ok" if finished.returncode == 0 else f"FAILED ({finished.returncode})"
        print(f"  gate: {name:<22} {status}")
        # Enter the failure path only when the subprocess reports a nonzero status.
        if finished.returncode != 0:
            failed.append(name)
            # Compute tail using (finished.stdout or finished.stderr or "").strip().splitline
            # Details: for later run gate logic.
            tail = (finished.stdout or finished.stderr or "").strip().splitlines()[-6:]
            # Preserve the current decoded diagnostic line before location normalization.
            # Advance run gate through the current input element in declared order.
            for line in tail:
                print(f"      {line}")
    # Return the name of each step that did not exit 0, in gate order to the caller.
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 when the archive was written, 1 when a gate refused it
    """
    # Select the guarded path only after `isinstance(sys.stdout, io.TextIOWrapper)` is
    # Details: satisfied.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description="Build the redistributable archive.")
    parser.add_argument("--source", type=Path, default=REPO_ROOT,
                        help="the upstream checkout to install from")
    parser.add_argument("--out", type=Path,
                        default=DIST_DIR / f"agent-discipline-{vendor.RELEASE}.zip",
                        help="where to write the archive")
    parser.add_argument("--staging", type=Path,
                        help="build here instead of a temporary directory")
    parser.add_argument("--keep-staging", action="store_true",
                        help="leave the staged tree in place for inspection")
    parser.add_argument("--skip-gate", action="store_true",
                        help="build without running the gate; the archive is unverified")
    # Capture the validated invocation arguments that govern this execution.
    args = parser.parse_args(argv)

    # Select the guarded path only after `args.skip_gate` is satisfied.
    if args.skip_gate:
        print("!! --skip-gate: the gate did NOT run. This archive is unverified and")
        print("!! must not be published. Use it for inspection only.")
    else:
        print("running the gate before staging anything")
        # Preserve failed step-name string elements in gate execution order.
        failed = run_gate(args.source)
        # Report aggregate failure only when at least one gate step was unsuccessful.
        if failed:
            print(f"refusing to build: {len(failed)} gate step(s) failed "
                  f"({', '.join(failed)}). A release cannot be recalled; fix the "
                  f"tree, or pass --skip-gate to build an archive marked unverified.",
                  file=sys.stderr)
            # Return the aggregate process status to the command-line boundary.
            return 1

    # Compute staging using args.staging or Path(tempfile.mkdtemp(prefix="agent-discipli for
    # Details: later main logic.
    staging = args.staging or Path(tempfile.mkdtemp(prefix="agent-discipline-"))
    # Select the existing-artifact path only when `staging.exists() and any(staging.iterdir())`
    # Details: is satisfied.
    if staging.exists() and any(staging.iterdir()):
        shutil.rmtree(staging)
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the observed item count used by the non-vacuity verdict.
        count, reviewable = build(args.source, args.out, staging)
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"\nrelease refused: {exc}")
        # Return the aggregate process status to the command-line boundary.
        return 1
    finally:
        # Select the existing-artifact path only when `not args.keep_staging and
        # Details: staging.exists()` is satisfied.
        if not args.keep_staging and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    # Select finding as the current element from reviewable while main preserves traversal
    # Details: order.
    # Advance main through the current input element in declared order.
    for finding in reviewable:
        # Compute why using excuse for later main logic.
        why = excuse(finding.member, finding.pattern)
        print(finding.render() + (f"  [allowed: {why}]" if why else "  [review]"))
    # Compute size using args.out.stat for later main logic.
    size = args.out.stat().st_size
    print(f"\nwrote {args.out} -- {count} member(s), {size:,} bytes, "
          f"release {vendor.RELEASE}")
    # Return the aggregate process status to the command-line boundary.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
