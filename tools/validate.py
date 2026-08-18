"""Validate the discipline corpus against `discipline/meta/SCHEMA.md`.

Exit code 0 when no error-severity finding is raised::

    python tools/validate.py [--json] [--root PATH]

Every finding carries a stable code and a remediation line, so a fix can be derived
from the output alone -- the same property the corpus demands of program errors.
Each check has a companion test in `test_validate.py` proving it fails when the
condition it guards is violated; a check never observed to fail has not been shown
to check anything.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import defaultdict
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

import jsonschema

from discipline_core import (
    REPO_ROOT,
    Document,
    Force,
    Kind,
    ParseError,
    Rule,
    body_without_fences,
    budget_for,
    count_tokens,
    find_version_literals,
    find_xrefs,
    mechanism_is_implemented,
    parse_document,
    prose_of,
)

## The JSON Schema every corpus file's front-matter is validated against. Kept
## beside this file so the checker and its schema cannot be separated.
SCHEMA_PATH: Final = Path(__file__).resolve().parent / "frontmatter.schema.json"

## The committed ceiling V081/V082 ratchet against. Kept beside this file, in the
## same idiom as `SCHEMA_PATH` and `tools/doc_baseline.json`: a checked-in record
## the tool itself writes, moved only by an explicit rerun with a reason.
V080_BASELINE_PATH: Final = Path(__file__).resolve().parent / "v080_baseline.json"

## How long a `verified:` date stands before V060 calls the document rotted, per
## `decay:` class. "none" is a sentinel large enough never to fire, so an
## explicitly undecaying document needs no special case downstream.
DECAY_DAYS: Final[dict[str, int]] = {
    "months": 120,
    "quarters": 270,
    "years": 730,
    "none": 10**6,
}

## Documents legitimately named in prose that are not corpus modules.
KNOWN_EXTERNAL_MD: Final[frozenset[str]] = frozenset(
    {"CLAUDE.md", "README.md", "SKILL.md", "SUPERSEDED.md", "MEMORY.md"}
)
## A backticked markdown filename, which V041 then has to resolve on disk. Only
## backticked mentions count -- unquoted prose says "the schema", not a path --
## and it is run over the body with fenced blocks removed, so an illustrative
## filename inside an example block is not held to existing.
_MD_MENTION = re.compile(r"`(?P<name>[A-Za-z0-9_./-]+\.md)`")
## A glossary heading that declares its term unusable without qualification.
_BARE_BANNED = re.compile(r"^###\s+(?P<term>.+?)\s*\[BARE-BANNED\]\s*$", re.MULTILINE)
## Tells a rule id from a module id, so an unresolved reference is reported as
## the right kind of thing to go looking for.
_RULE_ID = re.compile(r"^[A-Z][A-Z0-9]{1,7}-\d{3}$")

## How far an agent may have to walk from a module to reach any rule (V092).
REACH_DEPTH: Final = 3
## The first cell of a markdown table row whose second cell opens with a digit --
## i.e. a tool sitting next to a pinned version, in a fact module's table.
_TOOL_ROW = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9_.-]{2,})\s*\|\s*\d", re.MULTILINE)
## A candidate tool name inside a rule's **Check** line. Deliberately loose: it
## over-matches, and V095 only acts on the words that a fact module actually pins.
_TOOL_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


class Severity(StrEnum):
    """Whether a finding fails the run or is only put on the record.

    A `StrEnum` so that `--json` emits `"error"` with no encoder of its own; a
    plain `Enum` would fall through to `json.dumps(default=str)` and write
    "Severity.ERROR", a name no consumer agreed to.
    """

    ## The corpus is non-conformant; the process exits 1 until this is gone.
    ERROR = "error"
    ## Reported and counted, but the exit code stays 0. Used where the corpus is
    ## permitted to be incomplete so long as it is not permitted to hide it.
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class Finding:
    """One validation defect, addressable by `code` and fixable from `remediation`."""

    ## Stable identifier of the condition that was violated, e.g. "V050". Quoted
    ## from outside this file -- README.md, ENFORCEMENT.md, PROVENANCE.md -- so a
    ## code is never reassigned to a different condition, only retired.
    code: str
    ## Whether this fails the run or is only reported.
    severity: Severity
    ## The file the defect sits in, relative to `Layout.root` and POSIX-separated
    ## whatever the host, so the same corpus reports identically everywhere.
    path: str
    ## 1-based line to jump to; 1 when the defect belongs to the file as a whole
    ## rather than to any one of its lines.
    line: int
    ## What is wrong, quoting the offending text so the defect is recognisable
    ## without opening the file.
    message: str
    ## The action that clears it. Present on every finding without exception: a
    ## defect an agent cannot act on from the output alone is not yet reported.
    remediation: str

    def render(self) -> str:
        """Lay one finding out for a terminal, location first.

        The leading `path:line:` is the form editors and CI annotators already
        parse, so a finding is clickable without any adapter.

        @return two lines, the second indenting the remediation under the message
        """
        return (
            f"{self.path}:{self.line}: {self.severity.value.upper()} {self.code} "
            f"{self.message}\n    -> {self.remediation}"
        )


@dataclass(frozen=True, slots=True)
class Layout:
    """Where the corpus lives. Injected so the checks are testable in isolation.

    Every property below answers where a thing belongs, never whether it is
    there: each is a join, and none touches the filesystem. Callers that care
    about absence test for it themselves, so each property records which check
    depends on it and what happens when it is not there.
    """

    ## Everything below is resolved against this, so a test can point the whole
    ## checker at a temporary tree without touching global state.
    root: Path

    @property
    def discipline(self) -> Path:
        """The directory holding the corpus modules.

        @return the tree `load_documents` walks; absent, nothing parses and every
            per-document check is silent rather than failing
        """
        return self.root / "discipline"

    @property
    def enforce(self) -> Path:
        """Where the mechanisms live that decide the binding rules.

        @return the directory V080 resolves `check:` tags under, and one of the
            two it searches for a `fitness:` function
        """
        return self.root / "enforce"

    @property
    def examples(self) -> Path:
        """Long-form material lifted out of modules to keep them under budget.

        @return the directory whose `*.md` stems make up the `examples/...`
            namespace a V040 reference may resolve into
        """
        return self.discipline / "examples"

    @property
    def enforcement_ledger(self) -> Path:
        """The generated table pairing each rule with what decides it.

        No check here reads it; `build_index.py` writes it, and this property
        exists so the location is stated once for whoever needs it next.

        @return where that generation is expected to put the file
        """
        return self.enforce / "ENFORCEMENT.md"

    @property
    def open_ledger(self) -> Path:
        """Where undecided questions are written down, which V031 requires.

        @return the file V031 searches for each rule id; absent, it reads as
            empty and every [OPEN] rule is reported unrecorded
        """
        return self.discipline / "meta" / "OPEN.md"

    @property
    def glossary(self) -> Path:
        """The definitions of terms the sources used in incompatible senses.

        @return the file the banned terms are read from; absent, V070 has nothing
            to enforce and passes every document
        """
        return self.discipline / "meta" / "GLOSSARY.md"

    def rel(self, path: Path) -> str:
        """Render a location for display, anchored at `root`.

        Never raises: a path outside the tree is shown whole rather than costing
        a report its findings.

        @param path the location to display
        @return a POSIX-separated path, relative when it lies under `root` and
            absolute when it does not, so a stray location is still identifiable
        """
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()


## The real repository, used when no layout is injected.
DEFAULT_LAYOUT: Final = Layout(REPO_ROOT)


def _relpath(layout: Layout, doc: Document) -> str:
    """Adapt `Layout.rel` to a parsed document.

    Every check reports a file through here, so a defect in one document is named
    identically whichever check raised it and findings collate by path.

    @param layout the tree the document was read from
    @param doc the document being reported on
    @return its path relative to `layout.root`, POSIX-separated
    """
    return layout.rel(doc.path)


# --------------------------------------------------------------------------- checks


def check_front_matter(
    doc: Document, schema: dict[str, object], layout: Layout
) -> Iterator[Finding]:
    """V002-V004 -- front-matter conforms, and agrees with where the file sits.

    The two placement checks exist because front-matter is what everything else
    trusts; an id or a kind that disagrees with the filesystem sends every later
    check, and every agent, to the wrong document.

    @param doc the parsed corpus file
    @param schema the loaded front-matter JSON Schema
    @param layout the tree the document was read from
    @return one finding per schema violation, plus V003 when the id's last
        segment disagrees with the filename -- KERNEL.md is exempt by name -- and
        V004 when `kind:` disagrees with the directory, which is only tested for
        files that sit in a genre-named directory at all
    """
    validator = jsonschema.Draft202012Validator(schema)
    for error in sorted(validator.iter_errors(dict(doc.front_matter)), key=str):
        location = "/".join(str(p) for p in error.absolute_path) or "(root)"
        yield Finding(
            code="V002",
            severity=Severity.ERROR,
            path=_relpath(layout, doc),
            line=1,
            message=f"front-matter invalid at {location}: {error.message}",
            remediation="See discipline/meta/SCHEMA.md section 2.",
        )
    if doc.doc_id and doc.path.stem != "KERNEL":
        expected = doc.doc_id.split("/", 1)[-1]
        if doc.path.stem != expected:
            yield Finding(
                code="V003",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"front-matter id '{doc.doc_id}' does not match filename '{doc.path.stem}'",
                remediation=f"Rename the file to {expected}.md, or correct the id.",
            )
    kind_dir = doc.path.parent.name
    if doc.kind is not None and kind_dir in {k.value for k in Kind} and kind_dir != doc.kind.value:
        yield Finding(
            code="V004",
            severity=Severity.ERROR,
            path=_relpath(layout, doc),
            line=1,
            message=f"kind '{doc.kind.value}' does not match directory '{kind_dir}/'",
            remediation="Move the file, or correct `kind:`.",
        )


def check_genre_constraints(doc: Document, layout: Layout) -> Iterator[Finding]:
    """V010-V012 -- what each genre may do. SCHEMA.md section 1.

    A document whose `kind:` is missing -- or present but not a genre this format
    knows, which reaches here as the same absence -- is left alone. V002 has
    already reported it, and reporting the same file twice buries the finding that
    names the cause.

    @param doc the parsed corpus file
    @param layout the tree the document was read from
    @return findings for rules outside law/ and ops/, [BINDING] in frame/, and
        version pins in law/
    """
    if doc.kind is None:
        return
    if doc.kind not in {Kind.LAW, Kind.OPS}:
        for rule in doc.rules:
            yield Finding(
                code="V010",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=rule.line,
                message=f"{rule.rule_id}: only law/ and ops/ may carry rules; this is {doc.kind.value}/",
                remediation="Move the rule into a law/ module, or drop its force tag.",
            )
    if doc.kind is Kind.FRAME:
        for rule in doc.rules:
            if rule.force is Force.BINDING:
                yield Finding(
                    code="V011",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [BINDING] is not permitted in a frame/ document",
                    remediation="frame/ describes options; move the rule to law/.",
                )
    if doc.kind is Kind.LAW:
        for tool, version in find_version_literals(prose_of(doc)):
            yield Finding(
                code="V012",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"law/ pins a version: '{tool} ... {version}'",
                remediation="State the capability here; put the pin in a fact/ file with a verified: date.",
            )


def check_rules(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V020-V024 -- rule identity, and the mechanism-first axiom.

    Cross-document by necessity: an id collides only against the rest of the
    corpus, and the first definition wins so the report names a stable culprit.

    @param documents every parsed corpus file, in the order they were read
    @param layout the tree they were read from
    @return findings for duplicate ids, wrong prefixes, unchecked or unmechanised
        [BINDING] rules, and over-long titles
    """
    seen: dict[str, Rule] = {}
    for doc in documents:
        for rule in doc.rules:
            first = seen.get(rule.rule_id)
            if first is not None:
                yield Finding(
                    code="V020",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=(
                        f"duplicate rule id {rule.rule_id}, first defined at "
                        f"{layout.rel(first.path)}:{first.line}"
                    ),
                    remediation="Ids are assigned once and never reused; take the next free ordinal.",
                )
            else:
                seen[rule.rule_id] = rule

            if rule.prefix != doc.module_name.upper():
                yield Finding(
                    code="V021",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: prefix does not match module '{doc.module_name}'",
                    remediation=f"Use {doc.module_name.upper()}-NNN, or move the rule to its module.",
                )

            if rule.force is Force.BINDING and not rule.check:
                yield Finding(
                    code="V022",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [BINDING] without a **Check** line",
                    remediation="Name the command or test that decides it, or demote it with a justification.",
                )
            if rule.force is Force.BINDING and not rule.mechanisms:
                yield Finding(
                    code="V023",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [BINDING] without a mechanism tag",
                    remediation="Add [auto:...], [check:...] or [fitness:...]; nothing checks it otherwise.",
                )
            if len(rule.title) > 60:
                yield Finding(
                    code="V024",
                    severity=Severity.WARN,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: title is {len(rule.title)} chars (limit 60)",
                    remediation="Shorten it; the heading is the whole rule surface an agent greps.",
                )


def check_ledgers(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V030-V031 -- every [ADVISORY] and [OPEN] rule is accounted for in writing.

    A missing OPEN.md is not itself reported here; its absence simply makes every
    [OPEN] rule unaccounted for, which is the same defect stated per rule.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return findings for unjustified [ADVISORY] rules and unrecorded [OPEN] ones
    """
    opens = layout.open_ledger
    open_text = opens.read_text(encoding="utf-8") if opens.exists() else ""
    for doc in documents:
        for rule in doc.rules:
            if rule.force is Force.ADVISORY and not rule.no_mechanism:
                yield Finding(
                    code="V030",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [ADVISORY] without a **No mechanism** justification",
                    remediation="State why no mechanism is possible, or find one and make it [BINDING].",
                )
            if rule.force is Force.OPEN and rule.rule_id not in open_text:
                yield Finding(
                    code="V031",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [OPEN] with no entry in discipline/meta/OPEN.md",
                    remediation="Record the undecided question and what it blocks.",
                )


def check_xrefs(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V040-V041 -- every reference resolves. SCHEMA.md section 5.

    Two populations, checked separately: bracketed ids, which must name a rule,
    a module or an example; and backticked filenames, which must exist somewhere
    a reader would plausibly look. Names in `KNOWN_EXTERNAL_MD` are exempt, being
    real documents the corpus does not own.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return findings for unresolved ids and for filenames matching nothing on disk
    """
    rule_ids = {rule.rule_id for doc in documents for rule in doc.rules}
    module_ids = {doc.doc_id for doc in documents if doc.doc_id}
    example_ids = (
        {f"examples/{p.stem}" for p in layout.examples.glob("*.md")}
        if layout.examples.exists()
        else set()
    )

    for doc in documents:
        prose = prose_of(doc)
        for target in find_xrefs(prose):
            base = target.split("#", 1)[0]
            if base in rule_ids or base in module_ids or base in example_ids:
                continue
            kind = "rule" if _RULE_ID.match(base) else "module"
            yield Finding(
                code="V040",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"reference to undefined {kind} [{target}]",
                remediation="Fix the target or remove it; every reference must resolve.",
            )

        for match in _MD_MENTION.finditer(body_without_fences(doc)):
            name = match.group("name")
            if Path(name).name in KNOWN_EXTERNAL_MD:
                continue
            candidates = (
                layout.root / name,
                doc.path.parent / name,
                *(layout.root / d / name for d in ("discipline", "enforce", "sources")),
            )
            if any(c.exists() for c in candidates):
                continue
            yield Finding(
                code="V041",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"dangling document reference `{name}`",
                remediation="The source corpus carried ~130 of these; cite a corpus module or drop it.",
            )


def check_budgets(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V050 -- token ceilings, so a session can afford to load a module.

    Measured over the file as written, front-matter included, because that is
    what a reader actually pays to open it.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return one finding per document over the ceiling its genre allows
    """
    for doc in documents:
        budget = budget_for(doc)
        actual = count_tokens(doc.path.read_text(encoding="utf-8"))
        if actual > budget:
            yield Finding(
                code="V050",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"{actual} tokens exceeds the {budget}-token ceiling",
                remediation="Split the module, or move detail into discipline/examples/.",
            )


def check_freshness(
    documents: Sequence[Document], layout: Layout, *, today: dt.date | None = None
) -> Iterator[Finding]:
    """V060 -- dated genres are re-verified before they rot.

    Only documents declaring both `decay:` and a `verified:` date are aged; an
    undated document is simply not making the claim. An unrecognised decay class
    is treated as `years` rather than as no limit, so a typo cannot exempt a file
    outright.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @param today the date to measure against, injected so the check is deterministic
    @return a warning per document older than its declared decay allows
    @throws ValueError if a `verified:` string is not an ISO date
    """
    now = today or dt.date.today()
    for doc in documents:
        raw = doc.front_matter.get("verified")
        decay = doc.front_matter.get("decay")
        if not isinstance(decay, str):
            continue
        if isinstance(raw, dt.date):
            verified = raw
        elif isinstance(raw, str):
            verified = dt.date.fromisoformat(raw)
        else:
            continue
        age = (now - verified).days
        limit = DECAY_DAYS.get(decay, DECAY_DAYS["years"])
        if age > limit:
            yield Finding(
                code="V060",
                severity=Severity.WARN,
                path=_relpath(layout, doc),
                line=1,
                message=f"verified {age} days ago; decay is '{decay}' ({limit} days)",
                remediation="Re-verify each claim against its source, then update verified:.",
            )


def banned_terms(glossary: Path) -> dict[str, tuple[str, ...]]:
    """Map each `[BARE-BANNED]` term to the qualified forms the glossary approves.

    A qualified form is a bold phrase under the term's heading that contains it,
    e.g. ``- **branch coverage** -- ...`` approves "branch coverage".

    Each term's forms come back longest first, which is what lets a caller strip
    them one after another without a short form eating a longer one's prefix.

    @param glossary the glossary file, which may legitimately be absent
    @return each banned term mapped to its approved forms; a term the glossary
        qualifies nowhere maps to an empty tuple, which bans it outright rather
        than exempting it. Empty when there is no glossary to read.
    """
    if not glossary.exists():
        return {}
    text = glossary.read_text(encoding="utf-8")
    sections = list(_BARE_BANNED.finditer(text))
    approved: dict[str, tuple[str, ...]] = {}
    for index, match in enumerate(sections):
        term = match.group("term").strip().lower()
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        body = text[match.end() : end]
        phrases = {
            p.strip().lower()
            for p in re.findall(r"\*\*(.+?)\*\*", body)
            if term in p.lower() and p.strip().lower() != term
        }
        approved[term] = tuple(sorted(phrases, key=len, reverse=True))
    return approved


def check_glossary(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V070 -- terms the sources used in incompatible senses stay qualified.

    Quoting a source's own defective phrasing is legitimate; put it in backticks,
    which `prose_of` removes.

    The glossary itself is skipped -- it is where the bare term is defined, so
    flagging it would make the definition unwritable.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return one finding per banned term a document uses unqualified, so a file
        misusing three terms is reported three times; nothing at all when no
        glossary declares any
    """
    approved = banned_terms(layout.glossary)
    if not approved:
        return
    for doc in documents:
        if doc.path == layout.glossary:
            continue
        prose = prose_of(doc).lower()
        for term, qualified in approved.items():
            remaining = prose
            for phrase in qualified:  # longest first, so overlaps resolve correctly
                remaining = remaining.replace(phrase, " ")
            if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", remaining):
                allowed = ", ".join(f'"{q}"' for q in sorted(qualified)) or "a qualified form"
                yield Finding(
                    code="V070",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=1,
                    message=f"bare use of ambiguous term '{term}'",
                    remediation=f"Use one of: {allowed}. See discipline/meta/GLOSSARY.md.",
                )


def check_mechanisms(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V080 -- a named mechanism actually exists.

    Warning, not error: the corpus is allowed to name a mechanism before it is
    built, but never allowed to hide that it has not been. `ENFORCEMENT.md`
    reports the implemented fraction so the gap is tracked rather than assumed
    closed.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return a warning per unimplemented mechanism, so a rule naming two absent
        mechanisms is reported twice; unverifiable tags are passed over in silence
    """
    for doc in documents:
        for rule in doc.rules:
            for mechanism in rule.mechanisms:
                if mechanism_is_implemented(mechanism, layout.root) is False:
                    yield Finding(
                        code="V080",
                        severity=Severity.WARN,
                        path=_relpath(layout, doc),
                        line=rule.line,
                        message=f"{rule.rule_id}: mechanism `{mechanism}` is not implemented",
                        remediation="Build it under enforce/, or the rule is binding in name only.",
                    )


def unbuilt_pairs(documents: Sequence[Document], layout: Layout) -> frozenset[tuple[str, str]]:
    """Every (rule, mechanism) pair V080 would warn about, as a comparable set.

    The same test `check_mechanisms` applies, restated as a set rather than a
    finding stream: the ratchet needs to diff two moments of the corpus against
    each other, not render either one.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return each rule id paired with a mechanism tag it names that resolves to
        nothing on disk; a rule naming two absent mechanisms contributes two pairs
    """
    return frozenset(
        (rule.rule_id, mechanism)
        for doc in documents
        for rule in doc.rules
        for mechanism in rule.mechanisms
        if mechanism_is_implemented(mechanism, layout.root) is False
    )


@dataclass(frozen=True, slots=True)
class V080Baseline:
    """The recorded ceiling V081/V082 hold the corpus to, and why it last moved."""

    ## How many (rule, mechanism) pairs may be unbuilt without failing the run.
    ## Redundant with `len(pairs)` in a well-formed file, and kept explicit only
    ## so that a disagreement between the two is a detectable state at all;
    ## `load_v080_baseline` is what rejects it. Raising this number alone is the
    ## cheapest way to switch V081 off, so it must never be read on trust.
    count: int
    ## The exact pairs unbuilt when the baseline was last recorded, so V081 can
    ## name which ones are new rather than only report that the count grew.
    pairs: frozenset[tuple[str, str]]
    ## The `--why` given for the last move, or None for a baseline no one has
    ## moved since it was first written.
    why: str | None


## The ceiling before any baseline file has ever been written -- zero unbuilt
## mechanisms tolerated -- so a corpus with no baseline on disk fails closed
## rather than passing by default.
_EMPTY_BASELINE: Final = V080Baseline(count=0, pairs=frozenset(), why=None)


def load_v080_baseline(path: Path = V080_BASELINE_PATH) -> V080Baseline:
    """Read the committed ceiling, or the empty one when nothing has been recorded yet.

    The stored `count` is checked against the stored `pairs` rather than taken
    on trust. A ratchet whose ceiling is one hand-editable integer is not a
    ratchet: raising that integer alone silences V081 for every rule at once and
    leaves no trace, so the two halves of the file must agree or the file is not
    the one this module wrote.

    @param path the baseline file to read, defaulting to the checked-in one
    @return the baseline; `_EMPTY_BASELINE` when `path` does not exist
    @throws ValueError if the file exists but is not the JSON this module writes:
        unparsable, missing `count` or `pairs`, holding something other than
        two-element pairs, or carrying a `count` its own `pairs` contradict
    """
    if not path.exists():
        return _EMPTY_BASELINE
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in ("count", "pairs"):
        if key not in data:
            missing = f"{path}: not a V080 baseline -- no `{key}` field"
            raise ValueError(missing)
    pairs = frozenset((rule_id, mechanism) for rule_id, mechanism in data["pairs"])
    if data["count"] != len(pairs):
        disagrees = (
            f"{path}: `count` is {data['count']} but `pairs` holds {len(pairs)}; "
            f"rewrite it with `python tools/validate.py --update-baseline "
            f'--why "..."` rather than by hand'
        )
        raise ValueError(disagrees)
    return V080Baseline(count=data["count"], pairs=pairs, why=data.get("why"))


def write_v080_baseline(pairs: frozenset[tuple[str, str]], why: str, path: Path = V080_BASELINE_PATH) -> None:
    """Move the ceiling to `pairs`, recording why, in the `doc_baseline.json` idiom.

    @param pairs the (rule, mechanism) set the new ceiling holds the corpus to
    @param why the reason the ceiling is moving; required, matching
        `learn.py calibrate --set` refusing an unexplained dial turn
    @param path where to write the baseline, defaulting to the checked-in one
    """
    payload = {
        "generated_by": "tools/validate.py --update-baseline",
        "note": (
            "Ratchet ceiling for V081/V082. validate.py fails when the corpus's "
            "unbuilt-mechanism count exceeds `count` below, and only warns when it "
            "falls under it. Move this file with `python tools/validate.py "
            '--update-baseline --why "..."`, never by hand -- the pairs must stay '
            "exactly what the tool itself measured."
        ),
        "count": len(pairs),
        "pairs": sorted(pairs),
        "why": why,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def check_v080_ratchet(
    documents: Sequence[Document], layout: Layout, *, baseline: V080Baseline | None = None
) -> Iterator[Finding]:
    """V081-V082 -- the unbuilt-mechanism count is a ratchet, not a freeze.

    A rule adding a mechanism that already resolves costs the count nothing, so a
    new binding rule with real enforcement never trips V081 -- only a rule whose
    mechanism is *not* built does, which is the exact case the corpus's own axiom
    (anything mechanically verifiable shall be mechanically verified) forbids
    hiding. Force is not weighed here at all, which is what closes the obvious
    dodge: re-tagging a rule `[ADVISORY]` while keeping its unbuilt mechanism tag
    still contributes the pair and still trips V081. Dropping the tag as well
    escapes this check and lands on `enforce/fitness/test_meta.py`'s
    `test_advisory_rules_justify_themselves`, which demands a written reason no
    mechanism could exist.

    Silent when `layout.root` is not the real repository: the baseline records one
    specific tree, and diffing a throwaway test corpus against it would report
    every synthetic fixture as a mass regression. Call this function directly, with
    an injected `baseline`, to test it against a fixture.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @param baseline the ceiling to compare against; loaded from
        `V080_BASELINE_PATH` when not given, which is every caller but a test
    @return one V081 error when the count rose, naming the pairs that are new;
        one V082 warning when it fell, inviting the baseline down; nothing when
        it is unchanged
    """
    if baseline is None:
        if layout.root != REPO_ROOT:
            return
        baseline = load_v080_baseline()
    current = unbuilt_pairs(documents, layout)
    if len(current) > baseline.count:
        added = sorted(current - baseline.pairs)
        names = ", ".join(f"{rule_id} `{mechanism}`" for rule_id, mechanism in added) or "(recount only)"
        yield Finding(
            code="V081",
            severity=Severity.ERROR,
            path=layout.rel(V080_BASELINE_PATH),
            line=1,
            message=(
                f"{len(current)} unbuilt mechanism(s) exceeds the baseline of "
                f"{baseline.count}; new: {names}"
            ),
            remediation=(
                "Build the missing mechanism(s) under enforce/, or if the rule is "
                "legitimately new and its mechanism genuinely not written yet, move "
                'the ceiling deliberately: `python tools/validate.py '
                '--update-baseline --why "..."`.'
            ),
        )
    elif len(current) < baseline.count:
        yield Finding(
            code="V082",
            severity=Severity.WARN,
            path=layout.rel(V080_BASELINE_PATH),
            line=1,
            message=f"{len(current)} unbuilt mechanism(s), below the baseline of {baseline.count}",
            remediation=(
                'Lock in the progress: `python tools/validate.py --update-baseline '
                '--why "..."`.'
            ),
        )


def check_graph(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V090-V094 -- the navigation graph is well formed and current.

    A dangling edge or an unreachable rule is not a cosmetic defect: it is a rule
    that exists and cannot be arrived at, which is the failure the graph was built
    to make impossible.

    Yields nothing when the graph tools are not importable: they are optional, and
    a checker that cannot run a check must not pretend the check passed elsewhere.
    A dangling edge is blamed on `edges.yaml` when it was declared by hand and on
    the generated graph otherwise, so the report names the file to edit.

    @param documents every parsed corpus file, unused -- the graph is rebuilt from
        the tree so that a stale graph is detectable rather than assumed
    @param layout the tree to build the graph from
    @return findings for dangling edges, `requires` cycles, rules beyond
        `REACH_DEPTH` hops, and a checked-in graph that disagrees with the corpus
    """
    try:
        from build_graph import build, render  # noqa: PLC0415 - optional at import time
        from graph_model import EdgeType, NodeType, Origin
    except ImportError:  # pragma: no cover - the graph tools are part of the repo
        return

    graph, _ = build(layout.root)
    edges_yaml = layout.discipline / "meta" / "edges.yaml"

    for edge in graph.dangling():
        missing = edge.src if edge.src not in graph.nodes else edge.dst
        declared = edge.origin is Origin.DECLARED
        yield Finding(
            code="V093" if declared else "V090",
            severity=Severity.ERROR,
            path=layout.rel(edges_yaml) if declared else "discipline/graph.json",
            line=1,
            message=f"{edge.type} edge {edge.src} -> {edge.dst} names unknown node {missing!r}",
            remediation="Correct the id, or remove the relation. Every endpoint must resolve.",
        )

    for cycle in graph.cycles_in(EdgeType.REQUIRES):
        yield Finding(
            code="V091",
            severity=Severity.ERROR,
            path="discipline/graph.json",
            line=1,
            message="cycle in `requires`: " + " -> ".join(cycle),
            remediation="Load order would be undefined. Break the cycle in front-matter.",
        )

    seeds = sorted(n.id for n in graph.of_type(NodeType.MODULE))
    unreachable = graph.unreachable_from(seeds, NodeType.RULE, depth=REACH_DEPTH)
    for rule_id in unreachable:
        yield Finding(
            code="V092",
            severity=Severity.ERROR,
            path="discipline/graph.json",
            line=1,
            message=f"{rule_id} is not reachable from any module within {REACH_DEPTH} hops",
            remediation="Give it a citation, a layer, a trigger or a mechanism an agent can arrive by.",
        )

    # Absence is not staleness. The graph accelerates navigation; a corpus
    # without one is valid, merely unaccelerated, and `build_graph.py --check`
    # is what reports "not built yet". Here we catch the worse case: a graph that
    # exists and disagrees with the corpus, which would misroute silently.
    on_disk = layout.discipline / "graph.json"
    if on_disk.exists() and on_disk.read_text(encoding="utf-8") != render(graph):
        yield Finding(
            code="V094",
            severity=Severity.ERROR,
            path="discipline/graph.json",
            line=1,
            message="graph disagrees with the corpus",
            remediation="Run `python tools/build_graph.py`.",
        )


def check_grounding(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V095 -- a rule checked by a pinned tool declares where the pin lives.

    Narrow on purpose: the obligation attaches only where a rule's Check actually
    invokes a tool some fact module version-pins. Requiring `grounds_on`
    everywhere would manufacture edges that are not true.

    When two fact modules pin the same tool the first one read owns it, so the
    obligation stays single-valued and the remediation can name one file.

    @param documents every parsed corpus file
    @param layout the tree they were read from
    @return one finding per (law rule, pinned tool) pair the rule's module does
        not ground on, so a Check invoking two such tools is reported twice
    """
    pinned: dict[str, str] = {}
    for doc in documents:
        if doc.kind is not Kind.FACT:
            continue
        for tool in _TOOL_ROW.findall(prose_of(doc)):
            # removesuffix, not rstrip: rstrip takes a character set, and turned
            # "mypy" into "m", so this check silently skipped it everywhere.
            pinned.setdefault(tool.lower().removesuffix(".py"), doc.doc_id)

    for doc in documents:
        if doc.kind is not Kind.LAW:
            continue
        declared = {str(g) for g in (doc.front_matter.get("grounds_on") or [])}
        for rule in doc.rules:
            for tool in _TOOL_WORD.findall((rule.check or "").lower()):
                owner = pinned.get(tool)
                if owner is None or owner in declared:
                    continue
                yield Finding(
                    code="V095",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=(
                        f"{rule.rule_id} is checked by `{tool}`, pinned in {owner}, "
                        f"but {doc.doc_id} does not ground on it"
                    ),
                    remediation=f"Add {owner} to this module's `grounds_on`.",
                )


def check_learning(layout: Layout) -> Iterator[Finding]:
    """V096 -- the ledger and its query index agree.

    The ledger is the record and the database is derived from it, so a database
    holding a different number of events is stale at best and, at worst, is
    answering retrievals from material the ledger does not contain.

    Silent when the subsystem is absent or the database has not been built; the
    database is derived and gitignored, so its absence is the state a fresh clone
    is in. An unreadable database counts as -1 events, which can never equal a
    ledger's count and so is always reported rather than swallowed.

    @param layout the tree holding the ledger and its database
    @return at most one finding: an unparsable ledger stops the check there, since
        a count taken from it would be meaningless; otherwise a finding when the
        two disagree on how many events exist
    """
    try:
        import learn  # noqa: PLC0415 - optional subsystem
    except ImportError:
        return
    store = learn.Store(layout.root)
    if not store.db.exists():
        return  # derived and gitignored; absence is the normal state after a clone
    try:
        events = len(learn.read_ledger(store))
    except learn.LearnError as exc:
        yield Finding(
            code="V096", severity=Severity.ERROR, path="learning/ledger.jsonl", line=1,
            message=str(exc),
            remediation="Repair the line, or drop it and re-record the event.",
        )
        return
    import sqlite3  # noqa: PLC0415 - only needed on this path

    connection = sqlite3.connect(store.db)
    try:
        stored = connection.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    except sqlite3.DatabaseError:
        stored = -1
    finally:
        connection.close()
    if stored != events:
        yield Finding(
            code="V096", severity=Severity.ERROR, path="learning/learning.db", line=1,
            message=f"database holds {stored} event(s), the ledger holds {events}",
            remediation="Run `python tools/learn.py sync`; the ledger is the record.",
        )


# ---------------------------------------------------------------------------- main


def load_documents(layout: Layout) -> tuple[list[Document], list[Finding]]:
    """Parse every corpus file; unparsable files become V001 findings.

    A file that will not parse is reported and dropped rather than aborting the
    run, so one broken document does not hide the state of the other hundred.
    `INDEX.md` is skipped as generated output, not source.

    @param layout the tree to read
    @return the documents that parsed, and a V001 finding for each that did not;
        both empty when there is no discipline/ directory
    """
    documents: list[Document] = []
    findings: list[Finding] = []
    if not layout.discipline.exists():
        return documents, findings
    for path in sorted(layout.discipline.rglob("*.md")):
        if path.name == "INDEX.md":
            continue
        try:
            documents.append(parse_document(path))
        except ParseError as exc:
            findings.append(
                Finding(
                    code="V001",
                    severity=Severity.ERROR,
                    path=layout.rel(path),
                    line=1,
                    message=exc.reason,
                    remediation="Every corpus file opens with YAML front-matter; see SCHEMA.md section 2.",
                )
            )
    return documents, findings


def run(layout: Layout = DEFAULT_LAYOUT) -> list[Finding]:
    """Every check, over the whole corpus.

    Findings arrive grouped by check rather than sorted by file, which keeps a
    single broken invariant together in the output instead of scattering it.
    A check that finds nothing contributes nothing, so the order is stable but
    the offsets are not: callers filter by `code`, never by position.

    @param layout the tree to validate, defaulting to the real repository
    @return every finding raised, both severities mixed, in check order with the
        unparsable files (V001) first
    @throws OSError if the front-matter schema cannot be read
    @throws ValueError propagated from a check that cannot proceed at all, such as
        a `verified:` date that is not ISO; a corpus this malformed is reported by
        the traceback rather than as a finding
    """
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    documents, findings = load_documents(layout)
    for doc in documents:
        findings.extend(check_front_matter(doc, schema, layout))
        findings.extend(check_genre_constraints(doc, layout))
    findings.extend(check_rules(documents, layout))
    findings.extend(check_ledgers(documents, layout))
    findings.extend(check_xrefs(documents, layout))
    findings.extend(check_budgets(documents, layout))
    findings.extend(check_freshness(documents, layout))
    findings.extend(check_glossary(documents, layout))
    findings.extend(check_mechanisms(documents, layout))
    findings.extend(check_v080_ratchet(documents, layout))
    findings.extend(check_graph(documents, layout))
    findings.extend(check_grounding(documents, layout))
    findings.extend(check_learning(layout))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    """Run every check over one tree and print what it found.

    `--json` prints the findings as an array for a machine; the default form
    prints each one rendered, then a tally by code so a run's shape is legible
    without reading every line.

    `--update-baseline` moves the V081/V082 ceiling to the corpus as it stands
    right now and exits, doing none of the other checks; it always requires
    `--why`, the same refusal `learn.py calibrate --set` makes for an unexplained
    dial turn, since a ceiling that can move without a recorded reason is a freeze
    wearing a ratchet's name.

    @param argv command-line arguments, defaulting to those of the process
    @return 1 if any error-severity finding was raised, or if `--update-baseline`
        was given without `--why`; 0 otherwise -- warnings are printed and counted
        but never decide the exit code
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Validate the discipline corpus.")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    parser.add_argument(
        "--update-baseline", action="store_true",
        help="move the V081/V082 ceiling to the corpus's current unbuilt-mechanism count and exit",
    )
    parser.add_argument("--why", help="required with --update-baseline: why the ceiling is moving")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.update_baseline:
        if not args.why:
            parser.error("--why is required with --update-baseline; an unexplained ceiling move is drift")
        layout = Layout(root)
        documents, _ = load_documents(layout)
        pairs = unbuilt_pairs(documents, layout)
        write_v080_baseline(pairs, args.why)
        print(f"recorded {len(pairs)} unbuilt mechanism(s) in {layout.rel(V080_BASELINE_PATH)} -- {args.why}")
        return 0

    findings = run(Layout(root))
    errors = [f for f in findings if f.severity is Severity.ERROR]

    if args.json:
        print(json.dumps([asdict(f) for f in findings], indent=2, default=str))
    else:
        for finding in findings:
            print(finding.render())
        counts: defaultdict[str, int] = defaultdict(int)
        for finding in findings:
            counts[finding.code] += 1
        summary = ", ".join(f"{code}x{n}" for code, n in sorted(counts.items())) or "none"
        print(f"\n{len(errors)} error(s), {len(findings) - len(errors)} warning(s). [{summary}]")

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
