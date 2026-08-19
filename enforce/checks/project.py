"""What a project declares about itself, and what every check reads from it.

The discipline assumed one project's conventions were universal, and two defects
came out of that assumption at once when the checks were first run over a
codebase written by someone who had not read them:

* `layer_of` matched four literal segment names. A project laying its code out as
  `cli / composition / adapters / services / ports / domain` had `services/`,
  `composition/` and `cli/` resolve to `unknown`, so every layer-scoped check
  **skipped them in silence** -- the worst possible outcome, since a clean run
  read as conformance.
* `doc_coverage` demanded Doxygen's `@param` and `##` forms unconditionally. On a
  codebase documenting in Sphinx style it produced 1,064 findings that were the
  form and not the absence, against 18 real defects. A check with that ratio does
  not get read; it gets turned off.

Both are answered here. A project states its layer vocabulary and its
documentation engine in one table, and the mechanisms adapt to what it says.

    [tool.agent-discipline]
    doc_engine = "doxygen"          # doxygen | sphinx | none.  Absent => none.

    [tool.agent-discipline.layers]  # own segment name -> canonical layer
    services = "app"
    composition = "shell"
    cli = "shell"

**This is not an opt-out mechanism and must never become one.** Only two things
are declarable: what a project calls its layers, and which engine reads its
documentation. No rule can be switched off, and a check running with a rule
narrowed by declaration says so on stdout rather than quietly reporting less --
the same reasoning that makes `release.py` announce a dropped leak-scan
identifier instead of scanning with fewer signals in silence.

A project that declares nothing gets the canonical four layers and no engine, and
is told which rules that leaves undecided.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

## The canonical layer names `law/ARCH` defines. The first four are the dependency
## stack, innermost last; a project may map its own segment names onto them but
## may not invent a fifth, because those four are what makes a fault's origin
## derivable from its layer and a fifth would have no defined direction.
##
## `ports` is here and is NOT part of that stack -- it is the boundary the stack
## is drawn against. It was omitted at first for exactly that reason, and the
## omission meant every file under `ports/` resolved to 'unknown'. No check
## happens to be scoped to `ports` today, so nothing was being skipped; what was
## wrong is that `layer_of` answered "unknown" for a file plainly in a layer, and
## the next check scoped to ports would have inherited a silent skip rather than
## a decision.
CANONICAL_LAYERS: Final[tuple[str, ...]] = ("domain", "app", "adapters", "shell",
                                            "ports")

## Documentation engines a project may declare. `doxygen` activates the `@param`
## and `##` forms `law/DOC` describes; `sphinx` and `none` leave `DOC-002` and
## `DOC-007` inactive while `DOC-001` and `DOC-003` still require that every
## element be documented at all.
DOC_ENGINES: Final[frozenset[str]] = frozenset({"doxygen", "sphinx", "none"})

## The table a project writes its declaration in, inside its own pyproject.toml.
TABLE: Final = "agent-discipline"


@dataclass(frozen=True, slots=True)
class Declaration:
    """What one project says about its own conventions."""

    ## Each of the project's own path segments against the canonical layer it
    ## stands for. Empty means the canonical names are used directly.
    layers: Mapping[str, str] = field(default_factory=dict)
    ## Which engine reads this project's documentation comments, deciding whether
    ## the form rules apply. `none` when nothing was declared.
    doc_engine: str = "none"
    ## The file the declaration was read from, or None when nothing was found and
    ## the defaults are in force. Printed so a reader can tell a deliberate
    ## declaration from an absent one.
    source: Path | None = None

    def canonical(self, segment: str) -> str | None:
        """The canonical layer a path segment names, if it names one.

        @param segment one path segment
        @return the canonical layer, or None when the segment is not a layer
        """
        if segment in self.layers:
            return self.layers[segment]
        if segment in CANONICAL_LAYERS:
            return segment
        return None

    def narrowed(self) -> tuple[str, ...]:
        """Which rules this declaration leaves inactive, for the run to announce.

        @return one line per rule narrowed by what was declared, empty when the
            declaration activates everything
        """
        notes: list[str] = []
        if self.doc_engine != "doxygen":
            notes.append(
                f"DOC-002 and DOC-007 are inactive: doc_engine is {self.doc_engine!r}, "
                f"so the @param and ## forms are not required. DOC-001 and DOC-003 "
                f"still require that every element be documented."
            )
        return tuple(notes)


## The declaration in force when a project says nothing at all.
DEFAULT: Final = Declaration()


def find_declaration(start: Path) -> Path | None:
    """The nearest `pyproject.toml` at or above a path that carries the table.

    Walks upward rather than requiring the caller to know where the project root
    is, because a check is usually pointed at `src/` and the declaration lives a
    level or two above it.

    @param start the file or directory the check was pointed at
    @return the declaring file, or None when no ancestor carries the table
    """
    here = start.resolve()
    if here.is_file():
        here = here.parent
    for directory in (here, *here.parents):
        candidate = directory / "pyproject.toml"
        if not candidate.is_file():
            continue
        try:
            data = tomllib.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if TABLE in data.get("tool", {}):
            return candidate
    return None


def parse(path: Path) -> Declaration:
    """Read one declaration, refusing anything it does not understand.

    A misspelled engine or a layer mapped onto a name that is not canonical is an
    error rather than an ignored line: a declaration that silently does nothing is
    worse than none, because the author believes it took effect.

    @param path the `pyproject.toml` to read
    @return the declaration it states
    @throws ValueError when the table names an unknown engine or a layer target
        that is not one of the four canonical names
    """
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    table = data.get("tool", {}).get(TABLE, {})

    engine = str(table.get("doc_engine", "none"))
    if engine not in DOC_ENGINES:
        known = ", ".join(sorted(DOC_ENGINES))
        message = f"{path}: doc_engine {engine!r} is not one of {known}"
        raise ValueError(message)

    layers: dict[str, str] = {}
    for segment, target in (table.get("layers") or {}).items():
        if target not in CANONICAL_LAYERS:
            known = ", ".join(CANONICAL_LAYERS)
            message = (
                f"{path}: layer {segment!r} maps to {target!r}, which is not one of "
                f"the canonical layers ({known}). A project may rename its layers; "
                f"it may not add a fifth."
            )
            raise ValueError(message)
        layers[str(segment)] = str(target)

    return Declaration(layers=layers, doc_engine=engine, source=path)


def load(start: Path, explicit: Path | None = None) -> Declaration:
    """The declaration governing a run, found or defaulted.

    @param start the path the check was pointed at, searched upward from
    @param explicit a declaration named on the command line, which wins outright
        -- the only way to check a tree whose own project file cannot be edited
    @return the declaration, or `DEFAULT` when nothing was found
    @throws ValueError when a declaration is present and malformed
    """
    if explicit is not None:
        return parse(explicit)
    found = find_declaration(start)
    return parse(found) if found is not None else DEFAULT
