# Integrating this discipline into a repository

**If you are an agent and someone has asked you to integrate the discipline, this is the
file to follow. It is short and the whole procedure is two commands.**

The discipline has been vendored into this repository — it sits under `.agent/`. Vendoring
copies the files; it does **not** announce them. Nothing under `.agent/` is loaded by an
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
<!-- BEGIN AGENT DISCIPLINE <version> -- managed by ... -->
   ... the pointer, the thesis, the three commands that matter ...
<!-- END AGENT DISCIPLINE -->
```

- **The file does not exist yet** — it is created with a title and the block, and nothing
  else. The rest of that file is yours to write; the integrator does not presume to
  author your project's documentation.
- **The file already exists** — the block is appended, and **every byte outside the
  markers is left exactly as it was**. There is a test for that property specifically.
- **A block from an earlier version is already there** — it is replaced in place, not
  stacked. Running the integrator twice changes nothing the second time.

It also merges — never replaces — the narrow set of permissions the discipline's own
tooling needs into `.claude/settings.json`, and adds the derived learning index and the
documentation build output to `.gitignore`. Existing permission entries are never removed.

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

That removes the block, the permission entries it added and the ignore lines it added, and
leaves everything else — including a pre-existing configuration — as it was.

## After integrating

Read `.agent/discipline/KERNEL.md`. It is about 1,800 tokens and it routes everything
else; do not read the modules speculatively. From then on:

```bash
python .agent/tools/nav.py context --file <path> --error "<message>"
python .agent/tools/learn.py retrieve --file <path> --error "<message>"
```

and, before reporting a change done, record what the session learned about this
repository — or that it learned nothing.
