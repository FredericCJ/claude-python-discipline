# Python Testing & Verification — Ground-Truth Manifest

**Scope.** Ground truth for a specification team defining TEST OBLIGATIONS and an integration-test strategy for small-scale Python applications. Tags: ESTABLISHED (stable, documented), VERSION-DEPENDENT (give version), OPEN (unverified). Verified against official docs; secondary reliance flagged inline. Versions current as of June 16, 2026.

## TL;DR
- Adopt pytest 9.1.0 (released 2026-06-13) on Python 3.14.x as the default runner for small Python projects; it gives plain-assert testing, dependency-injected fixtures with five scopes, and parametrization with no boilerplate — VERSION-DEPENDENT. unittest remains the zero-dependency stdlib fallback — ESTABLISHED.
- Specify obligations as observable contracts at seams (Feathers), partition inputs (equivalence classes + boundary values), cover error paths, and prefer fakes implementing the real contract over mocks; use coverage.py 7.x as a diagnostic for untested code, never as a target — ESTABLISHED.
- Use Hypothesis 6.155.x property-based testing for pure-core logic (round-trip, invariant, oracle, metamorphic, stateful) and example-based tests for side-effectful shells; design for testability via dependency injection and Protocol-typed seams (PEP 544) and functional-core/imperative-shell — ESTABLISHED/VERSION-DEPENDENT.

## Key Findings
- **Latest stable versions (mid-2026):** pytest 9.1.0 (2026-06-13); Hypothesis 6.155.2 (2026-06-05); coverage.py 7.14.1 (2026-05-17); Python 3.14.x is the latest stable CPython (3.14.0 released 2025-10-07; 3.14.5 in May 2026), with 3.15 in alpha/beta and 3.16 on main. VERSION-DEPENDENT.
- **pytest fixture scopes are exactly five:** function (default), class, module, package, session. A callable may be passed to `scope` for dynamic scope, but it must return one of those five strings. ESTABLISHED (pytest 9.1.0 docs).
- **Test-double taxonomy (Meszaros/Fowler):** dummy, fake, stub, spy, mock — only mocks insist on behavior verification. ESTABLISHED.
- **Over-mocking hazard is documented:** mocks couple tests to implementation; a fake with a working implementation of the real contract is often preferable. ESTABLISHED (Fowler).
- **Coverage % is a diagnostic, not a target** (Fowler; Goodhart's law framing). ESTABLISHED.

## Details

### 1. Test framework landscape

**pytest (default recommendation for small projects).** pytest 9.1.0 (2026-06-13) is the current stable release; the 9.0.0 major release (2025-11-05) dropped Python 3.9, turned `PytestRemovedIn9Warning` into errors by default, and added native TOML config under `[tool.pytest]`. VERSION-DEPENDENT. pytest lets you use plain `assert` statements with detailed introspection, auto-discovers test modules/functions, and has a large plugin ecosystem — the official pytest documentation homepage describes a "Rich plugin architecture, with over 1300+ external plugins and thriving community." ESTABLISHED (docs.pytest.org; pytest PyPI). (Note: an older SourceForge mirror of the project still cites "more than 850 external plugins" — the higher current figure on the official homepage supersedes it.)

- **Fixtures** are functions decorated with `@pytest.fixture` that provide a fixed baseline and are injected into tests by parameter name (dependency injection). A test (or another fixture) requests a fixture by naming it as a parameter. ESTABLISHED.
- **Fixture scopes (VERIFIED complete set = five).** Per the official "How to use fixtures" page: "Fixtures are created when first requested by a test, and are destroyed based on their `scope`: `function`: the default scope, the fixture is destroyed at the end of the test. `class`: … last test in the class. `module`: … last test in the module. `package`: … last test in the package where the fixture is defined, including sub-packages and sub-directories within it. `session`: … at the end of the test session." A second doc passage confirms: "Possible values for `scope` are: `function`, `class`, `module`, `package` or `session`." Higher-scoped fixtures execute before lower-scoped ones; a callable scope (added in pytest 5.2) must still return one of the five. ESTABLISHED.
- **`@pytest.mark.parametrize`** calls a test function multiple times with different argument sets; e.g. `@parametrize('arg1', [1,2])` yields two calls. Stacking decorators produces the Cartesian product. pytest builds a test ID per parameter set, usable with `-k` and shown by `--collect-only`. ESTABLISHED.
- **Markers** (`@pytest.mark.<name>`) attach metadata to tests, used for selection (`-m`) and plugin behavior. Custom marks should be registered in config (`[pytest] markers = …` / `[tool.pytest.ini_options]`) or via a `pytest_configure` hook; unregistered marks warn, and `--strict-markers` turns unknown marks into errors. Marks apply to tests, not fixtures. ESTABLISHED.
- **conftest.py** provides fixtures, hooks, and plugin config for an entire directory tree without imports; pytest auto-discovers them. ESTABLISHED.
- **Assertion rewriting.** pytest rewrites `assert` statements in test modules at import time (an AST/import-hook transform) to produce detailed failure introspection; it writes cached `.pyc` files. It "only rewrites test modules directly discovered by its test collection process," plus plugin modules; other imported helper modules are not rewritten unless you call `register_assert_rewrite` before importing them. Mode is controlled by `--assert=rewrite` (default) or `--assert=plain`. ESTABLISHED.

**stdlib unittest (zero-dependency fallback).** A test case subclasses `unittest.TestCase`; test methods are named with a `test` prefix. Checks use assertion methods — `assertEqual()`, `assertTrue()`/`assertFalse()`, `assertRaises()` (these "are used instead of the assert statement so the test runner can accumulate all test results and produce a report"). `setUp()`/`tearDown()` run before/after each test method; `setUpClass()`/`tearDownClass()` (classmethods) run once per class; `addCleanup()` registers LIFO cleanups that run even if `setUp` fails. `unittest.main()` provides a CLI. ESTABLISHED (docs.python.org/3/library/unittest.html).

**Sensible default for small projects: pytest.** Rationale (decision): plain-assert syntax with introspection removes `self.assert*` boilerplate; fixtures give composable, scoped dependency injection superior to repeated `setUp`; parametrization and markers are first-class; and pytest can run existing unittest suites unchanged, so adoption is incremental and reversible. Keep unittest where a zero-dependency stdlib-only suite is a hard requirement. Decision-ready.

### 2. The unit–integration boundary (definitional)

- **Unit test (working definition).** A test that exercises a single component in isolation, fast and deterministic, failing only when that component's behavior fails. Michael Feathers' widely cited operational definition states what is NOT a unit test: a test is not a unit test if it talks to a database, communicates across the network, touches the file system, or cannot run without environmental setup. Secondary source: this negative formulation is most often quoted from Feathers and circulated via blog summaries; the canonical source is *Working Effectively with Legacy Code* (2004). FLAGGED secondary.
- **Unit-testable in isolation.** A component is unit-testable when its dependencies can be substituted at a seam so it runs without real infrastructure, and its observable behavior (return values or observable state/effects) can be asserted deterministically.
- **Integration test (working definition).** A test that exercises two or more components together across a real boundary (e.g., real filesystem, real DB, real subprocess), validating that their contract holds when wired together.
- **The seam (Michael Feathers, *Working Effectively with Legacy Code*, 2004 — PRIMARY).** Feathers' definition: "a seam is a place where you can alter behavior in your program without editing in that place," with an associated "enabling point" where the choice between behaviors is made. Feathers catalogs seam types — preprocessor seams, link seams, and object (polymorphic) seams — the last being "pretty much the most useful seams available in object-oriented programming languages." The seam determines the boundary: where you can substitute a double or a real collaborator is exactly where the unit/integration line can be drawn. ESTABLISHED (primary; quotes corroborated via InformIT excerpt of the book chapter — FLAGGED that the book text was read via the publisher's posted chapter excerpt, not the print book).

(Strategy — which seams to cut and where to draw the line — belongs to the team; the definitions above are the analyst's.)

### 3. Test doubles, precisely

**Taxonomy (Gerard Meszaros, *xUnit Test Patterns*, popularized by Martin Fowler, "Mocks Aren't Stubs" / "Test Double" — PRIMARY).** "Test Double" is the generic term (after "stunt double"). Fowler, summarizing Meszaros:
- **Dummy** — objects passed around but never actually used; usually just fill parameter lists.
- **Fake** — has a working implementation, but takes a shortcut unsuitable for production (an in-memory database is the canonical example).
- **Stub** — provides canned answers to calls made during the test, not responding outside what's programmed.
- **Spy** — a stub that also records information about how it was called (e.g., how many messages were "sent").
- **Mock** — pre-programmed with expectations forming a specification of the calls it expects; verifies those calls.
Key distinction: "only mocks insist upon behavior verification"; stubs use state verification (or either). ESTABLISHED.

**unittest.mock (VERIFIED against docs.python.org/3/library/unittest.mock.html).**
- **`Mock`** — flexible mock object; callable; auto-creates attributes/methods as they are accessed; records usage so you can assert on calls (`assert_called_with`, `assert_called_once_with`, etc.). ESTABLISHED.
- **`MagicMock`** — a `Mock` subclass with magic (dunder) methods pre-created and ready to use. ESTABLISHED.
- **`patch()`** — decorator/context manager that temporarily replaces a target (module/class attribute) with a mock for the scope of a test, restoring it afterward; `new_callable` controls the replacement class (AsyncMock for async functions, MagicMock otherwise by default). ESTABLISHED.
- **`spec` / `spec_set`** — constrain a mock's interface to a real object's attributes; `spec_set` additionally forbids setting attributes that don't exist on the spec. ESTABLISHED.
- **`autospec` / `create_autospec()`** — "Auto-speccing creates mock objects that have the same attributes and methods as the objects they are replacing, and any functions and methods (including constructors) have the same call signature as the real object." Calling with the wrong signature raises `TypeError`. Use via `patch(..., autospec=True)` or `create_autospec(obj, spec_set=True, instance=True)`. ESTABLISHED.

**Over-mocking hazard (documented).** Fowler notes mocks (behavior verification) make tests "tightly coupled to implementation, which makes them very fragile"; he and others recommend stubs/fakes where possible and reserving mocks for genuine command-style interactions. A fake that implements the real contract (e.g., an in-memory repository) tests behavior against the actual interface and survives refactors, whereas a forest of `autospec=False` mocks can pass while the real integration is broken. Decision: prefer fakes-implementing-the-contract; use `autospec`/`spec_set` whenever you must mock, to prevent silent drift when the real API changes. ESTABLISHED (Fowler — PRIMARY).

### 4. Property-based testing (Hypothesis)

**Library identity (VERIFIED).** Hypothesis is "the property-based testing library for Python," maintained by the HypothesisWorks organization; PyPI lists authors David R. MacIver and Zac Hatfield-Dodds, with maintainers including DRMacIver, tybug, and Zac-HD; license MPL-2.0; docs at hypothesis.readthedocs.io. Latest version 6.155.2 (2026-06-05), requires Python ≥3.10. VERSION-DEPENDENT.

- **What it generates / strategies.** You write a test that should pass for all inputs in a described range and let Hypothesis choose inputs, including edge cases. The described range is a **strategy** (e.g., `st.integers()`, `st.lists(st.integers())`, `st.text()`); strategies are composable and can be built with `@st.composite` and adapted with `.filter()` / `assume()`. ESTABLISHED.
- **`@given`** is "the standard entrypoint"; it takes strategies and supplies generated arguments to the test. Default is 100 examples per test, controllable via the `max_examples` setting. ESTABLISHED.
- **Shrinking.** "When Hypothesis does find a bug, it doesn't just report any failing example — it reports the simplest possible one," reducing complex failing inputs to a minimal counterexample. ESTABLISHED.
- **Stateful / rule-based testing.** `hypothesis.stateful.RuleBasedStateMachine` plus `@rule`, `@initialize`, `@precondition`, `@invariant`, and `Bundle` let Hypothesis generate sequences of operations and shrink failing sequences. `@rule` defines actions (args drawn from strategies); `Bundle` passes values between rules; `@invariant()` runs after every rule; `@precondition` gates rules. Default `stateful_step_count` is 50. ESTABLISHED.
- **Property classes it fits:**
  - **Round-trip:** `decode(encode(x)) == x` (serializers/parsers). 
  - **Invariant:** a property that must always hold (e.g., `sorted(xs)` is ordered and same length/multiset as `xs`). 
  - **Oracle (differential):** compare against a trusted reference implementation (`my_sort(xs) == sorted(xs)`). 
  - **Metamorphic:** relate outputs of related inputs without a full oracle (e.g., filtering a search result set must yield a subset). Metamorphic testing addresses the "test oracle problem" and was invented by Tsong Yueh Chen, S.C. Cheung, and S.M. Yiu in "Metamorphic Testing: A New Approach for Generating Next Test Cases," Technical Report HKUST-CS98-01, Department of Computer Science, The Hong Kong University of Science and Technology, 1998 (primary report). ESTABLISHED.
- **When example-based tests are better.** Property-based testing fits pure functions, data transforms, parsers, serializers, and algorithms; it is weaker for code that is mostly side effects (sending email, writing to a DB), for GUI flows, and where the "right" output is hard to define without rebuilding the function. Use targeted example-based tests there. FLAGGED secondary (botmonster blog) for the "when to prefer examples" framing; consistent with Hypothesis docs guidance to start with simple properties.

### 5. Specifying obligations vs. writing tests

A **test obligation** names what must be verified, not how. Express each obligation as:
1. **Observable contract under test** — the externally visible behavior at a named seam: return value, raised exception, or observable state/effect. (Do not specify internal calls unless the contract is the interaction itself.)
2. **Input partitioning** — divide the input domain into **equivalence classes** (sets expected to be handled identically) and pick representatives; apply **boundary-value analysis** at the edges of each class (min, min±1, max, max±1, empty, zero, overflow). 
3. **Expected observable** — the asserted result for each partition/boundary, stated as a checkable predicate.
4. **Error-path coverage** — obligations for invalid inputs and failure modes: which exception type, which message/contract, which cleanup/rollback must occur. 

**Coverage tooling (coverage.py — VERIFIED at coverage.readthedocs.io).** coverage.py 7.14.1 (2026-05-17) measures line and branch coverage using the stdlib trace/analysis hooks; supports Python 3.10 through 3.15 beta (incl. free-threading) and PyPy3 3.10–3.11. Run via `coverage run`, report via `coverage report -m` (shows missing lines) or `coverage html`. On Python 3.14+ the "sysmon" measurement core is the default where supported. The maintainer (Ned Batchelder, since 2004) notes pytest users often use the `pytest-cov` plugin "but for most purposes, it is unnecessary." VERSION-DEPENDENT.

**Coverage % is a diagnostic, not a target (Martin Fowler, "TestCoverage" — PRIMARY).** Fowler: "Test coverage is a useful tool for finding untested parts of a codebase. Test coverage is of little use as a numeric statement of how good your tests are." He warns: "If you make a certain level of coverage a target, people will try to attain it. The trouble is that high coverage numbers are too easy to reach with low quality testing" (citing assertion-free testing), and expects "a coverage percentage in the upper 80s or 90s" from thoughtful testing while being "suspicious of anything like 100%." This is a textbook instance of **Goodhart's law** — when a measure becomes a target it ceases to be a good measure. Use coverage to find untested code; set obligations on behaviors, not on a percentage. ESTABLISHED.

### 6. Integration-test strategy primitives

- **Contract testing at component boundaries.** At each seam, define the contract (inputs, outputs, side effects, error behavior) and test that both sides honor it. A fake used in unit tests and the real implementation in integration tests should satisfy the *same* contract test suite, so the fake cannot drift from reality. ESTABLISHED (principle; consistent with Fowler/Feathers).
- **Fakes / test harnesses for external systems:**
  - **Filesystem** — use `tmp_path` (see below) instead of touching real paths.
  - **Clock** — inject a clock dependency or use `monkeypatch.setattr` to substitute `datetime`/time sources; do not call real wall-clock in core logic.
  - **Network** — substitute a fake client or block network (e.g., `monkeypatch.setattr` raising on `urllib.request.urlopen`); reserve real network for explicitly-marked integration tests.
  - **Subprocess** — wrap process invocation behind a seam and substitute a fake in unit tests.
- **Host-side testing.** Run logic in-process against fakes/harnesses on the developer/CI host; reserve real external systems for a smaller, marked integration layer. This mirrors Gary Bernhardt's formulation, stated verbatim as "Functional core — Many fast unit tests. Imperative shell — Few integration tests" (from his SCNA 2012 talk "Boundaries").
- **pytest-provided isolation (VERIFIED against official pytest docs):**
  - **`tmp_path`** — "Provide a `pathlib.Path` object to a temporary directory which is unique to each test function." Function-scoped. ESTABLISHED.
  - **`tmp_path_factory`** — "Make session-scoped temporary directories and return `pathlib.Path` objects"; its `mktemp()` creates multiple dirs; use it for session-scoped temp resources. ESTABLISHED.
  - **`tmp_path` vs older `tmpdir`** — `tmpdir` returns a legacy `py.path.local` object and is superseded: the docs state "These days, it is preferred to use `tmp_path`." `tmpdir`/`tmpdir_factory` remain for backward compatibility. ESTABLISHED.
  - **`monkeypatch`** — "Temporarily modify classes, functions, dictionaries, `os.environ`, and other objects"; methods include `setattr`, `delattr`, `setitem`, `delitem`, `setenv`, `delenv`, `syspath_prepend`, `chdir`, `context`. "All modifications will be undone after the requesting test function or fixture has finished." ESTABLISHED.
  - **`capsys`** — captures text written to `sys.stdout`/`sys.stderr`; `capsys.readouterr()` returns an `(out, err)` namedtuple. (Variants: `capsysbinary`, `capfd`, `capfdbinary`.) ESTABLISHED.
- **Treat fixtures and test data as version-controlled code.** Fixtures, conftest.py, and test data files live in the repo, are reviewed, and evolve with the contract; do not generate them ad hoc outside version control. ESTABLISHED (principle).

### 7. Testability design patterns (verification-relevant facts)

- **Dependency injection in Python.** Pass collaborators in via the constructor or as function/method parameters rather than constructing them internally; this creates an object (polymorphic) seam where a fake/stub can be substituted. pytest fixtures are themselves a DI mechanism (a test declares a needed fixture as a parameter; the framework supplies it). ESTABLISHED.
- **Protocol-typed dependencies (typing.Protocol / PEP 544 — PRIMARY).** PEP 544 (accepted; available since Python 3.8) specifies **structural subtyping** ("static duck typing"): "Protocols are defined by including … `typing.Protocol` in the base classes list." Any class with matching members is a structural subtype without explicit inheritance, so a production implementation and a test fake both satisfy the same `Protocol` and are type-checked at the seam. "At runtime, protocol classes will be simple ABCs"; `@runtime_checkable` adds `isinstance()` support but "only checks that all protocol members exist, not that they have the correct type," and signatures are not checked at runtime. ESTABLISHED/VERSION-DEPENDENT (3.8+).
- **Functional core, imperative shell (Gary Bernhardt — PRIMARY for the phrasing).** The phrasing originates in Gary Bernhardt's talk "Boundaries" (SCNA 2012); per the talk page, "The 'Functional Core, Imperative Shell' screencast mentioned at the end is available as part of season 4 of the DAS catalog." Pattern: push decision logic into a pure, side-effect-free **functional core** (testable with many fast, isolated unit tests, no doubles needed), and confine I/O and mutation to a thin **imperative shell** (few conditionals, exercised by a small number of integration tests). ESTABLISHED (primary attribution; talk hosted at destroyallsoftware.com — FLAGGED that the screencast itself is paywalled, so content is corroborated via Bernhardt's published talk page and secondary summaries).

(Tooling supports these patterns — DI via plain Python and fixtures, contracts via Protocol, isolation via pure functions. Which architecture to adopt is the team's strategy decision.)

### 8. Open questions and version caveats

- **VERSION-DEPENDENT:** pytest 9.1.0 (2026-06-13); the PyPI project page briefly lagged showing 9.0.3 (2026-04-07) as "Latest release" while the changelog already published 9.1.0 — treat the changelog as canonical. pytest 9.0.0 (2025-11-05) was a breaking major release (dropped Python 3.9; `PytestRemovedIn9Warning` → errors; native TOML config).
- **VERSION-DEPENDENT:** Hypothesis 6.155.2 (2026-06-05); coverage.py 7.14.1 (2026-05-17); Python 3.14.x latest stable (3.14.0 2025-10-07; 3.14.5 ~2026-05-10), 3.15 in pre-release, 3.16 on main.
- **VERSION-DEPENDENT:** coverage.py defaults to the "sysmon" core on Python 3.14+ where supported; plugins and dynamic contexts are not supported with sysmon.
- **VERSION-DEPENDENT:** `typing.Protocol` requires Python 3.8+; `@runtime_checkable` runtime checks verify member existence only (not signatures/types).
- **OPEN:** The exact print-page numbers and wording in Feathers' *Working Effectively with Legacy Code* were read via a publisher chapter excerpt (InformIT) and reputable secondary notes, not the physical book; verify against the book if exact pagination is required.
- **OPEN:** Bernhardt's "Functional Core, Imperative Shell" screencast content is paywalled; the attribution and summary rest on his public "Boundaries" talk page plus secondary write-ups.
- **OPEN:** Claims that "pytest 8.x is the current major line in 2026" appear in 2026 blog posts and are outdated/incorrect relative to the official changelog (9.x); do not rely on them.
- **OPEN:** The "over 1300+ external plugins" figure is the current official homepage claim; it is a moving number and conflicts with older mirrors citing "more than 850" — treat as approximate and re-verify if a precise count matters.

## Recommendations
1. **Baseline now (stage 1).** Pin pytest 9.1.x, coverage.py 7.14.x, Hypothesis 6.155.x on Python 3.14.x; put config in `pyproject.toml` (`[tool.pytest.ini_options]` or the new `[tool.pytest]` TOML table); register all custom markers and enable `--strict-markers`. Benchmark to revisit: when Python 3.15 reaches stable (final 3.15.0) or pytest issues another major (10.x), re-validate.
2. **Specify obligations, not tests (stage 2).** For each component, document: the seam, the observable contract, equivalence classes + boundary values, expected observables, and explicit error-path obligations. Require that every obligation maps to at least one assertion; forbid assertion-free tests.
3. **Choose doubles deliberately (stage 3).** Default to fakes implementing the contract; when mocking, require `autospec=True` or `spec_set=True`. Write one contract test suite run against both the fake and the real implementation. Threshold to change: if mock-heavy tests break on refactors without behavior changes, migrate those collaborators to fakes or Protocol-typed seams.
4. **Add property-based tests for the core (stage 4).** Apply Hypothesis to pure functions/parsers/serializers (round-trip, invariant, oracle, metamorphic) and `RuleBasedStateMachine` to stateful components; keep example-based tests for side-effectful shells.
5. **Use coverage as a flashlight (ongoing).** Run coverage to locate untested branches and error paths; do NOT set a numeric gate as the goal. If a percentage gate is mandated externally, pair it with a ban on assertion-free tests and review the *missing* lines, treating upper-80s/90s as a smell-check range, not a target.
6. **Architect for isolation (ongoing).** Adopt functional-core/imperative-shell and constructor/Protocol-typed DI so most logic is unit-testable without doubles and the integration layer stays small.

## Caveats
- All version facts are time-stamped to June 16, 2026 and will drift; re-verify against PyPI and official changelogs before adoption. The pytest PyPI page/changelog lag noted above is a live example of source disagreement — prefer the changelog.
- Definitions in §2 are deliberately analyst-side; the team owns the strategy (which seams to cut, where to draw the unit/integration line, target test mix).
- Primary-source reliance is noted per claim; secondary reliance is FLAGGED for: the Feathers "not a unit test" list and book pagination, the Bernhardt screencast content, the plugin-count figure, and the "when example-based is better" framing.

## Sources (accessed 2026-06-16)
- pytest documentation — fixtures, scopes, parametrize, markers, conftest, assertion rewriting, builtin fixtures (tmp_path, tmp_path_factory, tmpdir, monkeypatch, capsys), changelog, homepage plugin count. docs.pytest.org/en/stable/ (how-to/fixtures.html, reference/fixtures.html, how-to/mark.html, how-to/parametrize.html, how-to/assert.html, builtin.html, changelog.html); pytest on PyPI (pypi.org/project/pytest/) — pytest 9.1.0 (2026-06-13), 9.0.0 (2025-11-05).
- Python standard library docs — unittest (docs.python.org/3/library/unittest.html) and unittest.mock (docs.python.org/3/library/unittest.mock.html).
- Python release information — What's New in Python 3.14 (docs.python.org/3/whatsnew/3.14.html); PEP 745 (3.14 schedule); python.org downloads/release pages; devguide.python.org/versions.
- Hypothesis — hypothesis.readthedocs.io (index, quickstart, stateful, settings/API reference); Hypothesis on PyPI (pypi.org/project/hypothesis/) — 6.155.2 (2026-06-05); github.com/HypothesisWorks/hypothesis.
- coverage.py — coverage.readthedocs.io (homepage, change history) — 7.14.1 (2026-05-17); coverage on PyPI; github.com/coveragepy/coveragepy.
- Martin Fowler — "Mocks Aren't Stubs" and "Test Double" (martinfowler.com/articles/mocksArentStubs.html, /bliki/TestDouble.html); "Test Coverage" (martinfowler.com/bliki/TestCoverage.html); "Legacy Seam" (martinfowler.com/bliki/LegacySeam.html).
- Gerard Meszaros — *xUnit Test Patterns* taxonomy (via Fowler's articles, primary summaries).
- Michael Feathers — *Working Effectively with Legacy Code* (2004); seam definition and seam types via InformIT chapter excerpt (informit.com/articles/article.aspx?p=359417) and Feathers interview (InfoQ) — FLAGGED chapter-excerpt/secondary for book pagination.
- typing.Protocol / PEP 544 — peps.python.org/pep-0544/; typing.python.org/en/latest/spec/protocol.html; mypy.readthedocs.io/en/stable/protocols.html.
- Gary Bernhardt — "Boundaries" (SCNA 2012), destroyallsoftware.com/talks/boundaries (functional core / imperative shell phrasing and unit-vs-integration split).
- Metamorphic testing — Chen, Cheung, Yiu, "Metamorphic Testing: A New Approach for Generating Next Test Cases," Tech. Report HKUST-CS98-01, HKUST, 1998 (primary report).