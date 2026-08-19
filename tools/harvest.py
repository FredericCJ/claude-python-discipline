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
    """
    if not store.ledger.exists():
        return []
    connection = learn.sync(store)
    try:
        rows = connection.execute(
            "SELECT * FROM learning WHERE scope = 'discipline' "
            "AND status NOT IN ('superseded','refuted') ORDER BY id"
        ).fetchall()
        found: list[dict[str, object]] = []
        for row in rows:
            if row["helped"] < min_evidence and not row["verification"]:
                continue
            links = [
                r["node"] for r in connection.execute(
                    "SELECT node FROM link WHERE learning_id = ? ORDER BY node", (row["id"],)
                )
            ]
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
        return found
    finally:
        connection.close()


def render_report(target: Path, found: Sequence[dict[str, object]], min_evidence: int) -> str:
    """The reviewer's view of a harvest, with the triage question attached.

    An empty harvest is spelled out rather than left blank, so it cannot be read
    as a broken run; and each finding carries the question that decides whether
    it belongs upstream at all.

    @param target the repository the findings were read from
    @param found the qualifying learnings
    @param min_evidence the threshold applied, restated for the reader
    @return Markdown text, newline-terminated
    """
    lines = [
        "# Harvest",
        "",
        f"Discipline-scoped learnings from `{target}` with at least {min_evidence} "
        "recorded outcome(s), or a verification command.",
        "",
    ]
    if not found:
        lines += [
            "Nothing to harvest. Either the repository has recorded no discipline-level",
            "findings, or none has enough evidence yet. Both are ordinary states: a",
            "single session disagreeing with a rule is not evidence the rule is wrong.",
            "",
        ]
        return "\n".join(lines)

    lines += ["| Learning | Kind | Evidence | About | Claim |", "|---|---|---|---|---|"]
    for item in found:
        about = ", ".join(f"`{n}`" for n in item["links"]) or "—"  # type: ignore[arg-type]
        lines.append(
            f"| `{item['id']}` | {item['kind']} | {item['evidence']}"
            f" over {item['sessions']} session(s) | {about} | {item['claim']} |"
        )
    lines.append("")

    for item in found:
        lines += [
            f"## {item['id']} — {item['claim']}",
            "",
            f"- **Proposed action** {item['action']}",
            f"- **Triggers** {', '.join(f'`{t}`' for t in item['triggers'])}",  # type: ignore[arg-type]
        ]
        if item["verification"]:
            lines.append(f"- **Verification offered** `{item['verification']}`")
        if item["links"]:
            lines.append(f"- **Concerns** {', '.join(item['links'])}")  # type: ignore[arg-type]
        lines += [
            "",
            "*Review question:* is this a defect in the rule, a gap in its mechanism, or a",
            "project circumstance the rule was never meant to cover? Only the first two",
            "belong upstream.",
            "",
        ]
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
    @return Markdown holding one proposed rule block per learning
    """
    lines = [
        "# Proposed rules",
        "",
        "Each block is shaped for `discipline/meta/SCHEMA.md` section 3. A reviewer",
        "chooses the owning module, allocates the next free ordinal, and supplies the",
        "mechanism — the three things a harvest cannot decide for you.",
        "",
    ]
    for item in found:
        mechanism = (
            f"[check:{str(item['id']).lower().replace('-', '_')}]"
            if item["verification"] else "[review]"
        )
        check_line = (
            f"- **Check** `{item['verification']}`" if item["verification"]
            else "- **Check** TODO: no mechanism proposed; the rule cannot be binding "
                 "without one"
        )
        see = ", ".join(f"[{n}]" for n in item["links"])  # type: ignore[arg-type]
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
    return "\n".join(lines).rstrip() + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Print one repository's harvest, and optionally write the rule proposals.

    Works against either a vendored install or a source checkout, deciding which
    by looking for `.agent/learning`.

    @param argv command-line arguments, defaulting to `sys.argv`
    @return 0 always; finding nothing to harvest is an ordinary outcome, not a
            failure, and must not fail a build that runs this
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

    target = args.target.resolve()
    # A vendored install keeps its learning database under .agent/; a source
    # checkout keeps it at the root.
    root = target / ".agent" if (target / ".agent" / "learning").exists() else target
    found = collect(learn.Store(root), args.min_evidence)

    print(render_report(target, found, args.min_evidence))
    if args.patch:
        args.patch.write_text(render_patch(found), encoding="utf-8")
        print(f"proposed rule text written to {args.patch}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
