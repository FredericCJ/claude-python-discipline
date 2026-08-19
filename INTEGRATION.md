# Integrating this discipline into a repository

**If you are an agent and someone has asked you to integrate the discipline, this is the
file to follow. It is short and the whole procedure is two commands.**

The discipline has been vendored into this repository — it sits under `.agent/`, whether it
was put there by `vendor.py install` or by unzipping a release archive at the repository
root; the layout is the same either way. Vendoring copies the files; it does **not**
announce them. Nothing under `.agent/` is loaded by an
agent session on its own, because what a session reads first is `CLAUDE.md`, `AGENTS.md`
and the permission settings. Integration is the step that puts a pointer there.

## The procedure

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
<!-- BEGIN AGENT DISCIPLINE v1.0.0 (3f9c1a20b7d4) -- managed by ... -->
   ... the pointer, the thesis, the three commands that matter ...
<!-- END AGENT DISCIPLINE -->
```

The marker names two things. `v1.0.0` is the release, so a reader can tell at a glance
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

It also merges — never replaces — the narrow set of permissions the discipline's own
tooling needs into `.claude/settings.json`, creating that file only if it is absent, and
adds four derived paths to `.gitignore`: the three files of the learning database
(`.agent/learning/learning.db` and its two SQLite sidecars, derived from
`.agent/learning/ledger.jsonl`, which is the durable record) and `build/doc/`, the
documentation build output. Existing permission entries are never removed.

Applying also writes `.agent/integration-record.json`, which names the permission and
ignore entries that were genuinely absent beforehand and the blank line inserted before
each managed block. That file is what makes `--remove` safe, and it is deliberately at the
top of `.agent/` rather than under `.agent/tools/`: `vendor.py install` replaces the
upstream directories wholesale, so a record kept inside one would not survive an upgrade.

It will not touch anything else. If `.claude/settings.json` is not valid JSON it says so
and leaves the file alone rather than guessing at what you meant.

## The two situations

**A new repository.** Ask for the whole top-level configuration and run the integrator as
part of it. The integrator supplies the discipline's section; you supply the project's —
what it is, how to run it, what to be careful with. Write yours around the managed block,
not inside it: anything inside the markers is overwritten on the next update.

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
stale until the integrator is run again.

To take it back out cleanly:

```bash
python .agent/tools/integrate.py --remove
```

That takes back exactly what the install record says was put in: the managed block, the
blank line inserted before it, the permission entries that were absent beforehand, and the
ignore lines that were absent beforehand together with the header introducing them. A
markdown file the integrator appended its block to comes back byte for byte, whatever its
trailing whitespace and whatever its line endings.

Everything else is left alone, and that includes entries the project already had. An entry
you already allowed — `Bash(pytest:*)`, say — is the same string as one the integrator
would have added, so nothing about the entry itself distinguishes them; only the record
does. Removal therefore consults the record and not the values.

If there is no record — the install was made by a build that predates it, or the file was
deleted — removal takes out the managed block, whose markers say who owns it, but **no
permission or ignore entry at all**. It prints which entries it left behind and why.
Leftover configuration is recoverable by hand; deleted configuration is not.

A file the integrator *created* is not deleted by `--remove`; it is left holding whatever
is outside the markers, which for a greenfield repository is its title line. Delete it by
hand if you want it gone. `.agent/integration-record.json` is left in place too, emptied,
so that removing twice is a no-op.

## After integrating

Read `.agent/discipline/KERNEL.md`. It is about 1,800 tokens and it routes everything
else; do not read the modules speculatively. From then on:

```bash
python .agent/tools/nav.py context --file <path> --error "<message>"
python .agent/tools/learn.py retrieve --file <path> --error "<message>"
```

and, before reporting a change done, record what the session learned about this
repository — or that it learned nothing.
