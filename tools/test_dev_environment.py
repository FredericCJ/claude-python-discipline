"""Executable contracts for the two shipped development legs.

The Docker integration test is a release qualification because it needs a
daemon, registry access, and several minutes on a cold cache. These tests keep
the security- and ownership-bearing structure from drifting during every normal
suite: immutable build inputs, a minimal context, non-root execution, direct
signal delivery, a native-mode WSL gate projection, and Conda as the Windows
launcher's only package manager.

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
    # Read shipped launcher bytes through the repository anchor, never the process directory.
    return (ROOT / relative).read_text(encoding="utf-8")


def test_every_remote_docker_build_input_is_immutable() -> None:
    """Neither the frontend nor base image may move behind a readable tag."""
    # Dockerfile text is the release surface whose remote identities must be digest-pinned.
    dockerfile = _text("dev/Dockerfile")
    # Split Dockerfile directives in authored order before validating pinned base images.
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
    # Extract Docker build-context directives from the shipped ignore file.
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
    # Compare lexical build positions to prove the declared Node runtime precedes Pyright.
    dockerfile = _text("dev/Dockerfile")
    path = dockerfile.index('PATH="/opt/conda/envs/claude/bin')
    pyright = dockerfile.index("python -m pyright --version")
    assert path < pyright
    assert 'PYRIGHT_PYTHON_GLOBAL_NODE="true"' in dockerfile
    assert 'PYRIGHT_PYTHON_NODEJS_WHEEL="false"' in dockerfile


def test_the_image_never_cleans_the_mounted_conda_package_cache() -> None:
    """A reusable package cache must retain every manifest-owned file."""
    # Dockerfile text must distinguish the reusable package cache from disposable env files.
    dockerfile = _text("dev/Dockerfile")
    assert "id=python-discipline-conda-v5,target=/opt/conda/pkgs" in dockerfile
    assert "find /opt/conda/envs/claude" in dockerfile
    assert "find /opt/conda -type d -name __pycache__" not in dockerfile


def test_the_linux_leg_preserves_identity_and_signal_delivery() -> None:
    """The runtime workspace stays developer-owned and the tool becomes PID 1."""
    # The launcher owns host identity discovery while the entrypoint owns privilege drop.
    launcher = _text("dev/docker.sh")
    entrypoint = _text("dev/container-entrypoint.sh")
    assert "runtime_uid=$(id -u)" in launcher
    assert "runtime_gid=$(id -g)" in launcher
    assert '--user "$runtime_uid:$runtime_gid"' in launcher
    assert '--volume "${mounted_repository}:/workspace"' in launcher
    assert "--privileged" not in launcher
    assert "safe.directory /workspace" in entrypoint
    assert entrypoint.rstrip().endswith('exec "$@"')


def test_a_windows_backed_default_gate_uses_a_docker_volume_projection() -> None:
    """WSL gate evidence is not distorted by NTFS modes or metadata latency."""
    # Read the launcher contract whose default-gate projection is under test.
    launcher = _text("dev/docker.sh")

    assert "/mnt/[A-Za-z]/*:true)" in launcher
    assert "volume create \\" in launcher
    assert '--label "python-discipline.workspace-token=$workspace_token"' in launcher
    assert 'cp --archive "$copy_source"' in launcher
    assert '-type f -name "*.py" -exec chmod 0644' in launcher
    assert '"#!"*) chmod 0755 "$python_file"' in launcher
    assert 'chown -R "$1:$2" /workspace' in launcher
    assert "mounted_repository=$workspace_volume" in launcher
    assert "container_is_owned" in launcher
    assert "volume_is_owned" in launcher
    assert "trap cleanup_workspace EXIT HUP INT TERM" in launcher
    assert '"${report_container}:/workspace/build/project-gate-docker.json"' in launcher


def test_the_wsl_fallback_rejects_a_nonfunctional_docker_stub() -> None:
    """A discoverable Docker command is not accepted until its engine responds."""
    # Launcher text must pair WSL executable discovery with an engine-health probe.
    launcher = _text("dev/docker.sh")
    assert "docker version >/dev/null 2>&1" in launcher
    assert "/mnt/c/Program Files/Docker/Docker/resources/bin/docker.exe" in launcher
    assert "wslpath -w" in launcher


def test_every_linux_invocation_reconciles_the_image_inputs() -> None:
    """A pre-existing mutable local tag must not stand in for current build bytes."""
    # The launch path must rebuild from current inputs instead of trusting tag presence.
    launcher = _text("dev/docker.sh")
    assert launcher.count("\nbuild_image\n") == 1
    assert "image inspect" not in launcher


def test_the_windows_leg_delegates_environment_ownership_only_to_conda() -> None:
    """No undeclared host package manager enters the native bootstrap path."""
    # Windows launcher text is inspected as the complete host bootstrap contract.
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


def test_the_windows_leg_reserves_only_leading_launcher_options() -> None:
    """Dashed Python arguments must pass through without PowerShell binding."""
    # Raw argument handling must reserve launcher flags without parsing child options.
    launcher = _text("dev/windows.ps1")
    assert "[CmdletBinding" not in launcher
    assert "$rawArguments = @($args)" in launcher
    assert '$argument -ieq "-EnvironmentName"' in launcher
    assert '$argument -ieq "-Refresh"' in launcher
    assert '$argument -eq "--"' in launcher
    assert "$Command = @($rawArguments[" in launcher
