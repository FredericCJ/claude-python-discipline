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
    parse_document,
    prose_of,
)

SCHEMA_PATH: Final = Path(__file__).resolve().parent / "frontmatter.schema.json"

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
_MD_MENTION = re.compile(r"`(?P<name>[A-Za-z0-9_./-]+\.md)`")
_BARE_BANNED = re.compile(r"^###\s+(?P<term>.+?)\s*\[BARE-BANNED\]\s*$", re.MULTILINE)
_RULE_ID = re.compile(r"^[A-Z][A-Z0-9]{1,7}-\d{3}$")

## How far an agent may have to walk from a module to reach any rule (V092).
REACH_DEPTH: Final = 3
## A tool named in a fact module's version table, and a tool named in a Check.
_TOOL_ROW = re.compile(r"^\|\s*([A-Za-z][A-Za-z0-9_.-]{2,})\s*\|\s*\d", re.MULTILINE)
_TOOL_WORD = re.compile(r"[a-z][a-z0-9_-]{2,}")


class Severity(StrEnum):
    ERROR = "error"
    WARN = "warn"


@dataclass(frozen=True, slots=True)
class Finding:
    """One validation defect, addressable by `code` and fixable from `remediation`."""

    code: str
    severity: Severity
    path: str
    line: int
    message: str
    remediation: str

    def render(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.severity.value.upper()} {self.code} "
            f"{self.message}\n    -> {self.remediation}"
        )


@dataclass(frozen=True, slots=True)
class Layout:
    """Where the corpus lives. Injected so the checks are testable in isolation."""

    root: Path

    @property
    def discipline(self) -> Path:
        return self.root / "discipline"

    @property
    def enforce(self) -> Path:
        return self.root / "enforce"

    @property
    def examples(self) -> Path:
        return self.discipline / "examples"

    @property
    def enforcement_ledger(self) -> Path:
        return self.enforce / "ENFORCEMENT.md"

    @property
    def open_ledger(self) -> Path:
        return self.discipline / "meta" / "OPEN.md"

    @property
    def glossary(self) -> Path:
        return self.discipline / "meta" / "GLOSSARY.md"

    def rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return path.as_posix()


DEFAULT_LAYOUT: Final = Layout(REPO_ROOT)


def _relpath(layout: Layout, doc: Document) -> str:
    return layout.rel(doc.path)


# --------------------------------------------------------------------------- checks


def check_front_matter(
    doc: Document, schema: dict[str, object], layout: Layout
) -> Iterator[Finding]:
    """V002-V004 -- front-matter conforms, and agrees with where the file sits."""
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
    """V010-V012 -- what each genre may do. SCHEMA.md section 1."""
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
    """V020-V024 -- rule identity, and the mechanism-first axiom."""
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
    """V030-V031 -- every [ADVISORY] and [OPEN] rule is accounted for in writing."""
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
    """V040-V041 -- every reference resolves. SCHEMA.md section 5."""
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
    """V050 -- token ceilings, so a session can afford to load a module."""
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
    """V060 -- dated genres are re-verified before they rot."""
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


def mechanism_is_implemented(mechanism: str, layout: Layout) -> bool | None:
    """Whether a mechanism tag points at something that exists.

    Returns None for mechanisms this cannot verify -- `auto:*` names a tool's own
    rule, and `review` names a person.
    """
    kind, _, target = mechanism.partition(":")
    if kind == "check":
        return (layout.enforce / "checks" / f"{target}.py").exists()
    if kind == "fitness":
        return any(
            f"def {target}(" in path.read_text(encoding="utf-8")
            for directory in (layout.enforce / "fitness", layout.root / "tools")
            if directory.exists()
            for path in directory.rglob("*.py")
        )
    return None


def check_mechanisms(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V080 -- a named mechanism actually exists.

    Warning, not error: the corpus is allowed to name a mechanism before it is
    built, but never allowed to hide that it has not been. `ENFORCEMENT.md`
    reports the implemented fraction so the gap is tracked rather than assumed
    closed.
    """
    for doc in documents:
        for rule in doc.rules:
            for mechanism in rule.mechanisms:
                if mechanism_is_implemented(mechanism, layout) is False:
                    yield Finding(
                        code="V080",
                        severity=Severity.WARN,
                        path=_relpath(layout, doc),
                        line=rule.line,
                        message=f"{rule.rule_id}: mechanism `{mechanism}` is not implemented",
                        remediation="Build it under enforce/, or the rule is binding in name only.",
                    )


def check_graph(documents: Sequence[Document], layout: Layout) -> Iterator[Finding]:
    """V090-V094 -- the navigation graph is well formed and current.

    A dangling edge or an unreachable rule is not a cosmetic defect: it is a rule
    that exists and cannot be arrived at, which is the failure the graph was built
    to make impossible.
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
    """Parse every corpus file; unparsable files become V001 findings."""
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
    """Every check, over the whole corpus."""
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
    findings.extend(check_graph(documents, layout))
    findings.extend(check_grounding(documents, layout))
    findings.extend(check_learning(layout))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Validate the discipline corpus.")
    parser.add_argument("--json", action="store_true", help="emit findings as JSON")
    parser.add_argument("--root", type=Path, default=REPO_ROOT, help="repository root")
    args = parser.parse_args(argv)

    findings = run(Layout(args.root.resolve()))
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
