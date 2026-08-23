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
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

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
    has_mechanical_claim,
    mechanism_is_implemented,
    parse_document,
    prose_of,
)
from evidence_model import (
    EvidenceParseError,
    discrimination_covered,
    discrimination_witnesses,
    load_evidence,
    load_observations,
    validate_evidence,
)

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

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
## Each key is a declared decay class and each value is its maximum age in days; mapping key
## order is deliberately unused.
DECAY_DAYS: Final[dict[str, int]] = {
    "months": 120,
    "quarters": 270,
    "years": 730,
    "none": 10**6,
}

## Documents legitimately named in prose that are not corpus modules.
KNOWN_EXTERNAL_MD: Final[frozenset[str]] = frozenset({
    "CLAUDE.md",
    "README.md",
    "SKILL.md",
    "SUPERSEDED.md",
    "MEMORY.md",
})
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

## How many outcomes a ledger should carry per learning before `V097` stops
## saying so. One in ten is deliberately undemanding: the point is to notice a
## loop that only ever writes, not to prescribe how much reporting is enough.
MIN_OUTCOME_SHARE: Final = 0.10

## How full the always-loaded file may get before `V051` says so. A warning, not
## a wall: the wall is `V050` at the ceiling itself, and by then the addition has
## already been written.
CROWDED_SHARE: Final = 0.90

## How many of V098's rules are named in the message before it elides. Enough
## to start on without turning a warning into a wall of ids; the full list is
## what `python tools/discrimination_gate.py` prints.
GAP_NAMED: Final = 6

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
        # Return two lines, the second indenting the remediation under the message to the
        # Details: caller.
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
        # Return the tree `load_documents` walks; absent, nothing parses and every to the
        # Details: caller.
        return self.root / "discipline"

    @property
    def enforce(self) -> Path:
        """Where the mechanisms live that decide the binding rules.

        @return the directory V080 resolves `check:` tags under, and one of the
            two it searches for a `fitness:` function
        """
        # Return the directory V080 resolves `check:` tags under, and one of the to the caller.
        return self.root / "enforce"

    @property
    def examples(self) -> Path:
        """Long-form material lifted out of modules to keep them under budget.

        @return the directory whose `*.md` stems make up the `examples/...`
            namespace a V040 reference may resolve into
        """
        # Return the directory whose `*.md` stems make up the `examples/...` to the caller.
        return self.discipline / "examples"

    @property
    def enforcement_ledger(self) -> Path:
        """The generated table pairing each rule with what decides it.

        No check here reads it; `build_index.py` writes it, and this property
        exists so the location is stated once for whoever needs it next.

        @return where that generation is expected to put the file
        """
        # Return where that generation is expected to put the file to the caller.
        return self.enforce / "ENFORCEMENT.md"

    @property
    def open_ledger(self) -> Path:
        """Where undecided questions are written down, which V031 requires.

        @return the file V031 searches for each rule id; absent, it reads as
            empty and every [OPEN] rule is reported unrecorded
        """
        # Return the file V031 searches for each rule id; absent, it reads as to the caller.
        return self.discipline / "meta" / "OPEN.md"

    @property
    def glossary(self) -> Path:
        """The definitions of terms the sources used in incompatible senses.

        @return the file the banned terms are read from; absent, V070 has nothing
            to enforce and passes every document
        """
        # Return the file the banned terms are read from; absent, V070 has nothing to the
        # Details: caller.
        return self.discipline / "meta" / "GLOSSARY.md"

    @property
    def evidence(self) -> Path:
        """The authored normative-to-observable evidence join.

        @return the registry validated by V100-V109
        """
        # Return the registry validated by V100-V109 to the caller.
        return self.discipline / "meta" / "evidence.json"

    @property
    def observations(self) -> Path:
        """The authored field observations referenced by rule evidence.

        @return registry whose IDs V109 resolves
        """
        # Return registry whose IDs V109 resolves to the caller.
        return self.discipline / "meta" / "observations.json"

    def rel(self, path: Path) -> str:
        """Render a location for display, anchored at `root`.

        Never raises: a path outside the tree is shown whole rather than costing
        a report its findings.

        @param path the location to display
        @return a POSIX-separated path, relative when it lies under `root` and
            absolute when it does not, so a stray location is still identifiable
        """
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Return a POSIX-separated path, relative when it lies under `root` and to the
            # Details: caller.
            return path.relative_to(self.root).as_posix()
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except ValueError:
            # Return a POSIX-separated path, relative when it lies under `root` and to the
            # Details: caller.
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
    # Return its path relative to `layout.root`, POSIX-separated to the caller.
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
        Each key is a JSON Schema keyword and each value is its constraint; mapping key order is
        deliberately unused.
    @param layout the tree the document was read from
    @return one finding per schema violation, plus V003 when the id's last
        segment disagrees with the filename -- KERNEL.md is exempt by name -- and
        V004 when `kind:` disagrees with the directory, which is only tested for
        files that sit in a genre-named directory at all
    """
    # Compute validator using jsonschema.Draft202012Validator for later check front matter
    # Details: logic.
    validator = jsonschema.Draft202012Validator(schema)
    # Preserve the caught failure that explains why the external result is unusable.
    # Advance check front matter through the current input element in declared order.
    for error in sorted(validator.iter_errors(dict(doc.front_matter)), key=str):
        # Select location, p as the current element from error.absolute_path) or "(root)" while
        # Details: check front matter preserves traversal order.
        location = "/".join(str(p) for p in error.absolute_path) or "(root)"
        yield Finding(
            code="V002",
            severity=Severity.ERROR,
            path=_relpath(layout, doc),
            line=1,
            message=f"front-matter invalid at {location}: {error.message}",
            remediation="See discipline/meta/SCHEMA.md section 2.",
        )
    # Select the guarded path only after `doc.doc_id and doc.path.stem != 'KERNEL'` is
    # Details: satisfied.
    if doc.doc_id and doc.path.stem != "KERNEL":
        # Compute expected using doc.doc id.split for later check front matter logic.
        expected = doc.doc_id.split("/", 1)[-1]
        # Select the guarded path only after `doc.path.stem != expected` is satisfied.
        if doc.path.stem != expected:
            yield Finding(
                code="V003",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"front-matter id '{doc.doc_id}' does not match filename '{doc.path.stem}'",
                remediation=f"Rename the file to {expected}.md, or correct the id.",
            )
    # Compute kind dir using doc.path.parent.name for later check front matter logic.
    kind_dir = doc.path.parent.name
    # Select k as the current element from Kind} and kind_dir != doc.kind.value while check
    # Details: front matter preserves traversal order.
    # Select the guarded path only after `doc.kind is not None and kind_dir in {k.value for k in
    # Details: Kind} and (kind_dir != doc.kind.value)` is satisfied.
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
    # Use the absence path when doc.kind has no available value.
    if doc.kind is None:
        # Return findings for rules outside law/ and ops/, [BINDING] in frame/, and to the
        # Details: caller.
        return
    # Select the guarded path only after `doc.kind not in {Kind.LAW, Kind.OPS}` is satisfied.
    if doc.kind not in {Kind.LAW, Kind.OPS}:
        # Select rule as the current element from doc.rules while check genre constraints
        # Details: preserves traversal order.
        # Advance check genre constraints through the current input element in declared order.
        for rule in doc.rules:
            yield Finding(
                code="V010",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=rule.line,
                message=f"{rule.rule_id}: only law/ and ops/ may carry rules; this is {doc.kind.value}/",
                remediation="Move the rule into a law/ module, or drop its force tag.",
            )
    # Select the guarded path only after `doc.kind is Kind.FRAME` is satisfied.
    if doc.kind is Kind.FRAME:
        # Select rule as the current element from doc.rules while check genre constraints
        # Details: preserves traversal order.
        # Advance check genre constraints through the current input element in declared order.
        for rule in doc.rules:
            # Select the guarded path only after `rule.force is Force.BINDING` is satisfied.
            if rule.force is Force.BINDING:
                yield Finding(
                    code="V011",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [BINDING] is not permitted in a frame/ document",
                    remediation="frame/ describes options; move the rule to law/.",
                )
    # Select the guarded path only after `doc.kind is Kind.LAW` is satisfied.
    if doc.kind is Kind.LAW:
        # Select tool, version as the current element from find_version_literals(prose_of(doc))
        # Details: while check genre constraints preserves traversal order.
        # Advance check genre constraints through the current input element in declared order.
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
    """V020-V025 -- rule identity, active strategies, and historical IDs.

    Cross-document by necessity: an id collides only against the rest of the
    corpus, and the first definition wins so the report names a stable culprit.

    @param documents every parsed corpus file, in the order they were read
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return findings for duplicate ids, wrong prefixes, unchecked or unmechanised
        [BINDING] rules, and over-long titles
    """
    # Each seen key is a rule id and each value is its first declaration; mapping key order is
    # deliberately unused for duplicate detection.
    seen: dict[str, Rule] = {}
    # Select doc as the current element from documents while check rules preserves traversal
    # Details: order.
    # Advance check rules through the current input element in declared order.
    for doc in documents:
        # Select rule as the current element from doc.rules while check rules preserves
        # Details: traversal order.
        # Advance check rules through the current input element in declared order.
        for rule in doc.rules:
            # Compute first using seen.get for later check rules logic.
            first = seen.get(rule.rule_id)
            # Use the available-value path only when first is present.
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
                # Update check rules state only after the required source facts are available.
                seen[rule.rule_id] = rule

            # Compute partitioned using doc.module name.upper for later check rules logic.
            partitioned = doc.module_name.upper().startswith(f"{doc.rule_prefix}-")
            # Compute prefix allowed using rule.prefix == doc.rule_prefix and ( for later check
            # Details: rules logic.
            prefix_allowed = rule.prefix == doc.rule_prefix and (
                "rule_prefix" not in doc.front_matter or partitioned
            )
            # Select the empty-or-disabled path when prefix allowed has no usable value.
            if not prefix_allowed:
                yield Finding(
                    code="V021",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=(
                        f"{rule.rule_id}: prefix does not match module "
                        f"'{doc.module_name}' or its declared partition prefix"
                    ),
                    remediation=(
                        f"Use {doc.module_name.upper()}-NNN, move the rule, or declare "
                        "rule_prefix only in a PREFIX-SUBJECT partition."
                    ),
                )

            # Select the guarded path only after `rule.force is Force.BINDING and (not
            # Details: rule.check)` is satisfied.
            if rule.force is Force.BINDING and not rule.check:
                yield Finding(
                    code="V022",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [BINDING] without a **Check** line",
                    remediation="Name the command or test that decides it, or demote it with a justification.",
                )
            # Select the guarded path only after `rule.force is Force.BINDING and (not
            # Details: rule.mechanisms)` is satisfied.
            if rule.force is Force.BINDING and not rule.mechanisms:
                yield Finding(
                    code="V023",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [BINDING] without a mechanism tag",
                    remediation="Add [auto:...], [check:...] or [fitness:...]; nothing checks it otherwise.",
                )
            # Select the guarded path only after `len(rule.title) > 60` is satisfied.
            if len(rule.title) > 60:
                yield Finding(
                    code="V024",
                    severity=Severity.WARN,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: title is {len(rule.title)} chars (limit 60)",
                    remediation="Shorten it; the heading is the whole rule surface an agent greps.",
                )
            # Select the guarded path only after `rule.force is Force.RETIRED and
            # Details: (rule.mechanisms or rule.check or rule.no_mechanism)` is satisfied.
            if rule.force is Force.RETIRED and (rule.mechanisms or rule.check or rule.no_mechanism):
                yield Finding(
                    code="V025",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [RETIRED] carries an active mechanism field",
                    remediation=(
                        "Remove mechanism tags, Check, and No mechanism; retain only "
                        "history, rationale, references, and an optional successor."
                    ),
                )


def check_ledgers(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V030-V031 -- every [ADVISORY] and [OPEN] rule is accounted for in writing.

    A missing OPEN.md is not itself reported here; its absence simply makes every
    [OPEN] rule unaccounted for, which is the same defect stated per rule.

    @param documents every parsed corpus file
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return findings for unjustified [ADVISORY] rules and unrecorded [OPEN] ones
    """
    # Compute opens using layout.open_ledger for later check ledgers logic.
    opens = layout.open_ledger
    # Compute open text using opens.read text for later check ledgers logic.
    open_text = opens.read_text(encoding="utf-8") if opens.exists() else ""
    # Select doc as the current element from documents while check ledgers preserves traversal
    # Details: order.
    # Advance check ledgers through the current input element in declared order.
    for doc in documents:
        # Select rule as the current element from doc.rules while check ledgers preserves
        # Details: traversal order.
        # Advance check ledgers through the current input element in declared order.
        for rule in doc.rules:
            # Select the guarded path only after `rule.force is Force.ADVISORY and (not
            # Details: rule.no_mechanism)` is satisfied.
            if rule.force is Force.ADVISORY and not rule.no_mechanism:
                yield Finding(
                    code="V030",
                    severity=Severity.ERROR,
                    path=_relpath(layout, doc),
                    line=rule.line,
                    message=f"{rule.rule_id}: [ADVISORY] without a **No mechanism** justification",
                    remediation="State why no mechanism is possible, or find one and make it [BINDING].",
                )
            # Select the guarded path only after `rule.force is Force.OPEN and rule.rule_id not
            # Details: in open_text` is satisfied.
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

    `sources/` is deliberately not a resolution root. It is superseded material
    that the release does not ship, so a reference resolving only there passes in
    this repository and dangles for every adopter -- the validator would be green
    exactly where it is needed most. Cite a corpus module, or the sigil that
    `meta/PROVENANCE` maps back to the source document.

    @param documents every parsed corpus file
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return findings for unresolved ids and for filenames matching nothing on disk
    """
    # Collect unique rule ids element values; their order is deliberately unordered.
    rule_ids = {rule.rule_id for doc in documents for rule in doc.rules}
    # Collect unique module ids element values; their order is deliberately unordered.
    module_ids = {doc.doc_id for doc in documents if doc.doc_id}
    # Unpack example ids, p using ( for later check xrefs logic.
    example_ids = (
        {f"examples/{p.stem}" for p in layout.examples.glob("*.md")}
        if layout.examples.exists()
        else set()
    )

    # Select doc as the current element from documents while check xrefs preserves traversal
    # Details: order.
    # Advance check xrefs through the current input element in declared order.
    for doc in documents:
        # Compute prose using prose of for later check xrefs logic.
        prose = prose_of(doc)
        # Resolve the repository-confined path used by this operation before filesystem access.
        # Advance check xrefs through the current input element in declared order.
        for target in find_xrefs(prose):
            # Compute base using target.split for later check xrefs logic.
            base = target.split("#", 1)[0]
            # Select the guarded path only after `base in rule_ids or base in module_ids or base
            # Details: in example_ids` is satisfied.
            if base in rule_ids or base in module_ids or base in example_ids:
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Compute kind using "rule" if _RULE_ID.match(base) else "module" for later check
            # Details: xrefs logic.
            kind = "rule" if _RULE_ID.match(base) else "module"
            yield Finding(
                code="V040",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"reference to undefined {kind} [{target}]",
                remediation="Fix the target or remove it; every reference must resolve.",
            )

        # Preserve the optional pattern match that carries the reported analysis count.
        # Advance check xrefs through the current input element in declared order.
        for match in _MD_MENTION.finditer(body_without_fences(doc)):
            # Normalize the current repository path to its portable baseline key spelling.
            name = match.group("name")
            # Select the guarded path only after `Path(name).name in KNOWN_EXTERNAL_MD` is
            # Details: satisfied.
            if Path(name).name in KNOWN_EXTERNAL_MD:
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Each candidates element is one possible cross-reference target, ordered repository
            # root, local directory, discipline root, then enforcement root.
            candidates = (
                layout.root / name,
                doc.path.parent / name,
                *(layout.root / d / name for d in ("discipline", "enforce")),
            )
            # Select c as the current element from candidates) while check xrefs preserves
            # Details: traversal order.
            # Select the existing-artifact path only when `any((c.exists() for c in
            # Details: candidates))` is satisfied.
            if any(c.exists() for c in candidates):
                # Advance after the current candidate has been conclusively excluded.
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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return one finding per document over the ceiling its genre allows
    """
    # Select doc as the current element from documents while check budgets preserves traversal
    # Details: order.
    # Advance check budgets through the current input element in declared order.
    for doc in documents:
        # Compute budget using budget for for later check budgets logic.
        budget = budget_for(doc)
        # Compute actual using count tokens for later check budgets logic.
        actual = count_tokens(doc.path.read_text(encoding="utf-8"))
        # Select the guarded path only after `actual > budget` is satisfied.
        if actual > budget:
            yield Finding(
                code="V050",
                severity=Severity.ERROR,
                path=_relpath(layout, doc),
                line=1,
                message=f"{actual} tokens exceeds the {budget}-token ceiling",
                remediation="Split the module, or move detail into discipline/examples/.",
            )
        # Select the guarded path only after `actual > budget * CROWDED_SHARE` is satisfied.
        elif actual > budget * CROWDED_SHARE:
            # A warning before the wall, and only for the always-loaded file.
            # KERNEL is the one document every session pays for unconditionally,
            # so it is the one whose remaining headroom is worth knowing BEFORE
            # the next addition is written rather than after it is rejected.
            # It stood at 1,876 of 2,000 -- 94% -- with nobody aware of it.
            if doc.path.name != "KERNEL.md":
                # Advance after the current candidate has been conclusively excluded.
                continue
            yield Finding(
                code="V051",
                severity=Severity.WARN,
                path=_relpath(layout, doc),
                line=1,
                message=(
                    f"{actual} of the {budget}-token ceiling "
                    f"({actual / budget:.0%}); {budget - actual} left"
                ),
                remediation=(
                    "The always-loaded surface is the premise the layered design "
                    "rests on. Pay for an addition here by trimming, not by "
                    "raising the ceiling."
                ),
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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @param today the date to measure against, injected so the check is deterministic
    @return a warning per document older than its declared decay allows
    @throws ValueError if a `verified:` string is not an ISO date
    """
    # Compute now using today or dt.date.today() for later check freshness logic.
    now = today or dt.date.today()
    # Select doc as the current element from documents while check freshness preserves traversal
    # Details: order.
    # Advance check freshness through the current input element in declared order.
    for doc in documents:
        # Retain the immutable source representation consumed by subsequent analysis.
        raw = doc.front_matter.get("verified")
        # Compute decay using doc.front matter.get for later check freshness logic.
        decay = doc.front_matter.get("decay")
        # Select the empty-or-disabled path when isinstance(decay, str) has no usable value.
        if not isinstance(decay, str):
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `isinstance(raw, dt.date)` is satisfied.
        if isinstance(raw, dt.date):
            # Compute verified using raw for later check freshness logic.
            verified = raw
        # Select the guarded path only after `isinstance(raw, str)` is satisfied.
        elif isinstance(raw, str):
            # Compute verified using dt.date.fromisoformat for later check freshness logic.
            verified = dt.date.fromisoformat(raw)
        else:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute age using (now - verified).days for later check freshness logic.
        age = (now - verified).days
        # Compute limit using DECAY DAYS.get for later check freshness logic.
        limit = DECAY_DAYS.get(decay, DECAY_DAYS["years"])
        # Select the guarded path only after `age > limit` is satisfied.
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
    # Select the existing-artifact path only when `not glossary.exists()` is satisfied.
    if not glossary.exists():
        # Return each banned term mapped to its approved forms; a term the glossary to the
        # Details: caller.
        return {}
    # Retain the immutable source representation consumed by subsequent analysis.
    text = glossary.read_text(encoding="utf-8")
    # Compute sections using list for later banned terms logic.
    sections = list(_BARE_BANNED.finditer(text))
    # Each approved key is a banned bare term and each value lists its longest-first qualified
    # forms; mapping key order is deliberately unused.
    approved: dict[str, tuple[str, ...]] = {}
    # Preserve the optional pattern match that carries the reported analysis count.
    # Advance banned terms through the current input element in declared order.
    for index, match in enumerate(sections):
        # Compute term using match.group for later banned terms logic.
        term = match.group("term").strip().lower()
        # Compute end using sections[index + 1].start() if index + 1 < len(sections) els for
        # Details: later banned terms logic.
        end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
        # Retain the immutable source representation consumed by subsequent analysis.
        body = text[match.end() : end]
        # Collect unique phrases element values; their order is deliberately unordered.
        phrases = {
            p.strip().lower()
            for p in re.findall(r"\*\*(.+?)\*\*", body)
            if term in p.lower() and p.strip().lower() != term
        }
        # Update banned terms state only after the required source facts are available.
        approved[term] = tuple(sorted(phrases, key=len, reverse=True))
    # Return each banned term mapped to its approved forms; a term the glossary to the caller.
    return approved


def check_glossary(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V070 -- terms the sources used in incompatible senses stay qualified.

    Quoting a source's own defective phrasing is legitimate; put it in backticks,
    which `prose_of` removes.

    The glossary itself is skipped -- it is where the bare term is defined, so
    flagging it would make the definition unwritable.

    @param documents every parsed corpus file
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return one finding per banned term a document uses unqualified, so a file
        misusing three terms is reported three times; nothing at all when no
        glossary declares any
    """
    # Compute approved using banned terms for later check glossary logic.
    approved = banned_terms(layout.glossary)
    # Select the empty-or-disabled path when approved has no usable value.
    if not approved:
        # Return one finding per banned term a document uses unqualified, so a file to the
        # Details: caller.
        return
    # Select doc as the current element from documents while check glossary preserves traversal
    # Details: order.
    # Advance check glossary through the current input element in declared order.
    for doc in documents:
        # Select the guarded path only after `doc.path == layout.glossary` is satisfied.
        if doc.path == layout.glossary:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute prose using prose of for later check glossary logic.
        prose = prose_of(doc).lower()
        # Select qualified, term as the current element from approved.items() while check
        # Details: glossary preserves traversal order.
        # Advance check glossary through the current input element in declared order.
        for term, qualified in approved.items():
            # Compute remaining using prose for later check glossary logic.
            remaining = prose
            # Strip each approved phrase longest-first so a short form cannot consume an
            # overlapping longer qualification.
            for phrase in qualified:
                # Compute remaining using remaining.replace for later check glossary logic.
                remaining = remaining.replace(phrase, " ")
            # Select the guarded path only after
            # Details: `re.search(f'(?<![\\w-]){re.escape(term)}(?![\\w-])', remaining)` is
            # Details: satisfied.
            if re.search(rf"(?<![\w-]){re.escape(term)}(?![\w-])", remaining):
                # Select allowed, q as the current element from sorted(qualified)) or "a
                # Details: qualified form" while check glossary preserves traversal order.
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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return a warning per unimplemented mechanism, so a rule naming two absent
        mechanisms is reported twice; unverifiable tags are passed over in silence
    """
    # Select doc as the current element from documents while check mechanisms preserves
    # Details: traversal order.
    # Advance check mechanisms through the current input element in declared order.
    for doc in documents:
        # Select rule as the current element from doc.rules while check mechanisms preserves
        # Details: traversal order.
        # Advance check mechanisms through the current input element in declared order.
        for rule in doc.rules:
            # Select mechanism as the current element from rule.mechanisms while check
            # Details: mechanisms preserves traversal order.
            # Advance check mechanisms through the current input element in declared order.
            for mechanism in rule.mechanisms:
                # Select the guarded path only after `mechanism_is_implemented(mechanism,
                # Details: layout.root, rule.rule_id) is False` is satisfied.
                if mechanism_is_implemented(mechanism, layout.root, rule.rule_id) is False:
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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return each rule id paired with a mechanism tag it names that resolves to
        nothing on disk; a rule naming two absent mechanisms contributes two pairs
    """
    # Bind doc, rule, mechanism to the current value used by the next unbuilt pairs decision.
    # Return each rule id paired with a mechanism tag it names that resolves to to the caller.
    return frozenset(
        (rule.rule_id, mechanism)
        for doc in documents
        for rule in doc.rules
        for mechanism in rule.mechanisms
        if mechanism_is_implemented(mechanism, layout.root, rule.rule_id) is False
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
    ## Collect unique pairs element values; their order is deliberately unordered.
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
    # Select the existing-artifact path only when `not path.exists()` is satisfied.
    if not path.exists():
        # Return the baseline; `_EMPTY_BASELINE` when `path` does not exist to the caller.
        return _EMPTY_BASELINE
    # Compute data using json.loads for later load v080 baseline logic.
    data = json.loads(path.read_text(encoding="utf-8"))
    # Treat the current key as the candidate element consumed by the enclosing transformation.
    # Advance load v080 baseline through the current input element in declared order.
    for key in ("count", "pairs"):
        # Select the guarded path only after `key not in data` is satisfied.
        if key not in data:
            # Format the relationship labels whose generated graph count is zero.
            missing = f"{path}: not a V080 baseline -- no `{key}` field"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ValueError(missing)
    # Select mechanism, pairs, rule id as the current element from data["pairs"]) while load
    # Details: v080 baseline preserves traversal order.
    pairs = frozenset((rule_id, mechanism) for rule_id, mechanism in data["pairs"])
    # Select the guarded path only after `data['count'] != len(pairs)` is satisfied.
    if data["count"] != len(pairs):
        # Compute disagrees using ( for later load v080 baseline logic.
        disagrees = (
            f"{path}: `count` is {data['count']} but `pairs` holds {len(pairs)}; "
            f"rewrite it with `python tools/validate.py --update-baseline "
            f'--why "..."` rather than by hand'
        )
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ValueError(disagrees)
    # Return the baseline; `_EMPTY_BASELINE` when `path` does not exist to the caller.
    return V080Baseline(count=data["count"], pairs=pairs, why=data.get("why"))


def write_v080_baseline(
    pairs: frozenset[tuple[str, str]], why: str, path: Path = V080_BASELINE_PATH
) -> None:
    """Move the ceiling to `pairs`, recording why, in the `doc_baseline.json` idiom.

    @param pairs the (rule, mechanism) set the new ceiling holds the corpus to
        Collect unique pairs element values; their order is deliberately unordered.
    @param why the reason the ceiling is moving; required, matching
        `learn.py calibrate --set` refusing an unexplained dial turn
    @param path where to write the baseline, defaulting to the checked-in one

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Each payload key is a baseline field and each value records generator identity, rationale,
    # count, ordered pairs, or operator reason; insertion order produces stable JSON.
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
    # Publish the externally visible effect after all required inputs are ready.
    path.write_text(
        json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
    )


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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @param baseline the ceiling to compare against; loaded from
        `V080_BASELINE_PATH` when not given, which is every caller but a test
    @return one V081 error when the count rose, naming the pairs that are new;
        one V082 warning when it fell, inviting the baseline down; nothing when
        it is unchanged
    """
    # Use the absence path when baseline has no available value.
    if baseline is None:
        # Select the guarded path only after `layout.root != REPO_ROOT` is satisfied.
        if layout.root != REPO_ROOT:
            # Return one V081 error when the count rose, naming the pairs that are new; to the
            # Details: caller.
            return
        # Hold baseline path keys mapped to their recorded behavior-fingerprint values.
        baseline = load_v080_baseline()
    # Preserve the documentation-stripped behavior fingerprint used for comparison.
    current = unbuilt_pairs(documents, layout)
    # Select the guarded path only after `len(current) > baseline.count` is satisfied.
    if len(current) > baseline.count:
        # Compute added using sorted for later check v080 ratchet logic.
        added = sorted(current - baseline.pairs)
        # Unpack names, mechanism, rule id using ( for later check v080 ratchet logic.
        names = (
            ", ".join(f"{rule_id} `{mechanism}`" for rule_id, mechanism in added)
            or "(recount only)"
        )
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
                "the ceiling deliberately: `python tools/validate.py "
                '--update-baseline --why "..."`.'
            ),
        )
    # Select the guarded path only after `len(current) < baseline.count` is satisfied.
    elif len(current) < baseline.count:
        yield Finding(
            code="V082",
            severity=Severity.WARN,
            path=layout.rel(V080_BASELINE_PATH),
            line=1,
            message=f"{len(current)} unbuilt mechanism(s), below the baseline of {baseline.count}",
            remediation=(
                'Lock in the progress: `python tools/validate.py --update-baseline --why "..."`.'
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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree to build the graph from
    @return findings for dangling edges, `requires` cycles, rules beyond
        `REACH_DEPTH` hops, and a checked-in graph that disagrees with the corpus
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        from build_graph import (  # ruff: ignore[import-outside-top-level] - optional at import time
            build,
            render,
        )
        from graph_model import EdgeType, NodeType, Origin
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ImportError:  # pragma: no cover - the graph tools are part of the repo
        # Return findings for dangling edges, `requires` cycles, rules beyond to the caller.
        return

    # Compute graph using build for later check graph logic.
    graph, _ = build(layout.root)
    # Compute edges yaml using layout.discipline / "meta" / "edges.yaml" for later check graph
    # Details: logic.
    edges_yaml = layout.discipline / "meta" / "edges.yaml"

    # Select edge as the current element from graph.dangling() while check graph preserves
    # Details: traversal order.
    # Advance check graph through the current input element in declared order.
    for edge in graph.dangling():
        # Format the relationship labels whose generated graph count is zero.
        missing = edge.src if edge.src not in graph.nodes else edge.dst
        # Compute declared using edge.origin is Origin.DECLARED for later check graph logic.
        declared = edge.origin is Origin.DECLARED
        yield Finding(
            code="V093" if declared else "V090",
            severity=Severity.ERROR,
            path=layout.rel(edges_yaml) if declared else "discipline/graph.json",
            line=1,
            message=f"{edge.type} edge {edge.src} -> {edge.dst} names unknown node {missing!r}",
            remediation="Correct the id, or remove the relation. Every endpoint must resolve.",
        )

    # Select cycle as the current element from graph.cycles_in(EdgeType.REQUIRES) while check
    # Details: graph preserves traversal order.
    # Advance check graph through the current input element in declared order.
    for cycle in graph.cycles_in(EdgeType.REQUIRES):
        yield Finding(
            code="V091",
            severity=Severity.ERROR,
            path="discipline/graph.json",
            line=1,
            message="cycle in `requires`: " + " -> ".join(cycle),
            remediation="Load order would be undefined. Break the cycle in front-matter.",
        )

    # Preserve the observed item count used by the non-vacuity verdict.
    seeds = sorted(n.id for n in graph.of_type(NodeType.MODULE))
    # Compute unreachable using graph.unreachable from for later check graph logic.
    unreachable = graph.unreachable_from(seeds, NodeType.RULE, depth=REACH_DEPTH)
    # Select rule id as the current element from unreachable while check graph preserves
    # Details: traversal order.
    # Advance check graph through the current input element in declared order.
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
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return one finding per (law rule, pinned tool) pair the rule's module does
        not ground on, so a Check invoking two such tools is reported twice
    """
    # Each pinned key is a normalized tool name and each value is the first fact document that
    # pins it; mapping key order is deliberately unused.
    pinned: dict[str, str] = {}
    # Select doc as the current element from documents while check grounding preserves traversal
    # Details: order.
    # Advance check grounding through the current input element in declared order.
    for doc in documents:
        # Select the guarded path only after `doc.kind is not Kind.FACT` is satisfied.
        if doc.kind is not Kind.FACT:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select tool as the current element from _TOOL_ROW.findall(prose_of(doc)) while check
        # Details: grounding preserves traversal order.
        # Advance check grounding through the current input element in declared order.
        for tool in _TOOL_ROW.findall(prose_of(doc)):
            # removesuffix, not rstrip: rstrip takes a character set, and turned
            # "mypy" into "m", so this check silently skipped it everywhere.
            pinned.setdefault(tool.lower().removesuffix(".py"), doc.doc_id)

    # Select doc as the current element from documents while check grounding preserves traversal
    # Details: order.
    # Advance check grounding through the current input element in declared order.
    for doc in documents:
        # Select the guarded path only after `doc.kind is not Kind.LAW` is satisfied.
        if doc.kind is not Kind.LAW:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Collect unique declared element values; their order is deliberately unordered.
        declared = {str(g) for g in (doc.front_matter.get("grounds_on") or [])}
        # Select rule as the current element from doc.rules while check grounding preserves
        # Details: traversal order.
        # Advance check grounding through the current input element in declared order.
        for rule in doc.rules:
            # Select tool as the current element from _TOOL_WORD.findall((rule.check or
            # Details: "").lower()) while check grounding preserves traversal order.
            # Advance check grounding through the current input element in declared order.
            for tool in _TOOL_WORD.findall((rule.check or "").lower()):
                # Compute owner using pinned.get for later check grounding logic.
                owner = pinned.get(tool)
                # Select the guarded path only after `owner is None or owner in declared` is
                # Details: satisfied.
                if owner is None or owner in declared:
                    # Advance after the current candidate has been conclusively excluded.
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


def check_learning_outcomes(layout: Layout) -> Iterator[Finding]:
    """V097 -- learnings are reported on, so retrieval precision means something.

    The loop writes and does not read back. Ninety-five learnings were recorded
    across six sessions and two outcomes were ever reported, so precision was
    computed from a sample of two and no learning could be promoted on evidence.

    `LEARN` says a session records what it found; nothing said a session reports
    what an earlier finding was worth. That left the most valuable half of the
    subsystem -- knowing which learnings are noise -- resting on a habit, and a
    habit is what `V096` exists because nobody keeps.

    A warning, not an error. A session may legitimately retrieve nothing worth
    reporting on, and failing the gate for it would teach people to record
    nothing rather than to report.

    @param layout the tree holding the ledger
    @return at most one finding, naming how thin the outcome record is
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        import learn  # ruff: ignore[import-outside-top-level] - optional subsystem
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ImportError:
        # Return at most one finding, naming how thin the outcome record is to the caller.
        return
    # Compute store using learn.Store for later check learning outcomes logic.
    store = learn.Store(layout.root)
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute events using learn.read ledger for later check learning outcomes logic.
        events = learn.read_ledger(store)
    except (OSError, learn.LearnError):
        # `V096` owns an unreadable ledger and reports it as an error. Two
        # findings for one fault is noise, and the second would be derived from
        # a count that could not be taken.
        return

    # Counted per learning, not per session: `learn.py record` mints a session id
    # per invocation, so grouping by session reported "68 of 68 sessions" for a
    # ledger holding six real sittings. The ratio is the fact worth acting on.
    recorded = sum(1 for e in events if e.get("kind") == "learn")
    reported = sum(1 for e in events if e.get("kind") == "use")
    if not recorded or reported >= recorded * MIN_OUTCOME_SHARE:
        # Return at most one finding, naming how thin the outcome record is to the caller.
        return
    yield Finding(
        code="V097",
        severity=Severity.WARN,
        path="learning/ledger.jsonl",
        line=1,
        message=(
            f"{recorded} learning(s) recorded and {reported} outcome(s) "
            f"reported; precision rests on {reported} sample(s)"
        ),
        remediation=(
            "Run `learn.py retrieve` before the work and `learn.py used <id> "
            "--outcome helped|noise` after. Until outcomes accumulate, retrieval "
            "precision is computed from too few samples to act on and nothing "
            "can be promoted on evidence."
        ),
    )


def check_discrimination_gap(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V098 -- a decided rule has been watched rejecting something.

    `V080` asks whether a mechanism exists. It has been wrong twice about that,
    both times for the same reason: existence was standing in for agreement. A
    check module existed and did not claim the rule; a fitness function existed
    and declared nothing. Both were corrected by making the mechanism say what it
    decides.

    **Saying is still not doing.** `ARCH-013` named `BaseModel` among the
    framework types a domain may not borrow, claimed the rule properly, was
    counted `mechanized`, and reported nothing against four real domains modelled
    entirely in pydantic -- because it read annotations and never bases. Nothing
    in the corpus could have found that, because nothing had ever put something
    it should reject in front of it.

    So this is the third question, and the last one: has anyone watched it work?
    The invariant the repository is aiming at is that the decided set and the
    discriminated set are the same set, and the difference between them is a
    defect list rather than a fact of life.

    A WARNING with its own ratchet, deliberately, in the same shape as `V051`,
    `V080` and `V097`. Ninety-three rules are in the gap as this ships. Making it
    an error would fail the gate on the day it was written, and a gate that fails
    for a reason nobody can fix that afternoon is a gate people learn to run with
    `--no-verify`. The ratchet is what stops it drifting the wrong way; promoting
    it to an error is a later release's decision, once the number is small enough
    to read as a list.

    @param documents every parsed corpus file
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout the tree they were read from
    @return at most one finding, naming how many decided rules nobody has watched
    """
    # Compute covered using discrimination covered for later check discrimination gap logic.
    covered = discrimination_covered(layout.root)
    # Use the absence path when covered has no available value.
    if covered is None:
        # An adopter may have vendored the corpus without the matrix. Reporting a
        # gap that cannot be computed would be worse than reporting nothing.
        return
    # Unpack gap, doc, rule using sorted for later check discrimination gap logic.
    gap = sorted(
        rule.rule_id
        for doc in documents
        for rule in doc.rules
        if rule.force is Force.BINDING
        and rule.rule_id not in covered
        and rule.mechanisms
        and has_mechanical_claim(rule.mechanisms, layout.root, rule.rule_id)
    )
    # Select the empty-or-disabled path when gap has no usable value.
    if not gap:
        # Return at most one finding, naming how many decided rules nobody has watched to the
        # Details: caller.
        return
    yield Finding(
        code="V098",
        severity=Severity.WARN,
        path="enforce/discrimination.py",
        line=1,
        message=(
            f"{len(gap)} binding rule(s) name a mechanism that nobody has "
            f"watched reject anything: {', '.join(gap[:GAP_NAMED])}"
            f"{' ...' if len(gap) > GAP_NAMED else ''}"
        ),
        remediation=(
            "Declare one concrete mutation per rule in `enforce/discrimination.py` "
            "and run `python tools/discrimination_gate.py`. A mechanism that "
            "exists and has never been observed failing may only ever have said "
            "yes."
        ),
    )


## Structural model findings against their stable validator code, severity, and
## actionable repair. E009 is handled separately as the temporary v3 debt ratchet.
## Each key is an evidence-model code and each value gives validator code, severity, and repair
## text in that tuple order; mapping key order is deliberately unused.
_EVIDENCE_CODES: Final[dict[str, tuple[str, Severity, str]]] = {
    "E001": (
        "V101",
        Severity.ERROR,
        "Add the stable id to discipline/meta/evidence.json before publishing the rule.",
    ),
    "E002": (
        "V102",
        Severity.ERROR,
        "Remove the orphan record or restore its retired normative heading.",
    ),
    "E003": (
        "V103",
        Severity.ERROR,
        "Cite at least one source or adopter observation with relation and confidence.",
    ),
    "E004": (
        "V104",
        Severity.ERROR,
        "Describe every heading mechanism exactly once and no mechanism absent from it.",
    ),
    "E005": (
        "V105",
        Severity.ERROR,
        "Remove active strategies from the retired record.",
    ),
    "E006": (
        "V105",
        Severity.ERROR,
        "Classify a heading with a successor as superseded, consolidated, or retired.",
    ),
    "E007": (
        "V105",
        Severity.ERROR,
        "Add the replacement to Superseded by, or classify a withdrawal as retired.",
    ),
    "E008": (
        "V106",
        Severity.ERROR,
        "Name a concrete must-reject case for every automated strategy.",
    ),
    "E010": (
        "V108",
        Severity.ERROR,
        "Use a mechanism kind compatible with the heading tag.",
    ),
    "E011": (
        "V109",
        Severity.ERROR,
        "Add the named observation to meta/observations.json or remove the reference.",
    ),
    "E012": (
        "V110",
        Severity.ERROR,
        "Name the exact discrimination:<rule>/<mechanism> witness for this strategy.",
    ),
    "E013": (
        "V111",
        Severity.ERROR,
        "Replace generated verifier prose with the exact proposition the mechanism observes.",
    ),
}


def check_evidence(
    documents: Sequence[Document], layout: Layout, *, required: bool | None = None
) -> Iterator[Finding]:
    """V100-V111 -- evidence records join honestly to every stable rule id.

    V107 remains a warning while the frozen v3 discrimination debt is removed;
    unlike the old V098 count, it counts exact rule/mechanism strategies. Every
    structural omission or dishonest join is an error immediately.

    @param documents parsed normative corpus
        Each documents element is one parsed corpus document;
        stable repository-path order is preserved.
    @param layout tree carrying the authored registry and mutation matrix
    @param required whether absence is a defect; defaults true for this repository
        and false for synthetic or legacy trees
    @return structural, join, retirement, kind, and discrimination findings
    """
    # Use the absence path when required has no available value.
    if required is None:
        # Compute required using layout.root == REPO_ROOT for later check evidence logic.
        required = layout.root == REPO_ROOT
    # Select the regular-file path only when `not layout.evidence.is_file()` is satisfied.
    if not layout.evidence.is_file():
        # Handle the non-empty or enabled required state.
        if required:
            yield Finding(
                code="V100",
                severity=Severity.ERROR,
                path=layout.rel(layout.evidence),
                line=1,
                message="the v4 evidence registry is missing",
                remediation=(
                    "Create discipline/meta/evidence.json and record every stable rule id."
                ),
            )
        # Return structural, join, retirement, kind, and discrimination findings to the caller.
        return
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute registry using load evidence for later check evidence logic.
        registry = load_evidence(layout.evidence)
    # Bind problem to the current value used by the next check evidence decision.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except EvidenceParseError as problem:
        yield Finding(
            code="V100",
            severity=Severity.ERROR,
            path=layout.rel(layout.evidence),
            line=1,
            message=str(problem),
            remediation="Repair the named field to match meta/SCHEMA.md section 4.",
        )
        # Return structural, join, retirement, kind, and discrimination findings to the caller.
        return
    # Compute observation ids using None for later check evidence logic.
    observation_ids: frozenset[str] | None = None
    # Select the regular-file path only when `layout.observations.is_file()` is satisfied.
    if layout.observations.is_file():
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            # Compute observations using load observations for later check evidence logic.
            observations = load_observations(layout.observations)
            # Compute observation ids using frozenset for later check evidence logic.
            observation_ids = frozenset(observations.observations)
        # Bind problem to the current value used by the next check evidence decision.
        # Translate the expected failure into this mechanism's stable diagnostic path.
        except EvidenceParseError as problem:
            yield Finding(
                code="V109",
                severity=Severity.ERROR,
                path=layout.rel(layout.observations),
                line=1,
                message=str(problem),
                remediation="Repair the named field to match meta/SCHEMA.md section 4.",
            )
    # Handle the non-empty or enabled required state.
    elif required:
        yield Finding(
            code="V109",
            severity=Severity.ERROR,
            path=layout.rel(layout.observations),
            line=1,
            message="the field-observation registry is missing",
            remediation="Create discipline/meta/observations.json with every cited ID.",
        )

    # Each rules element is one normative rule, flattened in document then declaration order.
    rules = [rule for document in documents for rule in document.rules]
    # Compute witnesses using discrimination witnesses for later check evidence logic.
    witnesses = discrimination_witnesses(layout.root) or frozenset()
    # Compute mismatches using validate evidence for later check evidence logic.
    mismatches = validate_evidence(registry, rules, witnesses, observation_ids)
    # Each unwitnessed element is one E009 discrimination gap in evidence-validation order.
    unwitnessed = [finding for finding in mismatches if finding.code == "E009"]
    # Select finding, mismatch as the current element from (finding for finding in mismatches if
    # Details: finding.code != "E009") while check evidence preserves traversal order.
    # Advance check evidence through the current input element in declared order.
    for mismatch in (finding for finding in mismatches if finding.code != "E009"):
        # Capture code, remediation, severity as the completed check evidence outcome for
        # Details: subsequent validation or publication.
        code, severity, remediation = _EVIDENCE_CODES[mismatch.code]
        yield Finding(
            code=code,
            severity=severity,
            path=layout.rel(layout.evidence),
            line=_evidence_line(layout.evidence, mismatch.rule_id),
            message=f"{mismatch.rule_id}: {mismatch.message}",
            remediation=remediation,
        )
    # Handle the non-empty or enabled unwitnessed state.
    if unwitnessed:
        # Unpack named, finding using ", ".join( for later check evidence logic.
        named = ", ".join(
            f"{finding.rule_id} {finding.message.split()[0]}" for finding in unwitnessed[:GAP_NAMED]
        )
        yield Finding(
            code="V107",
            severity=Severity.WARN,
            path=layout.rel(layout.evidence),
            line=1,
            message=(
                f"{len(unwitnessed)} automated strategy or strategies have no witnessed "
                f"rejection: {named}{' ...' if len(unwitnessed) > GAP_NAMED else ''}"
            ),
            remediation=(
                "Replace each pending:<rule> marker with a concrete matrix case and run "
                "python tools/discrimination_gate.py."
            ),
        )


def _evidence_line(path: Path, rule_id: str) -> int:
    """Locate a rule key in the pretty-printed registry for clickable findings.

    @param path evidence registry
    @param rule_id stable id to locate
    @return one-based line, or 1 when the key cannot be found
    """
    # Compute needle using f'"{rule_id}": {{' for later evidence line logic.
    needle = f'"{rule_id}": {{'
    # Preserve the current decoded diagnostic line before location normalization.
    # Advance evidence line through the current input element in declared order.
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        # Select the guarded path only after `needle in line` is satisfied.
        if needle in line:
            # Return one-based line, or 1 when the key cannot be found to the caller.
            return number
    # Return one-based line, or 1 when the key cannot be found to the caller.
    return 1


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

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        import learn  # ruff: ignore[import-outside-top-level] - optional subsystem
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ImportError:
        # Return at most one finding: an unparsable ledger stops the check there, since to the
        # Details: caller.
        return
    # Compute store using learn.Store for later check learning logic.
    store = learn.Store(layout.root)
    # Treat an absent derived database as the normal state after a clean clone.
    if not store.db.exists():
        # Return without inventing a learning-history finding from absent derived state.
        return
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute events using len for later check learning logic.
        events = len(learn.read_ledger(store))
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except learn.LearnError as exc:
        yield Finding(
            code="V096",
            severity=Severity.ERROR,
            path="learning/ledger.jsonl",
            line=1,
            message=str(exc),
            remediation="Repair the line, or drop it and re-record the event.",
        )
        # Return at most one finding: an unparsable ledger stops the check there, since to the
        # Details: caller.
        return
    import sqlite3  # ruff: ignore[import-outside-top-level] - only needed on this path

    # Compute connection using sqlite3.connect for later check learning logic.
    connection = sqlite3.connect(store.db)
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute stored using connection.execute for later check learning logic.
        stored = connection.execute("SELECT COUNT(*) FROM event").fetchone()[0]
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except sqlite3.DatabaseError:
        # Compute stored using -1 for later check learning logic.
        stored = -1
    finally:
        # Publish the externally visible effect after all required inputs are ready.
        connection.close()
    # Select the guarded path only after `stored != events` is satisfied.
    if stored != events:
        yield Finding(
            code="V096",
            severity=Severity.ERROR,
            path="learning/learning.db",
            line=1,
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
    # Each documents element is one successfully parsed corpus document in repository-path order.
    documents: list[Document] = []
    # Each findings element is one V001 parse diagnostic in repository-path order.
    findings: list[Finding] = []
    # Select the existing-artifact path only when `not layout.discipline.exists()` is satisfied.
    if not layout.discipline.exists():
        # Return the documents that parsed, and a V001 finding for each that did not; to the
        # Details: caller.
        return documents, findings
    # Resolve the repository-confined path used by this operation before filesystem access.
    # Advance load documents through the current input element in declared order.
    for path in sorted(layout.discipline.rglob("*.md")):
        # Select the guarded path only after `path.name == 'INDEX.md'` is satisfied.
        if path.name == "INDEX.md":
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Protect the fallible operation so expected failures remain explicitly classified.
        try:
            documents.append(parse_document(path))
        # Preserve the caught failure that explains why the external result is unusable.
        # Translate the expected failure into this mechanism's stable diagnostic path.
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
    # Return the documents that parsed, and a V001 finding for each that did not; to the caller.
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
    # Compute schema using json.loads for later run logic.
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # Preserve finding-record elements in checker emission order for the final verdict.
    documents, findings = load_documents(layout)
    # Select doc as the current element from documents while run preserves traversal order.
    # Advance run through the current input element in declared order.
    for doc in documents:
        findings.extend(check_front_matter(doc, schema, layout))
        findings.extend(check_genre_constraints(doc, layout))
    findings.extend(check_rules(documents, layout))
    findings.extend(check_evidence(documents, layout))
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
    findings.extend(check_learning_outcomes(layout))
    findings.extend(check_discrimination_gap(documents, layout))
    # Return every finding raised, both severities mixed, in check order with the to the caller.
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
        "--update-baseline",
        action="store_true",
        help="move the V081/V082 ceiling to the corpus's current unbuilt-mechanism count and exit",
    )
    parser.add_argument("--why", help="required with --update-baseline: why the ceiling is moving")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    # Select the guarded path only after `args.update_baseline` is satisfied.
    if args.update_baseline:
        # Select the empty-or-disabled path when args.why has no usable value.
        if not args.why:
            parser.error(
                "--why is required with --update-baseline; an unexplained ceiling move is drift"
            )
        # Compute layout using Layout for later main logic.
        layout = Layout(root)
        # Compute documents using load documents for later main logic.
        documents, _ = load_documents(layout)
        # Compute pairs using unbuilt pairs for later main logic.
        pairs = unbuilt_pairs(documents, layout)
        write_v080_baseline(pairs, args.why)
        print(
            f"recorded {len(pairs)} unbuilt mechanism(s) in {layout.rel(V080_BASELINE_PATH)} -- {args.why}"
        )
        # Return the aggregate process status to the command-line boundary.
        return 0

    # Preserve finding-record elements in checker emission order for the final verdict.
    findings = run(Layout(root))
    # Each errors element represents one diagnostic record; discovery order is preserved.
    errors = [f for f in findings if f.severity is Severity.ERROR]

    # Select the guarded path only after `args.json` is satisfied.
    if args.json:
        # Select f as the current element from findings], indent=2, default=str)) while main
        # Details: preserves traversal order.
        print(json.dumps([asdict(f) for f in findings], indent=2, default=str))
    else:
        # Select finding as the current element from findings while main preserves traversal
        # Details: order.
        # Advance main through the current input element in declared order.
        for finding in findings:
            print(finding.render())
        # Compute counts using defaultdict for later main logic.
        counts: defaultdict[str, int] = defaultdict(int)
        # Select finding as the current element from findings while main preserves traversal
        # Details: order.
        # Advance main through the current input element in declared order.
        for finding in findings:
            # Update main state only after the required source facts are available.
            counts[finding.code] += 1
        # Select the checker summary mapping that carries analyzed-file metrics.
        summary = ", ".join(f"{code}x{n}" for code, n in sorted(counts.items())) or "none"
        print(f"\n{len(errors)} error(s), {len(findings) - len(errors)} warning(s). [{summary}]")

    # Return the aggregate process status to the command-line boundary.
    return 1 if errors else 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
