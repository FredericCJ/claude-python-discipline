"""Mechanically inventory the source corpus, ahead of authoring `law/`.

    python tools/extract_sources.py [--out tools/extraction.yaml]

Produces two things the rest of the migration depends on:

* a **section census** -- every heading in every source document, which becomes the
  skeleton of `discipline/meta/PROVENANCE.md`. Nothing may be dropped silently: at
  the end, every section here must be marked migrated, superseded or dropped.
* **candidate rules** -- every already-tagged rule, every RFC-2119 sentence, every
  numbered rule item and every checklist entry, with its source, section and line.

Judgment -- which module a rule belongs to, what mechanism can decide it, whether
two candidates are the same rule -- is deliberately *not* done here. This pass only
guarantees that nothing escapes the net.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

## Where the corpus is read from unless `--root` says otherwise, and -- always,
## `--root` notwithstanding -- the root the paths in the output are relative to.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent
## ATX depth treated as the owning doctrine section when attributing nested claims.
MAJOR_HEADING_LEVEL: Final = 2

## Source documents, in the order they take precedence (later supersedes earlier).
## Each element is a `(two-letter provenance tag, repository-relative document path)` tuple;
## precedence increases with tuple order.
SOURCES: Final[tuple[tuple[str, str], ...]] = (
    ("SG", "sources/Software Engineering Style Guidelines.md"),
    ("SE", "sources/doctrine/SOFTWARE-ENGINEERING.md"),
    ("TD", "sources/doctrine/TESTING.md"),
    ("CA", "sources/doctrine/CHEAPEST-ABLE.md"),
    ("AR", "sources/manifests/architecture_manifest_default.md"),
    ("ET", "sources/manifests/error_tracing_contract_manifest.md"),
    ("LO", "sources/manifests/logging_observability_manifest.md"),
    ("TY", "sources/manifests/python_typing_contract_manifest.md"),
    ("TT", "sources/manifests/python_testing_tooling_manifest.md"),
    ("SP", "sources/manifests/software_spec_discipline_manifest.md"),
    ("AT", "sources/manifests/claude_code_agent_teams_manifest.md"),
    ("CD", "roadmap/from-4.1-to-5.0/inputs/python-commenting-and-documentation-discipline.md"),
)

## An ATX heading down to the third level. Deeper ones are treated as prose, so a
## candidate under one is attributed to the nearest heading above it.
_HEADING = re.compile(r"^(?P<hashes>#{1,3})\s+(?P<text>.+?)\s*$")
## The opening or closing line of a fenced block. Everything between two of these
## is an example, and an example that says MUST is not a rule.
_FENCE = re.compile(r"^\s*```")
## An explicit force tag, bold or bare -- the one signal that needs no guessing.
_TAGGED = re.compile(r"\*\*\[(?P<tag>BINDING|ADVISORY)\]\*\*|\[(?P<bare>BINDING|ADVISORY)\]")
## RFC-2119 keywords. Only whether one is present is read; the negative forms
## still lead so a match can never come back as the `MUST` of a `MUST NOT`.
_RFC2119 = re.compile(r"\b(MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|MAY)\b")
## A prohibition written in plain English, in each casing the corpus uses.
_NEVER = re.compile(r"\b(never|Never|NEVER)\b")
## A rule item numbered or lettered and given a bold title: an `A1` or a `12`,
## each followed by a dot, then the title in bold. The dots sit outside the code
## spans deliberately -- a span ending in a period breaks the Doxygen build.
## The letters stop at G and the numbers at two digits, so a corpus that grows an
## `H1` series silently stops being caught here.
_NUMBERED_RULE = re.compile(
    r"^\s*(?:(?P<letter>[A-G]\d)\.|(?P<num>\d{1,2})\.)\s+\*\*(?P<title>[^*]+)\*\*"
)
## A checklist entry. Whether the box is ticked says nothing about its force.
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[[ x]\]\s+(?P<text>.+)$")
## Any table row, used only to recognise and discard the `|---|` separators.
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")
## An ordinary list item. The commenting doctrine uses lists to complete a
## normative lead-in, so each item is a claim even when it carries no modal of
## its own. Fenced examples have already been removed by `scan`.
_BULLET = re.compile(r"^\s*[-*]\s+(?P<text>.+)$")
## The supplied doctrine uses lower-case force words rather than RFC-2119 case.
## Keep this net source-specific so re-running the historical extraction does
## not silently reinterpret all eleven already-disposed corpora.
_COMMENTING_MODAL = re.compile(
    r"\b(?:shall|must|should|may|required|requires?|prohibited|forbidden|"
    r"never|always|do not|cannot)\b",
    re.IGNORECASE,
)
## The only non-claim row in the doctrine's compact allocation table.
_COMMENTING_TABLE_HEADER = "| information | preferred owner |"


@dataclass(frozen=True, slots=True)
class Section:
    """One heading in a source document."""

    ## Two-letter tag of the document it came from, as listed in `SOURCES`.
    source: str
    ## The document, repository-relative and POSIX-separated, so the census is
    ## comparable across machines.
    path: str
    ## Depth of the heading, 1 to 3, counted in `#` characters.
    level: int
    ## The heading text verbatim. Also the key candidates are grouped under, so
    ## two identical headings in one document share a count.
    heading: str
    ## Where the heading sits, 1-based, so provenance can cite it.
    line: int
    ## How many candidate statements the nets caught under this heading. Zero
    ## means nothing matched, not that there is nothing here to migrate: an
    ## untagged section of plain prose still has to be accounted for.
    candidates: int = 0


@dataclass(frozen=True, slots=True)
class Candidate:
    """One statement that may become a rule."""

    ## Stable identity derived from the source tag, source line and complete
    ## normalized statement. A changed source line therefore cannot inherit an
    ## earlier disposition silently.
    claim_id: str
    ## Two-letter tag of the document it came from, as listed in `SOURCES`.
    source: str
    ## The document, repository-relative and POSIX-separated.
    path: str
    ## Heading it sits under, or `(preamble)` when it precedes the first one.
    section: str
    ## Nearest level-two heading. This keeps the owning numbered doctrine
    ## section available when a level-three example heading is more local.
    major_section: str
    ## Where the statement sits, 1-based, so the author can go back and read it
    ## in context before deciding anything.
    line: int
    ## Which net caught it: tagged, numbered-rule, checklist, rfc2119 or
    ## prohibition. Ordered from explicit signal to weakest inference.
    kind: str
    ## The statement, whitespace-collapsed and truncated to stay reviewable. A
    ## checklist entry arrives without its box; everything else keeps the line as
    ## written, list marker and Markdown emphasis included.
    text: str
    ## A hint for whoever authors the rule, never a decision, and deliberately
    ## crude: only a force tag yields ADVISORY, every RFC-2119 line is hinted
    ## BINDING even when its keyword was MAY, and a numbered rule or checklist
    ## item stays unclassified even when its text says MUST.
    force_hint: str


@dataclass(frozen=True, slots=True)
class CandidateContext:
    """Source location shared by every candidate constructor on one line."""

    ## Two-letter source tag and repository-relative document path.
    source: str
    ## Repository path that owns this candidate record.
    path: str
    ## Nearest heading and its owning level-two heading.
    section: str
    ## Nearest level-two heading, retained while more local level-three headings change.
    major_section: str


def _claim_id(source: str, line: int, text: str) -> str:
    """Build the stable identity used by the claim-disposition ledger.

    The line is deliberately part of the identity. Reordering the immutable
    source is a source change and must invalidate its previous review, even when
    the sentence itself is unchanged.

    @param source two-letter source tag
    @param line 1-based source line
    @param text complete normalized source statement
    @return an identity readable by a reviewer and collision-resistant in the corpus
    """
    # Hash the complete normalized statement so changed wording cannot inherit a disposition.
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    # Return an identity readable by a reviewer and collision-resistant in the corpus to the
    # caller.
    return f"{source}-L{line:04d}-{digest}"


def _candidate(
    context: CandidateContext,
    line: int,
    kind: str,
    text: str,
    force_hint: str,
) -> Candidate:
    """Construct one candidate without letting its identity and text diverge.

    @param context source document and heading ownership
    @param line 1-based source line
    @param kind extraction signal that selected the line
    @param text normalized statement preserved in the census
    @param force_hint mechanical force hint, never the final disposition
    @return the candidate and its derived stable identity
    """
    # Normalize and bound display text before deriving both identity and stored content.
    normalized = _truncate(text)
    # Return the candidate and its derived stable identity to the caller.
    return Candidate(
        _claim_id(context.source, line, normalized),
        context.source,
        context.path,
        context.section,
        context.major_section,
        line,
        kind,
        normalized,
        force_hint,
    )


def _truncate(text: str, limit: int = 400) -> str:
    """Collapse a statement onto one line short enough to read in a list.

    Runs of whitespace -- the padding inside a table cell, a tab, a double space
    after a full stop -- collapse to one, so every entry in the census reads
    alike. The input is a single source line: a sentence the author wrapped
    across two of them stays two statements, here and in the output.

    @param text one statement, as it stands in the document
    @param limit the longest result allowed, the ellipsis counted within it
    @return the flattened statement, never longer than the limit
    """
    # Collapse every whitespace run to one space for stable readable census entries.
    flat = " ".join(text.split())
    # Return the flattened statement, never longer than the limit to the caller.
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def scan(tag: str, path: Path) -> tuple[list[Section], list[Candidate]]:
    """Inventory one document: its headings, and the statements beneath each.

    Fenced blocks are excluded wholesale: neither a heading nor a MUST inside a
    worked example enters the census. Every section is returned even when it
    yielded nothing, because the census is only useful if it accounts for the
    whole document.

    @param tag the two-letter code recorded on everything found here
    @param path the document to read; it must lie under `REPO_ROOT`, because the
           path recorded on every result is taken relative to that
    @return its sections, each carrying its candidate count, and its candidates
    """
    # Preserve decoded source-line strings in lexical document order.
    lines = path.read_text(encoding="utf-8").splitlines()
    # Record the document using a repository-relative POSIX provenance path.
    rel = path.relative_to(REPO_ROOT).as_posix()
    # Each sections element is one accepted-heading record; document order is preserved.
    sections: list[Section] = []
    # Each candidates element is one strongest-signal claim record; source-line order is
    # preserved.
    candidates: list[Candidate] = []
    # Begin candidate attribution in the synthetic pre-heading section.
    current = "(preamble)"
    # Begin major-section attribution in the same synthetic pre-heading section.
    current_major = "(preamble)"
    # True enables inside fence; false selects its disabled alternative.
    inside_fence = False
    # Count candidate records by nearest-heading text; counter key order is deliberately unused.
    counts: Counter[str] = Counter()

    # Inspect every source line with its one-based provenance position in document order.
    for index, line in enumerate(lines, start=1):
        # Toggle example exclusion at each fenced-block delimiter.
        if _FENCE.match(line):
            # Flip whether subsequent lines belong to a fenced example.
            inside_fence = not inside_fence
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Exclude every line inside a fenced example from headings and candidate nets.
        if inside_fence:
            # Advance after the current candidate has been conclusively excluded.
            continue

        # Match accepted ATX heading levels before applying any claim detector.
        heading = _HEADING.match(line)
        # Update the nearest owning section before classifying claims beneath this heading.
        if heading is not None:
            # Make this heading the nearest section for subsequent candidate lines.
            current = heading.group("text")
            # Update major ownership only at the declared level-two boundary.
            if len(heading.group("hashes")) == MAJOR_HEADING_LEVEL:
                # Carry this level-two title across nested headings until the next peer.
                current_major = current
            sections.append(
                Section(
                    source=tag,
                    path=rel,
                    level=len(heading.group("hashes")),
                    heading=current,
                    line=index,
                )
            )
            # Advance after the current candidate has been conclusively excluded.
            continue

        # Freeze source and current heading ownership for all detectors on this line.
        context = CandidateContext(tag, rel, current, current_major)
        # Select at most one candidate using strongest-signal precedence.
        candidate = _candidate_in(context, index, line)
        # Record a detected claim and increment its owning section count together.
        if candidate is not None:
            candidates.append(candidate)
            # Increment the current heading only after the candidate record is retained.
            counts[current] += 1

    # Rebuild section records in document order with final candidate-count values attached.
    sections = [Section(**{**asdict(s), "candidates": counts.get(s.heading, 0)}) for s in sections]
    # Return its sections, each carrying its candidate count, and its candidates to the caller.
    return sections, candidates


def _explicit_candidate(
    context: CandidateContext, line_no: int, line: str, stripped: str
) -> Candidate | None:
    """Extract high-confidence claim syntax shared by every source document.

    @param context source and heading ownership
    @param line_no 1-based source line
    @param line original source line
    @param stripped whitespace-trimmed source line
    @return an explicitly tagged, numbered, or checklist claim when present
    """
    # Search first for an explicit BINDING or ADVISORY force tag.
    tagged = _TAGGED.search(line)
    # Let an explicit force tag override every syntax-derived force default.
    if tagged is not None:
        # Select the named or bare capture as the authoritative force hint.
        force = tagged.group("tag") or tagged.group("bare")
        # Return an explicitly tagged, numbered, or checklist claim when present to the caller.
        return _candidate(context, line_no, "tagged", stripped, force)
    # Treat a numbered bold-title rule as the next-highest confidence signal.
    if _NUMBERED_RULE.match(line) is not None:
        # Return an explicitly tagged, numbered, or checklist claim when present to the caller.
        return _candidate(context, line_no, "numbered-rule", stripped, "unclassified")
    # Match checklist syntax only after tagged and numbered forms are excluded.
    checkbox = _CHECKBOX.match(line)
    # Admit checklist syntax only after the stronger tagged and numbered forms are excluded.
    if checkbox is not None:
        # Return an explicitly tagged, numbered, or checklist claim when present to the caller.
        return _candidate(context, line_no, "checklist", checkbox.group("text"), "unclassified")
    # Return an explicitly tagged, numbered, or checklist claim when present to the caller.
    return None


def _commenting_candidate(
    context: CandidateContext, line_no: int, line: str, stripped: str
) -> Candidate | None:
    """Extract the lower-case normative forms used by the v5 doctrine.

    @param context source and heading ownership
    @param line_no 1-based source line
    @param line original source line
    @param stripped whitespace-trimmed source line
    @return one commenting-doctrine claim when present
    """
    # Treat doctrine list items as binding enumerated claims.
    bullet = _BULLET.match(line)
    # Treat each commenting-doctrine bullet as one enumerated normative claim.
    if bullet is not None:
        # Return one commenting-doctrine claim when present to the caller.
        return _candidate(context, line_no, "enumerated-claim", bullet.group("text"), "BINDING")
    # Treat non-header allocation-table rows as binding decisions.
    if _TABLE_ROW.match(line) and stripped.lower() != _COMMENTING_TABLE_HEADER:
        # Return one commenting-doctrine claim when present to the caller.
        return _candidate(context, line_no, "decision-table", stripped, "BINDING")
    # Treat remaining lower-case modal prose as a binding claim.
    if _COMMENTING_MODAL.search(line):
        # Return one commenting-doctrine claim when present to the caller.
        return _candidate(context, line_no, "normative-prose", stripped, "BINDING")
    # Return one commenting-doctrine claim when present to the caller.
    return None


def _candidate_in(context: CandidateContext, line_no: int, line: str) -> Candidate | None:
    """Return the single strongest claim signal contributed by one source line.

    The nets run from explicit force to source-specific inference. Fenced blocks
    were removed by `scan`; table separators and quoted prohibitions do not count.

    @param context source and heading ownership
    @param line_no 1-based source line
    @param line original source line
    @return the one candidate selected for this line, or None
    """
    # Normalize outer whitespace once for every claim detector and stored statement.
    stripped = line.strip()
    # Exclude blank lines and Markdown table separators before signal precedence begins.
    if not stripped or (_TABLE_ROW.match(line) and stripped.startswith("|---")):
        # Return the one candidate selected for this line, or None to the caller.
        return None
    # Give tagged, numbered, and checklist syntax first claim on the line.
    explicit = _explicit_candidate(context, line_no, line, stripped)
    # Give tagged, numbered, and checklist claims precedence over source-specific heuristics.
    if explicit is not None:
        # Return the one candidate selected for this line, or None to the caller.
        return explicit
    # Apply lower-case doctrine-specific inference only to the v5 commenting source.
    if context.source == "CD":
        # Test enumerated, allocation-table, then normative-prose signals in order.
        commenting = _commenting_candidate(context, line_no, line, stripped)
        # Accept the commenting-doctrine-specific claim after the shared explicit forms decline it.
        if commenting is not None:
            # Return the one candidate selected for this line, or None to the caller.
            return commenting
    # Use uppercase RFC-2119 vocabulary as the general binding fallback.
    if _RFC2119.search(line):
        # Return the one candidate selected for this line, or None to the caller.
        return _candidate(context, line_no, "rfc2119", stripped, "BINDING")
    # Capture unquoted prohibitions only after every stronger signal is absent.
    if _NEVER.search(line) and not line.lstrip().startswith(">"):
        # Return the one candidate selected for this line, or None to the caller.
        return _candidate(context, line_no, "prohibition", stripped, "unclassified")
    # Return the one candidate selected for this line, or None to the caller.
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Write the inventory file and summarise it on the console.

    A source that is not on disk is named on stderr and makes the run fail, but
    the documents that are present are still inventoried: a partial census is
    worth having while the corpus is being moved around, and the exit status
    still says it is incomplete.

    @param argv the arguments after the program name; `None` takes them from
           `sys.argv`
    @return 0 when every listed source was found, 1 when any was missing

    @par Effects
    In write mode, replaces the requested YAML census after scanning all present
    sources; check mode performs no filesystem writes.
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Inventory the source corpus.")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "tools" / "extraction.yaml")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the committed census with a fresh extraction without writing it",
    )
    args = parser.parse_args(argv)

    # Each all sections element is one heading record; source-precedence then document order is
    # preserved.
    all_sections: list[Section] = []
    # Each all candidates element is one claim record; source-precedence then source-line order
    # is preserved.
    all_candidates: list[Candidate] = []
    # Each missing element is one absent relative source-path string; declared source order is
    # preserved.
    missing: list[str] = []

    # Scan each `(tag, relative path)` source tuple in declared precedence order.
    for tag, relative in SOURCES:
        # Resolve the current declared source path below the selected input root.
        path = args.root / relative
        # Record a missing source without abandoning the partial census.
        if not path.exists():
            missing.append(relative)
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Scan the present document into ordered section and candidate records.
        sections, candidates = scan(tag, path)
        all_sections.extend(sections)
        all_candidates.extend(candidates)

    # Map YAML schema-field keys to provenance metadata and ordered record sequences; insertion
    # order intentionally defines human-readable output order.
    payload = {
        "generated_by": "tools/extract_sources.py",
        "note": (
            "Mechanical first pass. Module assignment, mechanism choice and "
            "deduplication are judgment and are recorded in meta/PROVENANCE.md."
        ),
        # Serialize section dataclasses in accumulated source/document order.
        "sections": [asdict(s) for s in all_sections],
        # Serialize candidate dataclasses in accumulated source/line order.
        "candidates": [asdict(c) for c in all_candidates],
    }
    # Render deterministic Unicode YAML while preserving schema insertion order.
    rendered = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100)
    # In check mode, detect either an absent census or byte-level extraction drift.
    drifted = args.check and (
        not args.out.exists() or args.out.read_text(encoding="utf-8") != rendered
    )
    # Write mode replaces the census only after the complete rendering exists.
    if not args.check:
        # Publish normalized UTF-8 YAML with platform-independent newlines.
        args.out.write_text(rendered, encoding="utf-8", newline="\n")

    # Count candidate records by source-tag key for the summary; key order is later sorted.
    by_source = Counter(c.source for c in all_candidates)
    # Count candidate records by extraction-kind key for the summary; key order is later sorted.
    by_kind = Counter(c.kind for c in all_candidates)
    # Name whether this invocation compared or published the census.
    action = "checked" if args.check else "wrote"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Prefer a portable path relative to the selected source root.
        display_path = args.out.relative_to(args.root).as_posix()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError:
        # Fall back to the absolute POSIX spelling for an external output path.
        display_path = args.out.as_posix()
    print(f"{action} {display_path}")
    print(f"  {len(all_sections)} sections, {len(all_candidates)} candidate statements")
    # Render source-tag/count pairs in lexical tag order.
    print("  by source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    # Render extraction-kind/count pairs in lexical kind order.
    print("  by kind:   " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    # Report missing relative source paths in declaration order.
    for name in missing:
        print(f"  MISSING: {name}", file=sys.stderr)
    # Report committed-census drift independently of source absence.
    if drifted:
        print("  DRIFT: committed extraction differs from the source corpus", file=sys.stderr)
    # Return the aggregate process status to the command-line boundary.
    return 1 if missing or drifted else 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
