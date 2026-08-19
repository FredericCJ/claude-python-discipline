"""Proof-of-failure tests for the project declaration.

Two silent failures motivated this module, and both have a case here: a layer
vocabulary the checks did not recognise, which made them skip whole directories
while reporting clean; and one engine's comment syntax demanded of a project
using another, which buried 18 real findings under 1,064 of form.

The declaration is deliberately narrow, so the tests that matter most are the
ones proving it cannot be widened: an unknown engine and a fifth layer are both
refused rather than ignored (`FLOW-007`).

    pytest enforce/checks/test_project.py
"""

from __future__ import annotations

from textwrap import dedent
from typing import TYPE_CHECKING

import pytest

from checks import layer_of, project

if TYPE_CHECKING:
    from pathlib import Path


def declare(tmp_path: Path, body: str) -> Path:
    """Write a project file carrying a declaration.

    @param tmp_path the directory to write into
    @param body the `[tool.agent-discipline]` section, dedented before writing
    @return the written `pyproject.toml`
    """
    path = tmp_path / "pyproject.toml"
    path.write_text(dedent(body), encoding="utf-8")
    return path


# ------------------------------------------------------------------- defaults


def test_an_undeclared_project_gets_the_canonical_layers() -> None:
    """The default must be the strict reading, never a permissive one."""
    assert project.DEFAULT.canonical("domain") == "domain"
    assert project.DEFAULT.canonical("services") is None
    assert project.DEFAULT.doc_engine == "none"


def test_an_undeclared_project_is_told_what_that_costs() -> None:
    """Silence about a narrowed run is the failure this whole table prevents."""
    notes = project.DEFAULT.narrowed()
    assert notes
    assert "DOC-002" in notes[0]
    assert "DOC-007" in notes[0]


def test_a_missing_declaration_falls_back_rather_than_raising(tmp_path: Path) -> None:
    """A project with no table is ordinary, not an error.

    @param tmp_path an empty directory standing in for an undeclaring project
    """
    assert project.load(tmp_path) is project.DEFAULT


# -------------------------------------------------------------- layer aliases


def test_an_aliased_layer_is_recognised(tmp_path: Path) -> None:
    """The defect this exists for: `services/` resolving to no layer at all.

    @param tmp_path the fixture directory
    """
    path = declare(tmp_path, """
        [tool.agent-discipline.layers]
        services = "app"
        composition = "shell"
    """)
    found = project.parse(path)
    assert found.canonical("services") == "app"
    assert layer_of(tmp_path / "src" / "pkg" / "services" / "clean.py", found) == "app"


def test_the_canonical_names_still_work_alongside_aliases(tmp_path: Path) -> None:
    """Declaring an alias must not stop the canonical names being recognised.

    @param tmp_path the fixture directory
    """
    found = project.parse(declare(tmp_path, """
        [tool.agent-discipline.layers]
        services = "app"
    """))
    assert layer_of(tmp_path / "src" / "pkg" / "domain" / "x.py", found) == "domain"


def test_an_unaliased_layer_still_reads_as_unknown(tmp_path: Path) -> None:
    """Undeclared is undeclared; the table must not guess.

    @param tmp_path the fixture directory
    """
    found = project.parse(declare(tmp_path, '[tool.agent-discipline]\ndoc_engine="none"\n'))
    assert layer_of(tmp_path / "src" / "pkg" / "services" / "x.py", found) == "unknown"


def test_a_fifth_layer_is_refused(tmp_path: Path) -> None:
    """A project may rename its layers; it may not invent one.

    Four layers with a defined direction are what make a fault's origin derivable
    from where it was raised. A fifth has no place in that order.

    @param tmp_path the fixture directory
    """
    path = declare(tmp_path, """
        [tool.agent-discipline.layers]
        plugins = "middleware"
    """)
    with pytest.raises(ValueError, match="canonical layers"):
        project.parse(path)


# ------------------------------------------------------------ the doc engine


@pytest.mark.parametrize("engine", ["doxygen", "sphinx", "none"])
def test_each_known_engine_is_accepted(tmp_path: Path, engine: str) -> None:
    """The three the discipline recognises, one at a time.

    @param tmp_path the fixture directory
    @param engine the engine under test
    """
    found = project.parse(declare(tmp_path, f'[tool.agent-discipline]\ndoc_engine="{engine}"\n'))
    assert found.doc_engine == engine


def test_an_unknown_engine_is_refused_not_ignored(tmp_path: Path) -> None:
    """A misspelled engine that silently means `none` is the worst outcome.

    The author believes the form rules are active; they are not, and nothing says
    so. Refusing is the only reading that cannot mislead.

    @param tmp_path the fixture directory
    """
    path = declare(tmp_path, '[tool.agent-discipline]\ndoc_engine="doxy"\n')
    with pytest.raises(ValueError, match="doc_engine"):
        project.parse(path)


def test_doxygen_narrows_nothing(tmp_path: Path) -> None:
    """Under the engine the rules were written for, all four apply.

    @param tmp_path the fixture directory
    """
    found = project.parse(declare(tmp_path, '[tool.agent-discipline]\ndoc_engine="doxygen"\n'))
    assert found.narrowed() == ()


# ---------------------------------------------------------------- the search


def test_the_declaration_is_found_from_a_nested_path(tmp_path: Path) -> None:
    """A check is pointed at `src/`; the declaration lives above it.

    @param tmp_path the fixture directory
    """
    declare(tmp_path, '[tool.agent-discipline]\ndoc_engine="sphinx"\n')
    nested = tmp_path / "src" / "pkg" / "domain"
    nested.mkdir(parents=True)
    assert project.load(nested).doc_engine == "sphinx"


def test_a_project_file_without_the_table_is_not_a_declaration(tmp_path: Path) -> None:
    """Most pyproject.toml files have nothing to say here and must be walked past.

    @param tmp_path the fixture directory
    """
    (tmp_path / "pyproject.toml").write_text('[project]\nname="x"\n', encoding="utf-8")
    assert project.find_declaration(tmp_path) is None


def test_an_explicit_declaration_wins(tmp_path: Path) -> None:
    """The only way to check a tree whose own project file cannot be edited.

    @param tmp_path the fixture directory
    """
    inner = tmp_path / "target"
    inner.mkdir()
    declare(inner, '[tool.agent-discipline]\ndoc_engine="doxygen"\n')
    outside = declare(tmp_path, '[tool.agent-discipline]\ndoc_engine="sphinx"\n')
    assert project.load(inner, outside).doc_engine == "sphinx"
