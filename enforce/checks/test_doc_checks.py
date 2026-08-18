"""Proof-of-failure tests for the documentation checks.

FLOW-007: each check is driven to fire before its silence on real code is
allowed to mean anything. The conforming cases matter as much as the violating
ones here, because a documentation rule that fires on correct code is a rule
people learn to suppress.

    pytest enforce/checks/test_doc_checks.py
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from checks import Check
from checks.doc_coverage import DocCoverageCheck
from checks.doc_style import DocStyleCheck


def write(tmp_path: Path, source: str, name: str = "mod.py") -> Path:
    """Write a probe module and return its path.

    @param tmp_path the per-test directory
    @param source the module text, dedented before writing
    @param name the file name to use
    @return the path written
    """
    target = tmp_path / "src" / "mypkg" / "domain" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(dedent(source), encoding="utf-8")
    return target


def rules_fired(check: Check, path: Path) -> set[str]:
    """Rule ids the check reports for one file.

    @param check the check to run
    @param path the file to run it over
    @return the set of rule ids reported
    """
    return {f.rule_id for f in check.run([path])}


# ------------------------------------------------------------------- coverage


def test_an_undocumented_module_fires(tmp_path: Path) -> None:
    """A file that opens with code rather than a summary is reported."""
    path = write(tmp_path, "VALUE = 1\n")
    assert "DOC-001" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_function_fires(tmp_path: Path) -> None:
    """A callable with no docstring is reported."""
    path = write(tmp_path, '''
        """! Module."""


        def compute(count: int) -> int:
            return count
    ''')
    assert "DOC-001" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_class_fires(tmp_path: Path) -> None:
    """A class with no docstring is reported."""
    path = write(tmp_path, '''
        """! Module."""


        class Outline:
            pass
    ''')
    assert "DOC-001" in rules_fired(DocCoverageCheck(), path)


def test_an_undocumented_module_constant_fires(tmp_path: Path) -> None:
    """DOC-002: Python has no docstring slot for a constant, so ## is required."""
    path = write(tmp_path, '''
        """! Module."""

        MAX_RETRIES = 3
    ''')
    assert "DOC-002" in rules_fired(DocCoverageCheck(), path)


def test_a_documented_module_constant_is_accepted(tmp_path: Path) -> None:
    """A `##` block above the assignment satisfies DOC-002."""
    path = write(tmp_path, '''
        """! Module."""

        ## How many times a transient failure is retried.
        MAX_RETRIES = 3
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_a_multi_line_hash_block_is_accepted(tmp_path: Path) -> None:
    """A block opens with ## and continues with plain #."""
    path = write(tmp_path, '''
        """! Module."""

        ## How many times a transient failure is retried.
        # Chosen to stay under the port's own timeout budget.
        MAX_RETRIES = 3
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_an_undocumented_class_attribute_fires(tmp_path: Path) -> None:
    """A dataclass field with no `##` block is reported."""
    path = write(tmp_path, '''
        """! Module."""

        from dataclasses import dataclass


        @dataclass(frozen=True, slots=True)
        class Outline:
            """! An outline."""

            title: str
    ''')
    assert "DOC-002" in rules_fired(DocCoverageCheck(), path)


def test_a_documented_enum_member_is_accepted(tmp_path: Path) -> None:
    """Enum members are named values and are documented like any other."""
    path = write(tmp_path, '''
        """! Module."""

        from enum import StrEnum


        class Stage(StrEnum):
            """! Where a document sits in its lifecycle."""

            ## Not yet submitted for review.
            DRAFT = "draft"
            ## Accepted and no longer editable.
            FINAL = "final"
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


def test_an_overload_stub_needs_no_docstring(tmp_path: Path) -> None:
    """An overload declares a signature; the implementation carries the contract."""
    path = write(tmp_path, '''
        """! Module."""

        from typing import overload


        @overload
        def read(name: str) -> str: ...
    ''')
    assert "DOC-001" not in rules_fired(DocCoverageCheck(), path)


def test_a_fully_documented_module_is_silent(tmp_path: Path) -> None:
    """The conforming case must stay quiet, or the rule gets suppressed."""
    path = write(tmp_path, '''
        """! Outline manipulation.

        @package mypkg.domain.mod
        """

        ## How many times a transient failure is retried.
        MAX_RETRIES = 3


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title the replacement title, already validated
            @return the renamed outline
            """
            return title
    ''')
    assert rules_fired(DocCoverageCheck(), path) == set()


# ---------------------------------------------------------------------- style


def test_a_hash_block_where_a_docstring_belongs_fires(tmp_path: Path) -> None:
    """DOC-004: a ## block is invisible to help() and every other Python tool."""
    path = write(tmp_path, '''
        """! Module."""

        ## Give an outline a new title.
        # @param title the replacement
        def rename(title: str) -> str:
            return title
    ''')
    assert "DOC-004" in rules_fired(DocStyleCheck(), path)


def test_a_restated_type_in_a_param_fires(tmp_path: Path) -> None:
    """DOC-008: the signature carries the type; prose carries the meaning."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title (str) the replacement title
            @return the renamed outline
            """
            return title
    ''')
    assert "DOC-008" in rules_fired(DocStyleCheck(), path)


def test_a_restated_return_type_fires(tmp_path: Path) -> None:
    """DOC-008 applies to the return value as much as to parameters."""
    path = write(tmp_path, '''
        """! Module."""


        def rename(title: str) -> str:
            """! Give an outline a new title.

            @param title the replacement title
            @return (str) the renamed outline
            """
            return title
    ''')
    assert "DOC-008" in rules_fired(DocStyleCheck(), path)


def test_documentation_that_restates_the_name_fires(tmp_path: Path) -> None:
    """DOC-009: a comment repeating the identifier answers nothing."""
    path = write(tmp_path, '''
        """! Module."""


        def parse_outline(text: str) -> str:
            """! Parses the outline."""
            return text
    ''')
    assert "DOC-009" in rules_fired(DocStyleCheck(), path)


def test_a_summary_that_adds_meaning_is_accepted(tmp_path: Path) -> None:
    """The check is conservative: a false positive here pushes authors to pad."""
    path = write(tmp_path, '''
        """! Module."""


        def parse_outline(text: str) -> str:
            """! Reject any heading that skips a depth level.

            @param text the source to read
            @return the parsed outline
            """
            return text
    ''')
    assert rules_fired(DocStyleCheck(), path) == set()


def test_tests_are_exempt_from_the_style_check(tmp_path: Path) -> None:
    """Test names state behaviour; their docstrings need no @param block."""
    target = tmp_path / "tests" / "test_thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('"""! Tests."""\n\n\ndef test_x() -> None:\n    pass\n',
                      encoding="utf-8")
    assert rules_fired(DocStyleCheck(), target) == set()


@pytest.mark.parametrize(
    "check", [DocCoverageCheck(), DocStyleCheck()], ids=lambda c: c.name
)
def test_each_check_declares_its_rules(check: Check) -> None:
    """Every check names the rules it decides, so output traces back to law.

    @param check the check under test
    """
    assert check.rules
    assert all(r.startswith("DOC-") for r in check.rules)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
