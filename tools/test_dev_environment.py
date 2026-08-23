"""Executable contracts for the two shipped development legs.

The Docker integration test is a release qualification because it needs a
daemon, registry access, and several minutes on a cold cache. These tests keep
the security- and ownership-bearing structure from drifting during every normal
suite: immutable build inputs, a minimal context, non-root execution, direct
signal delivery, and Conda as the Windows launcher's only package manager.

    pytest tools/test_dev_environment.py
"""

from __future__ import annotations

import re
from pathlib import Path

## The source checkout whose delivered development surfaces are under test.
ROOT = Path(__file__).resolve().parent.parent


def _text(relative: str) -> str:
    """Read one development-environment source as normalized text.

    @param relative source-root-relative file name
    @return the complete UTF-8 text
    """
    return (ROOT / relative).read_text(encoding="utf-8")


def test_every_remote_docker_build_input_is_immutable() -> None:
    """Neither the frontend nor base image may move behind a readable tag."""
    dockerfile = _text("dev/Dockerfile")
    lines = dockerfile.splitlines()
    assert re.fullmatch(
        r"# syntax=docker/dockerfile:1@sha256:[0-9a-f]{64}",
        lines[0],
    )
    from_lines = [line for line in lines if line.startswith("FROM ")]
    assert len(from_lines) == 1
    assert re.fullmatch(
        r"FROM condaforge/miniforge3:[^\s@]+@sha256:[0-9a-f]{64}",
        from_lines[0],
    )


def test_the_docker_context_contains_only_the_three_build_inputs() -> None:
    """Application source and repository metadata never reach the builder."""
    directives = tuple(
        line
        for raw in _text(".dockerignore").splitlines()
        if (line := raw.strip()) and not line.startswith("#")
    )
    assert directives == (
        "**",
        "!environment.yml",
        "!tools/",
        "tools/**",
        "!tools/check_env.py",
        "!dev/",
        "dev/**",
        "!dev/Dockerfile",
        "!dev/container-entrypoint.sh",
    )


def test_the_image_uses_the_declared_node_before_pyright() -> None:
    """Pyright must not provision a hidden runtime on first execution."""
    dockerfile = _text("dev/Dockerfile")
    path = dockerfile.index('PATH="/opt/conda/envs/claude/bin')
    pyright = dockerfile.index("python -m pyright --version")
    assert path < pyright
    assert 'PYRIGHT_PYTHON_GLOBAL_NODE="true"' in dockerfile
    assert 'PYRIGHT_PYTHON_NODEJS_WHEEL="false"' in dockerfile


def test_the_linux_leg_preserves_identity_and_signal_delivery() -> None:
    """The mounted checkout stays developer-owned and the tool becomes PID 1."""
    launcher = _text("dev/docker.sh")
    entrypoint = _text("dev/container-entrypoint.sh")
    assert '--user "$(id -u):$(id -g)"' in launcher
    assert '--volume "${mounted_repository}:/workspace"' in launcher
    assert "--privileged" not in launcher
    assert "safe.directory /workspace" in entrypoint
    assert entrypoint.rstrip().endswith('exec "$@"')


def test_the_wsl_fallback_rejects_a_nonfunctional_docker_stub() -> None:
    """A discoverable Docker command is not accepted until its engine responds."""
    launcher = _text("dev/docker.sh")
    assert "docker version >/dev/null 2>&1" in launcher
    assert "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" in launcher
    assert "wslpath -w" in launcher


def test_every_linux_invocation_reconciles_the_image_inputs() -> None:
    """A pre-existing mutable local tag must not stand in for current build bytes."""
    launcher = _text("dev/docker.sh")
    assert launcher.count("\nbuild_image\n") == 1
    assert "image inspect" not in launcher


def test_the_windows_leg_delegates_environment_ownership_only_to_conda() -> None:
    """No undeclared host package manager enters the native bootstrap path."""
    launcher = _text("dev/windows.ps1")
    assert "Get-Command conda" in launcher
    assert '"env", "update", "--name"' in launcher
    assert "tools\\check_env.py" in launcher
    assert "--prune" in launcher
    assert launcher.count("$savedPreference = $ErrorActionPreference") == 2
    assert launcher.count('$ErrorActionPreference = "Continue"') == 2
    assert launcher.count("$condaExit = $LASTEXITCODE") == 2
    assert "pip install" not in launcher.lower()
    assert "docker" not in launcher.lower()
