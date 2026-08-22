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
from dataclasses import asdict, dataclass, replace
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Final

from build_graph import load_graph
from discipline_core import REPO_ROOT
from graph_model import READING_EXPANSION, Edge, EdgeType, Graph, Node, NodeType

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

## Path segments that name an architectural layer. A path containing one is
## governed by whatever rules apply to that layer.
LAYERS: Final = ("domain", "app", "adapters", "shell", "ports")
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
    ## The verifier-availability state from `discipline/rules.json`, or None when
    ## the node is not a rule or the index has not been built. This is distinct
    ## from force and from an executed project-gate outcome.
    verification: str | None = None
    ## Reading cost copied off the node, and zero means unmeasured rather than
    ## free: nothing here distinguishes a costless node from an uncosted one.
    tokens: int = 0


## Verifier states that need a caveat beside normative force. Available automated
## strategies print the force plain; review remains visible because a checked
## artifact is not a machine verdict on the semantic conclusion.
_VERIFICATION_CAVEAT: Final[Mapping[str, str]] = {
    "unbuilt": "VERIFIER NOT BUILT",
    "undeclared": "NO VERIFICATION STRATEGY",
    "structured-review": "STRUCTURED REVIEW",
    "retired": "RETIRED",
}


@lru_cache(maxsize=4)
def verification_index(root: Path) -> Mapping[str, str]:
    """Rule id against verifier availability, read from `rules.json`.

    Overlaid rather than carried in the graph because the state is measured from
    the working tree at build time. A missing or unreadable index leaves answers
    unannotated; it never fabricates availability or a gate outcome.

    @param root the repository root whose generated index is read
    @return state by stable id, empty when the index is absent or malformed
    """
    path = root / "discipline" / "rules.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    found: dict[str, str] = {}
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            continue
        verification = rule.get("verification")
        if not isinstance(verification, dict):
            continue
        state = verification.get("state")
        if isinstance(state, str):
            found[rule["id"]] = state
    return found


def annotate(hits: Iterable[Hit], root: Path) -> list[Hit]:
    """Attach each rule's verifier-availability state to the answer.

    @param hits the answer records to annotate, in the order they will be shown
    @param root the repository root whose generated index supplies the statuses
    @return the same records in the same order, rules carrying their status
    """
    index = verification_index(root)
    return [replace(hit, verification=index.get(hit.id)) for hit in hits]


def force_tag(force: str | None, verification: str | None) -> str:
    """Render a rule's obligation beside verifier availability.

    A caveat is spelled out rather than reduced to punctuation because a reader
    skimming output must not turn normative force into a guarantee that some gate
    step exists. This function still never reports whether a step passed.

    @param force the declared force, or None on a node that carries none
    @param verification verifier availability, or None when it was not available
    @return the bracketed tag, or the empty string when there is no force to show
    """
    if not force:
        return ""
    caveat = _VERIFICATION_CAVEAT.get(verification or "")
    return f"[{force} - {caveat}]" if caveat else f"[{force}]"


def openable(stored: str) -> str:
    """A stored graph path, rewritten so the reader can actually open it.

    The graph records paths relative to the corpus root, which is correct where
    the corpus *is* the repository and wrong everywhere it is vendored: under
    `.agent/` the answer `discipline/law/ARCH.md:51` names nothing, and the file
    is at `.agent/discipline/law/ARCH.md:51`. An answer an agent cannot act on
    is the failure this navigator exists to prevent, so the path is resolved
    against the tool's own root and then expressed from wherever the caller is
    standing.

    In the source repository, where the two coincide, the output is unchanged.

    @param stored the path as the graph holds it, optionally suffixed `:LINE`
    @return the same location relative to the working directory, or absolute
        when it lies outside it
    """
    if not stored:
        return stored
    body, sep, line = stored.rpartition(":")
    if not (sep and line.isdigit()):
        body, line = stored, ""
    absolute = (REPO_ROOT / body).resolve()
    try:
        shown = absolute.relative_to(Path.cwd()).as_posix()
    except ValueError:
        shown = absolute.as_posix()
    return f"{shown}:{line}" if line else shown


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
    # Order is significant and the three differ in how they claim an id: a layer
    # match overwrites, the other two defer to whatever is already there. Running
    # them in this order is what makes "governs domain/" beat "matches **/*.py"
    # for the same rule.
    _seed_by_layer(graph, parts, found)
    _seed_test_law(graph, path, parts, found)
    _seed_by_glob(graph, path, found)
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _seed_by_layer(graph: Graph, parts: Sequence[str], found: dict[str, Hit]) -> None:
    """Claim every rule that governs an architectural layer the path sits in.

    @param graph the discipline graph
    @param parts the path's POSIX segments
    @param found the accumulator, overwritten here because a layer match is the
        strongest claim any route makes
    """
    for layer in LAYERS:
        if layer not in parts:
            continue
        for edge in graph.in_edges(f"layer:{layer}", [EdgeType.APPLIES_TO]):
            node = graph.nodes.get(edge.src)
            if node is not None:
                found[node.id] = _hit(node, 0, f"governs {layer}/")


def _seed_test_law(
    graph: Graph,
    path: str,
    parts: Sequence[str],
    found: dict[str, Hit],
) -> None:
    """Claim the whole testing law for a file that is a test.

    The testing rules bind on what a file *is* rather than where it sits, so this
    fires on a `test_` prefix as well as on a `tests/` segment.

    @param graph the discipline graph
    @param path the file being worked on
    @param parts the path's POSIX segments
    @param found the accumulator, deferred to where a layer already claimed a rule
    """
    if "tests" not in parts and not Path(path).name.startswith("test_"):
        return
    for edge in graph.out_edges("law/TEST", [EdgeType.CONTAINS]):
        node = graph.nodes.get(edge.dst)
        if node is not None:
            found.setdefault(node.id, _hit(node, 0, "test file"))


def _seed_by_glob(graph: Graph, path: str, found: dict[str, Hit]) -> None:
    """Claim the modules whose `applies_to` glob covers the path, one hop out.

    A glob match is weaker than a layer match: it says a module's rules cover
    this file, not that any of them is about what the file is.

    @param graph the discipline graph
    @param path the file being worked on
    @param found the accumulator, deferred to where a stronger route already claimed
    """
    posix = Path(path).as_posix()
    for node in graph.of_type(NodeType.TRIGGER):
        if node.attr("kind") != "glob" or not fnmatch.fnmatch(posix, node.label):
            continue
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            owner = graph.nodes.get(edge.src)
            if owner is not None and owner.type is NodeType.MODULE:
                found.setdefault(owner.id, _hit(owner, 1, f"matches {node.label}"))


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
    _seed_by_signature(graph, text, found)
    _seed_by_quoted_id(graph, text, found)
    _seed_by_mechanism(graph, text.lower(), found)
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _seed_by_signature(graph: Graph, text: str, found: dict[str, Hit]) -> None:
    """Claim rules whose error trigger the message matches.

    @param graph the discipline graph
    @param text whatever the failing tool printed
    @param found the accumulator, overwritten because the message's own words are
        the strongest evidence available
    """
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


def _seed_by_quoted_id(graph: Graph, text: str, found: dict[str, Hit]) -> None:
    """Claim any rule the message names outright.

    @param graph the discipline graph
    @param text whatever the failing tool printed
    @param found the accumulator, overwritten: a quoted id is not a guess
    """
    for rule_id in _RULE_ID.findall(text):
        node = graph.nodes.get(rule_id)
        if node is not None:
            found[node.id] = _hit(node, 0, "named in the error")


def _seed_by_mechanism(graph: Graph, lowered: str, found: dict[str, Hit]) -> None:
    """Claim the rules enforced by whichever checker produced the message, one hop out.

    Knowing which checker complained is weaker evidence than the rule's own words,
    so this defers to anything the other two routes already claimed.

    @param graph the discipline graph
    @param lowered the message, already lowercased
    @param found the accumulator, deferred to
    """
    for node in graph.of_type(NodeType.MECHANISM):
        stem = node.label.split(":")[-1]
        if len(stem) > 4 and stem.lower() in lowered:
            for edge in graph.in_edges(node.id, [EdgeType.ENFORCED_BY]):
                owner = graph.nodes.get(edge.src)
                if owner is not None:
                    found.setdefault(owner.id, _hit(owner, 1, f"checked by {node.label}"))


## Words too common to carry a topic. Dropped from both sides before a keyword is
## compared, so `a`, `this` and `the` cannot make up a keyword's overlap.
_STOPWORDS: Final[frozenset[str]] = frozenset({
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "it",
    "its",
    "is",
    "are",
    "was",
    "be",
    "to",
    "for",
    "of",
    "in",
    "on",
    "at",
    "and",
    "or",
    "my",
    "i",
    "we",
    "do",
    "does",
    "did",
    "how",
    "should",
    "would",
    "can",
    "with",
    "some",
    "any",
})


## How short a stem may get before a suffix is left alone. `is`, `as` and `us`
## are not inflections of `i`, `a` and `u`, and stripping them would collapse
## unrelated words onto each other.
_MIN_STEM: Final = 3

## The suffix that needs its own rule, because dropping it leaves a stem the
## singular form does not share: `dependencies` -> `dependenc` never meets
## `dependency`.
_PLURAL_Y: Final = "ies"


def _stem(word: str) -> str:
    """A word reduced to a form that survives ordinary inflection.

    Deliberately crude, and deliberately small. The alternative was exact
    matching, which is what the router did: `load_when` carried "add a
    dependency" and the query "adding a new dependency" reached NOTHING, sending
    the agent to read speculatively -- the one behaviour the layered design
    exists to prevent. A real stemmer would be a dependency in the core of a tool
    that must run anywhere; four suffixes recover most of the loss.

    @param word one lowercased word
    @return the stem, or the word unchanged when no suffix applies
    """
    if word.endswith(_PLURAL_Y) and len(word) - len(_PLURAL_Y) >= _MIN_STEM:
        return word[: -len(_PLURAL_Y)] + "y"
    for suffix in ("ing", "ed", "es", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            return word[: -len(suffix)]
    return word


def _content(text: str) -> set[str]:
    """The stemmed, topic-bearing words of a phrase.

    @param text a query or a router keyword
    @return its stems, with stopwords removed
    """
    return {_stem(w) for w in _WORD.findall(text.lower())} - _STOPWORDS


def seeds_for_task(graph: Graph, text: str) -> list[Hit]:
    """Modules whose router keywords the task text mentions.

    A single-word keyword must appear. A multi-word keyword is satisfied by half
    its topic-bearing words, rounded up -- because the phrasings a keyword is
    written in and the phrasings a person uses are rarely the same, and demanding
    the whole phrase verbatim produced empty answers for ordinary questions.

    Half is a judgement, and the reject cases in `enforce/fixtures/routing.toml`
    are what hold it: a router that answers "renaming a variable" with five law
    modules has been loosened past usefulness, and KERNEL's negative-routing
    paragraph says that query should load nothing at all.

    @param graph the discipline graph
    @param text the task description, in the author's own words
    @return the modules whose entry keywords it mentions, ordered by id
    """
    asked = _content(text)
    found: dict[str, Hit] = {}
    for node in graph.of_type(NodeType.TRIGGER):
        if node.attr("kind") != "keyword":
            continue
        parts = _content(node.label)
        if not parts:
            continue
        needed = 1 if len(parts) == 1 else -(-len(parts) // 2)
        if len(parts & asked) < needed:
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


def _gather_seeds(graph: Graph, args: argparse.Namespace) -> dict[str, Hit]:
    """Every channel's seeds, merged at the shortest distance each was found at.

    A rule reached by two channels is kept once, at its nearer hop, so supplying
    more context can only sharpen the plan and never dilute it.

    @param graph the discipline graph
    @param args the parsed `context` arguments; any channel may be absent
    @return the merged seeds by node id
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
    return by_id


def _module_relevance(
    graph: Graph,
    rules: Sequence[Hit],
    modules: Sequence[Hit],
) -> dict[str, tuple[int, int]]:
    """Rank the modules worth reading, by nearness and then by how much they carry.

    Reading a module is how a rule is actually loaded, so the budget is spent on
    modules that own the selected rules rather than on the rules themselves.
    Ranking by hop first and rule count second is what makes a tight budget keep
    what the task is about instead of whatever happens to be smallest.

    @param graph the discipline graph
    @param rules the selected rules, in plan order
    @param modules the modules selected in their own right
    @return each module id mapped to its nearest hop and the number of selected
        rules it owns
    """
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
    return relevance


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
    by_id = _gather_seeds(graph, args)

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

    rules = annotate(
        sorted(
            (h for h in by_id.values() if h.type == "rule"),
            key=lambda h: (h.hops, _force_rank(h.force), h.id),
        ),
        Path(getattr(args, "root", REPO_ROOT)).resolve(),
    )
    modules = sorted(
        (h for h in by_id.values() if h.type == "module"), key=lambda h: (h.hops, h.id)
    )
    relevance = _module_relevance(graph, rules, modules)
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
            store,
            connection,
            file=getattr(args, "file", None),
            error=getattr(args, "error", None),
            task=getattr(args, "task", None),
            rules=[r for r in selected if _RULE_ID.fullmatch(r)],
        )
    finally:
        connection.close()
    return [f"{c.id} [{c.status} {c.effective:.2f}] {c.claim} -> {c.action}" for c in found]


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


def rules_by_id(root: Path) -> dict[str, object]:
    """Every parsed rule in the corpus, by id.

    Parsed from the modules rather than read from the graph, because the graph
    carries a rule's identity and not its words -- and the words are the whole
    answer `diagnose` exists to give.

    @param root the repository root
    @return each rule id against its parsed `Rule`
    """
    from discipline_core import (  # ruff: ignore[import-outside-top-level]
        iter_documents,
    )

    found: dict[str, object] = {}
    for document in iter_documents(root / "discipline"):
        for rule in document.rules:
            found[rule.rule_id] = rule
    return found


def envelope_ids(payload: dict[str, object]) -> list[str]:
    """The rules a diagnostic envelope names outright.

    `DIAG-001`'s envelope carries `rule_ids` precisely so a failure can say which
    contract it broke. Reading them is the difference between a lookup and a
    derivation, and it is the hop the Prime Directive was missing.

    @param payload a parsed envelope
    @return the rule ids it names, in order, empty when it names none
    """
    named = payload.get("rule_ids") or []
    return [str(entry) for entry in named] if isinstance(named, list) else []


def _read_envelope(source: str | None) -> dict[str, object]:
    """Parse a serialized envelope from a path, or from stdin when given `-`.

    @param source the path, `-` for stdin, or None when the caller passed none
    @return the parsed envelope, empty when there was nothing to read
    @throws SystemExit when the text is not JSON, because a malformed envelope
        that fell through as an empty one would read as "this failure names no
        rule", which is a claim nobody made
    """
    if source is None:
        return {}
    raw = sys.stdin.read() if str(source) == "-" else Path(source).read_text(encoding="utf-8")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as broken:
        message = f"the envelope is not JSON: {broken}"
        raise SystemExit(message) from broken
    return parsed if isinstance(parsed, dict) else {}


def _diagnostic_seeds(graph: Graph, envelope: dict[str, object], text: str) -> dict[str, Hit]:
    """Which rules the failure implicates, preferring what it named outright.

    An id the envelope carries is evidence, not a guess, so it seeds at zero hops
    and nothing else is consulted. Only when the envelope named none does this
    fall back to the signature and quoted-id seeding `context` uses -- over the
    envelope's own prose as well as any raw text, since a program that emits an
    envelope without ids still describes itself in one.

    @param graph the discipline graph
    @param envelope the parsed envelope, possibly empty
    @param text raw error text, possibly empty
    @return the implicated nodes by id
    """
    found: dict[str, Hit] = {}
    for rule_id in envelope_ids(envelope):
        node = graph.nodes.get(rule_id)
        if node is not None:
            found[node.id] = _hit(node, 0, "named by the envelope")
    if found:
        return found

    prose = " ".join(
        str(envelope.get(field, ""))
        for field in ("code", "operation", "expected", "actual", "notes")
    )
    for hit in seeds_for_error(graph, f"{text} {prose}".strip()):
        found.setdefault(hit.id, hit)
    return found


def _rule_answer(hit: Hit, node: Node, rule: object, verification: str | None) -> dict[str, object]:
    """One rule laid out as an answer: what it says, why, and what decides it.

    @param hit how the rule was reached
    @param node its graph node, carrying the force tag and reading cost
    @param rule its parsed form, carrying the words
    @param verification measured verifier availability, kept separate from force
    @return the fields a caller needs to act without opening the module
    """
    return {
        "id": hit.id,
        "title": rule.title,  # type: ignore[attr-defined]
        "force": force_tag(node.attr("force"), verification),
        "statement": rule.statement,  # type: ignore[attr-defined]
        "why": rule.why,  # type: ignore[attr-defined]
        "check": rule.check,  # type: ignore[attr-defined]
        "module": node.attr("module"),
        "open": openable(node.path),
        "tokens": node.tokens,
        "reason": hit.reason,
    }


def cmd_diagnose(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """What broke, against which rule, and what to do -- and nothing else.

    `context` answers "what should I read", and answers it with a reading plan
    costing about five thousand tokens. That is the right answer to that question
    and the wrong answer to this one. An agent holding a failure wants the
    governing rule's own words, its rationale, and the line to open if the words
    are not enough.

    So this returns the rules themselves, at a measured median of 57 tokens
    against `context`'s 4,994 over the same twelve defects. The owning module is
    NAMED, not read: it is there for the case where the rule alone does not settle
    it.

    @param graph the discipline graph
    @param args the parsed `diagnose` arguments
    @return the implicated rules with their text, the envelope's own remediation
        when it carried one, what the answer cost, and any id the envelope named
        that the corpus does not carry
    @throws SystemExit when neither an envelope nor an error text was supplied
    """
    envelope = _read_envelope(args.envelope)
    text = args.error or ""
    if not (envelope or text):
        message = "diagnose needs --envelope or --error"
        raise SystemExit(message)

    root = Path(args.root).resolve()
    found = _diagnostic_seeds(graph, envelope, text)
    parsed = rules_by_id(root)
    status = verification_index(root)

    implicated: list[dict[str, object]] = []
    for hit in sorted(found.values(), key=lambda h: (h.hops, h.id)):
        node = graph.nodes.get(hit.id)
        rule = parsed.get(hit.id)
        if hit.type == "rule" and node is not None and rule is not None:
            implicated.append(_rule_answer(hit, node, rule, status.get(hit.id)))

    reached = {entry["id"] for entry in implicated}
    return {
        "code": envelope.get("code"),
        "layer": envelope.get("layer"),
        "reported_remediation": envelope.get("remediation"),
        "rules": implicated,
        "tokens": sum(int(entry["tokens"]) for entry in implicated),
        "unresolved": [r for r in envelope_ids(envelope) if r not in reached],
    }


def cmd_rule(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """One node with everything it relates to, grouped by relation.

    Both directions are reported: what a rule cites is half the picture, and
    what cites it is the other half.

    The declared force is reported beside verifier availability. A binding rule
    with no strategy or an absent verifier also gets a sentence-level warning,
    because the force tag alone must not be read as a gate guarantee.

    @param graph the discipline graph
    @param args the parsed `rule` arguments, carrying the id to look up
    @return the node's identity and its relations, outgoing and incoming
    @throws SystemExit when the graph holds no node with that id
    """
    node = _require(graph, args.id)
    verification = verification_index(Path(getattr(args, "root", REPO_ROOT)).resolve()).get(node.id)
    caveat = _VERIFICATION_CAVEAT.get(verification or "")
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
        "verification": verification,
        "warning": (
            f"{node.id} {force_tag(node.attr('force'), verification)}"
            f" - {caveat.lower()}; this is verifier availability, not a pass result"
            if caveat and node.attr("force")
            else None
        ),
        "module": node.attr("module"),
        "path": openable(node.path),
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
            {
                "id": nid,
                "hops": hops,
                "label": graph.nodes[nid].label,
                "type": str(graph.nodes[nid].type),
            }
            for nid, hops in sorted(reached.items(), key=lambda kv: (kv[1], kv[0]))
            if nid != args.id
        ],
    }


def cmd_applies(graph: Graph, args: argparse.Namespace) -> dict[str, object]:
    """What governs one file, with no expansion and no budgeting.

    The narrow question behind `context`, answered on its own for the case where
    an agent wants the obligations rather than a reading plan. The path need not
    exist; only its shape decides the answer.

    Each rule carries verifier availability alongside force, so a caller can see
    whether any strategy is available without mistaking that fact for a pass.

    @param graph the discipline graph
    @param args the parsed `applies` arguments, carrying the path
    @return the path, the rules that bind it, and the modules that carry them
    """
    hits = annotate(seeds_for_file(graph, args.path), Path(args.root).resolve())
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
        "resolved_by": [
            _describe(graph, e.dst, e) for e in graph.out_edges(node.id, [EdgeType.RESOLVED_BY])
        ],
        "blocked_by": [
            _describe(graph, e.dst, e) for e in graph.out_edges(node.id, [EdgeType.BLOCKED_BY])
        ],
        "grounds_on": [
            _describe(graph, e.dst, e) for e in graph.out_edges(node.id, [EdgeType.GROUNDS_ON])
        ],
        "tensions_with": [
            _describe(graph, e.dst, e) for e in graph.out_edges(node.id, [EdgeType.TENSIONS_WITH])
        ],
        "derives_from": [
            _describe(graph, e.dst, e) for e in graph.out_edges(node.id, [EdgeType.DERIVES_FROM])
        ],
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
            {"type": str(e.type), "src": e.src, "dst": e.dst, "note": e.note} for e in (found or [])
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
    unreachable = graph.unreachable_from(_kernel_seeds(graph), NodeType.RULE, depth=args.depth)
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


def _render_context(payload: dict[str, object]) -> list[str]:
    """The reading plan: what governs the situation, what to read, what it costs.

    @param payload the `context` answer
    @return the lines to print
    """
    shown, total = payload["rules_shown"], payload["rules_total"]
    suffix = f" of {total} - raise --max-rules to see the rest" if shown < total else ""
    lines = [f"RULES ({shown}{suffix})"]
    for rule in payload["rules"]:  # type: ignore[union-attr]
        tag = force_tag(rule["force"], rule.get("verification"))
        lines.append(f"  {rule['id']:<10} {tag:<32} {rule['label']}")
        lines.append(f"  {'':<10} {'':<32} ~ {rule['reason']}")
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
        lines += [f"  {item}" for item in payload["learnings"]]  # type: ignore[union-attr]
    return lines


def _render_applies(payload: dict[str, object]) -> list[str]:
    """Every rule and module that governs one path.

    @param payload the `applies` answer
    @return the lines to print
    """
    rules = payload["rules"]
    lines = [f"{payload['path']}  ({len(rules)} rules)"]  # type: ignore[arg-type]
    for rule in rules:  # type: ignore[union-attr]
        lines.append(
            f"  {rule['id']:<10} "
            f"{force_tag(rule['force'], rule.get('verification')):<32}"
            f" {rule['label']}   ~ {rule['reason']}"
        )
    lines += [f"  {module['id']:<20} ~ {module['reason']}" for module in payload["modules"]]  # type: ignore[union-attr]
    return lines


def _render_node(payload: dict[str, object]) -> list[str]:
    """One node and its edges, grouped by edge type.

    Shared by `rule` and `why`: the two differ in which edges they select, not in
    how the result reads.

    @param payload the `rule` or `why` answer
    @return the lines to print
    """
    lines = [f"{payload['id']} - {payload.get('label', '')}"]
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
    return lines


def _render_stats(payload: dict[str, object]) -> list[str]:
    """Node and edge census, and the reachability figure V092 gates on.

    @param payload the `stats` answer
    @return the lines to print
    """
    lines = [
        "NODES  " + ", ".join(f"{k}={v}" for k, v in payload["nodes"].items()),  # type: ignore[union-attr]
        "EDGES  " + ", ".join(f"{k}={v}" for k, v in payload["edges"].items()),  # type: ignore[union-attr]
        f"REACH  {payload['rules_reachable']}/{payload['rules_total']} rules "
        f"within {payload['reach_depth']} hops",
    ]
    if payload["unreachable"]:
        lines.append("  unreachable: " + ", ".join(payload["unreachable"]))  # type: ignore[union-attr]
    return lines


## The per-command layouts. A command absent from this table falls back to
## indented JSON, so a new subcommand prints something legible before anyone
## writes its renderer.
def _render_diagnose(payload: dict[str, object]) -> list[str]:
    """Lay a diagnosis out as an answer, not as a reading list.

    @param payload what `cmd_diagnose` produced
    @return the lines to print
    """
    lines: list[str] = []
    if payload.get("code"):
        where = f" in the {payload['layer']} layer" if payload.get("layer") else ""
        lines.append(f"{payload['code']}{where}")
    if payload.get("reported_remediation"):
        lines += ["", f"REPORTED  {payload['reported_remediation']}"]

    rules = payload.get("rules") or []
    if not rules:
        lines += [
            "",
            "no rule in the corpus matched this output.",
            "Add a signature to enforce/signals.toml if this shape recurs.",
        ]
        return lines

    lines.append("")
    for rule in rules:  # type: ignore[union-attr]
        lines += [
            f"{rule['id']} {rule['force']}  {rule['title']}",
            f"    {rule['statement']}",
        ]
        if rule.get("why"):
            lines.append(f"    why    {rule['why']}")
        if rule.get("check"):
            lines.append(f"    check  {rule['check']}")
        lines += [f"    open   {rule['open']}  ({rule['module']})", ""]
    lines.append(f"COST  {payload['tokens']} tok -- {len(rules)} rule(s), read in full")
    if payload.get("unresolved"):
        named = ", ".join(payload["unresolved"])  # type: ignore[arg-type]
        lines.append(f"UNRESOLVED  {named} -- named by the envelope, absent here")
    return lines


## Which renderer lays out which command's payload. A table rather than a chain
## of conditionals, because the chain was over `C901`'s ceiling and `ARCH-016` is
## enforced through that exact code. A command absent from here falls back to
## JSON, which is readable if not shaped.
_RENDERERS: Final[Mapping[str, Callable[[dict[str, object]], list[str]]]] = {
    "context": _render_context,
    "diagnose": _render_diagnose,
    "applies": _render_applies,
    "rule": _render_node,
    "why": _render_node,
    "stats": _render_stats,
}


def render(command: str, payload: dict[str, object]) -> str:
    """Lay an answer out for a terminal, in the shape that command deserves.

    @param command which subcommand produced the payload
    @param payload that command's answer, unmodified
    @return the text to print, with no trailing newline
    """
    renderer = _RENDERERS.get(command)
    if renderer is None:
        return json.dumps(payload, indent=1, ensure_ascii=False)
    return "\n".join(renderer(payload))


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

    dg = sub.add_parser("diagnose", help="what broke, against which rule, and what to do")
    dg.add_argument("--envelope", help="a serialized diagnostic envelope, or - for stdin")
    dg.add_argument("--error", help="raw error text, when there is no envelope")

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
    "diagnose": cmd_diagnose,
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
    print(
        json.dumps(payload, indent=1, ensure_ascii=False)
        if args.json
        else render(args.command, payload)
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
