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
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

## Where the corpus is read from unless `--root` says otherwise, and -- always,
## `--root` notwithstanding -- the root the paths in the output are relative to.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent

## Source documents, in the order they take precedence (later supersedes earlier).
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
_NUMBERED_RULE = re.compile(r"^\s*(?:(?P<letter>[A-G]\d)\.|(?P<num>\d{1,2})\.)\s+\*\*(?P<title>[^*]+)\*\*")
## A checklist entry. Whether the box is ticked says nothing about its force.
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[[ x]\]\s+(?P<text>.+)$")
## Any table row, used only to recognise and discard the `|---|` separators.
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")


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

    ## Two-letter tag of the document it came from, as listed in `SOURCES`.
    source: str
    ## The document, repository-relative and POSIX-separated.
    path: str
    ## Heading it sits under, or `(preamble)` when it precedes the first one.
    section: str
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
    flat = " ".join(text.split())
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
    lines = path.read_text(encoding="utf-8").splitlines()
    rel = path.relative_to(REPO_ROOT).as_posix()
    sections: list[Section] = []
    candidates: list[Candidate] = []
    current = "(preamble)"
    inside_fence = False
    counts: Counter[str] = Counter()

    for index, line in enumerate(lines, start=1):
        if _FENCE.match(line):
            inside_fence = not inside_fence
            continue
        if inside_fence:
            continue

        heading = _HEADING.match(line)
        if heading is not None:
            current = heading.group("text")
            sections.append(
                Section(
                    source=tag,
                    path=rel,
                    level=len(heading.group("hashes")),
                    heading=current,
                    line=index,
                )
            )
            continue

        for candidate in _candidates_in(tag, rel, current, index, line):
            candidates.append(candidate)
            counts[current] += 1

    sections = [Section(**{**asdict(s), "candidates": counts.get(s.heading, 0)}) for s in sections]
    return sections, candidates


def _candidates_in(
    tag: str, rel: str, section: str, line_no: int, line: str
) -> Iterator[Candidate]:
    """What a single line contributes to the census, which is at most one entry.

    The nets are tried from the most explicit signal to the weakest inference --
    force tag, numbered rule, checklist item, RFC-2119 keyword, bare prohibition
    -- and the first match ends the line, so no statement is counted twice under
    two kinds. Blank lines and table separators contribute nothing, and a
    prohibition inside a blockquote is ignored on the grounds that a quotation is
    citing a rule rather than stating one.

    @param tag the two-letter code of the document
    @param rel the document, repository-relative
    @param section the heading the line sits under
    @param line_no the line's 1-based position
    @param line the line as it appears, indentation included
    @return the one candidate the line produces, or nothing
    """
    stripped = line.strip()
    if not stripped or (_TABLE_ROW.match(line) and stripped.startswith("|---")):
        return

    tagged = _TAGGED.search(line)
    if tagged is not None:
        force = tagged.group("tag") or tagged.group("bare")
        yield Candidate(tag, rel, section, line_no, "tagged", _truncate(stripped), force)
        return

    numbered = _NUMBERED_RULE.match(line)
    if numbered is not None:
        yield Candidate(
            tag, rel, section, line_no, "numbered-rule", _truncate(stripped), "unclassified"
        )
        return

    checkbox = _CHECKBOX.match(line)
    if checkbox is not None:
        yield Candidate(
            tag, rel, section, line_no, "checklist", _truncate(checkbox.group("text")), "unclassified"
        )
        return

    if _RFC2119.search(line):
        yield Candidate(tag, rel, section, line_no, "rfc2119", _truncate(stripped), "BINDING")
        return

    if _NEVER.search(line) and not line.lstrip().startswith(">"):
        yield Candidate(
            tag, rel, section, line_no, "prohibition", _truncate(stripped), "unclassified"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Write the inventory file and summarise it on the console.

    A source that is not on disk is named on stderr and makes the run fail, but
    the documents that are present are still inventoried: a partial census is
    worth having while the corpus is being moved around, and the exit status
    still says it is incomplete.

    @param argv the arguments after the program name; `None` takes them from
           `sys.argv`
    @return 0 when every listed source was found, 1 when any was missing
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Inventory the source corpus.")
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "tools" / "extraction.yaml")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)

    all_sections: list[Section] = []
    all_candidates: list[Candidate] = []
    missing: list[str] = []

    for tag, relative in SOURCES:
        path = args.root / relative
        if not path.exists():
            missing.append(relative)
            continue
        sections, candidates = scan(tag, path)
        all_sections.extend(sections)
        all_candidates.extend(candidates)

    payload = {
        "generated_by": "tools/extract_sources.py",
        "note": (
            "Mechanical first pass. Module assignment, mechanism choice and "
            "deduplication are judgment and are recorded in meta/PROVENANCE.md."
        ),
        "sections": [asdict(s) for s in all_sections],
        "candidates": [asdict(c) for c in all_candidates],
    }
    args.out.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True, width=100),
        encoding="utf-8",
        newline="\n",
    )

    by_source = Counter(c.source for c in all_candidates)
    by_kind = Counter(c.kind for c in all_candidates)
    print(f"wrote {args.out.relative_to(args.root).as_posix()}")
    print(f"  {len(all_sections)} sections, {len(all_candidates)} candidate statements")
    print("  by source: " + ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())))
    print("  by kind:   " + ", ".join(f"{k}={v}" for k, v in sorted(by_kind.items())))
    for name in missing:
        print(f"  MISSING: {name}", file=sys.stderr)
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
