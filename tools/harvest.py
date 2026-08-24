"""Export a target repository's discipline-scoped learnings back upstream.

    python tools/harvest.py ../some-repo
    python tools/harvest.py ../some-repo --patch harvest.diff

The vendored discipline is read-only, so a repository that discovers a rule is
wrong, ambiguous or missing cannot fix it in place. It records the finding as a
`discipline`-scoped learning, and this reads those out: a report of what was
found, and -- with `--patch` -- a proposed diff carrying each one as a rule
already in the corpus grammar.

The diff is a proposal. Nothing lands without review, because a learning is
evidence that something is wrong, not agreement about what should replace it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import learn

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Sequence

## A finding needs this much evidence before it is worth an upstream proposal.
## Below it, one session disliked a rule; at or above it, the rule is a problem.
DEFAULT_MIN_EVIDENCE = 2


def collect(store: learn.Store, min_evidence: int) -> list[dict[str, object]]:
    """Discipline-scoped learnings with enough evidence to propose a change.

    Superseded and refuted findings are excluded: they have already been ruled
    on locally. A learning offering a verification command qualifies whatever
    its count, because an executable claim can be checked rather than counted.

    @param store the target repository's learning store
    @param min_evidence how many recorded outcomes a finding needs to qualify
    @return one mapping per qualifying learning, ordered by id; empty when the
            target has no ledger at all

    @par Effects
    May mutate caller-visible or process-local state in implementation order.
    """
    # Select the existing-artifact path only when `not store.ledger.exists()` is satisfied.
    if not store.ledger.exists():
        # An absent ledger represents an empty learning history, not a query failure.
        return []
    # Synchronize the derived store before selecting promotion candidates from it.
    connection = learn.sync(store)
    # Protect the fallible operation so expected failures remain explicitly classified.
    try:
        # Preserve rows element values in deterministic source order.
        rows = connection.execute(
            "SELECT * FROM learning WHERE scope = 'discipline' "
            "AND status NOT IN ('superseded','refuted') ORDER BY id"
        ).fetchall()
        # Accumulate mappings whose each element is one qualifying learning, in database id order.
        found: list[dict[str, object]] = []
        # Evaluate each active discipline learning against the promotion evidence threshold.
        for row in rows:
            # Exclude weak observations that also offer no command capable of verifying them.
            if row["helped"] < min_evidence and not row["verification"]:
                # Advance after the current candidate has been conclusively excluded.
                continue
            # Each links element is one graph-node id attached to this learning; SQL lexical
            # node order is preserved.
            links = [
                r["node"] for r in connection.execute(
                    "SELECT node FROM link WHERE learning_id = ? ORDER BY node", (row["id"],)
                )
            ]
            # Each triggers element is one `type:pattern` selector attached to this learning;
            # SQL type/pattern order is preserved.
            triggers = [
                f"{r['type']}:{r['pattern']}" for r in connection.execute(
                    "SELECT type, pattern FROM trigger WHERE learning_id = ? "
                    "ORDER BY type, pattern", (row["id"],)
                )
            ]
            found.append({
                "id": row["id"], "kind": row["kind"], "claim": row["claim"],
                "action": row["action"], "evidence": row["helped"],
                "sessions": row["sessions"], "confidence": row["confidence"],
                "verification": row["verification"], "links": links,
                "triggers": triggers, "status": row["status"],
            })
        # Expose the surviving promotion candidates in database id order.
        return found
    finally:
        # Publish the externally visible effect after all required inputs are ready.
        connection.close()


def render_report(target: Path, found: Sequence[dict[str, object]], min_evidence: int) -> str:
    """The reviewer's view of a harvest, with the triage question attached.

    An empty harvest is spelled out rather than left blank, so it cannot be read
    as a broken run; and each finding carries the question that decides whether
    it belongs upstream at all.

    @param target the repository the findings were read from
    @param found the qualifying learnings
        Treat found as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @param min_evidence the threshold applied, restated for the reader
    @return Markdown text, newline-terminated
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        "# Harvest",
        "",
        f"Discipline-scoped learnings from `{target}` with at least {min_evidence} "
        "recorded outcome(s), or a verification command.",
        "",
    ]
    # Render an explicit empty state when no learning currently warrants promotion.
    if not found:
        # Preserve lines element values in deterministic source order.
        lines += [
            "Nothing to harvest. Either the repository has recorded no discipline-level",
            "findings, or none has enough evidence yet. Both are ordinary states: a",
            "single session disagreeing with a rule is not evidence the rule is wrong.",
            "",
        ]
        # Return markdown text, newline-terminated to the caller.
        return "\n".join(lines)

    # Preserve lines element values in deterministic source order.
    lines += ["| Learning | Kind | Evidence | About | Claim |", "|---|---|---|---|---|"]
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Process each candidate element in deterministic source order.
    for item in found:
        # Preserve the observed item count used by the non-vacuity verdict.
        about = ", ".join(f"`{n}`" for n in item["links"]) or "—"  # type: ignore[arg-type]
        lines.append(
            f"| `{item['id']}` | {item['kind']} | {item['evidence']}"
            f" over {item['sessions']} session(s) | {about} | {item['claim']} |"
        )
    lines.append("")

    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Process each candidate element in deterministic source order.
    for item in found:
        # Preserve lines, t element values in deterministic source order.
        lines += [
            f"## {item['id']} — {item['claim']}",
            "",
            f"- **Proposed action** {item['action']}",
            f"- **Triggers** {', '.join(f'`{t}`' for t in item['triggers'])}",  # type: ignore[arg-type]
        ]
        # Include a verification command only when the learning actually supplied one.
        if item["verification"]:
            lines.append(f"- **Verification offered** `{item['verification']}`")
        # Expose related doctrine concerns only when the learning names them.
        if item["links"]:
            lines.append(f"- **Concerns** {', '.join(item['links'])}")  # type: ignore[arg-type]
        # Preserve lines element values in deterministic source order.
        lines += [
            "",
            "*Review question:* is this a defect in the rule, a gap in its mechanism, or a",
            "project circumstance the rule was never meant to cover? Only the first two",
            "belong upstream.",
            "",
        ]
    # Return markdown text, newline-terminated to the caller.
    return "\n".join(lines).rstrip() + "\n"


def render_patch(found: Sequence[dict[str, object]]) -> str:
    """A proposal in the corpus grammar, for a reviewer to place and amend.

    Deliberately not a real diff against a file: which module a rule belongs to
    is a judgment, and guessing it would produce a patch that applies cleanly and
    is wrong. What is generated is the rule text, correctly shaped.

    A finding with no verification command is proposed as `[review]` with a TODO
    standing in for its check line, so that the one thing a harvest cannot infer
    -- how the rule would be decided mechanically -- is visibly missing rather
    than absent.

    @param found the qualifying learnings
        Treat found as mapping elements whose keys identify fields and values carry their
        content; key order is deliberately unused.
    @return Markdown holding one proposed rule block per learning
    """
    # Each lines element represents one decoded record; lexical order is preserved.
    lines = [
        "# Proposed rules",
        "",
        "Each block is shaped for `discipline/meta/SCHEMA.md` section 3. A reviewer",
        "chooses the owning module, allocates the next free ordinal, and supplies the",
        "mechanism — the three things a harvest cannot decide for you.",
        "",
    ]
    # Treat the current item as the candidate element consumed by the enclosing transformation.
    # Process each candidate element in deterministic source order.
    for item in found:
        # Select mechanical enforcement for a verifiable learning and review ownership otherwise.
        mechanism = (
            f"[check:{str(item['id']).lower().replace('-', '_')}]"
            if item["verification"] else "[review]"
        )
        # Render the exact verifier or a conspicuous unresolved-mechanism diagnostic.
        check_line = (
            f"- **Check** `{item['verification']}`" if item["verification"]
            else "- **Check** TODO: no mechanism proposed; the rule cannot be binding "
                 "without one"
        )
        # Preserve the observed item count used by the non-vacuity verdict.
        see = ", ".join(f"[{n}]" for n in item["links"])  # type: ignore[arg-type]
        # Preserve lines element values in deterministic source order.
        lines += [
            "```markdown",
            f"### TODO-000 · {str(item['claim'])[:58]}  [BINDING] {mechanism}",
            f"{item['action']}",
            f"- **Why** Observed {item['evidence']} time(s) across "
            f"{item['sessions']} session(s) in a repository using this discipline.",
            check_line,
            *([f"- **See** {see}"] if see else []),
            "```",
            "",
        ]
    # Return markdown holding one proposed rule block per learning to the caller.
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Print one repository's harvest, and optionally write the rule proposals.

    Works against either a vendored install or a source checkout, deciding which
    by looking for `.agent/learning`.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 always; finding nothing to harvest is an ordinary outcome, not a
            failure, and must not fail a build that runs this

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # The console encoding is not ours to choose, and a tool that dies on one is
    # worse than one that renders a character imperfectly.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="Export discipline findings upstream.")
    parser.add_argument("target", type=Path, help="a repository with a vendored discipline")
    parser.add_argument("--patch", type=Path, help="also write proposed rule text here")
    parser.add_argument("--min-evidence", type=int, default=DEFAULT_MIN_EVIDENCE)
    args = parser.parse_args(argv)

    # Resolve the repository-confined path used by this operation before filesystem access.
    target = args.target.resolve()
    # A vendored install keeps its learning database under .agent/; a source
    # checkout keeps it at the root.
    root = target / ".agent" if (target / ".agent" / "learning").exists() else target
    found = collect(learn.Store(root), args.min_evidence)

    print(render_report(target, found, args.min_evidence))
    # Persist the proposed doctrine patch only when the caller requested an output artifact.
    if args.patch:
        # Publish the externally visible effect after all required inputs are ready.
        args.patch.write_text(render_patch(found), encoding="utf-8", newline="\n")
        print(f"proposed rule text written to {args.patch}")
    # Return the aggregate process status to the command-line boundary.
    return 0


# Enter the command-line boundary only when this module is executed directly.
if __name__ == "__main__":
    sys.exit(main())
