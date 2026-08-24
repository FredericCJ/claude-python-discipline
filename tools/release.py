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

# Keep annotation-only collection protocols out of the release tool's runtime imports.
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
        # Render archive identity, location, category, and bounded evidence as one terminal line.
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
    # Snapshot all builder-identifying environment inputs once so scan and diagnostics agree.
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
    # Attach stable diagnostic labels without changing the environment-provided values.
    return (("build username", username), ("build hostname", hostname),
            ("build home directory", home))


def _unusable_because(value: str | None) -> str | None:
    """Why an identifier cannot serve as a leak signal.

    @param value the identifier as the environment gave it
    @return the reason it is unusable, or None when it can be matched on
    """
    # Reject absent identity evidence before normalization could erase that distinction.
    if value is None or not value.strip():
        # Report absence separately from a present identifier that is too weak to scan.
        return "absent"
    cleaned = value.strip()
    # Exclude a fixed package-owned sandbox value that cannot identify the current builder.
    if cleaned.replace("\\", "/").rstrip("/") in PACKAGE_OWNED_IDENTIFIERS:
        # Return the explicit non-identity reason for release diagnostics.
        return "fixed package-owned runtime path, not a builder identity"
    if len(cleaned) < MINIMUM_IDENTIFIER:
        # Very short identities would match ordinary source too often to localize a leak.
        return f"shorter than {MINIMUM_IDENTIFIER} characters"
    if cleaned.lower() in COMMON_IDENTIFIERS:
        # Common repository vocabulary cannot distinguish host identity from authored content.
        return "too common in source to distinguish a leak from ordinary code"
    # A remaining identity is specific enough to become a bounded leak pattern.
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
    # Compile only usable identity values as bounded, case-insensitive literal patterns.
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
    # Collect present identities omitted from scanning so reduced coverage is visible to builders.
    # Each element is a label/value/reason triple retained in environment-probe order.
    dropped = []
    for label, value in _named_identifiers(username, hostname, home):
        # Absence supplies no sensitive literal and therefore needs no degraded-scan warning.
        if value is None or not value.strip():
            # Leave absent environment fields out of the present-but-unusable report.
            continue
        reason = _unusable_because(value)
        if reason is not None:
            # Preserve the exact omitted value and its refusal rationale for release output.
            dropped.append((label, value.strip(), reason))
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
    # Materialize the pattern stream once because every decoded line reuses the same scan set.
    compiled = tuple(patterns)
    for number, line in enumerate(text.splitlines(), start=1):
        # Test every leak category against the current physical line for precise diagnostics.
        for label, pattern in compiled:
            # Retain the optional match object because it supplies the exact reported excerpt.
            found = pattern.search(line)
            if found is not None:
                # Emit the bounded excerpt with its archive member and one-based line identity.
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
    # Retain only absolute, drive-qualified, or upward-traversing archive identities.
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
    Initializes ``staging`` as a Git repository and installs the discipline into that fresh
    adopter-shaped tree.
    """
    # Reproduce an adopter installation in a fresh Git repository before inspecting its output.
    staging.mkdir(parents=True, exist_ok=True)
    subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        ["git", "init", "--quiet", str(staging)],
        capture_output=True, encoding="utf-8", errors="replace", check=True,
    )
    return vendor.install(vendor.Plan(source.resolve(), staging.resolve()))


def prune(root: Path) -> list[str]:
    """Delete everything from a staged tree that must not ship.

    @param root the staged tree
    @return each deleted path, relative to `root`, in the order removed

    @par Effects
    Removes only excluded files and now-empty directories beneath ``root`` while recording
    each deleted relative path.
    """
    # Track each deletion while visiting deepest paths first so parent removal hides nothing.
    # Each element is an archive-relative path retained in actual deletion order.
    removed: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        # A removed parent may already have consumed a path from the precomputed traversal.
        if not path.exists():
            # Skip the stale traversal entry without recording a second deletion.
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_dir() and path.name in PRUNED_DIRS:
            # Remove excluded cache or build directories as complete staged subtrees.
            shutil.rmtree(path)
            removed.append(f"{relative}/")
        # Delete excluded individual artifacts after directories have received precedence.
        elif path.is_file() and path.suffix in PRUNED_SUFFIXES:
            # Remove excluded generated or nested-artifact files independently.
            path.unlink()
            removed.append(relative)
    return removed


def ledger_problems(agent_dir: Path) -> list[str]:
    """Whatever in the staged `learning/` is not a seed.

    @param agent_dir the staged `.agent/` directory
    @return one line per file that would ship somebody else's learning, plus a
            line if the seeds themselves are missing
    """
    # Compare staged learning contents with the immutable seed allowlist only. Each problem element
    # is one actionable ledger diagnostic in unexpected-file then missing-seed order.
    learning = agent_dir / "learning"
    if not learning.exists():
        # Missing seed storage proves the installer did not produce a valid discipline bundle.
        return ["learning/ is missing; the installer did not seed it"]
    problems = [
        f"learning/{path.relative_to(learning).as_posix()} is not a seed and must not ship"
        for path in sorted(learning.rglob("*")) if path.is_file()
        and path.relative_to(learning).as_posix() not in LEDGER_SEEDS
    ]
    problems += [
        f"learning/{seed} is missing from the seeded ledger"
        for seed in sorted(LEDGER_SEEDS) if not (learning / seed).exists()
    ]
    return problems


def requirement_problems(path: Path) -> list[str]:
    """Find absent, duplicate, or non-exact Python verifier requirements.

    The adopter manifest intentionally accepts only plain ``name==version`` lines.
    Environment markers and ranges could select different verifier bytes on two
    release platforms while both claimed to follow the same archive.

    @param path shipped requirements manifest
    @return stable diagnostics; empty only for complete exact pins
    """
    # Refuse absence before parsing because an empty dependency claim is not closed evidence.
    if not path.is_file():
        # Localize the missing shipped manifest for the release refusal.
        return [f"required dependency manifest is missing: {path}"]
    # Index accepted exact pins by normalized distribution name while retaining every defect.
    # Pin keys map to exact version values in manifest order; each problem is ordered by source.
    pins: dict[str, str] = {}
    problems: list[str] = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Normalize presentation whitespace without changing package or version spelling.
        line = raw.strip()
        if not line or line.startswith("#"):
            # Ignore manifest prose and separators; they declare no dependency.
            continue
        name, separator, version = line.partition("==")
        normalized = _DISTRIBUTION_PUNCTUATION.sub("-", name.strip()).lower()
        if not separator or not normalized or not version.strip() or ";" in version:
            # Ranges, markers, and malformed entries cannot identify one reproducible verifier.
            problems.append(f"requirements.txt:{number}: expected one exact name==version pin")
            continue
        if normalized in pins:
            # A second declaration makes dependency identity ambiguous even when versions agree.
            problems.append(f"requirements.txt:{number}: duplicate pin for {normalized}")
            continue
        # Retain the canonical name-to-version relation for closure comparison.
        pins[normalized] = version.strip()
    problems.extend(
        f"requirements.txt: missing required distribution {missing}"
        for missing in sorted(REQUIRED_PYTHON_DISTRIBUTIONS - pins.keys())
    )
    return problems


def verify_requirements(agent_dir: Path) -> None:
    """Refuse a staged package whose adopter verifier set is incomplete.

    @param agent_dir staged `.agent` bundle
    @throws RuntimeError when the manifest is absent, floating, or incomplete
    """
    # Aggregate all pinning and closure defects before refusing the staged package once.
    problems = requirement_problems(agent_dir / "requirements.txt")
    if problems:
        # Keep every actionable manifest defect in the single release-boundary failure.
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
    # Convert every staged regular file to a sorted portable archive identity.
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
    # Preserve only directory subtrees that contain no file and would vanish from a file-only zip.
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
    # Combine static secret shapes with current-builder identity literals for one complete scan.
    # Each pattern element is a label/regex pair in blocking, review, then environment order;
    # finding and undecodable-member elements preserve archive scan order.
    patterns = (
        *BLOCKING_PATTERNS,
        *REVIEW_PATTERNS,
        *environment_literals(*build_identity()),
    )
    findings: list[Finding] = []
    undecodable: list[str] = []
    for member in members:
        # Inspect the exact staged bytes that will enter the archive rather than source copies.
        raw = (root / member).read_bytes()
        # Decode text strictly so binary members cannot be misrepresented as partially scanned.
        try:
            # The complete UTF-8 representation is the only text admitted to pattern scanning.
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            # Disclose unscanned binary membership while preserving its bytes for packaging.
            undecodable.append(member)
            continue
        findings.extend(scan_text(member, text, patterns))
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
    # Require both the exact leak category and an exact or installed-suffix member identity.
    for name, label, reason in ALLOWED:
        # Grant an exception only when both dimensions match the recorded fixture declaration.
        if pattern == label and (member == name or member.endswith(f"/{name}")):
            # Expose the recorded fixture rationale instead of silently suppressing the match.
            return reason
    # Absence of a narrow recorded exception leaves the finding unexcused.
    return None


def partition(findings: Sequence[Finding]) -> tuple[list[Finding], list[Finding]]:
    """Split findings into the ones that stop the build and the ones that do not.

    A finding does not stop the build when its pattern is reviewable rather than
    blocking, or when `ALLOWED` records a reason for that file to carry it.

    @param findings every finding from the scan
        Each findings element is one emitted diagnostic mapping; checker order is preserved.
    @return the blocking findings and the reviewable ones, each in scan order
    """
    # Classify findings without reordering scanner output or discarding accepted evidence.
    # Each output element is the original finding in scan order, partitioned into blocking stops
    # or non-blocking seen evidence; reviewable labels form an unordered membership set.
    reviewable = {label for label, _ in REVIEW_PATTERNS}
    stops: list[Finding] = []
    seen: list[Finding] = []
    for finding in findings:
        # Only review-category patterns and exact fixture exceptions avoid the blocking set.
        passed = (finding.pattern in reviewable
                  or excuse(finding.member, finding.pattern) is not None)
        (seen if passed else stops).append(finding)
    return stops, seen


def copy_documents(source: Path, staging: Path) -> list[str]:
    """Place the archive-root documents beside the staged `.agent/`.

    @param source the upstream checkout, used to resolve the authored copies
    @param staging the staged tree
    @return the names copied, in archive order
    @throws FileNotFoundError if a required document has not been written
    """
    # Resolve each required root document through its declared authoring precedence. Each copied
    # element is a root filename in release order; candidate paths retain source precedence.
    copied: list[str] = []
    for name in ROOT_DOCUMENTS:
        # Preserve each candidate source path in declared precedence order for deterministic lookup.
        candidates = [source / directory / name for directory in DOCUMENT_SOURCES]
        found = next((path for path in candidates if path.is_file()), None)
        if found is None:
            # Refuse packaging before a release can omit its installation or release account.
            missing = f"{name} is required at the archive root but was not found"
            raise FileNotFoundError(missing)
        shutil.copy2(found, staging / name)
        copied.append(name)
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
    Creates the destination directory when needed and replaces ``destination`` with one
    deterministic archive assembled from the staged members.
    """
    # Establish the output location before opening one deterministic archive transaction.
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        # Materialize otherwise invisible empty directories with fixed timestamp and mode metadata.
        for name in directories:
            # Build a directory member record independent of checkout filesystem metadata.
            entry = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            entry.external_attr = ZIP_DIR_MODE
            archive.writestr(entry, b"")
        # Serialize staged file bytes in caller-provided order with host-independent metadata.
        for member in members:
            # Build a regular-file member record independent of checkout filesystem metadata.
            info = zipfile.ZipInfo(member, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
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
    # Construct the adopter-shaped staging tree and disclose every installer observation.
    count, notes = stage(source, staging)
    print(f"staged {count} upstream file(s) into {staging}")
    for note in notes:
        # Indent installer notes beneath the staging summary without changing their content.
        print(f"  {note}")

    # Remove non-shipping state before membership, closure, or leak evidence is computed.
    removed = prune(staging)
    print(f"pruned {len(removed)} path(s) that must not ship")
    for path in removed:
        # Make every defense-in-depth deletion independently reviewable in build output.
        print(f"  removed {path}")

    # Prove private learning history is absent while all required empty-ledger seeds remain.
    problems = ledger_problems(staging / ".agent")
    if problems:
        # Refuse the complete set of ledger violations at the release boundary.
        raise RuntimeError("the ledger would not ship empty:\n  " + "\n  ".join(problems))
    print("ledger ships empty: seeds only")

    # Add release-facing documents only after package-owned ledger contents are clean.
    copied = copy_documents(source, staging)
    print(f"archive root carries {', '.join(copied)}")

    # Freeze the final file and empty-directory inventories before validating archive identities.
    members = members_of(staging)
    directories = empty_dirs(staging)
    for name in directories:
        # Disclose each explicit directory member that file enumeration would otherwise hide.
        print(f"recording empty directory {name}")
    escaping = unsafe_members([*members, *directories])
    if escaping:
        # Prevent archive extraction from addressing anything outside its destination root.
        raise RuntimeError("member path escapes the archive root: " + ", ".join(escaping))
    # Retain each missing load-bearing archive identity in declaration order for one refusal.
    absent = [name for name in REQUIRED_MEMBERS if name not in members]
    if absent:
        # Refuse an internally consistent archive that still lacks a load-bearing member.
        raise RuntimeError("required member(s) missing: " + ", ".join(absent))
    verify_requirements(staging / ".agent")

    # Disclose every present builder identity omitted from dynamic leak protection.
    for label, value, reason in unusable_identifiers(*build_identity()):
        print(f"  leak scan dropped the {label} ({value!r}): {reason}")

    # Scan final staged bytes, preserving binary exceptions and all textual matches separately.
    findings, undecodable = scan_tree(staging, members)
    for member in undecodable:
        # Name each unscanned binary member so release review can account for the residual.
        print(f"  not UTF-8, shipped unread: {member}")
    stops, reviewable = partition(findings)
    if stops:
        # Render every blocking match into one refusal without losing member-level evidence.
        rendered = "\n".join(finding.render() for finding in stops)
        leaked = f"leak scan found {len(stops)} blocking match(es):\n{rendered}"
        raise RuntimeError(leaked)
    print(f"leak scan clean: {len(members)} member(s), "
          f"{len(reviewable)} reviewable match(es)")

    # Write bytes only after structure, dependency closure, and leak checks all accept the tree.
    write_archive(staging, members, directories, destination)
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
    # Execute the canonical gate sequence while retaining only failed step identities for refusal.
    # Each failed element is a canonical gate name in execution order.
    failed: list[str] = []
    for name, command in gate.GATE:
        # Capture the complete child outcome before reducing it to release diagnostics.
        finished = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv from gate.GATE
            command, cwd=source, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=False,
        )
        status = "ok" if finished.returncode == 0 else f"FAILED ({finished.returncode})"
        print(f"  gate: {name:<22} {status}")
        if finished.returncode != 0:
            # Preserve the failed gate name and a bounded diagnostic tail for terminal triage.
            failed.append(name)
            tail = (finished.stdout or finished.stderr or "").strip().splitlines()[-6:]
            for line in tail:
                # Indent child diagnostics beneath their canonical gate identity.
                print(f"      {line}")
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 when the archive was written, 1 when a gate refused it
    """
    # Stabilize terminal encoding when Python exposes a reconfigurable text stream.
    if isinstance(sys.stdout, io.TextIOWrapper):
        # Replace unencodable child diagnostics rather than losing the release verdict.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
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
    args = parser.parse_args(argv)

    # Make uncertified inspection mode unmistakable; normal mode must prove the source tree first.
    if args.skip_gate:
        print("!! --skip-gate: the gate did NOT run. This archive is unverified and")
        print("!! must not be published. Use it for inspection only.")
    else:
        # Preserve the failed gate identities so normal mode can refuse before staging.
        print("running the gate before staging anything")
        failed = run_gate(args.source)
        if failed:
            # Stop before staging when any canonical source-tree obligation failed.
            print(f"refusing to build: {len(failed)} gate step(s) failed "
                  f"({', '.join(failed)}). A release cannot be recalled; fix the "
                  f"tree, or pass --skip-gate to build an archive marked unverified.",
                  file=sys.stderr)
            return 1

    # Use caller-owned staging when supplied, otherwise allocate an isolated disposable root.
    staging = args.staging or Path(tempfile.mkdtemp(prefix="agent-discipline-"))
    if staging.exists() and any(staging.iterdir()):
        # Remove pre-existing staging contents so unrelated bytes cannot enter the inventory.
        shutil.rmtree(staging)
    # Translate expected release refusals to a stable command exit while always containing staging.
    try:
        # Retain archive membership and review evidence for the success-only terminal report.
        count, reviewable = build(args.source, args.out, staging)
    except (RuntimeError, FileNotFoundError) as exc:
        # Present policy or source-artifact refusal without an internal traceback.
        print(f"\nrelease refused: {exc}")
        return 1
    finally:
        # Preserve staging only for an explicit inspection request; normal runs leave no residue.
        if not args.keep_staging and staging.exists():
            # Delete only the selected staging root unless explicit inspection retention was asked.
            shutil.rmtree(staging, ignore_errors=True)

    # Surface non-blocking scan evidence after the archive is known to exist.
    for finding in reviewable:
        # Pair an exact built-in excuse with its match; otherwise mark it for human review.
        why = excuse(finding.member, finding.pattern)
        print(finding.render() + (f"  [allowed: {why}]" if why else "  [review]"))
    # Measure the completed artifact for the release summary and later hash verification.
    size = args.out.stat().st_size
    print(f"\nwrote {args.out} -- {count} member(s), {size:,} bytes, "
          f"release {vendor.RELEASE}")
    return 0

# Invoke release construction only when this module owns the process entry point.
if __name__ == "__main__":
    # Convert the command verdict to the process status expected by development gates.
    sys.exit(main())
