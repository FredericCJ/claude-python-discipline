# Python Engineering Discipline — v5.0.0

**v5 makes evident Python source a governed architectural property.** It is a breaking
release: Doxygen is now the sole structured documentation engine, every governed repository
declares a strict project-owned documentation model, and local bindings and execution steps
must have semantic narration in addition to entity contracts.

The package boundary is unchanged. One installation governs one repository containing
either a complete application or one independently developed component. Parent application
topology, sibling repositories, deployment wiring, and whole-system verification remain out
of scope.

## Upgrade from v4

Install the new bundle into the repository, refresh the shared Claude Code and Codex
integration, then preview the bounded migration:

```bash
python .agent/tools/migrate_v5.py --root .
python .agent/tools/migrate_v5.py --root . --apply
```

The migrator converts a complete v4 declaration to Doxygen, declares
`documentation-model.json` and a local `Doxyfile`, and creates only missing canonical
artifacts. Existing artifacts are never overwritten. Unsafe paths, incomplete v4 input,
and a declaration changed after preview block the write; a completed second apply is a
no-op.

Migration is intentionally not compliance. The tool reports project-authorship work rather
than inventing semantic comments, controlled abbreviations, identifier grammars,
generated-code ownership, units, states, or collection meanings. Review those diagnostics,
author the project truth, then run the packaged project gate through either shipped
development leg.

A v3 repository must first use `migrate_v4.py` with an explicit `application` or
`component` unit, finish its architecture and operational declarations, and only then run
the v5 migrator.

## What is mechanically decided

- Doxygen-readable contracts remain on modules, classes, callables, fields, parameters,
  results, exceptions, effects, and other structured entities.
- `doc_coverage` allocates documentation to every governed AST binding shape, including
  locals and Python elements that Doxygen cannot represent reliably.
- `doc_narration` requires one nearby semantic owner for governed branches, loops, exits,
  translations, state transitions, and effect sequences, while rejecting directives and
  known token-level filler as substitutes.
- `documentation_model` and `doc_naming` validate source ownership, controlled scoped
  abbreviations, project-declared semantic-dimension ordering, and mappings that keep
  generated vocabulary visibly derived.
- `doc_semantics` checks declared and mechanically inferable value properties such as
  units, Boolean state meanings, collection element meanings, and callable effects.
- The Doxygen gate runs the engine, requires warning-free and non-vacuous local output,
  proves call, caller, and directory-dependency relationships, and rejects undeclared
  remote assets.
- Content-bound adversarial review invalidates semantic acceptance whenever governed bytes
  change. It owns truth, obsolete narration, and domain adequacy that syntax cannot decide.

These mechanisms implement `DOC-015` through `DOC-019` and `DOC-022` through `DOC-029`
without changing the meaning of the earlier stable DOC identifiers. The claim-disposition
ledger accounts for every normative statement in the imported commenting and documentation
source, and generated provenance rejects unreviewed or multiply claimed input.

## Qualified documentation toolchain

Doxygen 1.17.0 and Graphviz 14.1.2 are exact Conda pins shared by the native Windows and
Linux Docker legs. The environment checker runs both executables; package metadata alone is
not accepted as proof. Reduced probes establish Python entity extraction, warning behavior,
contract commands, local-allocation limits, relationship diagrams, offline HTML, and
deterministic repeated generation.

The measured boundary matters. Doxygen does not expose annotation-only dataclass fields,
callable locals, or nested functions as dependable structured members, so the AST checks
own them. `WARN_NO_PARAMDOC` remains disabled because Doxygen 1.17.0 still demands a return
contract from `-> None`; `doc_coverage` owns the accurate signature-aware proposition.

## One package for both hosts

The authored skill and doctrine corpus still ship once. Integration places byte-identical
skill entry points in Claude Code's and Codex's native discovery paths, and both route back
to the same vendored laws, model schema, checks, facts, and examples. The v5 archive also
ships `migrate_v5.py`, the documentation-model template, the canonical Doxyfile, all four
documentation checks, the Doxygen output gate, and their independent counterexamples.

Synthetic archive lifecycle tests exercise both supported repository shapes. An
application and a single-component repository install from the same staged package, reject
their v4 declaration with actionable guidance, migrate through the public command path,
and reach the same v5 project gate without assuming a parent or counterpart repository.

On the expected Windows 11 plus WSL topology, a no-argument Docker gate projects the
Windows-backed checkout into a disposable Docker-managed Linux volume. Exact bytes are
preserved and Python executable intent is derived from shebangs, so NTFS's
all-executable mode projection and metadata latency cannot create Linux-only Ruff findings
or false timeouts. The packaged JSON report is copied back and the projection is removed.
Explicit commands and shells mount the real checkout because their edits must persist.

## Compatibility and residuals

- v4 projects declaring `sphinx` or `none` no longer pass. Doxygen is a deliberate v5
  requirement, not a default selected only when convenient.
- A structurally valid documentation model can still express a poor domain vocabulary.
  Project authors and content-bound review remain accountable for meaning.
- Mechanical association proves that an eligible comment owns a syntax element; it cannot
  prove that the prose faithfully explains current behavior. The adversarial review closes
  that acceptance loop without being mislabeled static verification.
- Generated Python must pass the same source checks. The generator owns conforming comments;
  hand-editing generated output is not the remedy.
- The environment remains version-locked rather than artifact-hash-locked. Initial Conda or
  Docker construction needs the configured package channels and registry.
- The Docker image supplies discipline verifiers, not undeclared project-specific runtime
  dependencies. Each governed repository still owns its complete dependency declaration.
- No v5 claim extends to a multi-repository application root, sibling compatibility, or
  whole-system behavior.
