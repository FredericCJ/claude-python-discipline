# A Python engineering discipline was unzipped here

**Release v5.0.0.** The archive placed one directory at the root of this repository:

```
.agent/
  discipline/     the corpus: KERNEL.md first, then law/ fact/ frame/ ops/ meta/
  enforce/        the mechanisms — AST checks, fitness tests, config templates
  tools/          the navigator, the learning CLI, the validator, the integrator
  skills/         one shared Claude Code and Codex skill source
  dev/            native Windows Conda and Linux Docker development legs
  learning/       project-owned; seeded with schema.sql and config.toml only, so this
                  repository's own record starts empty
  overrides/      project-owned, for local waivers
  environment.yml the shared executable toolchain declaration
  .dockerignore   the deliberately restricted Linux image build context
  MANIFEST.json   a content hash of every upstream file, plus the release name
  INTEGRATION.md  the detail behind everything below
```

`.agent/` is hidden, which is why this file is not. It exists to be found and then deleted.

## Construct the development environment

On Windows, the only host prerequisite is Conda on the user `PATH`:

```powershell
.agent\dev\windows.cmd
```

On Linux, including WSL on a Windows 11 host, the only host prerequisite is Docker:

```bash
sh .agent/dev/docker.sh
```

Either command constructs the same exact direct verifier set from
`.agent/environment.yml`, checks Python and every native executable, and runs the canonical
project gate. The Windows launcher creates or repairs the `claude` environment. The Linux
launcher reconciles its digest-pinned image through Docker's build cache, then bind-mounts
this repository and runs as the invoking uid/gid. Append a command such as
`python -m pytest -q` to either launcher for a focused run.

When the checkout is on a Windows-backed WSL path, the no-argument gate uses a disposable
copy on WSL's native Linux filesystem. It preserves exact file bytes, derives Python
executable bits from shebangs, and copies the packaged gate's JSON report back before
discarding the copy. This prevents NTFS mode projection and metadata latency from changing
Linux verifier outcomes. Explicit commands and `shell` mount the real checkout so intended
edits are not discarded.

The first construction needs network access. The image supplies the discipline verifiers,
not undeclared project runtime dependencies. `requirements.txt` remains the exact direct
Python-only manifest for CI systems which intentionally manage their own native tools.

For an **upgrade**, extract the new archive into a scratch directory rather than over the
existing checkout, then use the packaged vendor path:

```bash
python <scratch>/.agent/tools/vendor.py install . --source <scratch>/.agent
python .agent/tools/integrate.py
python .agent/tools/integrate.py --check
```

That replaces only `.agent/discipline/`, `.agent/enforce/`, `.agent/tools/`,
`.agent/skills/`, `.agent/dev/`, and the upstream root files. It preserves project-owned
learning, overrides, the
integration record, host configuration, and locally edited native skills. Overlay
extraction cannot provide that conditional ownership guarantee.

## Announce it

The files are present but nothing announces them: Claude Code and Codex discover the
repository instruction files and their own native skill directories, not a hidden bundle.
One command wires both agents to the same discipline.

```bash
python .agent/tools/integrate.py --dry-run    # preview; writes nothing
python .agent/tools/integrate.py              # apply
python .agent/tools/integrate.py --check      # CI: is the block present and current?
python .agent/tools/integrate.py --remove     # uninstall, restoring the prior config
```

`--dry-run` prints a unified diff of every file it would touch. It is the same code path as
the real run, stopped before the write — a preview, not a second implementation's guess.

If the repository still uses v3, preview and apply its structural declaration migration
first:

```bash
python .agent/tools/migrate_v4.py --root . --unit application
python .agent/tools/migrate_v4.py --root . --unit application --apply
```

Use `--unit component` for one component repository. Preview writes nothing; apply changes
only the contiguous discipline declaration tables and refuses ambiguous role or foreign
dependency ownership. Semantic architecture and conformance content is not guessed.

Then migrate the complete v4 declaration to v5. A repository already on v4 starts here:

```bash
python .agent/tools/migrate_v5.py --root .
python .agent/tools/migrate_v5.py --root . --apply
```

This second migrator selects Doxygen, declares the project-owned documentation model and
Doxyfile, and creates only missing canonical artifacts. It never overwrites an existing
model or Doxyfile and does not manufacture semantic comments, vocabulary, naming grammars,
generated-code ownership, units, states, or collection meanings. Resolve every reported
authoring and scope-review diagnostic from the project's actual contracts before treating
the project gate as release evidence.

Then start a fresh agent session, so the new configuration is loaded.

## What it will and will not do

It writes one delimited block into `CLAUDE.md` and `AGENTS.md`, copies the one vendored
skill to the native Claude Code and Codex discovery paths, merges a narrow set of Claude
Code permissions into `.claude/settings.json`, and adds four derived paths to `.gitignore`.

- **If an instruction file does not exist**, it is created carrying the block and nothing
  else. The rest of your `CLAUDE.md` or `AGENTS.md` is yours to write; the integrator does
  not presume to author it.
- **If a markdown file already exists**, the block is appended to it and **every byte
  already in that file is preserved — trailing blank lines and line endings included** —
  and the block itself is written in whichever line ending the file already uses, so a CRLF
  file does not come back mixed. The property is asserted on bytes, from a pure-LF and a
  pure-CRLF fixture, by
  `.agent/tools/test_integrate.py::test_an_existing_file_keeps_every_byte_it_had`.
- **If `.claude/settings.json` already exists**, the permission entries are merged into it
  and existing entries — allow, deny, everything else — are never removed. The file is
  re-serialized as two-space-indented JSON, so its formatting is normalised even though its
  content is not; its line endings are preserved. The same holds for `.gitignore`, whose
  existing lines are left alone.
- **Running it again changes nothing.** A block from an earlier release is replaced in
  place, never stacked.
- **Both agents get the same skill bytes.**
  `.agent/skills/python-discipline/SKILL.md` is copied to
  `.claude/skills/python-discipline/SKILL.md` and
  `.agents/skills/python-discipline/SKILL.md`; both route back to the one corpus under
  `.agent/discipline/`.
- **A native skill collision is never overwritten.** A different existing file, directory
  or symlink is reported and preserved. The other agent's path and every unrelated safe
  action can still be integrated, but the command and `--check` exit non-zero until the
  conflict is resolved. An unchanged skill created by an earlier integration is updated on
  upgrade; a locally edited one is preserved.
- **`--remove` takes back only what the install record says was added.** Applying writes
  `.agent/integration-record.json`, naming the permission and ignore entries that were
  genuinely absent beforehand, the blank line inserted before each block, and ownership
  plus content digests for the two native skills. Removal takes back exactly those, so a
  markdown file the integrator appended to comes back byte for byte and an entry you already
  had — `Bash(pytest:*)`, say — is left alone. A native skill is deleted only when the
  record says this integration created it and its bytes are unchanged. If the record is
  missing, because the install was made by a build that predates it, removal takes out the
  managed block but no permission, ignore entry or native skill file at all, and prints
  which were left behind and why.
- **It touches nothing else.** If `.claude/settings.json` is not valid JSON it says so and
  leaves the file alone rather than guessing at what you meant.

Write your own text *around* the markers, not inside them: anything between them is
overwritten by the next update.

## Then

**This file has done its job — delete it.** Nothing references it, and re-running the
integrator does not need it.

`RELEASE-NOTES-v5.0.0.md` beside it is worth reading once before you rely on the discipline:
it states what is mechanically enforced and, more usefully, what is not. Delete it too when
you have.

Everything else lives at `.agent/INTEGRATION.md`, which is written for the agent doing the
work. After integrating, the entry point for every session is
`.agent/discipline/KERNEL.md` — about 2,000 tokens, and it routes the rest.
