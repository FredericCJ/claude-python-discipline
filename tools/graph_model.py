"""The node and edge model shared by every tool that walks the discipline.

A directed, typed **multigraph**: any two nodes may be joined by any number of
edges, of any type, in either direction. Edges are first-class records rather
than adjacency embedded in nodes, which is what makes parallel edges expressible
and what lets an edge carry its own provenance.

Three edge origins, kept apart on purpose:

* ``derived``  -- computed from the corpus. Regenerated, never hand-written.
* ``declared`` -- authored in ``discipline/meta/edges.yaml`` for relations that
  cannot be inferred from the text.
* ``learned``  -- contributed by the learning database and overlaid at query
  time only, so the static layer keeps its byte-stability guarantee.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final


class NodeType(StrEnum):
    """What a node is. Node ids are unique across all types."""

    MODULE = "module"        # law/ARCH, fact/py-typing, ...
    RULE = "rule"            # ARCH-002
    MECHANISM = "mechanism"  # check:raise_from, auto:ruff:G004
    TERM = "term"            # a glossary entry
    TRIGGER = "trigger"      # a router keyword, a glob, an error signature
    DECISION = "decision"    # CONF-001, OPEN-001
    SOURCE = "source"        # an archived source document
    LAYER = "layer"          # domain | app | adapters | shell
    ARTIFACT = "artifact"    # enforce/pyproject.toml, a schema, an example
    LEARNING = "learning"    # L-0001, from the learning database


class EdgeType(StrEnum):
    """How two nodes relate. Each type answers a question an agent asks."""

    CONTAINS = "contains"            # module -> rule
    REQUIRES = "requires"            # module -> module: hold this first
    GROUNDS_ON = "grounds_on"        # module/rule -> fact: the verified basis
    DEFINES = "defines"              # module -> term
    CITES = "cites"                  # rule -> rule/module
    ENFORCED_BY = "enforced_by"      # rule -> mechanism: what do I run
    APPLIES_TO = "applies_to"        # rule -> layer/artifact
    SUPERSEDES = "supersedes"        # rule -> rule
    TENSIONS_WITH = "tensions_with"  # rule -> rule: what pulls against this
    PRECEDES = "precedes"            # rule -> rule: ordering
    DERIVES_FROM = "derives_from"    # rule/module -> source
    RESOLVED_BY = "resolved_by"      # rule/source -> decision: why it is so
    BLOCKED_BY = "blocked_by"        # rule -> decision: why not binding
    TRIGGERED_BY = "triggered_by"    # module/rule -> trigger: how to get in
    LEARNED_ABOUT = "learned_about"  # learning -> any
    CONTRADICTS = "contradicts"      # learning -> rule
    CO_ACTIVATED = "co_activated"    # rule -> rule, weighted by observation
    EVIDENCES = "evidences"          # learning -> learning


class Origin(StrEnum):
    DERIVED = "derived"
    DECLARED = "declared"
    LEARNED = "learned"


## Edge types an agent follows when expanding "what else do I need to read".
## Deliberately excludes provenance and entry edges, which explain rather than
## oblige, and excludes the learned layer, which is advisory.
READING_EXPANSION: Final[frozenset[EdgeType]] = frozenset({
    EdgeType.REQUIRES,
    EdgeType.GROUNDS_ON,
    EdgeType.CITES,
    EdgeType.TENSIONS_WITH,
})

## Edge types that carry normative weight, for the reachability guarantee.
NAVIGABLE: Final[frozenset[EdgeType]] = READING_EXPANSION | frozenset({
    EdgeType.CONTAINS,
    EdgeType.TRIGGERED_BY,
    EdgeType.APPLIES_TO,
    EdgeType.ENFORCED_BY,
})


@dataclass(frozen=True, slots=True)
class Node:
    """One addressable thing. `id` is unique across the whole graph."""

    id: str
    type: NodeType
    label: str
    path: str | None = None
    tokens: int = 0
    attrs: tuple[tuple[str, str], ...] = ()

    def attr(self, key: str) -> str | None:
        for name, value in self.attrs:
            if name == key:
                return value
        return None


@dataclass(frozen=True, slots=True)
class Edge:
    """One directed, typed relation. Parallel edges are expected, not exceptional."""

    type: EdgeType
    src: str
    dst: str
    origin: Origin = Origin.DERIVED
    weight: float = 1.0
    note: str | None = None

    @property
    def id(self) -> str:
        """Stable identity: type plus endpoints. Duplicates collapse; parallels do not."""
        return f"{self.src}--{self.type}-->{self.dst}"


@dataclass(slots=True)
class Graph:
    """A directed typed multigraph with adjacency indices built on demand."""

    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    _out: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    _in: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    _seen: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ build

    def add_node(self, node: Node) -> None:
        """Add a node. A later add with the same id wins, which lets the learned
        layer enrich a static node without duplicating it."""
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> bool:
        """Add an edge unless an identical one is already present.

        Identical means same type, endpoints *and* origin -- two edges of the
        same type from different origins are both kept, because the fact that a
        relation was both declared and observed is itself information.
        """
        key = f"{edge.id}#{edge.origin}"
        if key in self._seen:
            return False
        self._seen.add(key)
        self.edges.append(edge)
        self._out[edge.src].append(edge)
        self._in[edge.dst].append(edge)
        return True

    def merge(self, other: Graph) -> None:
        """Overlay another graph onto this one. Used for the learned layer."""
        for node in other.nodes.values():
            self.nodes.setdefault(node.id, node)
        for edge in other.edges:
            self.add_edge(edge)

    # ------------------------------------------------------------------ query

    def out_edges(self, node_id: str, types: Iterable[EdgeType] | None = None) -> list[Edge]:
        wanted = set(types) if types is not None else None
        return [e for e in self._out.get(node_id, ()) if wanted is None or e.type in wanted]

    def in_edges(self, node_id: str, types: Iterable[EdgeType] | None = None) -> list[Edge]:
        wanted = set(types) if types is not None else None
        return [e for e in self._in.get(node_id, ()) if wanted is None or e.type in wanted]

    def neighbors(
        self,
        node_id: str,
        types: Iterable[EdgeType] | None = None,
        *,
        undirected: bool = False,
    ) -> list[str]:
        """Neighbouring node ids, in stable order."""
        found = [e.dst for e in self.out_edges(node_id, types)]
        if undirected:
            found += [e.src for e in self.in_edges(node_id, types)]
        seen: dict[str, None] = {}
        for item in found:
            seen.setdefault(item, None)
        return list(seen)

    def of_type(self, node_type: NodeType) -> list[Node]:
        return sorted(
            (n for n in self.nodes.values() if n.type is node_type), key=lambda n: n.id
        )

    def expand(
        self,
        seeds: Sequence[str],
        *,
        types: Iterable[EdgeType] | None = None,
        depth: int = 2,
        undirected: bool = False,
    ) -> dict[str, int]:
        """Breadth-first closure from `seeds`, returning node id -> hop distance.

        Deterministic: the frontier is sorted at every level, so the same seeds
        always yield the same walk. An unreproducible expansion could not be
        calibrated or reviewed.
        """
        distance: dict[str, int] = {s: 0 for s in seeds if s in self.nodes}
        frontier = sorted(distance)
        for hop in range(1, depth + 1):
            following: list[str] = []
            for node_id in frontier:
                for neighbor in self.neighbors(node_id, types, undirected=undirected):
                    if neighbor not in distance:
                        distance[neighbor] = hop
                        following.append(neighbor)
            if not following:
                break
            frontier = sorted(set(following))
        return distance

    def shortest_path(
        self, src: str, dst: str, *, types: Iterable[EdgeType] | None = None
    ) -> list[Edge] | None:
        """One shortest edge path, or None. Ties break on sorted node order."""
        if src not in self.nodes or dst not in self.nodes:
            return None
        previous: dict[str, Edge] = {}
        visited = {src}
        frontier = [src]
        while frontier:
            following: list[str] = []
            for node_id in sorted(frontier):
                for edge in sorted(
                    self.out_edges(node_id, types), key=lambda e: (str(e.type), e.dst)
                ):
                    if edge.dst in visited:
                        continue
                    visited.add(edge.dst)
                    previous[edge.dst] = edge
                    if edge.dst == dst:
                        return _unwind(previous, src, dst)
                    following.append(edge.dst)
            frontier = following
        return None

    def unreachable_from(
        self,
        seeds: Sequence[str],
        node_type: NodeType,
        *,
        depth: int,
        types: Iterable[EdgeType] | None = None,
    ) -> list[str]:
        """Nodes of `node_type` not reached from `seeds` within `depth` hops.

        This is the mechanical measure of navigability: a rule an agent cannot
        arrive at from the kernel is a rule that exists but cannot be found.
        """
        reached = self.expand(seeds, types=types, depth=depth, undirected=True)
        return sorted(
            n.id for n in self.of_type(node_type) if n.id not in reached
        )

    def cycles_in(self, edge_type: EdgeType) -> list[list[str]]:
        """Every cycle over one edge type. `requires` must be acyclic or load
        order is undefined."""
        found: list[list[str]] = []
        colour: dict[str, int] = {}
        stack: list[str] = []

        def walk(node_id: str) -> None:
            colour[node_id] = 1
            stack.append(node_id)
            for edge in sorted(self.out_edges(node_id, [edge_type]), key=lambda e: e.dst):
                state = colour.get(edge.dst, 0)
                if state == 0:
                    walk(edge.dst)
                elif state == 1:
                    start = stack.index(edge.dst)
                    found.append([*stack[start:], edge.dst])
            stack.pop()
            colour[node_id] = 2

        for node_id in sorted(self.nodes):
            if colour.get(node_id, 0) == 0:
                walk(node_id)
        return found

    def dangling(self) -> list[Edge]:
        """Edges whose endpoints do not resolve to nodes."""
        return [e for e in self.edges if e.src not in self.nodes or e.dst not in self.nodes]

    def orphans(self, node_type: NodeType) -> list[str]:
        """Nodes of a type with no edges at all, in either direction."""
        return sorted(
            n.id
            for n in self.of_type(node_type)
            if not self._out.get(n.id) and not self._in.get(n.id)
        )

    # --------------------------------------------------------------- serialize

    def to_dict(self) -> dict[str, object]:
        """Deterministic serialization: nodes by id, edges by a stable sort key."""
        return {
            "nodes": [
                {
                    "id": n.id,
                    "type": str(n.type),
                    "label": n.label,
                    **({"path": n.path} if n.path else {}),
                    **({"tokens": n.tokens} if n.tokens else {}),
                    **({"attrs": dict(n.attrs)} if n.attrs else {}),
                }
                for n in sorted(self.nodes.values(), key=lambda n: (str(n.type), n.id))
            ],
            "edges": [
                {
                    "type": str(e.type),
                    "src": e.src,
                    "dst": e.dst,
                    "origin": str(e.origin),
                    **({"weight": e.weight} if e.weight != 1.0 else {}),
                    **({"note": e.note} if e.note else {}),
                }
                for e in sorted(
                    self.edges, key=lambda e: (str(e.type), e.src, e.dst, str(e.origin))
                )
            ],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> Graph:
        graph = cls()
        for raw in payload.get("nodes", []):  # type: ignore[union-attr]
            attrs = raw.get("attrs") or {}
            graph.add_node(
                Node(
                    id=str(raw["id"]),
                    type=NodeType(str(raw["type"])),
                    label=str(raw["label"]),
                    path=raw.get("path"),
                    tokens=int(raw.get("tokens", 0)),
                    attrs=tuple(sorted((str(k), str(v)) for k, v in attrs.items())),
                )
            )
        for raw in payload.get("edges", []):  # type: ignore[union-attr]
            graph.add_edge(
                Edge(
                    type=EdgeType(str(raw["type"])),
                    src=str(raw["src"]),
                    dst=str(raw["dst"]),
                    origin=Origin(str(raw.get("origin", "derived"))),
                    weight=float(raw.get("weight", 1.0)),
                    note=raw.get("note"),
                )
            )
        return graph

    def __len__(self) -> int:
        return len(self.nodes)


def _unwind(previous: dict[str, Edge], src: str, dst: str) -> list[Edge]:
    path: list[Edge] = []
    cursor = dst
    while cursor != src:
        edge = previous[cursor]
        path.append(edge)
        cursor = edge.src
    return list(reversed(path))


def iter_edge_types(names: Sequence[str]) -> Iterator[EdgeType]:
    """Parse edge-type names from a CLI, failing loudly on an unknown one."""
    for name in names:
        yield EdgeType(name)
