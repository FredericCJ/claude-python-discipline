"""Proof-of-failure tests for the additive capability manifest."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from checks import project
from checks.capabilities import CapabilitiesCheck
from checks.test_architecture_checks import architecture_payload
from checks.test_project import declare, v4

if TYPE_CHECKING:
    from pathlib import Path


def _tree(
    tmp_path: Path,
    *,
    enabled: tuple[project.Capability, ...] = (),
    source: str = "",
    filename: str = "module.py",
    published: bool = False,
) -> tuple[CapabilitiesCheck, Path]:
    """Create one locally declared capability fixture.

    @param tmp_path fixture repository
    @param enabled capability facts set true
    @param source production module body
    @param filename production module basename
    @param published whether architecture carries a published contract
    @return configured check and source root
    """
    body = v4()
    for capability in enabled:
        body = body.replace(
            f"{capability.value} = false",
            f"{capability.value} = true",
        )
    declaration_path = declare(tmp_path, body)
    source_root = tmp_path / "src/pkg"
    source_root.mkdir(parents=True)
    (source_root / filename).write_text(source or "VALUE = 1\n", encoding="utf-8")
    architecture = architecture_payload()
    contracts = architecture["contracts"]
    assert isinstance(contracts, list)
    contract = contracts[0]
    assert isinstance(contract, dict)
    contract["direction"] = "published" if published else "internal"
    (tmp_path / "architecture.json").write_text(
        json.dumps(architecture), encoding="utf-8",
    )
    check = CapabilitiesCheck()
    check.declaration = project.parse(declaration_path)
    return check, source_root


def _diagnostics(check: CapabilitiesCheck, source: Path) -> set[str | None]:
    """Collect stable diagnostics from one fixture.

    @param check configured capability check
    @param source production source root
    @return emitted diagnostic ids
    """
    return {finding.diagnostic_id for finding in check.run([source])}


def test_declared_capability_may_exceed_static_inference(tmp_path: Path) -> None:
    """Intent may activate obligations that syntax cannot observe.

    @param tmp_path fixture repository
    """
    check, source = _tree(
        tmp_path,
        enabled=(project.Capability.SENSITIVE_DATA,),
    )
    assert check.run([source]) == []


def test_published_contract_requires_public_api(tmp_path: Path) -> None:
    """The local contract model is an inference input.

    @param tmp_path fixture repository
    """
    check, source = _tree(tmp_path, published=True)
    assert "CAP002_UNDERDECLARED" in _diagnostics(check, source)


@pytest.mark.parametrize(
    ("source", "capability"),
    [
        ("import pathlib\n", project.Capability.FILESYSTEM_IO),
        ("import sqlite3\n", project.Capability.PERSISTENT_STATE),
        ("import socket\n", project.Capability.NETWORK_IO),
        ("import subprocess\n", project.Capability.LAUNCHES_SUBPROCESSES),
        ("import threading\n", project.Capability.CONCURRENCY),
        ("def erase(path):\n    path.unlink()\n", project.Capability.DESTRUCTIVE_EFFECTS),
        (
            "def bounded(process):\n    process.wait(timeout=1)\n",
            project.Capability.BOUNDED_LATENCY,
        ),
        (
            "import os\nTOKEN = os.getenv('SERVICE_API_KEY')\n",
            project.Capability.SENSITIVE_DATA,
        ),
    ],
)
def test_source_witness_cannot_be_declared_false(
    tmp_path: Path,
    source: str,
    capability: project.Capability,
) -> None:
    """Each narrow inference family turns its matching obligation on.

    @param tmp_path fixture repository
    @param source production source carrying one observation
    @param capability fact that observation implies
    """
    check, root = _tree(tmp_path, source=source)
    findings = check.run([root])
    assert any(
        finding.diagnostic_id == "CAP002_UNDERDECLARED"
        and capability.value in finding.message
        for finding in findings
    )


def test_generator_module_requires_generated_artifacts(tmp_path: Path) -> None:
    """A production build module cannot hide the derived-artifact obligation.

    @param tmp_path fixture repository
    """
    check, source = _tree(tmp_path, filename="build_schema.py")
    assert "CAP002_UNDERDECLARED" in _diagnostics(check, source)


def test_lifecycle_ownership_requires_launch_authority(tmp_path: Path) -> None:
    """A repository cannot own subprocesses it says it never creates.

    @param tmp_path fixture repository
    """
    check, source = _tree(
        tmp_path,
        enabled=(project.Capability.OWNS_SUBPROCESS_LIFECYCLE,),
    )
    assert "CAP001_MANIFEST_RELATION" in _diagnostics(check, source)


def test_test_modules_do_not_activate_production_capabilities(tmp_path: Path) -> None:
    """Harness technology is not attributed to the delivered unit.

    @param tmp_path fixture repository
    """
    check, source = _tree(
        tmp_path,
        source="import socket\n",
        filename="test_harness.py",
    )
    assert check.run([source]) == []
