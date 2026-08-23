"""Correctness fixtures for the documentation gate and its behaviour oracle.

Oracle: `docgate.py`'s own module docstring plus `discipline/law/DOC.md`
(DOC-001/DOC-003) and `discipline/law/FLOW.md` (FLOW-007 -- every check ships a
proof-of-failure companion). The provenance format is exercised directly
against `docgate`'s public functions rather than through the CLI, so no test
here ever touches the repository's real `tools/doc_baseline.json`.

    pytest tools/test_docgate.py
"""

from __future__ import annotations

import ast
import json
import subprocess
from typing import TYPE_CHECKING

import pytest

import docgate

# Import annotation-only protocols without adding runtime dependencies.
if TYPE_CHECKING:
    from pathlib import Path

## A minimal file with one function, used wherever a test needs something to
## fingerprint. `x = 1` inside gives the function a body distinct from `pass`,
## so a change to it is visible in the fingerprint.
_SAMPLE_SOURCE = '''"""A sample module."""


def greet() -> str:
    """Say hello.

    @return a greeting
    """
    x = 1
    return f"hi {x}"
'''

## The same module with its function body changed -- a real behaviour change,
## as opposed to a docstring edit, which the fingerprint must not ignore.
_SAMPLE_SOURCE_CHANGED = '''"""A sample module."""


def greet() -> str:
    """Say hello.

    @return a greeting
    """
    x = 2
    return f"hi {x}"
'''


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An isolated fake repository with one covered file and its baseline path.

    Points `docgate.BASELINE_PATH` and `docgate.COVERED` at the temporary tree
    so every test in this module is free to write baselines without touching
    the real `tools/doc_baseline.json`.

    @param tmp_path pytest's per-test temporary directory
    @param monkeypatch active for the duration of the test
    @return the fake repository root, containing `tools/sample.py`

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Resolve the repository-confined path used by this operation before filesystem access.
    root = tmp_path
    # Publish the externally visible effect after all required inputs are ready.
    (root / "tools").mkdir()
    # Publish the externally visible effect after all required inputs are ready.
    (root / "tools" / "sample.py").write_text(_SAMPLE_SOURCE, encoding="utf-8")
    monkeypatch.setattr(docgate, "BASELINE_PATH", root / "tools" / "doc_baseline.json")
    monkeypatch.setattr(docgate, "COVERED", ("tools",))
    # Return the fake repository root, containing `tools/sample.py` to the caller.
    return root


def _sample(repo: Path) -> Path:
    """The one covered file inside the fake repository.

    @param repo the fake repository root, from the `repo` fixture
    @return the path to `tools/sample.py`
    """
    # Return the path to `tools/sample.py` to the caller.
    return repo / "tools" / "sample.py"


# --------------------------------------------------------------- provenance


def test_write_baseline_records_ref_per_entry(repo: Path) -> None:
    """A fresh full baseline gives every entry a ref and no reason.

    @param repo the fake repository, from the fixture
    """
    # Preserve the observed item count used by the non-vacuity verdict.
    count = docgate.write_baseline(repo)
    assert count == 1
    # Preserve entries element values in deterministic source order.
    entries = docgate.load_baseline()
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    entry = entries["tools/sample.py"]
    assert entry.fingerprint == docgate.fingerprint(_sample(repo))
    assert entry.ref  # some ref was recorded, sha or the working-tree sentinel
    assert entry.reason is None


def test_rerecord_without_reason_is_refused(repo: Path) -> None:
    """Re-recording a subset with no `reason` is REFUSED, not silently accepted.

    Proof-of-failure for FLOW-007: the exact defect this format exists to
    prevent -- a re-baseline that launders a real behaviour change -- must be
    unreachable through the code path meant to guard against it.

    @param repo the fake repository, from the fixture
    """
    docgate.write_baseline(repo)
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="reason"):
        docgate.rerecord_baseline(repo, [_sample(repo)], "")
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="reason"):
        docgate.rerecord_baseline(repo, [_sample(repo)], "   ")


def test_cli_rerecord_without_reason_exits_nonzero(repo: Path) -> None:
    """The CLI path refuses the same way `argparse` refuses a missing flag.

    @param repo the fake repository, from the fixture
    """
    docgate.write_baseline(repo)
    # Bind excinfo to the current value used by the next test cli rerecord without reason exits
    # Details: nonzero decision.
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(SystemExit) as excinfo:
        docgate.main(["--baseline", "tools/sample.py", "--root", str(repo)])
    assert excinfo.value.code != 0
    # the baseline file itself must be unchanged -- no entry silently rewritten
    entries = docgate.load_baseline()
    assert entries["tools/sample.py"].reason is None


def test_rerecord_with_reason_updates_only_named_entry(repo: Path) -> None:
    """Re-recording one file leaves every other entry byte-identical.

    @param repo the fake repository, from the fixture

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (repo / "tools" / "other.py").write_text(_SAMPLE_SOURCE, encoding="utf-8")
    docgate.write_baseline(repo)
    # Compute before using docgate.load baseline for later test rerecord with reason updates
    # Details: only named entry logic.
    before = docgate.load_baseline()

    # Publish the externally visible effect after all required inputs are ready.
    (repo / "tools" / "sample.py").write_text(_SAMPLE_SOURCE_CHANGED, encoding="utf-8")
    # Preserve the observed item count used by the non-vacuity verdict.
    count = docgate.rerecord_baseline(repo, [_sample(repo)], "changed on purpose")

    assert count == 1
    # Compute after using docgate.load baseline for later test rerecord with reason updates only
    # Details: named entry logic.
    after = docgate.load_baseline()
    assert after["tools/sample.py"].reason == "changed on purpose"
    assert after["tools/sample.py"].fingerprint == docgate.fingerprint(_sample(repo))
    assert after["tools/sample.py"].fingerprint != before["tools/sample.py"].fingerprint
    # untouched entry: identical fingerprint, ref and (absent) reason
    assert after["tools/other.py"] == before["tools/other.py"]


def test_rerecord_requires_existing_baseline(repo: Path) -> None:
    """Re-recording against a repository with no baseline yet is refused.

    @param repo the fake repository, from the fixture
    """
    # Confine the acquired resource to this operation and release it on every exit.
    with pytest.raises(ValueError, match="no baseline"):
        docgate.rerecord_baseline(repo, [_sample(repo)], "a reason")


def test_load_baseline_accepts_pre_provenance_flat_format(repo: Path) -> None:
    """A baseline written before this format still loads.

    A bare fingerprint string plus one top-level `ref` attributes that ref to
    every entry.

    @param repo the fake repository, from the fixture

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Preserve the documentation-stripped behavior fingerprint used for comparison.
    fp = docgate.fingerprint(_sample(repo))
    # Treat old format as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    old_format = {
        "generated_by": "tools/docgate.py",
        "ref": "0123456789abcdef0123456789abcdef01234567",
        "files": {"tools/sample.py": fp},
    }
    # Publish the externally visible effect after all required inputs are ready.
    docgate.BASELINE_PATH.write_text(json.dumps(old_format), encoding="utf-8")

    # Preserve entries element values in deterministic source order.
    entries = docgate.load_baseline()
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    entry = entries["tools/sample.py"]
    assert entry.fingerprint == fp
    assert entry.ref == "0123456789abcdef0123456789abcdef01234567"
    assert entry.reason is None


def test_check_behaviour_reads_new_format(repo: Path) -> None:
    """Gate 1 still detects a real change under the new per-entry shape.

    @param repo the fake repository, from the fixture

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    docgate.write_baseline(repo)
    # Publish the externally visible effect after all required inputs are ready.
    (repo / "tools" / "sample.py").write_text(_SAMPLE_SOURCE_CHANGED, encoding="utf-8")

    # Preserve failed step-name string elements in gate execution order.
    failures = list(docgate.check_behaviour([_sample(repo)], repo))

    assert len(failures) == 1
    assert failures[0].gate == "behaviour"
    assert failures[0].path == "tools/sample.py"


def test_note_survives_a_rerecord(repo: Path) -> None:
    """The top-level note is preserved across a partial re-record.

    @param repo the fake repository, from the fixture

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    docgate.write_baseline(repo)
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    document = json.loads(docgate.BASELINE_PATH.read_text(encoding="utf-8"))
    # Update test note survives a rerecord state only after the required source facts are
    # Details: available.
    document["note"] = "kept across a rerecord"
    # Publish the externally visible effect after all required inputs are ready.
    docgate.BASELINE_PATH.write_text(json.dumps(document), encoding="utf-8")

    docgate.rerecord_baseline(repo, [_sample(repo)], "some reason")

    # Compute after using json.loads for later test note survives a rerecord logic.
    after = json.loads(docgate.BASELINE_PATH.read_text(encoding="utf-8"))
    assert after["note"] == "kept across a rerecord"


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    """Run one git command inside a throwaway repository.

    @param root the repository to run in
    @param arguments the git arguments, without the leading `git`
    @return the finished process, its output captured
    @throws AssertionError when git reports failure, since a broken fixture
        would otherwise be read as the behaviour under test
    """
    # Compute done using subprocess.run for later git logic.
    done = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
        ["git", *arguments],
        capture_output=True, encoding="utf-8", cwd=root, check=False,
    )
    assert done.returncode == 0, f"git {' '.join(arguments)}: {done.stderr}"
    # Return the finished process, its output captured to the caller.
    return done


@pytest.fixture
def git_repo(repo: Path) -> Path:
    """The fake repository, turned into a real git repository with one commit.

    @param repo the fake repository, from the `repo` fixture
    @return the same root, with `tools/sample.py` committed
    """
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    _git(repo, "config", "user.name", "fixture")
    _git(repo, "add", "tools/sample.py")
    _git(repo, "commit", "-q", "-m", "sample")
    # Return the same root, with `tools/sample.py` committed to the caller.
    return repo


def test_a_clean_file_is_attributed_to_the_commit(git_repo: Path) -> None:
    """A file identical to HEAD may honestly claim HEAD's sha.

    @param git_repo the fake repository with one commit, from the fixture
    """
    # Preserve the immutable revision identity used as provenance for this comparison.
    head = _git(git_repo, "rev-parse", "HEAD").stdout.strip()
    docgate.write_baseline(git_repo)

    assert docgate.load_baseline()["tools/sample.py"].ref == head


def test_a_dirty_file_is_never_attributed_to_the_commit(git_repo: Path) -> None:
    """Proof-of-failure: a fingerprint taken from an edited file must not cite HEAD.

    The recorded ref is a checkable claim -- `git show <ref>:<path>`,
    fingerprinted, must equal the entry. Stamping the checked-out sha on a
    fingerprint taken from a modified working tree records a claim that
    replaying it disproves, and a disproved provenance is indistinguishable
    from a laundered one. Neutralise `_ref_for` and this test fails.

    @param git_repo the fake repository with one commit, from the fixture

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Preserve the immutable revision identity used as provenance for this comparison.
    head = _git(git_repo, "rev-parse", "HEAD").stdout.strip()
    docgate.write_baseline(git_repo)
    # Publish the externally visible effect after all required inputs are ready.
    _sample(git_repo).write_text(_SAMPLE_SOURCE_CHANGED, encoding="utf-8")

    docgate.rerecord_baseline(git_repo, [_sample(git_repo)], "changed on purpose")
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    entry = docgate.load_baseline()["tools/sample.py"]

    assert entry.ref == "working-tree"
    assert entry.ref != head
    # and the claim the sentinel replaces is the one that would have been false
    shown = _git(git_repo, "show", f"{head}:tools/sample.py").stdout
    at_head = ast.dump(
        docgate.strip_documentation(ast.parse(shown, filename="tools/sample.py")),
        annotate_fields=False,
    )
    assert entry.fingerprint != at_head


def test_an_untracked_file_is_attributed_to_the_working_tree(git_repo: Path) -> None:
    """A file git has never seen cannot be replayed from any commit.

    @param git_repo the fake repository with one commit, from the fixture

    @par Effects
    Creates, replaces, or removes repository artifacts in implementation order.
    """
    # Publish the externally visible effect after all required inputs are ready.
    (git_repo / "tools" / "fresh.py").write_text(_SAMPLE_SOURCE, encoding="utf-8")

    docgate.write_baseline(git_repo)
    # Preserve entries element values in deterministic source order.
    entries = docgate.load_baseline()

    assert entries["tools/fresh.py"].ref == "working-tree"
    assert entries["tools/sample.py"].ref != "working-tree"


def test_every_recorded_ref_replays_to_its_fingerprint() -> None:
    """The real baseline's provenance is checkable, entry by entry.

    Every entry naming a commit must fingerprint back to exactly what that
    commit holds; an entry that cannot is either a laundered re-record or a
    provenance the tool invented. Entries carrying the `working-tree` sentinel
    are exempt by construction: the sentinel is the admission that there is
    nothing to replay against.
    """
    # Preserve files element values in deterministic source order.
    files = json.loads(docgate.BASELINE_PATH.read_text(encoding="utf-8"))["files"]
    # Compute checked using 0 for later test every recorded ref replays to its fingerprint
    # Details: logic.
    checked = 0
    # Retain the immutable source representation consumed by subsequent analysis.
    # Advance test every recorded ref replays to its fingerprint through the current input
    # Details: element in declared order.
    for name, raw in files.items():
        # Treat the current entry as the candidate element consumed by the enclosing
        # Details: transformation.
        entry = docgate.BaselineEntry.from_json(raw, "working-tree")
        # Select the guarded path only after `entry.ref == 'working-tree'` is satisfied.
        if entry.ref == "working-tree":
            # Advance after the current candidate has been conclusively excluded.
            continue
        # Preserve the completed Git query with its status and captured content.
        shown = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            ["git", "show", f"{entry.ref}:{name}"],
            capture_output=True, encoding="utf-8", cwd=docgate.REPO_ROOT, check=False,
        )
        assert shown.returncode == 0, f"{name}: ref {entry.ref} does not hold it"
        # Compute replayed using ast.dump for later test every recorded ref replays to its
        # Details: fingerprint logic.
        replayed = ast.dump(
            docgate.strip_documentation(ast.parse(shown.stdout, filename=name)),
            annotate_fields=False,
        )
        assert replayed == entry.fingerprint, (
            f"{name}: the fingerprint does not match ref {entry.ref}; either the "
            f"entry was re-recorded from a different tree without saying so, or "
            f"the ref is wrong"
        )
        # Compute checked using 1 for later test every recorded ref replays to its fingerprint
        # Details: logic.
        checked += 1

    # Until v1.1.0 this asserted `checked` -- that at least one entry still named
    # a commit. That held only while most of the baseline was inherited from the
    # migration, and stopped holding the first time a release re-recorded the
    # covered set for a real code change. The durable property is the one below,
    # and it is the stronger of the two: an entry must be accountable EITHER by a
    # replayable ref OR by a written reason. Neither is the signature of a bare
    # `--baseline` with no paths, which drops reasons and refs together -- the
    # laundering path docgate's own docstring names.
    # Each unaccountable element carries one unaccountable value produced or consumed by this
    # Details: operation; construction order is preserved.
    unaccountable = [
        name for name, raw in files.items()
        if docgate.BaselineEntry.from_json(raw, "working-tree").ref == "working-tree"
        and not raw.get("reason")
    ]
    assert unaccountable == [], (
        f"{len(unaccountable)} entry(ies) carry neither a replayable ref nor a "
        f"reason, which is what a full `--baseline` with no paths leaves behind: "
        f"{', '.join(unaccountable[:5])}"
    )


# ------------------------------------------------------------- the migration


def test_migrated_baseline_holds_the_original_fingerprints() -> None:
    """The migrated baseline still carries every pre-migration fingerprint.

    Proven by replaying the same fingerprint derivation against the commit
    its `note` names as the pre-migration baseline and comparing byte-for-byte.

    This is the proof the task's before/after comparison asked for, kept as a
    regression test rather than a one-off script output: if a future edit to
    `tools/doc_baseline.json` ever re-derives a fingerprint instead of
    preserving it, this test is what catches it.
    """
    # Hold the decoded mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    document = json.loads(docgate.BASELINE_PATH.read_text(encoding="utf-8"))
    # Preserve files element values in deterministic source order.
    files = document["files"]
    # The migration recorded 27 entries. The roster grows when the repository
    # gains a covered file and must never shrink, so the count is a floor, and
    # the real property -- every covered file is baselined and no entry was
    # dropped -- is the set equality below. A count alone would pass a baseline
    # that swapped one entry for another.
    migrated_entries = 27
    assert len(files) >= migrated_entries
    assert set(files) == {
        docgate._relative(path, docgate.REPO_ROOT)
        for path in docgate.iter_python(docgate.covered_paths(docgate.REPO_ROOT))
    }

    # Compute pre migration ref using "99314dbb6983e620a9bfb402b4ead27c06d153a9" for later test
    # Details: migrated baseline holds the original fingerprints logic.
    pre_migration_ref = "99314dbb6983e620a9bfb402b4ead27c06d153a9"
    # Every entry not carrying its own re-record reason must still point at the
    # original pre-migration ref -- the "rest inherit the original ref" half of
    # the migration requirement.
    #
    # This set is allowed to be empty and, as of v1.1.0, is: that release changed
    # real code in every covered file (eight C901 decompositions, the ruff
    # autofixes, the type-only import moves), so each entry was deliberately
    # re-recorded with a reason and none still inherits the migration ref. An
    # inherited ref is a claim that a file has not changed since the migration,
    # and asserting one exists would only be asserting that the repository has
    # stopped moving. What must hold is that nothing is re-recorded silently,
    # which is the `reason` check below and in the replay test.
    # Each unreasoned element carries one unreasoned value produced or consumed by this
    # Details: operation; construction order is preserved.
    unreasoned = [name for name, entry in files.items() if "reason" not in entry]
    for name in unreasoned:
        assert files[name]["ref"] == pre_migration_ref

    # The reasoned set grows every time a later session deliberately re-records a
    # subset of the baseline (each call requires --reason, enforced elsewhere in
    # this file); it is a superset of the four files the original migration itself
    # touched, never a fixed roster.
    # Treat reasoned as mapping elements whose keys identify fields and values carry their
    # Details: content; key order is deliberately unused.
    reasoned = {name: entry for name, entry in files.items() if "reason" in entry}
    assert reasoned.keys() >= {
        "enforce/checks/doc_coverage.py",
        "enforce/checks/doc_style.py",
        "enforce/checks/test_doc_checks.py",
        "tools/docgate.py",
    }
    # Treat the current entry as the candidate element consumed by the enclosing transformation.
    # Advance test migrated baseline holds the original fingerprints through the current input
    # Details: element in declared order.
    for entry in reasoned.values():
        # Reject an empty explanation because silent re-recording is the defect under test.
        assert entry["reason"]

    # Replay every unreasoned entry from the common pre-migration revision in path-key order.
    for name in unreasoned:
        # Preserve the completed Git query with its status and captured content.
        shown = subprocess.run(  # ruff: ignore[subprocess-without-shell-equals-true] - fixed argv, no shell
            ["git", "show", f"{pre_migration_ref}:{name}"],
            capture_output=True, encoding="utf-8", cwd=docgate.REPO_ROOT, check=False,
        )
        # Ignore files absent from that revision because they have no historical source to replay.
        if shown.returncode != 0:
            # Advance after classifying the file as added after the provenance revision.
            continue
        # Parse the Python source into the syntax tree used for structural fingerprinting.
        tree = ast.parse(shown.stdout, filename=name)
        # Compute replayed using ast.dump for later test migrated baseline holds the original
        # Details: fingerprints logic.
        replayed = ast.dump(docgate.strip_documentation(tree), annotate_fields=False)
        assert replayed == files[name]["fingerprint"], (
            f"{name}: migrated fingerprint diverges from the pre-migration ref"
        )
