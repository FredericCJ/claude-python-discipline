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
    # Read verifier availability from the generated index owned by the selected repository.
    path = root / "discipline" / "rules.json"
    # Missing or malformed generated state degrades to an unannotated answer.
    try:
        # Decode generated-index field keys to their JSON values; mapping key order is
        # deliberately unused.
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Do not infer verifier availability when the measured index cannot be trusted.
        return {}
    # Accept only the documented top-level object shape before iterating its rule records.
    rules = payload.get("rules", []) if isinstance(payload, dict) else []
    # Each found key is a rule id and each value is its verification state; mapping key order is
    # deliberately unused.
    found: dict[str, str] = {}
    # Extract only typed rule/state records; unrelated generated fields remain ignored.
    for rule in rules:
        # Reject malformed rule records before accessing their stable identity.
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            # Exclude this record without allowing its partial fields into the availability index.
            continue
        # Verification must itself be an object before its state can be interpreted.
        verification = rule.get("verification")
        if not isinstance(verification, dict):
            # Exclude rules whose generated verification field has no structured state.
            continue
        # Retain only textual states because caveat rendering uses a closed string vocabulary.
        state = verification.get("state")
        if isinstance(state, str):
            # Index the measured availability by the rule id carried in the same record.
            found[rule["id"]] = state
    # Expose the validated subset without fabricating entries for malformed records.
    return found


def annotate(hits: Iterable[Hit], root: Path) -> list[Hit]:
    """Attach each rule's verifier-availability state to the answer.

    @param hits the answer records to annotate, in the order they will be shown
    @param root the repository root whose generated index supplies the statuses
    @return the same records in the same order, rules carrying their status
    """
    # Snapshot verifier states once, then preserve answer order while enriching rule hits.
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
    # Nodes with no normative force need neither brackets nor a verifier caveat.
    if not force:
        # Empty text lets every renderer concatenate tags without a special separator case.
        return ""
    # Map non-automated availability to the exact warning readers must see beside force.
    caveat = _VERIFICATION_CAVEAT.get(verification or "")
    # Automated or unknown availability leaves force plain; known residual states stay explicit.
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
    # Preserve an absent graph location without attempting path or suffix parsing.
    if not stored:
        # Empty input represents a node with no openable source location.
        return stored
    # Split a numeric trailing line while leaving colons inside ordinary path text untouched.
    body, sep, line = stored.rpartition(":")
    # A nonnumeric suffix belongs to the path rather than to an editor line locator.
    if not (sep and line.isdigit()):
        # The two assigned elements are ordered as complete stored path then absent line locator.
        body, line = stored, ""
    # Resolve against the package root before expressing the location from the caller's cwd.
    absolute = (REPO_ROOT / body).resolve()
    # Prefer a portable relative path when the corpus lies beneath the caller's directory.
    try:
        # Retain POSIX spelling because graph locations are host-independent answer data.
        shown = absolute.relative_to(Path.cwd()).as_posix()
    # Fall back to an absolute location when no honest relative path exists.
    except ValueError:
        # Preserve an openable canonical path when cwd-relative representation is impossible.
        shown = absolute.as_posix()
    # Reattach a validated line suffix after path relocation rather than before it.
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
    # Normalize host separators once before layer and test-shape matching.
    parts = Path(path).as_posix().split("/")
    # Order is significant and the three differ in how they claim an id: a layer
    # match overwrites, the other two defer to whatever is already there. Running
    # them in this order is what makes "governs domain/" beat "matches **/*.py"
    # for the same rule.
    _seed_by_layer(graph, parts, found)
    _seed_test_law(graph, path, parts, found)
    _seed_by_glob(graph, path, found)
    # Resolve route collisions before returning deterministic nearest-first seed order.
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
    # Test every declared layer spelling because nested component paths may contain more than one.
    for layer in LAYERS:
        # Skip layers absent from the normalized path segments.
        if layer not in parts:
            # Continue because this layer contributes no applicability edge for the file.
            continue
        # Follow incoming applicability edges from the matched architectural-layer node.
        for edge in graph.in_edges(f"layer:{layer}", [EdgeType.APPLIES_TO]):
            # Resolve the owning rule or module defensively against stale graph edges.
            node = graph.nodes.get(edge.src)
            if node is not None:
                # A direct layer match overwrites weaker routes to the same node.
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
    # Files with neither a test directory nor pytest naming do not activate the testing law.
    if "tests" not in parts and not Path(path).name.startswith("test_"):
        # Leave the shared seed accumulator unchanged for production files.
        return
    # Expand the testing law to every contained rule while respecting stronger layer claims.
    for edge in graph.out_edges("law/TEST", [EdgeType.CONTAINS]):
        # Ignore a stale containment edge whose target is absent from the node table.
        node = graph.nodes.get(edge.dst)
        if node is not None:
            # Test-law membership is direct evidence but does not overwrite an existing seed.
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
    # Match graph trigger labels against one host-independent path representation.
    posix = Path(path).as_posix()
    # Inspect only trigger nodes; their kind distinguishes globs from other routing channels.
    for node in graph.of_type(NodeType.TRIGGER):
        # Require both glob semantics and an actual path match before traversing ownership.
        if node.attr("kind") != "glob" or not fnmatch.fnmatch(posix, node.label):
            # Continue past non-glob triggers and globs that do not cover the normalized path.
            continue
        # Walk from the matching trigger back to the module that declared it.
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            # A malformed or non-module owner cannot be a file-reading-plan seed.
            owner = graph.nodes.get(edge.src)
            if owner is not None and owner.type is NodeType.MODULE:
                # Glob evidence is one hop away and therefore defers to direct layer evidence.
                found.setdefault(owner.id, _hit(owner, 1, f"matches {node.label}"))


def _normalize(text: str) -> set[str]:
    """Reduce text to the set of words it contains, separators flattened.

    `adapters-are-independent` and `adapters are independent` collapse to the
    same signature, so the punctuation an error happens to use cannot decide
    whether it matches a trigger.

    @param text prose, an identifier, or a tool's error phrase
    @return its lowercased words, deduplicated and unordered
    """
    # Flatten common identifier separators before producing the unordered signature vocabulary.
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
    # Prepare literal and separator-insensitive views of the same diagnostic once.
    lowered = text.lower()
    words = _normalize(text)
    # Compare every error trigger against both views without considering other trigger kinds.
    for node in graph.of_type(NodeType.TRIGGER):
        # Error signatures alone participate in this routing channel.
        if node.attr("kind") != "error":
            # Continue without interpreting another trigger family's label as diagnostic prose.
            continue
        # Normalize the configured signature for the multi-word containment fallback.
        signature = _normalize(node.label)
        # A code such as G004 matches literally; a phrase matches when all of its
        # words are present, so separator style does not decide the outcome.
        literal = node.label.lower() in lowered
        if not (literal or (len(signature) > 1 and signature <= words)):
            # Continue when neither literal nor conservative multi-word matching succeeds.
            continue
        # Attribute a matched signature to each rule or module that declared the trigger.
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            # Ignore stale owner edges without a node record.
            owner = graph.nodes.get(edge.src)
            if owner is not None:
                # Error text is direct evidence and overwrites weaker mechanism inference.
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
    # Extract citable rule identities in message order; duplicate assignments are harmless.
    for rule_id in _RULE_ID.findall(text):
        # Resolve only ids present in the current graph revision.
        node = graph.nodes.get(rule_id)
        if node is not None:
            # An explicit id is direct evidence and therefore overwrites weaker routes.
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
    # Infer a producing checker only from mechanism labels with a distinctive terminal stem.
    for node in graph.of_type(NodeType.MECHANISM):
        # Use the label segment after the final namespace separator as the diagnostic signature.
        stem = node.label.split(":")[-1]
        # Very short stems are too collision-prone to support mechanism inference.
        if len(stem) > 4 and stem.lower() in lowered:
            # Traverse from the identified checker back to the rules it enforces.
            for edge in graph.in_edges(node.id, [EdgeType.ENFORCED_BY]):
                # Ignore enforcement edges whose owning rule is absent.
                owner = graph.nodes.get(edge.src)
                if owner is not None:
                    # Mechanism evidence remains one hop away and never overwrites direct evidence.
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
    # Normalize ``-ies`` separately so plural and singular ``-y`` forms converge.
    if word.endswith(_PLURAL_Y) and len(word) - len(_PLURAL_Y) >= _MIN_STEM:
        # Restore the singular terminal ``y`` after enforcing the minimum stem length.
        return word[: -len(_PLURAL_Y)] + "y"
    # Apply the small inflection registry in priority order, longest suffix first.
    for suffix in ("ing", "ed", "es", "s"):
        # Strip only when the remaining topic stem is long enough to stay discriminating.
        if word.endswith(suffix) and len(word) - len(suffix) >= _MIN_STEM:
            # Return the first qualified inflection removal from longest to shortest suffix.
            return word[: -len(suffix)]
    # Preserve words that carry no qualified ordinary inflection.
    return word


def _content(text: str) -> set[str]:
    """The stemmed, topic-bearing words of a phrase.

    @param text a query or a router keyword
    @return its stems, with stopwords removed
    """
    # Stem each lexical token, deduplicate it, and remove vocabulary with no topic signal.
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
    # Reduce the caller's task to the topic-bearing stems used by router keywords.
    asked = _content(text)
    # Each found key is a reached module id and each value is its task-keyword Hit; mapping key
    # order is deliberately unused because results are explicitly sorted.
    found: dict[str, Hit] = {}
    # Evaluate every keyword trigger while excluding glob and error channels.
    for node in graph.of_type(NodeType.TRIGGER):
        # Only router keywords can seed modules from free-form task prose.
        if node.attr("kind") != "keyword":
            # Continue without mixing error and glob semantics into task-topic matching.
            continue
        # Normalize the configured keyword through the same stemmer as the task.
        parts = _content(node.label)
        # A keyword containing only stopwords provides no defensible topic evidence.
        if not parts:
            # Continue because an empty topic set cannot meet a meaningful overlap threshold.
            continue
        # Single-topic triggers need that topic; longer phrases require a strict rounded-up half.
        needed = 1 if len(parts) == 1 else -(-len(parts) // 2)
        # Reject keywords whose topic overlap falls below the calibrated discrimination threshold.
        if len(parts & asked) < needed:
            # Continue to the next keyword rather than weakening the threshold per query.
            continue
        # Attribute the matching keyword to each module that declared it.
        for edge in graph.in_edges(node.id, [EdgeType.TRIGGERED_BY]):
            # Only present owner nodes can become reading-plan seeds.
            owner = graph.nodes.get(edge.src)
            if owner is not None:
                # Preserve the first equal-strength keyword route for deterministic explanation.
                found.setdefault(owner.id, _hit(owner, 0, f"keyword {node.label!r}"))
    # Return direct module seeds in stable id order after all keyword collisions resolve.
    return sorted(found.values(), key=lambda h: (h.hops, h.id))


def _hit(node: Node, hops: int, reason: str) -> Hit:
    """Record a reached node together with the evidence for reaching it.

    @param node the node the walk arrived at
    @param hops how far it stood from the seed
    @param reason the justification to show the reader
    @return the answer record, with force and cost copied off the node
    """
    # Freeze graph identity, obligation, and reading cost beside the route evidence.
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
    # Add each supplied evidence channel in declared priority order.
    if args.file:
        # File shape contributes layer, test-law, and glob seeds.
        seeds += seeds_for_file(graph, args.file)
    # Diagnostic text contributes signatures, quoted ids, and producing mechanisms.
    if args.error:
        # Extend the merged seed sequence with diagnostic-derived evidence.
        seeds += seeds_for_error(graph, args.error)
    # Task prose contributes router-keyword module seeds.
    if args.task:
        # Extend the same sequence with topic-derived module evidence.
        seeds += seeds_for_task(graph, args.task)
    # Explicit rule ids are strongest caller evidence and remain hop-zero seeds.
    for rule_id in args.rule or []:
        # Ignore ids absent from this graph revision instead of inventing answer records.
        node = graph.nodes.get(rule_id)
        if node is not None:
            # Retain an explicit reason distinct from every inferred routing channel.
            seeds.append(_hit(node, 0, "named on the command line"))

    # Each by-id key is a node id and each value is its nearest Hit; mapping key order is
    # deliberately unused.
    by_id: dict[str, Hit] = {}
    # Collapse cross-channel duplicates while keeping the shortest evidentiary route.
    for hit in seeds:
        # Compare against the currently retained route for this node, if any.
        current = by_id.get(hit.id)
        if current is None or hit.hops < current.hops:
            # Replace only with strictly nearer evidence so equal-hop explanations stay stable.
            by_id[hit.id] = hit
    # Expose merged seeds by identity for subsequent graph expansion.
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
    # Attribute every selected rule to its declaring module and accumulate ownership strength.
    for hit in rules:
        # Read module identity from the current graph only when the selected node still exists.
        owner = graph.nodes[hit.id].attr("module") if hit.id in graph.nodes else None
        # Rules without a module cannot contribute to a module-reading budget.
        if owner is None:
            # Continue without inventing a reading unit or zero-cost owner.
            continue
        # Retain the nearest route and count one more selected rule owned by this module.
        hops, count = relevance.get(owner, (99, 0))
        relevance[owner] = (min(hops, hit.hops), count + 1)
    # Directly selected modules participate even when they own no selected rule.
    for hit in modules:
        # Merge direct module distance without altering its accumulated owned-rule count.
        hops, count = relevance.get(hit.id, (99, 0))
        relevance[hit.id] = (min(hops, hit.hops), count)
    # Expose the ranking inputs without imposing the caller's eventual ordering.
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
    # Merge all available evidence channels before expanding reading relationships.
    by_id = _gather_seeds(graph, args)

    # Traverse only declared reading edges to the requested bounded depth.
    reached = graph.expand(
        sorted(by_id), types=READING_EXPANSION, depth=args.depth, undirected=False
    )
    # Add newly reached rule and module nodes without replacing direct seed evidence.
    for node_id, hops in sorted(reached.items()):
        # Seed records already carry a more specific channel explanation.
        if node_id in by_id:
            # Preserve direct evidence rather than replacing it with generic graph distance.
            continue
        # Resolve the expanded identity and discard non-reading node categories.
        node = graph.nodes.get(node_id)
        if node is None or node.type not in {NodeType.RULE, NodeType.MODULE}:
            # Exclude stale ids and non-readable graph categories from the plan.
            continue
        # Record graph distance as the explanation for indirectly reached material.
        by_id[node_id] = _hit(node, hops, f"{hops} hop(s) from a seed")

    # Separate and force-rank rules before overlaying verifier availability.
    rules = annotate(
        sorted(
            (h for h in by_id.values() if h.type == "rule"),
            key=lambda h: (h.hops, _force_rank(h.force), h.id),
        ),
        Path(getattr(args, "root", REPO_ROOT)).resolve(),
    )
    # Keep directly or transitively selected modules nearest-first for relevance ranking.
    modules = sorted(
        (h for h in by_id.values() if h.type == "module"), key=lambda h: (h.hops, h.id)
    )
    # Rank module reads by distance, owned-rule density, cost, then stable identity.
    relevance = _module_relevance(graph, rules, modules)
    ordered = sorted(
        relevance,
        key=lambda m: (relevance[m][0], -relevance[m][1], graph.nodes[m].tokens, m),
    )
    # Compute unconstrained cost separately from the prefix that fits the caller's budget.
    cost = sum(graph.nodes[m].tokens for m in ordered if m in graph.nodes)
    plan = _fit_budget(graph, ordered, args.budget)
    # Publish bounded display slices while preserving totals needed to detect truncation.
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
    # Treat the optional learning subsystem as enrichment rather than a navigator dependency.
    try:
        import learn
    # A package without the learning module still produces the complete static reading plan.
    except ImportError:
        # Empty overlay is the explicit degraded result.
        return []
    # Bind the learning store to the same root whose static graph the caller queried.
    store = learn.Store(Path(getattr(args, "root", REPO_ROOT)).resolve())
    # Do not create state merely to answer navigation when no learning ledger exists.
    if not store.ledger.exists():
        # Preserve a purely static plan for repositories that have learned nothing yet.
        return []
    # Fold optional learned state, degrading cleanly when its authoritative record is unusable.
    try:
        # Retain the open derived projection for the one retrieval below.
        connection = learn.sync(store)
    except (learn.LearnError, OSError):
        # Static navigation remains authoritative even when learned enrichment cannot fold.
        return []
    # Retrieve contextual learnings and always close the temporary projection connection.
    try:
        # Pass only selected rule identities through the rule-trigger channel.
        found = learn.retrieve(
            store,
            connection,
            file=getattr(args, "file", None),
            error=getattr(args, "error", None),
            task=getattr(args, "task", None),
            rules=[r for r in selected if _RULE_ID.fullmatch(r)],
        )
    finally:
        # Release the optional SQLite resource on both successful and failed retrieval.
        connection.close()
    # Render one concise line per candidate while preserving retrieval rank.
    return [f"{c.id} [{c.status} {c.effective:.2f}] {c.claim} -> {c.action}" for c in found]


def _force_rank(force: str | None) -> int:
    """Sort key that shows what binds before what merely advises.

    @param force the declared force, or None on a node that has none
    @return the rank, lower sorting first, with anything unrecognised last
    """
    # Map known force levels to binding-first order and place unknown values last.
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
    # Track the accepted prefix cost; later modules never displace more relevant earlier ones.
    spent = 0
    # Evaluate module ids in relevance order and retain explicit overflow records.
    for module_id in module_ids:
        # Resolve graph metadata before assigning either cost or status.
        node = graph.nodes.get(module_id)
        # Unknown ids have no defensible cost and therefore disappear rather than becoming free.
        if node is None:
            # Continue after deliberately omitting this unresolved module from the plan.
            continue
        # After at least one read, mark every module that would cross the ceiling as deferred.
        if plan and spent + node.tokens > budget:
            plan.append({"id": node.id, "tokens": node.tokens, "status": "deferred"})
            # Preserve the overflow entry but do not charge it against the accepted prefix.
            continue
        # Admit the first or still-fitting module and advance the measured read cost.
        spent += node.tokens
        plan.append({"id": node.id, "tokens": node.tokens, "status": "read"})
    # Expose both accepted and deferred known modules in their original relevance order.
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
    for document in iter_documents(root / "discipline"):
        # Index every parsed rule by its globally stable id; duplicate ids are validated elsewhere.
        for rule in document.rules:
            # Store the complete parsed rule object needed by compact diagnosis answers.
            found[rule.rule_id] = rule
    # Expose parsed rule prose independently of graph node ordering.
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
    # Treat absent and null rule lists as the same explicit no-identities state.
    named = payload.get("rule_ids") or []
    # Preserve envelope order only for a genuine list; reject scalar lookalikes conservatively.
    return [str(entry) for entry in named] if isinstance(named, list) else []


def _read_envelope(source: str | None) -> dict[str, object]:
    """Parse a serialized envelope from a path, or from stdin when given `-`.

    @param source the path, `-` for stdin, or None when the caller passed none
    @return the parsed envelope, empty when there was nothing to read
    @throws SystemExit when the text is not JSON, because a malformed envelope
        that fell through as an empty one would read as "this failure names no
        rule", which is a claim nobody made
    """
    # No envelope argument means diagnosis may proceed entirely from raw error text.
    if source is None:
        # Empty mapping is the neutral envelope consumed by downstream seed logic.
        return {}
    # Read stdin only for the explicit dash convention; every other spelling is a path.
    raw = sys.stdin.read() if str(source) == "-" else Path(source).read_text(encoding="utf-8")
    # Parse the complete serialized document before making any diagnostic claims from it.
    try:
        # Retain the decoded value until its top-level object shape is validated below.
        parsed = json.loads(raw)
    # Malformed JSON must fail closed instead of masquerading as an empty valid envelope.
    except json.JSONDecodeError as broken:
        # Preserve parser location detail in the command-line failure.
        message = f"the envelope is not JSON: {broken}"
        raise SystemExit(message) from broken
    # Only object envelopes carry named diagnostic fields; other JSON values yield no envelope.
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
    # Resolve envelope-declared identities before attempting any prose inference.
    for rule_id in envelope_ids(envelope):
        # Ignore ids absent from this corpus revision while preserving them for unresolved output.
        node = graph.nodes.get(rule_id)
        if node is not None:
            # A structured identity is direct hop-zero evidence.
            found[node.id] = _hit(node, 0, "named by the envelope")
    # Structured identities suppress heuristic routing because they are stronger evidence.
    if found:
        # Return direct seeds without introducing lower-confidence signature matches.
        return found

    # Concatenate only diagnostic prose fields whose wording may carry signatures or rule ids.
    prose = " ".join(
        str(envelope.get(field, ""))
        for field in ("code", "operation", "expected", "actual", "notes")
    )
    # Fall back to the same calibrated error router used by context queries.
    for hit in seeds_for_error(graph, f"{text} {prose}".strip()):
        found.setdefault(hit.id, hit)
    # Expose heuristic seeds only because the envelope supplied no direct identity evidence.
    return found


def _rule_answer(hit: Hit, node: Node, rule: object, verification: str | None) -> dict[str, object]:
    """One rule laid out as an answer: what it says, why, and what decides it.

    @param hit how the rule was reached
    @param node its graph node, carrying the force tag and reading cost
    @param rule its parsed form, carrying the words
    @param verification measured verifier availability, kept separate from force
    @return the fields a caller needs to act without opening the module
    """
    # Combine parsed rule prose with graph force, location, cost, and route evidence.
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
    # Read structured diagnostics first, then retain any unstructured error text as fallback.
    envelope = _read_envelope(args.envelope)
    text = args.error or ""
    # A diagnosis with neither channel would otherwise produce a plausible empty answer.
    if not (envelope or text):
        # State the two supported evidence sources in the command-line failure.
        message = "diagnose needs --envelope or --error"
        raise SystemExit(message)

    # Bind parsed rule prose and verifier state to the same repository root as the graph.
    root = Path(args.root).resolve()
    # Resolve diagnostic seeds, complete rule prose, and measured verifier availability once.
    found = _diagnostic_seeds(graph, envelope, text)
    parsed = rules_by_id(root)
    status = verification_index(root)

    # Each implicated element is one rendered diagnostic record in hops/type/id rank order.
    implicated: list[dict[str, object]] = []
    # Render only complete rule subjects in deterministic evidence-distance order.
    for hit in sorted(found.values(), key=lambda h: (h.hops, h.id)):
        # Join route evidence to both graph metadata and parsed normative prose.
        node = graph.nodes.get(hit.id)
        rule = parsed.get(hit.id)
        # Non-rule seeds and incomplete joins cannot support a self-contained rule answer.
        if hit.type == "rule" and node is not None and rule is not None:
            implicated.append(_rule_answer(hit, node, rule, status.get(hit.id)))

    # Collect unique reached element values; their order is deliberately unordered.
    reached = {entry["id"] for entry in implicated}
    # Preserve envelope remediation and unresolved ids alongside the compact implicated rules.
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
    # Resolve the asserted subject, then overlay verifier availability without changing force.
    node = _require(graph, args.id)
    verification = verification_index(Path(getattr(args, "root", REPO_ROOT)).resolve()).get(node.id)
    caveat = _VERIFICATION_CAVEAT.get(verification or "")
    # Each out key is an outgoing edge type and each value lists described targets in graph edge
    # order; first-seen edge-type order is preserved for rendering.
    out: dict[str, list[str]] = {}
    # Group outgoing relations by type while preserving graph edge order inside each group.
    for edge in graph.out_edges(node.id):
        out.setdefault(str(edge.type), []).append(_describe(graph, edge.dst, edge))
    # Each incoming key is an incoming edge type and each value lists described sources in graph
    # edge order; first-seen edge-type order is preserved for rendering.
    incoming: dict[str, list[str]] = {}
    # Group incoming relations separately so direction remains visible to the reader.
    for edge in graph.in_edges(node.id):
        incoming.setdefault(str(edge.type), []).append(_describe(graph, edge.src, edge))
    # Publish identity, obligation, availability, location, and both relation directions.
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
    # Validate the starting node before interpreting relation filters or performing expansion.
    _require(graph, args.id)
    # Convert requested relation spellings to the graph enum, or leave all types enabled.
    types = [EdgeType(t) for t in args.type] if args.type else None
    # Run one bounded breadth-first expansion with the caller's direction policy.
    reached = graph.expand([args.id], types=types, depth=args.depth, undirected=args.undirected)
    # Exclude the starting node while preserving hop-then-id ordering for all neighbors.
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
    # Compute direct file seeds and overlay verifier state without graph expansion or budgeting.
    hits = annotate(seeds_for_file(graph, args.path), Path(args.root).resolve())
    # Separate governing rules from directly applicable modules while retaining seed order.
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
    # Resolve the asserted rule once before selecting its provenance-only relations.
    node = _require(graph, args.id)
    # Preserve relation categories independently so an empty category remains meaningful.
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
    # Validate both endpoints before attempting forward or reverse shortest-path search.
    _require(graph, args.src)
    _require(graph, args.dst)
    # Prefer the authored forward direction from the requested source to destination.
    found = graph.shortest_path(args.src, args.dst)
    # When no forward route exists, search reverse direction to answer connectivity.
    if found is None:
        # Retain a reverse-authored route if the graph connects the endpoints that way.
        found = graph.shortest_path(args.dst, args.src)
        if found is not None:
            # Reorder reverse-route steps from the caller's requested source perspective.
            found = list(reversed(found))
    # Report both route existence and each edge's true authored direction.
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
    # Accumulate a conservative cost in argument order; repeated owners remain repeatedly charged.
    total = 0
    # Price every requested identity independently so one unknown id cannot abort the rest.
    for node_id in args.ids:
        # Resolve the requested rule or module from the current graph revision.
        node = graph.nodes.get(node_id)
        # Unknown identities are retained explicitly with zero unclaimed cost.
        if node is None:
            items.append({"id": node_id, "tokens": 0, "status": "unknown"})
            # Continue after retaining the unresolved request in the priced answer.
            continue
        # Rules charge their owning module; modules charge themselves.
        owner = node.attr("module") if node.type is NodeType.RULE else node.id
        # Resolve the actual reading unit and degrade missing owner nodes to unmeasured zero.
        target = graph.nodes.get(owner or node.id)
        tokens = target.tokens if target else 0
        items.append({"id": node_id, "reads": owner, "tokens": tokens})
        total += tokens
    # Expose per-id reading units beside the deliberately conservative aggregate ceiling.
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
    # Measure rule reachability from every router-visible module at the requested depth.
    unreachable = graph.unreachable_from(_kernel_seeds(graph), NodeType.RULE, depth=args.depth)
    total = len(graph.of_type(NodeType.RULE))
    # Each nodes key is a node-type label and each value is its count; mapping key order follows
    # first graph occurrence for stable rendering.
    nodes: dict[str, int] = {}
    # Count node categories in graph insertion order before sorting the public mapping.
    for node in graph.nodes.values():
        # Increment the category represented by this concrete graph node.
        nodes[str(node.type)] = nodes.get(str(node.type), 0) + 1
    # Each edges key is an edge-type label and each value is its count; mapping key order follows
    # first graph occurrence for stable rendering.
    edges: dict[str, int] = {}
    # Count relation categories independently of node reachability.
    for edge in graph.edges:
        # Increment the category represented by this concrete graph edge.
        edges[str(edge.type)] = edges.get(str(edge.type), 0) + 1
    # Publish sorted censuses beside the exact reachable numerator and residual ids.
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
    # Use every router-addressable module as the stable sorted reachability frontier.
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
    # Resolve exact identity without accepting labels or fuzzy spellings.
    node = graph.nodes.get(node_id)
    # Fail loudly so a mistyped query cannot look like an isolated valid node.
    if node is None:
        # Preserve the unknown spelling in the command-line diagnostic.
        message = f"unknown node {node_id!r}"
        raise SystemExit(message)
    # Hand the validated graph subject to the requesting command.
    return node


def _describe(graph: Graph, node_id: str, edge: Edge) -> str:
    """Name one end of an edge in a line, qualified by whatever the edge records.

    @param graph the discipline graph
    @param node_id the endpoint being reported
    @param edge the relation it was reached through, whose note qualifies it
    @return the id with its title, degrading to the bare id when the endpoint
        does not resolve
    """
    # Resolve endpoint metadata when present while tolerating stale edge references.
    node = graph.nodes.get(node_id)
    # Combine stable id with its human label, or degrade to the unresolved id alone.
    label = f"{node_id} - {node.label}" if node else node_id
    # Append relation qualification only when the edge carries a nonempty note.
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
    # Disclose rule truncation in the heading and name the control that expands it.
    suffix = f" of {total} - raise --max-rules to see the rest" if shown < total else ""
    # Start context output with the selected-rule count and truncation disclosure.
    lines = [f"RULES ({shown}{suffix})"]
    # Render selected rules in plan order with force, verifier caveat, and route evidence.
    for rule in payload["rules"]:  # type: ignore[union-attr]
        # Combine normative force with measured availability without implying a pass result.
        tag = force_tag(rule["force"], rule.get("verification"))
        lines.append(f"  {rule['id']:<10} {tag:<32} {rule['label']}")
        lines.append(f"  {'':<10} {'':<32} ~ {rule['reason']}")
    lines.append("")
    lines.append("READ")
    # Mark each module as an accepted read or visible budget overflow.
    for item in payload["read"]:  # type: ignore[union-attr]
        # A leading exclamation makes deferred material visible without changing status text.
        mark = " " if item["status"] == "read" else "!"
        lines.append(f" {mark} {item['id']:<22} {item['tokens']:>6} tok  {item['status']}")
    lines.append("")
    lines.append(
        f"BUDGET  planned {payload['tokens_planned']} tok"
        f"  (all candidates {payload['tokens_if_all']} tok)"
    )
    # Append learned guidance only when the optional overlay returned contextual claims.
    if payload.get("learnings"):
        lines.append("")
        lines.append("LEARNED")
        # Preserve retrieval rank in the human-readable learned section.
        lines += [f"  {item}" for item in payload["learnings"]]  # type: ignore[union-attr]
    # Return the complete terminal lines in the same order as the machine payload.
    return lines


def _render_applies(payload: dict[str, object]) -> list[str]:
    """Every rule and module that governs one path.

    @param payload the `applies` answer
        Each key is an applies-response field and each value is its command result; mapping key
        order is deliberately unused.
    @return the lines to print
    """
    # Retain the rule sequence once for both the heading count and detailed rows.
    rules = payload["rules"]
    # Start file output with the governed path and its resolved-rule count.
    lines = [f"{payload['path']}  ({len(rules)} rules)"]  # type: ignore[arg-type]
    # Render governing rules first, carrying force, verifier availability, and evidence.
    for rule in rules:  # type: ignore[union-attr]
        lines.append(
            f"  {rule['id']:<10} "
            f"{force_tag(rule['force'], rule.get('verification')):<32}"
            f" {rule['label']}   ~ {rule['reason']}"
        )
    # Follow rule obligations with any directly applicable module seeds.
    lines += [f"  {module['id']:<20} ~ {module['reason']}" for module in payload["modules"]]  # type: ignore[union-attr]
    # Preserve the command payload's rule-then-module answer order.
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
    # Start node output with identity before appending available metadata and relations.
    lines = [f"{payload['id']} - {payload.get('label', '')}"]
    # Render nonempty metadata and relation groups in payload declaration order.
    for key, value in payload.items():
        # Identity is already in the heading; omit empty optional fields entirely.
        if key in {"id", "label", "type"} or not value:
            # Continue after suppressing redundant identity or absent optional content.
            continue
        # Mapping values represent relation groups and require one nested heading per edge type.
        if isinstance(value, dict):
            # Preserve relation-type insertion order from the command payload.
            for edge_type, targets in value.items():
                lines.append(f"  {edge_type}:")
                # Preserve each relation group's already-sorted endpoint order.
                lines += [f"    {t}" for t in targets]
        # List values are flat multi-valued fields rather than relation mappings.
        elif isinstance(value, list):
            lines.append(f"  {key}:")
            # Keep list order because command handlers define its semantic priority.
            lines += [f"    {t}" for t in value]
        # Scalar metadata renders on one line beside its field name.
        else:
            lines.append(f"  {key}: {value}")
    # Expose the completed terminal representation without a trailing blank sentinel.
    return lines


def _render_stats(payload: dict[str, object]) -> list[str]:
    """Node and edge census, and the reachability figure V092 gates on.

    @param payload the `stats` answer
        Each key is a statistics-response field and each value is its count or summary; mapping
        key order is deliberately unused.
    @return the lines to print
    """
    # Start statistics output with node, edge, force, and strategy census rows.
    lines = [
        "NODES  " + ", ".join(f"{k}={v}" for k, v in payload["nodes"].items()),  # type: ignore[union-attr]
        "EDGES  " + ", ".join(f"{k}={v}" for k, v in payload["edges"].items()),  # type: ignore[union-attr]
        f"REACH  {payload['rules_reachable']}/{payload['rules_total']} rules "
        f"within {payload['reach_depth']} hops",
    ]
    # List residual unreachable rules only when the reachability measure found some.
    if payload["unreachable"]:
        lines.append("  unreachable: " + ", ".join(payload["unreachable"]))  # type: ignore[union-attr]
    # Preserve the census-then-reachability display sequence.
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
    # Accumulate diagnosis output beginning with envelope identity and resolved rules.
    lines: list[str] = []
    # Lead with envelope identity and optional architectural layer when available.
    if payload.get("code"):
        # Qualify the diagnostic code only when the structured envelope named a layer.
        where = f" in the {payload['layer']} layer" if payload.get("layer") else ""
        lines.append(f"{payload['code']}{where}")
    # Preserve the emitting mechanism's own remediation before doctrine interpretation.
    if payload.get("reported_remediation"):
        # Keep the external recommendation visually distinct from doctrine-derived rules.
        lines += ["", f"REPORTED  {payload['reported_remediation']}"]

    # Normalize absent rules to an empty sequence for the no-match explanation.
    rules = payload.get("rules") or []
    # No match is explicit diagnostic debt, not an empty-looking successful lookup.
    if not rules:
        # Name signature maintenance as the repair path when this failure shape recurs.
        lines += [
            "",
            "no rule in the corpus matched this output.",
            "Add a signature to enforce/signals.toml if this shape recurs.",
        ]
        # Stop before adding cost or per-rule sections that have no subjects.
        return lines

    # Separate header/remediation from the self-contained implicated rule blocks.
    lines.append("")
    # Render each rule in evidence order with its normative statement and available rationale.
    for rule in rules:  # type: ignore[union-attr]
        # Begin with identity, force, title, and the complete binding statement.
        lines += [
            f"{rule['id']} {rule['force']}  {rule['title']}",
            f"    {rule['statement']}",
        ]
        # Include rationale only when the parsed doctrine rule supplies one.
        if rule.get("why"):
            lines.append(f"    why    {rule['why']}")
        # Include the deciding mechanism or review instruction when present.
        if rule.get("check"):
            lines.append(f"    check  {rule['check']}")
        # Finish each rule with its openable source and module ownership, then a separator.
        lines += [f"    open   {rule['open']}  ({rule['module']})", ""]
    lines.append(f"COST  {payload['tokens']} tok -- {len(rules)} rule(s), read in full")
    # Call out envelope-declared ids absent from the current corpus revision.
    if payload.get("unresolved"):
        # Join unresolved identities in envelope order for direct provenance comparison.
        named = ", ".join(payload["unresolved"])  # type: ignore[arg-type]
        lines.append(f"UNRESOLVED  {named} -- named by the envelope, absent here")
    # Return the complete diagnosis with measured cost and any corpus skew exposed.
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
    # Resolve the command-specific terminal layout while permitting forward-compatible fallback.
    renderer = _RENDERERS.get(command)
    # Unknown commands still receive legible structured output rather than failing presentation.
    if renderer is None:
        # Preserve Unicode and one-space indentation in the generic JSON representation.
        return json.dumps(payload, indent=1, ensure_ascii=False)
    # Join the selected renderer's semantic lines without adding an extra terminal newline.
    return "\n".join(renderer(payload))


def build_parser() -> argparse.ArgumentParser:
    """Assemble the command grammar, one subparser per question an agent asks.

    @return a parser that refuses to run without a subcommand, since there is no
        sensible default walk
    """
    # Define global output/root controls before requiring one explicit graph question.
    parser = argparse.ArgumentParser(description="Walk the discipline graph.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    sub = parser.add_subparsers(dest="command", required=True)

    # Context combines all evidence channels with traversal and reading-budget controls.
    ctx = sub.add_parser("context", help="the reading plan for a situation")
    ctx.add_argument("--file")
    ctx.add_argument("--error")
    ctx.add_argument("--task")
    ctx.add_argument("--rule", action="append")
    ctx.add_argument("--depth", type=int, default=1)
    ctx.add_argument("--budget", type=int, default=DEFAULT_BUDGET)
    ctx.add_argument("--max-rules", type=int, default=20)

    # Rule lookup returns one subject with its bidirectional relation groups.
    rule = sub.add_parser("rule", help="one rule and its neighbourhood")
    rule.add_argument("id")

    # Neighbor traversal exposes depth, relation filtering, and optional reverse edges.
    nb = sub.add_parser("neighbors", help="breadth-first walk from a node")
    nb.add_argument("id")
    nb.add_argument("--type", action="append")
    nb.add_argument("--depth", type=int, default=1)
    nb.add_argument("--undirected", action="store_true")

    # Diagnosis accepts either a structured envelope or raw failure text.
    dg = sub.add_parser("diagnose", help="what broke, against which rule, and what to do")
    dg.add_argument("--envelope", help="a serialized diagnostic envelope, or - for stdin")
    dg.add_argument("--error", help="raw error text, when there is no envelope")

    # Applies asks the narrow file-obligation question without graph expansion.
    ap = sub.add_parser("applies", help="rules governing a file")
    ap.add_argument("path")

    # Why selects provenance relations for one asserted rule identity.
    why = sub.add_parser("why", help="why a rule has the shape it has")
    why.add_argument("id")

    # Path asks for shortest connectivity between two validated endpoints.
    pth = sub.add_parser("path", help="how two nodes connect")
    pth.add_argument("src")
    pth.add_argument("dst")

    # Budget prices a caller-selected list without requiring every identity to resolve.
    bud = sub.add_parser("budget", help="token cost of a reading set")
    bud.add_argument("ids", nargs="+")

    # Stats measures graph census and router-to-rule reachability at a chosen depth.
    st = sub.add_parser("stats", help="graph shape and reachability")
    st.add_argument("--depth", type=int, default=3)
    # Expose the complete grammar only after every supported question is registered.
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
    # Parse one required question, load the selected repository graph, and dispatch it.
    args = build_parser().parse_args(argv)
    graph = load_graph(args.root.resolve())
    payload = COMMANDS[args.command](graph, args)
    # Select machine JSON or command-shaped terminal prose only at the output boundary.
    print(
        json.dumps(payload, indent=1, ensure_ascii=False)
        if args.json
        else render(args.command, payload)
    )
    # Successful rendering completes the navigator command regardless of answer size.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
