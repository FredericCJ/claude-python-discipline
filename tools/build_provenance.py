"""Generate `discipline/meta/PROVENANCE.md` from the source-section census.

    python tools/build_provenance.py

Reads `tools/extraction.yaml` (written by `extract_sources.py`) and maps every
heading in the eight source documents to its disposition: migrated to named
modules, superseded by another source, or dropped with a reason.

The point is that nothing leaves the corpus silently. A section with no entry
below is reported as UNREVIEWED, and the count is printed -- the same treatment
`ENFORCEMENT.md` gives an unbuilt mechanism.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

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
}

## Section-level exceptions, matched as a case-insensitive substring of the
## heading. Each carries the disposition and the reason.
DISPOSITIONS: Final[tuple[tuple[str, str, str, str], ...]] = (
    # source, heading substring, disposition, note
    ("SG", "", "superseded",
     "Every section is re-covered by doctrine/SOFTWARE-ENGINEERING.md, which names the "
     "supersession itself. Mined for the handful of items the doctrine dropped."),
    ("SE", "compiled core", "dropped",
     "Resolved as CONFLICTS C1: Python is the premise, not a departure. The underlying "
     "concerns survive as the motivation for strict typing and mutation testing."),
    ("SE", "the python core", "dropped",
     "Same resolution; the tension section is not carried forward as an apology."),
    ("SE", "revision log", "dropped", "Superseded by version control."),
    ("TD", "revision log", "dropped", "Superseded by version control."),
    ("CA", "revision log", "dropped", "Superseded by version control."),
    ("SE", "summary", "dropped", "Replaced by discipline/KERNEL.md."),
    ("TD", "one sentence that explains", "migrated", "Opens law/TEST."),
    ("SE", "how this doctrine is enforced", "migrated",
     "Generalized into enforce/ENFORCEMENT.md, now generated from the rules."),
    ("SE", "architecture decision record template", "migrated",
     "Obligations kept as FLOW-003..005; the template itself belongs to a project."),
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
        rows.append(
            Row(source, heading, int(section["line"]), disposition, targets, note)
        )
    return rows


def render(rows: Sequence[Row]) -> str:
    """The whole of PROVENANCE.md: front matter, tallies, exceptions, gaps.

    The exceptions table holds only headings matched by a *named* section in
    DISPOSITIONS; a document-wide entry is that document's default, not an
    exception to it, so it never appears there. Among what remains, each
    distinct reason is printed once per document rather than once per heading.
    The unreviewed section is emitted only when something is unreviewed.

    @param rows every section, already ruled on
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
        "<!-- GENERATED by tools/build_provenance.py -- do not edit; "
        "change DISPOSITIONS in that script and rebuild. -->",
        "",
        "# Source Provenance",
        "",
        f"Every heading in the {len(by_source)} source documents "
        f"({len(rows)} sections) and where it went. Nothing leaves the corpus silently: "
        "a section with no recorded disposition is reported as `UNREVIEWED` here and by "
        "the build, rather than quietly omitted.",
        "",
        "**Resolution.** The mapping is at document granularity, with the named "
        "section-level exceptions below. It establishes that no source *document* was "
        "dropped and that each one's material has a home; it does not by itself prove "
        "that every individual claim survived. Section-by-section verification is the "
        "remaining work, and this file is where it will be recorded.",
        "",
        "| Disposition | Sections |",
        "|---|---|",
    ]
    for disposition, count in sorted(counts.items()):
        lines.append(f"| {disposition} | {count} |")
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
        lines += [
            f"| `{r.source}` | {r.line} | {_escape(r.heading)} |" for r in unreviewed
        ]
        lines.append("")

    lines += [
        "## Dropped material, in full",
        "",
        "The corpus carried roughly 130 references to documents that do not exist in it, "
        "73 of them to a single PROPOSAL.md. All are severed. Where a reference carried "
        "information, the information is inlined and the pointer dropped: the recorded "
        "incident in which a cleanup routine destroyed 8,023 files while reporting success "
        "is kept as the justification for `EFCT-005`, because the rule is not persuasive "
        "without it. Where a reference was bookkeeping, it is deleted. "
        "`tools/validate.py` rejects any new one as `V041`.",
        "",
        "Project-specific material — package paths, a document renderer, bilingual "
        "catalogs, one filesystem's atomicity guarantees — is genericized rather than "
        "carried. The rules that depended on it are stated against a neutral layer "
        "layout; the worked artifacts worth keeping belong in `discipline/examples/`.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _escape(text: str) -> str:
    """Make a heading safe to drop into a Markdown table cell.

    @param text arbitrary heading text
    @return the same text with any pipe backslash-escaped
    """
    return re.sub(r"\|", r"\\|", text)


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
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "discipline" / "meta" / "PROVENANCE.md")
    args = parser.parse_args(argv)

    if not args.extraction.exists():
        print(f"missing {args.extraction}; run tools/extract_sources.py first", file=sys.stderr)
        return 1

    payload = yaml.safe_load(args.extraction.read_text(encoding="utf-8"))
    rows = build_rows(payload.get("sections", []))
    args.out.write_text(render(rows), encoding="utf-8")

    counts = Counter(r.disposition for r in rows)
    print(f"wrote {args.out.relative_to(REPO_ROOT).as_posix()}: {len(rows)} sections")
    for disposition, count in sorted(counts.items()):
        print(f"  {disposition}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
