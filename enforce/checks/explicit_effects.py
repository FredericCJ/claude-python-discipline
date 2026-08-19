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

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

## Module-level calls that reach outside the process or make a result
## irreproducible, against the port each belongs behind. The message names the
## port, because "this is an effect" is a diagnosis and "put it behind a Clock"
## is a repair.
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

## Modules whose mere presence in a domain or app file means an effect is being
## reached for, whatever is called on them.
REACHED_MODULES = frozenset({"os", "time", "random", "secrets", "subprocess",
                             "socket", "shutil", "tempfile", "webbrowser"})

## Layers the rule binds. An adapter reaching for an effect is an adapter doing
## its job; the shell composing them is the composition root doing its job.
GOVERNED = frozenset({"domain", "app"})


class ExplicitEffectsCheck(ModuleCheck):
    """Reports the core reaching for a clock, a random source or the environment."""

    ## Invoked as `python -m checks.explicit_effects`.
    name = "explicit_effects"
    ## The law/ARCH and law/EFCT rules this check decides.
    rules = ("ARCH-005", "EFCT-002")

    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for each effect reached for inside the core.

        @param tree the module's syntax tree
        @param path the file it was parsed from
        @param layer the architectural layer; only `domain` and `app` are governed
        @return one finding per reached-for effect
        """
        if layer not in GOVERNED or is_test_path(path):
            return

        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                yield from self._imports(node, path)
            elif isinstance(node, ast.Call):
                yield from self._call(node, path, layer)

    def _imports(self, node: ast.Import | ast.ImportFrom, path: Path) -> Iterator[Finding]:
        """Report an import of a module the core may not reach for.

        @param node the import statement
        @param path the file it came from
        @return one finding per offending module
        """
        roots = (
            [a.name.split(".", 1)[0] for a in node.names] if isinstance(node, ast.Import)
            else [node.module.split(".", 1)[0]] if node.module
            else []
        )
        for root in roots:
            if root in REACHED_MODULES:
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
        @return one finding when the call reaches for an effect
        """
        if not isinstance(node.func, ast.Attribute):
            return
        owner = node.func.value
        if not isinstance(owner, ast.Name) or owner.id not in REACHED_MODULES | {"datetime", "dt"}:
            return
        port = REACHED_FOR.get(node.func.attr)
        if port is None:
            return
        yield Finding(
            "ARCH-005", path, node.lineno,
            f"{layer} reaches for `{owner.id}.{node.func.attr}()`",
            f"Receive {port} as a parameter and call it. The effect then has a "
            f"seam, which is what makes its failure reachable from a test.",
        )


if __name__ == "__main__":
    raise SystemExit(main(ExplicitEffectsCheck()))
