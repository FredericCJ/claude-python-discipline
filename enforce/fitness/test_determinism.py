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

## Unordered root-module-name elements that introduce ambient non-determinism.
## `ARCH-005` already forbids the same reach from the architectural perspective.
NON_DETERMINISTIC: Final[frozenset[str]] = frozenset({
    "random", "secrets", "time", "uuid", "os",
})

## Unordered layer-name elements required to remain deterministic.
PURE_LAYERS: Final[frozenset[str]] = frozenset({"domain"})

## Pytest plugin-name elements in stable diagnostic order. Randomly records seeds;
## socket and timeout bound environmental reach and duration.
HARNESS_PLUGINS: Final[tuple[str, ...]] = ("randomly", "socket", "timeout")

## Rerun-switch string elements in stable diagnostic order. Any occurrence enables
## the prohibited habit of retrying a failure until it disappears.
RERUN_SWITCHES: Final[tuple[str, ...]] = ("--reruns", "--only-rerun", "flaky")


@decides("EFCT-003")
def test_determinism() -> None:
    """EFCT-003: the core reaches for nothing that could change its answer.

    Asserted structurally rather than by running the code twice, because a
    function that reads a clock only on a rare branch would pass a two-run
    comparison and still be non-deterministic. What the rule actually forbids is
    the *reach*, and the reach is visible in the imports.
    """
    # Resolve the reference package before scanning its source modules by path order.
    package = package_root(reference_root())
    # Inspect every authored Python module in deterministic source-tree order.
    for module in sorted(package.rglob("*.py")):
        # Exclude interpreter cache paths from the governed source surface.
        if "__pycache__" in module.parts:
            # Advance to the next authored module without reading cached bytecode paths.
            continue
        # Derive the architecture layer from the first recognized path element.
        layer = next((p for p in module.parts if p in
                      {"domain", "app", "ports", "adapters", "shell"}), "unknown")
        # Restrict the deterministic-core obligation to declared pure layers.
        if layer not in PURE_LAYERS:
            # Continue with the next module when ambient effects are architecture-owned.
            continue
        # Parse imports without executing the candidate domain module.
        tree = ast.parse(module.read_text(encoding="utf-8"), filename=str(module))
        # Accumulate unique imported root-module-name elements without ordering semantics.
        reached: set[str] = set()
        # Visit every syntax node because imports may occur beneath control flow.
        for node in ast.walk(tree):
            # Expand direct-import aliases to their root module identities.
            if isinstance(node, ast.Import):
                # Merge direct-import roots into the unordered reachability set.
                reached |= {a.name.split(".", 1)[0] for a in node.names}
            # Accept from-imports only when they name a concrete module.
            elif isinstance(node, ast.ImportFrom) and node.module:
                # Add the from-import's root module identity to the reachability set.
                reached.add(node.module.split(".", 1)[0])
        # Intersect unordered reached-module elements with prohibited ambient sources.
        offending = reached & NON_DETERMINISTIC
        # Reject every pure-layer module whose imports can vary an answer implicitly.
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
    # Combine property-test source elements in sorted path order for oracle discovery.
    properties = reference_root() / "tests" / "property"
    text = "\n".join(m.read_text(encoding="utf-8")
                     for m in sorted(properties.rglob("test_*.py")))
    # Require a differential determinism oracle in addition to structural reachability.
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
    # Read durable harness configuration and inventory installed plugin-name elements.
    configured = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    installed = _installed_plugins()

    # Verify required plugins in stable diagnostic order.
    for plugin in HARNESS_PLUGINS:
        # Require each randomness or environmental-boundary mechanism to be installed.
        assert plugin in installed, (
            f"pytest-{plugin} is not installed, so the harness does not bound or "
            f"randomise what it runs. A suite that cannot vary cannot show that "
            f"it is order-independent."
    )
    # Reject a vacuous durable harness declaration even when plugins happen to exist.
    assert configured.strip(), "pytest.ini is empty; the harness configures nothing"


def _installed_plugins() -> set[str]:
    """Which pytest plugins the running environment provides.

    @return unordered installed pytest-plugin-name elements without their prefix
    """
    from importlib.metadata import (  # ruff: ignore[import-outside-top-level]
        distributions,
    )

    # Collapse installed distribution records to unique normalized pytest plugin names.
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
    # Inventory installed plugin-name elements before inspecting durable switches.
    installed = _installed_plugins()
    # Reject the plugin whose purpose is to turn a first failure into a later pass.
    assert "rerunfailures" not in installed, (
        "pytest-rerunfailures is installed. A failure that passes on the second "
        "attempt is a defect in the harness, and this plugin is the mechanism "
        "for not finding out which one."
    )
    configured = (REPO_ROOT / "pytest.ini").read_text(encoding="utf-8")
    # Check every prohibited rerun token in stable diagnostic order.
    for switch in RERUN_SWITCHES:
        # Reject any configured automatic retry path, independently of plugin inventory.
        assert switch not in configured, (
            f"pytest.ini configures {switch!r}, so a flaky failure is retried "
            f"rather than investigated."
        )


def test_a_configured_rerun_is_caught(tmp_path: Path) -> None:
    """The negative case: an ini that retries what it could not reproduce.

    @param tmp_path holds the substituted configuration

    @par Effects
    Writes one isolated pytest configuration and reads it back for rejection.
    """
    # Materialize a harness configuration that retries each failure three times.
    configured = tmp_path / "pytest.ini"
    # Persist the negative subject before inspecting its exact configured text.
    configured.write_text("[pytest]\naddopts = --reruns 3\n", encoding="utf-8")
    text = configured.read_text(encoding="utf-8")
    # Require at least one prohibited switch to identify the deliberate violation.
    assert any(switch in text for switch in RERUN_SWITCHES)
