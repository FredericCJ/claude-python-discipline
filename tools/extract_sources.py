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
from collections.abc import Iterator, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

import yaml

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

_HEADING = re.compile(r"^(?P<hashes>#{1,3})\s+(?P<text>.+?)\s*$")
_FENCE = re.compile(r"^\s*```")
_TAGGED = re.compile(r"\*\*\[(?P<tag>BINDING|ADVISORY)\]\*\*|\[(?P<bare>BINDING|ADVISORY)\]")
_RFC2119 = re.compile(r"\b(MUST NOT|MUST|SHALL NOT|SHALL|SHOULD NOT|SHOULD|MAY)\b")
_NEVER = re.compile(r"\b(never|Never|NEVER)\b")
_NUMBERED_RULE = re.compile(r"^\s*(?:(?P<letter>[A-G]\d)\.|(?P<num>\d{1,2})\.)\s+\*\*(?P<title>[^*]+)\*\*")
_CHECKBOX = re.compile(r"^\s*[-*]\s+\[[ x]\]\s+(?P<text>.+)$")
_TABLE_ROW = re.compile(r"^\s*\|.+\|\s*$")


@dataclass(frozen=True, slots=True)
class Section:
    """One heading in a source document."""

    source: str
    path: str
    level: int
    heading: str
    line: int
    candidates: int = 0


@dataclass(frozen=True, slots=True)
class Candidate:
    """One statement that may become a rule."""

    source: str
    path: str
    section: str
    line: int
    kind: str
    text: str
    force_hint: str


def _truncate(text: str, limit: int = 400) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def scan(tag: str, path: Path) -> tuple[list[Section], list[Candidate]]:
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
