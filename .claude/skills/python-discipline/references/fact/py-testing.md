---
id: fact/py-testing
kind: fact
title: Python Testing Tooling
tokens: 1423
load_when:
  - "pytest version"
  - "fixture scope"
  - "hypothesis"
  - "coverage tool"
  - "mutation tool"
  - "pytest plugin"
  - "markers"
verified: 2026-08-18
decay: quarters
python: ">=3.11"
---

# Python Testing Tooling

What the test tooling actually provides. The obligations are in [law/TEST]; this is the
ground truth those obligations are satisfiable against.

---

## Installed versions

| Tool | Version | Role |
|---|---|---|
| pytest | 9.1.1 | runner |
| hypothesis | 6.165.10 | property-based generation |
| coverage.py | 7.15.4 | line and branch measurement |
| mutmut | 3.7.0 | mutation engine |
| pytest-randomly | 4.1.0 | order randomization |
| pytest-timeout | 2.4.0 | per-test budget |
| pytest-socket | 0.8.0 | network isolation |

`VERSION-DEPENDENT` — pytest crossed a major boundary at 9.0, which turned prior
deprecation warnings into errors and added native configuration in the project file. A
configuration written for the 8.x line may not load unchanged.

## Runner facts

`ESTABLISHED` — fixture scopes are exactly five: function (the default), class, module,
package, session. Fixtures are created when first requested and destroyed according to
scope. Any list naming six is conflating something else.

`ESTABLISHED` — parametrization stacks multiplicatively; two stacked decorators produce the
Cartesian product, not the zip.

`ESTABLISHED` — markers must be registered, and strict-marker mode turns an unregistered
marker into an error rather than a warning. Without it, a typo in a marker name silently
selects nothing, which is a test suite that passes by running none of itself.

`ESTABLISHED` — assertion rewriting applies to test modules and to plugins that register
for it. A helper module that has not registered gets bare assertion output with no values.

## Property-based generation

`ESTABLISHED` — the default is 100 generated examples per property. Failures are shrunk to
a minimal counterexample.

`ESTABLISHED` — the local example database persists failing cases between runs. It is a
convenience, not a durable record: it is machine-local and can be cleared. A counterexample
worth keeping is promoted to an explicit committed fixture, which is what [law/TEST]
requires.

`ESTABLISHED` — the useful property classes are round-trip, invariant, oracle or
differential, and metamorphic. Stateful testing with rule-based machines is available for
protocols whose legal calls depend on prior calls — the case the type system cannot express.

## Measurement

`ESTABLISHED` — coverage.py measures line coverage and, when enabled, branch coverage.
Neither can distinguish a line that ran from a line whose logic was verified.

`ESTABLISHED` — on recent interpreters coverage.py can use the built-in monitoring
interface, which is substantially faster but does not support every plugin and context
feature. A configuration relying on those features must not assume it.

`ESTABLISHED` — the widely cited position, and the reason [law/TEST] refuses a percentage
gate, is that a numeric target is easy to reach with low-quality tests. Treated as a target
rather than a diagnostic, it is a textbook Goodhart failure.

`ESTABLISHED` — mutation testing is the measurement that does discriminate: it seeds a
defect and asks whether the suite notices. It is the only available check on the suite
itself.

`OPEN` — no mainstream tool measures `modified condition/decision coverage` for this
language. [law/TEST] therefore meets the requirement by construction — decomposed
predicates plus a truth table — rather than by measurement. If a credible tool appears,
that rule's mechanism should be revisited.

## Isolation

`ESTABLISHED` — network blocking is available as a plugin that fails closed by default,
which is the property an autouse fixture someone forgets to request does not have.

`ESTABLISHED` — temporary-directory and environment-patching fixtures are built in. They
are appropriate at the contract, integration and fault layers, and not at the unit layer,
which touches no filesystem at all.

`ESTABLISHED` — order randomization with a reported seed makes order dependence visible
and reproducible. Without it, an order dependence is a failure that appears on someone
else's machine.

## Test doubles

`ESTABLISHED` — the classical taxonomy is dummy, fake, stub, spy, mock, distinguished by
whether they verify state or interaction.

This discipline uses **real / fake / faulty** instead, and maps the classical terms onto it
in [meta/GLOSSARY]. "Faulty" has no equivalent in the classical taxonomy, which is why the
substitution is necessary rather than cosmetic.

`ESTABLISHED` — auto-specced mocks constrain calls to the real signature; unspecced ones do
not, and a suite of unspecced mocks can pass while the real integration is broken. Where a
contract exists, a fake implementing it is strictly better, which is why [law/TEST] puts
the contract suite at the top of the oracle hierarchy.

---

## Sources

Verified against the official documentation of each tool and by invoking the installed
versions on 2026-08-18. Version numbers are read from the tools, not from a changelog.
Re-verify when `verified:` exceeds the decay window.
