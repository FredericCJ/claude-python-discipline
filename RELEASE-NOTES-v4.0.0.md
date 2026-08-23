# Python Engineering Discipline — v4.0.0

**v4 governs one consequential Python repository as either a complete application or one
independently developed component, and the same package serves Claude Code and Codex.**

This is a breaking doctrine release. It strengthens strict typing and mechanical
verification by narrowing every automated claim to an exact proposition, then requiring a
passing control and a witnessed rejection. It does not govern a multi-repository
application top level, sibling compatibility, deployment wiring, or whole-system behavior.

## One repository, one governed unit

Every adopter declares exactly one of:

- `unit = "application"` — the repository owns the complete delivered application; or
- `unit = "component"` — the repository owns one independently buildable, testable,
  diagnosable component and its local contracts.

A component records contract roles, provenance and versions, never counterpart repository
names or deployment topology. The project gate confines every configured path to the
declared repository and refuses parent or sibling escape.

## What changed mechanically

- One canonical project gate loads the declaration once and reports `pass`, `fail`,
  `not-applicable`, `unsupported`, or `not-run` for every required step. Only `pass` and a
  capability-justified `not-applicable` are green.
- Ruff, strict mypy, strict pyright, import-linter, pytest timeout/random/socket controls,
  documentation generation, Cosmic Ray mutation, isolated wheel/sdist construction, and
  clean installed-artifact probes are configuration-bound and non-vacuous.
- All 179 automated rule/mechanism strategies have witnessed rejections. Rule-only or
  pending discrimination credit and generated proposition boilerplate are invalid.
- Eleven semantic strategies use content-bound structured review. The gate validates the
  artifact's commit, scope, freshness, reviewer role, objections, conclusion and residual;
  it does not claim that artifact presence proves insight.
- The v3 unbuilt-mechanism and unwitnessed-rejection ceilings are both zero.
- The v3-to-v4 migrator is preview-first, repository-confined, idempotent and conservative
  around project-owned configuration.
- Wheel and source-distribution identity, fresh installation, imports and declared public
  entry points are tested without source-tree `PYTHONPATH` substitution.

## Superseded, consolidated and retired rules

Old IDs remain resolvable and are never repurposed.

| v3 ID | v4 disposition | Replacement and adopter action |
|---|---|---|
| `ARCH-004` | superseded | Use `ARCH-020`; declare one foreign-dependency owner per import root instead of transitive per-module bans. |
| `ARCH-007` | superseded | Use `ARCH-024`; record contract representation and terms in the architecture and conformance registries. |
| `ARCH-008` | superseded | Use `ARCH-025`; register real, controllable and scheduled-fault implementation capabilities. |
| `ARCH-010` | superseded | Use `ARCH-021`; record volatile decisions and the change scenarios each boundary absorbs. |
| `TYPE-009` | superseded | Use `ARCH-024`; choose structural or nominal representation per contract rather than forcing every boundary to `Protocol`. |
| `ALLOC-008` | consolidated | Use `TEAMS-002`; retain the old ID only for historical citations. |
| `ARCH-009` | consolidated | Use `TEST-020`; replace suite-name convention with a contract implementation and term-evidence registry. |
| `TEST-005` | consolidated | Use `TEST-020`; physical triad names no longer substitute for capability evidence. |
| `TEST-006` | consolidated | Use `TEST-020`; one registry owns shared-suite and substitute-drift obligations. |
| `FLOW-013` | retired | The lightweight profile is removed. This discipline is only for consequential application or component repositories. |

## New capability declaration

Every key is present as an explicit boolean. Capabilities activate additional local
obligations; they never describe another repository.

| Capability | Activates evidence for |
|---|---|
| `public_api` | published contracts, compatibility and installed public probes |
| `filesystem_io` | path/resource ownership, I/O failure and recovery |
| `persistent_state` | compatibility, reconstruction, corruption and recovery |
| `generated_artifacts` | provenance, deterministic regeneration and drift |
| `network_io` | framing, timeout, backpressure, disconnect and ordering |
| `launches_subprocesses` | launch, handoff and status-delivery behavior |
| `owns_subprocess_lifecycle` | interruption, graceful stop, escalation and orphan refusal |
| `concurrency` | ordering, single-writer policy, cancellation and race evidence |
| `destructive_effects` | plan/apply, preview, interruption and partial-progress reporting |
| `bounded_latency` | finite budgets, measurement and timeout behavior |
| `sensitive_data` | classification, trust boundaries, retention, redaction and sink policy |

Static inference may require a capability to be enabled but never silently disables one;
intentional facts remain explicit declaration decisions.

## Changed defaults and required configuration

| Surface | v4 behavior |
|---|---|
| unit scope | `application` or `component` is mandatory; no implicit multi-repository scope exists. |
| source layout | `source_roots` and every domain/application/ports/adapters/shell role path are explicit and repository-confined. |
| documentation | `doc_engine` is mandatory: `doxygen`, `sphinx`, or deliberate `none`; absence cannot narrow the gate. |
| capabilities | all eleven keys are explicit booleans; omitted keys fail declaration loading. |
| external tools | required tables and non-empty local targets are probed before execution. |
| tests | a finite timeout, thread timeout method, randomization plugin and socket refusal are canonical. |
| mutation | native Windows/Linux Cosmic Ray execution must produce competent mutants and zero survivors. |
| delivery | exact build-backend pins, wheel plus sdist, fresh installation and public probes are required. |
| semantic review | content-bound architecture, contract, operations, security and adversarial artifacts replace presence-only claims. |

## Required adopter actions

1. Install the v4 bundle through `vendor.py`; when starting from an archive upgrade,
   extract it to a scratch directory and run its packaged vendor command instead of
   overlaying project-owned `.agent/learning/` state.
2. Preview `python .agent/tools/migrate_v4.py --root . --unit application|component`,
   review the diff, then repeat with `--apply`. Unit kind is intentionally not inferred.
3. Declare exact source roots, role paths, documentation engine and every capability.
4. Author `architecture.json`, `contract-conformance.json`, `operational-model.json` and
   `security-model.json` from the shipped templates. Do not invent parent or sibling facts.
5. Configure strict Ruff/mypy/pyright, import-linter, controlled pytest, documentation,
   mutation, exact PEP 517 build requirements and installed-artifact probes.
6. Install `.agent/requirements.txt`. Doxygen projects additionally install native
   Doxygen 1.10.0; Sphinx 8.2.3 is in the Python manifest and preserves Python 3.11 support.
7. Replace adopter-owned discipline wrappers with
   `python .agent/tools/project_gate.py --root . --json <report>`.
8. Generate the adversarial-review scope only after implementation stabilizes, close or
   explicitly accept every finding, and bind the accepted artifact to the repository.
9. Re-run `integrate.py` so `CLAUDE.md`, `AGENTS.md`, and both host-native skills record the
   v4 manifest; `--check` must then be clean.

## One package for Claude Code and Codex

The archive authors one skill at `.agent/skills/python-discipline/SKILL.md`. Integration
copies those exact bytes to `.claude/skills/python-discipline/SKILL.md` and
`.agents/skills/python-discipline/SKILL.md`. Archive-level tests build twice for byte
identity and exercise fresh install, collision, upgrade, check and conservative removal
through the extracted public CLIs.

An unowned or locally edited native skill is preserved and reported. A conflict for one
host does not authorize overwriting it and does not prevent the other host's safe install.

## Known residuals

- Structured review cannot authenticate reviewer identity or prove intellectual
  independence; the artifact records the claimed separation and residual.
- Version pins establish distribution identity, not wheel-content hashes. Release archive
  reproducibility is byte-exact; Python dependency resolution is exact-version only.
- Pyright may provision its Node runtime on first use. That external action must be
  available before an offline gate is expected to pass.
- Doxygen is a native dependency and is verified by executing it, not by Python package
  metadata.
- v4 certifies each component independently. It makes no claim about composition,
  counterpart compatibility or whole-application behavior.

The release is complete only with named Windows and independent Linux gate evidence plus
independent passing commits for the complete-application adopter and all four component
adopters. Those identities are recorded during final release certification.
