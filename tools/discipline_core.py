"""Shared parsing for the discipline corpus.

Implements the file format specified in `discipline/meta/SCHEMA.md`. Both
`validate.py` and `build_index.py` read the corpus through this module so the two
can never disagree about what a rule is.
"""

from __future__ import annotations

import ast
import datetime
import re
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence

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
GENERATED_NAMES: Final[frozenset[str]] = frozenset({"INDEX.md", "rules.json", "ENFORCEMENT.md"})

## Ceilings from SCHEMA.md section 2, keyed by file stem with ``*`` as the fallback.
## Exceeding one is an error and not a warning: the budget is what lets an agent
## decide to open a module without first paying to read it.
## Treat TOKEN BUDGETS as mapping elements whose keys identify fields and values carry their
## content; key order is deliberately unused.
TOKEN_BUDGETS: Final[Mapping[str, int]] = {"KERNEL": 2_000, "*": 4_000}

## The divisor ``count_tokens`` measures by, and therefore the definition of the
## ``tokens:`` field. Chosen to sit close to a byte-pair encoder over English
## markdown while depending on nothing that has to be installed or downloaded.
## Changing it renumbers every module in the corpus, so it moves only with a
## rebuild of every generated artifact in the same change.
CHARACTERS_PER_TOKEN: Final = 3.7


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
    ## Historical stable ID with no current normative force or active mechanism.
    RETIRED = "RETIRED"


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
        # Count only locally resolved and externally automated enforcement as machine-decidable.
        return self in {Enforcement.MECHANIZED, Enforcement.EXTERNAL}


def rules_claimed_by(check: str, root: Path = REPO_ROOT) -> frozenset[str] | None:
    """Which rules a check module says it decides, read from its `rules` tuple.

    Parsed rather than imported: the census runs in `build_index.py`, which must
    not execute a check to find out what it claims.

    @param check the check's module name, as a `check:` tag writes it
    @param root the tree to look in
    @return the rule ids it names, or None when the module or the tuple is absent
    """
    # Resolve the named check only beneath this repository's shipped check directory.
    path = root / "enforce" / "checks" / f"{check}.py"
    try:
        # Parse the Python source into the syntax tree used for structural fingerprinting.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        # Treat unreadable or unparsable check source as an unresolved declaration.
        return None
    # Search assignments structurally without executing module import side effects.
    for node in ast.walk(tree):
        # Only plain assignments can declare the module-level rules tuple.
        if not isinstance(node, ast.Assign):
            # Continue past unrelated syntax nodes.
            continue
        # Match any assignment target named exactly ``rules``.
        if not any(getattr(t, "id", "") == "rules" for t in node.targets):
            # Continue until the module's claim declaration is found.
            continue
        # Accept only literal tuple or list containers whose contents can be inspected safely.
        if isinstance(node.value, (ast.Tuple, ast.List)):
            # Return literal string ids; each element is a claimed rule and order is unused.
            return frozenset(
                element.value
                # Each AST element contributes only when it is a textual constant.
                for element in node.value.elts
                if isinstance(element, ast.Constant) and isinstance(element.value, str)
            )
    # No literal module-level claim tuple means this resolver has no claim information.
    return None


def rules_declared_by(function: str, root: Path = REPO_ROOT) -> frozenset[str] | None:
    """Which rules a fitness test says it decides, read from its `@decides`.

    Parsed rather than imported, for the reason `rules_claimed_by` is: the census
    runs in `build_index.py`, which must not execute a test suite to find out what
    it claims. Parsing also means a decorator that names a constant instead of a
    literal resolves to nothing rather than to something wrong.

    Both trees are searched. Thirty-four of the forty tagged functions live in
    `enforce/fitness/`, but six are in `tools/test_*.py` -- `test_a_dry_run_writes_nothing`
    and its kin -- and a resolver narrowed to the suites would silently undecide them.

    An empty set and None mean different things and both are false-y on purpose
    only at the call site: None is "no such function", an empty set is "the
    function is there and has declared nothing".

    @param function the test's name, as a `fitness:` tag writes it
    @param root the tree to look in
    @return the union of the ids it declares, or None when no such function exists
    """
    # True enables found; false selects its disabled alternative.
    found = False
    # Collect unique declared element values; their order is deliberately unordered.
    declared: set[str] = set()
    for directory in (root / "enforce" / "fitness", root / "tools"):
        # An absent search family contributes no candidate functions.
        if not directory.exists():
            # Continue with the other supported fitness location.
            continue
        # Parse every Python candidate under the supported fitness location.
        for path in directory.rglob("*.py"):
            # Treat authored source as data; do not import tests during the census.
            try:
                # Parse the candidate while retaining its filename in syntax diagnostics.
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            # An unreadable or unparsable candidate cannot declare the requested function.
            except (OSError, SyntaxError):
                # Continue searching independent candidate files.
                continue
            # Inspect both synchronous and asynchronous function definitions structurally.
            for node in ast.walk(tree):
                # Ignore every syntax node that cannot carry the ``@decides`` declaration.
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Continue traversal without interpreting unrelated syntax.
                    continue
                # Only the exact fitness function named by the mechanism contributes evidence.
                if node.name != function:
                    # Continue searching for another same-file function definition.
                    continue
                # True means a matching function definition exists; false means none exists.
                found = True
                # Union literal ids from every matching definition without executing decorators.
                declared |= _declared_on(node)
    # Distinguish an existing undecorated function from an absent function.
    return frozenset(declared) if found else None


def _declared_on(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    """Read the rule ids out of one function's `@decides(...)` decorator.

    @param node the function definition to inspect
    @return the literal string arguments, or an empty set when it is undecorated
    """
    # Collect unique ids element values; their order is deliberately unordered.
    ids: set[str] = set()
    for decorator in node.decorator_list:
        # Only called decorators can carry literal ``@decides(...)`` arguments.
        if not isinstance(decorator, ast.Call):
            # Continue past marker decorators without argument lists.
            continue
        # Normalize attribute and bare-name call targets to their terminal identifier.
        target = decorator.func
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        # Ignore every decorator other than the explicit decision declaration.
        if name != "decides":
            # Continue searching sibling decorators on the same function.
            continue
        # Add literal textual rule ids; each argument is one claim and order is unused.
        ids |= {
            argument.value
            for argument in decorator.args
            if isinstance(argument, ast.Constant) and isinstance(argument.value, str)
        }
    # Return the complete literal declaration, empty when no suitable decorator was present.
    return ids


def mechanism_is_implemented(
    mechanism: str, root: Path = REPO_ROOT, rule_id: str | None = None
) -> bool | None:
    """Whether a mechanism tag points at something that decides this rule.

    The single implementation in the repository. ``validate.py`` reports the False
    case as V080 and ``build_index.py`` derives every rule's ``Enforcement`` from it;
    a second copy would drift, and the two artefacts would then disagree about which
    rules are enforced while both looked authoritative.

    A ``check:`` tag names a module under ``enforce/checks/``; a ``fitness:`` tag
    names a function defined somewhere under ``enforce/fitness/`` or ``tools/``.
    Anything else -- ``auto:*`` for a configured tool's own rule, ``review`` for a
    person -- is not decidable from this tree and is reported as such rather than
    guessed at.

    Both tags are resolved against what the mechanism itself declares when a rule
    id is supplied: a check against its `rules` tuple, a fitness test against its
    `@decides` decorator. Something that exists but does not name this rule decides
    nothing about it.

    The two arms differ in one place, deliberately. A check with no `rules` tuple
    at all is given the benefit of the doubt; **a fitness test with no `@decides`
    is not.** Treating a missing declaration as consent is precisely how sixty-four
    rules came to rest on a tag that only ever asked whether some file contained
    the text `def <name>(`.

    @param mechanism a tag exactly as a rule heading writes it, such as
        `check:layering` or `fitness:no_cycles`
    @param root the tree to look in, defaulting to this repository
    @param rule_id the rule being resolved, so a tag can be held to what the
        mechanism claims; omitted, the older existence-only answer is given
    @return True when something that names this rule is present, False when the
        tag is checkable and nothing answers it, None when it is not checkable
    """
    # Split the tag once into mechanism family and family-specific target.
    kind, _, target = mechanism.partition(":")
    # Local check tags resolve to shipped check modules and optional claim tuples.
    if kind == "check":
        # Absence of the named module is a mechanically decidable unbuilt mechanism.
        if not (root / "enforce" / "checks" / f"{target}.py").exists():
            # Report definite absence rather than external uncertainty.
            return False
        # Existence-only callers stop after proving the check module is present.
        if rule_id is None:
            # Preserve backward-compatible existence semantics when no joined rule is supplied.
            return True
        # Existence is not enough, and assuming it was is how fifteen binding
        # rules came to be counted decided by checks that could never report
        # them. Several of those checks said so in their own docstrings while
        # their `rules` tuple claimed the rule anyway; nothing read the tuple.
        # Parse the module's literal rule claims without importing check code.
        claimed = rules_claimed_by(target, root)
        # An absent tuple retains legacy benefit-of-doubt; a present tuple must name the rule.
        return True if claimed is None else rule_id in claimed
    # Fitness tags require a function whose literal decorator claims the joined rule.
    if kind == "fitness":
        # Resolve the named function across both supported fitness source families.
        declared = rules_declared_by(target, root)
        # Missing functions are mechanically decidable absent fitness mechanisms.
        if declared is None:
            # Refuse existence credit when no matching definition can be parsed.
            return False
        # Existence-only callers accept the function; joined callers require its exact rule id.
        return True if rule_id is None else rule_id in declared
    # Auto and review tags are decided outside this repository-local structural resolver.
    return None


def enforcement_of(
    mechanisms: Sequence[str], root: Path = REPO_ROOT, rule_id: str | None = None
) -> Enforcement:
    """Classify a rule's mechanism set into one status an agent can act on.

    Absence dominates: one missing mechanism makes the whole rule ``UNBUILT``,
    whatever else it names, because a rule is only as decided as its weakest tag.
    Below that, the emptiest reading wins over the most flattering one.

    @param mechanisms the rule's tags with the force tag already removed, in the
        order the heading wrote them
        Each element is one declared mechanism tag; heading order is preserved.
    @param root the tree the mechanisms are resolved against
    @param rule_id the rule being classified, so a ``check:`` tag is resolved
        against what that check claims rather than against its mere existence
    @return the status; never ``MECHANIZED`` for an empty set, and never a
        mechanical status for a rule decided only by ``review``
    """
    # Empty mechanism sets must not gain mechanized status through vacuous universal predicates.
    if not mechanisms:
        # Preserve the explicit unmechanized classification.
        return Enforcement.UNMECHANIZED
    # Each resolved element is one mechanism implementation verdict; heading mechanism order is
    # preserved.
    resolved = [mechanism_is_implemented(m, root, rule_id) for m in mechanisms]
    # One definitely absent local mechanism makes the complete rule enforcement unbuilt.
    if any(state is False for state in resolved):
        # Absence dominates working or external sibling arms.
        return Enforcement.UNBUILT
    # All local resolutions establish fully repository-mechanized enforcement.
    if all(state is True for state in resolved):
        # Return the strongest status only for a non-empty all-true sequence.
        return Enforcement.MECHANIZED
    # A pure review set represents human judgment rather than external automation.
    if all(m == "review" for m in mechanisms):
        # Keep review-only rules out of mechanical enforcement counts.
        return Enforcement.REVIEW
    # Remaining sets contain at least one external automated arm and no known absence.
    return Enforcement.EXTERNAL


def has_mechanical_claim(
    mechanisms: Sequence[str], root: Path = REPO_ROOT, rule_id: str | None = None,
) -> bool:
    """Whether at least one mechanism arm claims a machine-decidable proposition.

    This is deliberately not ``enforcement_of(...).is_mechanical``. Overall
    enforcement fails closed when any local arm is unbuilt, while the
    discrimination census must still retain another working or external tool arm.
    Review is the one undecidable mechanism that is explicitly semantic rather
    than an external mechanical claim.

    @param mechanisms heading tags after the normative force
        Each element is one declared mechanism tag; heading order is preserved.
    @param root tree against which local mechanisms resolve
    @param rule_id rule each local mechanism must claim, when known
    @return True for at least one local or external mechanical arm, never review alone
    """
    # Detect at least one non-review arm that is external or locally implemented.
    return any(
        mechanism != "review"
        and mechanism_is_implemented(mechanism, root, rule_id) is not False
        # Each mechanism is evaluated independently so an unbuilt sibling cannot hide a claim.
        for mechanism in mechanisms
    )


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
_XREF = re.compile(
    r"\[(?P<target>(?:[A-Z][A-Z0-9]{1,7}-\d{3})|(?:[a-z]+/[A-Za-z0-9_-]+(?:#[a-z0-9-]+)?))\]"
)

## The tools whose versions belong in a dated ``fact`` file and nowhere else.
## Naming them explicitly is what keeps an ordinary number in prose from reading
## as a pin.
## Each element is one native or Python tool name whose numeric version can denote a pin;
## declaration order is preserved for grammar matching.
_PINNED_TOOLS: Final = (
    "mypy",
    "pyright",
    "ruff",
    "pytest",
    "hypothesis",
    "coverage",
    "mutmut",
    "cosmic-ray",
    "pydantic",
    "python",
    "cpython",
    "import-linter",
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
    ## Each element is one declared mechanism tag; heading order is preserved.
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
        # Split at the final ordinal separator so compound family names remain intact.
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
        # Parse only the final id segment as the stable numeric ordinal.
        return int(self.rule_id.rsplit("-", 1)[1])


@dataclass(frozen=True, slots=True)
class Document:
    """One parsed corpus file."""

    ## Where it was read from, kept absolute; ``relpath`` is the form to display.
    path: Path
    ## The YAML header as loaded, with dates normalized back to ISO strings. Typed as
    ## ``object`` because nothing here validates it — that is the validator's job.
    ## Treat front matter as mapping elements whose keys identify fields and values carry their
    ## content; key order is deliberately unused.
    front_matter: Mapping[str, object]
    ## Everything after the closing delimiter, verbatim and unstripped.
    body: str
    ## How many lines the header occupied, added back to make body positions absolute.
    body_offset: int
    ## The rules found in the body, in source order. Empty for the genres that carry none.
    ## Each element is one parsed rule record; document source order is preserved.
    rules: tuple[Rule, ...] = field(default=())

    @property
    def doc_id(self) -> str:
        """The declared ``kind/NAME`` identity, or the empty string when it is missing.

        Empty rather than None so callers may split and compare without a guard; a
        header without an id is a finding for the validator, not a crash here.

        @return the front-matter ``id`` when it is a string, else the empty string
        """
        # Read the authored document identity without coercing malformed front matter.
        raw = self.front_matter.get("id")
        # Preserve textual identity exactly; malformed values become the validator-visible empty id.
        return raw if isinstance(raw, str) else ""

    @property
    def kind(self) -> Kind | None:
        """The declared genre, or None when it is absent or not one this format knows.

        @return the matching genre, or None for anything unrecognized
        """
        # Read the authored genre value before checking its controlled-vocabulary type.
        raw = self.front_matter.get("kind")
        # Only textual front-matter values can name the controlled genre vocabulary.
        if isinstance(raw, str):
            # Translate unknown genre text to absence without hiding it from schema validation.
            try:
                # Return the exact known genre member.
                return Kind(raw)
            # Unknown text remains a validation concern rather than a parser crash.
            except ValueError:
                # Expose no semantic kind for the unrecognized value.
                return None
        # Missing or non-text genre values have no parsed semantic kind.
        return None

    @property
    def module_name(self) -> str:
        """The ``NAME`` half of ``kind/NAME``.

        This is the prefix every rule id in the file must carry.

        @return the half after the slash, or the whole id when there is no slash
        """
        # Strip a present genre prefix while retaining malformed unslashed ids for validation.
        return self.doc_id.split("/", 1)[-1] if "/" in self.doc_id else self.doc_id

    @property
    def rule_prefix(self) -> str:
        """The rule-id prefix owned by this module or declared partition.

        A large family may be physically partitioned as ``ARCH-PORTS`` while
        retaining stable ``ARCH-NNN`` identities. The optional front-matter
        value makes that exception explicit; ordinary modules derive it from
        their own identity as before.

        @return uppercase rule prefix
        """
        # Read the optional explicit rule partition before applying the document-id default.
        raw = self.front_matter.get("rule_prefix")
        # Prefer an explicit partition prefix; otherwise derive the module's uppercase identity.
        return raw if isinstance(raw, str) else self.module_name.upper()

    @property
    def relpath(self) -> str:
        """Location in the form a finding should quote, identical on every platform.

        @return the path below the repository root, with forward slashes
        @throws ValueError when the document lies outside the repository
        """
        # Normalize the repository-relative location to platform-independent report spelling.
        return self.path.relative_to(REPO_ROOT).as_posix()

    @property
    def is_generated(self) -> bool:
        """Whether a build writes this file, in which case its content is not authored.

        Checks by name alone: the builders own these three wherever they sit, and an
        authored-content finding against a generated file would be unfixable by hand.

        @return True when the filename is one the builders produce
        """
        # Classify by the fixed builder-owned filename vocabulary.
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
        # Retain the source path independently for grouping and navigation.
        self.path = path
        # Retain the structural refusal reason without reparsing formatted exception text.
        self.reason = reason


def _strip_code(text: str, *, inline: bool = True) -> str:
    """Blank out code, preserving line numbering.

    Fenced blocks are always removed. Inline spans are removed by default, which
    makes backticks the way to write a *format example* of a rule id or reference
    without it being read as a live one.

    @param text the document body to redact
    @param inline whether backtick spans go too, or only fenced blocks
        True enables inline; false selects its disabled alternative.
    @return the same number of lines, fenced and fence lines emptied, inline spans
        overwritten with as many spaces as they occupied so columns outside them hold
    """
    # Each out element is one source character outside fenced examples or a masking space inside;
    # exact character order is preserved.
    out: list[str] = []
    # True enables inside; false selects its disabled alternative.
    inside = False
    for line in text.splitlines():
        # Fence lines toggle redaction state and remain as blank positional placeholders.
        if _CODE_FENCE.match(line):
            # Enter or leave the fenced-example region.
            inside = not inside
            out.append("")
            # Continue without exposing fence syntax as doctrine prose.
            continue
        # Every line inside a fenced example is blanked while retaining its line slot.
        if inside:
            out.append("")
            # Continue to the next source line without inline processing.
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
    # Read the complete module once so front-matter and body locations share one coordinate space.
    text = path.read_text(encoding="utf-8")
    # Match the required opening YAML fence before attempting to parse its payload.
    match = _FRONT_MATTER.match(text)
    # A corpus document must start with the delimited YAML header.
    if match is None:
        # Refuse body-only Markdown before YAML parsing.
        raise ParseError(path, "no YAML front-matter")
    # Translate YAML decoder failures to the document parser's stable error shape.
    try:
        # Decode only the captured header, leaving the document body untouched.
        loaded = yaml.safe_load(match.group("yaml"))
    # Preserve the native YAML failure as the cause of the localized parse refusal.
    except yaml.YAMLError as exc:
        # Name the source document whose header cannot be interpreted.
        raise ParseError(path, f"front-matter is not valid YAML: {exc}") from exc
    # Top-level scalar and sequence YAML cannot satisfy keyed corpus metadata.
    if not isinstance(loaded, dict):
        # Refuse before any front-matter field access.
        raise ParseError(path, "front-matter is not a mapping")
    # YAML parses an unquoted ISO date into a date object. Normalize back to the
    # string form the schema declares, so authors need not remember to quote it.
    # Treat loaded as mapping elements whose keys are front-matter fields and whose values are
    # normalized YAML values; YAML insertion order is preserved for deterministic processing.
    loaded = {
        # Each field retains its value except date objects, which become schema-declared ISO text.
        key: value.isoformat() if isinstance(value, datetime.date) else value
        for key, value in loaded.items()
    }

    # Preserve body text and compute its source-line offset from the same front-matter match.
    body = text[match.end() :]
    body_offset = text[: match.end()].count("\n")
    doc = Document(path=path, front_matter=loaded, body=body, body_offset=body_offset)
    rules = tuple(_parse_rules(doc))
    # Publish the final immutable document after attaching parsed rules with absolute line numbers.
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
    # Scan each body line in source order so yielded rules and diagnostics remain stable.
    for index, line in enumerate(lines):
        # Attempt to parse only the strict id, title, and bracketed-tag heading grammar.
        heading = _RULE_HEADING.match(line)
        # Ordinary H3 prose and malformed headings are not parser-level rules.
        if heading is None:
            # Continue searching later source lines for valid rule headings.
            continue
        # Each tags element is one normalized rule-heading tag; authored heading order is
        # preserved.
        tags = [t.strip() for t in _TAG.findall(heading.group("tags"))]
        force = _force_from_tags(tags)
        # A tagged heading without normative force remains non-rule framing prose.
        if force is None:
            # Continue to later headings without manufacturing advisory semantics.
            continue
        # Remove every controlled force tag while preserving authored mechanism order.
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
        Each element is one normalized heading tag; authored tag order is
        preserved.
    @return the weight found, or None when none of them name one
    """
    # Examine heading tags in authored order; the first controlled force wins.
    for tag in tags:
        # Treat unknown mechanism tags as non-force values rather than parser failures.
        try:
            # Return immediately when this tag names a normative force.
            return Force(tag)
        # Unknown tags may still be valid mechanisms, so continue scanning.
        except ValueError:
            # Preserve order while looking for a later force tag.
            continue
    # No controlled force means the heading does not define a rule.
    return None


def _block_after(lines: Sequence[str], index: int) -> list[str]:
    """Lines belonging to the rule that starts at ``index``, exclusive of its heading.

    Stops at the next heading of any level, so a rule body cannot silently swallow
    the section beneath it.

    @param lines the body, already split, with fenced blocks blanked
        Each element is one body line with fenced content blanked; source order is preserved.
    @param index position of the heading line
    @return the lines under it, up to the next heading or the end
    """
    # Each block element is one source line owned by the selected heading; document order is
    # preserved.
    block: list[str] = []
    for line in lines[index + 1 :]:
        # Any subsequent Markdown heading terminates ownership of this rule body.
        if line.startswith("#"):
            # End rule-body capture at the next Markdown heading.
            break
        block.append(line)
    return block


def _statement_of(block: Sequence[str]) -> str:
    """The normative prose of a rule: everything above its first field line.

    Folded onto one line, so a sentence that wrapped in the source reads the same as
    one that did not.

    @param block the lines under a rule heading
        Each element is one source line from the rule block; document order is
        preserved.
    @return the statement as a single line, empty when the rule states nothing
    """
    # Each parts element is one prose line from the rule statement; source order is preserved
    # before whitespace joining.
    parts: list[str] = []
    for line in block:
        # The first structured field terminates free-form normative statement prose.
        if _FIELD.match(line):
            # End normative-statement capture before the first structured field.
            break
        # Blank lines do not contribute whitespace tokens to the folded statement.
        if line.strip():
            parts.append(line.strip())
    # Fold retained prose lines with one space for wrap-insensitive comparison.
    return " ".join(parts)


def _field_of(block: Sequence[str], name: str) -> str | None:
    """One named field of a rule body, its continuation lines folded in.

    Capture ends at the next field or at the first blank line, so a wrapped continuation
    line belongs to the field above it while the paragraph after a gap does not.

    @param block the lines under a rule heading
        Each element is one source line from the rule block; document order is
        preserved.
    @param name the field wanted, spelled as it is in the source
    @return the field on one line, or None when the rule does not carry it
    """
    # Each collected element is one continuation line from the selected rule field; source order
    # is preserved before joining.
    collected: list[str] = []
    # True enables capturing; false selects its disabled alternative.
    capturing = False
    for line in block:
        # Parse each possible field header while tracking whether the requested field is active.
        found = _FIELD.match(line)
        # A new field either begins capture or terminates the field already being captured.
        if found is not None:
            # The next field header ends continuation ownership of the requested field.
            if capturing:
                # End the requested field once the next field header begins.
                break
            # Begin capture only for the exact requested controlled field name.
            if found.group("name") == name:
                # Mark later continuation lines as belonging to this field.
                capturing = True
                collected.append(found.group("body").strip())
            # Field header handling is complete; do not treat it as a continuation line.
            continue
        # Only lines after the requested header can extend its value.
        if capturing:
            # A blank line terminates continuation ownership.
            if not line.strip():
                # End field continuation at the first blank separator line.
                break
            collected.append(line.strip())
    # Fold captured lines or preserve absence distinctly when the field was not found.
    return " ".join(collected) if collected else None


def iter_documents(root: Path = DISCIPLINE_DIR) -> Iterator[Document]:
    """Yield every corpus document below ``root``, in stable path order.

    Generated files are passed over: they are output, and a finding against one
    names something no author can fix.

    @param root the directory to walk
    @return each authored document beneath it, sorted by path
    @throws ParseError when a file below the root cannot be parsed
    """
    # Traverse authored Markdown candidates in platform-stable lexical path order.
    for path in sorted(root.rglob("*.md")):
        # Builder-owned documents are outputs and cannot be repaired as authored sources.
        if path.name in GENERATED_NAMES:
            # Continue to the next authored candidate.
            continue
        yield parse_document(path)


def prose_of(doc: Document) -> str:
    """Document body with all code removed, for text-level checks.

    Line numbering survives the redaction, so an index into this text is an index into
    the body; add ``doc.body_offset`` to turn it into a line of the file on disk.

    @param doc the document to redact
    @return the body with fenced blocks and backtick spans blanked
    """
    # Remove both fenced examples and inline identifiers for prose-only analysis.
    return _strip_code(doc.body)


def body_without_fences(doc: Document) -> str:
    """Document body with fenced blocks removed but inline code intact.

    The right scope for scanning document mentions: a filename inside a fenced
    example is illustration, one in a sentence is a live reference.

    @param doc the document to redact
    @return the body with fences blanked and backtick spans left as written
    """
    # Remove fenced examples while retaining inline references as live mentions.
    return _strip_code(doc.body, inline=False)


def find_version_literals(prose: str) -> list[tuple[str, str]]:
    """Every version pin in a passage, paired with the tool it pins.

    A law file may require a capability but never a version; pins belong in a dated
    fact file, where the date says when to distrust them. See SCHEMA.md section 1.

    @param prose text with code already stripped, so a fenced example is not read as a pin
    @return each tool with the version literal found beside it, in source order
    """
    # Preserve each regex match as a tool/version pair in source order.
    return [
        # Each match contributes the named tool and adjacent version capture.
        (m.group("tool"), m.group("ver")) for m in _VERSION_NEAR_TOOL.finditer(prose)
    ]


def find_xrefs(text: str) -> list[str]:
    """Every cross-reference target in ``text``, as written and in source order.

    Duplicates are kept and nothing is resolved here; whether a target exists is the
    validator's finding to make.

    @param text the passage to scan, usually a body with fences already removed
    @return the raw targets, e.g. ``TYPE-012`` or ``fact/py-typing#strict-flags``
    """
    # Preserve duplicate raw targets in source order for validator-level resolution.
    return _XREF.findall(text)


def count_tokens(text: str) -> int:
    """The `tokens:` measurement, by the definition in `meta/SCHEMA.md`.

    Deliberately arithmetic rather than a real tokenizer. An earlier version
    imported tiktoken when it was installed and estimated when it was not, which
    meant `build_index.py` wrote DIFFERENT BYTES on two machines running the same
    command over the same corpus, and nothing reported the difference. Every
    committed `tokens:` value came from the estimate; the tokenizer branch shipped
    for months and never once ran here. A number every machine agrees on is worth
    more than a more precise one that silently varies, because this figure is a
    budgeting hint an agent reads before opening a module -- not a contract.

    @param text the passage to measure
    @return the count, by `CHARACTERS_PER_TOKEN`, identical on every machine
    """
    # Apply the repository-wide deterministic character ratio without optional tokenizers.
    return round(len(text) / CHARACTERS_PER_TOKEN)


def budget_for(doc: Document) -> int:
    """The token ceiling a document must stay under, by filename.

    ``KERNEL.md`` is held tighter than the rest because every agent reads it and
    nothing routes without it.

    @param doc the document whose ceiling is wanted
    @return the ceiling in tokens, falling back to the general module limit
    """
    # Select a named special ceiling or fall back to the general module budget.
    return TOKEN_BUDGETS.get(doc.path.stem, TOKEN_BUDGETS["*"])
