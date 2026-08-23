"""The router lands where a person asking would need it to.

**Oracle: contract.** A declared table of realistic queries against the modules
and rules they must reach, in `enforce/fixtures/routing.toml`.

* `FLOW-011` -- the diagnosis is checked, not assumed

The router and the `load_when` triggers are the highest-traffic and least-verified
path in the corpus. A wrong answer costs the agent a module it did not need and
then reasons from the wrong law; an EMPTY answer costs more, because the agent
falls back to reading speculatively, which is the one behaviour the whole layered
design exists to prevent.

**Recall and precision are asserted together.** `expect` alone is satisfied by a
router that returns everything, and loosening the match until every query passes is
the obvious way to make this file green. `reject` is what makes that visible --
including two queries (a rename, a typo) that KERNEL says should load nothing at
all.

The queries are deliberately NOT the front-matter's own phrases. Feeding a
module's `load_when` back to it and asserting it matches measures string equality.

    pytest enforce/fitness/test_routing.py
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Final

import pytest

from graph_model import NodeType
from nav import load_graph, seeds_for_file, seeds_for_task

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## The declared table.
TABLE: Final = REPO_ROOT / "enforce" / "fixtures" / "routing.toml"


def _cases(kind: str) -> list[dict[str, object]]:
    """The declared cases of one kind.

    @param kind `task` or `file`
    @return case-record mapping elements in TOML declaration order
    """
    # Decode section-name keys to ordered case-record list values from the table.
    document = tomllib.loads(TABLE.read_text(encoding="utf-8"))
    # Copy the requested case elements while preserving authored declaration order.
    return list(document.get(kind, []))


def _graph() -> object:
    """The discipline graph, loaded once per call.

    @return the graph the navigator walks
    """
    # Load the generated typed multigraph from the repository's canonical products.
    return load_graph(REPO_ROOT)


@pytest.mark.parametrize("case", _cases("task"),
                         ids=lambda case: str(case["query"])[:38])
def test_a_task_reaches_the_modules_that_govern_it(case: dict[str, object]) -> None:
    """A task described in a person's own words lands on the right modules.

    @param case field-name keys mapped to query, expected, rejected, and reason
        values; TOML insertion order is not semantically significant
    """
    # Collapse task-seed node-id elements to an unordered membership set.
    reached = {hit.id for hit in seeds_for_task(_graph(), str(case["query"]))}

    # Verify each expected node identifier in declared expectation order.
    for wanted in case.get("expect", []):  # type: ignore[union-attr]
        # Require recall while reporting the complete sorted router result on failure.
        assert wanted in reached, (
            f"{case['query']!r} did not reach {wanted}.\n"
            f"  reached: {', '.join(sorted(reached)) or 'NOTHING'}\n"
            f"  why it should: {case['why']}\n"
            f"An empty answer sends the agent to read speculatively, which costs "
            f"more than the wrong module."
        )
    # Verify each rejected node identifier in declared precision-check order.
    for unwanted in case.get("reject", []):  # type: ignore[union-attr]
        # Reject over-broad routing that drags an unrelated module into context.
        assert unwanted not in reached, (
            f"{case['query']!r} dragged in {unwanted}, which it does not need.\n"
            f"  why not: {case['why']}\n"
            f"A router that returns everything is as useless as one that returns "
            f"nothing, and easier to build by accident."
        )


@pytest.mark.parametrize("case", _cases("file"),
                         ids=lambda case: str(case["path"]))
def test_a_path_reaches_the_rules_that_bind_it(case: dict[str, object]) -> None:
    """A file's shape decides which rules govern it, whether or not it exists.

    @param case field-name keys mapped to path, expected, rejected, and reason
        values; TOML insertion order is not semantically significant
    """
    # Collapse file-seed rule-id elements to an unordered membership set.
    reached = {hit.id for hit in seeds_for_file(_graph(), str(case["path"]))}

    # Verify each expected rule identifier in declared expectation order.
    for wanted in case.get("expect", []):  # type: ignore[union-attr]
        # Require path-based recall with the complete sorted result in diagnostics.
        assert wanted in reached, (
            f"{case['path']} did not pull {wanted}.\n"
            f"  reached: {', '.join(sorted(reached)) or 'NOTHING'}\n"
            f"  why it should: {case['why']}"
        )
    # Verify each rejected rule identifier in declared precision-check order.
    for unwanted in case.get("reject", []):  # type: ignore[union-attr]
        # Reject path routing that attaches a non-binding rule to the source shape.
        assert unwanted not in reached, (
            f"{case['path']} pulled {unwanted}, which does not bind it.\n"
            f"  why not: {case['why']}"
        )


def test_the_table_does_not_quote_the_front_matter() -> None:
    """A query that repeats a module's own `load_when` phrase measures nothing.

    The cheapest way to make this suite green is to write the triggers back as
    queries. This refuses the degenerate form of that: a query that IS a trigger,
    verbatim.
    """
    # Load router trigger nodes and collapse keyword-label elements to an unordered set.
    graph = _graph()
    triggers = {
        node.label.lower()
        for node in graph.of_type(NodeType.TRIGGER)  # type: ignore[attr-defined]
        if node.attr("kind") == "keyword"
    }
    # Reject a vacuous comparison surface containing no declared routing keywords.
    assert triggers, "the graph carries no router keywords at all"
    # Compare each authored task case against exact lower-cased trigger vocabulary.
    for case in _cases("task"):
        # Reject an oracle that simply repeats the implementation's configured keyword.
        assert str(case["query"]).lower() not in triggers, (
            f"{case['query']!r} is a router keyword quoted back at itself"
        )


def test_every_case_says_why() -> None:
    """An entry that cannot say why that answer is right is not an oracle.

    Without the reason, a failing case invites changing the expectation rather
    than the router, and the table stops being evidence of anything.
    """
    # Visit task and file case families in stable diagnostic order.
    for kind in ("task", "file"):
        # Inspect each case record in authored TOML declaration order.
        for case in _cases(kind):
            # Require a substantive reason so expectation edits remain reviewable.
            assert len(str(case.get("why", ""))) > 30, (
                f"{kind} case {case.get('query') or case.get('path')!r} states no "
                f"reason"
            )
