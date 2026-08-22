---
id: law/ARCH-PORTS
kind: law
title: Boundary Contracts and Conformance
tokens: 841
rule_prefix: ARCH
load_when:
  - "new port"
  - "boundary contract"
  - "adapter substitute"
  - "fake adapter"
  - "fault schedule"
  - "contract suite"
applies_to: ["**/*.py", "architecture.json", "contract-conformance.json"]
grounds_on: ["law/ARCH", "law/TYPE", "law/TEST"]
decay: none
python: ">=3.11"
---

# Boundary Contracts and Conformance

A boundary is justified by the decision it hides and proved through observable contract
terms. Python representation is explicit; semantic test capabilities replace file-shape
ceremony.

## Retained v3 identities

### ARCH-007 · Every port is a Protocol with a published contract  [RETIRED]
Retired because it combined contract completeness with one prescribed representation.
- **Why** Historical findings remain resolvable without making `Protocol` universal.
- **Superseded by** ARCH-024
- **See** [ARCH-022]

### ARCH-008 · Every port has a real, a fake and a faulty adapter  [RETIRED]
Retired because three files do not prove controlled state, injected failure, or fidelity.
- **Why** Semantic capabilities survive refactoring and may share one implementation.
- **Superseded by** ARCH-025

### ARCH-009 · One contract suite runs against every adapter  [RETIRED]
Consolidated with the duplicate testing rules into one term-traceable obligation.
- **Why** Three ids counted one observed suite property three times.
- **Superseded by** TEST-020

### ARCH-010 · A port earns its place from a stated justification  [RETIRED]
Retired because generic docstring phrases did not identify a volatile decision or change.
- **Why** Information-hiding evidence belongs in the canonical architecture model.
- **Superseded by** ARCH-021

## v4 contract evidence

### ARCH-024 · Boundary representation is explicit and locally resolvable  [BINDING] [check:contract_conformance]
Every internal contract in `architecture.json` MUST have exactly one record in
`contract-conformance.json`. It MUST name a local boundary class and select `structural`
or `nominal`; source MUST match. Structural boundaries derive from `Protocol`. Nominal
boundaries declare abstract behavior and every registered implementation inherits them.
- **Why** Representation is a local design choice. Declaring it preserves a typed,
  inspectable boundary without confusing structural typing with architecture.
- **Check** `python -m checks.contract_conformance`
- **See** [ARCH-022] · [law/TYPE]

### ARCH-025 · Conformance evidence names capabilities, not a file triad  [BINDING] [check:contract_conformance]
Every internal contract MUST register a real implementation and test evidence that is
controllable and executes scheduled faults. One test implementation MAY provide both
capabilities. Every implementation MUST resolve to one local class; filenames are free.
- **Why** Real behavior, controlled state, and injected failure are the required
  observations. A physical triad is neither necessary nor sufficient for them.
- **Check** `python -m checks.contract_conformance`
- **See** [TEST-020] · [EVID-003]
