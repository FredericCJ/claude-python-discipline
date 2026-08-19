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
    @return the entries, in declaration order
    """
    document = tomllib.loads(TABLE.read_text(encoding="utf-8"))
    return list(document.get(kind, []))


def _graph() -> object:
    """The discipline graph, loaded once per call.

    @return the graph the navigator walks
    """
    return load_graph(REPO_ROOT)


@pytest.mark.parametrize("case", _cases("task"),
                         ids=[c["query"][:38] for c in _cases("task")])
def test_a_task_reaches_the_modules_that_govern_it(case: dict[str, object]) -> None:
    """A task described in a person's own words lands on the right modules.

    @param case one declared entry: the query, what it must reach, what it must not
    """
    reached = {hit.id for hit in seeds_for_task(_graph(), str(case["query"]))}

    for wanted in case.get("expect", []):  # type: ignore[union-attr]
        assert wanted in reached, (
            f"{case['query']!r} did not reach {wanted}.\n"
            f"  reached: {', '.join(sorted(reached)) or 'NOTHING'}\n"
            f"  why it should: {case['why']}\n"
            f"An empty answer sends the agent to read speculatively, which costs "
            f"more than the wrong module."
        )
    for unwanted in case.get("reject", []):  # type: ignore[union-attr]
        assert unwanted not in reached, (
            f"{case['query']!r} dragged in {unwanted}, which it does not need.\n"
            f"  why not: {case['why']}\n"
            f"A router that returns everything is as useless as one that returns "
            f"nothing, and easier to build by accident."
        )


@pytest.mark.parametrize("case", _cases("file"),
                         ids=[c["path"] for c in _cases("file")])
def test_a_path_reaches_the_rules_that_bind_it(case: dict[str, object]) -> None:
    """A file's shape decides which rules govern it, whether or not it exists.

    @param case one declared entry: the path, the rules it must and must not pull
    """
    reached = {hit.id for hit in seeds_for_file(_graph(), str(case["path"]))}

    for wanted in case.get("expect", []):  # type: ignore[union-attr]
        assert wanted in reached, (
            f"{case['path']} did not pull {wanted}.\n"
            f"  reached: {', '.join(sorted(reached)) or 'NOTHING'}\n"
            f"  why it should: {case['why']}"
        )
    for unwanted in case.get("reject", []):  # type: ignore[union-attr]
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
    graph = _graph()
    triggers = {
        node.label.lower()
        for node in graph.of_type(NodeType.TRIGGER)  # type: ignore[attr-defined]
        if node.attr("kind") == "keyword"
    }
    assert triggers, "the graph carries no router keywords at all"
    for case in _cases("task"):
        assert str(case["query"]).lower() not in triggers, (
            f"{case['query']!r} is a router keyword quoted back at itself"
        )


def test_every_case_says_why() -> None:
    """An entry that cannot say why that answer is right is not an oracle.

    Without the reason, a failing case invites changing the expectation rather
    than the router, and the table stops being evidence of anything.
    """
    for kind in ("task", "file"):
        for case in _cases(kind):
            assert len(str(case.get("why", ""))) > 30, (
                f"{kind} case {case.get('query') or case.get('path')!r} states no "
                f"reason"
            )
