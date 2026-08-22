# Python Engineering Discipline — v3.3.0

**One package now installs the same discipline for Claude Code and Codex.**

The rules, mechanisms, navigation graph and learning model remain one corpus. What changes
is how an adopter reaches them: the release now carries one agent-neutral skill and the
integrator exposes exact copies at both hosts' repository discovery paths. Claude Code and
Codex can therefore work in the same repository without installing separate packages or
maintaining divergent instructions.

```bash
python .agent/tools/integrate.py --dry-run
python .agent/tools/integrate.py
python .agent/tools/integrate.py --check
```

## One authority, two discovery paths

The source checkout authors only `skills/python-discipline/SKILL.md`. A generator keeps the
checkout's `.claude/skills/python-discipline/SKILL.md` and
`.agents/skills/python-discipline/SKILL.md` discovery copies byte-identical and rejects
stale or orphaned mirror files.

The archive does not ship those repository-specific roots. It carries the authority once,
at `.agent/skills/python-discipline/SKILL.md`; `integrate.py` copies that file to the Claude
Code and Codex paths in the consuming repository. Both entry points locate the same
`.agent/discipline/KERNEL.md`, use the same navigator and learning database, and enforce the
same rules.

`vendor.py install` still keeps its original blast boundary: it writes only `.agent/`.
Native instruction and skill files remain an explicit, previewable integration step.

## Ownership is proved before a host file changes

The integration record is now version 2. For each native skill it stores whether this
integration created the file and the digest of the exact bytes written. That gives upgrades
and removal a conservative ownership rule:

| Native path state | Apply or upgrade | Remove |
|---|---|---|
| absent | create it and record ownership | delete it if its digest still matches |
| already byte-identical, but unowned | accept it without claiming ownership | leave it |
| unchanged file created by this integration | update it to the new vendored bytes | delete it |
| locally edited, different, non-regular or a symlink | report it and leave it | leave it |

A collision at one host path does not overwrite that project-owned path and does not prevent
safe changes elsewhere, including installing the other host's entry point. The command and
`--check` return non-zero while the conflict remains, so partial availability cannot be
mistaken for a complete integration.

The same record continues to protect existing `CLAUDE.md`, `AGENTS.md`, permission and
ignore entries. Removal takes back only contributions whose ownership is recorded; when
provenance is missing or the content has changed, it leaves recoverable residue instead of
deleting project state.

## Packaging and maintenance

- `skills/` is now an upstream-owned part of every `.agent/` install and is covered by the
  content-hash manifest.
- The release builder refuses an archive missing the shared skill source.
- The source repository has a root `AGENTS.md` so Codex receives the same maintenance
  contract as Claude Code's `CLAUDE.md`.
- Mirror, vendor, integration and release tests pin byte identity, idempotence, safe
  upgrade, collision handling, conservative removal and the archive member contract.
- The duplicated skill reference corpus formerly maintained under `.claude/` is gone. The
  skill routes to the canonical discipline modules instead.

## Upgrading from v3.2.0

Install v3.3.0 over the existing `.agent/` bundle, then preview and run the integrator
again. The prior integration record is retained because it lives at `.agent/`'s top level,
outside the upstream directories replaced by `vendor.py`.

The first v3.3.0 integration creates or accepts the two native skill files and upgrades the
record to version 2. Later releases can update unchanged files the record says they own.
Pre-existing files with the same bytes remain project-owned; different files are never
silently adopted.

No rule ID, force tag, mechanism assignment or conformance-baseline format changes in this
release. Project-owned `.agent/learning/` and `.agent/overrides/` directories retain their
existing update guarantees.

## By the numbers

| Measure | v3.2.0 | v3.3.0 |
|---|---:|---:|
| packaged skill authorities | 0 | **1** |
| native skill paths managed by integration | 0 | **2** |
| independently authored discipline corpora | 1 | **1** |
| integration record version | 1 | **2** |
| binding / advisory rules | 155 / 28 | **155 / 28** |
| tests | 736 | **746** |

The minor version is deliberate: existing rule and project-owned data contracts remain
compatible. The release adds a second supported agent host and makes the already shared
instruction surface discoverable in the host-native way.

## Known gaps

- A conflicting native skill requires a person to choose a name or reconcile the existing
  file. The integrator reports the exact path but will not make that ownership decision.
- `.claude/settings.json` is a Claude Code permission surface. This release does not edit
  global Codex configuration; Codex receives the repository instructions and skill through
  `AGENTS.md` and `.agents/skills/`.
- The corpus's existing enforcement gaps are unchanged: `V080` reports 14 binding rules
  without a built mechanism, and `V098` reports 93 named mechanisms not yet observed
  rejecting a concrete violation.
- Every verdict still comes from one machine: win32, cp932. `OPEN-009` remains open until a
  CI run provides an independent environment.

Seventeen validation warnings are expected: `V051` once, `V080` fourteen times, `V097`
once and `V098` once. They are measured gaps, not release-gate exceptions.
