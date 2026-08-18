"""Shared parsing for the discipline corpus.

Implements the file format specified in `discipline/meta/SCHEMA.md`. Both
`validate.py` and `build_index.py` read the corpus through this module so the two
can never disagree about what a rule is.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Final

import yaml

## Anchor for every other path here, derived from this file rather than the working
## directory, so a tool behaves the same however it was invoked.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent
## The corpus itself: the default root walked by ``iter_documents``.
DISCIPLINE_DIR: Final = REPO_ROOT / "discipline"
## The mechanisms. A cross-reference may point here; SCHEMA.md section 5 admits
## only this, the corpus and the examples as reference targets.
ENFORCE_DIR: Final = REPO_ROOT / "enforce"
## Worked code, for rules whose illustration is too long to sit in a rule body.
EXAMPLES_DIR: Final = DISCIPLINE_DIR / "examples"

## Files written by ``build_index.py``; excluded from authored-content checks.
GENERATED_NAMES: Final[frozenset[str]] = frozenset(
    {"INDEX.md", "rules.json", "ENFORCEMENT.md"}
)

## Ceilings from SCHEMA.md section 2, keyed by file stem with ``*`` as the fallback.
## Exceeding one is an error and not a warning: the budget is what lets an agent
## decide to open a module without first paying to read it.
TOKEN_BUDGETS: Final[Mapping[str, int]] = {"KERNEL": 2_000, "*": 4_000}


class Kind(StrEnum):
    """The genre of a document, which fixes what that document may do.

    Specified in SCHEMA.md section 1.
    """

    ## Binding rules and their mechanisms. One of the two genres that may carry rules,
    ## and the only one forbidden to name a version.
    LAW = "law"
    ## Verified truths about Python and its tooling, each stamped with a date and
    ## re-verified when its decay window closes.
    FACT = "fact"
    ## Vocabulary and reasoning scaffolds. Describes options; prescribing here is an error.
    FRAME = "frame"
    ## Agent dispatch and coordination. The other genre that may carry rules, and the
    ## one that decays fastest, being written against a specific agent harness.
    OPS = "ops"
    ## Documents about the corpus: this format, the glossary, the ledgers.
    META = "meta"


class Force(StrEnum):
    """The normative force of a rule, and what the rule then owes the reader.

    Exactly one tag per heading. Specified in SCHEMA.md section 3.2.
    """

    ## Violation is a defect. Obliges the rule to name a mechanism and a check.
    BINDING = "BINDING"
    ## A strong default, departed from with a recorded reason. Obliges the rule to
    ## say why no mechanism could decide it.
    ADVISORY = "ADVISORY"
    ## Blocked on an undecided question, so it can never also be binding. Obliges an
    ## entry in ``meta/OPEN.md`` naming what the open question blocks.
    OPEN = "OPEN"


class Enforcement(StrEnum):
    """What actually decides a rule, as against how strongly its heading is tagged.

    A force tag is a claim about obligation; this is a measurement of the tree. The
    two come apart constantly -- a rule may be tagged binding and name a mechanism
    nobody has written yet -- and an agent that cannot see the gap will read the tag
    as a guarantee. Computed by ``enforcement_of`` and published per rule in
    ``discipline/rules.json``.

    Tri-state at the bottom because ``mechanism_is_implemented`` is: a mechanism is
    found, is checkable and absent, or is decided somewhere this repository cannot
    look. The vocabulary keeps those three apart rather than flattening them to a
    boolean that would have to lie about one of them.
    """

    ## Every named mechanism was found on disk here, and there was at least one.
    ## This is the only status under which the corpus itself decides the rule.
    MECHANIZED = "mechanized"
    ## No named mechanism is missing, but at least one is settled outside this tree
    ## -- an `auto:*` tag naming a configured tool's own rule, or a `review` tag
    ## sitting alongside a mechanism that was found. Enforced, elsewhere.
    EXTERNAL = "external"
    ## Every named mechanism is `review`: a person or an agent decides it, and
    ## nothing mechanical will ever report it. Not enforced in the machine sense.
    REVIEW = "review"
    ## At least one checkable mechanism names a file or function that is not there.
    ## Paired with a binding force tag, this is the dishonest case the field exists
    ## to surface: the rule reads as enforced and nothing decides it.
    UNBUILT = "unbuilt"
    ## The rule names no mechanism at all. Distinguished from ``MECHANIZED`` because
    ## "every named mechanism resolves" is vacuously true over an empty set, and
    ## reporting the emptiest case as the strongest one is the exact failure this
    ## vocabulary exists to prevent. Ordinary for an advisory rule, a defect for a
    ## binding one -- which V023 already reports.
    UNMECHANIZED = "unmechanized"

    @property
    def is_mechanical(self) -> bool:
        """Whether some machine, here or elsewhere, reports a violation of this rule.

        False for ``REVIEW``: judgment is a mechanism in the corpus's grammar but not
        one that fails a gate, so a review-tagged rule must never be counted as
        enforced. False for ``UNBUILT`` and ``UNMECHANIZED``, which are the two ways
        of having nothing behind the tag.

        @return True only for the two statuses under which a tool decides the rule
        """
        return self in {Enforcement.MECHANIZED, Enforcement.EXTERNAL}


def mechanism_is_implemented(mechanism: str, root: Path = REPO_ROOT) -> bool | None:
    """Whether a mechanism tag points at something that exists.

    The single implementation in the repository. ``validate.py`` reports the False
    case as V080 and ``build_index.py`` derives every rule's ``Enforcement`` from it;
    a second copy would drift, and the two artefacts would then disagree about which
    rules are enforced while both looked authoritative.

    A ``check:`` tag names a module under ``enforce/checks/``; a ``fitness:`` tag
    names a function defined somewhere under ``enforce/fitness/`` or ``tools/``.
    Anything else -- ``auto:*`` for a configured tool's own rule, ``review`` for a
    person -- is not decidable from this tree and is reported as such rather than
    guessed at.

    @param mechanism a tag exactly as a rule heading writes it, such as
        `check:layering` or `fitness:no_cycles`
    @param root the tree to look in, defaulting to this repository
    @return True when the file or function it names is present, False when the tag
        is checkable and nothing answers it, None when it is not checkable here
    """
    kind, _, target = mechanism.partition(":")
    if kind == "check":
        return (root / "enforce" / "checks" / f"{target}.py").exists()
    if kind == "fitness":
        return any(
            f"def {target}(" in path.read_text(encoding="utf-8")
            for directory in (root / "enforce" / "fitness", root / "tools")
            if directory.exists()
            for path in directory.rglob("*.py")
        )
    return None


def enforcement_of(mechanisms: Sequence[str], root: Path = REPO_ROOT) -> Enforcement:
    """Classify a rule's mechanism set into one status an agent can act on.

    Absence dominates: one missing mechanism makes the whole rule ``UNBUILT``,
    whatever else it names, because a rule is only as decided as its weakest tag.
    Below that, the emptiest reading wins over the most flattering one.

    @param mechanisms the rule's tags with the force tag already removed, in the
        order the heading wrote them
    @param root the tree the mechanisms are resolved against
    @return the status; never ``MECHANIZED`` for an empty set, and never a
        mechanical status for a rule decided only by ``review``
    """
    if not mechanisms:
        return Enforcement.UNMECHANIZED
    resolved = [mechanism_is_implemented(m, root) for m in mechanisms]
    if any(state is False for state in resolved):
        return Enforcement.UNBUILT
    if all(state is True for state in resolved):
        return Enforcement.MECHANIZED
    if all(m == "review" for m in mechanisms):
        return Enforcement.REVIEW
    return Enforcement.EXTERNAL


## The delimited YAML header, anchored at the very start of the file. A block that
## begins anywhere else is body text, so a stray ``---`` cannot be read as metadata.
_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)

## A rule heading: id, separator, title, then the run of bracketed tags.
## ``### TYPE-012 · Domain code carries no `Any`  [BINDING] [auto:mypy]``
_RULE_HEADING = re.compile(
    r"^###\s+"
    r"(?P<id>[A-Z][A-Z0-9]{1,7}-\d{3})"
    r"\s*(?:·|\|)\s*"
    r"(?P<title>.+?)"
    r"\s*(?P<tags>(?:\[[^\]]+\]\s*)+)$"
)
## One bracketed tag, applied to the run the heading already isolated.
_TAG = re.compile(r"\[([^\]]+)\]")
## A rule body field. The five names are spelled out rather than matched generically,
## so an invented field is left unrecognized instead of being silently accepted.
_FIELD = re.compile(
    r"^\s*[-*]\s+\*\*(?P<name>Why|Check|See|No mechanism|Superseded by)\*\*\s*(?P<body>.*)$"
)

## A cross-reference target: a rule, a module, or a section of one.
## ``[TYPE-012]`` / ``[law/TYPE]`` / ``[fact/py-typing#strict-flags]``
_XREF = re.compile(r"\[(?P<target>(?:[A-Z][A-Z0-9]{1,7}-\d{3})|(?:[a-z]+/[A-Za-z0-9_-]+(?:#[a-z0-9-]+)?))\]")

## The tools whose versions belong in a dated ``fact`` file and nowhere else.
## Naming them explicitly is what keeps an ordinary number in prose from reading
## as a pin.
_PINNED_TOOLS: Final = (
    "mypy", "pyright", "ruff", "pytest", "hypothesis", "coverage",
    "mutmut", "pydantic", "python", "cpython", "import-linter",
)
## A version literal close enough to a tool name to be a pin. The gap is capped at
## 24 characters and stops at a newline or a period, so a number in the next clause
## is not attributed to a tool named in this one.
_VERSION_NEAR_TOOL = re.compile(
    r"(?i)\b(?P<tool>" + "|".join(_PINNED_TOOLS) + r")\b[^\n.]{0,24}?(?P<ver>\d+\.\d+(?:\.\d+)?)"
)

## A fence line. Opening and closing look alike, so the scanner toggles on each match
## rather than trying to tell them apart.
_CODE_FENCE = re.compile(r"^\s*```")
## A backtick span. Confined to one line, so an unpaired backtick blanks nothing
## beyond the line it sits on.
_INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True, slots=True)
class Rule:
    """One normative rule, parsed from its H3 block."""

    ## ``MODULE-NNN``. Assigned once, never renumbered, never reused; it is quoted in
    ## reviews, commits and diagnostic envelopes, so treat it as public API.
    rule_id: str
    ## Front-matter id of the file this was read from, e.g. ``law/TYPE``.
    module_id: str
    ## The imperative heading text, with the tags removed.
    title: str
    ## Normative weight, taken from the single force tag the heading carried.
    force: Force
    ## The remaining tags, naming what decides the rule. Empty means nothing does.
    mechanisms: tuple[str, ...]
    ## The normative prose between the heading and the first field, joined to one line.
    statement: str
    ## The rationale, tying the rule to the Prime Directive. None when the author gave none.
    why: str | None
    ## The command or test that settles the rule; a binding rule without one is a defect.
    check: str | None
    ## Targets extracted from the ``See`` field, in source order. The validator resolves
    ## each one, which is what stops the corpus growing references to files that never existed.
    see: tuple[str, ...]
    ## Why no mechanism can decide this rule. Belongs to advisory rules and to no others.
    no_mechanism: str | None
    ## What replaced the rule. Set means the heading survives only to reserve its id.
    superseded_by: str | None
    ## The file it was parsed from — the owning document's own ``path``, copied onto
    ## each rule so a finding can travel without the document that produced it.
    path: Path
    ## Line of the heading, counted from 1 in the whole file rather than in the body,
    ## so a finding can be opened where it is reported.
    line: int

    @property
    def prefix(self) -> str:
        """The module prefix embedded in the rule id, e.g. ``TYPE``.

        @return the part before the ordinal, which must match the ``NAME`` half of
            the owning file's id, upper-cased
        """
        return self.rule_id.rsplit("-", 1)[0]

    @property
    def ordinal(self) -> int:
        """The numeric half of the id, the secondary sort key of the rule surface.

        Not a position. Ids are never renumbered, so a deleted rule leaves a gap and
        the largest ordinal in a module exceeds its rule count; a new id is allocated
        from the maximum, never from the count.

        @return the three-digit ordinal as a number, leading zeros dropped
        @throws ValueError when the id does not end in digits
        """
        return int(self.rule_id.rsplit("-", 1)[1])


@dataclass(frozen=True, slots=True)
class Document:
    """One parsed corpus file."""

    ## Where it was read from, kept absolute; ``relpath`` is the form to display.
    path: Path
    ## The YAML header as loaded, with dates normalized back to ISO strings. Typed as
    ## ``object`` because nothing here validates it — that is the validator's job.
    front_matter: Mapping[str, object]
    ## Everything after the closing delimiter, verbatim and unstripped.
    body: str
    ## How many lines the header occupied, added back to make body positions absolute.
    body_offset: int
    ## The rules found in the body, in source order. Empty for the genres that carry none.
    rules: tuple[Rule, ...] = field(default=())

    @property
    def doc_id(self) -> str:
        """The declared ``kind/NAME`` identity, or the empty string when it is missing.

        Empty rather than None so callers may split and compare without a guard; a
        header without an id is a finding for the validator, not a crash here.

        @return the front-matter ``id`` when it is a string, else the empty string
        """
        raw = self.front_matter.get("id")
        return raw if isinstance(raw, str) else ""

    @property
    def kind(self) -> Kind | None:
        """The declared genre, or None when it is absent or not one this format knows.

        @return the matching genre, or None for anything unrecognized
        """
        raw = self.front_matter.get("kind")
        if isinstance(raw, str):
            try:
                return Kind(raw)
            except ValueError:
                return None
        return None

    @property
    def module_name(self) -> str:
        """The ``NAME`` half of ``kind/NAME``.

        This is the prefix every rule id in the file must carry.

        @return the half after the slash, or the whole id when there is no slash
        """
        return self.doc_id.split("/", 1)[-1] if "/" in self.doc_id else self.doc_id

    @property
    def relpath(self) -> str:
        """Location in the form a finding should quote, identical on every platform.

        @return the path below the repository root, with forward slashes
        @throws ValueError when the document lies outside the repository
        """
        return self.path.relative_to(REPO_ROOT).as_posix()

    @property
    def is_generated(self) -> bool:
        """Whether a build writes this file, in which case its content is not authored.

        Checks by name alone: the builders own these three wherever they sit, and an
        authored-content finding against a generated file would be unfixable by hand.

        @return True when the filename is one the builders produce
        """
        return self.path.name in GENERATED_NAMES


class ParseError(ValueError):
    """Raised when a file cannot be parsed far enough to be checked."""

    def __init__(self, path: Path, reason: str) -> None:
        """Compose the message and keep its two halves separately readable.

        A caller that wants to group failures by file should not have to parse the
        rendered string back apart.

        @param path the file that could not be read far enough to check
        @param reason what stopped the parse, as a statement about that file
        """
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def _strip_code(text: str, *, inline: bool = True) -> str:
    """Blank out code, preserving line numbering.

    Fenced blocks are always removed. Inline spans are removed by default, which
    makes backticks the way to write a *format example* of a rule id or reference
    without it being read as a live one.

    @param text the document body to redact
    @param inline whether backtick spans go too, or only fenced blocks
    @return the same number of lines, fenced and fence lines emptied, inline spans
        overwritten with as many spaces as they occupied so columns outside them hold
    """
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if _CODE_FENCE.match(line):
            inside = not inside
            out.append("")
            continue
        if inside:
            out.append("")
            continue
        out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line) if inline else line)
    return "\n".join(out)


def parse_document(path: Path) -> Document:
    """Parse one corpus file into front-matter, body and rules.

    An unquoted ISO date is handed back as a string, so an author need not remember
    to quote ``verified:``.

    @param path the file to read
    @return the document, its rules carrying line numbers absolute in the file
    @throws ParseError when the header is absent, is not valid YAML, or is not a mapping
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ParseError(path, "no YAML front-matter")
    try:
        loaded = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise ParseError(path, f"front-matter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ParseError(path, "front-matter is not a mapping")
    # YAML parses an unquoted ISO date into a date object. Normalize back to the
    # string form the schema declares, so authors need not remember to quote it.
    loaded = {
        key: value.isoformat() if isinstance(value, datetime.date) else value
        for key, value in loaded.items()
    }

    body = text[match.end() :]
    body_offset = text[: match.end()].count("\n")
    doc = Document(path=path, front_matter=loaded, body=body, body_offset=body_offset)
    rules = tuple(_parse_rules(doc))
    return Document(
        path=path,
        front_matter=loaded,
        body=body,
        body_offset=body_offset,
        rules=rules,
    )


def _parse_rules(doc: Document) -> Iterator[Rule]:
    """Every H3 rule block in a body, yielded in the order it was written.

    A heading whose tags name no force is passed over rather than reported: untagged
    prose in a law file is framing, and framing carries no obligation.

    @param doc the document whose body is scanned
    @return each rule found, positioned against the whole file
    """
    # Rule headings inside code fences are format examples, not rules; inline code
    # is kept so a statement may quote an identifier.
    lines = _strip_code(doc.body, inline=False).splitlines()
    for index, line in enumerate(lines):
        heading = _RULE_HEADING.match(line)
        if heading is None:
            continue
        tags = [t.strip() for t in _TAG.findall(heading.group("tags"))]
        force = _force_from_tags(tags)
        if force is None:
            continue
        mechanisms = tuple(t for t in tags if t not in {f.value for f in Force})
        block = _block_after(lines, index)
        yield Rule(
            rule_id=heading.group("id"),
            module_id=doc.doc_id,
            title=heading.group("title").strip(),
            force=force,
            mechanisms=mechanisms,
            statement=_statement_of(block),
            why=_field_of(block, "Why"),
            check=_field_of(block, "Check"),
            see=tuple(_XREF.findall(_field_of(block, "See") or "")),
            no_mechanism=_field_of(block, "No mechanism"),
            superseded_by=_field_of(block, "Superseded by"),
            path=doc.path,
            line=doc.body_offset + index + 1,
        )


def _force_from_tags(tags: Sequence[str]) -> Force | None:
    """The first tag naming a normative weight, the mechanism tags passing by.

    None means the heading is not a rule, which is how an ordinary H3 that happens
    to start with an id-shaped word is left alone.

    @param tags the bracketed tags from a heading, in written order
    @return the weight found, or None when none of them name one
    """
    for tag in tags:
        try:
            return Force(tag)
        except ValueError:
            continue
    return None


def _block_after(lines: Sequence[str], index: int) -> list[str]:
    """Lines belonging to the rule that starts at ``index``, exclusive of its heading.

    Stops at the next heading of any level, so a rule body cannot silently swallow
    the section beneath it.

    @param lines the body, already split, with fenced blocks blanked
    @param index position of the heading line
    @return the lines under it, up to the next heading or the end
    """
    block: list[str] = []
    for line in lines[index + 1 :]:
        if line.startswith("#"):
            break
        block.append(line)
    return block


def _statement_of(block: Sequence[str]) -> str:
    """The normative prose of a rule: everything above its first field line.

    Folded onto one line, so a sentence that wrapped in the source reads the same as
    one that did not.

    @param block the lines under a rule heading
    @return the statement as a single line, empty when the rule states nothing
    """
    parts: list[str] = []
    for line in block:
        if _FIELD.match(line):
            break
        if line.strip():
            parts.append(line.strip())
    return " ".join(parts)


def _field_of(block: Sequence[str], name: str) -> str | None:
    """One named field of a rule body, its continuation lines folded in.

    Capture ends at the next field or at the first blank line, so a wrapped continuation
    line belongs to the field above it while the paragraph after a gap does not.

    @param block the lines under a rule heading
    @param name the field wanted, spelled as it is in the source
    @return the field on one line, or None when the rule does not carry it
    """
    collected: list[str] = []
    capturing = False
    for line in block:
        found = _FIELD.match(line)
        if found is not None:
            if capturing:
                break
            if found.group("name") == name:
                capturing = True
                collected.append(found.group("body").strip())
            continue
        if capturing:
            if not line.strip():
                break
            collected.append(line.strip())
    return " ".join(collected) if collected else None


def iter_documents(root: Path = DISCIPLINE_DIR) -> Iterator[Document]:
    """Yield every corpus document below ``root``, in stable path order.

    Generated files are passed over: they are output, and a finding against one
    names something no author can fix.

    @param root the directory to walk
    @return each authored document beneath it, sorted by path
    @throws ParseError when a file below the root cannot be parsed
    """
    for path in sorted(root.rglob("*.md")):
        if path.name in GENERATED_NAMES:
            continue
        yield parse_document(path)


def prose_of(doc: Document) -> str:
    """Document body with all code removed, for text-level checks.

    Line numbering survives the redaction, so an index into this text is an index into
    the body; add ``doc.body_offset`` to turn it into a line of the file on disk.

    @param doc the document to redact
    @return the body with fenced blocks and backtick spans blanked
    """
    return _strip_code(doc.body)


def body_without_fences(doc: Document) -> str:
    """Document body with fenced blocks removed but inline code intact.

    The right scope for scanning document mentions: a filename inside a fenced
    example is illustration, one in a sentence is a live reference.

    @param doc the document to redact
    @return the body with fences blanked and backtick spans left as written
    """
    return _strip_code(doc.body, inline=False)


def find_version_literals(prose: str) -> list[tuple[str, str]]:
    """Every version pin in a passage, paired with the tool it pins.

    A law file may require a capability but never a version; pins belong in a dated
    fact file, where the date says when to distrust them. See SCHEMA.md section 1.

    @param prose text with code already stripped, so a fenced example is not read as a pin
    @return each tool with the version literal found beside it, in source order
    """
    return [(m.group("tool"), m.group("ver")) for m in _VERSION_NEAR_TOOL.finditer(prose)]


def find_xrefs(text: str) -> list[str]:
    """Every cross-reference target in ``text``, as written and in source order.

    Duplicates are kept and nothing is resolved here; whether a target exists is the
    validator's finding to make.

    @param text the passage to scan, usually a body with fences already removed
    @return the raw targets, e.g. ``TYPE-012`` or ``fact/py-typing#strict-flags``
    """
    return _XREF.findall(text)


def count_tokens(text: str) -> int:
    """Token count, measured with tiktoken where available.

    Falls back to a character-ratio estimate when the encoding cannot be
    downloaded, so a validation run never fails for lack of network.

    @param text the passage to measure
    @return the count, exact under the real encoding and approximate without it
    """
    encoding = _encoding()
    if encoding is None:
        return round(len(text) / 3.7)
    return len(encoding.encode(text))


@lru_cache(maxsize=1)
def _encoding() -> object | None:
    """The tokenizer, constructed once.

    Building it per call made a validation run take over a minute: the graph
    measures every rule and the builders measure every file. None selects the
    character-ratio estimate instead.

    @return the tokenizer, or None when it is not installed or cannot be built
    """
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding("o200k_base")
    except Exception:  # ruff: ignore[blind-except] - no network, no cached vocabulary
        return None


def budget_for(doc: Document) -> int:
    """The token ceiling a document must stay under, by filename.

    ``KERNEL.md`` is held tighter than the rest because every agent reads it and
    nothing routes without it.

    @param doc the document whose ceiling is wanted
    @return the ceiling in tokens, falling back to the general module limit
    """
    return TOKEN_BUDGETS.get(doc.path.stem, TOKEN_BUDGETS["*"])
