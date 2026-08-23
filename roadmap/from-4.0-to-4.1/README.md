# Python Engineering Discipline v4.1 roadmap

## From certified doctrine to a self-contained development environment

| Field | Value |
|---|---|
| Status | In progress |
| Baseline | v4.0.0 at `d4d43841f0cb0f59640183eb8f72441c894116c8` |
| Target | v4.1.0 |
| Governed unit | Exactly one application repository or one component repository |
| Windows host prerequisite | Conda available on the user `PATH` |
| Linux host prerequisite | Docker available to the user |
| Primary host shape | Windows 11 with WSL 2 and Docker Desktop |

## Goal

Ship the development environment as part of the same discipline package used by Claude
Code and Codex. A developer shall not have to discover or install Python, Doxygen, Node,
Pyright's runtime, or the verifier set individually.

The two supported legs are deliberately different:

- Windows uses a checked, automatically created or repaired Conda environment.
- Linux uses a pinned Docker image and bind-mounts the repository into it.

Both execute the same repository-local tools and the same `environment.yml`. Neither leg
changes the v4 governed-unit boundary or adds responsibility for a multi-repository parent.

## Delivered surfaces

### Windows Conda leg

`dev/windows.ps1` and `dev/windows.cmd` shall:

1. find the bundle in either a discipline source checkout or an adopter's `.agent/`;
2. require only a callable `conda` command on the user `PATH`;
3. create the named environment from the shipped lock when absent;
4. check the running environment mechanically and update it from that lock when drifted;
5. run the source gate or adopter project gate from the repository root by default; and
6. admit an explicit environment name and arbitrary in-environment command for diagnosis.

The launcher owns the declared pins, not every package a developer may have added. Its
post-update verifier, rather than Conda's zero exit alone, decides whether the required
toolchain matches.

### Linux Docker leg

`dev/Dockerfile`, `dev/container-entrypoint.sh`, and `dev/docker.sh` shall:

1. pin the Miniforge base by immutable multi-platform digest;
2. construct the exact Conda environment inside the image;
3. verify every declared native and Python tool while building;
4. include Node so Pyright performs no hidden first-run runtime download;
5. bake no governed repository source into the image;
6. bind-mount the source or adopter repository at `/workspace`;
7. run as the invoking Linux uid/gid with writable, disposable home/cache directories;
8. preserve signal delivery through a minimal `exec` entry point; and
9. run the source gate or adopter project gate by default.

The first image build needs registry and package-channel access. After the image exists,
ordinary runs need no additional host package manager. Project-specific dependencies remain
the governed repository's responsibility and shall be declared by that repository; they
are not silently inferred by the discipline image.

## Lock changes

The shared environment shall pin and execute-check:

- Python 3.13.14;
- Doxygen 1.10.0;
- pip 26.2.1;
- Git 2.51.2; and
- Node.js 22.21.1;

plus the existing exact Python verifier set. Version extraction shall accept the real
output grammars of `doxygen --version`, `pip --version`, `git --version`, and
`node --version`, while rejecting absence, non-zero execution, and version drift.

## Package and documentation obligations

- `dev/`, `environment.yml`, and `.dockerignore` become upstream-owned package members.
- The manifest and archive tests require both launchers, the Dockerfile, entry point, and
  shared lock.
- The archive remains one package for Claude Code and Codex; no host-specific doctrine
  fork is introduced.
- README, integration, installation, skill, and release notes expose the two one-command
  paths and state their network, dependency, ownership, and platform residuals.
- v4.1 archive construction remains deterministic and leak-scanned.

## Release acceptance

v4.1.0 may be tagged only after:

- the environment parser and native-version probes have passing and proof-of-failure tests;
- a fresh temporary Windows Conda environment is created from the shipped lock, verified,
  and used to run a packaged command;
- the normal Windows launcher checks or repairs the `claude` environment and invokes a
  discipline-repository command;
- Docker builds from the pinned digest with no repository source baked into its layers;
- the Docker image verifies its lock and runs focused source/package checks from the bind
  mount as a non-root uid;
- an extracted release archive contains and can invoke both development legs;
- focused discipline tests and the actual release command pass; and
- two independently staged v4.1 archives have identical bytes.

No adopter or SIGSIM repository is a v4.1 work target. v4 adopter evidence remains the
frozen v4.0 certificate; v4.1 changes delivery and developer setup, not adopter product
code or multi-component scope.
