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

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

## Path segments that name an architectural layer. A path containing one is
## governed by whatever rules apply to that layer.
## Each element is one architectural path-segment spelling in matching-priority order.
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
## Each key is a verification state and each value is its reader-facing caveat; mapping key
## order is deliberately unused.
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
    # Resolve the repository-confined path used by this operation before filesystem access.
    path = root / "discipline" / "rules.json"
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Decode generated-index field keys to their JSON values; mapping key order is
        # deliberately unused.
        payload = json.loads(path.read_text(encoding="utf-8"))
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (OSError, ValueError):
        # Return state by stable id, empty when the index is absent or malformed to the caller.
        return {}
    # Compute rules using payload.get for later verification index logic.
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    # Each found key is a rule id and each value is its verification state; mapping key order is
    # deliberately unused.
    found: dict[str, str] = {}
    # Select rule as the current element from rules while verification index preserves traversal
    # Details: order.
    # Advance verification index through the current input element in declared order.
    for rule in rules:
        # Select the empty-or-disabled path when isinstance(rule, dict) or not
        # Details: isinstance(rule.get('id'), str) has no usable value.
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute verification using rule.get for later verification index logic.
        verification = rule.get("verification")
        # Select the empty-or-disabled path when isinstance(verification, dict) has no usable
        # Details: value.
        if not isinstance(verification, dict):
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute state using verification.get for later verification index logic.
        state = verification.get("state")
        # Select the guarded path only after `isinstance(state, str)` is satisfied.
        if isinstance(state, str):
            # Update verification index state only after the required source facts are
            # Details: available.
            found[rule["id"]] = state
    # Return state by stable id, empty when the index is absent or malformed to the caller.
    return found


def annotate(hits: Iterable[Hit], root: Path) -> list[Hit]:
    """Attach each rule's verifier-availability state to the answer.

    @param hits the answer records to annotate, in the order they will be shown
    @param root the repository root whose generated index supplies the statuses
    @return the same records in the same order, rules carrying their status
    """
    # Locate the structural boundary used to parse the external result safely.
    index = verification_index(root)
    # Select hit as the current element from hits] while annotate preserves traversal order.
    # Return the same records in the same order, rules carrying their status to the caller.
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
    # Select the empty-or-disabled path when force has no usable value.
    if not force:
        # Return the bracketed tag, or the empty string when there is no force to show to the
        # Details: caller.
        return ""
    # Compute caveat using  VERIFICATION CAVEAT.get for later force tag logic.
    caveat = _VERIFICATION_CAVEAT.get(verification or "")
    # Return the bracketed tag, or the empty string when there is no force to show to the
    # Details: caller.
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
    # Select the empty-or-disabled path when stored has no usable value.
    if not stored:
        # Return the same location relative to the working directory, or absolute to the caller.
        return stored
    # Retain the immutable source representation consumed by subsequent analysis.
    body, sep, line = stored.rpartition(":")
    # Select the empty-or-disabled path when (sep and line.isdigit()) has no usable value.
    if not (sep and line.isdigit()):
        # The two assigned elements are ordered as complete path text then empty line suffix.
        body, line = stored, ""
    # Compute absolute using (REPO_ROOT / body).resolve() for later openable logic.
    absolute = (REPO_ROOT / body).resolve()
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the completed Git query with its status and captured content.
        shown = absolute.relative_to(Path.cwd()).as_posix()
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ValueError:
        # Preserve the completed Git query with its status and captured content.
        shown = absolute.as_posix()
    # Return the same location relative to the working directory, or absolute to the caller.
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
    # Each found key is a reached node id and each value is its strongest Hit; mapping key order
    # is deliberately unused because results are explicitly sorted.
    found: dict[str, Hit] = {}
    # Compute parts using Path for later seeds for file logic.
    parts = Path(path).as_posix().split("/")
    # Order is significant and the three differ in how they claim an id: a layer
    # match overwrites, the other two defer to whatever is already there. Running
    # them in this order is what makes "governs domain/" beat "matches **/*.py"
    # for the same rule.
    _seed_by_layer(graph, parts, found)
    _seed_test_law(graph, path, parts, found)
    _seed_by_glob(graph, path, found)
    # Return the rules and modules that govern it, nearest first then by id to the caller.
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _seed_by_layer(graph: Graph, parts: Sequence[str], found: dict[str, Hit]) -> None:
    """Claim every rule that governs an architectural layer the path sits in.

    @param graph the discipline graph
    @param parts the path's POSIX segments
        Each element is one path segment in root-to-leaf order.
    @param found the accumulator, overwritten here because a layer match is the
        strongest claim any route makes
        Each key is a reached node id and each value is its strongest Hit; mapping key order is
        deliberately unused.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Select layer as the current element from LAYERS while seed by layer preserves traversal
    # Details: order.
    # Advance seed by layer through the current input element in declared order.
    for layer in LAYERS:
        # Select the guarded path only after `layer not in parts` is satisfied.
        if layer not in parts:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select edge as the current element from graph.in_edges(f"layer while seed by layer
        # Details: preserves traversal order.
        # Advance seed by layer through the current input element in declared order.
        for edge in graph.in_edges(f"layer:{layer}", [EdgeType.APPLIES_TO]):
            # Treat the current node as the candidate element consumed by the enclosing
            # Details: transformation.
            node = graph.nodes.get(edge.src)
            # Use the available-value path only when node is present.
            if node is not None:
                # Update  seed by layer state only after the required source facts are
                # Details: available.
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
        Each element is one path segment in root-to-leaf order.
    @param found the accumulator, deferred to where a layer already claimed a rule
        Each key is a reached node id and each value is its strongest Hit; mapping key order is
        deliberately unused.
    """
    # Select the guarded path only after `'tests' not in parts and (not
    # Details: Path(path).name.startswith('test_'))` is satisfied.
    if "tests" not in parts and not Path(path).name.startswith("test_"):
        # Return the completed  seed test law result to its caller.
        return
    # Select edge as the current element from graph.out_edges("law/TEST", [EdgeType.CONTAINS])
    # Details: while seed test law preserves traversal order.
    # Advance seed test law through the current input element in declared order.
    for edge in graph.out_edges("law/TEST", [EdgeType.CONTAINS]):
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(edge.dst)
        # Use the available-value path only when node is present.
        if node is not None:
            found.setdefault(node.id, _hit(node, 0, "test file"))


def _seed_by_glob(graph: Graph, path: str, found: dict[str, Hit]) -> None:
    """Claim the modules whose `applies_to` glob covers the path, one hop out.

    A glob match is weaker than a layer match: it says a module's rules cover
    this file, not that any of them is about what the file is.

    @param graph the discipline graph
    @param path the file being worked on
    @param found the accumulator, deferred to where a stronger route already claimed
        Each key is a reached node id and each value is its strongest Hit; mapping key order is
        deliberately unused.
    """
    # Compute posix using Path for later seed by glob logic.
    posix = Path(path).as_posix()
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    # Advance seed by glob through the current input element in declared order.
    for node in graph.of_type(NodeType.TRIGGER):
        # Select the guarded path only after `node.attr('kind') != 'glob' or not
        # Details: fnmatch.fnmatch(posix, node.label)` is satisfied.
        if node.attr("kind") != "glob" or not fnmatch.fnmatch(posix, node.label):
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select edge as the current element from graph.in_edges(node.id,
        # Details: [EdgeType.TRIGGERED_BY]) while seed by glob preserves traversal order.
        # Advance seed by glob through the current input element in declared order.
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            # Compute owner using graph.nodes.get for later seed by glob logic.
            owner = graph.nodes.get(edge.src)
            # Select the guarded path only after `owner is not None and owner.type is
            # Details: NodeType.MODULE` is satisfied.
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
    # Return its lowercased words, deduplicated and unordered to the caller.
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
    # Each found key is a reached node id and each value is its strongest Hit; mapping key order
    # is deliberately unused because results are explicitly sorted.
    found: dict[str, Hit] = {}
    _seed_by_signature(graph, text, found)
    _seed_by_quoted_id(graph, text, found)
    _seed_by_mechanism(graph, text.lower(), found)
    # Return the rules and modules the message points at, nearest first then by id to the
    # Details: caller.
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _seed_by_signature(graph: Graph, text: str, found: dict[str, Hit]) -> None:
    """Claim rules whose error trigger the message matches.

    @param graph the discipline graph
    @param text whatever the failing tool printed
    @param found the accumulator, overwritten because the message's own words are
        the strongest evidence available
        Each key is a reached node id and each value is its strongest Hit; mapping key order is
        deliberately unused.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Compute lowered using text.lower for later seed by signature logic.
    lowered = text.lower()
    # Compute words using  normalize for later seed by signature logic.
    words = _normalize(text)
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    # Advance seed by signature through the current input element in declared order.
    for node in graph.of_type(NodeType.TRIGGER):
        # Select the guarded path only after `node.attr('kind') != 'error'` is satisfied.
        if node.attr("kind") != "error":
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute signature using  normalize for later seed by signature logic.
        signature = _normalize(node.label)
        # A code such as G004 matches literally; a phrase matches when all of its
        # words are present, so separator style does not decide the outcome.
        literal = node.label.lower() in lowered
        if not (literal or (len(signature) > 1 and signature <= words)):
            # Advance after the current candidate has been conclusively excluded.
            continue
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            # Compute owner using graph.nodes.get for later seed by signature logic.
            owner = graph.nodes.get(edge.src)
            # Use the available-value path only when owner is present.
            if owner is not None:
                # Update  seed by signature state only after the required source facts are
                # Details: available.
                found[owner.id] = _hit(owner, 0, f"error signature {node.label!r}")


def _seed_by_quoted_id(graph: Graph, text: str, found: dict[str, Hit]) -> None:
    """Claim any rule the message names outright.

    @param graph the discipline graph
    @param text whatever the failing tool printed
    @param found the accumulator, overwritten: a quoted id is not a guess
        Each key is a reached node id and each value is its strongest Hit; mapping key order is
        deliberately unused.

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Select rule id as the current element from _RULE_ID.findall(text) while seed by quoted id
    # Details: preserves traversal order.
    # Advance seed by quoted id through the current input element in declared order.
    for rule_id in _RULE_ID.findall(text):
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(rule_id)
        # Use the available-value path only when node is present.
        if node is not None:
            # Update  seed by quoted id state only after the required source facts are
            # Details: available.
            found[node.id] = _hit(node, 0, "named in the error")


def _seed_by_mechanism(graph: Graph, lowered: str, found: dict[str, Hit]) -> None:
    """Claim the rules enforced by whichever checker produced the message, one hop out.

    Knowing which checker complained is weaker evidence than the rule's own words,
    so this defers to anything the other two routes already claimed.

    @param graph the discipline graph
    @param lowered the message, already lowercased
    @param found the accumulator, deferred to
        Each key is a reached node id and each value is its strongest Hit; mapping key order is
        deliberately unused.
    """
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    # Advance seed by mechanism through the current input element in declared order.
    for node in graph.of_type(NodeType.MECHANISM):
        # Compute stem using node.label.split for later seed by mechanism logic.
        stem = node.label.split(":")[-1]
        # Select the guarded path only after `len(stem) > 4 and stem.lower() in lowered` is
        # Details: satisfied.
        if len(stem) > 4 and stem.lower() in lowered:
            # Select edge as the current element from graph.in_edges(node.id,
            # Details: [EdgeType.ENFORCED_BY]) while seed by mechanism preserves traversal order.
            # Advance seed by mechanism through the current input element in declared order.
            for edge in graph.in_edges(node.id, [EdgeType.ENFORCED_BY]):
                # Compute owner using graph.nodes.get for later seed by mechanism logic.
                owner = graph.nodes.get(edge.src)
                # Use the available-value path only when owner is present.
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
    # Select the guarded path only after `word.endswith(_PLURAL_Y) and len(word) -
    # Details: len(_PLURAL_Y) >= _MIN_STEM` is satisfied.
    if word.endswith(_PLURAL_Y) and len(word) - len(_PLURAL_Y) >= _MIN_STEM:
        # Return the stem, or the word unchanged when no suffix applies to the caller.
        return word[: -len(_PLURAL_Y)] + "y"
    # Select suffix as the current element from ("ing", "ed", "es", "s") while stem preserves
    # Details: traversal order.
    # Advance stem through the current input element in declared order.
    for suffix in ("ing", "ed", "es", "s"):
        # Select the guarded path only after `word.endswith(suffix) and len(word) - len(suffix)
        # Details: >= _MIN_STEM` is satisfied.
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            # Return the stem, or the word unchanged when no suffix applies to the caller.
            return word[: -len(suffix)]
    # Return the stem, or the word unchanged when no suffix applies to the caller.
    return word


def _content(text: str) -> set[str]:
    """The stemmed, topic-bearing words of a phrase.

    @param text a query or a router keyword
    @return its stems, with stopwords removed
    """
    # Select w as the current element from _WORD.findall(text.lower())} - _STOPWORDS while
    # Details: content preserves traversal order.
    # Return its stems, with stopwords removed to the caller.
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
    # Compute asked using  content for later seeds for task logic.
    asked = _content(text)
    # Each found key is a reached module id and each value is its task-keyword Hit; mapping key
    # order is deliberately unused because results are explicitly sorted.
    found: dict[str, Hit] = {}
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    # Advance seeds for task through the current input element in declared order.
    for node in graph.of_type(NodeType.TRIGGER):
        # Select the guarded path only after `node.attr('kind') != 'keyword'` is satisfied.
        if node.attr("kind") != "keyword":
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute parts using  content for later seeds for task logic.
        parts = _content(node.label)
        # Select the empty-or-disabled path when parts has no usable value.
        if not parts:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute needed using 1 if len(parts) == 1 else -(-len(parts) // 2) for later seeds for
        # Details: task logic.
        needed = 1 if len(parts) == 1 else -(-len(parts) // 2)
        # Select the guarded path only after `len(parts & asked) < needed` is satisfied.
        if len(parts & asked) < needed:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select edge as the current element from graph.in_edges(node.id,
        # Details: [EdgeType.TRIGGERED_BY]) while seeds for task preserves traversal order.
        # Advance seeds for task through the current input element in declared order.
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            # Compute owner using graph.nodes.get for later seeds for task logic.
            owner = graph.nodes.get(edge.src)
            # Use the available-value path only when owner is present.
            if owner is not None:
                found.setdefault(owner.id, _hit(owner, 0, f"keyword {node.label!r}"))
    # Return the modules whose entry keywords it mentions, ordered by id to the caller.
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _hit(node: Node, hops: int, reason: str) -> Hit:
    """Record a reached node together with the evidence for reaching it.

    @param node the node the walk arrived at
    @param hops how far it stood from the seed
    @param reason the justification to show the reader
    @return the answer record, with force and cost copied off the node
    """
    # Return the answer record, with force and cost copied off the node to the caller.
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
    # Each seeds element is one Hit, concatenated in file, error, task, then explicit-rule order.
    seeds: list[Hit] = []
    # Select the guarded path only after `args.file` is satisfied.
    if args.file:
        # Compute seeds using seeds for file for later gather seeds logic.
        seeds += seeds_for_file(graph, args.file)
    # Select the guarded path only after `args.error` is satisfied.
    if args.error:
        # Compute seeds using seeds for error for later gather seeds logic.
        seeds += seeds_for_error(graph, args.error)
    # Select the guarded path only after `args.task` is satisfied.
    if args.task:
        # Compute seeds using seeds for task for later gather seeds logic.
        seeds += seeds_for_task(graph, args.task)
    # Select rule id as the current element from args.rule or [] while gather seeds preserves
    # Details: traversal order.
    # Advance gather seeds through the current input element in declared order.
    for rule_id in args.rule or []:
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(rule_id)
        # Use the available-value path only when node is present.
        if node is not None:
            seeds.append(_hit(node, 0, "named on the command line"))

    # Each by-id key is a node id and each value is its nearest Hit; mapping key order is
    # deliberately unused.
    by_id: dict[str, Hit] = {}
    # Select hit as the current element from seeds while gather seeds preserves traversal order.
    # Advance gather seeds through the current input element in declared order.
    for hit in seeds:
        # Preserve the documentation-stripped behavior fingerprint used for comparison.
        current = by_id.get(hit.id)
        # Select the guarded path only after `current is None or hit.hops < current.hops` is
        # Details: satisfied.
        if current is None or hit.hops < current.hops:
            # Update  gather seeds state only after the required source facts are available.
            by_id[hit.id] = hit
    # Return the merged seeds by node id to the caller.
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
        Each element is one selected-rule Hit in plan order.
    @param modules the modules selected in their own right
        Each element is one directly selected module Hit in plan order.
    @return each module id mapped to its nearest hop and the number of selected
        rules it owns
    """
    # Each relevance key is a module id and each value is nearest hops then owned-rule count;
    # mapping key order is deliberately unused because callers sort explicitly.
    relevance: dict[str, tuple[int, int]] = {}
    # Select hit as the current element from rules while module relevance preserves traversal
    # Details: order.
    # Advance module relevance through the current input element in declared order.
    for hit in rules:
        # Compute owner using graph.nodes[hit.id].attr("module") if hit.id in graph.nodes  for
        # Details: later module relevance logic.
        owner = graph.nodes[hit.id].attr("module") if hit.id in graph.nodes else None
        # Use the absence path when owner has no available value.
        if owner is None:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Preserve the observed item count used by the non-vacuity verdict.
        hops, count = relevance.get(owner, (99, 0))
        # Update  module relevance state only after the required source facts are available.
        relevance[owner] = (min(hops, hit.hops), count + 1)
    # Select hit as the current element from modules while module relevance preserves traversal
    # Details: order.
    # Advance module relevance through the current input element in declared order.
    for hit in modules:
        # Preserve the observed item count used by the non-vacuity verdict.
        hops, count = relevance.get(hit.id, (99, 0))
        # Update  module relevance state only after the required source facts are available.
        relevance[hit.id] = (min(hops, hit.hops), count)
    # Return each module id mapped to its nearest hop and the number of selected to the caller.
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
    # Compute by id using  gather seeds for later cmd context logic.
    by_id = _gather_seeds(graph, args)

    # Compute reached using graph.expand for later cmd context logic.
    reached = graph.expand(
        sorted(by_id), types=READING_EXPANSION, depth=args.depth, undirected=False
    )
    # Select hops, node id as the current element from sorted(reached.items()) while cmd context
    # Details: preserves traversal order.
    # Advance cmd context through the current input element in declared order.
    for node_id, hops in sorted(reached.items()):
        # Select the guarded path only after `node_id in by_id` is satisfied.
        if node_id in by_id:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(node_id)
        # Select the guarded path only after `node is None or node.type not in {NodeType.RULE,
        # Details: NodeType.MODULE}` is satisfied.
        if node is None or node.type not in {NodeType.RULE, NodeType.MODULE}:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Update cmd context state only after the required source facts are available.
        by_id[node_id] = _hit(node, hops, f"{hops} hop(s) from a seed")

    # Unpack rules, h using annotate for later cmd context logic.
    rules = annotate(
        sorted(
            (h for h in by_id.values() if h.type == "rule"),
            key=lambda h: (h.hops, _force_rank(h.force), h.id),
        ),
        Path(getattr(args, "root", REPO_ROOT)).resolve(),
    )
    # Unpack modules, h using sorted for later cmd context logic.
    modules = sorted(
        (h for h in by_id.values() if h.type == "module"), key=lambda h: (h.hops, h.id)
    )
    # Compute relevance using  module relevance for later cmd context logic.
    relevance = _module_relevance(graph, rules, modules)
    # Compute ordered using sorted for later cmd context logic.
    ordered = sorted(
        relevance,
        key=lambda m: (relevance[m][0], -relevance[m][1], graph.nodes[m].tokens, m),
    )
    # Select cost, m as the current element from ordered if m in graph.nodes) while cmd context
    # Details: preserves traversal order.
    cost = sum(graph.nodes[m].tokens for m in ordered if m in graph.nodes)
    # Compute plan using  fit budget for later cmd context logic.
    plan = _fit_budget(graph, ordered, args.budget)
    # Bind h, p to the current value used by the next cmd context decision.
    # Return the seeds, the selected rules, the modules to read, both costs, and to the caller.
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
        Each element is one selected node id in retrieval-key order.
    @return one line per claim, or nothing at all when the database is absent,
        unreadable or empty on this situation

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        import learn
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except ImportError:
        # Return one line per claim, or nothing at all when the database is absent, to the
        # Details: caller.
        return []
    # Compute store using learn.Store for later learnings for logic.
    store = learn.Store(Path(getattr(args, "root", REPO_ROOT)).resolve())
    # Select the existing-artifact path only when `not store.ledger.exists()` is satisfied.
    if not store.ledger.exists():
        # Return one line per claim, or nothing at all when the database is absent, to the
        # Details: caller.
        return []
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute connection using learn.sync for later learnings for logic.
        connection = learn.sync(store)
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except (learn.LearnError, OSError):
        # Return one line per claim, or nothing at all when the database is absent, to the
        # Details: caller.
        return []
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve the optional pattern match that carries the reported analysis count.
        found = learn.retrieve(
            store,
            connection,
            file=getattr(args, "file", None),
            error=getattr(args, "error", None),
            task=getattr(args, "task", None),
            rules=[r for r in selected if _RULE_ID.fullmatch(r)],
        )
    finally:
        # Publish the externally visible effect after all required inputs are ready.
        connection.close()
    # Select c as the current element from found] while learnings for preserves traversal order.
    # Return one line per claim, or nothing at all when the database is absent, to the caller.
    return [f"{c.id} [{c.status} {c.effective:.2f}] {c.claim} -> {c.action}" for c in found]


def _force_rank(force: str | None) -> int:
    """Sort key that shows what binds before what merely advises.

    @param force the declared force, or None on a node that has none
    @return the rank, lower sorting first, with anything unrecognised last
    """
    # Return the rank, lower sorting first, with anything unrecognised last to the caller.
    return {"BINDING": 0, "OPEN": 1, "ADVISORY": 2}.get(force or "", 3)


def _fit_budget(graph: Graph, module_ids: Sequence[str], budget: int) -> list[dict[str, object]]:
    """Pack in the order given -- most relevant first -- and mark the overflow.

    Modules that do not fit are still listed, so an agent can see what it is
    choosing not to read rather than being handed a silently truncated plan.
    The first module is always taken, even when it alone exceeds the budget: an
    empty plan would answer nothing.

    @param graph the discipline graph
    @param module_ids the modules to pack, most relevant first
        Each element is one module id in descending relevance order.
    @param budget the token ceiling the plan aims to stay under
    @return one entry per module the graph knows, each marked `read` or
        `deferred`, in the order it was offered; an id with no node is dropped
        rather than priced at zero
    """
    # Each plan element is one id/token/status record in offered module order.
    plan: list[dict[str, object]] = []
    # Compute spent using 0 for later fit budget logic.
    spent = 0
    # Select module id as the current element from module_ids while fit budget preserves
    # Details: traversal order.
    # Advance fit budget through the current input element in declared order.
    for module_id in module_ids:
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(module_id)
        # Use the absence path when node has no available value.
        if node is None:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `plan and spent + node.tokens > budget` is
        # Details: satisfied.
        if plan and spent + node.tokens > budget:
            plan.append({"id": node.id, "tokens": node.tokens, "status": "deferred"})
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute spent using node.tokens for later fit budget logic.
        spent += node.tokens
        plan.append({"id": node.id, "tokens": node.tokens, "status": "read"})
    # Return one entry per module the graph knows, each marked `read` or to the caller.
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

    # Each found key is a rule id and each value is its parsed Rule; mapping key order is
    # deliberately unused.
    found: dict[str, object] = {}
    # Traverse parsed documents and their rules in stable corpus order.
    # Advance rules by id through the current input element in declared order.
    for document in iter_documents(root / "discipline"):
        # Select rule as the current element from document.rules while rules by id preserves
        # Details: traversal order.
        # Advance rules by id through the current input element in declared order.
        for rule in document.rules:
            # Update rules by id state only after the required source facts are available.
            found[rule.rule_id] = rule
    # Return each rule id against its parsed `Rule` to the caller.
    return found


def envelope_ids(payload: dict[str, object]) -> list[str]:
    """The rules a diagnostic envelope names outright.

    `DIAG-001`'s envelope carries `rule_ids` precisely so a failure can say which
    contract it broke. Reading them is the difference between a lookup and a
    derivation, and it is the hop the Prime Directive was missing.

    @param payload a parsed envelope
        Each key is an envelope field and each value is its decoded content; mapping key order is
        deliberately unused.
    @return the rule ids it names, in order, empty when it names none
    """
    # Compute named using payload.get for later envelope ids logic.
    named = payload.get("rule_ids") or []
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Return the rule ids it names, in order, empty when it names none to the caller.
    return [str(entry) for entry in named] if isinstance(named, list) else []


def _read_envelope(source: str | None) -> dict[str, object]:
    """Parse a serialized envelope from a path, or from stdin when given `-`.

    @param source the path, `-` for stdin, or None when the caller passed none
    @return the parsed envelope, empty when there was nothing to read
    @throws SystemExit when the text is not JSON, because a malformed envelope
        that fell through as an empty one would read as "this failure names no
        rule", which is a claim nobody made
    """
    # Use the absence path when source has no available value.
    if source is None:
        # Return the parsed envelope, empty when there was nothing to read to the caller.
        return {}
    # Retain the immutable source representation consumed by subsequent analysis.
    raw = sys.stdin.read() if str(source) == "-" else Path(source).read_text(encoding="utf-8")
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Compute parsed using json.loads for later read envelope logic.
        parsed = json.loads(raw)
    # Preserve the caught failure that explains why the external result is unusable.
    # Translate the expected failure into this mechanism's stable diagnostic path.
    except json.JSONDecodeError as broken:
        # Compute message using f"the envelope is not JSON: {broken}" for later read envelope
        # Details: logic.
        message = f"the envelope is not JSON: {broken}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise SystemExit(message) from broken
    # Return the parsed envelope, empty when there was nothing to read to the caller.
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
        Each key is an envelope field and each value is its decoded content; mapping key order is
        deliberately unused.
    @param text raw error text, possibly empty
    @return the implicated nodes by id
    """
    # Each found key is an implicated node id and each value is its strongest diagnostic Hit;
    # mapping key order is deliberately unused.
    found: dict[str, Hit] = {}
    # Select rule id as the current element from envelope_ids(envelope) while diagnostic seeds
    # Details: preserves traversal order.
    # Advance diagnostic seeds through the current input element in declared order.
    for rule_id in envelope_ids(envelope):
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(rule_id)
        # Use the available-value path only when node is present.
        if node is not None:
            # Update  diagnostic seeds state only after the required source facts are available.
            found[node.id] = _hit(node, 0, "named by the envelope")
    # Handle the non-empty or enabled found state.
    if found:
        # Return the implicated nodes by id to the caller.
        return found

    # Unpack prose, field using " ".join( for later diagnostic seeds logic.
    prose = " ".join(
        str(envelope.get(field, ""))
        for field in ("code", "operation", "expected", "actual", "notes")
    )
    # Select hit as the current element from seeds_for_error(graph, f"{text} {prose}".strip())
    # Details: while diagnostic seeds preserves traversal order.
    # Advance diagnostic seeds through the current input element in declared order.
    for hit in seeds_for_error(graph, f"{text} {prose}".strip()):
        found.setdefault(hit.id, hit)
    # Return the implicated nodes by id to the caller.
    return found


def _rule_answer(hit: Hit, node: Node, rule: object, verification: str | None) -> dict[str, object]:
    """One rule laid out as an answer: what it says, why, and what decides it.

    @param hit how the rule was reached
    @param node its graph node, carrying the force tag and reading cost
    @param rule its parsed form, carrying the words
    @param verification measured verifier availability, kept separate from force
    @return the fields a caller needs to act without opening the module
    """
    # Return the fields a caller needs to act without opening the module to the caller.
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
    # Compute envelope using  read envelope for later cmd diagnose logic.
    envelope = _read_envelope(args.envelope)
    # Retain the immutable source representation consumed by subsequent analysis.
    text = args.error or ""
    # Select the empty-or-disabled path when (envelope or text) has no usable value.
    if not (envelope or text):
        # Compute message using "diagnose needs --envelope or --error" for later cmd diagnose
        # Details: logic.
        message = "diagnose needs --envelope or --error"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise SystemExit(message)

    # Resolve the repository-confined path used by this operation before filesystem access.
    root = Path(args.root).resolve()
    # Preserve the optional pattern match that carries the reported analysis count.
    found = _diagnostic_seeds(graph, envelope, text)
    # Compute parsed using rules by id for later cmd diagnose logic.
    parsed = rules_by_id(root)
    # Capture status as the completed cmd diagnose outcome for subsequent validation or
    # Details: publication.
    status = verification_index(root)

    # Each implicated element is one rendered diagnostic record in hops/type/id rank order.
    implicated: list[dict[str, object]] = []
    # Select hit as the current element from sorted(found.values(), key=lambda h while cmd
    # Details: diagnose preserves traversal order.
    # Advance cmd diagnose through the current input element in declared order.
    for hit in sorted(found.values(), key=lambda h: (h.hops, h.id)):
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(hit.id)
        # Compute rule using parsed.get for later cmd diagnose logic.
        rule = parsed.get(hit.id)
        # Select the guarded path only after `hit.type == 'rule' and node is not None and (rule
        # Details: is not None)` is satisfied.
        if hit.type == "rule" and node is not None and rule is not None:
            implicated.append(_rule_answer(hit, node, rule, status.get(hit.id)))

    # Collect unique reached element values; their order is deliberately unordered.
    reached = {entry["id"] for entry in implicated}
    # Treat the current entry, r as the candidate element consumed by the enclosing
    # Details: transformation.
    # Return the implicated rules with their text, the envelope's own remediation to the caller.
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
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    node = _require(graph, args.id)
    # Compute verification using verification index for later cmd rule logic.
    verification = verification_index(Path(getattr(args, "root", REPO_ROOT)).resolve()).get(node.id)
    # Compute caveat using  VERIFICATION CAVEAT.get for later cmd rule logic.
    caveat = _VERIFICATION_CAVEAT.get(verification or "")
    # Each out key is an outgoing edge type and each value lists described targets in graph edge
    # order; first-seen edge-type order is preserved for rendering.
    out: dict[str, list[str]] = {}
    # Select edge as the current element from graph.out_edges(node.id) while cmd rule preserves
    # Details: traversal order.
    # Advance cmd rule through the current input element in declared order.
    for edge in graph.out_edges(node.id):
        out.setdefault(str(edge.type), []).append(_describe(graph, edge.dst, edge))
    # Each incoming key is an incoming edge type and each value lists described sources in graph
    # edge order; first-seen edge-type order is preserved for rendering.
    incoming: dict[str, list[str]] = {}
    # Select edge as the current element from graph.in_edges(node.id) while cmd rule preserves
    # Details: traversal order.
    # Advance cmd rule through the current input element in declared order.
    for edge in graph.in_edges(node.id):
        incoming.setdefault(str(edge.type), []).append(_describe(graph, edge.src, edge))
    # Bind k, v to the current value used by the next cmd rule decision.
    # Return the node's identity and its relations, outgoing and incoming to the caller.
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
    # Select t, types as the current element from args.type] if args.type else None while cmd
    # Details: neighbors preserves traversal order.
    types = [EdgeType(t) for t in args.type] if args.type else None
    # Compute reached using graph.expand for later cmd neighbors logic.
    reached = graph.expand([args.id], types=types, depth=args.depth, undirected=args.undirected)
    # Bind hops, nid to the current value used by the next cmd neighbors decision.
    # Return the reached nodes with their hop distance, the start node excluded to the caller.
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
    # Compute hits using annotate for later cmd applies logic.
    hits = annotate(seeds_for_file(graph, args.path), Path(args.root).resolve())
    # Bind h to the current value used by the next cmd applies decision.
    # Return the path, the rules that bind it, and the modules that carry them to the caller.
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
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    node = _require(graph, args.id)
    # Bind e to the current value used by the next cmd why decision.
    # Return the rule with each provenance relation listed separately, empty to the caller.
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
    # Preserve the optional pattern match that carries the reported analysis count.
    found = graph.shortest_path(args.src, args.dst)
    # Use the absence path when found has no available value.
    if found is None:
        # Preserve the optional pattern match that carries the reported analysis count.
        found = graph.shortest_path(args.dst, args.src)
        # Use the available-value path only when found is present.
        if found is not None:
            # Preserve the optional pattern match that carries the reported analysis count.
            found = list(reversed(found))
    # Bind e to the current value used by the next cmd path decision.
    # Return whether a route was found and the edges it crosses, in order to the caller.
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
    # Each items element is one requested node's owner/token record in argument order.
    items: list[dict[str, object]] = []
    # Compute total using 0 for later cmd budget logic.
    total = 0
    # Select node id as the current element from args.ids while cmd budget preserves traversal
    # Details: order.
    # Advance cmd budget through the current input element in declared order.
    for node_id in args.ids:
        # Treat the current node as the candidate element consumed by the enclosing
        # Details: transformation.
        node = graph.nodes.get(node_id)
        # Use the absence path when node has no available value.
        if node is None:
            items.append({"id": node_id, "tokens": 0, "status": "unknown"})
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Compute owner using node.attr for later cmd budget logic.
        owner = node.attr("module") if node.type is NodeType.RULE else node.id
        # Resolve the repository-confined path used by this operation before filesystem access.
        target = graph.nodes.get(owner or node.id)
        # Compute tokens using target.tokens if target else 0 for later cmd budget logic.
        tokens = target.tokens if target else 0
        items.append({"id": node_id, "reads": owner, "tokens": tokens})
        # Compute total using tokens for later cmd budget logic.
        total += tokens
    # Return one item per id, naming what is actually read, and the total to the caller.
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
    # Compute unreachable using graph.unreachable from for later cmd stats logic.
    unreachable = graph.unreachable_from(_kernel_seeds(graph), NodeType.RULE, depth=args.depth)
    # Compute total using len for later cmd stats logic.
    total = len(graph.of_type(NodeType.RULE))
    # Each nodes key is a node-type label and each value is its count; mapping key order follows
    # first graph occurrence for stable rendering.
    nodes: dict[str, int] = {}
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    # Advance cmd stats through the current input element in declared order.
    for node in graph.nodes.values():
        # Update cmd stats state only after the required source facts are available.
        nodes[str(node.type)] = nodes.get(str(node.type), 0) + 1
    # Each edges key is an edge-type label and each value is its count; mapping key order follows
    # first graph occurrence for stable rendering.
    edges: dict[str, int] = {}
    # Select edge as the current element from graph.edges while cmd stats preserves traversal
    # Details: order.
    # Advance cmd stats through the current input element in declared order.
    for edge in graph.edges:
        # Update cmd stats state only after the required source facts are available.
        edges[str(edge.type)] = edges.get(str(edge.type), 0) + 1
    # Return the node and edge census, the reachable fraction, and the ids of any to the caller.
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
    # Preserve the observed item count used by the non-vacuity verdict.
    # Return the module ids, sorted, as the seed set for a reachability measure to the caller.
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
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    node = graph.nodes.get(node_id)
    # Use the absence path when node has no available value.
    if node is None:
        # Compute message using f"unknown node {node_id!r}" for later require logic.
        message = f"unknown node {node_id!r}"
        # Propagate the localized failure so callers cannot mistake it for success.
        raise SystemExit(message)
    # Return the node it names to the caller.
    return node


def _describe(graph: Graph, node_id: str, edge: Edge) -> str:
    """Name one end of an edge in a line, qualified by whatever the edge records.

    @param graph the discipline graph
    @param node_id the endpoint being reported
    @param edge the relation it was reached through, whose note qualifies it
    @return the id with its title, degrading to the bare id when the endpoint
        does not resolve
    """
    # Treat the current node as the candidate element consumed by the enclosing transformation.
    node = graph.nodes.get(node_id)
    # Compute label using f"{node_id} - {node.label}" if node else node_id for later describe
    # Details: logic.
    label = f"{node_id} - {node.label}" if node else node_id
    # Return the id with its title, degrading to the bare id when the endpoint to the caller.
    return f"{label} [{edge.note}]" if edge.note else label


# ---------------------------------------------------------------------- output


def _render_context(payload: dict[str, object]) -> list[str]:
    """The reading plan: what governs the situation, what to read, what it costs.

    @param payload the `context` answer
        Each key is a context-response field and each value is its command result; mapping key
        order is deliberately unused.
    @return the lines to print
    """
    # The two assigned elements are ordered as displayed-rule count then total-rule count.
    shown, total = payload["rules_shown"], payload["rules_total"]
    # Compute suffix using f" of {total} - raise --max-rules to see the rest" if shown  for
    # Details: later render context logic.
    suffix = f" of {total} - raise --max-rules to see the rest" if shown < total else ""
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [f"RULES ({shown}{suffix})"]
    # Select rule as the current element from payload["rules"] while render context preserves
    # Details: traversal order.
    # Advance render context through the current input element in declared order.
    for rule in payload["rules"]:  # type: ignore[union-attr]
        # Compute tag using force tag for later render context logic.
        tag = force_tag(rule["force"], rule.get("verification"))
        lines.append(f"  {rule['id']:<10} {tag:<32} {rule['label']}")
        lines.append(f"  {'':<10} {'':<32} ~ {rule['reason']}")
    lines.append("")
    lines.append("READ")
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Advance render context through the current input element in declared order.
    for item in payload["read"]:  # type: ignore[union-attr]
        # Compute mark using " " if item["status"] == "read" else "!" for later render context
        # Details: logic.
        mark = " " if item["status"] == "read" else "!"
        lines.append(f" {mark} {item['id']:<22} {item['tokens']:>6} tok  {item['status']}")
    lines.append("")
    lines.append(
        f"BUDGET  planned {payload['tokens_planned']} tok"
        f"  (all candidates {payload['tokens_if_all']} tok)"
    )
    # Select the guarded path only after `payload.get('learnings')` is satisfied.
    if payload.get("learnings"):
        lines.append("")
        lines.append("LEARNED")
        # Preserve item, lines element values in deterministic source order.
        lines += [f"  {item}" for item in payload["learnings"]]  # type: ignore[union-attr]
    # Return the lines to print to the caller.
    return lines


def _render_applies(payload: dict[str, object]) -> list[str]:
    """Every rule and module that governs one path.

    @param payload the `applies` answer
        Each key is an applies-response field and each value is its command result; mapping key
        order is deliberately unused.
    @return the lines to print
    """
    # Compute rules using payload["rules"] for later render applies logic.
    rules = payload["rules"]
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [f"{payload['path']}  ({len(rules)} rules)"]  # type: ignore[arg-type]
    # Select rule as the current element from rules while render applies preserves traversal
    # Details: order.
    # Advance render applies through the current input element in declared order.
    for rule in rules:  # type: ignore[union-attr]
        lines.append(
            f"  {rule['id']:<10} "
            f"{force_tag(rule['force'], rule.get('verification')):<32}"
            f" {rule['label']}   ~ {rule['reason']}"
        )
    # Preserve lines, module element values in deterministic source order.
    lines += [f"  {module['id']:<20} ~ {module['reason']}" for module in payload["modules"]]  # type: ignore[union-attr]
    # Return the lines to print to the caller.
    return lines


def _render_node(payload: dict[str, object]) -> list[str]:
    """One node and its edges, grouped by edge type.

    Shared by `rule` and `why`: the two differ in which edges they select, not in
    how the result reads.

    @param payload the `rule` or `why` answer
        Each key is a rule-response field and each value is its command result; mapping key order
        is deliberately unused.
    @return the lines to print
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [f"{payload['id']} - {payload.get('label', '')}"]
    # Treat the current key, value as the candidate element consumed by the enclosing
    # Details: transformation.
    # Advance render node through the current input element in declared order.
    for key, value in payload.items():
        # Select the guarded path only after `key in {'id', 'label', 'type'} or not value` is
        # Details: satisfied.
        if key in {"id", "label", "type"} or not value:
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Select the guarded path only after `isinstance(value, dict)` is satisfied.
        if isinstance(value, dict):
            # Preserve governed Python-path elements in deterministic traversal order.
            # Advance render node through the current input element in declared order.
            for edge_type, targets in value.items():
                lines.append(f"  {edge_type}:")
                # Preserve lines, t element values in deterministic source order.
                lines += [f"    {t}" for t in targets]
        # Select the guarded path only after `isinstance(value, list)` is satisfied.
        elif isinstance(value, list):
            lines.append(f"  {key}:")
            # Preserve lines, t element values in deterministic source order.
            lines += [f"    {t}" for t in value]
        else:
            lines.append(f"  {key}: {value}")
    # Return the lines to print to the caller.
    return lines


def _render_stats(payload: dict[str, object]) -> list[str]:
    """Node and edge census, and the reachability figure V092 gates on.

    @param payload the `stats` answer
        Each key is a statistics-response field and each value is its count or summary; mapping
        key order is deliberately unused.
    @return the lines to print
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        "NODES  " + ", ".join(f"{k}={v}" for k, v in payload["nodes"].items()),  # type: ignore[union-attr]
        "EDGES  " + ", ".join(f"{k}={v}" for k, v in payload["edges"].items()),  # type: ignore[union-attr]
        f"REACH  {payload['rules_reachable']}/{payload['rules_total']} rules "
        f"within {payload['reach_depth']} hops",
    ]
    # Select the guarded path only after `payload['unreachable']` is satisfied.
    if payload["unreachable"]:
        lines.append("  unreachable: " + ", ".join(payload["unreachable"]))  # type: ignore[union-attr]
    # Return the lines to print to the caller.
    return lines


## The per-command layouts. A command absent from this table falls back to
## indented JSON, so a new subcommand prints something legible before anyone
## writes its renderer.
def _render_diagnose(payload: dict[str, object]) -> list[str]:
    """Lay a diagnosis out as an answer, not as a reading list.

    @param payload what `cmd_diagnose` produced
        Each key is a diagnosis-response field and each value is its command result; mapping key
        order is deliberately unused.
    @return the lines to print
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines: list[str] = []
    # Select the guarded path only after `payload.get('code')` is satisfied.
    if payload.get("code"):
        # Compute where using f" in the {payload['layer']} layer" if payload.get("layer")  for
        # Details: later render diagnose logic.
        where = f" in the {payload['layer']} layer" if payload.get("layer") else ""
        lines.append(f"{payload['code']}{where}")
    # Select the guarded path only after `payload.get('reported_remediation')` is satisfied.
    if payload.get("reported_remediation"):
        # Preserve lines element values in deterministic source order.
        lines += ["", f"REPORTED  {payload['reported_remediation']}"]

    # Compute rules using payload.get for later render diagnose logic.
    rules = payload.get("rules") or []
    # Select the empty-or-disabled path when rules has no usable value.
    if not rules:
        # Preserve lines element values in deterministic source order.
        lines += [
            "",
            "no rule in the corpus matched this output.",
            "Add a signature to enforce/signals.toml if this shape recurs.",
        ]
        # Return the lines to print to the caller.
        return lines

    lines.append("")
    # Select rule as the current element from rules while render diagnose preserves traversal
    # Details: order.
    # Advance render diagnose through the current input element in declared order.
    for rule in rules:  # type: ignore[union-attr]
        # Preserve lines element values in deterministic source order.
        lines += [
            f"{rule['id']} {rule['force']}  {rule['title']}",
            f"    {rule['statement']}",
        ]
        # Select the guarded path only after `rule.get('why')` is satisfied.
        if rule.get("why"):
            lines.append(f"    why    {rule['why']}")
        # Select the guarded path only after `rule.get('check')` is satisfied.
        if rule.get("check"):
            lines.append(f"    check  {rule['check']}")
        # Preserve lines element values in deterministic source order.
        lines += [f"    open   {rule['open']}  ({rule['module']})", ""]
    lines.append(f"COST  {payload['tokens']} tok -- {len(rules)} rule(s), read in full")
    # Select the guarded path only after `payload.get('unresolved')` is satisfied.
    if payload.get("unresolved"):
        # Compute named using ", ".join(payload["unresolved"])  # type: ignore[arg-type] for
        # Details: later render diagnose logic.
        named = ", ".join(payload["unresolved"])  # type: ignore[arg-type]
        lines.append(f"UNRESOLVED  {named} -- named by the envelope, absent here")
    # Return the lines to print to the caller.
    return lines


## Which renderer lays out which command's payload. A table rather than a chain
## of conditionals, because the chain was over `C901`'s ceiling and `ARCH-016` is
## enforced through that exact code. A command absent from here falls back to
## JSON, which is readable if not shaped.
## Each key is a subcommand name and each value is its text renderer; mapping key order is
## deliberately unused.
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
        Each key is a command-response field and each value is its result; mapping key order is
        deliberately unused.
    @return the text to print, with no trailing newline
    """
    # Compute renderer using  RENDERERS.get for later render logic.
    renderer = _RENDERERS.get(command)
    # Use the absence path when renderer has no available value.
    if renderer is None:
        # Return the text to print, with no trailing newline to the caller.
        return json.dumps(payload, indent=1, ensure_ascii=False)
    # Return the text to print, with no trailing newline to the caller.
    return "\n".join(renderer(payload))


def build_parser() -> argparse.ArgumentParser:
    """Assemble the command grammar, one subparser per question an agent asks.

    @return a parser that refuses to run without a subcommand, since there is no
        sensible default walk
    """
    # Configure the command-line parser that defines this tool's invocation contract.
    parser = argparse.ArgumentParser(description="Walk the discipline graph.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    # Compute sub using parser.add subparsers for later build parser logic.
    sub = parser.add_subparsers(dest="command", required=True)

    # Compute ctx using sub.add parser for later build parser logic.
    ctx = sub.add_parser("context", help="the reading plan for a situation")
    ctx.add_argument("--file")
    ctx.add_argument("--error")
    ctx.add_argument("--task")
    ctx.add_argument("--rule", action="append")
    ctx.add_argument("--depth", type=int, default=1)
    ctx.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ctx.add_argument("--max-rules", type=int, default=20)

    # Compute rule using sub.add parser for later build parser logic.
    rule = sub.add_parser("rule", help="one rule and its neighbourhood")
    rule.add_argument("id")

    # Compute nb using sub.add parser for later build parser logic.
    nb = sub.add_parser("neighbors", help="breadth-first walk from a node")
    nb.add_argument("id")
    nb.add_argument("--type", action="append")
    nb.add_argument("--depth", type=int, default=1)
    nb.add_argument("--undirected", action="store_true")

    # Compute dg using sub.add parser for later build parser logic.
    dg = sub.add_parser("diagnose", help="what broke, against which rule, and what to do")
    dg.add_argument("--envelope", help="a serialized diagnostic envelope, or - for stdin")
    dg.add_argument("--error", help="raw error text, when there is no envelope")

    # Compute ap using sub.add parser for later build parser logic.
    ap = sub.add_parser("applies", help="rules governing a file")
    ap.add_argument("path")

    # Compute why using sub.add parser for later build parser logic.
    why = sub.add_parser("why", help="why a rule has the shape it has")
    why.add_argument("id")

    # Compute pth using sub.add parser for later build parser logic.
    pth = sub.add_parser("path", help="how two nodes connect")
    pth.add_argument("src")
    pth.add_argument("dst")

    # Compute bud using sub.add parser for later build parser logic.
    bud = sub.add_parser("budget", help="token cost of a reading set")
    bud.add_argument("ids", nargs="+")

    # Compute st using sub.add parser for later build parser logic.
    st = sub.add_parser("stats", help="graph shape and reachability")
    st.add_argument("--depth", type=int, default=3)
    # Return a parser that refuses to run without a subcommand, since there is no to the caller.
    return parser


## Subcommand name to the handler that answers it. The keys must be exactly the
## strings the parser accepts: a subcommand the parser gained but this map lacks
## raises KeyError at dispatch, and one added here alone is simply unreachable.
## Each key is an accepted subcommand and each value is its handler; mapping key order is
## deliberately unused.
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


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
