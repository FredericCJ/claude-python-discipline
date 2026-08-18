---
id: law/API
kind: law
title: Contracts and Public Surface
tokens: 2073
load_when:
  - "public API"
  - "contract"
  - "versioning"
  - "breaking change"
  - "CLI"
  - "JSON output"
  - "exit code"
  - "schema version"
  - "migration"
applies_to: ["**/*.py"]
grounds_on: ["fact/py-testing"]
requires: ["law/ARCH", "law/ERR"]
decay: none
python: ">=3.11"
---

# Contracts and Public Surface

What the outside world may depend on, and what it may not. The published surface is the
thing an agent automates against, so its stability is not a courtesy to human users — it
is what makes automated diagnosis and repair worth building at all.

An agent is an ordinary client. It gets the same contract, the same validation and the
same errors as anyone else.

---

## Contracts as artifacts

### API-001 · A contract states more than a signature  [BINDING] [fitness:test_contract_documented]
Every published operation MUST state its inputs, its results, its error variants, its
idempotency, its ordering constraints, its concurrency behaviour and its versioning.
- **Why** These are precisely the questions a failing call raises; leaving them to the
  implementation means answering them by experiment.
- **Check** `pytest enforce/fitness/test_api.py::test_contract_documented`
- **See** [law/ARCH]

### API-002 · The implementation is not the contract  [BINDING] [fitness:test_contract_documented]
Behaviour a consumer observes but the contract does not promise MUST NOT be relied upon,
and MUST NOT be treated as a breaking change when it changes.
- **Why** Otherwise every incidental detail becomes frozen by accident, and the contract
  stops describing the system.
- **Check** `pytest enforce/fitness/test_api.py::test_contract_documented`

### API-003 · Public operations speak the domain, not the store  [BINDING] [check:single_wiring_point]
The published surface MUST expose domain-level operations. Generic record manipulation and
query primitives MUST NOT be exposed.
- **Why** A generic write surface lets a client construct states the domain rules forbid,
  and the resulting corruption is attributed to the domain that never permitted it.
- **Check** `python -m checks.single_wiring_point`
- **See** [law/EFCT]

### API-004 · The persistent representation is private  [BINDING] [auto:import-linter]
Storage layout, indexes, internal identifiers and file formats MUST be implementation
detail. Where a file is deliberately hand-editable, that is a declared authoring surface
whose next load re-runs full validation.
- **Why** A sanctioned authoring surface with full revalidation is a different entry, not
  a weaker path; an unsanctioned one is a second writer with no owner.
- **Check** `lint-imports` contract `storage-has-one-owner`

---

## Machine-readable output

### API-005 · Structured output is the primary interface  [BINDING] [fitness:test_structured_output]
Every command MUST be able to emit a machine-readable result carrying a schema identifier,
the outcome, the data, and any errors as structured values.
- **Why** Human text is a rendering; an agent parsing prose is an agent that breaks when
  the prose improves.
- **Check** `pytest enforce/fitness/test_api.py::test_structured_output`

### API-006 · Human output renders the same result object  [BINDING] [fitness:test_structured_output]
The text presentation MUST be a view over the structured result, never a separate
computation.
- **Why** Two renderings of one outcome diverge, and the divergence is discovered by a
  user reading one while an agent acts on the other.
- **Check** `pytest enforce/fitness/test_api.py::test_structured_output`

### API-007 · Exit status is part of the contract  [BINDING] [fitness:test_exit_codes]
Each defined exit status MUST correspond to a stated outcome class, and MUST be documented
and tested.
- **Why** It is the only signal available to a caller that reads nothing else, and the
  first thing a script branches on.
- **Check** `pytest enforce/fitness/test_api.py::test_exit_codes`
- **See** [law/ERR]

### API-008 · The surface is self-describing  [BINDING] [fitness:test_structured_output]
The published surface MUST offer a machine-readable description of its own operations,
arguments and error codes.
- **Why** A client that can enumerate the contract can adapt to it; one that cannot must
  hard-code assumptions that silently rot.
- **Check** `pytest enforce/fitness/test_api.py::test_structured_output`

### API-009 · Automation gets no relaxed validation  [BINDING] [fitness:test_agent_parity]
A request from an agent, a hook or a script MUST be validated identically to one from a
person. No privileged path, no skipped checks, no direct store access.
- **Why** The value of a validated core is that every producer of bad state hits the same
  wall; one exception makes the guarantee conditional and therefore useless to reason from.
- **Check** `pytest enforce/fitness/test_api.py::test_agent_parity`

Assume automated clients will send stale reads, repeat commands, and submit malformed
input. These are ordinary inputs with ordinary typed refusals, not exceptional conditions.

---

## Versioning

### API-010 · Every published payload carries a schema version  [BINDING] [fitness:test_schema_versioned]
Structured results and persisted formats MUST carry an explicit version identifier.
- **Why** Without it, a consumer cannot tell an old producer from a broken one, and both
  present as malformed input.
- **Check** `pytest enforce/fitness/test_api.py::test_schema_versioned`

### API-011 · Error codes and result variants are versioned surface  [BINDING] [fitness:test_codes_are_stable]
Renaming an error code, removing one, or adding a variant to a published result union is a
breaking change.
- **Why** These are what an automated consumer branches on, so they are load-bearing in
  exactly the way a function name is.
- **Check** `pytest enforce/fitness/test_diagnostics.py::test_codes_are_stable`
- **See** [law/DIAG]

### API-012 · A format change ships with a migration and its test  [BINDING] [fitness:test_migrations]
Changing a persisted format MUST include a migration and a test that runs it against a
fixture of the previous version.
- **Why** A migration nobody has run against real prior data is a plan, not a migration.
- **Check** `pytest enforce/fitness/test_api.py::test_migrations`

### API-013 · Compatibility is not inherited from parser tolerance  [BINDING] [fitness:test_schema_versioned]
Compatibility MUST rest on a stated policy, never on a parser happening to accept an
older shape.
- **Why** Accidental tolerance disappears in a dependency upgrade nobody connected to it.
- **Check** `pytest enforce/fitness/test_api.py::test_schema_versioned`

### API-014 · Prefer additive change  [ADVISORY]
Extend the surface with new fields and new operations rather than repurposing existing
ones.
- **No mechanism** Whether a change is genuinely additive in meaning, rather than only in
  shape, is a semantic judgment; [API-011] mechanizes the cases that can be detected.
- **Why** A field that quietly changes meaning breaks consumers that still typecheck,
  which is the failure mode with the worst diagnostic signal of all.

### API-015 · The delivered artifact is what gets tested  [BINDING] [fitness:test_delivered_boundary]
End-to-end tests MUST exercise the installed entry point as a separate process, asserting
its structured output and exit status.
- **Why** Testing the imported function verifies the library; the contract that ships is
  the process boundary, and only running it tests packaging, arguments and exit paths.
- **Check** `pytest enforce/fitness/test_api.py::test_delivered_boundary`
