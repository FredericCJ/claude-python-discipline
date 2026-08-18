"""Correctness fixtures for the graph and its query interface.

Two kinds of test here. The **model** tests prove the multigraph behaves as a
multigraph -- parallel edges, direction, determinism. The **fixture** tests pin
canonical questions to expected answers, so navigation quality is asserted rather
than eyeballed: if a future edit makes the discipline harder to walk, one of
these fails.

    pytest tools/test_nav.py
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

import pytest

import nav
from build_graph import build, load_graph, render
from discipline_core import REPO_ROOT
from graph_model import Edge, EdgeType, Graph, Node, NodeType, Origin

# ------------------------------------------------------------------ the model


def _tiny() -> Graph:
    graph = Graph()
    for node_id, node_type in (
        ("law/A", NodeType.MODULE),
        ("law/B", NodeType.MODULE),
        ("A-001", NodeType.RULE),
        ("A-002", NodeType.RULE),
    ):
        graph.add_node(Node(id=node_id, type=node_type, label=node_id))
    return graph


def test_parallel_edges_of_different_types_coexist() -> None:
    """The defining property: two nodes, several relations, either direction."""
    graph = _tiny()
    assert graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002"))
    assert graph.add_edge(Edge(EdgeType.TENSIONS_WITH, "A-001", "A-002"))
    assert graph.add_edge(Edge(EdgeType.PRECEDES, "A-002", "A-001"))
    assert len(graph.edges) == 3
    assert len(graph.out_edges("A-001")) == 2
    assert len(graph.in_edges("A-001")) == 1


def test_same_edge_from_two_origins_is_kept() -> None:
    """A relation both declared and observed is two facts, not one."""
    graph = _tiny()
    assert graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002", Origin.DECLARED))
    assert graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002", Origin.LEARNED))
    assert len(graph.edges) == 2


def test_an_identical_edge_is_not_duplicated() -> None:
    graph = _tiny()
    assert graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002"))
    assert not graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002"))
    assert len(graph.edges) == 1


def test_direction_is_respected_unless_asked_otherwise() -> None:
    graph = _tiny()
    graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002"))
    assert graph.neighbors("A-002") == []
    assert graph.neighbors("A-002", undirected=True) == ["A-001"]


def test_expansion_is_deterministic() -> None:
    graph = _tiny()
    graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002"))
    graph.add_edge(Edge(EdgeType.CITES, "A-002", "law/B"))
    first = graph.expand(["A-001"], depth=2)
    assert first == graph.expand(["A-001"], depth=2)
    assert first == {"A-001": 0, "A-002": 1, "law/B": 2}


def test_a_requires_cycle_is_found() -> None:
    graph = _tiny()
    graph.add_edge(Edge(EdgeType.REQUIRES, "law/A", "law/B"))
    graph.add_edge(Edge(EdgeType.REQUIRES, "law/B", "law/A"))
    assert graph.cycles_in(EdgeType.REQUIRES)


def test_a_dangling_edge_is_found() -> None:
    graph = _tiny()
    graph.add_edge(Edge(EdgeType.CITES, "A-001", "GHOST-999"))
    assert [e.dst for e in graph.dangling()] == ["GHOST-999"]


def test_round_trip_through_json_is_lossless() -> None:
    graph = _tiny()
    graph.add_edge(Edge(EdgeType.CITES, "A-001", "A-002", note="why"))
    graph.add_edge(Edge(EdgeType.TENSIONS_WITH, "A-001", "A-002", Origin.DECLARED))
    again = Graph.from_dict(graph.to_dict())
    assert again.to_dict() == graph.to_dict()


# ------------------------------------------------------------- the live graph


@pytest.fixture(scope="module")
def graph() -> Graph:
    return load_graph(REPO_ROOT)


def test_the_built_graph_is_byte_stable() -> None:
    """Same corpus, same bytes -- the property `--check` depends on."""
    first, _ = build(REPO_ROOT)
    second, _ = build(REPO_ROOT)
    assert render(first) == render(second)


def test_every_rule_is_reachable(graph: Graph) -> None:
    """The mechanical measure of navigability. A rule nobody can arrive at is a
    rule that exists and cannot be found."""
    seeds = sorted(n.id for n in graph.of_type(NodeType.MODULE))
    unreachable = graph.unreachable_from(seeds, NodeType.RULE, depth=3)
    assert unreachable == []


def test_no_dangling_edges(graph: Graph) -> None:
    assert graph.dangling() == []


def test_requires_is_acyclic(graph: Graph) -> None:
    assert graph.cycles_in(EdgeType.REQUIRES) == []


def test_every_rule_belongs_to_exactly_one_module(graph: Graph) -> None:
    for rule in graph.of_type(NodeType.RULE):
        owners = graph.in_edges(rule.id, [EdgeType.CONTAINS])
        assert len(owners) == 1, f"{rule.id} has {len(owners)} owning modules"


def test_tensions_are_symmetric(graph: Graph) -> None:
    """A tension one rule declares is a tension the other is subject to."""
    for edge in graph.edges:
        if edge.type is not EdgeType.TENSIONS_WITH:
            continue
        back = graph.out_edges(edge.dst, [EdgeType.TENSIONS_WITH])
        assert any(e.dst == edge.src for e in back), f"{edge.dst} does not point back"


# ------------------------------------------------- canonical question fixtures


def _ns(**kwargs: object) -> argparse.Namespace:
    defaults = {
        "file": None, "error": None, "task": None, "rule": None,
        "depth": 1, "budget": 6000, "max_rules": 20,  # matches the CLI default
    }
    return argparse.Namespace(**{**defaults, "root": REPO_ROOT, **kwargs})


def _rule_ids(payload: dict[str, object]) -> set[str]:
    return {r["id"] for r in payload["rules"]}  # type: ignore[union-attr,index]


def test_an_adapter_file_reaches_the_adapter_rules(graph: Graph) -> None:
    found = _rule_ids(nav.cmd_context(graph, _ns(file="src/pkg/adapters/fs.py")))
    assert {"ARCH-003", "ARCH-004", "ARCH-008", "DEP-003"} <= found
    assert "TYPE-002" not in found, "a domain-only rule must not govern an adapter"


def test_a_domain_file_reaches_the_purity_rules(graph: Graph) -> None:
    found = _rule_ids(nav.cmd_context(graph, _ns(file="src/pkg/domain/outline.py")))
    assert {"ARCH-002", "TYPE-002", "TYPE-007", "EFCT-001", "DEP-001"} <= found
    assert "ARCH-003" not in found, "an adapter-only rule must not govern the domain"


def test_an_import_linter_failure_reaches_its_rule(graph: Graph) -> None:
    """Separator style must not decide the outcome."""
    for text in (
        "lint-imports: contract adapters-are-independent FAILED",
        "ARCH-003 adapters are independent: broken",
    ):
        found = _rule_ids(nav.cmd_context(graph, _ns(error=text)))
        assert "ARCH-003" in found, text


def test_a_named_rule_in_an_error_is_picked_up(graph: Graph) -> None:
    payload = nav.cmd_context(graph, _ns(error="violates DIAG-005 at line 12"))
    assert "DIAG-005" in _rule_ids(payload)


def test_what_do_i_run_for_a_rule(graph: Graph) -> None:
    mechanisms = graph.neighbors("ARCH-002", [EdgeType.ENFORCED_BY])
    assert "mech:check:domain_purity" in mechanisms
    assert "mech:auto:import-linter" in mechanisms


def test_why_a_rule_has_its_shape(graph: Graph) -> None:
    payload = nav.cmd_why(graph, argparse.Namespace(id="ARCH-008", root=REPO_ROOT))
    assert any("CONF-007" in entry for entry in payload["resolved_by"])  # type: ignore[union-attr]


def test_an_open_rule_names_what_blocks_it(graph: Graph) -> None:
    payload = nav.cmd_why(graph, argparse.Namespace(id="ALLOC-010", root=REPO_ROOT))
    assert any("OPEN-006" in entry for entry in payload["blocked_by"])  # type: ignore[union-attr]


def test_a_budget_defers_rather_than_truncates(graph: Graph) -> None:
    payload = nav.cmd_context(graph, _ns(file="src/pkg/adapters/fs.py", budget=3000))
    plan = payload["read"]
    assert any(p["status"] == "deferred" for p in plan), "nothing was deferred"  # type: ignore[union-attr]
    read = sum(p["tokens"] for p in plan if p["status"] == "read")  # type: ignore[union-attr]
    assert read <= 3000 or len([p for p in plan if p["status"] == "read"]) == 1
    assert payload["tokens_planned"] == read


def test_the_most_relevant_module_is_planned_first(graph: Graph) -> None:
    """A tight budget must keep what the task is about, not what is smallest."""
    payload = nav.cmd_context(graph, _ns(file="src/pkg/adapters/fs.py", budget=3000))
    first = [p["id"] for p in payload["read"] if p["status"] == "read"]  # type: ignore[union-attr]
    assert first[0] == "law/ARCH"


def test_context_is_reproducible(graph: Graph) -> None:
    args = _ns(file="src/pkg/domain/outline.py", error="G004", task="add a port")
    assert nav.cmd_context(graph, args) == nav.cmd_context(graph, args)


def test_a_path_between_two_rules_is_found(graph: Graph) -> None:
    payload = nav.cmd_path(
        graph, argparse.Namespace(src="ARCH-008", dst="ARCH-009", root=REPO_ROOT)
    )
    assert payload["found"]


def test_stats_reports_full_reachability(graph: Graph) -> None:
    payload = nav.cmd_stats(graph, argparse.Namespace(depth=3, root=REPO_ROOT))
    assert payload["rules_reachable"] == payload["rules_total"]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
