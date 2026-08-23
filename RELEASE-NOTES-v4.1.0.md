# Python Engineering Discipline — v4.1.0

**v4.1 ships one development environment for the same combined Claude Code and Codex
discipline package.** The doctrine and governed-unit boundary are unchanged from v4.0: one
repository is either a complete application or one independently developed component.
Multi-repository application topology remains out of scope.

## Start contributing

On Windows, the only host prerequisite is Conda on the user `PATH`:

```powershell
.agent\dev\windows.cmd
```

The launcher creates or repairs the `claude` environment from
`.agent/environment.yml`, independently verifies every declared Python and native tool,
then runs the repository's project gate. Use `-EnvironmentName <name>` for an isolated
environment, `-Refresh` to request a lock reconciliation, or append an arbitrary command:

```powershell
.agent\dev\windows.cmd python -m pytest -q
```

On Linux, including WSL on the usual Windows 11 host, the only host prerequisite is a
working Docker engine:

```bash
sh .agent/dev/docker.sh
```

The launcher reconciles the image through Docker's build cache, bind-mounts the repository
at `/workspace`, and runs the project gate as the invoking uid/gid. It uses a native Linux
Docker CLI when that engine responds and otherwise supports Docker Desktop's Windows CLI
from WSL. Warm the build cache explicitly, open a shell, or run another command with:

```bash
sh .agent/dev/docker.sh build
sh .agent/dev/docker.sh shell
sh .agent/dev/docker.sh python -m pytest -q
```

In a checkout of the discipline itself, use the same commands without the `.agent/`
prefix: `dev\windows.cmd` or `sh dev/docker.sh`. Their default becomes the discipline's
own source gate.

## What is now shipped

- `environment.yml` is the shared executable declaration for both legs.
- `dev/windows.ps1` and `dev/windows.cmd` own native Windows creation, repair,
  verification, and invocation through Conda.
- `dev/Dockerfile`, `dev/docker.sh`, and `dev/container-entrypoint.sh` own the Linux image,
  WSL bridge, bind mount, numeric identity, disposable runtime home, and signal delivery.
- `.dockerignore` permits only the environment declaration, its dependency-free checker,
  the Dockerfile, and the entry point into the build context.

All seven surfaces are upstream-owned manifest members and mandatory archive members. One
archive still installs the same canonical skill bytes into the Claude Code and Codex native
discovery paths.

## Toolchain and supply-chain changes

The shared declaration now pins and execution-checks Python 3.13.14, Doxygen 1.10.0,
pip 26.2.1, Git 2.51.2, and Node.js 22.21.1 in addition to the existing exact direct Python
verifier pins. The checker normalizes each tool's real output grammar, including Git for
Windows' platform suffix.

The Dockerfile pins both its Dockerfile frontend and Miniforge base by immutable digest.
It puts the declared environment first on `PATH` before invoking Pyright and disables the
alternative Node wheel strategy. The image build proves Pyright uses the shipped runtime;
ordinary runs no longer trigger Pyright's hidden nodeenv download.

The image contains no application/component checkout. Repository code arrives only through
the runtime bind mount, which is non-privileged and preserves the invoking Linux identity.
The entry point trusts only `/workspace` for Git ownership and `exec`s the requested tool as
PID 1.

## Qualification evidence

- The source Windows launcher verified and invoked the designated `claude` environment.
- A freshly vendored package created a new, isolated Windows Conda environment from its
  own lock, verified every declared pin, and executed its packaged checker. This exposed
  and closed a Windows PowerShell 5.1 stderr/exit-status defect before release.
- A clean Linux image was constructed from the pinned digests and matched all declared
  executable and Python versions.
- Pyright 1.1.407 executed through the pinned Node 22.21.1 without provisioning nodeenv.
- The unmounted image had an empty `/workspace` and only the shared lock plus checker under
  `/opt/python-discipline`.
- A bind-mounted discipline checkout executed as numeric uid 1000.
- The WSL launcher rejected Docker Desktop's nonfunctional Linux stub, selected the working
  Windows Docker CLI, converted mount paths, and ran the checker successfully.
- A literal extracted candidate archive invoked both packaged legs, and two independently
  staged candidate archives were byte-identical.

The final release operation still runs the complete discipline gate before repeating the
staging and leak scan. Exact pre-release qualification results are recorded in the v4.1
roadmap evidence.

## Residuals

- The first Conda environment creation or Docker image build needs network access to the
  configured Conda and pip channels and, for Docker, the registry. Already constructed legs
  execute without installing another host package manager.
- Exact direct version pins identify distributions, not their artifact hashes; transitive
  Python dependencies are resolved by pip. This remains weaker than a hash-locked wheelhouse.
- The image supplies the discipline verifier toolchain, not undeclared project-specific
  runtime dependencies. A governed repository remains responsible for declaring those.
- Windows uses the named mutable Conda environment and repairs required-pin drift; packages
  outside the declaration are not evidence and may be removed by `--prune`.
- v4.1 changes delivery and setup, not the frozen v4.0 adopter certification. It makes no
  claim about a parent application, sibling compatibility, deployment wiring, or whole-system
  behavior.
