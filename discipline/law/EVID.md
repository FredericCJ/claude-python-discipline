---
id: law/EVID
kind: law
title: Claims and Verification Evidence
tokens: 1288
load_when:
  - "why is this a rule"
  - "verification strategy"
  - "mechanism"
  - "proxy"
  - "residual"
  - "discrimination"
  - "field evidence"
  - "supersede a rule"
applies_to: ["discipline/**/*", "enforce/**/*"]
grounds_on: ["meta/SCHEMA", "meta/PROVENANCE", "fact/py-testing"]
requires: ["law/FLOW", "law/TEST"]
decay: none
python: ">=3.11"
---

# Claims and Verification Evidence

A useful engineering obligation, a checker that observes one proposition, and a result
seen in one adopter are three different claims. This module prevents any one from being
presented as either of the others.

## Claim identity

### EVID-001 · Every rule owns one evidence record  [BINDING] [fitness:test_evidence_registry_joins_rules]
Every active or retired stable rule ID MUST join to exactly one authored evidence record,
and no evidence record may name an absent rule.
- **Why** An unjoined rationale or verifier can drift while still looking related by
  proximity, and a deleted retired record makes old citations change meaning.
- **Check** `pytest enforce/fitness/test_evidence.py::test_evidence_registry_joins_rules`
- **See** [meta/SCHEMA]

### EVID-002 · Every strategy states its observable  [BINDING] [fitness:test_strategy_claims_are_explicit]
Each heading mechanism MUST have exactly one strategy stating its kind, exact observable
proposition, supported platforms, not-applicable condition, and residual.
- **Why** A mechanism name establishes neither what it observes nor what remains possible
  after it accepts.
- **Check** `pytest enforce/fitness/test_evidence.py::test_strategy_claims_are_explicit`
- **See** [FLOW-006]

### EVID-003 · Proxy claims retain their residual  [BINDING] [fitness:test_proxy_claims_preserve_residuals]
A proxy strategy MUST remain labeled `proxy` in every generated view and MUST carry the
semantic claim it does not decide.
- **Why** A proxy is useful only while its limit travels with its result; dropping the
  residual silently upgrades correlation into proof.
- **Check** `pytest enforce/fitness/test_evidence.py::test_proxy_claims_preserve_residuals`
- **See** [FLOW-007]

### EVID-004 · Declarations earn no rejection credit  [BINDING] [fitness:test_rejection_credit_is_witnessed]
A must-reject label MUST NOT be reported as discrimination evidence until the named
strategy has been observed rejecting that counterexample by its diagnostic ID.
- **Why** Writing down an expected failure observes nothing, and is compatible with a
  checker that always accepts.
- **Check** `pytest enforce/fitness/test_evidence.py::test_rejection_credit_is_witnessed`
- **See** [TEST-015]

### EVID-005 · Build views publish no gate outcome  [BINDING] [fitness:test_generated_rules_publish_no_gate_outcome]
A generated corpus view MUST report verifier availability only; `pass`, `fail`,
`not-applicable`, `unsupported`, and `not-run` belong only to a named gate execution.
- **Why** A build that never ran a verifier cannot distinguish a pass from a missing,
  unsupported, or misconfigured invocation.
- **Check** `pytest enforce/fitness/test_evidence.py::test_generated_rules_publish_no_gate_outcome`
- **See** [FLOW-009]

## Warrants, observations, and history

### EVID-006 · Warrants state relation and confidence  [BINDING] [fitness:test_warrants_are_typed]
Every normative rule MUST cite at least one warrant with an explicit relation and
confidence; citation presence alone MUST NOT be treated as support.
- **Why** A source may motivate, limit, or merely report a rule, and erasing that relation
  makes a bibliography look like a proof.
- **Check** `pytest enforce/fitness/test_evidence.py::test_warrants_are_typed`
- **See** [meta/PROVENANCE]

### EVID-007 · Field observations resolve to records  [BINDING] [fitness:test_field_observations_resolve]
Every field-observation ID MUST resolve to a classified claim with named evidence
locations, scope, provenance, and a reproduction or explicit manual-synthesis label.
- **Why** An unlabeled anecdote cannot be challenged, repeated, or distinguished from a
  general claim.
- **Check** `pytest enforce/fitness/test_evidence.py::test_field_observations_resolve`

### EVID-008 · Stable IDs preserve migration history  [BINDING] [fitness:test_rule_migrations_are_total]
Every rule MUST state its migration disposition and guidance; a superseded or consolidated
ID retains its heading and successor, while a withdrawn ID remains resolvable as retired.
- **Why** Reusing or deleting an ID changes the meaning of old reviews, baselines, waivers,
  and diagnostics without changing their text.
- **Check** `pytest enforce/fitness/test_evidence.py::test_rule_migrations_are_total`
- **See** [FLOW-004]
