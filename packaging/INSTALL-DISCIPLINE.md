# A Python engineering discipline was unzipped here

**Release v1.0.0.** The archive placed one directory at the root of this repository:

```
.agent/
  discipline/     the corpus: KERNEL.md first, then law/ fact/ frame/ ops/ meta/
  enforce/        the mechanisms — AST checks, fitness tests, config templates
  tools/          the navigator, the learning CLI, the validator, the integrator
  learning/       project-owned; seeded with schema.sql and config.toml only, so this
                  repository's own record starts empty
  overrides/      project-owned, for local waivers
  MANIFEST.json   a content hash of every upstream file, plus the release name
  INTEGRATION.md  the detail behind everything below
```

`.agent/` is hidden, which is why this file is not. It exists to be found and then deleted.

## Announce it

The files are present but nothing loads them: an agent session reads `CLAUDE.md`,
`AGENTS.md` and `.claude/settings.json`, not a hidden directory. One command fixes that.

```bash
python .agent/tools/integrate.py --dry-run    # preview; writes nothing
python .agent/tools/integrate.py              # apply
python .agent/tools/integrate.py --check      # CI: is the block present and current?
python .agent/tools/integrate.py --remove     # uninstall, restoring the prior config
```

`--dry-run` prints a unified diff of every file it would touch. It is the same code path as
the real run, stopped before the write — a preview, not a second implementation's guess.

Then start a fresh agent session, so the new configuration is loaded.

## What it will and will not do

It writes one delimited block into `CLAUDE.md` and `AGENTS.md`, merges a narrow set of
permissions into `.claude/settings.json`, and adds four derived paths to `.gitignore`.

- **If those files do not exist**, each is created carrying the block and nothing else. The
  rest of your `CLAUDE.md` is yours to write; the integrator does not presume to author it.
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
- **`--remove` takes back only what the install record says was added.** Applying writes
  `.agent/integration-record.json`, naming the permission and ignore entries that were
  genuinely absent beforehand and the blank line inserted before each block. Removal takes
  back exactly those, so a markdown file the integrator appended to comes back byte for
  byte and an entry you already had — `Bash(pytest:*)`, say — is left alone. It has to work
  this way: an entry you already had is the same string as one the integrator would have
  added, so value alone cannot tell them apart. If the record is missing, because the
  install was made by a build that predates it, removal takes out the managed block but no
  permission or ignore entry at all, and prints which were left behind and why.
- **It touches nothing else.** If `.claude/settings.json` is not valid JSON it says so and
  leaves the file alone rather than guessing at what you meant.

Write your own text *around* the markers, not inside them: anything between them is
overwritten by the next update.

## Then

**This file has done its job — delete it.** Nothing references it, and re-running the
integrator does not need it.

`RELEASE-NOTES-v1.0.0.md` beside it is worth reading once before you rely on the discipline:
it states what is mechanically enforced and, more usefully, what is not. Delete it too when
you have.

Everything else lives at `.agent/INTEGRATION.md`, which is written for the agent doing the
work. After integrating, the entry point for every session is
`.agent/discipline/KERNEL.md` — about 1,800 tokens, and it routes the rest.
