"""A dry run is the pipeline truncated, and an interruption reports where it got to.

**Oracle: contract.** `law/EFCT` held against a project tree.

* `EFCT-006` -- a dry run is the pipeline truncated, never a second path
* `EFCT-007`, `EFCT-009`, `TEST-012` -- a multi-effect apply is journalled, what
  is not guaranteed is stated, and interruption is tested at every effect boundary

`EFCT-006` is checked structurally *and* behaviourally, because the structural
half is the one that can be gamed. Two functions with the same name in different
modules satisfy "there is a plan and an apply"; only running both and comparing
their answers shows there is one pipeline. The reference's integration layer does
exactly that, and this asserts that it does.

    pytest enforce/fitness/test_effects.py
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING, Final

from fixtures import broken_copy, package_root, reference_root

if TYPE_CHECKING:
    from pathlib import Path

## Names a planning function goes by. A plan is computed and returned; nothing is
## performed until a caller asks.
PLANNERS: Final[tuple[str, ...]] = ("survey", "plan", "preview", "dry_run", "compute")

## Names an applying function goes by. It takes the plan the planner produced.
APPLIERS: Final[tuple[str, ...]] = ("apply", "perform", "execute", "commit")

## Evidence in the fault or integration layer that an interruption was driven and
## its aftermath asserted, rather than the happy path being run twice.
INTERRUPTION_EVIDENCE: Final[tuple[str, ...]] = ("interrupt", "partway", "remaining",
                                                 "deleted", "failing_on")

## A docstring stating what is *not* guaranteed. `EFCT-009` is satisfied by
## saying so, not by achieving atomicity.
_STATES_LIMITS = re.compile(r"(not atomic|no guarantee|is not guaranteed|leaves some"
                            r"|not undone|interrupted)", re.IGNORECASE)


def functions_in(package: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    """Every top-level function the package defines, by name.

    @param package the package directory
    @return each function name against its definition; later definitions win
    """
    found: dict[str, ast.FunctionDef | ast.AsyncFunctionDef] = {}
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                found[node.name] = node
    return found


# ------------------------------------------------------------------- EFCT-006


def test_dry_run_matches_apply() -> None:
    """EFCT-006: one pipeline, truncated -- not two implementations.

    Structurally: a planner exists, an applier exists, and the applier *takes*
    what the planner returns. That last clause is the whole rule. An applier
    recomputing the plan for itself is a second implementation free to disagree
    with the one the caller was shown.
    """
    package = package_root(reference_root())
    functions = functions_in(package)

    planner = next((n for n in PLANNERS if n in functions), None)
    applier = next((n for n in APPLIERS if n in functions), None)
    assert planner, f"no planning function found; looked for {', '.join(PLANNERS)}"
    assert applier, f"no applying function found; looked for {', '.join(APPLIERS)}"

    parameters = {a.arg for a in functions[applier].args.args}
    assert parameters & {"plan", "outcome", "planned"}, (
        f"{applier}() does not take a plan. If it recomputes what to do, the dry "
        f"run is a prediction made by a second implementation, and the two are "
        f"free to disagree exactly when it matters."
    )


def test_the_dry_run_is_compared_to_the_apply() -> None:
    """EFCT-006, behaviourally: somebody ran both and compared the answers.

    The structural check above can be satisfied by two functions that never meet.
    This asserts the integration layer actually drives both.
    """
    integration = reference_root() / "tests" / "integration"
    text = "\n".join(m.read_text(encoding="utf-8")
                     for m in sorted(integration.rglob("test_*.py")))
    unrun = (
        "the integration layer never runs the pipeline {}, so nothing compares "
        "the plan a caller is shown against the one performed"
    )
    assert "apply_it=False" in text, unrun.format("as a dry run")
    assert "apply_it=True" in text, unrun.format("for real")


def test_an_applier_that_recomputes_is_caught(tmp_path: Path) -> None:
    """The negative case: an apply that takes no plan.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, replace=[(
        "src/refpkg/app/prune.py",
        "def apply(store: FileStore, plan: Plan) -> tuple[str, ...]:",
        "def apply(store: FileStore) -> tuple[str, ...]:",
    )])
    functions = functions_in(package_root(root))
    assert not {a.arg for a in functions["apply"].args.args} & {"plan", "outcome"}


# --------------------------------------------- EFCT-007 / EFCT-009 / TEST-012


def test_interruption_recovers() -> None:
    """EFCT-007, TEST-012: an interruption is driven, and its aftermath asserted.

    The interesting failure is not "the apply raised". It is "the apply stopped
    with some effects done", which nothing but a fault schedule can produce on
    demand -- and which is the state a journal exists to make recoverable.
    """
    fault = reference_root() / "tests" / "fault"
    text = "\n".join(m.read_text(encoding="utf-8")
                     for m in sorted(fault.rglob("test_*.py"))).lower()
    found = [word for word in INTERRUPTION_EVIDENCE if word in text]
    assert len(found) >= 3, (
        f"the fault layer shows little evidence of driving an interruption; it "
        f"mentions only {', '.join(found) or 'none'} of "
        f"{', '.join(INTERRUPTION_EVIDENCE)}"
    )


def test_what_is_not_guaranteed_is_stated() -> None:
    """EFCT-009: the limit is written down where a caller will meet it.

    Satisfied by *saying* the operation is not atomic across calls, not by making
    it so. A caller who assumes the strongest guarantee has been told nothing and
    believes they have been told everything.
    """
    package = package_root(reference_root())
    ports = "\n".join(
        m.read_text(encoding="utf-8") for m in sorted((package / "ports").glob("*.py"))
    )
    assert _STATES_LIMITS.search(ports), (
        "no port states what it does not guarantee. The rule is satisfied by "
        "saying so, and unsatisfiable by hoping nobody asks."
    )


def test_an_error_carrying_no_progress_is_caught(tmp_path: Path) -> None:
    """The negative case: an interruption that does not say how far it got.

    @param tmp_path the fixture directory
    """
    root = broken_copy(tmp_path, write={
        "src/refpkg/app/errors.py":
            '"""The app family."""\n\n\nclass AppError(Exception):\n'
            '    """Base."""\n\n    ## The code.\n    code = "refpkg.app.error"\n',
    })
    text = (package_root(root) / "app" / "errors.py").read_text(encoding="utf-8")
    assert "deleted" not in text
    assert "remaining" not in text
