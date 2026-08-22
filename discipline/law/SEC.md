---
id: law/SEC
kind: law
title: Local Security and Trust Boundaries
tokens: 566
load_when:
  - "security model"
  - "trust boundary"
  - "sensitive data"
  - "classification"
  - "redaction"
  - "least exposure"
applies_to: ["pyproject.toml", "architecture.json", "security-model.json", "**/*.py"]
grounds_on: ["law/ARCH", "law/DIAG", "law/OPS"]
decay: none
python: ">=3.11"
---

# Local Security and Trust Boundaries

Security claims stop at this repository's boundary. A component states what it accepts,
validates, trusts, retains, reveals, and hands off through counterpart-neutral contract
roles; it does not assign controls to a peer or claim whole-application security.

### SEC-001 · Every contract has a local trust boundary  [BINDING] [check:security_model]
The project MUST name one repository-local `security-model.json`. Every architecture
contract MUST occur in exactly one trust-boundary record naming inbound trust, explicit
assumptions, validation before stronger trust, the point where the trust claim ceases,
and confined executable evidence.
- **Why** An unstated trust transition lets hostile representation become policy input,
  while an assumption with no endpoint quietly expands into a system-wide claim.
- **Check** `python -m checks.security_model`
- **See** [ARCH-022] · [ERR-011] · [meta/SCOPE]

### SEC-002 · Data exposure follows explicit classification  [BINDING] [check:security_model]
Every intentionally handled data class MUST name its entry trust boundaries,
classification, allowed local roles and sinks, retention policy, redaction policy, and
confined evidence. `sensitive_data = true` MUST name at least one confidential, secret,
or personal class; `false` MUST state why none is intentionally handled and MUST NOT
declare one. No role outside this repository may own a local exposure decision.
- **Why** Redaction by identifier spelling catches cheap mistakes but cannot establish
  what a value means, where it may flow, or when every copy ceases to exist.
- **Check** `python -m checks.security_model`
- **See** [DIAG-014] · [OPS-001] · [EVID-003]
