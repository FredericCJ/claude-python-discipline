"""Walk the discipline. The graph is data; this is the interface.

    python tools/nav.py context --file src/pkg/adapters/fs.py --error "adapters-are-independent"
    python tools/nav.py rule ARCH-002
    python tools/nav.py neighbors ARCH-002 --type enforced_by --depth 2
    python tools/nav.py applies src/pkg/domain/outline.py
    python tools/nav.py why ARCH-002
    python tools/nav.py path ARCH-002 DIAG-005
    python tools/nav.py budget ARCH-002 law/TEST

Answers are small and self-contained: an agent runs one command and reads a few
hundred tokens, rather than loading the graph or a module speculatively. Every
walk is deterministic -- the same arguments always produce the same answer, so a
retrieval can be reviewed and calibrated.

`--json` on any subcommand emits the same answer as machine-readable data.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from build_graph import load_graph
from discipline_core import REPO_ROOT, count_tokens
from graph_model import READING_EXPANSION, Edge, EdgeType, Graph, Node, NodeType

## Path segments that name an architectural layer. A path containing one is
## governed by whatever rules apply to that layer.
LAYERS: Final = ("domain", "app", "adapters", "shell")
## Reading budget assumed when the caller names none -- about what an agent can
## absorb alongside the task that sent it here.
DEFAULT_BUDGET: Final = 6_000
## Tokenizer for keyword and signature matching.
_WORD = re.compile(r"[a-z0-9_]+")
## The shape of a citable rule id, for picking ids out of free-form error text.
_RULE_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,7}-\d{3}\b")


@dataclass(frozen=True, slots=True)
class Hit:
    """One node the query reached, with why and how far."""

    ## The node's graph id, such as `ARCH-002` or `law/TEST`.
    id: str
    ## The node's title, for a human reading the answer.
    label: str
    ## The node type as a bare string -- a `Hit` is answer data, not a graph
    ## handle, and callers select on it by name (`h.type == "rule"`).
    type: str
    ## Hops from the query to this node. 0 marks a seed -- something a channel
    ## reached on its own evidence -- not necessarily an id the caller typed.
    hops: int
    ## Why the walk arrived here, phrased to be printed unchanged.
    reason: str
    ## A rule's declared force; absent for nodes that carry no force.
    force: str | None = None
    ## Reading cost copied off the node, and zero means unmeasured rather than
    ## free: nothing here distinguishes a costless node from an uncosted one.
    tokens: int = 0


# --------------------------------------------------------------------- seeding


def seeds_for_file(graph: Graph, path: str) -> list[Hit]:
    """Rules governing a path: by layer, then by glob.

    A path under `tests/` or named `test_*` also picks up the whole testing law,
    because the testing rules bind on what a file is rather than where it sits.
    Layer and test matches are seeds at hop 0; a glob match is one hop out, so a
    directly governing rule always outranks a pattern that merely covers the file.

    @param graph the discipline graph
    @param path the file being worked on; it is matched in POSIX form and need
        not exist, since only its shape is read
    @return the rules and modules that govern it, nearest first then by id
    """
    found: dict[str, Hit] = {}
    parts = Path(path).as_posix().split("/")

    for layer in LAYERS:
        if layer not in parts:
            continue
        for edge in graph.in_edges(f"layer:{layer}", [EdgeType.APPLIES_TO]):
            node = graph.nodes.get(edge.src)
            if node is not None:
                found[node.id] = _hit(node, 0, f"governs {layer}/")

    if "tests" in parts or Path(path).name.startswith("test_"):
        for edge in graph.out_edges("law/TEST", [EdgeType.CONTAINS]):
            node = graph.nodes.get(edge.dst)
            if node is not None:
                found.setdefault(node.id, _hit(node, 0, "test file"))

    for node in graph.of_type(NodeType.TRIGGER):
        if node.attr("kind") != "glob":
            continue
        if not fnmatch.fnmatch(Path(path).as_posix(), node.label):
            continue
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            owner = graph.nodes.get(edge.src)
            if owner is not None and owner.type is NodeType.MODULE:
                found.setdefault(owner.id, _hit(owner, 1, f"matches {node.label}"))
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _normalize(text: str) -> set[str]:
    """Reduce text to the set of words it contains, separators flattened.

    `adapters-are-independent` and `adapters are independent` collapse to the
    same signature, so the punctuation an error happens to use cannot decide
    whether it matches a trigger.

    @param text prose, an identifier, or a tool's error phrase
    @return its lowercased words, deduplicated and unordered
    """
    return set(_WORD.findall(text.lower().replace("-", " ").replace("_", " ")))


def seeds_for_error(graph: Graph, text: str) -> list[Hit]:
    """Rules reachable from an error signature: a tool rule code or contract name.

    Three routes in, and a rule found by any of them is returned once: a trigger
    matched literally or word-for-word, a rule id quoted in the text, and the
    mechanism that produced the message. Only the last is a hop away, because
    knowing which checker complained is weaker evidence than the rule's own words.

    @param graph the discipline graph
    @param text whatever the failing tool printed
    @return the rules and modules the message points at, nearest first then by id
    """
    found: dict[str, Hit] = {}
    lowered = text.lower()
    words = _normalize(text)
    for node in graph.of_type(NodeType.TRIGGER):
        if node.attr("kind") != "error":
            continue
        signature = _normalize(node.label)
        # A code such as G004 matches literally; a phrase matches when all of its
        # words are present, so separator style does not decide the outcome.
        literal = node.label.lower() in lowered
        if not (literal or (len(signature) > 1 and signature <= words)):
            continue
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            owner = graph.nodes.get(edge.src)
            if owner is not None:
                found[owner.id] = _hit(owner, 0, f"error signature {node.label!r}")
    for rule_id in _RULE_ID.findall(text):
        node = graph.nodes.get(rule_id)
        if node is not None:
            found[node.id] = _hit(node, 0, "named in the error")
    for node in graph.of_type(NodeType.MECHANISM):
        stem = node.label.split(":")[-1]
        if len(stem) > 4 and stem.lower() in lowered:
            for edge in graph.in_edges(node.id, [EdgeType.ENFORCED_BY]):
                owner = graph.nodes.get(edge.src)
                if owner is not None:
                    found.setdefault(owner.id, _hit(owner, 1, f"checked by {node.label}"))
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def seeds_for_task(graph: Graph, text: str) -> list[Hit]:
    """Modules whose router keywords the task text mentions.

    A space in the keyword is what decides how it matches. Without one it is
    satisfied when every word it contains appears anywhere in the task, so order
    and punctuation are irrelevant; with one it must appear verbatim, which keeps
    a common pair of words from dragging in a module the task never meant.

    @param graph the discipline graph
    @param text the task description, in the author's own words
    @return the modules whose entry keywords it mentions, ordered by id
    """
    words = set(_WORD.findall(text.lower()))
    found: dict[str, Hit] = {}
    for node in graph.of_type(NodeType.TRIGGER):
        if node.attr("kind") != "keyword":
            continue
        keyword = node.label.lower()
        parts = set(_WORD.findall(keyword))
        matched = keyword in text.lower() if " " in keyword else parts <= words
        if not (matched and parts):
            continue
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            owner = graph.nodes.get(edge.src)
            if owner is not None:
                found.setdefault(owner.id, _hit(owner, 0, f"keyword {node.label!r}"))
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _hit(node: Node, hops: int, reason: str) -> Hit:
    """Record a reached node together with the evidence for reaching it.

    @param node the node the walk arrived at
    @param hops how far it stood from the seed
    @param reason the justification to show the reader
    @return the answer record, with force and cost copied off the node
    """
    return Hit(
        id=node.id,
        label=node.label,
        type=str(node.type),
        hops=hops,
        reason=reason,
        force=node.attr("force"),
        tokens=node.tokens,
    )


# -------------------------------------------------------------------- commands


def cmd_context(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """The reading plan: what to load, why, and what it costs.

    Seeds from every channel the caller supplied are merged at their shortest
    distance, expanded along the reading edges, then costed as modules rather
    than as rules -- a module is the unit an agent actually opens. The answer is
    a plan, not a truncation: what does not fit the budget is still named.

    @param graph the discipline graph
    @param args the parsed `context` arguments
    @return the seeds, the selected rules, the modules to read, both costs, and
        whatever the learned layer had to say about the situation
    """
    seeds: list[Hit] = []
    if args.file:
        seeds += seeds_for_file(graph, args.file)
    if args.error:
        seeds += seeds_for_error(graph, args.error)
    if args.task:
        seeds += seeds_for_task(graph, args.task)
    for rule_id in args.rule or []:
        node = graph.nodes.get(rule_id)
        if node is not None:
            seeds.append(_hit(node, 0, "named on the command line"))

    by_id: dict[str, Hit] = {}
    for hit in seeds:
        current = by_id.get(hit.id)
        if current is None or hit.hops < current.hops:
            by_id[hit.id] = hit

    reached = graph.expand(
        sorted(by_id), types=READING_EXPANSION, depth=args.depth, undirected=False
    )
    for node_id, hops in sorted(reached.items()):
        if node_id in by_id:
            continue
        node = graph.nodes.get(node_id)
        if node is None or node.type not in {NodeType.RULE, NodeType.MODULE}:
            continue
        by_id[node_id] = _hit(node, hops, f"{hops} hop(s) from a seed")

    rules = sorted(
        (h for h in by_id.values() if h.type == "rule"),
        key=lambda h: (h.hops, _force_rank(h.force), h.id),
    )
    modules = sorted(
        (h for h in by_id.values() if h.type == "module"), key=lambda h: (h.hops, h.id)
    )
    # Reading a module is how a rule is actually loaded, so cost the modules that
    # own the selected rules, not the rules themselves. Rank by relevance --
    # nearest hop first, then by how many selected rules the module owns -- so a
    # tight budget keeps what the task is about rather than whatever is smallest.
    relevance: dict[str, tuple[int, int]] = {}
    for hit in rules:
        owner = graph.nodes[hit.id].attr("module") if hit.id in graph.nodes else None
        if owner is None:
            continue
        hops, count = relevance.get(owner, (99, 0))
        relevance[owner] = (min(hops, hit.hops), count + 1)
    for hit in modules:
        hops, count = relevance.get(hit.id, (99, 0))
        relevance[hit.id] = (min(hops, hit.hops), count)

    ordered = sorted(
        relevance,
        key=lambda m: (relevance[m][0], -relevance[m][1], graph.nodes[m].tokens, m),
    )
    cost = sum(graph.nodes[m].tokens for m in ordered if m in graph.nodes)
    plan = _fit_budget(graph, ordered, args.budget)
    return {
        "seeds": [asdict(h) for h in sorted(by_id.values(), key=lambda h: (h.hops, h.id))[:20]],
        "rules": [asdict(h) for h in rules[: args.max_rules]],
        "rules_total": len(rules),
        "rules_shown": min(len(rules), args.max_rules),
        "read": plan,
        "tokens_if_all": cost,
        "tokens_planned": sum(p["tokens"] for p in plan if p["status"] == "read"),
        "learnings": _learnings_for(args, sorted(by_id)),
    }


def _learnings_for(args: argparse.Namespace, selected: Sequence[str]) -> list[str]:
    """What the learning database knows about this situation, if it has anything.

    Overlaid here rather than merged into the graph: the static layer is
    regenerated and byte-stable, the learned layer is weighted and refutable, and
    keeping them apart is what lets both guarantees hold. A missing or unbuilt
    database is not an error -- the plan is simply unannotated.

    @param args the parsed arguments, read defensively since not every
        subcommand offers the same channels
    @param selected the node ids the plan settled on; rule ids among them are
        used as retrieval keys
    @return one line per claim, or nothing at all when the database is absent,
        unreadable or empty on this situation
    """
    try:
        import learn
    except ImportError:
        return []
    store = learn.Store(Path(getattr(args, "root", REPO_ROOT)).resolve())
    if not store.ledger.exists():
        return []
    try:
        connection = learn.sync(store)
    except (learn.LearnError, OSError):
        return []
    try:
        found = learn.retrieve(
            store, connection,
            file=getattr(args, "file", None),
            error=getattr(args, "error", None),
            task=getattr(args, "task", None),
            rules=[r for r in selected if _RULE_ID.fullmatch(r)],
        )
    finally:
        connection.close()
    return [
        f"{c.id} [{c.status} {c.effective:.2f}] {c.claim} -> {c.action}"
        for c in found
    ]


def _force_rank(force: str | None) -> int:
    """Sort key that shows what binds before what merely advises.

    @param force the declared force, or None on a node that has none
    @return the rank, lower sorting first, with anything unrecognised last
    """
    return {"BINDING": 0, "OPEN": 1, "ADVISORY": 2}.get(force or "", 3)


def _fit_budget(graph: Graph, module_ids: Sequence[str], budget: int) -> list[dict[str, object]]:
    """Pack in the order given -- most relevant first -- and mark the overflow.

    Modules that do not fit are still listed, so an agent can see what it is
    choosing not to read rather than being handed a silently truncated plan.
    The first module is always taken, even when it alone exceeds the budget: an
    empty plan would answer nothing.

    @param graph the discipline graph
    @param module_ids the modules to pack, most relevant first
    @param budget the token ceiling the plan aims to stay under
    @return one entry per module the graph knows, each marked `read` or
        `deferred`, in the order it was offered; an id with no node is dropped
        rather than priced at zero
    """
    plan: list[dict[str, object]] = []
    spent = 0
    for module_id in module_ids:
        node = graph.nodes.get(module_id)
        if node is None:
            continue
        if plan and spent + node.tokens > budget:
            plan.append({"id": node.id, "tokens": node.tokens, "status": "deferred"})
            continue
        spent += node.tokens
        plan.append({"id": node.id, "tokens": node.tokens, "status": "read"})
    return plan


def cmd_rule(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """One node with everything it relates to, grouped by relation.

    Both directions are reported: what a rule cites is half the picture, and
    what cites it is the other half.

    @param graph the discipline graph
    @param args the parsed `rule` arguments, carrying the id to look up
    @return the node's identity and its relations, outgoing and incoming
    @throws SystemExit when the graph holds no node with that id
    """
    node = _require(graph, args.id)
    out: dict[str, list[str]] = {}
    for edge in graph.out_edges(node.id):
        out.setdefault(str(edge.type), []).append(_describe(graph, edge.dst, edge))
    incoming: dict[str, list[str]] = {}
    for edge in graph.in_edges(node.id):
        incoming.setdefault(str(edge.type), []).append(_describe(graph, edge.src, edge))
    return {
        "id": node.id,
        "label": node.label,
        "type": str(node.type),
        "force": node.attr("force"),
        "module": node.attr("module"),
        "path": node.path,
        "out": {k: sorted(v) for k, v in sorted(out.items())},
        "in": {k: sorted(v) for k, v in sorted(incoming.items())},
    }


def cmd_neighbors(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """What lies within a few hops, ordered by distance.

    @param graph the discipline graph
    @param args the parsed `neighbors` arguments: the start node, the edge types
        to follow, the depth, and whether to walk edges backwards as well
    @return the reached nodes with their hop distance, the start node excluded
    @throws SystemExit when the start node is unknown
    @throws ValueError when a requested edge type is not a relation that exists
    """
    _require(graph, args.id)
    types = [EdgeType(t) for t in args.type] if args.type else None
    reached = graph.expand([args.id], types=types, depth=args.depth, undirected=args.undirected)
    return {
        "from": args.id,
        "depth": args.depth,
        "types": args.type or "all",
        "nodes": [
            {"id": nid, "hops": hops, "label": graph.nodes[nid].label,
             "type": str(graph.nodes[nid].type)}
            for nid, hops in sorted(reached.items(), key=lambda kv: (kv[1], kv[0]))
            if nid != args.id
        ],
    }


def cmd_applies(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """What governs one file, with no expansion and no budgeting.

    The narrow question behind `context`, answered on its own for the case where
    an agent wants the obligations rather than a reading plan. The path need not
    exist; only its shape decides the answer.

    @param graph the discipline graph
    @param args the parsed `applies` arguments, carrying the path
    @return the path, the rules that bind it, and the modules that carry them
    """
    hits = seeds_for_file(graph, args.path)
    return {
        "path": args.path,
        "rules": [asdict(h) for h in hits if h.type == "rule"],
        "modules": [asdict(h) for h in hits if h.type == "module"],
    }


def cmd_why(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """The justification behind a rule, not its content.

    Only the provenance relations are followed: the decision that settled it,
    what keeps it from binding, the verified fact it stands on, what pulls
    against it, and the superseded source it came from. An agent that disagrees
    with a rule should be able to read the argument before arguing back.

    @param graph the discipline graph
    @param args the parsed `why` arguments, carrying the id to explain
    @return the rule with each provenance relation listed separately, empty
        where the rule has none of that kind
    @throws SystemExit when the graph holds no node with that id
    """
    node = _require(graph, args.id)
    return {
        "id": node.id,
        "label": node.label,
        "resolved_by": [_describe(graph, e.dst, e)
                        for e in graph.out_edges(node.id, [EdgeType.RESOLVED_BY])],
        "blocked_by": [_describe(graph, e.dst, e)
                       for e in graph.out_edges(node.id, [EdgeType.BLOCKED_BY])],
        "grounds_on": [_describe(graph, e.dst, e)
                       for e in graph.out_edges(node.id, [EdgeType.GROUNDS_ON])],
        "tensions_with": [_describe(graph, e.dst, e)
                          for e in graph.out_edges(node.id, [EdgeType.TENSIONS_WITH])],
        "derives_from": [_describe(graph, e.dst, e)
                         for e in graph.out_edges(node.id, [EdgeType.DERIVES_FROM])],
    }


def cmd_path(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """How two nodes connect, along edges or against them.

    When no forward route exists the reverse is searched, because a relation
    such as `supersedes` is authored one way round and the connection is what
    the question was about. Those steps are re-ordered to read from the
    requested start, while each step still reports its own true direction.

    @param graph the discipline graph
    @param args the parsed `path` arguments: the two endpoints
    @return whether a route was found and the edges it crosses, in order
    @throws SystemExit when either endpoint is unknown
    """
    _require(graph, args.src)
    _require(graph, args.dst)
    found = graph.shortest_path(args.src, args.dst)
    if found is None:
        found = graph.shortest_path(args.dst, args.src)
        if found is not None:
            found = list(reversed(found))
    return {
        "from": args.src,
        "to": args.dst,
        "found": found is not None,
        "steps": [
            {"type": str(e.type), "src": e.src, "dst": e.dst, "note": e.note}
            for e in (found or [])
        ],
    }


def cmd_budget(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """What a chosen reading set will cost before any of it is loaded.

    A rule is charged at the price of the module that contains it, since that is
    the file an agent opens. Two rules from one module therefore cost that module
    twice; the estimate is a ceiling, not a packing. An id the graph does not
    know is marked `unknown` at zero rather than aborting, so one typo does not
    cost the caller the rest of the answer.

    @param graph the discipline graph
    @param args the parsed `budget` arguments, carrying the ids to price
    @return one item per id, naming what is actually read, and the total
    """
    items: list[dict[str, object]] = []
    total = 0
    for node_id in args.ids:
        node = graph.nodes.get(node_id)
        if node is None:
            items.append({"id": node_id, "tokens": 0, "status": "unknown"})
            continue
        owner = node.attr("module") if node.type is NodeType.RULE else node.id
        target = graph.nodes.get(owner or node.id)
        tokens = target.tokens if target else 0
        items.append({"id": node_id, "reads": owner, "tokens": tokens})
        total += tokens
    return {"items": items, "total_tokens": total}


def cmd_stats(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """Graph shape, and the reachability guarantee as a number.

    The number that matters is how many rules are reachable from the modules the
    kernel's router can name: a rule no walk arrives at exists but cannot be
    found, which for an agent is the same as not existing.

    @param graph the discipline graph
    @param args the parsed `stats` arguments, carrying the reach depth to test
    @return the node and edge census, the reachable fraction, and the ids of any
        rules the walk never arrives at
    """
    unreachable = graph.unreachable_from(
        _kernel_seeds(graph), NodeType.RULE, depth=args.depth
    )
    total = len(graph.of_type(NodeType.RULE))
    nodes: dict[str, int] = {}
    for node in graph.nodes.values():
        nodes[str(node.type)] = nodes.get(str(node.type), 0) + 1
    edges: dict[str, int] = {}
    for edge in graph.edges:
        edges[str(edge.type)] = edges.get(str(edge.type), 0) + 1
    return {
        "nodes": dict(sorted(nodes.items())),
        "edges": dict(sorted(edges.items())),
        "rules_total": total,
        "rules_reachable": total - len(unreachable),
        "reach_depth": args.depth,
        "unreachable": unreachable,
    }


def _kernel_seeds(graph: Graph) -> list[str]:
    """The kernel's own starting points: every module the router can name.

    @param graph the discipline graph
    @return the module ids, sorted, as the seed set for a reachability measure
    """
    return sorted(n.id for n in graph.of_type(NodeType.MODULE))


def _require(graph: Graph, node_id: str) -> Node:
    """Resolve an id the caller asserted exists, or stop and say which one did not.

    A mistyped id must fail here rather than produce an empty but plausible
    answer that reads as "this rule relates to nothing".

    @param graph the discipline graph
    @param node_id the id to resolve
    @return the node it names
    @throws SystemExit naming the id, when the graph holds no such node
    """
    node = graph.nodes.get(node_id)
    if node is None:
        message = f"unknown node {node_id!r}"
        raise SystemExit(message)
    return node


def _describe(graph: Graph, node_id: str, edge: Edge) -> str:
    """Name one end of an edge in a line, qualified by whatever the edge records.

    @param graph the discipline graph
    @param node_id the endpoint being reported
    @param edge the relation it was reached through, whose note qualifies it
    @return the id with its title, degrading to the bare id when the endpoint
        does not resolve
    """
    node = graph.nodes.get(node_id)
    label = f"{node_id} - {node.label}" if node else node_id
    return f"{label} [{edge.note}]" if edge.note else label


# ---------------------------------------------------------------------- output


def render(command: str, payload: dict[str, object]) -> str:
    """Lay an answer out for a terminal, in the shape that command deserves.

    A command with no layout of its own falls back to indented JSON, so a new
    subcommand prints something legible before anyone writes its renderer.

    @param command which subcommand produced the payload
    @param payload that command's answer, unmodified
    @return the text to print, with no trailing newline
    """
    lines: list[str] = []
    if command == "context":
        rules = payload["rules"]  # type: ignore[index]
        shown, total = payload["rules_shown"], payload["rules_total"]
        suffix = f" of {total} - raise --max-rules to see the rest" if shown < total else ""
        lines.append(f"RULES ({shown}{suffix})")
        for rule in rules:  # type: ignore[union-attr]
            force = (rule["force"] or "")[:8]
            lines.append(f"  {rule['id']:<10} {force:<9} {rule['label']}")
            lines.append(f"  {'':<10} {'':<9} ~ {rule['reason']}")
        lines.append("")
        lines.append("READ")
        for item in payload["read"]:  # type: ignore[union-attr]
            mark = " " if item["status"] == "read" else "!"
            lines.append(f" {mark} {item['id']:<22} {item['tokens']:>6} tok  {item['status']}")
        lines.append("")
        lines.append(
            f"BUDGET  planned {payload['tokens_planned']} tok"
            f"  (all candidates {payload['tokens_if_all']} tok)"
        )
        if payload.get("learnings"):
            lines.append("")
            lines.append("LEARNED")
            for item in payload["learnings"]:  # type: ignore[union-attr]
                lines.append(f"  {item}")
    elif command == "applies":
        rules = payload["rules"]  # type: ignore[index]
        lines.append(f"{payload['path']}  ({len(rules)} rules)")
        for rule in rules:  # type: ignore[union-attr]
            lines.append(
                f"  {rule['id']:<10} {(rule['force'] or ''):<9} {rule['label']}"
                f"   ~ {rule['reason']}"
            )
        for module in payload["modules"]:  # type: ignore[union-attr]
            lines.append(f"  {module['id']:<20} ~ {module['reason']}")
    elif command in {"rule", "why"}:
        lines.append(f"{payload['id']} - {payload.get('label', '')}")
        for key, value in payload.items():
            if key in {"id", "label", "type"} or not value:
                continue
            if isinstance(value, dict):
                for edge_type, targets in value.items():
                    lines.append(f"  {edge_type}:")
                    lines += [f"    {t}" for t in targets]
            elif isinstance(value, list):
                lines.append(f"  {key}:")
                lines += [f"    {t}" for t in value]
            else:
                lines.append(f"  {key}: {value}")
    elif command == "stats":
        lines.append("NODES  " + ", ".join(f"{k}={v}" for k, v in payload["nodes"].items()))  # type: ignore[union-attr]
        lines.append("EDGES  " + ", ".join(f"{k}={v}" for k, v in payload["edges"].items()))  # type: ignore[union-attr]
        lines.append(
            f"REACH  {payload['rules_reachable']}/{payload['rules_total']} rules "
            f"within {payload['reach_depth']} hops"
        )
        if payload["unreachable"]:
            lines.append("  unreachable: " + ", ".join(payload["unreachable"]))  # type: ignore[union-attr]
    else:
        lines.append(json.dumps(payload, indent=1, ensure_ascii=False))
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    """Assemble the command grammar, one subparser per question an agent asks.

    @return a parser that refuses to run without a subcommand, since there is no
        sensible default walk
    """
    parser = argparse.ArgumentParser(description="Walk the discipline graph.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    ctx = sub.add_parser("context", help="the reading plan for a situation")
    ctx.add_argument("--file")
    ctx.add_argument("--error")
    ctx.add_argument("--task")
    ctx.add_argument("--rule", action="append")
    ctx.add_argument("--depth", type=int, default=1)
    ctx.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ctx.add_argument("--max-rules", type=int, default=20)

    rule = sub.add_parser("rule", help="one rule and its neighbourhood")
    rule.add_argument("id")

    nb = sub.add_parser("neighbors", help="breadth-first walk from a node")
    nb.add_argument("id")
    nb.add_argument("--type", action="append")
    nb.add_argument("--depth", type=int, default=1)
    nb.add_argument("--undirected", action="store_true")

    ap = sub.add_parser("applies", help="rules governing a file")
    ap.add_argument("path")

    why = sub.add_parser("why", help="why a rule has the shape it has")
    why.add_argument("id")

    pth = sub.add_parser("path", help="how two nodes connect")
    pth.add_argument("src")
    pth.add_argument("dst")

    bud = sub.add_parser("budget", help="token cost of a reading set")
    bud.add_argument("ids", nargs="+")

    st = sub.add_parser("stats", help="graph shape and reachability")
    st.add_argument("--depth", type=int, default=3)
    return parser


## Subcommand name to the handler that answers it. The keys must be exactly the
## strings the parser accepts: a subcommand the parser gained but this map lacks
## raises KeyError at dispatch, and one added here alone is simply unreachable.
COMMANDS = {
    "context": cmd_context,
    "rule": cmd_rule,
    "neighbors": cmd_neighbors,
    "applies": cmd_applies,
    "why": cmd_why,
    "path": cmd_path,
    "budget": cmd_budget,
    "stats": cmd_stats,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Answer one question from the command line and print it.

    @param argv the arguments, defaulting to the process's own
    @return 0; a failed lookup leaves through SystemExit with its own message
    """
    # The console encoding is not ours to choose, and a navigation tool that
    # dies on one is worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args(argv)
    graph = load_graph(args.root.resolve())
    payload = COMMANDS[args.command](graph, args)
    print(json.dumps(payload, indent=1, ensure_ascii=False) if args.json
          else render(args.command, payload))
    return 0


if __name__ == "__main__":
    sys.exit(main())
