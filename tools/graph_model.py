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
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Sequence


class NodeType(StrEnum):
    """What a node is.

    Ids are unique across every type, so an id alone names a node and no query
    ever has to say which kind it expected.
    """

    ## A discipline file: the unit an agent opens and pays reading tokens for.
    MODULE = "module"        # law/ARCH, fact/py-typing, ...
    ## One numbered obligation. The citable unit, and what reachability is measured over.
    RULE = "rule"            # ARCH-002
    ## Something runnable that decides a rule, so a claim of compliance can be tested.
    MECHANISM = "mechanism"  # check:raise_from, auto:ruff:G004
    ## A defined word. Exists so one term keeps one meaning across the corpus.
    TERM = "term"            # a glossary entry
    ## An entry condition: what an agent notices that should send it to a module.
    TRIGGER = "trigger"      # a router keyword, a glob, an error signature
    ## A settled or still-open judgement that explains, or suspends, an obligation.
    DECISION = "decision"    # CONF-001, OPEN-001
    ## A superseded document, kept only so material can be traced back to it.
    SOURCE = "source"        # an archived source document
    ## One architectural tier, so a rule can say where it bites.
    LAYER = "layer"          # domain | app | adapters | shell
    ## A concrete file the corpus obliges or ships, as opposed to prose about one.
    ARTIFACT = "artifact"    # enforce/templates/pyproject.toml, a schema, an example
    ## An observation from practice. Advisory: it never enters the static graph.
    LEARNING = "learning"    # L-0001, from the learning database


class EdgeType(StrEnum):
    """How two nodes relate.

    Each type exists because some agent question needs exactly it; the set is
    deliberately closed, since an untyped relation cannot be reasoned over.
    """

    ## Ownership. The only relation by which a rule becomes findable at all.
    CONTAINS = "contains"            # module -> rule
    ## Load order: the target must already be held. Must stay acyclic.
    REQUIRES = "requires"            # module -> module: hold this first
    ## The verified basis a normative claim rests on, so it can be re-checked.
    GROUNDS_ON = "grounds_on"        # module/rule -> fact: the verified basis
    ## Which module owns a word's meaning, so the definition has one home.
    DEFINES = "defines"              # module -> term
    ## A plain reference. Weaker than requires: it implies no reading order.
    CITES = "cites"                  # rule -> rule/module
    ## What to run to decide the rule. Its absence is what "unenforced" means.
    ENFORCED_BY = "enforced_by"      # rule -> mechanism: what do I run
    ## Scope: where the rule bites, so it is not applied to the wrong tier.
    APPLIES_TO = "applies_to"        # rule -> layer/artifact
    ## Replacement. The target survives for provenance but no longer binds.
    SUPERSEDES = "supersedes"        # rule -> rule
    ## Conflict of obligations. An agent shown one must be shown the other.
    TENSIONS_WITH = "tensions_with"  # rule -> rule: what pulls against this
    ## Sequencing between rules that are both binding but not simultaneous.
    PRECEDES = "precedes"            # rule -> rule: ordering
    ## Where the material came from, back into the superseded documents.
    DERIVES_FROM = "derives_from"    # rule/module -> source
    ## The judgement that settled the wording; why it reads as it does.
    RESOLVED_BY = "resolved_by"      # rule/source -> decision: why it is so
    ## An open question that suspends the rule until it is answered.
    BLOCKED_BY = "blocked_by"        # rule -> decision: why not binding
    ## The entry condition that should make an agent open this.
    TRIGGERED_BY = "triggered_by"    # module/rule -> trigger: how to get in
    ## What an observation is about. Learned layer only, never persisted here.
    LEARNED_ABOUT = "learned_about"  # learning -> any
    ## Evidence that a rule does not survive contact with practice.
    CONTRADICTS = "contradicts"      # learning -> rule
    ## Observed together often enough to be worth loading together; weight counts it.
    CO_ACTIVATED = "co_activated"    # rule -> rule, weighted by observation
    ## One observation supporting another, so confidence can accumulate.
    EVIDENCES = "evidences"          # learning -> learning


class Origin(StrEnum):
    """Where an edge came from, which decides who is allowed to rewrite it.

    Kept on the edge rather than in separate graphs so that one relation
    asserted from two origins stays visible as two records.
    """

    ## Computed from the corpus and regenerated wholesale; a hand edit is lost.
    DERIVED = "derived"
    ## Authored by a human because no text implies it; regeneration must preserve it.
    DECLARED = "declared"
    ## Overlaid at query time by the learning database, so the static layer stays byte-stable.
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
    """One addressable thing in the corpus.

    Frozen, because a node is a fact about the corpus at build time; anything
    that varies belongs on an edge or in the learned overlay.
    """

    ## Unique across the whole graph, whatever the type. Every edge names nodes by this.
    id: str
    ## What `of_type` and the reachability checks select on, and what decides
    ## which of the fields below carry anything: a layer has no file, no cost.
    type: NodeType
    ## Human wording, and for trigger and mechanism nodes the matched text itself:
    ## `nav` fnmatches a glob trigger, word-matches an error trigger, and splits a
    ## mechanism on `:`. Changing one is a behaviour change, not a rename.
    label: str
    ## The backing file, repository-relative, with `:line` appended for a rule.
    ## None for what no file backs on its own -- layers, triggers, terms, mechanisms.
    path: str | None = None
    ## Measured reading cost, so an expansion can be budgeted before anything is opened.
    ## Zero means unmeasured, not free.
    tokens: int = 0
    ## Everything else, sorted key/value pairs. A tuple so the node stays hashable.
    attrs: tuple[tuple[str, str], ...] = ()

    def attr(self, key: str) -> str | None:
        """Look up one extra attribute, treating absence as a normal answer.

        @param key the attribute name
        @return the stored value, or None when this node carries no such attribute
        """
        # Each pair is one unique metadata key and its string value in authored order.
        for name, value in self.attrs:
            # Compare exact attribute keys while preserving authored tuple order.
            if name == key:
                # Expose the first matching metadata value because keys are contractually unique.
                return value
        # Absence is represented explicitly rather than by an invented empty value.
        return None


@dataclass(frozen=True, slots=True)
class Edge:
    """One directed, typed relation, carrying its own provenance.

    A record rather than adjacency inside a node, which is what makes parallel
    edges between the same pair expressible at all.
    """

    ## Which relation is being asserted.
    type: EdgeType
    ## The node the relation runs from. Not required to exist; `Graph.dangling` finds those.
    src: str
    ## The node it runs to, under the same no-existence-check rule as `src`.
    dst: str
    ## Who asserted it, and therefore whether a rebuild may overwrite it.
    origin: Origin = Origin.DERIVED
    ## Strength, meaningful only for observation-counted types such as `co_activated`.
    ## The default means unweighted and is omitted from serialization.
    weight: float = 1.0
    ## Free text for a declared edge, saying why a human asserted what no text
    ## implies. Serialized only when set, and shown by `nav` beside the endpoint
    ## it qualifies, so it is read by people and never matched on.
    note: str | None = None

    @property
    def id(self) -> str:
        """Identity for de-duplication: the type and the two endpoints.

        Deliberately excludes the origin, so the same relation from two origins
        shares an id; `Graph.add_edge` appends the origin when it de-duplicates.

        @return `src--type-->dst`, equal for two edges exactly when they assert
            the same relation
        """
        # Origin is deliberately excluded so duplicate assertions share one relation identity.
        return f"{self.src}--{self.type}-->{self.dst}"


@dataclass(slots=True)
class Graph:
    """A directed typed multigraph, with adjacency maintained as edges arrive.

    Not a general graph library: it holds only the queries the discipline tools
    ask, and every one of them is ordered, because an answer that varied between
    runs could not be reviewed or used as a gate.
    """

    ## Keyed by node id. A second add under the same id replaces the first.
    ## Treat nodes as mapping elements whose keys identify fields and values carry their
    ## content; key order is deliberately unused.
    nodes: dict[str, Node] = field(default_factory=dict)
    ## In arrival order, which is builder order; `to_dict` sorts instead of trusting it.
    ## Each element is one directed typed edge; builder arrival order is preserved until
    ## serialization imposes its stable sort.
    edges: list[Edge] = field(default_factory=list)
    ## Outgoing adjacency, kept in step with `edges` by `add_edge`.
    ## Treat  out as mapping elements whose keys identify fields and values carry their content;
    ## key order is deliberately unused.
    _out: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    ## Incoming adjacency, the mirror of `_out`.
    ## Treat  in as mapping elements whose keys identify fields and values carry their content;
    ## key order is deliberately unused.
    _in: dict[str, list[Edge]] = field(default_factory=lambda: defaultdict(list))
    ## Edge identity plus origin, the set that makes `add_edge` idempotent.
    ## Collect unique  seen element values; their order is deliberately unordered.
    _seen: set[str] = field(default_factory=set)

    # ------------------------------------------------------------------ build

    def add_node(self, node: Node) -> None:
        """Register a node, last write winning.

        Replacement rather than rejection is what lets the learned layer enrich
        a node the static build already made, instead of duplicating it.

        @param node the node to hold under its own id

        @par Effects
        May mutate caller-visible or process-local state in implementation order.
        """
        # Replace the node at its stable identity while retaining insertion ordering semantics.
        self.nodes[node.id] = node

    def add_edge(self, edge: Edge) -> bool:
        """Add an edge unless an identical one is already present.

        Identical means same type, endpoints *and* origin -- two edges of the
        same type from different origins are both kept, because the fact that a
        relation was both declared and observed is itself information.

        @param edge the relation to record; its endpoints need not exist yet
        @return True when it was stored, False when it was already present
        """
        # Include origin in edge identity so inferred and declared evidence remain distinguishable.
        key = f"{edge.id}#{edge.origin}"
        if key in self._seen:
            # Preserve the first edge record and report that this origin-specific duplicate lost.
            return False
        self._seen.add(key)
        self.edges.append(edge)
        self._out[edge.src].append(edge)
        self._in[edge.dst].append(edge)
        return True

    def merge(self, other: Graph) -> None:
        """Overlay another graph onto this one, this graph winning on conflict.

        Asymmetric on purpose: a node already here keeps its definition, while
        edges accumulate. That is what makes the learned overlay additive and
        unable to rewrite what the corpus states.

        @param other the graph to fold in; it is left untouched
        """
        # Merge nodes without replacing metadata already owned by this graph.
        for node in other.nodes.values():
            self.nodes.setdefault(node.id, node)
        # Route incoming edges through normal deduplication and adjacency indexing.
        for edge in other.edges:
            self.add_edge(edge)

    # ------------------------------------------------------------------ query

    def out_edges(self, node_id: str, types: Iterable[EdgeType] | None = None) -> list[Edge]:
        """Relations leaving a node, in the order they were added.

        @param node_id the node to look from; an unknown id yields nothing rather than raising
        @param types the relation types to keep, or None to keep every type
        @return a list built for this call, so sorting or trimming it cannot
            disturb the adjacency index behind it
        """
        # Normalize an optional type filter to unordered membership while preserving edge order.
        wanted = set(types) if types is not None else None
        return [e for e in self._out.get(node_id, ()) if wanted is None or e.type in wanted]

    def in_edges(self, node_id: str, types: Iterable[EdgeType] | None = None) -> list[Edge]:
        """Relations arriving at a node, which is how "who depends on this" is asked.

        @param node_id the node to look at; an unknown id yields nothing rather than raising
        @param types the relation types to keep, or None to keep every type
        @return the matching edges, in the order they were added
        """
        # Normalize an optional type filter to unordered membership while preserving edge order.
        wanted = set(types) if types is not None else None
        return [e for e in self._in.get(node_id, ()) if wanted is None or e.type in wanted]

    def neighbors(
        self,
        node_id: str,
        types: Iterable[EdgeType] | None = None,
        *,
        undirected: bool = False,
    ) -> list[str]:
        """Adjacent node ids, each reported once, outgoing before incoming.

        @param node_id the node to look from
        @param types the relation types to follow, or None to follow every type
        @param undirected also follow relations arriving at the node, not only those leaving
            True enables undirected; false selects its disabled alternative.
        @return the ids alone; parallel relations between the same pair collapse
            to one entry, so this counts neighbours and never edges
        """
        # Each found element is one adjacent destination node id; outgoing edge order is
        # preserved before optional reverse neighbors are appended.
        found = [e.dst for e in self.out_edges(node_id, types)]
        if undirected:
            # Include incoming sources when the caller requests an undirected neighborhood.
            found += [e.src for e in self.in_edges(node_id, types)]
        # Deduplicate neighbor identities in first-edge order; each key represents one node ID.
        seen: dict[str, None] = {}
        for item in found:
            seen.setdefault(item, None)
        return list(seen)

    def of_type(self, node_type: NodeType) -> list[Node]:
        """Every node of one kind, sorted by id so two runs list them alike.

        @param node_type the kind to collect, compared by identity: a plain
            string equal to the value matches nothing and reports nothing
        @return the matching nodes; every call rescans the whole node table, so
            hoist it out of a loop rather than calling it per candidate
        """
        # Each result is a node of the exact enum type; identifier order stabilizes callers.
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

        @param seeds the starting ids; any the graph does not hold are dropped silently
            Each element is one starting node id; caller order is preserved
            before stable frontier sorting.
        @param types the relation types to follow, or None to follow every type
        @param depth how many hops out to go; the walk stops early once nothing new appears
        @param undirected follow relations in both directions
            True enables undirected; false selects its disabled alternative.
        @return every reached id mapped to its hop count, the seeds at zero
        """
        # Seed each existing start node at distance zero; mapping order follows caller seed order.
        distance: dict[str, int] = {s: 0 for s in seeds if s in self.nodes}
        frontier = sorted(distance)
        # Advance breadth-first one hop at a time so the first recorded distance is minimal.
        for hop in range(1, depth + 1):
            # Each following element is one next-hop node id discovered at this depth; frontier
            # then adjacency order is preserved before deduplication.
            following: list[str] = []
            for node_id in frontier:
                # Expand neighbors in graph-defined stable order from the current frontier node.
                for neighbor in self.neighbors(node_id, types, undirected=undirected):
                    # Admit only first discovery so later, longer routes cannot replace distance.
                    if neighbor not in distance:
                        # First discovery proves and records this node's shortest hop count.
                        distance[neighbor] = hop
                        following.append(neighbor)
            if not following:
                # End breadth expansion when the current depth reaches no new nodes.
                break
            frontier = sorted(set(following))
        return distance

    def shortest_path(
        self, src: str, dst: str, *, types: Iterable[EdgeType] | None = None
    ) -> list[Edge] | None:
        """One shortest path, following relations only in their own direction.

        Ties break on sorted node order, so the path shown to a reader is the
        same one every time even where several are equally short.

        @param src the id to start from
        @param dst the id to reach
        @param types the relation types the path may use, or None to allow every type
        @return the edges in travel order, or None when no path exists -- which
            includes `src == dst`, treated as unreachable rather than as an
            empty path, and either endpoint being absent from the graph
        """
        # Refuse path search when either endpoint is absent from the graph's node universe.
        if src not in self.nodes or dst not in self.nodes:
            # Missing endpoints have no meaningful edge path.
            return None
        # Map each discovered node to its incoming edge in breadth-first discovery order.
        previous: dict[str, Edge] = {}
        # Collect unique visited element values; their order is deliberately unordered.
        visited = {src}
        # Each frontier element is one node id at the current breadth-first depth; discovery
        # order is preserved until the next lexical sort.
        frontier = [src]
        # Expand the breadth-first frontier until no newly reachable node remains.
        while frontier:
            # Each following element is one newly reached node id for the next breadth-first
            # depth; current frontier and edge order are preserved.
            following: list[str] = []
            for node_id in sorted(frontier):
                # Examine outgoing edges in type/destination order for deterministic parent choice.
                for edge in sorted(
                    self.out_edges(node_id, types), key=lambda e: (str(e.type), e.dst)
                ):
                    # Exclude already reached destinations before mutating frontier or parent state.
                    if edge.dst in visited:
                        # Skip previously reached destinations to preserve shortest-path parents.
                        continue
                    visited.add(edge.dst)
                    # Bind the first incoming edge as this destination's shortest-path predecessor.
                    previous[edge.dst] = edge
                    # Stop at the first breadth-first encounter of the requested destination.
                    if edge.dst == dst:
                        # Reconstruct when breadth-first search first reaches the target.
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

        Direction is not honoured -- the walk is always undirected, because a
        reader who lands on a rule has found it whichever way the link was drawn.

        @param seeds the entry points an agent really starts from
            Each element is one starting node id; caller order is preserved
            before stable reachability expansion.
        @param node_type the kind of node whose findability is being measured
        @param depth the hop budget, standing in for how far an agent will follow links
        @param types the relation types an agent is assumed to follow, or None for every type
        @return the ids that were missed, sorted; empty means the kind is fully navigable
        """
        # Expand undirected reachability before subtracting it from the requested node class.
        reached = self.expand(seeds, types=types, depth=depth, undirected=True)
        return sorted(
            n.id for n in self.of_type(node_type) if n.id not in reached
        )

    def cycles_in(self, edge_type: EdgeType) -> list[list[str]]:
        """Cycles over one relation type, one per back edge of a depth-first walk.

        A decision procedure for acyclicity, not an enumeration. Empty proves the
        relation acyclic, and every list returned is a real cycle, but a node is
        never re-entered once finished, so where cycles overlap only the first the
        walk closes is named and the count is a lower bound. That is all
        `requires` needs: load order is undefined the moment one cycle exists.

        @param edge_type the single relation type to walk
        @return one node-id list per cycle found, each ending on the node it began at
        """
        # Each found element is one directed cycle represented by node-id strings ending at its
        # start; discovery order is preserved.
        found: list[list[str]] = []
        colour: dict[str, int] = {}
        # Each stack element is one active depth-first node id; traversal order is preserved for
        # cycle slicing.
        stack: list[str] = []

        def walk(node_id: str) -> None:
            """Descend from one node, recording every back edge as a cycle.

            @param node_id the node to visit; recursion depth follows the longest chain
            """
            # Mark the node active before descending so back-edges identify cycles.
            colour[node_id] = 1
            stack.append(node_id)
            for edge in sorted(self.out_edges(node_id, [edge_type]), key=lambda e: e.dst):
                # Read the destination's white/grey/black traversal state.
                state = colour.get(edge.dst, 0)
                if state == 0:
                    # Descend into an unvisited dependency before completing this node.
                    walk(edge.dst)
                # A grey destination is a back-edge closing a cycle on the active stack.
                elif state == 1:
                    # Locate the repeated active-stack node that begins the discovered cycle.
                    start = stack.index(edge.dst)
                    found.append([*stack[start:], edge.dst])
            stack.pop()
            # Mark the node complete only after every outgoing dependency has been examined.
            colour[node_id] = 2

        # Start depth-first traversal at each still-unvisited node in lexical identity order.
        for node_id in sorted(self.nodes):
            # Skip nodes already completed through an earlier component root.
            if colour.get(node_id, 0) == 0:
                # Traverse one disconnected component and append any canonicalized cycles found.
                walk(node_id)
        # Preserve cycle discovery order for stable validator diagnostics.
        return found

    def dangling(self) -> list[Edge]:
        """Edges naming an endpoint the graph does not hold.

        Adding an edge never checks its endpoints, so that builders may run in
        any order; this is the check deferred until they have all finished.

        @return every unresolved edge, in the order it was added
        """
        # Retain each edge with an absent endpoint in original edge order.
        return [e for e in self.edges if e.src not in self.nodes or e.dst not in self.nodes]

    def orphans(self, node_type: NodeType) -> list[str]:
        """Nodes of one kind that no relation touches, in either direction.

        Weaker than `unreachable_from` and cheaper: it finds material that was
        added and then never wired to anything at all.

        @param node_type the kind to inspect
        @return the isolated ids, sorted
        """
        # Each result is a typed node id with neither incoming nor outgoing adjacency.
        return sorted(
            n.id
            for n in self.of_type(node_type)
            if not self._out.get(n.id) and not self._in.get(n.id)
        )

    # --------------------------------------------------------------- serialize

    def to_dict(self) -> dict[str, object]:
        """A JSON-ready mapping fixed by content alone, never by build order.

        Sorted throughout, and defaulted fields are omitted, so a rebuild that
        changed nothing produces no diff and a diff always means something moved.

        @return the graph as `nodes` and `edges` lists of plain values, losing
            nothing `from_dict` needs to rebuild it
        """
        # Project nodes and edges into independently sorted plain-value lists for stable JSON.
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
        """Rebuild a graph from what `to_dict` produced.

        Strict about vocabulary and lenient about omissions: a missing optional
        field takes its default, but an unrecognised type name is an error
        rather than a silently dropped relation.

        @param payload a mapping with `nodes` and `edges` entries, both optional
            Treat payload as mapping elements whose keys identify fields and values carry their
            content; key order is deliberately unused.
        @return a graph holding what the payload described
        @throws KeyError when a record leaves out a field that has no default
        @throws ValueError when a node, edge or origin name is not one this model defines
        """
        # Reconstruct an empty graph before replaying serialized nodes and edges in payload order.
        graph = cls()
        # Reconstruct nodes from serialized order after normalizing each optional metadata map.
        for raw in payload.get("nodes", []):  # type: ignore[union-attr]
            # Normalize optional node metadata to a key/value mapping before string conversion.
            attrs = raw.get("attrs") or {}
            graph.add_node(
                Node(
                    id=str(raw["id"]),
                    type=NodeType(str(raw["type"])),
                    label=str(raw["label"]),
                    path=raw.get("path"),
                    tokens=int(raw.get("tokens", 0)),
                    # Sort each metadata pair by key for deterministic graph equality and output.
                    attrs=tuple(sorted((str(k), str(v)) for k, v in attrs.items())),
                )
            )
        # Reconstruct edges in serialized order so adjacency traversal remains byte-stable.
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
        """Size counted in nodes; edges do not contribute.

        @return the node count, so a graph carrying edges and no node is falsy
        """
        # Truth and cardinality intentionally describe vertices, not relationship volume.
        return len(self.nodes)


def _unwind(previous: dict[str, Edge], src: str, dst: str) -> list[Edge]:
    """Turn a search's predecessor map back into a forward path.

    @param previous each node mapped to the edge that first reached it
        Treat previous as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param src the node the walk started at
    @param dst the node that was reached
    @return the edges from `src` to `dst`, in travel order
    @throws KeyError when the map does not in fact join the two, which would mean
        the caller unwound a search that never reached `dst`
    """
    # Each path element is one predecessor edge collected destination-to-source; reverse unwind
    # order is preserved until the final reversal.
    path: list[Edge] = []
    cursor = dst
    # Walk predecessor links backward until the path reaches its requested source.
    while cursor != src:
        # Follow each recorded predecessor edge backward from destination to source.
        edge = previous[cursor]
        path.append(edge)
        cursor = edge.src
    # Reverse predecessor order so callers receive edges in source-to-destination travel order.
    return list(reversed(path))


def iter_edge_types(names: Sequence[str]) -> Iterator[EdgeType]:
    """Turn command-line words into edge types, failing loudly on an unknown one.

    A misspelt type would otherwise narrow a query to nothing and read as a
    clean, empty result, which is the worst answer a gate can give.

    @param names the words as written on the command line
        Each element is one candidate node-name string; caller order is
        preserved while the best lexical match is selected.
    @return one edge type per name, yielded lazily
    @throws ValueError on iteration, as soon as a word names no edge type
    """
    # Each name is validated lazily so callers observe the first invalid edge vocabulary item.
    for name in names:
        yield EdgeType(name)
