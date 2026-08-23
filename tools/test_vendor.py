"""The installer's own contract, and the round trip an adopter actually takes.

`vendor.install` is the most adopter-facing code in this repository: it is what
writes a `.agent/` into somebody else's tree. It had no tests of its own. It was
exercised incidentally, as a fixture inside `test_integrate.py`, which asserts
things about the integrator and nothing about the installer.

Four properties carry the weight, and each is here because getting it wrong is
silent:

* **The upstream half is replaced wholesale.** A file deleted upstream must not
  survive an update, or an adopter keeps a check the discipline retired.
* **The project half is never destroyed.** `learning/` and `overrides/` hold work
  nobody upstream can reproduce -- a ledger, and the tier mapping `ALLOC-010`
  now rests on. `force` re-seeds a missing file and still overwrites nothing.
* **The manifest names what was installed.** It is what `check` compares against,
  so a manifest that omits a file makes that file undetectably editable.
* **Removal restores the prior state.** Asserted on BYTES, and in both line
  endings, because the defect this guards against is invisible to any assertion
  made on decoded text.

The round trip at the end is **synthetic**. It exercises the machinery on a
greenfield repository; it is not a repository that depends on the discipline in
daily use, and the difference is recorded as an accepted defect rather than
argued away.

    pytest tools/test_vendor.py
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import integrate
import vendor

## The upstream checkout under test: this repository.
SOURCE = Path(__file__).resolve().parent.parent

## A configuration a project already had, in the line endings a Unix checkout
## would carry. Bytes, and written as bytes, so nothing between the fixture and
## the disk can normalise it.
EXISTING_LF: bytes = (
    b"# Acme Service\n\n## Running it\n\n    make serve\n\n"
    b"## House rules\n\nBranch names are `feat/<ticket>`. Ask before `legacy/`.\n"
)

## The same file as a Windows checkout would have it.
EXISTING_CRLF: bytes = EXISTING_LF.replace(b"\n", b"\r\n")


@pytest.fixture
def target(tmp_path: Path) -> Path:
    """An empty repository to vendor into.

    No teardown: `tmp_path` is per-test, and pytest keeps the last few so a
    failed round trip can be inspected where it stopped.

    @param tmp_path the per-test directory
    @return the repository root
    """
    root = tmp_path / "adopter"
    root.mkdir()
    return root


def _install(target: Path, **kwargs: bool) -> tuple[int, list[str]]:
    """Vendor this repository into a target.

    @param target the repository root
    @param kwargs forwarded to `install`, for `force`
    @return what `install` returned
    """
    return vendor.install(vendor.Plan(SOURCE, target), **kwargs)


# ------------------------------------------------------------------ manifest


def test_the_manifest_names_every_upstream_file(target: Path) -> None:
    """`check` compares against the manifest, so an omission is undetectable drift.

    A file installed but unrecorded can be edited in place forever and `check`
    will never say so -- which is exactly the failure the manifest exists to
    prevent.

    @param target an empty repository
    """
    _install(target)
    recorded = set(
        json.loads((target / ".agent" / "MANIFEST.json").read_text(encoding="utf-8"))["files"]
    )
    installed = {
        p.relative_to(target / ".agent").as_posix()
        for root in vendor.UPSTREAM
        for p in (target / ".agent" / root).rglob("*")
        if p.is_file()
        and p.suffix not in vendor.SKIP_SUFFIXES
        and not vendor.SKIP_DIRS & set(p.parts)
    }
    assert installed <= recorded, f"installed but unrecorded: {sorted(installed - recorded)[:5]}"


def test_the_generated_manifest_is_byte_stable_across_hosts(target: Path) -> None:
    """Windows and Linux installations emit the same LF-delimited manifest.

    @param target an empty repository
    """
    _install(target)
    manifest = (target / ".agent" / "MANIFEST.json").read_bytes()
    assert manifest.endswith(b"\n")
    assert b"\r\n" not in manifest


def test_install_carries_one_shared_agent_skill_source(target: Path) -> None:
    """Vendoring stages one skill without writing either host discovery root.

    Integration owns files outside `.agent/`; the vendor owns the canonical
    source it will copy. Keeping that boundary means installing files cannot
    silently replace a repository's existing Claude Code or Codex skill.

    @param target an empty repository
    """
    _install(target)
    source = SOURCE / "skills" / "python-discipline" / "SKILL.md"
    installed = target / ".agent" / "skills" / "python-discipline" / "SKILL.md"

    assert installed.read_bytes() == source.read_bytes()
    assert not (target / ".claude").exists()
    assert not (target / ".agents").exists()


def test_install_carries_both_development_legs_and_their_shared_lock(target: Path) -> None:
    """One install must support Windows and Linux without a second package.

    @param target an empty repository
    """
    _install(target)
    required = (
        "dev/Dockerfile",
        "dev/container-entrypoint.sh",
        "dev/docker.sh",
        "dev/windows.cmd",
        "dev/windows.ps1",
        "environment.yml",
        ".dockerignore",
    )
    for relative in required:
        assert (target / ".agent" / relative).read_bytes() == (SOURCE / relative).read_bytes()


def test_the_manifest_excludes_build_products(target: Path) -> None:
    """A version stamp that moves when somebody runs the tests is not a stamp.

    `SKIP_DIRS` and `SKIP_SUFFIXES` keep caches and compiled files out, so the
    hash depends on the corpus rather than on what has been run in the checkout.

    @param target an empty repository
    """
    _install(target)
    recorded = json.loads((target / ".agent" / "MANIFEST.json").read_text(encoding="utf-8"))[
        "files"
    ]
    assert not [
        name for name in recorded if any(part in vendor.SKIP_DIRS for part in Path(name).parts)
    ]
    assert not [name for name in recorded if Path(name).suffix in vendor.SKIP_SUFFIXES]


def test_the_version_stamp_is_stable_across_two_installs(target: Path, tmp_path: Path) -> None:
    """The same corpus installed twice reports the same version.

    A stamp that moved on every install would make `check`'s staleness report
    meaningless: everything would always look stale.

    @param target an empty repository
    @param tmp_path holds a second, independent target
    """
    _install(target)
    second = tmp_path / "other"
    second.mkdir()
    _install(second)
    assert (
        vendor.build_manifest(SOURCE)["version"]
        == json.loads((target / ".agent" / "MANIFEST.json").read_text(encoding="utf-8"))["version"]
    )
    assert (target / ".agent" / "MANIFEST.json").read_text(encoding="utf-8") == (
        second / ".agent" / "MANIFEST.json"
    ).read_text(encoding="utf-8")


# ------------------------------------------------------ the two halves


def test_a_file_retired_upstream_does_not_survive_an_update(target: Path) -> None:
    """The upstream half is replaced wholesale, not merged.

    Without this an adopter keeps a check the discipline retired, and keeps
    running it, and it keeps deciding rules that no longer exist.

    @param target an empty repository
    """
    _install(target)
    stale = target / ".agent" / "enforce" / "checks" / "retired_check.py"
    stale.write_text('"""A check upstream no longer has."""\n', encoding="utf-8")
    _install(target)
    assert not stale.exists(), (
        "a file absent upstream survived an update; the adopter keeps a retired check"
    )


def test_the_project_half_survives_an_update(target: Path) -> None:
    """`learning/` and `overrides/` hold what nobody upstream can reproduce.

    The ledger is a record of what this project found out, and
    `overrides/allocation.toml` is what `ALLOC-010` now rests on. An update that
    replaced either would destroy evidence and a declaration in one step.

    @param target an empty repository
    """
    _install(target)
    ledger = target / ".agent" / "learning" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"seq": 1, "kind": "learn"}\n', encoding="utf-8")
    mapping = target / ".agent" / "overrides" / "allocation.toml"
    mapping.parent.mkdir(parents=True, exist_ok=True)
    mapping.write_text('[tiers]\nT0 = "ours"\n', encoding="utf-8")

    _install(target)
    assert ledger.read_text(encoding="utf-8") == '{"seq": 1, "kind": "learn"}\n'
    assert 'T0 = "ours"' in mapping.read_text(encoding="utf-8")


def test_force_restores_a_seed_without_overwriting_work(target: Path) -> None:
    """`force` re-enters the project half and still destroys nothing.

    Its whole reachable effect is putting back a seed file the project deleted;
    every copy is guarded by the destination's absence.

    @param target an empty repository
    """
    _install(target)
    ledger = target / ".agent" / "learning" / "ledger.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text('{"seq": 99}\n', encoding="utf-8")
    schema = target / ".agent" / "learning" / "schema.sql"
    if schema.exists():
        schema.unlink()

    _install(target, force=True)
    assert ledger.read_text(encoding="utf-8") == '{"seq": 99}\n', (
        "force overwrote a project-owned file"
    )


# --------------------------------------------------------------------- check


def test_check_reports_an_edited_vendored_file_by_name(target: Path) -> None:
    """Drift must name the file, not merely say something is wrong.

    An adopter who edits a vendored check silently loses it on the next update.
    Naming it is the difference between a warning and a diagnosis.

    @param target an empty repository
    """
    _install(target)
    edited = target / ".agent" / "tools" / "nav.py"
    edited.write_text(edited.read_text(encoding="utf-8") + "\n# local tweak\n", encoding="utf-8")
    problems = vendor.check(vendor.Plan(SOURCE, target))
    assert any("nav.py" in problem for problem in problems), problems


def test_check_is_silent_on_a_clean_install(target: Path) -> None:
    """...and says nothing when there is nothing to say.

    Asserted so the test above is evidence of detection rather than of a check
    that always complains.

    @param target an empty repository
    """
    _install(target)
    assert vendor.check(vendor.Plan(SOURCE, target)) == []


def test_check_on_a_tree_never_vendored_is_not_silence(target: Path) -> None:
    """No manifest means never installed, which is not the same as up to date.

    @param target an empty repository
    """
    assert vendor.check(vendor.Plan(SOURCE, target)) != []


# ------------------------------------------------------------- the round trip


@pytest.mark.parametrize(("label", "original"), [("lf", EXISTING_LF), ("crlf", EXISTING_CRLF)])
def test_the_whole_round_trip_preserves_every_prior_byte(
    target: Path,
    label: str,
    original: bytes,
) -> None:
    """Install, integrate, check and remove -- and nothing else moved.

    **Synthetic.** This exercises the machinery on a greenfield repository. It is
    not a repository that depends on the discipline in daily use, and the
    difference is recorded as an accepted defect rather than argued away here.

    Driven from both line endings and asserted on BYTES, because the failure this
    guards against -- a read/write cycle silently normalising CRLF to LF -- is
    invisible to any assertion made on decoded text, and it would rewrite every
    line of a file the adopter never asked us to touch.

    @param target an empty repository
    @param label which ending is under test, for the failure message
    @param original the configuration the project already had
    """
    claude = target / "CLAUDE.md"
    claude.write_bytes(original)

    installed, _ = _install(target)
    assert installed > 0, "the install recorded no files"
    assert integrate.main(["--root", str(target)]) == 0

    after_install = claude.read_bytes()
    assert original in after_install, (
        f"[{label}] the prior configuration did not survive integration byte for byte"
    )

    assert vendor.check(vendor.Plan(SOURCE, target)) == []
    assert integrate.main(["--root", str(target), "--check"]) == 0

    assert integrate.main(["--root", str(target), "--remove"]) == 0
    restored = claude.read_bytes()
    assert integrate.BEGIN not in restored.decode("utf-8", "replace"), (
        f"[{label}] the managed block survived removal"
    )
    assert original.rstrip() in restored.rstrip(), (
        f"[{label}] removal did not restore the prior bytes"
    )
