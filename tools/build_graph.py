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
import json
import re
import sys
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Final

import yaml

from discipline_core import (
    REPO_ROOT,
    Document,
    Force,
    Kind,
    ParseError,
    count_tokens,
    parse_document,
    prose_of,
)
from graph_model import Edge, EdgeType, Graph, Node, NodeType, Origin

GENERATED_BANNER: Final = "tools/build_graph.py"

_TERM = re.compile(r"^###\s+(?P<term>.+?)(?:\s+\[BARE-BANNED\])?\s*$", re.MULTILINE)
_DECISION_HEADING = re.compile(r"^###\s+(?P<id>(?:CONF|OPEN)-\d{3})\s*(?:·|\|)\s*(?P<label>.+?)\s*$", re.MULTILINE)
_DECISION_ROW = re.compile(r"^\|\s*(?P<id>CONF-\d{3})\s*\|\s*(?P<label>[^|]+?)\s*\|", re.MULTILINE)
_SOURCE_ROW = re.compile(r"^\|\s*`(?P<tag>[A-Z]{2})`\s+(?P<name>[^|]+?)\s*\|", re.MULTILINE)
_RUFF_CODE = re.compile(r"\b(?P<code>[A-Z]{1,4}\d{3,4})\b")
_CONTRACT_NAME = re.compile(r'^name\s*=\s*"(?P<name>[^"]+)"', re.MULTILINE)

LAYERS: Final = ("domain", "app", "adapters", "shell")


def _rel(path: Path, root: Path) -> str:
    """Path relative to the corpus root, or absolute if it lies outside it."""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()

# ------------------------------------------------------------------ derivation


def build(root: Path) -> tuple[Graph, list[str]]:
    """Assemble the static graph. Returns the graph and any build warnings."""
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
    for layer in LAYERS:
        graph.add_node(
            Node(id=f"layer:{layer}", type=NodeType.LAYER, label=layer)
        )


def _add_modules_and_rules(graph: Graph, documents: Sequence[Document], root: Path) -> None:
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
    """Error signatures are entry points: a tool's own rule code or contract name
    is what an agent has in hand when something fails."""
    enforce = root / "enforce"
    for check in sorted((enforce / "checks").glob("*.py")):
        if check.stem.startswith(("__", "test_")):
            continue
        node_id = f"mech:check:{check.stem}"
        graph.add_node(Node(id=node_id, type=NodeType.MECHANISM, label=f"check:{check.stem}",
                            path=_rel(check, root),
                            attrs=(("family", "check"), ("implemented", "true"))))

    config = enforce / "importlinter.toml"
    if config.exists():
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

    pyproject = enforce / "pyproject.toml"
    if pyproject.exists():
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            if "#" not in line:
                continue
            comment = line.split("#", 1)[1]
            codes = {m.group("code") for m in _RUFF_CODE.finditer(comment)}
            rules = set(_RULE_IDS_IN(comment))
            for code in codes - rules:
                trigger = f"trigger:err:{code}"
                graph.add_node(Node(id=trigger, type=NodeType.TRIGGER, label=code,
                                    attrs=(("kind", "error"), ("tool", "ruff"))))
                for rule_id in rules:
                    if rule_id in graph.nodes:
                        graph.add_edge(Edge(EdgeType.TRIGGERED_BY, rule_id, trigger))


_RULE_ID_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,7}-\d{3}\b")


def _RULE_IDS_IN(text: str) -> list[str]:  # noqa: N802 - reads as a constant-like helper
    return _RULE_ID_RE.findall(text)


def _add_declared(graph: Graph, root: Path, warnings: list[str]) -> None:
    path = root / "discipline" / "meta" / "edges.yaml"
    if not path.exists():
        warnings.append("no discipline/meta/edges.yaml; declared layer is empty")
        return
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    for layer, rules in (spec.get("applies_to") or {}).items():
        for rule_id in rules:
            graph.add_edge(
                Edge(EdgeType.APPLIES_TO, rule_id, f"layer:{layer}", Origin.DECLARED)
            )

    for entry in spec.get("tensions_with") or []:
        left, right = entry["pair"]
        note = " ".join((entry.get("note") or "").split()) or None
        graph.add_edge(Edge(EdgeType.TENSIONS_WITH, left, right, Origin.DECLARED, note=note))
        graph.add_edge(Edge(EdgeType.TENSIONS_WITH, right, left, Origin.DECLARED, note=note))

    for before, after in spec.get("precedes") or []:
        graph.add_edge(Edge(EdgeType.PRECEDES, before, after, Origin.DECLARED))

    for rule_id, decisions in (spec.get("resolved_by") or {}).items():
        for decision in decisions:
            graph.add_edge(Edge(EdgeType.RESOLVED_BY, rule_id, decision, Origin.DECLARED))

    for rule_id, decisions in (spec.get("blocked_by") or {}).items():
        for decision in decisions:
            graph.add_edge(Edge(EdgeType.BLOCKED_BY, rule_id, decision, Origin.DECLARED))

    for artifact_path, entry in (spec.get("artifacts") or {}).items():
        node_id = f"artifact:{artifact_path}"
        graph.add_node(
            Node(id=node_id, type=NodeType.ARTIFACT, label=entry.get("label", artifact_path),
                 path=artifact_path)
        )
        for rule_id in entry.get("rules", []):
            graph.add_edge(Edge(EdgeType.APPLIES_TO, rule_id, node_id, Origin.DECLARED))


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        return [value]
    return []


# ----------------------------------------------------------------------- main


def render(graph: Graph) -> str:
    payload = {"generated_by": GENERATED_BANNER, **graph.to_dict()}
    return json.dumps(payload, indent=1, ensure_ascii=False) + "\n"


def load_graph(root: Path = REPO_ROOT) -> Graph:
    """Read the built graph. Used by nav.py and the validator."""
    path = root / "discipline" / "graph.json"
    if not path.exists():
        graph, _ = build(root)
        return graph
    return Graph.from_dict(json.loads(path.read_text(encoding="utf-8")))


def main(argv: Sequence[str] | None = None) -> int:
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

    target.write_text(text, encoding="utf-8")
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
