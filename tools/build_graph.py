"""Build `discipline/graph.json` from the corpus and the declared edge layer.

    python tools/build_graph.py [--check] [--root PATH]

Nodes and edges are computed from what the corpus already says -- front-matter,
rule headings, mechanism tags, the glossary, the decision ledgers, provenance --
plus `discipline/meta/edges.yaml` for the relations that cannot be inferred.

The output is byte-stable: same corpus, same bytes. `--check` writes nothing and
exits non-zero if the graph is stale, which is the form to run in CI.

Agents do not read this file. They call `tools/nav.py`, which loads it once and
answers a question. The graph is an accelerator; `INDEX.md` and the kernel router
remain a working fallback if it is absent.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, Final

import yaml

from discipline_core import (
    REPO_ROOT,
    Document,
    ParseError,
    count_tokens,
    parse_document,
)
from graph_model import Edge, EdgeType, Graph, Node, NodeType, Origin

if TYPE_CHECKING:
    from collections.abc import Sequence

## Recorded in the emitted JSON so a reader of graph.json knows what to re-run.
GENERATED_BANNER: Final = "tools/build_graph.py"

## A glossary entry heading; the optional trailing tag rides along in group 0.
_TERM = re.compile(r"^###\s+(?P<term>.+?)(?:\s+\[BARE-BANNED\])?\s*$", re.MULTILINE)
## A decision's own section heading, carrying the fuller of its two labels.
_DECISION_HEADING = re.compile(r"^###\s+(?P<id>(?:CONF|OPEN)-\d{3})\s*(?:·|\|)\s*(?P<label>.+?)\s*$", re.MULTILINE)
## A decision's summary-table row, for a ledger that lists an id before expanding it.
## Narrower than the heading pattern on purpose: only the conflict ledger has such a table.
_DECISION_ROW = re.compile(r"^\|\s*(?P<id>CONF-\d{3})\s*\|\s*(?P<label>[^|]+?)\s*\|", re.MULTILINE)
## A provenance row: the two-letter tag and the archived document it stands for.
_SOURCE_ROW = re.compile(r"^\|\s*`(?P<tag>[A-Z]{2})`\s+(?P<name>[^|]+?)\s*\|", re.MULTILINE)
## A linter code as it appears in the comment beside the setting that selects it.
_RUFF_CODE = re.compile(r"\b(?P<code>[A-Z]{1,4}\d{3,4})\b")
## The `name = "..."` line that titles one import-linter contract.
_CONTRACT_NAME = re.compile(r'^name\s*=\s*"(?P<name>[^"]+)"', re.MULTILINE)

## Base classes that make a module under `enforce/checks/` a mechanism. Two
## walkers exist: one over Python syntax, one over files this repository does
## not parse -- markdown dispatch records, the learning ledger.
_CHECK_BASES: Final = frozenset({"Check", "ModuleCheck", "TextCheck"})

## The architectural layers a rule may be scoped to, core first.
LAYERS: Final = ("domain", "app", "adapters", "shell", "ports")


def _rel(path: Path, root: Path) -> str:
    """Path relative to the corpus root, or absolute if it lies outside it.

    @param path the file to express
    @param root the root to express it against
    @return a POSIX path, so the graph reads the same on either platform
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()

# ------------------------------------------------------------------ derivation


def build(root: Path) -> tuple[Graph, list[str]]:
    """Assemble the whole static graph in one pass over the corpus.

    The derived layer is added before the declared one so that hand-authored
    edges can reference nodes the text produced. Nothing here validates
    endpoints: an edge naming something absent is left dangling on purpose, for
    the validator to report rather than for the build to drop in silence.

    @param root the repository root
    @return the graph, and one warning per thing that could not be derived
    """
    graph = Graph()
    warnings: list[str] = []
    documents = _load(root, warnings)

    _add_layers(graph)
    _add_modules_and_rules(graph, documents, root)
    _add_terms(graph, documents)
    _add_decisions(graph, root)
    _add_sources(graph, root)
    _add_mechanisms(graph, root)
    _add_declared(graph, root, warnings)
    return graph, warnings


def _load(root: Path, warnings: list[str]) -> list[Document]:
    """Parse every corpus document, recording failures instead of raising them.

    One malformed file must not cost the whole graph, so it is skipped and named.
    `INDEX.md` is generated from the same rules and would double-count them.

    @param root the repository root
    @param warnings accumulator, appended to once per unparsable file
    @return the documents that parsed, in path order
    """
    documents: list[Document] = []
    for path in sorted((root / "discipline").rglob("*.md")):
        if path.name == "INDEX.md":
            continue
        try:
            documents.append(parse_document(path))
        except ParseError as exc:
            warnings.append(f"unparsable {path.name}: {exc.reason}")
    return documents


def _add_layers(graph: Graph) -> None:
    """Seed the layer nodes, so `applies_to` edges have somewhere to land.

    They exist whether or not any rule claims them; an empty layer is a fact
    worth being able to observe.

    @param graph the graph under construction
    """
    for layer in LAYERS:
        graph.add_node(
            Node(id=f"layer:{layer}", type=NodeType.LAYER, label=layer)
        )


def _add_modules_and_rules(graph: Graph, documents: Sequence[Document], root: Path) -> None:
    """Add one node per module and per rule, with the containment edge between.

    A document with no `id` in its front-matter is not addressable and is left
    out entirely rather than given a synthesized one. Each node carries the path
    and the reading cost an agent needs to decide whether to open it -- for a
    module the count its front-matter declares, for a rule its statement measured
    here -- and a rule's path is anchored at the line its heading sits on, so a
    finding can be opened where it is reported.

    @param graph the graph under construction
    @param documents the parsed corpus
    @param root the repository root, for the paths recorded on nodes
    """
    for doc in documents:
        if not doc.doc_id:
            continue
        front = doc.front_matter
        graph.add_node(
            Node(
                id=doc.doc_id,
                type=NodeType.MODULE,
                label=str(front.get("title", doc.doc_id)),
                path=_rel(doc.path, root),
                tokens=int(front.get("tokens", 0) or 0),
                attrs=tuple(
                    sorted(
                        (k, str(front[k]))
                        for k in ("kind", "decay", "verified", "python")
                        if front.get(k) is not None
                    )
                ),
            )
        )
        _module_edges(graph, doc)
        for rule in doc.rules:
            graph.add_node(
                Node(
                    id=rule.rule_id,
                    type=NodeType.RULE,
                    label=rule.title,
                    path=f"{_rel(doc.path, root)}:{rule.line}",
                    tokens=count_tokens(rule.statement),
                    attrs=(("force", str(rule.force)), ("module", doc.doc_id)),
                )
            )
            graph.add_edge(Edge(EdgeType.CONTAINS, doc.doc_id, rule.rule_id))
            _rule_edges(graph, doc, rule)


def _module_edges(graph: Graph, doc: Document) -> None:
    """Add a module's front-matter relations, minting trigger nodes as it goes.

    A `load_when` keyword and an `applies_to` glob both become triggers because
    they answer the same question from opposite ends: they are how an agent
    reaches a module without already knowing its name.

    @param graph the graph under construction
    @param doc the module whose front-matter is being read
    """
    front = doc.front_matter
    for target in _as_list(front.get("requires")):
        graph.add_edge(Edge(EdgeType.REQUIRES, doc.doc_id, target))
    for target in _as_list(front.get("grounds_on")):
        graph.add_edge(Edge(EdgeType.GROUNDS_ON, doc.doc_id, target))
    for keyword in _as_list(front.get("load_when")):
        trigger = f"trigger:kw:{keyword.lower()}"
        graph.add_node(Node(id=trigger, type=NodeType.TRIGGER, label=keyword,
                            attrs=(("kind", "keyword"),)))
        graph.add_edge(Edge(EdgeType.TRIGGERED_BY, doc.doc_id, trigger))
    for glob in _as_list(front.get("applies_to")):
        trigger = f"trigger:glob:{glob}"
        graph.add_node(Node(id=trigger, type=NodeType.TRIGGER, label=glob,
                            attrs=(("kind", "glob"),)))
        graph.add_edge(Edge(EdgeType.TRIGGERED_BY, doc.doc_id, trigger))


def _rule_edges(graph: Graph, doc: Document, rule: object) -> None:
    """Add a rule's mechanism, citation, supersession and grounding edges.

    A `see` target keeps only the half before its anchor: an anchor addresses a
    section of a node, not a node of its own. A supersession edge runs from the
    replacement to the rule it replaced, so the rule still in force is always the
    source and the retired one the target; to ask "what binds instead of this",
    follow the edge backwards.

    @param graph the graph under construction
    @param doc the module that owns the rule, whose grounding the rule inherits
    @param rule the parsed rule; the signature admits any object, so the
        attributes read off it -- `rule_id`, `mechanisms`, `see`,
        `superseded_by` -- are the real contract
    """
    rule_id = rule.rule_id  # type: ignore[attr-defined]
    for mechanism in rule.mechanisms:  # type: ignore[attr-defined]
        node_id = f"mech:{mechanism}"
        graph.add_node(
            Node(id=node_id, type=NodeType.MECHANISM, label=mechanism,
                 attrs=(("family", mechanism.split(":", 1)[0]),))
        )
        graph.add_edge(Edge(EdgeType.ENFORCED_BY, rule_id, node_id))
    for target in rule.see:  # type: ignore[attr-defined]
        graph.add_edge(Edge(EdgeType.CITES, rule_id, target.split("#", 1)[0]))
    if rule.superseded_by:  # type: ignore[attr-defined]
        graph.add_edge(Edge(EdgeType.SUPERSEDES, rule.superseded_by, rule_id))  # type: ignore[attr-defined]
    # A rule inherits its module's factual grounding: the fact is what the rule
    # is satisfiable against, not merely what the file cites.
    for target in _as_list(doc.front_matter.get("grounds_on")):
        graph.add_edge(Edge(EdgeType.GROUNDS_ON, rule_id, target))


def _add_terms(graph: Graph, documents: Sequence[Document]) -> None:
    """Add one node per glossary entry, flagging those banned in bare form.

    Only `meta/GLOSSARY` is read; an H3 heading anywhere else is prose that
    happens to share the shape. Decision ids share it too and are excluded, since
    they are nodes of a different kind added elsewhere.

    @param graph the graph under construction
    @param documents the parsed corpus, of which at most one file is the glossary
    """
    for doc in documents:
        if doc.doc_id != "meta/GLOSSARY":
            continue
        for match in _TERM.finditer(doc.body):
            term = match.group("term").strip()
            if term.startswith(("CONF-", "OPEN-")):
                continue
            node_id = f"term:{term.lower()}"
            banned = "[BARE-BANNED]" in match.group(0)
            graph.add_node(
                Node(id=node_id, type=NodeType.TERM, label=term,
                     attrs=(("bare_banned", str(banned).lower()),))
            )
            graph.add_edge(Edge(EdgeType.DEFINES, doc.doc_id, node_id))


def _add_decisions(graph: Graph, root: Path) -> None:
    """Add a node per entry in the two decision ledgers.

    A decision may appear as a full section, as a summary-table row, or as both;
    the section's label wins, being the one written to be read. A missing ledger
    is not an error, only a graph that cannot answer why a rule reads as it does.

    @param graph the graph under construction
    @param root the repository root
    """
    for name in ("CONFLICTS", "OPEN"):
        path = root / "discipline" / "meta" / f"{name}.md"
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        found: dict[str, str] = {}
        for match in _DECISION_HEADING.finditer(text):
            found[match.group("id")] = match.group("label").strip()
        for match in _DECISION_ROW.finditer(text):
            found.setdefault(match.group("id"), match.group("label").strip())
        for decision_id, label in sorted(found.items()):
            graph.add_node(
                Node(id=decision_id, type=NodeType.DECISION, label=label,
                     path=_rel(path, root),
                     attrs=(("ledger", f"meta/{name}"),))
            )


def _add_sources(graph: Graph, root: Path) -> None:
    """Add a node per archived source document named in the provenance table.

    The nodes are added with no edges at all: `derives_from` is constructed
    nowhere in this build, so every source lands in the graph as an orphan even
    though `nav.py` queries that edge type. The provenance table records where
    material went per source *document*, not per rule, so nothing finer than a
    document-level edge could be derived from it anyway. A missing provenance
    file is not an error.

    @param graph the graph under construction
    @param root the repository root
    """
    path = root / "discipline" / "meta" / "PROVENANCE.md"
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    for match in _SOURCE_ROW.finditer(text):
        tag = match.group("tag")
        graph.add_node(
            Node(id=f"source:{tag}", type=NodeType.SOURCE,
                 label=match.group("name").strip(), attrs=(("tag", tag),))
        )


def _add_mechanisms(graph: Graph, root: Path) -> None:
    """Add the implemented checks, and the error signatures that lead back to rules.

    Error signatures are entry points: a tool's own diagnostic code or contract
    name is what an agent has in hand when something fails, so both are indexed
    as triggers. A ruff code reaches a rule only when the two are named in the
    same configuration comment; a comment carrying a code and no rule id still
    mints the trigger, which then stands with no edge into the corpus.

    @param graph the graph under construction
    @param root the repository root
    """
    enforce = root / "enforce"
    _add_check_modules(graph, enforce, root)
    _add_contract_triggers(graph, enforce / "importlinter.toml")
    _add_ruff_triggers(graph, enforce / "templates" / "pyproject.toml")
    _add_signal_triggers(graph, enforce / "signals.toml")


def _add_check_modules(graph: Graph, enforce: Path, root: Path) -> None:
    """Add one mechanism node per AST check that exists on disk.

    @param graph the graph under construction
    @param enforce the `enforce/` directory
    @param root the repository root, for the path recorded on each node
    """
    for check in sorted((enforce / "checks").glob("*.py")):
        if check.stem.startswith(("__", "test_")) or not _defines_a_check(check):
            continue
        node_id = f"mech:check:{check.stem}"
        graph.add_node(Node(id=node_id, type=NodeType.MECHANISM, label=f"check:{check.stem}",
                            path=_rel(check, root),
                            attrs=(("family", "check"), ("implemented", "true"))))


def _defines_a_check(path: Path) -> bool:
    """Whether a module under `enforce/checks/` implements a mechanism.

    Not every module there is a check. `project.py` parses the consuming
    project's declaration and implements nothing; treating it as a mechanism
    minted a `check:project` node no rule names, which `V094` then reported as
    the graph disagreeing with the corpus. Membership is decided by what a module
    defines rather than by where it sits, matching `checks/__main__.py`.

    Read from the syntax tree rather than by importing, because the graph builder
    must not execute the code it describes.

    @param path the module to inspect
    @return True when it defines a class deriving from `Check`
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, SyntaxError):
        return False
    return any(
        isinstance(node, ast.ClassDef)
        and any(isinstance(b, ast.Name) and b.id in _CHECK_BASES for b in node.bases)
        for node in ast.walk(tree)
    )


def _add_contract_triggers(graph: Graph, config: Path) -> None:
    """Index each import-linter contract name as an error an agent can arrive with.

    @param graph the graph under construction
    @param config the import-linter configuration, skipped when absent
    """
    if not config.exists():
        return
    for match in _CONTRACT_NAME.finditer(config.read_text(encoding="utf-8")):
        name = match.group("name")
        # The contract is named "ARCH-003 adapters are independent"; a failure
        # reports only the descriptive half, so that is what must match.
        signature = _RULE_ID_RE.sub("", name).strip() or name
        trigger = f"trigger:err:{signature}"
        graph.add_node(Node(id=trigger, type=NodeType.TRIGGER, label=signature,
                            attrs=(("kind", "error"), ("tool", "import-linter"),
                                   ("contract", name))))
        for rule_id in _RULE_IDS_IN(name):
            if rule_id in graph.nodes:
                graph.add_edge(Edge(EdgeType.TRIGGERED_BY, rule_id, trigger))


def _add_signal_triggers(graph: Graph, config: Path) -> None:
    """Index the error vocabulary an agent meets, as opposed to the one we emit.

    The other two trigger sources index this repository's own instruments: ruff
    codes and import-linter contract names. `tools/bench.py` measured what that
    leaves out -- a Python traceback, a mypy line and a pytest failure resolved to
    an entirely empty reading plan, and those are the three outputs an agent meets
    most. `enforce/signals.toml` is the vocabulary that closes it.

    An entry naming a rule the corpus does not carry mints the trigger anyway and
    leaves it unattached, the same way an unattributed ruff code does: the
    signature is still what an agent has in hand, whether or not anyone has said
    which rule it serves.

    @param graph the graph under construction
    @param config the signal table, skipped when absent
    """
    if not config.exists():
        return
    document = tomllib.loads(config.read_text(encoding="utf-8"))
    for entry in document.get("signal", []):
        signature = str(entry.get("match", "")).strip()
        if not signature:
            continue
        trigger = f"trigger:err:{signature}"
        graph.add_node(Node(id=trigger, type=NodeType.TRIGGER, label=signature,
                            attrs=(("kind", "error"),
                                   ("tool", str(entry.get("tool", "unknown"))))))
        for rule_id in entry.get("rules", []):
            if rule_id in graph.nodes:
                graph.add_edge(Edge(EdgeType.TRIGGERED_BY, rule_id, trigger))


def _add_ruff_triggers(graph: Graph, pyproject: Path) -> None:
    """Index each ruff code named in a configuration comment beside its rules.

    A comment carrying a code and no rule id still mints the trigger, which then
    stands with no edge into the corpus -- the code is still what an agent has in
    hand when ruff fails, whether or not anyone wrote down which rule it serves.

    @param graph the graph under construction
    @param pyproject the enforcement template, skipped when absent
    """
    if not pyproject.exists():
        return
    for line in pyproject.read_text(encoding="utf-8").splitlines():
        if "#" not in line:
            continue
        comment = line.split("#", 1)[1]
        codes = {m.group("code") for m in _RUFF_CODE.finditer(comment)}
        rules = set(_RULE_IDS_IN(comment))
        # Subtracting the ids is defensive only: a rule id carries a hyphen and a
        # ruff code cannot, so as the two patterns stand nothing matches both.
        for code in codes - rules:
            trigger = f"trigger:err:{code}"
            graph.add_node(Node(id=trigger, type=NodeType.TRIGGER, label=code,
                                attrs=(("kind", "error"), ("tool", "ruff"))))
            for rule_id in rules:
                if rule_id in graph.nodes:
                    graph.add_edge(Edge(EdgeType.TRIGGERED_BY, rule_id, trigger))


## A rule id wherever it is embedded in free text -- a contract title, a comment.
_RULE_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,7}-\d{3}\b")


def _RULE_IDS_IN(text: str) -> list[str]:  # ruff: ignore[invalid-function-name] - reads as a constant-like helper
    """Every rule id mentioned in a string, in the order they appear.

    @param text a contract title, a configuration comment, any prose
    @return the ids found, duplicates kept
    """
    return _RULE_ID_RE.findall(text)


def _add_declared(graph: Graph, root: Path, warnings: list[str]) -> None:
    """Overlay the relations no reading of the corpus text could produce.

    Every edge added here carries `Origin.DECLARED`, which is what keeps a human
    judgement distinguishable from a computed fact later; the artifact nodes it
    also mints carry no origin, since a node records no such thing. A tension is
    written both ways round, since neither of the two rules is the subject of it.
    An absent edge file leaves the graph correct but thinner, so it warns rather
    than fails.

    @param graph the graph under construction
    @param root the repository root
    @param warnings accumulator, appended to when the edge file is absent
    """
    path = root / "discipline" / "meta" / "edges.yaml"
    if not path.exists():
        warnings.append("no discipline/meta/edges.yaml; declared layer is empty")
        return
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    _add_declared_layers(graph, spec)
    _add_declared_decisions(graph, spec)
    _add_declared_orderings(graph, spec)
    _add_declared_artifacts(graph, spec)


def _add_declared_layers(graph: Graph, spec: dict[str, object]) -> None:
    """Edge each rule to the architectural layer it governs.

    Written layer-first in the source, because a reader authoring the file thinks
    in layers; the edge runs rule to layer, which is the direction a query walks.

    @param graph the graph under construction
    @param spec the parsed edge declaration
    """
    for layer, rules in (spec.get("applies_to") or {}).items():
        for rule_id in rules:
            graph.add_edge(
                Edge(EdgeType.APPLIES_TO, rule_id, f"layer:{layer}", Origin.DECLARED)
            )


def _add_declared_decisions(graph: Graph, spec: dict[str, object]) -> None:
    """Edge each rule to the decisions that shaped it or hold it up.

    `resolved_by` is what `nav.py why` answers from; `blocked_by` is what keeps an
    `[OPEN]` rule tied to the question in `meta/OPEN.md` that blocks it.

    @param graph the graph under construction
    @param spec the parsed edge declaration
    """
    for section, edge in (("resolved_by", EdgeType.RESOLVED_BY),
                          ("blocked_by", EdgeType.BLOCKED_BY)):
        for rule_id, decisions in (spec.get(section) or {}).items():
            for decision in decisions:
                graph.add_edge(Edge(edge, rule_id, decision, Origin.DECLARED))


def _add_declared_orderings(graph: Graph, spec: dict[str, object]) -> None:
    """Edge the relations that hold between two rules rather than rule and thing.

    A tension is written both ways round, since neither of the two rules is the
    subject of it; precedence is written one way, since one of them genuinely is.

    @param graph the graph under construction
    @param spec the parsed edge declaration
    """
    for entry in spec.get("tensions_with") or []:
        left, right = entry["pair"]
        note = " ".join((entry.get("note") or "").split()) or None
        graph.add_edge(Edge(EdgeType.TENSIONS_WITH, left, right, Origin.DECLARED, note=note))
        graph.add_edge(Edge(EdgeType.TENSIONS_WITH, right, left, Origin.DECLARED, note=note))

    for before, after in spec.get("precedes") or []:
        graph.add_edge(Edge(EdgeType.PRECEDES, before, after, Origin.DECLARED))


def _add_declared_artifacts(graph: Graph, spec: dict[str, object]) -> None:
    """Mint a node per configuration file a rule governs, and edge the rules to it.

    @param graph the graph under construction
    @param spec the parsed edge declaration
    """
    for artifact_path, entry in (spec.get("artifacts") or {}).items():
        node_id = f"artifact:{artifact_path}"
        graph.add_node(
            Node(id=node_id, type=NodeType.ARTIFACT, label=entry.get("label", artifact_path),
                 path=artifact_path)
        )
        for rule_id in entry.get("rules", []):
            graph.add_edge(Edge(EdgeType.APPLIES_TO, rule_id, node_id, Origin.DECLARED))


def _as_list(value: object) -> list[str]:
    """Normalize a front-matter field written as one string, a list, or not at all.

    Total by construction: any other shape -- a number, a mapping, a null --
    yields nothing rather than raising, because the schema, not the graph
    builder, is where a malformed corpus is meant to be caught. The cost is that
    a field written in an unexpected shape goes silently unedged.

    @param value the raw YAML value
    @return its entries, stringified; empty when the field is missing
    """
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


# ----------------------------------------------------------------------- main


def render(graph: Graph) -> str:
    """Serialize to the exact bytes `discipline/graph.json` is meant to hold.

    Byte-stability is the contract that makes `--check` meaningful: the same
    corpus must produce the same text, or staleness cannot be told apart from
    reordering. The sorting that guarantees it lives in `Graph.to_dict`.

    @param graph the assembled graph
    @return the JSON document, banner first and newline-terminated
    """
    payload = {"generated_by": GENERATED_BANNER, **graph.to_dict()}
    return json.dumps(payload, indent=1, ensure_ascii=False) + "\n"


def load_graph(root: Path = REPO_ROOT) -> Graph:
    """Read the built graph, deriving it in memory when none has been written.

    The fallback is what lets `nav.py` answer in a checkout where the build has
    never run, at the cost of parsing the whole corpus first. A graph read from
    disk is trusted as it stands: staleness is `main`'s `--check` to decide, not
    this function's.

    @param root the repository root
    @return the graph, from disk when it is present there
    """
    path = root / "discipline" / "graph.json"
    if not path.exists():
        graph, _ = build(root)
        return graph
    return Graph.from_dict(json.loads(path.read_text(encoding="utf-8")))


def main(argv: Sequence[str] | None = None) -> int:
    """Write the graph, or under `--check` report only whether it is stale.

    Warnings go to stderr and never change the exit status: a graph missing its
    declared layer is degraded, not wrong, and failing the build over it would
    make the accelerator harder to live with than to live without.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 on success, 1 when `--check` finds the written graph out of date
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Build the discipline navigation graph.")
    parser.add_argument("--check", action="store_true", help="report staleness, write nothing")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    args = parser.parse_args(argv)
    root = args.root.resolve()

    graph, warnings = build(root)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)

    target = root / "discipline" / "graph.json"
    text = render(graph)
    stale = not target.exists() or target.read_text(encoding="utf-8") != text

    if args.check:
        print("stale: discipline/graph.json" if stale else "up to date.")
        return 1 if stale else 0

    target.write_text(text, encoding="utf-8", newline="\n")
    counts: dict[str, int] = {}
    for node in graph.nodes.values():
        counts[str(node.type)] = counts.get(str(node.type), 0) + 1
    edge_counts: dict[str, int] = {}
    for edge in graph.edges:
        edge_counts[str(edge.type)] = edge_counts.get(str(edge.type), 0) + 1
    print(f"wrote discipline/graph.json: {len(graph.nodes)} nodes, {len(graph.edges)} edges")
    print("  nodes: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    print("  edges: " + ", ".join(f"{k}={v}" for k, v in sorted(edge_counts.items())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
