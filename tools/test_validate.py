"""Proof-of-failure tests for `validate.py`.

Every check gets a test that drives it to fire. This is the corpus's own
anti-vacuity rule turned on the tooling: a check whose passing signal is "no
output" must first be shown capable of producing a failing signal, or its silence
means nothing.

    pytest tools/test_validate.py
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable, Sequence
from pathlib import Path
from textwrap import dedent

import pytest

from validate import Layout, Severity, run

CONFORMANT_RULE = dedent(
    """\
    ### TYPE-001 · Domain code carries no implicit Any  [BINDING] [auto:mypy]
    Domain modules MUST NOT use `Any`, explicit or implicit.
    - **Why** `Any` erases the guarantee the diagnostic envelope depends on.
    - **Check** `mypy --strict src/`
    """
)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(text), encoding="utf-8")
    return path


def module(
    root: Path,
    *,
    kind: str = "law",
    name: str = "TYPE",
    body: str = CONFORMANT_RULE,
    verified: str | None = None,
    decay: str = "years",
    title: str = "Typing and Contracts",
) -> Path:
    front = [
        "---",
        f"id: {kind}/{name}",
        f"kind: {kind}",
        f"title: {title}",
        "tokens: 0",
        'load_when: ["alpha", "beta", "gamma"]',
        f"decay: {decay}",
    ]
    if verified is not None:
        front.append(f"verified: {verified}")
    front.append("---")
    # Dedent the body on its own: joining it to the unindented front-matter first
    # would leave `dedent` with a common prefix of "" and silently do nothing.
    return write(
        root / "discipline" / kind / f"{name}.md",
        "\n".join(front) + "\n\n" + dedent(body),
    )


def codes(findings: Iterable[object]) -> list[str]:
    return [f.code for f in findings]  # type: ignore[attr-defined]


def run_on(root: Path) -> Sequence[object]:
    return run(Layout(root))


# ---------------------------------------------------------------- the positive case


def test_conformant_corpus_is_silent(tmp_path: Path) -> None:
    module(tmp_path)
    assert codes(run_on(tmp_path)) == []


# ------------------------------------------------------- one failure proof per check


def test_v001_missing_front_matter(tmp_path: Path) -> None:
    write(tmp_path / "discipline" / "law" / "TYPE.md", "# No front-matter here\n")
    assert "V001" in codes(run_on(tmp_path))


def test_v002_front_matter_schema_violation(tmp_path: Path) -> None:
    write(
        tmp_path / "discipline" / "law" / "TYPE.md",
        """\
        ---
        id: law/TYPE
        kind: law
        title: T
        tokens: 0
        decay: forever
        ---
        """,
    )
    assert "V002" in codes(run_on(tmp_path))


def test_v003_id_does_not_match_filename(tmp_path: Path) -> None:
    path = module(tmp_path)
    path.rename(path.with_name("TYPES.md"))
    assert "V003" in codes(run_on(tmp_path))


def test_v004_kind_does_not_match_directory(tmp_path: Path) -> None:
    module(tmp_path, kind="law", name="TYPE")
    src = tmp_path / "discipline" / "law" / "TYPE.md"
    dst = tmp_path / "discipline" / "fact" / "TYPE.md"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    src.unlink()
    assert "V004" in codes(run_on(tmp_path))


def test_v010_rule_in_a_non_rule_genre(tmp_path: Path) -> None:
    module(
        tmp_path,
        kind="fact",
        name="pytyping",
        verified="2026-06-16",
        body=CONFORMANT_RULE.replace("TYPE-001", "PYTYPING-001"),
    )
    assert "V010" in codes(run_on(tmp_path))


def test_v011_binding_in_a_frame_document(tmp_path: Path) -> None:
    module(tmp_path, kind="frame", name="ARCH", body=CONFORMANT_RULE.replace("TYPE-", "ARCH-"))
    assert "V011" in codes(run_on(tmp_path))


def test_v012_law_pins_a_version(tmp_path: Path) -> None:
    module(tmp_path, body=CONFORMANT_RULE + "\nThe project runs mypy 2.3.1 in CI.\n")
    assert "V012" in codes(run_on(tmp_path))


def test_v020_duplicate_rule_id(tmp_path: Path) -> None:
    module(tmp_path)
    module(
        tmp_path,
        name="ERR",
        title="Errors",
        body=CONFORMANT_RULE,  # still declares TYPE-001
    )
    assert "V020" in codes(run_on(tmp_path))


def test_v021_prefix_does_not_match_module(tmp_path: Path) -> None:
    module(tmp_path, name="ERR", title="Errors", body=CONFORMANT_RULE)
    assert "V021" in codes(run_on(tmp_path))


def test_v022_binding_without_a_check(tmp_path: Path) -> None:
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Domain code carries no Any  [BINDING] [auto:mypy]
        Domain modules MUST NOT use Any.
        - **Why** It erases the guarantee.
        """,
    )
    assert "V022" in codes(run_on(tmp_path))


def test_v023_binding_without_a_mechanism(tmp_path: Path) -> None:
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Domain code carries no Any  [BINDING]
        Domain modules MUST NOT use Any.
        - **Check** `mypy --strict src/`
        """,
    )
    assert "V023" in codes(run_on(tmp_path))


def test_v024_overlong_title_warns(tmp_path: Path) -> None:
    long_title = "Domain code carries no Any anywhere at all under any circumstance"
    module(
        tmp_path,
        body=f"""\
        ### TYPE-001 · {long_title}  [BINDING] [auto:mypy]
        Domain modules MUST NOT use Any.
        - **Check** `mypy --strict src/`
        """,
    )
    findings = run_on(tmp_path)
    assert "V024" in codes(findings)
    assert all(f.severity is Severity.WARN for f in findings if f.code == "V024")  # type: ignore[attr-defined]


def test_v030_advisory_without_a_justification(tmp_path: Path) -> None:
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Prefer narrow protocols  [ADVISORY]
        Protocols SHOULD stay small.
        """,
    )
    assert "V030" in codes(run_on(tmp_path))


def test_v030_clears_once_justified(tmp_path: Path) -> None:
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Prefer narrow protocols  [ADVISORY]
        Protocols SHOULD stay small.
        - **No mechanism** "Small" is a judgment about intent that no check can make.
        """,
    )
    assert "V030" not in codes(run_on(tmp_path))


def test_v031_open_without_a_ledger_entry(tmp_path: Path) -> None:
    module(
        tmp_path,
        body="""\
        ### TYPE-001 · Pin the second checker  [OPEN]
        Blocked on choosing a checker.
        """,
    )
    assert "V031" in codes(run_on(tmp_path))


def test_v040_unresolved_cross_reference(tmp_path: Path) -> None:
    module(
        tmp_path,
        body=CONFORMANT_RULE + "\nSee also [ERR-999] for the failure path.\n",
    )
    assert "V040" in codes(run_on(tmp_path))


def test_v040_ignores_a_backticked_example(tmp_path: Path) -> None:
    module(tmp_path, body=CONFORMANT_RULE + "\nA reference looks like `[ERR-999]`.\n")
    assert "V040" not in codes(run_on(tmp_path))


def test_v041_dangling_document_reference(tmp_path: Path) -> None:
    module(tmp_path, body=CONFORMANT_RULE + "\nAs required by `PROPOSAL.md` section 4.\n")
    assert "V041" in codes(run_on(tmp_path))


def test_v050_over_token_budget(tmp_path: Path) -> None:
    filler = "\n".join(f"Sentence number {n} of padding prose." for n in range(2_000))
    module(tmp_path, body=CONFORMANT_RULE + "\n" + filler)
    assert "V050" in codes(run_on(tmp_path))


def test_v060_stale_fact_warns(tmp_path: Path) -> None:
    stale = (dt.date.today() - dt.timedelta(days=400)).isoformat()
    module(tmp_path, kind="fact", name="pytyping", verified=stale, decay="months", body="")
    assert "V060" in codes(run_on(tmp_path))


def test_v070_bare_use_of_a_banned_term(tmp_path: Path) -> None:
    write(
        tmp_path / "discipline" / "meta" / "GLOSSARY.md",
        """\
        ---
        id: meta/GLOSSARY
        kind: meta
        title: Glossary
        tokens: 0
        decay: none
        ---

        ### coverage [BARE-BANNED]
        Say line coverage, branch coverage, or obligation coverage.
        """,
    )
    module(tmp_path, body=CONFORMANT_RULE + "\nThe suite must keep coverage high.\n")
    assert "V070" in codes(run_on(tmp_path))


# --------------------------------------------------------------- the real corpus


def test_the_live_corpus_is_clean() -> None:
    """The repository itself passes every check."""
    findings = [f for f in run() if f.severity is Severity.ERROR]  # type: ignore[attr-defined]
    assert findings == [], "\n".join(f.render() for f in findings)  # type: ignore[attr-defined]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
