"""The process boundary: exit codes, structured output, and the last catch.

`ERR-015` -- no unhandled exception reaches the process boundary. Everything is
caught here, turned into an envelope, and reported once (`DIAG-010`). This is the
only module allowed to catch broadly, and the `noqa` below is the whole of that
permission: anywhere else it would be `ERR-008` catching too much.

`API-005` -- structured output is the primary interface, and the human rendering
formats the same result object rather than computing a second answer.

Exit status is part of the contract (`API-007`), so the codes are named constants
rather than literals scattered through a function.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from refpkg.app.prune import apply, survey
from refpkg.domain.model import Policy
from refpkg.domain.plan import Outcome, Plan, Refusal, narrow
from refpkg.shell import envelope
from refpkg.shell.composition import Wiring, production

# Keep the command argument sequence contract out of runtime shell imports.
if TYPE_CHECKING:
    from collections.abc import Sequence

## Everything asked for was done.
EXIT_OK: int = 0
## The planner refused, or the run failed. The reason is in the envelope on
## stderr, and a retry may succeed.
EXIT_REFUSED: int = 1
## The command line itself was wrong. Distinguished from a refusal because no
## amount of retrying the same invocation will help.
EXIT_USAGE: int = 2

## The version of the payload this command emits, so a consumer can tell whether
## it understands what it just parsed (`API-010`).
SCHEMA_VERSION: str = "1"


def build_parser() -> argparse.ArgumentParser:
    """The command-line surface.

    @return the parser; `--apply` is opt-in because the default for a
        destructive command must be the one that changes nothing (`EFCT-005`)
    """
    # Assemble the complete destructive command surface before publishing its parser.
    parser = argparse.ArgumentParser(prog="refpkg", description="Prune stale files.")
    parser.add_argument("root", type=Path, help="the directory to prune")
    parser.add_argument("--max-age-days", type=int, default=30)
    parser.add_argument("--keep-newest", type=int, default=3)
    parser.add_argument("--apply", action="store_true",
                        help="perform the plan; without this the plan is only reported")
    return parser


def render(payload: dict[str, Any], *, as_json: bool) -> str:
    """Format one result object for a reader.

    Both renderings take the *same* object (`API-006`). A human rendering
    computed separately would be a second implementation of the answer, free to
    disagree with the machine-readable one.

    @param payload each result field keyed by schema name; key order is normalized here
    @param as_json True emits canonical JSON; False emits sorted human-readable fields
    @return the text to print
    """
    # Select one rendering over the same result object without recomputing its meaning.
    if as_json:
        # Preserve every field and normalize key order in the machine representation.
        return json.dumps(payload, indent=1, sort_keys=True)
    # Preserve the same fields in deterministic key order for a human reader.
    return "\n".join(f"{key}: {value}" for key, value in sorted(payload.items()))


def describe(plan: Plan, deleted: tuple[str, ...] | None) -> dict[str, Any]:
    """The result object for a completed run.

    @param plan what was decided
    @param deleted each removed path in execution order, or None when nothing was applied
    @return the payload, identical in shape whether or not the plan was applied
    """
    # Project each plan partition and execution fact into one stable payload shape.
    return {
        "schema_version": SCHEMA_VERSION,
        "doomed": [entry.path for entry in plan.doomed],
        "kept": [entry.path for entry in plan.kept],
        "reclaimed_bytes": plan.reclaimed_bytes,
        "applied": deleted is not None,
        "deleted": list(deleted or ()),
    }


def run(wiring: Wiring, policy: Policy, *, apply_it: bool) -> tuple[int, dict[str, Any]]:
    """Survey, optionally apply, and return the exit code with its payload.

    Separated from `main` so the whole pipeline can be driven against fake
    adapters in a test without a process, argument parsing or a captured stream.

    @param wiring the bound ports
    @param policy what the caller considers stale
    @param apply_it True performs the accepted plan; False reports it without mutation
    @return the exit code and the object to render
    """
    # Compute the complete domain outcome before choosing any destructive continuation.
    outcome: Outcome = survey(wiring.store, wiring.clock, policy)
    # A `match` rather than a chain of `isinstance`, because with the union at
    # exactly two variants the second test is provably redundant and pyright
    # says so. The wildcard arm keeps what the chain was there for: when a third
    # variant joins `Outcome`, `narrow` no longer receives `Never` and the type
    # checker rejects this function until the arm is written (`ERR-002`).
    match outcome:
        case Refusal():
            # Preserve the expected refusal as a structured domain envelope.
            return EXIT_REFUSED, envelope.from_refusal(outcome)
        case Plan():
            # Apply only when explicitly selected, retaining None as the dry-run marker.
            deleted = apply(wiring.store, outcome) if apply_it else None
            return EXIT_OK, describe(outcome, deleted)
        case _:
            # Make any future unhandled outcome arm fail static exhaustiveness checking.
            return narrow(outcome)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command, reporting through the envelope on any failure.

    @param argv the command-line arguments, or None to read `sys.argv`
    @return one of the `EXIT_*` codes
    """
    # Parse one invocation before entering the process boundary's final containment scope.
    args = build_parser().parse_args(argv)
    # Translate every boundary failure exactly once after argument parsing succeeds.
    try:
        # Validate policy values and execute the fully composed application pipeline.
        policy = Policy.parse(args.max_age_days, args.keep_newest)
        code, payload = run(production(args.root), policy, apply_it=args.apply)
    except Exception as exc:  # ruff: ignore[blind-except] - the process boundary; see ERR-015
        # Render the captured failure through the one diagnostic-envelope owner.
        print(render(envelope.from_error(exc), as_json=True), file=sys.stderr)
        return EXIT_REFUSED
    # Route the completed payload by stable status without changing its schema.
    stream = sys.stdout if code == EXIT_OK else sys.stderr
    print(render(payload, as_json=True), file=stream)
    return code


# Convert the library-style result into the process exit status only at execution time.
if __name__ == "__main__":
    # Terminate the interpreter with the stable command status returned above.
    raise SystemExit(main())
