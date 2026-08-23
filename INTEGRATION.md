# Integrating this discipline into a repository

**If you are an agent and someone has asked you to integrate the discipline, this is the
file to follow. It is short and the whole procedure is two commands.**

The discipline has been vendored into this repository — it sits under `.agent/`, whether it
was put there by `vendor.py install` or by unzipping a release archive at the repository
root; the layout is the same either way. Vendoring copies the files; it does **not**
announce them. Nothing under `.agent/` is a native project entry point on its own: Claude
Code and Codex discover the repository instruction files and their own skill directories.
Integration puts the shared pointer into `CLAUDE.md` and `AGENTS.md` and exposes the same
vendored skill through both native discovery paths. The resulting repository can be used by
Claude Code, Codex, or both without installing two disciplines.

One integrated bundle governs this repository only. The repository declares either a
complete application or one independently developed component; a component's parent,
sibling repositories, wiring and whole-application verification remain out of scope. See
`.agent/discipline/meta/SCOPE.md` after installation.

## The procedure

The package ships the interpreter and verifier environment used by these commands. On
Windows, with only Conda on `PATH`, prefix a command with `.agent\dev\windows.cmd`. On
Linux or WSL, with only Docker available, prefix it with `sh .agent/dev/docker.sh`. For
example:

```powershell
.agent\dev\windows.cmd python .agent\tools\integrate.py --dry-run
```

```bash
sh .agent/dev/docker.sh python .agent/tools/integrate.py --dry-run
```

If an already verified Python environment is active, the direct standard-library command
remains valid:

```bash
python .agent/tools/integrate.py --dry-run    # read the plan first
python .agent/tools/integrate.py              # apply it
```

Then start a fresh session, so the new configuration is loaded.

`--dry-run` prints exactly what will change, with a diff, and writes nothing. It is the
same code path as the real run truncated before the write, so what it shows is what
happens — not a prediction made by a second implementation.

## What it does, and what it will not do

It manages one clearly delimited block in each of `CLAUDE.md` and `AGENTS.md`:

```
<!-- BEGIN AGENT DISCIPLINE v5.0.0 (manifest content hash) -- managed by ... -->
   ... the pointer, the thesis, the three commands that matter ...
<!-- END AGENT DISCIPLINE -->
```

The marker names two things. `v5.0.0` is the release, so a reader can tell at a glance
what is installed. The value in brackets is the content hash from
`.agent/MANIFEST.json`, computed over every upstream file: it is what `--check` compares,
and unlike a release name it cannot be claimed, only computed. If you edited a vendored
file in place, the hash moves and `vendor.py check` says which file.

- **The file does not exist yet** — it is created with a title and the block, and nothing
  else. The rest of that file is yours to write; the integrator does not presume to
  author your project's documentation.
- **The file already exists** — the block is appended, and **every byte already in the
  file is preserved, trailing blank lines and line endings included**. The block itself is
  written in whichever line ending the file already uses, so a CRLF file does not come back
  mixed. That is asserted on bytes, from a pure-LF and a pure-CRLF fixture, by
  `tools/test_integrate.py::test_an_existing_file_keeps_every_byte_it_had` — the property is
  invisible to any assertion made on decoded text, since reading through universal newlines
  and writing back through the platform separator normalises both sides.
- **A block from an earlier version is already there** — it is replaced in place, not
  stacked. Running the integrator twice changes nothing the second time.

The bundle contains one authoritative agent skill at
`.agent/skills/python-discipline/SKILL.md`. The integrator copies it byte for byte to
`.claude/skills/python-discipline/SKILL.md` for Claude Code and
`.agents/skills/python-discipline/SKILL.md` for Codex. Both entry points route back into
`.agent/discipline/`; neither contains a second rules corpus.

- **The native path is absent** — the skill file is created and recorded as owned by this
  integration.
- **The native file already has exactly the same bytes** — it is accepted without claiming
  that the integration created it.
- **A different file, directory or symlink already occupies the native path** — that path
  is reported as a conflict and left untouched. Other safe actions can still be applied,
  including the other agent's skill, but the command and `--check` exit non-zero until the
  conflict is resolved.
- **The vendored discipline is upgraded** — a native skill that the prior integration
  created and that has not been edited is updated. A local edit is reported and preserved.

It also merges — never replaces — the narrow set of Claude Code permissions the
discipline's own tooling needs into `.claude/settings.json`, creating that file only if it
is absent, and adds four derived paths to `.gitignore`: the three files of the learning
database (`.agent/learning/learning.db` and its two SQLite sidecars, derived from
`.agent/learning/ledger.jsonl`, which is the durable record) and `build/doc/`, the
documentation build output. Existing permission entries are never removed.

Applying also writes `.agent/integration-record.json`, which names the permission and
ignore entries that were genuinely absent beforehand and the blank line inserted before
each managed block. It also records whether each native skill was created by the integrator
and the digest of the bytes written. That file is what makes upgrades and `--remove` safe,
and it is deliberately at the top of `.agent/` rather than under `.agent/tools/`:
`vendor.py install` replaces the upstream directories wholesale, so a record kept inside
one would not survive an upgrade.

It will not touch anything else. If `.claude/settings.json` is not valid JSON it says so
and leaves the file alone rather than guessing at what you meant.

## The two situations

**A new repository.** Ask for the whole top-level configuration and run the integrator as
part of it. The integrator supplies the discipline's section; you supply the project's —
what it is, how to run it, what to be careful with. Write yours around the managed block,
not inside it: anything inside the markers is overwritten on the next update. The same run
creates both native skill entry points, so either agent can begin from a fresh session.

**A repository that already has a configuration.** Run the integrator. Read the dry run,
confirm the diff only adds the block, apply. Nothing else in the file changes. If the
existing configuration already says something about `.agent/`, remove that by hand
afterwards — the integrator will not delete text it did not write, so a hand-written
mention will simply sit alongside the managed block.

## Keeping it in step

```bash
python .agent/tools/integrate.py --check      # non-zero if missing or stale
```

Worth putting in the repository's own gate. After updating the vendored discipline with
`vendor.py install`, the recorded version changes and `--check` will report the block as
stale until the integrator is run again. Applying then updates both native skill files if
they are still the unchanged files recorded by the prior integration.

When the update arrives as a release archive, extract it into a scratch directory and run
its installer against this checkout; do not overlay-extract it onto an existing `.agent/`:

```bash
python <scratch>/.agent/tools/vendor.py install . --source <scratch>/.agent
python .agent/tools/integrate.py
python .agent/tools/integrate.py --check
```

The source and destination are distinct so `vendor.py` can replace upstream-owned trees
while leaving `.agent/learning/`, `.agent/overrides/`, and `integration-record.json`
untouched. The archive lifecycle test exercises this exact public command path.

To take it back out cleanly:

```bash
python .agent/tools/integrate.py --remove
```

That takes back exactly what the install record says was put in: the managed block, the
blank line inserted before it, the permission entries that were absent beforehand, and the
ignore lines that were absent beforehand together with the header introducing them. It also
deletes each native skill only when the record says the integrator created it and its digest
still matches. A pre-existing skill or one edited after installation stays in place. A
markdown file the integrator appended its block to comes back byte for byte, whatever its
trailing whitespace and whatever its line endings.

Everything else is left alone, and that includes entries the project already had. An entry
you already allowed — `Bash(pytest:*)`, say — is the same string as one the integrator
would have added, so nothing about the entry itself distinguishes them; only the record
does. Removal therefore consults the record and not the values.

If there is no record — the install was made by a build that predates it, or the file was
deleted — removal takes out the managed block, whose markers say who owns it, but **no
permission, ignore entry or native skill file at all**. It prints which entries it left
behind and why. Leftover configuration is recoverable by hand; deleted configuration is
not.

A file the integrator *created* is not deleted by `--remove`; it is left holding whatever
is outside the markers, which for a greenfield repository is its title line. Delete it by
hand if you want it gone. `.agent/integration-record.json` is left in place too, emptied,
so that removing twice is a no-op.

## Migrating a v3 or v4 declaration

Installation and declaration migration are separate reviews. A v3 repository first
previews and applies the bounded v3-to-v4 project-file edit with:

```bash
python .agent/tools/migrate_v4.py --root . --unit application
python .agent/tools/migrate_v4.py --root . --unit application --apply
```

Select `component` only when this checkout is one independently testable component. The
migrator preserves configuration outside `[tool.agent-discipline]`, converts legacy role
aliases and unambiguous `ARCH-004` ownership, refuses paths outside this checkout, and is
idempotent. It cannot decide the unit kind, the meaning of a boundary, or the contents of
`architecture.json`, `contract-conformance.json`, `operational-model.json`,
`security-model.json`, and `adversarial-review.json`; those remain explicit authoring work
rather than inferred prose. Start the first four from the shipped templates, then run
`python -m checks.capabilities` before filling the operational and security models so
their records exactly match the true manifest facts. Author the adversarial review last:
its file count and digest cover every governed repository-owned file, and any subsequent
content change invalidates that acceptance until the review is repeated.
UTF-8 CRLF and LF checkout projections deliberately share one digest so the accepted
content remains portable across Windows and Linux; binary assets remain byte-exact.

A complete v4 declaration then previews and applies the v5 documentation migration. A
repository already on v4 starts with these commands:

```bash
python .agent/tools/migrate_v5.py --root .
python .agent/tools/migrate_v5.py --root . --apply
```

The migrator selects Doxygen, adds the project-owned documentation-model and Doxyfile
declarations, and creates only canonical artifacts that are absent. It does not overwrite
existing artifacts or infer semantic comments, abbreviations, identifier grammars,
generated-code ownership, units, states, or collection meanings. Treat every
`MIGRATE-V5-003_AUTHORING_REQUIRED`, `MIGRATE-V5-004_SCOPE_REVIEW`, and
`MIGRATE-V5-005_DOXYFILE_REVIEW` diagnostic as work to resolve from project truth. Unsafe
paths and incomplete v4 declarations block all writes, and apply refuses a declaration
that changed after preview.

The v5 project gate requires `doc_engine = "doxygen"` and executes four complementary
source checks: structured entity coverage, semantic-step narration, the project naming
model, and mechanically inferable semantic properties. It also runs Doxygen and inspects
the generated site for non-vacuous entities and relationships. Syntax and declared policy
are mechanical verdicts; the content-bound adversarial review remains the verdict on
whether comments actually match the implementation.

## After integrating

Use `.agent\dev\windows.cmd` or `sh .agent/dev/docker.sh` with no appended command to run
the canonical project gate. The Windows leg reconciles the shared lock before execution;
the Linux leg mounts this repository into its image as the invoking uid/gid. Neither leg
governs a parent or sibling repository.

Read `.agent/discipline/KERNEL.md`. It is about 2,000 tokens and it routes everything
else; do not read the modules speculatively. From then on:

```bash
python .agent/tools/nav.py context --file <path> --error "<message>"
python .agent/tools/learn.py retrieve --file <path> --error "<message>"
```

and, before reporting a change done, record what the session learned about this
repository — or that it learned nothing.
