"""Generate `discipline/meta/PROVENANCE.md` from the source-section census.

    python tools/build_provenance.py

Reads `tools/extraction.yaml` (written by `extract_sources.py`) and maps every
historical heading plus every normative claim in the v5 input to a reviewed
disposition and named target.

The point is that nothing leaves the corpus silently. A section with no entry
below is reported as UNREVIEWED, and the count is printed -- the same treatment
`ENFORCEMENT.md` gives an unbuilt mechanism.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

from discipline_core import count_tokens

if TYPE_CHECKING:
    from collections.abc import Sequence

## Derived from this file's location so the script works from any directory.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Where each source document's material went, at document granularity.
## Section-level exceptions are listed in DISPOSITIONS below.
DEFAULT_TARGETS: Final[dict[str, tuple[str, ...]]] = {
    "SG": (),  # fully superseded; see SUPERSEDED
    "SE": ("law/ARCH", "law/TYPE", "law/ERR", "law/EFCT", "law/API", "law/DEP", "law/FLOW"),
    "TD": ("law/TEST",),
    "CA": ("ops/ALLOC",),
    "AR": ("frame/architecture",),
    "ET": ("law/ERR", "law/DIAG", "fact/py-errors"),
    "LO": ("law/DIAG", "fact/py-logging"),
    "TY": ("law/TYPE", "fact/py-typing"),
    "TT": ("law/TEST", "fact/py-testing"),
    "SP": ("frame/spec", "law/FLOW"),
    "AT": ("ops/teams",),
    "CD": ("law/DOC", "law/DOC-NARRATION", "law/DOC-NAMING"),
}

## The path each two-letter census code stands for, shown so a reader of the
## ledger never has to decode the abbreviations.
SOURCE_NAMES: Final[dict[str, str]] = {
    "SG": "Software Engineering Style Guidelines.md",
    "SE": "doctrine/SOFTWARE-ENGINEERING.md",
    "TD": "doctrine/TESTING.md",
    "CA": "doctrine/CHEAPEST-ABLE.md",
    "AR": "manifests/architecture_manifest_default.md",
    "ET": "manifests/error_tracing_contract_manifest.md",
    "LO": "manifests/logging_observability_manifest.md",
    "TY": "manifests/python_typing_contract_manifest.md",
    "TT": "manifests/python_testing_tooling_manifest.md",
    "SP": "manifests/software_spec_discipline_manifest.md",
    "AT": "manifests/claude_code_agent_teams_manifest.md",
    "CD": "roadmap input/python-commenting-and-documentation-discipline.md",
}

## The copied source is evidence, not an editable working draft. This digest is
## checked before any disposition output is accepted.
COMMENTING_SOURCE: Final = (
    REPO_ROOT
    / "roadmap"
    / "from-4.1-to-5.0"
    / "inputs"
    / "python-commenting-and-documentation-discipline.md"
)
COMMENTING_SHA256: Final = "23509318ef92d79240a931539eba0c57b4367f345f06c74ad99225bbd989fa72"
COMMENTING_CLAIM_COUNT: Final = 365
COMMENTING_LEDGER: Final = (
    REPO_ROOT / "roadmap" / "from-4.1-to-5.0" / "evidence" / "commenting-claim-dispositions.json"
)
CLAIM_DISPOSITIONS: Final = frozenset({
    "retained",
    "strengthened",
    "split",
    "superseded",
    "rejected-with-reason",
})
_SECTION_NUMBER: Final = re.compile(r"^(?P<major>\d+)(?:\.|\s)")
_TOKENS_LINE: Final = re.compile(r"^tokens:\s*\d+\s*$", re.MULTILINE)

## Section-level exceptions, matched as a case-insensitive substring of the
## heading. Each carries the disposition and the reason.
DISPOSITIONS: Final[tuple[tuple[str, str, str, str], ...]] = (
    # source, heading substring, disposition, note
    (
        "SG",
        "",
        "superseded",
        (
            "Every section is re-covered by doctrine/SOFTWARE-ENGINEERING.md, which names the "
            "supersession itself. Mined for the handful of items the doctrine dropped."
        ),
    ),
    (
        "SE",
        "compiled core",
        "dropped",
        (
            "Resolved as CONFLICTS C1: Python is the premise, not a departure. The underlying "
            "concerns survive as the motivation for strict typing and mutation testing."
        ),
    ),
    (
        "SE",
        "the python core",
        "dropped",
        "Same resolution; the tension section is not carried forward as an apology.",
    ),
    ("SE", "revision log", "dropped", "Superseded by version control."),
    ("TD", "revision log", "dropped", "Superseded by version control."),
    ("CA", "revision log", "dropped", "Superseded by version control."),
    ("SE", "summary", "dropped", "Replaced by discipline/KERNEL.md."),
    ("TD", "one sentence that explains", "migrated", "Opens law/TEST."),
    (
        "SE",
        "how this doctrine is enforced",
        "migrated",
        "Generalized into enforce/ENFORCEMENT.md, now generated from the rules.",
    ),
    (
        "SE",
        "architecture decision record template",
        "migrated",
        "Obligations kept as FLOW-003..005; the template itself belongs to a project.",
    ),
    ("AT", "", "migrated", "Whole document becomes ops/teams, decaying in months."),
    ("TT", "sources", "migrated", "Citations kept in fact/py-testing."),
    ("TY", "sources", "migrated", "Citations kept in fact/py-typing."),
    ("ET", "sources", "migrated", "Citations kept in fact/py-errors."),
    ("LO", "sources", "migrated", "Citations kept in fact/py-logging."),
    ("AT", "sources", "migrated", "Citations kept in ops/teams."),
)


@dataclass(frozen=True, slots=True)
class Row:
    """One heading of one source document, and the verdict on its material.

    Every censused heading yields exactly one of these, including the ones
    nobody has ruled on; that is what keeps an omission visible.
    """

    ## Two-letter code of the owning document, as the census writes it.
    source: str
    ## The heading text, verbatim from the source.
    heading: str
    ## Line the heading sits on in its source document.
    line: int
    ## `migrated`, `superseded`, `dropped`, or `UNREVIEWED` when nothing on
    ## record says where the material went.
    disposition: str
    ## Modules the material landed in; empty unless it was migrated.
    targets: tuple[str, ...]
    ## Why this heading was ruled the way it was; empty when no DISPOSITIONS
    ## entry matched it and the document's default applied unmodified.
    note: str


@dataclass(frozen=True, slots=True)
class ClaimPolicy:
    """Authored disposition for every claim under one numbered source section."""

    ## Major source-section number; subheadings inherit it.
    section: int
    ## One value from `CLAIM_DISPOSITIONS`.
    disposition: str
    ## Target doctrine modules that carry the proposition after integration.
    targets: tuple[str, ...]
    ## Review judgment explaining the disposition, never an empty placeholder.
    reason: str


@dataclass(frozen=True, slots=True)
class ClaimRow:
    """One extracted source claim with exactly one reviewed disposition."""

    ## Stable source identity written by `extract_sources.py`.
    claim_id: str
    ## Nearest source heading and 1-based line for human verification.
    section: str
    ## Owning numbered level-two section when the nearest heading is an example.
    major_section: str
    line: int
    ## Mechanical signal by which extraction identified the claim.
    kind: str
    ## Normalized source text; evidence, not rewritten target doctrine.
    text: str
    ## Reviewed treatment of this exact claim.
    disposition: str
    ## Doctrine modules that receive or resolve the claim.
    targets: tuple[str, ...]
    ## Why this treatment was chosen.
    reason: str


class ProvenanceError(ValueError):
    """The frozen source and its reviewed disposition model disagree."""


## A section is the review unit only for assigning judgment; the generated
## ledger expands these policies to all 365 individual claims. Exact section
## keys (rather than catch-all ranges) make additions fail closed.
COMMENTING_POLICIES: Final[tuple[ClaimPolicy, ...]] = (
    ClaimPolicy(
        1,
        "retained",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Retain evident source as the purpose shared by structured contracts and "
            "procedural narration."
        ),
    ),
    ClaimPolicy(
        2,
        "split",
        ("law/DOC", "fact/doxygen"),
        (
            "Keep Doxygen ownership as law; move the exact qualified version and observed "
            "capabilities to dated fact."
        ),
    ),
    ClaimPolicy(
        3,
        "split",
        ("law/DOC", "law/DOC-NARRATION", "law/DOC-NAMING"),
        (
            "Preserve the axioms while allocating entity meaning, execution explanation, "
            "and identifier meaning to distinct laws."
        ),
    ),
    ClaimPolicy(
        4,
        "split",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Retain the two information layers and give each a single, mechanically "
            "distinguishable comment form."
        ),
    ),
    ClaimPolicy(
        5,
        "strengthened",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Turn the allocation preference into an exclusive ownership rule with "
            "detectable duplicate and misplaced forms."
        ),
    ),
    ClaimPolicy(
        6,
        "strengthened",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Broaden existing entity coverage to all governed bindings and semantic steps "
            "with explicit association rules."
        ),
    ),
    ClaimPolicy(
        7,
        "strengthened",
        ("law/DOC",),
        (
            "Retain semantic contract content and enumerate the properties that can be "
            "checked without claiming semantic truth."
        ),
    ),
    ClaimPolicy(
        8,
        "strengthened",
        ("law/DOC-NAMING",),
        (
            "Make naming obligations project-owned structured data so domain vocabulary "
            "is enforceable without being universalized."
        ),
    ),
    ClaimPolicy(
        9,
        "retained",
        ("law/DOC-NAMING", "frame/documentation"),
        (
            "Retain domain ownership of naming conventions and explain why the discipline "
            "supplies schema rather than vocabulary."
        ),
    ),
    ClaimPolicy(
        10,
        "strengthened",
        ("law/DOC-NARRATION", "frame/documentation"),
        (
            "Define quasi-literate narration through a stable comment-to-AST association "
            "grammar instead of prose examples alone."
        ),
    ),
    ClaimPolicy(
        11,
        "retained",
        ("law/DOC-NARRATION",),
        "Retain narration of governed branches, loops, exits, handlers, and state transitions.",
    ),
    ClaimPolicy(
        12,
        "retained",
        ("law/DOC-NARRATION",),
        (
            "Retain narration of data movement, intermediate representations, "
            "transformations, and ordering."
        ),
    ),
    ClaimPolicy(
        13,
        "strengthened",
        ("law/DOC-NARRATION",),
        (
            "Define one coherent semantic step as the granularity and reject both distant "
            "blanket prose and per-token noise."
        ),
    ),
    ClaimPolicy(
        14,
        "retained",
        ("law/DOC-NARRATION",),
        (
            "Retain semantic restatement while explicitly rejecting syntactic paraphrase "
            "as a qualifying owner."
        ),
    ),
    ClaimPolicy(
        15,
        "retained",
        ("law/DOC-NARRATION",),
        (
            "Retain documentation for obvious syntax because the required information is "
            "semantic role, not code translation."
        ),
    ),
    ClaimPolicy(
        16,
        "retained",
        ("law/DOC-NARRATION",),
        (
            "Retain local rationale where the code cannot expose constraints or "
            "non-obvious language behavior."
        ),
    ),
    ClaimPolicy(
        17,
        "strengthened",
        ("law/DOC-NARRATION",),
        (
            "Reject obsolete history and route durable rationale to current contracts or "
            "decision records."
        ),
    ),
    ClaimPolicy(
        18,
        "split",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Attach stable units, ranges, and representations to entities and temporary "
            "conversions to their semantic steps."
        ),
    ),
    ClaimPolicy(
        19,
        "split",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Require both boolean states at the owning entity and narrate only local state "
            "interpretation or transition."
        ),
    ),
    ClaimPolicy(
        20,
        "split",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Define collection element, ordering, uniqueness, and mutability at the "
            "entity; narrate temporary collection transformations."
        ),
    ),
    ClaimPolicy(
        21,
        "strengthened",
        ("law/DOC", "law/API", "law/ERR", "law/EFCT"),
        (
            "Cross-reference callable contract, error, and effect laws while adding "
            "mechanically checkable documentation fields."
        ),
    ),
    ClaimPolicy(
        22,
        "retained",
        ("law/DOC", "law/EFCT"),
        "Retain explicit purity claims and let the effect law own behavioral correctness.",
    ),
    ClaimPolicy(
        23,
        "split",
        ("law/DOC", "law/EFCT", "law/DIAG"),
        (
            "Document observable effects and failure behavior without duplicating their "
            "execution and diagnostic requirements."
        ),
    ),
    ClaimPolicy(
        24,
        "split",
        ("law/DOC", "law/DOC-NARRATION", "law/TYPE"),
        (
            "Place stable invariants on entities, local assumptions on steps, and keep "
            "type-enforceable constraints in TYPE."
        ),
    ),
    ClaimPolicy(
        25,
        "retained",
        ("law/DOC-NARRATION",),
        (
            "Retain explanations of non-obvious evaluation, aliasing, mutability, "
            "exception, and resource semantics."
        ),
    ),
    ClaimPolicy(
        26,
        "retained",
        ("law/DOC-NARRATION",),
        (
            "Retain algorithm purpose, progression, termination, complexity, and "
            "rejected-alternative narration where applicable."
        ),
    ),
    ClaimPolicy(
        27,
        "split",
        ("law/DOC", "law/DOC-NARRATION", "law/API", "law/DEP"),
        (
            "Allocate stable boundary contracts to entities and boundary translation or "
            "sequencing to implementation narration."
        ),
    ),
    ClaimPolicy(
        28,
        "strengthened",
        ("law/DOC", "law/DOC-NARRATION"),
        (
            "Mechanize detectable drift and bind semantic synchronization to "
            "content-addressed adversarial review."
        ),
    ),
    ClaimPolicy(
        29,
        "strengthened",
        ("law/DOC", "law/DOC-NARRATION", "law/DOC-NAMING"),
        (
            "Convert the review questions into content-bound challenges with explicit "
            "outcomes and residual judgment."
        ),
    ),
    ClaimPolicy(
        30,
        "split",
        ("law/DOC", "law/DOC-NARRATION", "law/DOC-NAMING"),
        (
            "Preserve each anti-pattern under the law that owns its entity, narration, or "
            "vocabulary failure."
        ),
    ),
    ClaimPolicy(
        31,
        "retained",
        ("frame/documentation", "law/DOC", "law/DOC-NARRATION"),
        (
            "Retain structural and procedural reading as complementary acceptance views "
            "rather than parallel documentation systems."
        ),
    ),
    ClaimPolicy(
        32,
        "retained",
        ("law/DOC", "law/DOC-NARRATION"),
        "Retain the allocation table as a compact consequence of the two ownership laws.",
    ),
    ClaimPolicy(
        33,
        "split",
        ("law/DOC", "law/DOC-NARRATION", "law/DOC-NAMING"),
        (
            "Resolve the governing summary through the three target laws without creating "
            "a fourth source of rules."
        ),
    ),
)


def disposition_for(source: str, heading: str) -> tuple[str, str] | None:
    """The most specific matching disposition, or None.

    Specificity is the length of the matched substring, so a document-wide entry
    (an empty needle) never shadows a section-level one.

    @param source the two-letter code of the document the heading came from
    @param heading the heading to rule on
    @return the disposition and its reason, or None when no entry matches
    """
    best: tuple[str, str] | None = None
    best_len = -1
    for src, needle, disposition, note in DISPOSITIONS:
        if src != source:
            continue
        if needle and needle.lower() not in heading.lower():
            continue
        if len(needle) > best_len:
            best, best_len = (disposition, note), len(needle)
    return best


def build_rows(sections: Sequence[dict[str, object]]) -> list[Row]:
    """Rule on every censused section, refusing to assume the undecided ones.

    A section with no matching exception inherits its document's default
    targets. When the document has none either, nothing has actually decided
    where the material went, so it is marked UNREVIEWED rather than counted as
    migrated -- an unbacked claim of survival is what this ledger exists to
    prevent.

    @param sections census entries, each carrying a source, a heading and a line
    @return one row per section, in census order
    @throws KeyError when a census entry is missing one of those three fields
    """
    rows: list[Row] = []
    for section in sections:
        source = str(section["source"])
        heading = str(section["heading"])
        found = disposition_for(source, heading)
        if found is None:
            disposition, note = "migrated", ""
        else:
            disposition, note = found
        targets = DEFAULT_TARGETS.get(source, ()) if disposition == "migrated" else ()
        if disposition == "migrated" and not targets:
            disposition = "UNREVIEWED"
        rows.append(Row(source, heading, int(section["line"]), disposition, targets, note))
    return rows


def verify_commenting_source(path: Path = COMMENTING_SOURCE) -> str:
    """Prove the reviewed input is still the byte-identical frozen copy.

    @param path source path, injectable for a destructive test
    @return the verified lowercase SHA-256 digest
    @throws ValueError when the source is absent or has changed
    """
    if not path.is_file():
        msg = f"commenting doctrine input is missing: {path}"
        raise ProvenanceError(msg)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != COMMENTING_SHA256:
        msg = (
            "commenting doctrine input changed: "
            f"expected {COMMENTING_SHA256}, observed {digest}; restore the frozen input"
        )
        raise ProvenanceError(msg)
    return digest


def _major_section(heading: str) -> int:
    """Read the major number inherited by a claim from its nearest heading.

    @param heading source heading such as `3.2 Documentation comments...`
    @return the major section number
    @throws ValueError when the claim is outside the numbered doctrine
    """
    found = _SECTION_NUMBER.match(heading)
    if found is None:
        msg = f"commenting claim has no numbered owner section: {heading!r}"
        raise ProvenanceError(msg)
    return int(found.group("major"))


def build_claim_rows(
    candidates: Sequence[dict[str, object]],
    policies: Sequence[ClaimPolicy] = COMMENTING_POLICIES,
) -> list[ClaimRow]:
    """Expand authored policies into exactly one disposition per source claim.

    The function deliberately accepts a policy sequence instead of indexing it
    first. That makes duplicate policies observable as multiple claims on the
    same item instead of allowing a dictionary overwrite to hide the error.

    @param candidates mechanically extracted candidate statements
    @param policies reviewed section policies to apply
    @return exact claim-level disposition rows in source order
    @throws ValueError on an unreviewed, multiply claimed, duplicate, or altered item
    """
    rows: list[ClaimRow] = []
    seen: set[str] = set()
    for candidate in candidates:
        if str(candidate.get("source", "")) != "CD":
            continue
        section = str(candidate["section"])
        major_section = str(candidate["major_section"])
        matching = [
            policy for policy in policies if policy.section == _major_section(major_section)
        ]
        claim_id = str(candidate["claim_id"])
        if len(matching) != 1:
            state = "unreviewed" if not matching else "multiply claimed"
            msg = f"{claim_id} is {state}: matched {len(matching)} policies"
            raise ProvenanceError(msg)
        if claim_id in seen:
            msg = f"duplicate extracted claim identity: {claim_id}"
            raise ProvenanceError(msg)
        seen.add(claim_id)

        line = int(candidate["line"])
        text = str(candidate["text"])
        expected_id = f"CD-L{line:04d}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"
        if claim_id != expected_id:
            msg = f"altered claim identity {claim_id}: source line and text derive {expected_id}"
            raise ProvenanceError(msg)

        policy = matching[0]
        if policy.disposition not in CLAIM_DISPOSITIONS:
            msg = f"{claim_id} has unknown disposition {policy.disposition!r}"
            raise ProvenanceError(msg)
        if not policy.reason.strip():
            msg = f"{claim_id} has no disposition reason"
            raise ProvenanceError(msg)
        if policy.disposition != "rejected-with-reason" and not policy.targets:
            msg = f"{claim_id} has no target for {policy.disposition}"
            raise ProvenanceError(msg)
        rows.append(
            ClaimRow(
                claim_id=claim_id,
                section=section,
                major_section=major_section,
                line=line,
                kind=str(candidate["kind"]),
                text=text,
                disposition=policy.disposition,
                targets=policy.targets,
                reason=policy.reason,
            )
        )
    return rows


def render_claim_ledger(rows: Sequence[ClaimRow], source_digest: str) -> str:
    """Render the complete machine-readable claim disposition evidence.

    @param rows all reviewed commenting-doctrine claims
    @param source_digest verified digest of the frozen source
    @return deterministic, newline-terminated JSON
    """
    counts = Counter(row.disposition for row in rows)
    payload = {
        "schema_version": 1,
        "generated_by": "tools/build_provenance.py",
        "source": COMMENTING_SOURCE.relative_to(REPO_ROOT).as_posix(),
        "source_sha256": source_digest,
        "claim_count": len(rows),
        "unreviewed_count": 0,
        "multiply_claimed_count": 0,
        "disposition_counts": dict(sorted(counts.items())),
        "claims": [
            {
                "claim_id": row.claim_id,
                "section": row.section,
                "major_section": row.major_section,
                "line": row.line,
                "kind": row.kind,
                "text": row.text,
                "disposition": row.disposition,
                "targets": list(row.targets),
                "reason": row.reason,
            }
            for row in rows
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _with_current_token_count(text: str) -> str:
    """Converge a generated corpus module's self-referential token count.

    @param text rendered Markdown containing one `tokens:` field
    @return the same text with the stable measured value
    """
    updated = text
    for _ in range(4):
        candidate = _TOKENS_LINE.sub(f"tokens: {count_tokens(updated)}", updated, count=1)
        if candidate == updated:
            break
        updated = candidate
    return updated


def render(rows: Sequence[Row], claims: Sequence[ClaimRow] = ()) -> str:
    """The whole of PROVENANCE.md: front matter, tallies, exceptions, gaps.

    The exceptions table holds only headings matched by a *named* section in
    DISPOSITIONS; a document-wide entry is that document's default, not an
    exception to it, so it never appears there. Among what remains, each
    distinct reason is printed once per document rather than once per heading.
    The unreviewed section is emitted only when something is unreviewed.

    @param rows every section, already ruled on
    @param claims exact reviewed claims from the commenting doctrine
    @return the file's complete text, newline-terminated
    """
    counts = Counter(r.disposition for r in rows)
    by_source: defaultdict[str, list[Row]] = defaultdict(list)
    for row in rows:
        by_source[row.source].append(row)

    lines = [
        "---",
        "id: meta/PROVENANCE",
        "kind: meta",
        "title: Source Provenance",
        "tokens: 0",
        'load_when: ["where did this come from", "was anything lost", "source document"]',
        "decay: none",
        "---",
        "",
        (
            "<!-- GENERATED by tools/build_provenance.py -- do not edit; "
            "change DISPOSITIONS in that script and rebuild. -->"
        ),
        "",
        "# Source Provenance",
        "",
        (
            f"Every heading in the {len(by_source)} source documents "
            f"({len(rows)} sections) and where it went. Nothing leaves the corpus silently: "
            "a section with no recorded disposition is reported as `UNREVIEWED` here and by "
            "the build, rather than quietly omitted."
        ),
        "",
        (
            "**Resolution.** The eleven historical inputs retain the section-level "
            "census used for their original migration. The v5 commenting input is held to "
            "claim-level provenance: every mechanically enumerated normative claim has "
            "exactly one reviewed disposition in the generated machine-readable ledger. "
            "A source change, missing policy, duplicate policy, duplicate identity, or stale "
            "generated view fails the build."
        ),
        "",
        "| Disposition | Sections |",
        "|---|---|",
    ]
    for disposition, count in sorted(counts.items()):
        lines.append(f"| {disposition} | {count} |")
    lines.append("")

    if claims:
        claim_counts = Counter(row.disposition for row in claims)
        lines += [
            "## v5 claim-level disposition",
            "",
            (
                f"The frozen `CD` input contains **{len(claims)}** enumerated normative claims. "
                "Zero are unreviewed and zero are multiply claimed. The complete records, "
                "including source line, text, target modules, reason, and pinned source hash, "
                "are committed in "
                "`roadmap/from-4.1-to-5.0/evidence/commenting-claim-dispositions.json`."
            ),
            "",
            "| Disposition | Claims |",
            "|---|---|",
        ]
        lines += [
            f"| {disposition} | {count} |" for disposition, count in sorted(claim_counts.items())
        ]
        lines.append("")

    lines += ["## By source document", "", "| Source | Sections | Goes to |", "|---|---|---|"]
    for source in sorted(by_source):
        targets = DEFAULT_TARGETS.get(source, ())
        where = ", ".join(f"`{t}`" for t in targets) or "*superseded*"
        lines.append(
            f"| `{source}` {SOURCE_NAMES.get(source, '')} | {len(by_source[source])} | {where} |"
        )
    lines.append("")

    lines += [
        "## Named exceptions",
        "",
        "Sections whose disposition differs from their document's default.",
        "",
        "| Source | Section | Disposition | Reason |",
        "|---|---|---|---|",
    ]
    seen: set[tuple[str, str]] = set()
    for row in rows:
        if not row.note or (row.source, row.note) in seen:
            continue
        if disposition_for(row.source, row.heading) is None:
            continue
        needle_specific = any(
            n and n.lower() in row.heading.lower() for s, n, _, _ in DISPOSITIONS if s == row.source
        )
        if not needle_specific:
            continue
        seen.add((row.source, row.note))
        lines.append(
            f"| `{row.source}` | {_escape(row.heading)} | {row.disposition} | {row.note} |"
        )
    lines.append("")

    unreviewed = [r for r in rows if r.disposition == "UNREVIEWED"]
    if unreviewed:
        lines += [
            "## Unreviewed",
            "",
            "These have no recorded disposition. Each is a gap, not an omission.",
            "",
            "| Source | Line | Section |",
            "|---|---|---|",
        ]
        lines += [f"| `{r.source}` | {r.line} | {_escape(r.heading)} |" for r in unreviewed]
        lines.append("")

    lines += [
        "## Dropped material, in full",
        "",
        (
            "The corpus carried roughly 130 references to documents that do not exist in it, "
            "73 of them to a single PROPOSAL.md. All are severed. Where a reference carried "
            "information, the information is inlined and the pointer dropped: the recorded "
            "incident in which a cleanup routine destroyed 8,023 files while reporting success "
            "is kept as the justification for `EFCT-005`, because the rule is not persuasive "
            "without it. Where a reference was bookkeeping, it is deleted. "
            "`tools/validate.py` rejects any new one as `V041`."
        ),
        "",
        (
            "Project-specific material — package paths, a document renderer, bilingual "
            "catalogs, one filesystem's atomicity guarantees — is genericized rather than "
            "carried. The rules that depended on it are stated against a neutral layer "
            "layout; the worked artifacts worth keeping belong in `discipline/examples/`."
        ),
    ]
    return _with_current_token_count("\n".join(lines).rstrip() + "\n")


def _escape(text: str) -> str:
    """Make a heading safe to drop into a Markdown table cell.

    @param text arbitrary heading text
    @return the same text with any pipe backslash-escaped
    """
    return re.sub(r"\|", r"\\|", text)


def _build_outputs(
    extraction: Path,
) -> tuple[list[Row], list[ClaimRow], str, str]:
    """Load, validate, and render both provenance projections.

    @param extraction committed mechanical source census
    @return section rows, claim rows, Markdown view, and JSON ledger
    @throws ProvenanceError when the reviewed claim count no longer matches
    """
    source_digest = verify_commenting_source()
    payload = yaml.safe_load(extraction.read_text(encoding="utf-8"))
    rows = build_rows(payload.get("sections", []))
    claims = build_claim_rows(payload.get("candidates", []))
    if len(claims) != COMMENTING_CLAIM_COUNT:
        msg = (
            "commenting doctrine claim census changed: "
            f"expected {COMMENTING_CLAIM_COUNT}, observed {len(claims)}; "
            "review the extractor and every added or removed claim"
        )
        raise ProvenanceError(msg)
    return rows, claims, render(rows, claims), render_claim_ledger(claims, source_digest)


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the provenance ledger from the extraction census.

    Prints the tally per disposition, so an UNREVIEWED count is visible in the
    build output and not only inside the file just written.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 once the ledger is written, or 1 when the census file is absent
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Generate the provenance ledger.")
    parser.add_argument("--extraction", type=Path, default=REPO_ROOT / "tools" / "extraction.yaml")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "discipline" / "meta" / "PROVENANCE.md"
    )
    parser.add_argument("--claim-out", type=Path, default=COMMENTING_LEDGER)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare both committed outputs with a fresh build without writing",
    )
    args = parser.parse_args(argv)

    if not args.extraction.exists():
        print(f"missing {args.extraction}; run tools/extract_sources.py first", file=sys.stderr)
        return 1

    try:
        rows, claims, provenance, claim_ledger = _build_outputs(args.extraction)
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"provenance build failed: {exc}", file=sys.stderr)
        return 1

    outputs = ((args.out, provenance), (args.claim_out, claim_ledger))
    if args.check:
        drifted = [
            path
            for path, expected in outputs
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        ]
        if drifted:
            for path in drifted:
                print(f"DRIFT: {path}", file=sys.stderr)
            return 1
    else:
        for path, content in outputs:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")

    counts = Counter(r.disposition for r in rows)
    action = "checked" if args.check else "wrote"
    print(f"{action} {args.out.relative_to(REPO_ROOT).as_posix()}: {len(rows)} sections")
    for disposition, count in sorted(counts.items()):
        print(f"  {disposition}: {count}")
    claim_counts = Counter(row.disposition for row in claims)
    print(
        f"{action} {args.claim_out.relative_to(REPO_ROOT).as_posix()}: "
        f"{len(claims)} claims, 0 unreviewed, 0 multiply claimed"
    )
    for disposition, count in sorted(claim_counts.items()):
        print(f"  {disposition}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
