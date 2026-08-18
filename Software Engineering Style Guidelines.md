# Software Engineering Style Guidelines

## 1. Purpose and Engineering Philosophy

This engineering style is intended for software whose core behavior should remain understandable, testable, replaceable, and robust under both expected and abnormal operating conditions.

The principal objective is not merely to produce working software. The objective is to produce software for which important behavior can be reasoned about, exercised independently, and challenged systematically.

The style therefore favors:

- explicit contracts over implicit coupling;
- independently testable components over tightly integrated implementations;
- deterministic logic over hidden side effects;
- strong static guarantees where practical;
- compiled binaries for application core functionality;
- replaceable adapters at external boundaries;
- aggressive testing of both nominal and abnormal behavior;
- deliberate testing of fault propagation and containment;
- machine-readable interfaces suitable for human tools, scripts, and autonomous agents.

Architectural choices should improve the ability to verify the system. Abstraction is useful when it creates a meaningful boundary for specification, substitution, observation, or containment. Abstraction for its own sake should be avoided.

---

# 2. Separation of Core and Presentation

The application core and the graphical user interface should normally be treated as separate programs.

The core is the authoritative implementation of application semantics. The GUI is a client.

A typical structure is:

```text
┌───────────────────────┐
│          GUI          │
│                       │
│ presentation          │
│ interaction           │
│ visualization         │
└───────────┬───────────┘
            │
            │ explicit interaction contract
            │
┌───────────▼───────────┐
│     application core  │
│                       │
│ domain semantics      │
│ validation            │
│ persistence control   │
│ transactions          │
│ business rules        │
└───────────┬───────────┘
            │
            ▼
      external systems
```

The GUI technology is not required to match the core technology.

The GUI may therefore use whichever framework provides the best development efficiency and user-interface capabilities, provided that it communicates with the core exclusively through the defined interaction contract.

The GUI should not contain authoritative copies of domain rules.

In particular, the GUI should not be responsible for:

- enforcing persistent domain invariants;
- deciding whether a transaction is semantically valid;
- directly manipulating the application's persistent database;
- reproducing substantial portions of the domain model;
- silently correcting invalid requests before sending them to the core.

Presentation-level validation may be duplicated for usability, but the core remains authoritative.

---

# 3. Compiled Core

Core application functionality should normally be delivered as compiled binaries.

The choice is motivated by several objectives:

- strong static verification;
- explicit dependency management;
- predictable deployment;
- controlled runtime behavior;
- clear process boundaries;
- reduced dependence on mutable runtime environments;
- straightforward testing of the exact executable artifact delivered to users.

Languages and runtimes should be selected according to the application rather than ideology, but strong static typing and meaningful compile-time diagnostics are preferred.

Dynamic languages remain appropriate for:

- scripting;
- experimentation;
- data analysis;
- development tooling;
- orchestration;
- prototypes;
- auxiliary automation.

They should not automatically become the implementation language for long-lived application cores merely because development is initially convenient.

---

# 4. Contracts Are First-Class Engineering Artifacts

Interactions between components should be governed by explicit contracts.

This applies especially to boundaries between independently executable programs, but the same principle applies inside the application architecture.

A contract should describe more than the serialized representation of a message.

Where relevant, it should specify:

- accepted inputs;
- output semantics;
- preconditions;
- postconditions;
- invariants;
- error conditions;
- failure semantics;
- transactional behavior;
- ordering constraints;
- idempotency;
- concurrency assumptions;
- versioning behavior;
- compatibility requirements;
- timing expectations where timing is significant.

The physical implementation of a component should not become an undocumented extension of its contract.

Consumers should depend on the contract, not on incidental behavior observed from a particular implementation.

For example, if a storage port specifies:

```text
save(A)
get(A) -> A
```

a consumer should not rely on undocumented properties such as insertion order, hidden caching behavior, filesystem layout, or internal database identifiers.

---

# 5. Public Contracts and Private Representations

Persistent representation and external application contracts should remain separate.

For example:

```text
SQLite schema
    PRIVATE

Application API
    PUBLIC
```

Clients should interact with application concepts rather than database tables.

Prefer:

```text
CreateRequirement
ReviseRequirement
CreateTrace
CreateBaseline
RunValidation
ApplyChangeSet
```

over exposing generic database-oriented operations such as:

```text
InsertRow
UpdateRecord
ExecuteSQL
```

This separation permits the internal representation to evolve without forcing unrelated clients to change.

Database migrations, indexing strategies, normalization choices, caching, and internal identifiers should remain implementation details unless there is a specific architectural reason to expose them.

---

# 6. Hexagonal Modular Architecture

Application cores should generally follow a hexagonal, ports-and-adapters architecture.

The domain and application logic occupy the center.

External systems are accessed through explicit ports.

Concrete technologies are implemented by adapters.

A typical arrangement is:

```text
                    ┌──────────────────┐
                    │   application    │
                    │      core        │
                    └────────┬─────────┘
                             │
                 ┌───────────┼───────────┐
                 │           │           │
               port        port        port
                 │           │           │
                 ▼           ▼           ▼
             SQLite      filesystem     IPC
             adapter       adapter     adapter
```

The inner layers should not depend directly on concrete infrastructure where such dependency would prevent substitution or independent verification.

Dependencies should normally point inward.

However, ports should not be introduced mechanically.

A port is justified when there is value in one or more of:

- replacing the implementation;
- independently testing the consumer;
- defining a behavioral contract;
- controlling side effects;
- injecting faults;
- observing interactions;
- isolating external instability;
- supporting multiple adapters;
- decoupling the domain model from infrastructure.

Wrapping every standard-library call behind an interface without one of these purposes is unnecessary abstraction.

---

# 7. Functional Core, Imperative Shell

The application should push as much domain logic as practical into deterministic, side-effect-free transformations.

The preferred conceptual model is:

```text
input state
    +
command
    │
    ▼
pure domain logic
    │
    ▼
result / state transition / effects description
```

The imperative shell is responsible for performing effects:

```text
deserialize
    ↓
load state
    ↓
invoke functional core
    ↓
interpret result
    ↓
perform persistence / I/O
    ↓
return response
```

A domain operation should therefore tend toward forms such as:

```text
evaluate(current_state, command)
    -> result
```

rather than directly manipulating databases, sockets, filesystems, clocks, environment variables, or user-interface state.

Benefits include:

- deterministic unit testing;
- simpler mutation testing;
- easier fuzzing;
- simpler property-based testing;
- clearer failure analysis;
- reduced mocking;
- easier reasoning about state transitions;
- reduced coupling between business semantics and infrastructure.

Side effects are not prohibited. They are concentrated where they can be controlled.

---

# 8. Make Effects Explicit

Operations with external effects should be visible in the design.

Important effects include:

- persistence;
- filesystem access;
- IPC;
- networking;
- clocks;
- randomness;
- process execution;
- operating-system state;
- environment variables;
- concurrency;
- external libraries with hidden state.

Avoid domain functions whose apparent signature hides significant external interaction.

For example, prefer an explicit dependency:

```text
evaluate_expiration(now, object)
```

over domain logic that silently reads the system clock.

Likewise, generated identifiers, randomness, and environment-dependent configuration should be controllable when they affect observable application behavior.

---

# 9. Commands Over Raw Mutation

Where appropriate, application state changes should be represented as explicit domain operations rather than arbitrary mutation.

For example:

```text
ReviseRequirement
CreateTrace
DeleteTrace
CreateBaseline
ApplyChangeSet
```

is preferable to exposing general-purpose mutation primitives.

A command should express intent.

The core should determine whether that intent is valid.

This separation supports:

- validation;
- auditability;
- dry runs;
- deterministic replay;
- testing;
- authorization;
- change review;
- agentic operation;
- transaction boundaries.

For complex changes, a first-class change-set representation is encouraged.

A change set can be validated before application:

```text
construct
    ↓
validate syntax
    ↓
validate references
    ↓
validate domain invariants
    ↓
calculate consequences
    ↓
commit atomically
```

Dry-run capability should be considered when changes can have broad consequences.

---

# 10. Prefer Explicit State Transitions

Important domain objects should not be allowed to drift arbitrarily between states.

Where the domain contains lifecycle concepts, represent legal state transitions explicitly.

For example:

```text
Draft
  ↓
Reviewed
  ↓
Approved
  ↓
Obsolete
```

should not merely be represented as an unconstrained string field if transitions have domain significance.

Illegal transitions should fail explicitly.

Where possible, the type system should make invalid states harder to represent.

---

# 11. Strong Typing as a Design Tool

Static typing should be used to communicate domain structure rather than merely satisfy a compiler.

Avoid excessive use of primitive representations when domain distinctions matter.

Instead of conceptually treating these as interchangeable strings:

```text
RequirementId
BaselineId
ChangeSetId
UserId
```

represent them as distinct types where practical.

Similarly, prefer:

```text
enum RelationType {
    Satisfies,
    Refines,
    Verifies,
    DerivesFrom
}
```

over unconstrained text when the domain contains a known closed set.

Types should help prevent invalid combinations before runtime.

However, type sophistication should remain proportional to the benefit. Highly elaborate type machinery that significantly obscures otherwise simple behavior is undesirable.

---

# 12. Explicit Error Semantics

Errors are part of the contract.

Do not collapse all failures into generic exceptions, strings, boolean failure flags, or process termination.

Where practical, distinguish failure categories.

For example:

```text
NotFound
InvalidCommand
InvariantViolation
Conflict
PersistenceFailure
ProtocolViolation
UnsupportedVersion
CorruptState
```

Infrastructure failures and domain rejections should remain distinguishable.

For example:

```text
Requirement cannot transition from Approved to Draft
```

is not the same kind of failure as:

```text
SQLite returned I/O error
```

This distinction is important for recovery, diagnostics, automated clients, and fault-injection testing.

---

# 13. Expected Failure Versus Contract Violation

The design should distinguish between a component reporting an allowed failure and a component violating its contract.

For example:

```text
repository -> DiskFull
```

may be a legitimate failure mode.

By contrast:

```text
save(A)
read(A) -> B
```

may indicate a non-conformant or corrupted component.

These should not be treated as equivalent.

The system should be tested against both:

```text
conformant failures
```

and:

```text
non-conformant / tainted behavior
```

The latter is essential for discovering hidden assumptions between components.

---

# 14. Testing Is an Architectural Activity

Testing should influence architecture from the beginning.

A component that cannot be exercised independently should trigger examination of its boundaries and dependencies.

Testing should not primarily be used to demonstrate that the implementation works under nominal examples. It should challenge the assumptions embedded in the implementation.

The verification toolbox may include:

- unit testing;
- integration testing;
- end-to-end testing;
- mutation testing;
- MC/DC analysis;
- fuzz testing;
- property-based testing;
- fault injection;
- robustness testing;
- destructive testing;
- concurrency testing;
- persistence recovery testing;
- protocol testing;
- component substitution;
- corrupted-input testing.

Not every technique must be applied everywhere. Selection should follow the type of behavior being verified.

---

# 15. Unit Tests

Unit tests should concentrate primarily on deterministic logic and locally meaningful behavior.

The functional core should permit substantial testing without:

- a database;
- a network;
- a filesystem;
- operating-system state;
- wall-clock time;
- real external processes.

Unit tests should verify both expected results and rejected states.

Tests should emphasize domain invariants rather than simply mirroring implementation functions.

---

# 16. Integration Tests

Integration tests should exercise real boundaries.

Examples include:

```text
application ↔ SQLite
application ↔ filesystem
client ↔ IPC server
serialization ↔ protocol implementation
migration ↔ previous database version
```

Integration testing is not replaced by mocked unit tests.

Mocks and synthetic adapters test controlled models of dependencies. Integration tests verify assumptions against the real technology.

Both are necessary.

---

# 17. Port Contract Tests

Every important port should have an associated behavioral contract.

Where multiple adapters implement the same port, the same contract test suite should be executable against each adapter.

Conceptually:

```text
RepositoryContract
        │
        ├── InMemoryRepository
        ├── SQLiteRepository
        ├── InstrumentedRepository
        └── other implementation
```

This verifies substitutability rather than merely checking each implementation independently.

Contract tests should cover behavior observable by consumers, not internal implementation details.

---

# 18. Deliberately Broken Components

The test environment should contain intentionally defective implementations of important ports and adapters.

Examples include:

```text
FailAlwaysStore
FailNthWriteStore
DelayedStore
ReadOnlyStore
CorruptReadStore
StaleReadStore
DuplicatingTransport
DroppedMessageTransport
MalformedReplyTransport
FrozenClock
JumpingClock
```

These components are not merely test doubles. They are instruments for evaluating the behavior of the rest of the architecture under controlled failure.

The purpose is to ask:

> What happens to healthy components when an adjacent component fails or becomes untrustworthy?

---

# 19. Fault Propagation and Containment

Testing should explicitly evaluate propagation.

If component A is faulty and component B is healthy, observe whether B:

- detects the fault;
- rejects invalid data;
- enters a safe state;
- propagates an explicit error;
- continues correctly where possible;
- corrupts its own state;
- propagates corrupted information to C.

A useful conceptual experiment is:

```text
healthy A
   │
poisoned B
   │
healthy C
```

The behavior of C is often more interesting than the direct failure of B.

This testing reveals undocumented assumptions and insufficient validation at boundaries.

---

# 20. Architectural Mutation Testing

Traditional mutation testing changes implementation logic.

For example:

```text
x > 5
```

may become:

```text
x >= 5
```

The same principle should also be applied at component boundaries.

Instead of mutating code, mutate behavior:

```text
valid response
    ↓
stale but valid response
```

or:

```text
one delivery
    ↓
duplicate delivery
```

or:

```text
atomic operation
    ↓
partial apparent completion
```

This form of architectural mutation testing is useful for detecting assumptions that were never included in the formal interaction contract.

---

# 21. Fault Models

Important boundaries should have an explicit fault model.

Relevant categories commonly include:

### Explicit failure

The component reports that an operation failed.

```text
Err(DiskFull)
```

### Omission

Expected output or activity never occurs.

```text
message dropped
```

### Timing failure

The operation completes too late or stalls.

```text
timeout
```

### Value corruption

The returned object is syntactically valid but semantically incorrect.

```text
requested A
returned B
```

### State inconsistency

Different operations expose mutually inconsistent state.

```text
exists(A) -> true
get(A)    -> NotFound
```

### Stale state

A previously valid state is returned after it should have changed.

### Duplication

A command, event, or result appears more than once.

### Reordering

Events occur in a legal individual form but illegal sequence.

### Partial effect

Only part of an operation becomes externally observable.

### Protocol violation

The component violates sequencing or framing rules.

Fault injection should be organized around such categories where practical rather than accumulated as unrelated special-case mocks.

---

# 22. Fault Schedules as Data

For components that are heavily tested under failure, faults should preferably be configurable rather than hard-coded into individual mock classes.

For example:

```text
FaultSchedule {
    fail_write: 3
}
```

could mean:

> fail the third write operation.

More complex schedules might describe:

```text
operation 2 -> delayed
operation 5 -> corrupted response
operation 8 -> explicit failure
```

Representing fault schedules as data allows the same mechanism to be reused by:

- deterministic tests;
- property tests;
- fuzzers;
- regression tests;
- fault-injection campaigns.

A failing generated schedule can then be persisted and replayed exactly.

---

# 23. Mutation Testing

Mutation testing should be used where conventional coverage could provide false confidence.

The purpose is not to maximize a mutation score blindly.

The useful question is:

> If meaningful logic were subtly wrong, would the test suite detect it?

Surviving mutants should be investigated to determine whether they indicate:

- missing tests;
- redundant code;
- equivalent mutants;
- insufficiently specified behavior;
- overly complex decision logic.

Mutation testing is particularly valuable for validation rules and domain decisions.

---

# 24. MC/DC

MC/DC should be used where decision logic warrants detailed examination.

The objective is to demonstrate that individual conditions within important decisions independently affect outcomes.

MC/DC is particularly useful for logic such as:

```text
valid_revision
AND
authorized_transition
AND
all_dependencies_resolved
```

where ordinary branch coverage can hide untested condition interactions.

MC/DC should complement, not replace, semantic testing.

A test suite can obtain excellent structural coverage while still misunderstanding the domain.

---

# 25. Fuzzing

Interfaces that process structured or externally influenced data should be considered fuzzing targets.

Potential targets include:

- import formats;
- parsers;
- serialization;
- IPC messages;
- query languages;
- identifiers;
- migration inputs;
- change sets;
- trace structures;
- malformed persistent data.

Prefer fuzzing typed or structured representations when possible.

The objective should extend beyond avoiding crashes.

Relevant properties include:

```text
must not panic
must not corrupt persistent state
must not violate invariants
must return bounded diagnostics
must not hang indefinitely
```

---

# 26. Property-Based Testing

For domain logic, general properties are often more useful than large numbers of manually selected examples.

Examples:

```text
Applying an invalid change set never modifies persistent state.
```

```text
Creating and then deleting a trace restores the previous trace set.
```

```text
Serializing and deserializing a valid contract object preserves its meaning.
```

```text
A baseline is immutable after successful creation.
```

```text
No valid command may create a dangling mandatory reference.
```

Property tests should generate broad state spaces and preserve failing cases as regression tests when useful.

---

# 27. Test Real Failure Modes Too

Synthetic failure adapters are valuable because they make faults deterministic and reproducible.

They must not become the sole source of confidence.

Real infrastructure should also be challenged.

Examples include:

- killing the process during persistence;
- corrupting database files;
- denying filesystem permissions;
- exhausting disk capacity;
- terminating IPC clients mid-request;
- restarting the engine between operations;
- using older database schemas;
- sending malformed protocol messages;
- testing concurrent clients.

Synthetic testing verifies the fault model.

Destructive system testing verifies whether the fault model is complete enough.

---

# 28. Persistence Ownership

Persistent state should have a clearly defined owner.

For a local application with a dedicated core process, clients should not independently manipulate the core database.

Prefer:

```text
GUI ────────┐
CLI ────────┼── contract ──> core ──> SQLite
Agent ──────┘
```

over:

```text
GUI ────┐
CLI ────┼──> SQLite
Agent ──┘
```

This ensures that all mutations pass through the same validation, transaction, audit, and invariant enforcement.

---

# 29. Transactions and Partial Failure

Operations that conceptually represent one state transition should normally be atomic.

The design should explicitly consider what happens if failure occurs after each externally relevant step.

For a sequence:

```text
operation 1
operation 2
operation 3
operation 4
```

fault-injection tests should be able to examine:

```text
fail before 1
fail between 1 and 2
fail between 2 and 3
fail between 3 and 4
fail after 4
```

The application should not expose an unintended partially committed state.

Where atomicity cannot be provided, partial completion semantics must be explicit in the contract.

---

# 30. Protocol Design for Automation

Public application interfaces should be suitable for both human-operated tools and automated agents.

Machine-readable output should be considered a primary interface rather than an afterthought.

Prefer:

```text
req validate --json
```

over forcing agents to parse human-oriented console text.

Interfaces should provide:

- stable identifiers;
- structured errors;
- explicit schema versions;
- machine-readable results;
- deterministic commands where practical;
- dry-run operations for consequential changes;
- unambiguous success/failure states.

Human-friendly CLI presentation may be built on top of the same structured result.

---

# 31. Agentic Use Does Not Relax Validation

Agents should be treated as ordinary external clients.

They should not receive privileged database access merely because they automate application behavior.

An agent should normally operate through the same domain contract as:

- the GUI;
- the CLI;
- scripts;
- other integrations.

If an agent proposes an invalid operation, the core should reject it exactly as it would reject an invalid human request.

The architecture should assume that automated clients can:

- make mistakes;
- send stale information;
- repeat commands;
- misunderstand application state;
- generate malformed requests.

The core remains responsible for preserving invariants.

---

# 32. Observability

Failures should be diagnosable without weakening encapsulation.

Important operations should provide sufficient structured information to understand:

- what operation was requested;
- whether validation succeeded;
- which invariant rejected the operation;
- whether persistence was attempted;
- whether a transaction committed;
- whether an adapter failed;
- which contract version was used.

Logging should not substitute for explicit error results.

Logs serve diagnosis and post-mortem analysis.

Contracts serve program behavior.

---

# 33. Dependency Policy

The application should use mature third-party functionality rather than unnecessarily reimplementing solved infrastructure problems.

At the same time, third-party dependencies should be kept away from the domain core when they do not belong there.

A useful asymmetry is:

```text
DOMAIN CORE
-----------
small
deterministic
stable
few dependencies
highly testable


IMPERATIVE SHELL / ADAPTERS
---------------------------
feature-rich
dependency-heavy where justified
technology-specific
replaceable
```

Dependencies should be evaluated according to the architectural role they occupy.

A rich GUI component library is relatively easy to replace if it sits entirely outside the core.

A persistence library whose semantics leak throughout the domain is much more consequential.

---

# 34. Avoid Framework-Dominated Domain Models

Application semantics should not be shaped around framework constraints unless there is a compelling reason.

Avoid letting:

- ORM entities;
- GUI view models;
- serialization objects;
- database rows;
- HTTP request objects;

become the domain model by default.

Translation between representations is acceptable.

For example:

```text
wire DTO
   ↓
validated command
   ↓
domain object
   ↓
persistence representation
```

may involve more explicit code than directly passing one framework object everywhere, but it preserves architectural boundaries and makes assumptions visible.

---

# 35. Prefer Explicit Mapping Over Hidden Magic

Where maintainability and assurance are important, explicit behavior is generally preferred over large amounts of framework-generated implicit behavior.

This does not forbid:

- code generation;
- reflection;
- dependency injection;
- ORMs;
- macros;
- decorators;
- annotation-driven frameworks.

It means their behavior should remain understandable and testable.

Framework convenience should not make it difficult to determine:

```text
what code runs,
when it runs,
what state it changes,
what happens when it fails.
```

---

# 36. Replaceability Should Be Real

An abstraction is not useful merely because two implementations could theoretically satisfy an interface.

Important adapters should actually be replaceable in tests.

If the architecture claims:

```text
Domain -> StoragePort
```

it should be possible to execute the domain/application behavior using:

```text
SQLiteStorage
InMemoryStorage
FaultInjectingStorage
InstrumentedStorage
```

without invasive changes.

If substitution requires reconfiguring large parts of the application, the boundary is not sufficiently clean.

---

# 37. Keep the Domain Independent of Test Doubles

Testability should come from architecture, not from embedding test-specific branches in production logic.

Avoid production code such as:

```text
if test_mode:
    ...
```

when the same result can be achieved through dependency substitution.

The normal runtime implementation and the deliberately defective implementation should satisfy the same architectural boundary.

---

# 38. Version Contracts Deliberately

Interfaces between independently deployed programs should be versioned intentionally.

Compatibility policy should answer questions such as:

- Can an old GUI communicate with a new core?
- Can a new GUI communicate with an old core?
- How are optional fields introduced?
- How are obsolete commands removed?
- How does a client discover supported capabilities?
- What happens when the protocol version is unsupported?

Backward compatibility should not depend on accidental parser tolerance.

---

# 39. Test the Delivered Boundaries

Library-level tests are necessary but insufficient for independently executable applications.

Process-level tests should exercise the actual binaries.

For example:

```text
launch core
    ↓
connect client
    ↓
send protocol request
    ↓
observe result
    ↓
terminate core unexpectedly
    ↓
restart
    ↓
verify persistent consistency
```

This captures problems that do not exist when testing only functions inside one process.

---

# 40. Prefer Determinism

Tests and core behavior should be deterministic whenever determinism is reasonably achievable.

Control sources of nondeterminism such as:

- clocks;
- random numbers;
- iteration ordering;
- temporary paths;
- concurrency;
- process scheduling;
- automatically generated identifiers.

Nondeterminism should be introduced deliberately when testing nondeterministic behavior rather than accidentally contaminating unrelated tests.

A failed test should preferably be reproducible from recorded inputs and fault schedules.

---

# 41. Concurrency Requires Explicit Semantics

Concurrency should not be introduced merely because the language or framework makes asynchronous execution convenient.

Where concurrency exists, specify:

- ownership;
- ordering;
- synchronization;
- cancellation;
- shutdown behavior;
- atomicity;
- stale-state handling;
- conflict resolution.

Concurrency bugs should be attacked with dedicated testing rather than assumed to be covered by conventional integration tests.

---

# 42. Failures Should Be Observable but Contained

A component failure should produce enough information for recovery and diagnosis, while avoiding unnecessary propagation of internal implementation details.

The desired behavior is usually:

```text
fault
  ↓
detected at appropriate boundary
  ↓
converted into defined failure semantics
  ↓
affected operation rejected or degraded
  ↓
unrelated healthy state remains valid
```

Exceptions, panics, and process termination should not serve as routine domain control flow.

---

# 43. Simplicity Is Still a Requirement

Rigorous architecture does not justify needless complexity.

Prefer the simplest mechanism that provides:

- the required contract;
- the required isolation;
- the required observability;
- the required test seam;
- the required failure behavior.

A direct function call is preferable to a framework abstraction when no meaningful boundary exists.

A small explicit adapter is preferable to a generic infrastructure layer when the generic layer obscures behavior.

A relational schema is preferable to introducing a specialized database when relational operations adequately represent the domain.

---

# 44. Decision Heuristic

When making an implementation decision, ask:

1. Where does the authoritative behavior belong?
2. What is the contract at this boundary?
3. Which assumptions are currently implicit?
4. Can the consumer be tested without the real provider?
5. Can the provider be tested against the contract independently?
6. What happens if the provider fails explicitly?
7. What happens if the provider silently behaves incorrectly?
8. Can the fault propagate into healthy components?
9. Can important logic be expressed deterministically?
10. Can the resulting behavior be fuzzed, mutated, or property-tested?
11. Does this abstraction create a meaningful verification boundary?
12. Can the implementation later be replaced without changing domain semantics?
13. Is the added complexity justified by an actual engineering need?

If these questions cannot be answered clearly, the architectural boundary probably requires further work.

---

# 45. Summary

The characteristic architecture is:

```text
             independent clients
       GUI / CLI / agents / scripts
                    │
                    │
          explicit versioned contract
                    │
                    ▼
          ┌───────────────────┐
          │ imperative shell  │
          │                   │
          │ IPC               │
          │ transactions      │
          │ orchestration     │
          └─────────┬─────────┘
                    │
                    ▼
          ┌───────────────────┐
          │ functional core   │
          │                   │
          │ domain semantics  │
          │ validation        │
          │ state transitions │
          └─────────┬─────────┘
                    │
                   ports
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
       SQLite     filesystem   OS / other
       adapter     adapter     adapters
```

The corresponding engineering philosophy is:

> Specify boundaries clearly, keep authoritative logic deterministic where practical, isolate side effects, make components genuinely replaceable, and challenge the system with both expected failures and deliberately non-conformant behavior.

Correct nominal behavior is necessary but insufficient.

A robust implementation should also provide evidence that:

- invalid states are rejected;
- contracts remain enforceable across implementations;
- failure behavior is defined;
- faults are detected at appropriate boundaries;
- corrupted components do not silently contaminate healthy ones;
- persistent operations remain coherent under interruption;
- externally supplied data can be processed defensively;
- the architecture remains testable without requiring the complete deployed system;
- independently implemented clients observe the same authoritative application semantics.

The resulting software is designed not merely to work, but to remain understandable and defensible when its assumptions are actively challenged.