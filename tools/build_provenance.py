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

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

## Derived from this file's location so the script works from any directory.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Where each source document's material went, at document granularity.
## Section-level exceptions are listed in DISPOSITIONS below.
## Treat DEFAULT TARGETS as mapping elements whose keys identify fields and values carry their
## content; key order is deliberately unused.
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
## Treat SOURCE NAMES as mapping elements whose keys identify fields and values carry their
## content; key order is deliberately unused.
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
## Frozen SHA-256 of the imported commenting-doctrine bytes reviewed by this migration.
COMMENTING_SHA256: Final = "23509318ef92d79240a931539eba0c57b4367f345f06c74ad99225bbd989fa72"
## Exact extracted-claim cardinality required before dispositions may be published.
COMMENTING_CLAIM_COUNT: Final = 365
## Project path of the content-bound disposition ledger for every imported doctrine claim.
COMMENTING_LEDGER: Final = (
    REPO_ROOT / "roadmap" / "from-4.1-to-5.0" / "evidence" / "commenting-claim-dispositions.json"
)
## Allowed claim-disposition strings; membership matters and set order is deliberately
## unordered.
CLAIM_DISPOSITIONS: Final = frozenset({
    "retained",
    "strengthened",
    "split",
    "superseded",
    "rejected-with-reason",
})
## Prefix grammar capturing a provenance heading's leading major section number.
_SECTION_NUMBER: Final = re.compile(r"^(?P<major>\d+)(?:\.|\s)")
## Multiline grammar locating the authored front-matter token-count field.
_TOKENS_LINE: Final = re.compile(r"^tokens:\s*\d+\s*$", re.MULTILINE)

## Section-level exceptions, matched as a case-insensitive substring of the
## heading. Each carries the disposition and the reason.
## Each element is a `(source tag, heading substring, disposition, reason)` exception tuple;
## declaration order is preserved for first-match resolution.
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
    ## Each targets element represents one governed path; traversal order is preserved.
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
    ## Each targets element represents one governed path; traversal order is preserved.
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
    ## Source line number identifying the claim's authored location.
    line: int
    ## Mechanical signal by which extraction identified the claim.
    kind: str
    ## Normalized source text; evidence, not rewritten target doctrine.
    text: str
    ## Reviewed treatment of this exact claim.
    disposition: str
    ## Doctrine modules that receive or resolve the claim.
    ## Each targets element represents one governed path; traversal order is preserved.
    targets: tuple[str, ...]
    ## Why this treatment was chosen.
    reason: str


class ProvenanceError(ValueError):
    """The frozen source and its reviewed disposition model disagree."""


## A section is the review unit only for assigning judgment; the generated
## ledger expands these policies to all 365 individual claims. Exact section
## keys (rather than catch-all ranges) make additions fail closed.
## Each element is one exact major-section disposition policy; section-number order is preserved
## and used for deterministic ledger expansion.
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
    # Compute best using None for later disposition for logic.
    best: tuple[str, str] | None = None
    # Compute best len using -1 for later disposition for logic.
    best_len = -1
    # Preserve the optional baseline note while re-recording selected entries.
    # Process each candidate element in deterministic source order.
    for src, needle, disposition, note in DISPOSITIONS:
        # Select the guarded path only after `src != source` is satisfied.
        if src != source:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `needle and needle.lower() not in heading.lower()`
        # Details: is satisfied.
        if needle and needle.lower() not in heading.lower():
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `len(needle) > best_len` is satisfied.
        if len(needle) > best_len:
            # Replace the winning `(disposition, reason)` tuple and its matched-length scalar
            # together; tuple element order is fixed and longer heading matches take precedence.
            best, best_len = (disposition, note), len(needle)
    # Return the disposition and its reason, or None when no entry matches to the caller.
    return best


def build_rows(sections: Sequence[dict[str, object]]) -> list[Row]:
    """Rule on every censused section, refusing to assume the undecided ones.

    A section with no matching exception inherits its document's default
    targets. When the document has none either, nothing has actually decided
    where the material went, so it is marked UNREVIEWED rather than counted as
    migrated -- an unbacked claim of survival is what this ledger exists to
    prevent.

    @param sections census entries, each carrying a source, a heading and a line
        Treat sections as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return one row per section, in census order
    @throws KeyError when a census entry is missing one of those three fields
    """
    # Each rows element represents one decoded record; lexical order is preserved.
    rows: list[Row] = []
    # Select section as the current element from sections while build rows preserves traversal
    # Details: order.
    # Process each candidate element in deterministic source order.
    for section in sections:
        # Retain the immutable source representation consumed by subsequent analysis.
        source = str(section["source"])
        # Compute heading using str for later build rows logic.
        heading = str(section["heading"])
        # Preserve the optional pattern match that carries the reported analysis count.
        found = disposition_for(source, heading)
        # Use the absence path when found has no available value.
        if found is None:
            # Use the default `(migrated disposition, empty reason)` tuple in that element order
            # when no section exception matched.
            disposition, note = "migrated", ""
        else:
            # Preserve the optional baseline note while re-recording selected entries.
            disposition, note = found
        # Preserve governed Python-path elements in deterministic traversal order.
        targets = DEFAULT_TARGETS.get(source, ()) if disposition == "migrated" else ()
        # Select the guarded path only after `disposition == 'migrated' and (not targets)` is
        # Details: satisfied.
        if disposition == "migrated" and not targets:
            # Compute disposition using "UNREVIEWED" for later build rows logic.
            disposition = "UNREVIEWED"
        rows.append(Row(source, heading, int(section["line"]), disposition, targets, note))
    # Return one row per section, in census order to the caller.
    return rows


def verify_commenting_source(path: Path = COMMENTING_SOURCE) -> str:
    """Prove the reviewed input is still the byte-identical frozen copy.

    @param path source path, injectable for a destructive test
    @return the verified lowercase SHA-256 digest
    @throws ValueError when the source is absent or has changed
    """
    # Select the regular-file path only when `not path.is_file()` is satisfied.
    if not path.is_file():
        # Derive msg from f"commenting doctrine input is missing: {path}" for the next verify
        # Details: commenting source decision.
        msg = f"commenting doctrine input is missing: {path}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ProvenanceError(msg)
    # Compute digest using hashlib.sha256 for later verify commenting source logic.
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    # Select the guarded path only after `digest != COMMENTING_SHA256` is satisfied.
    if digest != COMMENTING_SHA256:
        # Compute msg using ( for later verify commenting source logic.
        msg = (
            "commenting doctrine input changed: "
            f"expected {COMMENTING_SHA256}, observed {digest}; restore the frozen input"
        )
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ProvenanceError(msg)
    # Return the verified lowercase SHA-256 digest to the caller.
    return digest


def _major_section(heading: str) -> int:
    """Read the major number inherited by a claim from its nearest heading.

    @param heading source heading such as `3.2 Documentation comments...`
    @return the major section number
    @throws ValueError when the claim is outside the numbered doctrine
    """
    # Preserve the optional pattern match that carries the reported analysis count.
    found = _SECTION_NUMBER.match(heading)
    # Use the absence path when found has no available value.
    if found is None:
        # Derive msg from f"commenting claim has no numbered owner section: {heading!r for the
        # Details: next  major section decision.
        msg = f"commenting claim has no numbered owner section: {heading!r}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ProvenanceError(msg)
    # Return the major section number to the caller.
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
        Treat candidates as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param policies reviewed section policies to apply
        Each element is one major-section `ClaimPolicy`; section-number order is
        preserved.
    @return exact claim-level disposition rows in source order
    @throws ValueError on an unreviewed, multiply claimed, duplicate, or altered item
    """
    # Each rows element represents one decoded record; lexical order is preserved.
    rows: list[ClaimRow] = []
    # Collect unique seen element values; their order is deliberately unordered.
    seen: set[str] = set()
    # Treat the current candidate as the candidate element consumed by the enclosing
    # Details: transformation.
    # Process each candidate element in deterministic source order.
    for candidate in candidates:
        # Select the guarded path only after `str(candidate.get('source', '')) != 'CD'` is
        # Details: satisfied.
        if str(candidate.get("source", "")) != "CD":
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute section using str for later build claim rows logic.
        section = str(candidate["section"])
        # Compute major section using str for later build claim rows logic.
        major_section = str(candidate["major_section"])
        # Each matching element is one policy for this major section; authored policy order is
        # preserved so duplicate coverage remains diagnosable.
        matching = [
            policy for policy in policies if policy.section == _major_section(major_section)
        ]
        # Compute claim id using str for later build claim rows logic.
        claim_id = str(candidate["claim_id"])
        # Select the guarded path only after `len(matching) != 1` is satisfied.
        if len(matching) != 1:
            # Derive state from "unreviewed" if not matching else "multiply claimed" for the
            # Details: next build claim rows decision.
            state = "unreviewed" if not matching else "multiply claimed"
            # Derive msg from f"{claim_id} is {state}: matched {len(matching)} policies" for the
            # Details: next build claim rows decision.
            msg = f"{claim_id} is {state}: matched {len(matching)} policies"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ProvenanceError(msg)
        # Select the guarded path only after `claim_id in seen` is satisfied.
        if claim_id in seen:
            # Compute msg using f"duplicate extracted claim identity: {claim_id}" for later
            # Details: build claim rows logic.
            msg = f"duplicate extracted claim identity: {claim_id}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ProvenanceError(msg)
        seen.add(claim_id)

        # Preserve the current decoded diagnostic line before location normalization.
        line = int(candidate["line"])
        # Retain the immutable source representation consumed by subsequent analysis.
        text = str(candidate["text"])
        # Derive expected id from f"CD-L{line:04d}-{hashlib.sha256(text.encode('utf-8')).hexdi
        # Details: for the next build claim rows decision.
        expected_id = f"CD-L{line:04d}-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:12]}"
        # Select the guarded path only after `claim_id != expected_id` is satisfied.
        if claim_id != expected_id:
            # Derive msg from f"altered claim identity {claim_id}: source line and text de for
            # Details: the next build claim rows decision.
            msg = f"altered claim identity {claim_id}: source line and text derive {expected_id}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ProvenanceError(msg)

        # Compute policy using matching[0] for later build claim rows logic.
        policy = matching[0]
        # Select the guarded path only after `policy.disposition not in CLAIM_DISPOSITIONS` is
        # Details: satisfied.
        if policy.disposition not in CLAIM_DISPOSITIONS:
            # Derive msg from f"{claim_id} has unknown disposition {policy.disposition!r}" for
            # Details: the next build claim rows decision.
            msg = f"{claim_id} has unknown disposition {policy.disposition!r}"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ProvenanceError(msg)
        # Refuse baseline re-recording unless the caller supplies a nonblank audit reason.
        if not policy.reason.strip():
            # Derive msg from f"{claim_id} has no disposition reason" for the next build claim
            # Details: rows decision.
            msg = f"{claim_id} has no disposition reason"
            # Propagate the localized failure so callers cannot mistake it for success.
            raise ProvenanceError(msg)
        # Select the guarded path only after `policy.disposition != 'rejected-with-reason' and
        # Details: (not policy.targets)` is satisfied.
        if policy.disposition != "rejected-with-reason" and not policy.targets:
            # Compute msg using f"{claim_id} has no target for {policy.disposition}" for later
            # Details: build claim rows logic.
            msg = f"{claim_id} has no target for {policy.disposition}"
            # Propagate the localized failure so callers cannot mistake it for success.
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
    # Return exact claim-level disposition rows in source order to the caller.
    return rows


def render_claim_ledger(rows: Sequence[ClaimRow], source_digest: str) -> str:
    """Render the complete machine-readable claim disposition evidence.

    @param rows all reviewed commenting-doctrine claims
        Each rows element represents one decoded record; lexical order is preserved.
    @param source_digest verified digest of the frozen source
    @return deterministic, newline-terminated JSON
    """
    # Select counts, row as the current element from rows) while render claim ledger preserves
    # Details: traversal order.
    counts = Counter(row.disposition for row in rows)
    # Treat payload as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
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
    # Return deterministic, newline-terminated JSON to the caller.
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _with_current_token_count(text: str) -> str:
    """Converge a generated corpus module's self-referential token count.

    @param text rendered Markdown containing one `tokens:` field
    @return the same text with the stable measured value
    """
    # Compute updated using text for later with current token count logic.
    updated = text
    # Process each candidate element in deterministic source order.
    for _ in range(4):
        # Treat the current candidate as the candidate element consumed by the enclosing
        # Details: transformation.
        candidate = _TOKENS_LINE.sub(f"tokens: {count_tokens(updated)}", updated, count=1)
        # Select the guarded path only after `candidate == updated` is satisfied.
        if candidate == updated:
            # Stop the scan once the decisive match has been established.
            break
        # Compute updated using candidate for later with current token count logic.
        updated = candidate
    # Return the same text with the stable measured value to the caller.
    return updated


def render(rows: Sequence[Row], claims: Sequence[ClaimRow] = ()) -> str:
    """The whole of PROVENANCE.md: front matter, tallies, exceptions, gaps.

    The exceptions table holds only headings matched by a *named* section in
    DISPOSITIONS; a document-wide entry is that document's default, not an
    exception to it, so it never appears there. Among what remains, each
    distinct reason is printed once per document rather than once per heading.
    The unreviewed section is emitted only when something is unreviewed.

    @param rows every section, already ruled on
        Each rows element represents one decoded record; lexical order is preserved.
    @param claims exact reviewed claims from the commenting doctrine
        Each element is one claim-disposition record; source-line order is
        preserved within source precedence.
    @return the file's complete text, newline-terminated
    """
    # Select counts, r as the current element from rows) while render preserves traversal order.
    counts = Counter(r.disposition for r in rows)
    # Compute by source using defaultdict for later render logic.
    by_source: defaultdict[str, list[Row]] = defaultdict(list)
    # Select row as the current element from rows while render preserves traversal order.
    # Process each candidate element in deterministic source order.
    for row in rows:
        by_source[row.source].append(row)

    # Each lines element represents one decoded record; lexical order is preserved.
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
    # Preserve the observed item count used by the non-vacuity verdict.
    # Process each candidate element in deterministic source order.
    for disposition, count in sorted(counts.items()):
        lines.append(f"| {disposition} | {count} |")
    lines.append("")

    # Handle the non-empty or enabled claims state.
    if claims:
        # Select claim counts, row as the current element from claims) while render preserves
        # Details: traversal order.
        claim_counts = Counter(row.disposition for row in claims)
        # Preserve lines element values in deterministic source order.
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
        # Preserve lines, count, disposition element values in deterministic source order.
        lines += [
            f"| {disposition} | {count} |" for disposition, count in sorted(claim_counts.items())
        ]
        lines.append("")

    # Preserve lines element values in deterministic source order.
    lines += ["## By source document", "", "| Source | Sections | Goes to |", "|---|---|---|"]
    # Retain the immutable source representation consumed by subsequent analysis.
    # Process each candidate element in deterministic source order.
    for source in sorted(by_source):
        # Preserve governed Python-path elements in deterministic traversal order.
        targets = DEFAULT_TARGETS.get(source, ())
        # Select t, where as the current element from targets) or "*superseded*" while render
        # Details: preserves traversal order.
        where = ", ".join(f"`{t}`" for t in targets) or "*superseded*"
        lines.append(
            f"| `{source}` {SOURCE_NAMES.get(source, '')} | {len(by_source[source])} | {where} |"
        )
    lines.append("")

    # Preserve lines element values in deterministic source order.
    lines += [
        "## Named exceptions",
        "",
        "Sections whose disposition differs from their document's default.",
        "",
        "| Source | Section | Disposition | Reason |",
        "|---|---|---|---|",
    ]
    # Collect unique seen element values; their order is deliberately unordered.
    seen: set[tuple[str, str]] = set()
    # Select row as the current element from rows while render preserves traversal order.
    # Process each candidate element in deterministic source order.
    for row in rows:
        # Select the empty-or-disabled path when row.note or (row.source, row.note) in seen has
        # Details: no usable value.
        if not row.note or (row.source, row.note) in seen:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Use the absence path when disposition for(row.source, row.heading) has no available
        # Details: value.
        if disposition_for(row.source, row.heading) is None:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Preserve the observed item count used by the non-vacuity verdict.
        needle_specific = any(
            n and n.lower() in row.heading.lower() for s, n, _, _ in DISPOSITIONS if s == row.source
        )
        # Select the empty-or-disabled path when needle specific has no usable value.
        if not needle_specific:
            # Advance after the current candidate has been conclusively excluded.
            continue
        seen.add((row.source, row.note))
        lines.append(
            f"| `{row.source}` | {_escape(row.heading)} | {row.disposition} | {row.note} |"
        )
    lines.append("")

    # Each unreviewed element is one provenance row lacking a disposition; source row order is
    # preserved for the blocking report.
    unreviewed = [r for r in rows if r.disposition == "UNREVIEWED"]
    # Handle the non-empty or enabled unreviewed state.
    if unreviewed:
        # Preserve lines element values in deterministic source order.
        lines += [
            "## Unreviewed",
            "",
            "These have no recorded disposition. Each is a gap, not an omission.",
            "",
            "| Source | Line | Section |",
            "|---|---|---|",
        ]
        # Preserve lines, r element values in deterministic source order.
        lines += [f"| `{r.source}` | {r.line} | {_escape(r.heading)} |" for r in unreviewed]
        lines.append("")

    # Preserve lines element values in deterministic source order.
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
    # Return the file's complete text, newline-terminated to the caller.
    return _with_current_token_count("\n".join(lines).rstrip() + "\n")


def _escape(text: str) -> str:
    """Make a heading safe to drop into a Markdown table cell.

    @param text arbitrary heading text
    @return the same text with any pipe backslash-escaped
    """
    # Return the same text with any pipe backslash-escaped to the caller.
    return re.sub(r"\|", r"\\|", text)


def _build_outputs(
    extraction: Path,
) -> tuple[list[Row], list[ClaimRow], str, str]:
    """Load, validate, and render both provenance projections.

    @param extraction committed mechanical source census
    @return section rows, claim rows, Markdown view, and JSON ledger
    @throws ProvenanceError when the reviewed claim count no longer matches
    """
    # Compute source digest using verify commenting source for later build outputs logic.
    source_digest = verify_commenting_source()
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    payload = yaml.safe_load(extraction.read_text(encoding="utf-8"))
    # Preserve rows element values in deterministic source order.
    rows = build_rows(payload.get("sections", []))
    # Compute claims using build claim rows for later build outputs logic.
    claims = build_claim_rows(payload.get("candidates", []))
    # Select the guarded path only after `len(claims) != COMMENTING_CLAIM_COUNT` is satisfied.
    if len(claims) != COMMENTING_CLAIM_COUNT:
        # Compute msg using ( for later build outputs logic.
        msg = (
            "commenting doctrine claim census changed: "
            f"expected {COMMENTING_CLAIM_COUNT}, observed {len(claims)}; "
            "review the extractor and every added or removed claim"
        )
        # Propagate the localized failure so callers cannot mistake it for success.
        raise ProvenanceError(msg)
    # Return section rows, claim rows, Markdown view, and JSON ledger to the caller.
    return rows, claims, render(rows, claims), render_claim_ledger(claims, source_digest)


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the provenance ledger from the extraction census.

    Prints the tally per disposition, so an UNREVIEWED count is visible in the
    build output and not only inside the file just written.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 once the ledger is written, or 1 when the census file is absent

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
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

    # Select the existing-artifact path only when `not args.extraction.exists()` is satisfied.
    if not args.extraction.exists():
        print(f"missing {args.extraction}; run tools/extract_sources.py first", file=sys.stderr)
        # Return the aggregate process status to the command-line boundary.
        return 1

    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve claim ledger, claims, provenance, rows element values in deterministic source
        # Details: order.
        rows, claims, provenance, claim_ledger = _build_outputs(args.extraction)
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (KeyError, TypeError, ValueError, yaml.YAMLError) as exc:
        print(f"provenance build failed: {exc}", file=sys.stderr)
        # Return the aggregate process status to the command-line boundary.
        return 1

    # Each outputs element is one `(destination path, rendered content)` tuple; provenance then
    # claim-ledger publication order is preserved.
    outputs = ((args.out, provenance), (args.claim_out, claim_ledger))
    # Select the guarded path only after `args.check` is satisfied.
    if args.check:
        # Each drifted element is one output path whose bytes differ or are absent; output tuple
        # order is preserved.
        drifted = [
            path
            for path, expected in outputs
            if not path.is_file() or path.read_text(encoding="utf-8") != expected
        ]
        # Handle the non-empty or enabled drifted state.
        if drifted:
            # Resolve the repository-confined path used by this operation before filesystem
            # Details: access.
            # Process each candidate element in deterministic source order.
            for path in drifted:
                print(f"DRIFT: {path}", file=sys.stderr)
            # Return the aggregate process status to the command-line boundary.
            return 1
    else:
        # Resolve the repository-confined path used by this operation before filesystem access.
        # Process each candidate element in deterministic source order.
        for path, content in outputs:
            # Publish the externally visible effect after all required inputs are ready.
            path.parent.mkdir(parents=True, exist_ok=True)
            # Publish the externally visible effect after all required inputs are ready.
            path.write_text(content, encoding="utf-8", newline="\n")

    # Select counts, r as the current element from rows) while main preserves traversal order.
    counts = Counter(r.disposition for r in rows)
    # Compute action using "checked" if args.check else "wrote" for later main logic.
    action = "checked" if args.check else "wrote"
    print(f"{action} {args.out.relative_to(REPO_ROOT).as_posix()}: {len(rows)} sections")
    # Preserve the observed item count used by the non-vacuity verdict.
    # Process each candidate element in deterministic source order.
    for disposition, count in sorted(counts.items()):
        print(f"  {disposition}: {count}")
    # Select claim counts, row as the current element from claims) while main preserves
    # Details: traversal order.
    claim_counts = Counter(row.disposition for row in claims)
    print(
        f"{action} {args.claim_out.relative_to(REPO_ROOT).as_posix()}: "
        f"{len(claims)} claims, 0 unreviewed, 0 multiply claimed"
    )
    # Preserve the observed item count used by the non-vacuity verdict.
    # Process each candidate element in deterministic source order.
    for disposition, count in sorted(claim_counts.items()):
        print(f"  {disposition}: {count}")
    # Return the aggregate process status to the command-line boundary.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
