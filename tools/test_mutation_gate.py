"""Failure proofs for the portable project mutation gate.

These are control experiments against the real Cosmic Ray distribution.  The
same tiny domain is first paired with a discriminating oracle and then with an
oracle that merely executes the code.  A wrapper that trusted exit status,
generated zero mutants, or scored the unmutated baseline would fail this pair.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

import mutation_gate

if TYPE_CHECKING:
    from pathlib import Path


def _project(root: Path, assertion: str) -> None:
    """Create a minimal declared domain and its selected unit suite.

    @param root isolated project root
    @param assertion body of the one unit-test oracle
    """
    domain = root / "src" / "sample" / "domain"
    tests = root / "tests" / "unit"
    domain.mkdir(parents=True)
    tests.mkdir(parents=True)
    (domain / "__init__.py").write_text("", encoding="utf-8")
    (domain / "core.py").write_text(
        '"""A deliberately tiny mutation subject."""\n\n\n'
        "def increment(value: int) -> int:\n"
        '    """Return the following integer."""\n'
        "    return value + 1\n",
        encoding="utf-8",
    )
    (tests / "test_core.py").write_text(
        "from sample.domain.core import increment\n\n\n"
        "def test_increment() -> None:\n"
        f"    {assertion}\n",
        encoding="utf-8",
    )
    (root / "pyproject.toml").write_text(
        "[tool.agent-discipline]\n"
        'unit = "application"\n'
        'source_roots = ["src"]\n\n'
        "[tool.agent-discipline.roles]\n"
        'domain = ["src/sample/domain/core.py"]\n\n'
        "[tool.agent-discipline-gate.mutation]\n"
        'test_targets = ["tests/unit"]\n'
        "mutant_timeout = 5\n"
        "command_timeout = 120\n"
        "maximum_survival = 0.0\n",
        encoding="utf-8",
    )


@pytest.mark.timeout(180)
def test_cosmic_ray_kills_a_non_empty_domain_mutant_set(tmp_path: Path) -> None:
    """A discriminating oracle earns a green, non-vacuous mutation report.

    @param tmp_path isolated project root
    """
    _project(
        tmp_path,
        "assert increment(0) == 1 and increment(1) == 2 and increment(2) == 3",
    )

    report = mutation_gate.run(tmp_path)

    assert report.status == "pass", report.output
    assert report.diagnostic_id is None
    assert report.mutants > 0
    assert report.domains == 1


@pytest.mark.timeout(180)
def test_cosmic_ray_rejects_a_suite_that_only_executes_the_core(tmp_path: Path) -> None:
    """A surviving mutant is red even though the ordinary baseline passes.

    @param tmp_path isolated project root
    """
    _project(tmp_path, "assert isinstance(increment(0), int)")

    report = mutation_gate.run(tmp_path)

    assert report.status == "fail", report.as_dict()
    assert report.diagnostic_id == "MUTATION-009_SURVIVOR"
    assert "zero-survivor score" in report.summary


def test_a_positive_survival_allowance_is_refused(tmp_path: Path) -> None:
    """Known test defects cannot be converted into an accepted percentage.

    @param tmp_path isolated project root
    """
    _project(tmp_path, "assert increment(0) == 1")
    project = tmp_path / "pyproject.toml"
    project.write_text(
        project.read_text(encoding="utf-8").replace(
            "maximum_survival = 0.0", "maximum_survival = 1.0",
        ),
        encoding="utf-8",
    )

    report = mutation_gate.run(tmp_path)

    assert report.status == "fail"
    assert report.diagnostic_id == "MUTATION-001_CONFIGURATION"
    assert "must be 0.0" in report.summary
