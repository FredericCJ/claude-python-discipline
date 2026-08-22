---
id: meta/SCOPE
kind: meta
title: Governed Repository Scope
tokens: 706
load_when:
  - "application repository"
  - "component repository"
  - "multi-component"
  - "parent repository"
  - "scope"
decay: none
---

# Governed Repository Scope

The discipline has exactly one subject: the repository in which it is installed. That
repository contains either one complete application or one independently developed
component of a larger application. Both are consequential, potentially long-lived Python
software; small scripts and disposable programs are outside the product class.

## The two unit kinds

**Application** means the repository owns the complete deliverable, its external entry
points and every runtime resource the deliverable creates or retains.

**Component** means the repository owns one independently buildable and testable
deliverable. It owns its side of every published or consumed contract, while counterpart
identity and the application that wires several components together remain outside the
repository.

Internal packages and modules do not create additional governed units. They are the
architecture of the one application or component declared by the repository.

## The boundary

For a component, the discipline covers its domain, application logic, ports, adapters,
repository-local shell, artifact, diagnostics, tests and operational behavior. External
actors are named only by contract role. Counterpart repositories, deployment endpoints,
cross-repository wiring, compatibility between independent implementations, global
lifecycle and whole-application verification are not subjects of this corpus.

A component remains verifiable from its own checkout. Its gate does not inspect a parent
checkout, discover siblings, consume another repository's verdict or emit a system-wide
verdict. A contract imported from elsewhere is a locally versioned input with provenance;
synchronizing it across repositories belongs to the integrator.

## Ownership at the boundary

Effects remain local even when the larger application is not. A repository accounts for
every resource it owns and every ownership transfer it initiates. If it opens a socket,
starts a thread, launches a process or persists state, its contract states whether the
resource remains locally owned or where lifecycle ownership is handed off. The discipline
checks that local behavior; it does not infer responsibility for resources owned beyond
the handoff.

The same boundary applies to evidence. Integration observations may motivate a local rule,
but they do not expand the rule's subject beyond one repository.
