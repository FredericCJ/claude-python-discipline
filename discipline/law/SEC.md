---
id: law/SEC
kind: law
title: Local Security and Trust Boundaries
tokens: 1095
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

## Adversarial acceptance

### SEC-003 · Semantic review is bound to exact content  [BINDING] [check:adversarial_review]
The project MUST name one repository-local `adversarial-review.json` carrying a full base
commit id and the exact generated digest and file count for every repository-owned file.
Only fixed environment and verifier caches, the vendored discipline, generated
native-host mirrors, build output, and the review artifact's unavoidable self-reference
may be excluded. Any change to the computed scope MUST make the review stale. UTF-8 CRLF
checkout projections MUST canonicalize to LF so identical reviewed Git text retains one
identity on Windows and Linux; invalid UTF-8 assets remain byte-exact.
- **Why** A review of a previous tree is an opinion about different software; a timestamp
  or filename cannot establish what bytes the reviewer actually considered.
- **Check** `python -m checks.adversarial_review`
- **See** [EVID-003] · [FLOW-011]

### SEC-004 · Adversarial acceptance records challenge and closure  [BINDING] [check:adversarial_review] [review]
An accepted review MUST cover architecture, contracts, failure containment, lifecycle and
budgets, trust and data, observability, supply chain, and test oracles in canonical order.
It MUST name a reviewer identity outside the author identities, state the independence
basis, record at least one concrete objection, close or explicitly accept every risk with
local evidence and a re-review trigger, and preserve a conclusion and residual. An open
objection or rejected verdict MUST fail acceptance.
- **Why** Presence-only review rewards an empty form. Named hostile questions and durable
  objections make the judgment inspectable without pretending a checker can authenticate
  independence or evaluate insight.
- **Check** `python -m checks.adversarial_review`, followed by semantic review of the
  artifact and cited evidence.
- **See** [EVID-005] · [TEST-015] · [FLOW-007]
