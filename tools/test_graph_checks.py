"""Proof-of-failure tests for the graph validation checks (V090-V095).

Same standard as every other check in this repository: each one is driven to
fire against a corpus built for the purpose, so its silence on the real corpus
means something. Kept separate from `test_validate.py` only because these need a
graph-shaped fixture rather than a single module.

    pytest tools/test_graph_checks.py
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from test_validate import CONFORMANT_RULE, codes, module, run_on, write

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path

## A fact module's version table, the smallest thing V095 will read a tool pin out of.
FACT_TABLE = "| Tool | Version |\n|---|---|\n| mypy | 2.3.1 |\n"


def edges_yaml(root: Path, body: str) -> Path:
    """Place the hand-authored relations file, version header already supplied.

    @param root the corpus root
    @param body the YAML mapping, dedented before writing
    @return the path written
    """
    # Route every synthetic edge declaration through the common UTF-8 fixture writer.
    return write(root / "discipline" / "meta" / "edges.yaml", "version: 1\n" + dedent(body))


def add_front_matter(path: Path, line: str) -> None:
    """Insert a front-matter line ahead of `decay:`, which every module has.

    Anchoring on a key the fixture always writes avoids parsing the YAML back
    out, and keeps the insertion inside the front-matter fence.

    @param path the module to rewrite in place
    @param line the front-matter entry to add, without a trailing newline

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Retain the immutable source representation consumed by subsequent analysis.
    text = path.read_text(encoding="utf-8")
    path.write_text(text.replace("decay: ", f"{line}\ndecay: ", 1), encoding="utf-8")


# ------------------------------------------------------------------- V090-V091


def test_v090_dangling_edge_endpoint(tmp_path: Path) -> None:
    """A citation to a rule that does not exist is an edge to nowhere."""
    module(
        tmp_path,
        body=CONFORMANT_RULE + "- **See** [GHOST-999]\n",
    )
    assert "V090" in codes(run_on(tmp_path))


def test_v091_requires_cycle(tmp_path: Path) -> None:
    """Two modules each requiring the other leaves load order undefined."""
    # These module paths are the two vertices of the deliberately cyclic requires graph.
    first = module(tmp_path, name="TYPE", title="Typing")
    second = module(
        tmp_path, name="ERR", title="Errors",
        body=CONFORMANT_RULE.replace("TYPE-001", "ERR-001"),
    )
    add_front_matter(first, 'requires: ["law/ERR"]')
    add_front_matter(second, 'requires: ["law/TYPE"]')
    assert "V091" in codes(run_on(tmp_path))


def test_a_rule_inside_a_module_is_always_reachable(tmp_path: Path) -> None:
    """V092 guards arrival; `contains` alone is enough to arrive."""
    module(tmp_path)
    assert "V092" not in codes(run_on(tmp_path))


# ------------------------------------------------------------------- V093-V094


def test_v093_declared_edge_names_an_unknown_id(tmp_path: Path) -> None:
    """A hand-authored relation is held to the same endpoints as a derived one.

    Reported separately from V090 because the fix is in `edges.yaml`, not in a
    module's prose.
    """
    module(tmp_path)
    edges_yaml(
        tmp_path,
        """
        tensions_with:
          - pair: [TYPE-001, NOSUCH-404]
        """,
    )
    assert "V093" in codes(run_on(tmp_path))


def test_a_declared_edge_between_real_rules_is_accepted(tmp_path: Path) -> None:
    """The conforming case: a true declared relation draws neither V093 nor V090.

    A check that fires on correct authoring is one people learn to route around.
    """
    module(tmp_path)
    module(tmp_path, name="ERR", title="Errors",
           body=CONFORMANT_RULE.replace("TYPE-001", "ERR-001"))
    edges_yaml(
        tmp_path,
        """
        tensions_with:
          - pair: [TYPE-001, ERR-001]
        """,
    )
    # Preserve the optional pattern match that carries the reported analysis count.
    found = codes(run_on(tmp_path))
    assert "V093" not in found
    assert "V090" not in found


def test_v094_graph_disagrees_with_the_corpus(tmp_path: Path) -> None:
    """An empty graph beside a populated corpus is stale, and would misroute in silence."""
    module(tmp_path)
    write(tmp_path / "discipline" / "graph.json", '{"nodes": [], "edges": []}\n')
    assert "V094" in codes(run_on(tmp_path))


def test_v094_is_silent_when_no_graph_is_built(tmp_path: Path) -> None:
    """Absence is not staleness: the graph accelerates, it is not depended on."""
    module(tmp_path)
    assert "V094" not in codes(run_on(tmp_path))


# ----------------------------------------------------------------------- V095


def test_v095_rule_checked_by_an_ungrounded_tool(tmp_path: Path) -> None:
    """A tool a rule leans on must be grounded, not merely invoked.

    The rule's Check runs mypy, which a fact module pins, but the law module
    never says where that pin lives.
    """
    module(tmp_path, kind="fact", name="pytooling", title="Tooling",
           verified="2026-06-16", body=FACT_TABLE)
    module(tmp_path)
    assert "V095" in codes(run_on(tmp_path))


def test_v095_clears_once_grounded(tmp_path: Path) -> None:
    """Naming the fact module in `grounds_on` discharges the obligation entirely."""
    module(tmp_path, kind="fact", name="pytooling", title="Tooling",
           verified="2026-06-16", body=FACT_TABLE)
    add_front_matter(module(tmp_path), 'grounds_on: ["fact/pytooling"]')
    assert "V095" not in codes(run_on(tmp_path))


def test_v095_stays_quiet_when_no_fact_pins_the_tool(tmp_path: Path) -> None:
    """Narrow on purpose.

    Without a pin there is nothing to ground on, and demanding an edge anyway
    would manufacture one that is not true.
    """
    module(tmp_path)
    assert "V095" not in codes(run_on(tmp_path))


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    # Direct execution delegates to the same pytest module used by the suite.
    raise SystemExit(pytest.main([__file__, "-q"]))
