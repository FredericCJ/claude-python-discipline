"""Effects are parameters, never reached for.

Enforces `ARCH-005` (a function performing an effect receives the port that
performs it) and `EFCT-002` (time, randomness and environment enter through
ports).

The property being protected is substitutability. An effect passed in can be
replaced by a fake and made to fail on demand; an effect reached for inside a
body cannot, and its failure mode is untestable -- which means it is untested,
which means it is discovered in production.

Scoped to `domain` and `app`. The adapter layer exists precisely to reach for
these things, and the shell wires them together, so reporting either would be
reporting the design working.
"""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, is_test_path, main

# Import annotation-only contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Mapping from each effect-call-name key to its required port-description value; insertion
## order is explanatory only because direct lookup owns classification.
REACHED_FOR: dict[str, str] = {
    "time": "a Clock port",
    "monotonic": "a Clock port",
    "perf_counter": "a Clock port",
    "sleep": "a Clock port",
    "now": "a Clock port",
    "today": "a Clock port",
    "utcnow": "a Clock port",
    "random": "a Random port",
    "randint": "a Random port",
    "choice": "a Random port",
    "shuffle": "a Random port",
    "uuid4": "an Identifier port",
    "getenv": "an Environment port",
    "urandom": "a Random port",
    "system": "a Process port",
    "popen": "a Process port",
    "run": "a Process port",
}

## Unordered effect-module set whose each element is forbidden in the governed core.
REACHED_MODULES = frozenset({"os", "time", "random", "secrets", "subprocess",
                             "socket", "shutil", "tempfile", "webbrowser"})

## Unordered governed-layer set whose each element must receive effects through ports.
GOVERNED = frozenset({"domain", "app"})


class ExplicitEffectsCheck(ModuleCheck):
    """Reports the core reaching for a clock, a random source or the environment."""

    ## Invoked as `python -m checks.explicit_effects`.
    name = "explicit_effects"
    ## Rule-id elements in deterministic reporting order decided by this check.
    rules = ("ARCH-005", "EFCT-002")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for each effect reached for inside the core.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; only `domain` and `app` are governed
        @return finding elements in AST walk order, one per reached-for effect
        """
        # Only non-test domain and application code owns this effect-injection obligation.
        if layer not in GOVERNED or is_test_path(path):
            # Stop iteration outside the rule's exact architectural subject.
            return

        # Inspect each syntax-node element in deterministic AST walk order.
        for node in ast.walk(tree):
            # Imports expose direct acquisition of effectful modules.
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                # Yield each forbidden imported root in statement order.
                yield from self._imports(node, path)
            # Calls expose acquisition through imported aliases such as datetime.
            elif isinstance(node, ast.Call):
                # Yield a call-level finding when its receiver and method are closed matches.
                yield from self._call(node, path, layer)

    def _imports(self, node: ast.Import | ast.ImportFrom, path: Path) -> Iterator[Finding]:
        """Report an import of a module the core may not reach for.

        @param node the import statement
        @param path the file it came from
        @return finding elements in imported-name order, one per offending module
        """
        # Collect imported root-name elements in authored import order.
        roots = (
            [a.name.split(".", 1)[0] for a in node.names] if isinstance(node, ast.Import)
            else [node.module.split(".", 1)[0]] if node.module
            else []
        )
        # Inspect each imported root-name element in statement order.
        for root in roots:
            # Any closed effect-module root is direct capability acquisition.
            if root in REACHED_MODULES:
                # Yield the import finding at the exact statement line.
                yield Finding(
                    "EFCT-002", path, node.lineno,
                    f"the core imports `{root}`, which is an effect it reaches for",
                    "Take the capability as a port parameter instead. An effect "
                    "passed in can be faked and faulted; one imported cannot.",
                )

    def _call(self, node: ast.Call, path: Path, layer: str) -> Iterator[Finding]:
        """Report a call that acquires an effect rather than receiving it.

        Only attribute calls are examined -- `time.time()`, `datetime.now()`. A
        bare `now()` is far more likely to be the caller's own port method, and
        reporting it would make the check unusable in exactly the codebases that
        did the right thing.

        @param node the call expression
        @param path the file it came from
        @param layer the architectural layer, named in the message
        @return zero or one finding element when the call reaches for an effect
        """
        # Bare calls commonly target injected port methods and are intentionally excluded.
        if not isinstance(node.func, ast.Attribute):
            # Stop iteration for a call shape outside the narrow reliable predicate.
            return
        # Select the receiver expression of the qualified call.
        owner = node.func.value
        # Only direct known module names establish a reliable reached-for effect.
        if not isinstance(owner, ast.Name) or owner.id not in REACHED_MODULES | {"datetime", "dt"}:
            # Stop without guessing what a complex receiver represents.
            return
        # Resolve the terminal method name to its required port description.
        port = REACHED_FOR.get(node.func.attr)
        # Unknown methods on an effect module are outside this check's claimed proposition.
        if port is None:
            # Stop without over-reporting module operations that may be pure.
            return
        # Yield the reached-for-effect finding with a concrete injection repair.
        yield Finding(
            "ARCH-005", path, node.lineno,
            f"{layer} reaches for `{owner.id}.{node.func.attr}()`",
            f"Receive {port} as a parameter and call it. The effect then has a "
            f"seam, which is what makes its failure reachable from a test.",
        )


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(ExplicitEffectsCheck()))
