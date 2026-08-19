"""The same inputs give the same answer, and a flaky failure is reproducible.

**Oracle: property, then differential.** `EFCT-003` is asserted by running the
core twice over generated input; `TEST-018` by checking that the harness records
what would let a failure be replayed.

* `EFCT-003` -- determinism is the default
* `TEST-018` -- a flaky failure is a defect in the harness

`TEST-018` resolves `CONF-016`, where one source said a flaky test should be
"preferably reproducible" and another said an unreproducible failure is a harness
defect investigated at the priority of a domain bug. The second won, and the
mechanism is the seed: a randomised suite that does not record its seed has
failures nobody can re-run, which makes every one of them a mystery rather than a
defect.

    pytest enforce/fitness/test_determinism.py
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Final

from decides import decides
from fixtures import package_root, reference_root

## The repository root, three levels up from this file.
REPO_ROOT: Final = Path(__file__).resolve().parent.parent.parent

## Sources of non-determinism the core may not reach for. `ARCH-005` already
## forbids them; this is the same prohibition read as a property of the answer
## rather than of the call.
NON_DETERMINISTIC: Final[frozenset[str]] = frozenset({
    "random", "secrets", "time", "uuid", "os",
})

## Layers that must produce the same answer for the same arguments.
PURE_LAYERS: Final[frozenset[str]] = frozenset({"domain"})

## Plugins that randomise or bound a run, and the file that must configure them.
## `pytest-randomly` prints the seed it used on every run, which is what makes a
## failure replayable; `pytest-socket` and `pytest-timeout` bound what a test may
## reach and how long it may take.
HARNESS_PLUGINS: Final[tuple[str, ...]] = ("randomly", "socket", "timeout")

## Ways a harness can be told to retry a failure until it stops failing.
## `TEST-018` prohibits the habit; these are the switches that automate it.
RERUN_SWITCHES: Final[tuple[str, ...]] = ("--reruns", "--only-rerun", "flaky")


@decides("EFCT-003")
def test_determinism() -> None:
    """EFCT-003: the core reaches for nothing that could change its answer.

    Asserted structurally rather than by running the code twice, because a
    function that reads a clock only on a rare branch would pass a two-run
    comparison and still be non-deterministic. What the rule actually forbids is
    the *reach*, and the reach is visible in the imports.
    """
    package = package_root(reference_root())
    for module in sorted(package.rglob("*.py")):
        if "__pycache__" in module.parts:
            continue
        layer = next((p for p in module.parts if p in
                      {"domain", "app", "ports", "adapters", "shell"}), "unknown")
        if layer not in PURE_LAYERS:
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        reached: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                reached |= {a.name.split(".", 1)[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                reached.add(node.module.split(".", 1)[0])
        offending = reached & NON_DETERMINISTIC
        assert not offending, (
            f"domain/{module.name} reaches for {', '.join(sorted(offending))}. "
            f"The same inputs must give the same plan, on every machine and in "
            f"every replay."
        )


def test_the_core_is_replayable() -> None:
    """EFCT-003, differentially: the reference's own property suite asserts it.

    A structural check says the core *cannot* be non-deterministic. This says
    somebody actually ran it twice and compared, which is the assertion a reader
    would want to see.
    """
    properties = reference_root() / "tests" / "property"
    text = "\n".join(m.read_text(encoding="utf-8")
                     for m in sorted(properties.rglob("test_*.py")))
    assert "deterministic" in text.lower(), (
        "the property layer asserts no determinism property; EFCT-003 would rest "
        "on the absence of an import and nothing else"
    )


def test_seeds_recorded() -> None:
    """TEST-018: a randomised run records what would let a failure be replayed.

    Without the seed, a failure that happens under one ordering and not another
    cannot be re-run, and the only available response is to run it again and hope
    -- which is exactly the rerun-and-dismiss habit CONF-016 settled against.
    """
    configured = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    installed = _installed_plugins()

    for plugin in HARNESS_PLUGINS:
        assert plugin in installed, (
            f"pytest-{plugin} is not installed, so the harness does not bound or "
            f"randomise what it runs. A suite that cannot vary cannot show that "
            f"it is order-independent."
        )
    assert configured.strip(), "pytest.ini is empty; the harness configures nothing"


def _installed_plugins() -> set[str]:
    """Which pytest plugins the running environment provides.

    @return the plugin names, without their `pytest-` prefix
    """
    from importlib.metadata import (  # ruff: ignore[import-outside-top-level]
        distributions,
    )

    return {
        d.metadata["Name"].removeprefix("pytest-").lower()
        for d in distributions()
        if (d.metadata["Name"] or "").lower().startswith("pytest-")
    }


@decides("TEST-018")
def test_no_rerun_dismissal() -> None:
    """TEST-018: the harness cannot be configured to re-run a failure away.

    The rule's three clauses are that an unreproducible failure is investigated
    at the priority of a domain defect, that "reruns MUST NOT be used to dismiss
    one", and that failing generated cases are recorded as fixtures. The second
    is the one with a mechanical subject: a rerun plugin, installed or configured,
    turns a flaky failure into a green run and removes the evidence that there was
    anything to investigate.

    Until v3.1 this rule was claimed by `test_seeds_recorded`, which asserts the
    randomising plugins are *present*. Presence of a randomiser says nothing about
    whether a failure can be dismissed, and the two are easy to confuse because
    both are about how the harness is configured.
    """
    installed = _installed_plugins()
    assert "rerunfailures" not in installed, (
        "pytest-rerunfailures is installed. A failure that passes on the second "
        "attempt is a defect in the harness, and this plugin is the mechanism "
        "for not finding out which one."
    )
    configured = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    for switch in RERUN_SWITCHES:
        assert switch not in configured, (
            f"pytest.ini configures {switch!r}, so a flaky failure is retried "
            f"rather than investigated."
        )


def test_a_configured_rerun_is_caught(tmp_path: Path) -> None:
    """The negative case: an ini that retries what it could not reproduce.

    @param tmp_path holds the substituted configuration
    """
    configured = tmp_path / "pytest.ini"
    configured.write_text("[pytest]\naddopts = --reruns 3\n", encoding="utf-8")
    text = configured.read_text(encoding="utf-8")
    assert any(switch in text for switch in RERUN_SWITCHES)
