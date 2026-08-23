"""Validate local boundary representation and conformance evidence.

``contract-conformance.json`` joins each internal contract in the canonical
architecture model to its Python boundary type, implementations, one shared
suite, and term-level evidence. The registry describes semantic roles and test
capabilities; it does not require files or classes named real, fake, or faulty.

This checker decides structural completeness and representation form. The
project gate separately executes the declared suites and strict type witnesses;
file presence and source spelling are not presented as behavioral conformance.
"""

from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import TYPE_CHECKING, Final, Never

from . import Check, Finding
from .architecture_model import ArchitectureError, Contract
from .architecture_model import parse as parse_architecture

# Import collection protocols only for static annotations.
if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable identifiers shared by contracts, implementations, and operations.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Importable Python module names.
MODULE_NAME: Final = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
## Importable Python symbols.
SYMBOL_NAME: Final = re.compile(r"^[A-Za-z_]\w*$")
## Unordered representation-name set whose each element is supported by the v5 boundary model.
REPRESENTATIONS: Final = frozenset({"structural", "nominal"})
## Unordered implementation-role set whose each element separates production from test behavior.
IMPLEMENTATION_KINDS: Final = frozenset({"real", "test"})
## Unordered capability-name set whose each element satisfies part of ARCH-025.
CAPABILITIES: Final = frozenset({"controllable", "scheduled_fault"})
## Unordered term-name set whose each element is inherited by every architecture operation.
TERM_KINDS: Final = frozenset({
    "success",
    "error",
    "ordering",
    "idempotency",
    "concurrency",
    "timeout",
})
## Unordered term-name set whose each element may truthfully be declared non-applicable.
OPTIONAL_TEST_TERMS: Final = frozenset({"ordering", "idempotency", "concurrency", "timeout"})


class ConformanceError(ValueError):
    """One stable contract-conformance diagnostic."""

    ## Stable diagnostic namespace for rejected conformance-registry propositions.
    code = "discipline.contract_conformance.invalid"

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one registry failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail actionable explanation
        """
        # Initialize the standard message from the stable id, JSON location, and detail.
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        # Retain the mechanism diagnostic for deterministic rule selection.
        self.diagnostic_id = diagnostic_id
        # Retain the exact model or repository location that failed validation.
        self.where = where
        # Retain the actionable schema or semantic explanation.
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise a registry diagnostic without duplicating exception mechanics.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail actionable explanation
    @return never; this helper always raises
    @throws ConformanceError unconditionally
    """
    # Translate the localized failure into the sole typed conformance-error channel.
    raise ConformanceError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require one JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return mapping whose each key is a field name and each value is decoded data;
        source order is preserved by the decoder
    """
    # Only a JSON object can supply named conformance fields.
    if not isinstance(value, dict):
        # Reject scalar and array impostors without coercion.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected an object")
    # Return the decoded key/value mapping with source order intact.
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject absent and ignored fields.

    @param record mapping whose each key names a field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param fields unordered field-name set whose each element is required and accepted
    @param where JSON path
    @throws ConformanceError when the field set differs
    """
    # Build an unordered set whose each element is a required field absent from the record.
    missing = fields - set(record)
    # Build an unordered set whose each element is an unrecognized record field.
    unknown = set(record) - fields
    # Missing and unknown fields both make the closed schema unsafe to interpret.
    if missing or unknown:
        # Reject the exact object before any partial field interpretation.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            where,
            f"missing={sorted(missing)}, unknown={sorted(unknown)}",
        )


def _text(value: object, where: str) -> str:
    """Require a non-empty string.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text
    """
    # Require authored non-empty text rather than coercing scalar values.
    if not isinstance(value, str) or not value.strip():
        # Reject at the exact JSON path owning the contentless value.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected non-empty text")
    # Return normalized text with insignificant surrounding whitespace removed.
    return value.strip()


def _optional_text(value: object, where: str) -> str | None:
    """Require null or a non-empty string.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text or None
    """
    # Preserve explicit absence; otherwise apply the ordinary text contract.
    return None if value is None else _text(value, where)


def _identifier(value: object, where: str) -> str:
    """Require a stable lower-snake identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identifier
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Stable registry identifiers use one complete lower-snake lexical shape.
    if IDENTIFIER.fullmatch(text) is None:
        # Reject invalid spelling at the exact field path.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected lower_snake identifier")
    # Return the validated stable identifier.
    return text


def _module(value: object, where: str) -> str:
    """Require a dotted Python module name.

    @param value untrusted decoded value
    @param where JSON path
    @return validated module name
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Import modules must comprise valid dotted Python identifiers.
    if MODULE_NAME.fullmatch(text) is None:
        # Reject invalid spelling rather than deferring to an import failure.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected dotted Python module")
    # Return the validated import-module spelling.
    return text


def _symbol(value: object, where: str) -> str:
    """Require a Python identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated symbol
    """
    # Parse and normalize the raw value as non-empty text first.
    text = _text(value, where)
    # Boundary and implementation symbols must be importable identifiers.
    if SYMBOL_NAME.fullmatch(text) is None:
        # Reject invalid spelling rather than accepting an expression.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected Python symbol")
    # Return the validated symbol spelling.
    return text


def _records(value: object, where: str, *, allow_empty: bool = False) -> list[Mapping[str, object]]:
    """Require an array of JSON objects.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when an explicit empty registry is valid; false when non-empty
    @return decoded mapping-record elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one record element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected a non-empty record array")
    # Parse each indexed object element while preserving authored source order.
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique array of strings.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty true when no values is meaningful; false when at least one is required
    @return unique string elements in source order
    """
    # Require an array and, unless explicitly permitted, at least one string element.
    if not isinstance(value, list) or (not value and not allow_empty):
        # Reject absent, scalar, and disallowed empty values at the exact path.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected a string array")
    # Parse each indexed string element while preserving authored source order.
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    # Duplicate values would make capability and identifier membership ambiguous.
    if len(values) != len(set(values)):
        # Reject the whole array because no duplicate has distinct semantics.
        _fail("CONTRACT001_MODEL_SCHEMA", where, "duplicate values are not allowed")
    # Return the validated unique sequence in authored order.
    return values


@dataclass(frozen=True, slots=True)
class Implementation:
    """One real or test implementation registered against a boundary."""

    ## Stable local implementation identifier.
    implementation_id: str
    ## Import module defining the implementation class.
    module: str
    ## Class symbol inside the implementation module.
    symbol: str
    ## Real or test implementation role.
    kind: str
    ## Capability-name elements in authored order, explicitly possibly empty.
    capabilities: tuple[str, ...]
    ## Parameter id under which the shared suite executes it.
    parameter: str


@dataclass(frozen=True, slots=True)
class TermEvidence:
    """One contract term traced to a test or explicit non-applicability."""

    ## Architecture operation identifier.
    operation: str
    ## Success, one error, or a named interaction semantic.
    term: str
    ## Error variant for an error term, otherwise None.
    error: str | None
    ## Exact local pytest node, otherwise None.
    test: str | None
    ## Rationale when a semantic term has no applicable assertion.
    not_applicable: str | None


@dataclass(frozen=True, slots=True)
class ContractEvidence:
    """Representation, implementations, and behavioral evidence for one contract."""

    ## Architecture contract identifier.
    contract_id: str
    ## Module declaring the boundary type.
    module: str
    ## Boundary class or protocol symbol.
    symbol: str
    ## Structural or nominal conformance decision.
    representation: str
    ## Real and test implementation-record elements in authored order.
    implementations: tuple[Implementation, ...]
    ## One suite executed unchanged across registered parameters.
    suite: str
    ## Operation-term trace-record elements in authored order.
    evidence: tuple[TermEvidence, ...]


@dataclass(frozen=True, slots=True)
class ConformanceModel:
    """The complete local conformance registry."""

    ## Internal contract-evidence elements in authored order, possibly empty when justified.
    contracts: tuple[ContractEvidence, ...]
    ## Explanation when this repository has no internal boundary contract.
    contract_absence: str | None


def _implementation(record: Mapping[str, object], where: str) -> Implementation:
    """Parse one implementation record.

    @param record mapping whose each key names an implementation field and each value is
        decoded data; mapping iteration order is deliberately unused
    @param where JSON path
    @return typed implementation
    """
    # Close the implementation schema before interpreting any semantic field.
    _exact(record, {"id", "module", "symbol", "kind", "capabilities", "parameter"}, where)
    # Parse the declared production-or-test implementation role.
    kind = _text(record["kind"], f"{where}.kind")
    # Only roles understood by the shared-suite policy are admissible.
    if kind not in IMPLEMENTATION_KINDS:
        # Reject an unknown role instead of silently weakening coverage obligations.
        _fail("CONTRACT001_MODEL_SCHEMA", f"{where}.kind", "expected real or test")
    # Parse capability-name elements in authored order, allowing an explicit empty set.
    capabilities = _strings(record["capabilities"], f"{where}.capabilities", allow_empty=True)
    # Build an unordered set whose each element is an unrecognized capability.
    unknown = set(capabilities) - CAPABILITIES
    # Unknown capabilities cannot satisfy any defined test obligation.
    if unknown:
        # Render the unknown set in deterministic lexical order.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            f"{where}.capabilities",
            f"unknown capabilities {sorted(unknown)}",
        )
    # Materialize the fully validated implementation record.
    return Implementation(
        implementation_id=_identifier(record["id"], f"{where}.id"),
        module=_module(record["module"], f"{where}.module"),
        symbol=_symbol(record["symbol"], f"{where}.symbol"),
        kind=kind,
        capabilities=capabilities,
        parameter=_text(record["parameter"], f"{where}.parameter"),
    )


def _term_evidence(record: Mapping[str, object], where: str) -> TermEvidence:
    """Parse one term-to-test trace.

    @param record mapping whose each key names a trace field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed evidence record
    """
    # Close the trace schema before interpreting mutually dependent fields.
    _exact(record, {"operation", "term", "error", "test", "not_applicable"}, where)
    # Parse the observable contract-term category.
    term = _text(record["term"], f"{where}.term")
    # Every trace must use one term inherited from the architecture operation.
    if term not in TERM_KINDS:
        # Reject unknown terms rather than accepting unverified vocabulary.
        _fail("CONTRACT001_MODEL_SCHEMA", f"{where}.term", "unknown contract term")
    # Parse an optional error-variant name for error terms.
    error = _optional_text(record["error"], f"{where}.error")
    # Parse an optional exact pytest node as executable evidence.
    test = _optional_text(record["test"], f"{where}.test")
    # Parse an optional rationale for a legitimately inapplicable interaction semantic.
    not_applicable = _optional_text(
        record["not_applicable"],
        f"{where}.not_applicable",
    )
    # Exactly one evidence disposition must explain every operation term.
    if (test is None) == (not_applicable is None):
        # Reject both omission and contradictory dual disposition.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            where,
            "exactly one of test and not_applicable must be non-null",
        )
    # Error variants belong only to error terms and are mandatory for those terms.
    if (term == "error") != (error is not None):
        # Reject a malformed operation-term key before architecture joining.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            f"{where}.error",
            "error is required only for an error term",
        )
    # Success and declared errors always require executable behavioral evidence.
    if not_applicable is not None and term not in OPTIONAL_TEST_TERMS:
        # Prevent prose from replacing tests for mandatory behavior.
        _fail(
            "CONTRACT005_TERM_TRACE",
            where,
            "success and declared errors require executable test evidence",
        )
    # Materialize the validated exclusive test-or-rationale trace.
    return TermEvidence(
        operation=_identifier(record["operation"], f"{where}.operation"),
        term=term,
        error=error,
        test=test,
        not_applicable=not_applicable,
    )


def _contract(record: Mapping[str, object], where: str) -> ContractEvidence:
    """Parse one contract evidence record.

    @param record mapping whose each key names a contract field and each value is decoded data;
        mapping iteration order is deliberately unused
    @param where JSON path
    @return typed contract evidence
    """
    # Define the unordered field-name set whose each element is required and accepted.
    fields = {
        "id",
        "module",
        "symbol",
        "representation",
        "implementations",
        "suite",
        "evidence",
    }
    # Close the contract schema before interpreting any nested registry.
    _exact(record, fields, where)
    # Parse the declared boundary-representation decision.
    representation = _text(record["representation"], f"{where}.representation")
    # Only the two mechanically distinguishable representation forms are supported.
    if representation not in REPRESENTATIONS:
        # Reject undefined representation vocabulary at its exact field path.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            f"{where}.representation",
            "expected structural or nominal",
        )
    # Parse each implementation-record element in authored order.
    implementations = tuple(
        _implementation(item, f"{where}.implementations[{index}]")
        for index, item in enumerate(
            _records(record["implementations"], f"{where}.implementations")
        )
    )
    # Collect each implementation identifier in authored order for uniqueness checking.
    identifiers = [item.implementation_id for item in implementations]
    # Collect each suite parameter identifier in the corresponding authored order.
    parameters = [item.parameter for item in implementations]
    # Neither registry identity nor suite selection may alias two implementations.
    if len(identifiers) != len(set(identifiers)) or len(parameters) != len(set(parameters)):
        # Reject the containing contract because either collision is ambiguous.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            where,
            "implementation ids and suite parameter ids must each be unique",
        )
    # Parse each operation-term evidence element in authored order.
    evidence = tuple(
        _term_evidence(item, f"{where}.evidence[{index}]")
        for index, item in enumerate(_records(record["evidence"], f"{where}.evidence"))
    )
    # Materialize the complete validated contract-evidence record.
    return ContractEvidence(
        contract_id=_identifier(record["id"], f"{where}.id"),
        module=_module(record["module"], f"{where}.module"),
        symbol=_symbol(record["symbol"], f"{where}.symbol"),
        representation=representation,
        implementations=implementations,
        suite=_text(record["suite"], f"{where}.suite"),
        evidence=evidence,
    )


def parse(path: Path) -> ConformanceModel:
    """Parse one exact local conformance registry.

    @param path registry JSON path
    @return typed model
    @throws ConformanceError when syntax or fields are invalid

    @par Effects
    Reads the registry file at ``path`` once before validating the decoded snapshot.
    """
    # Read and decode one immutable registry snapshot before semantic validation.
    try:
        # Decode the file snapshot into an untrusted JSON value.
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    # Translate filesystem, encoding, and JSON failures into the model error channel.
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        # Preserve the path and parser detail in a stable schema diagnostic.
        _fail("CONTRACT001_MODEL_SCHEMA", str(path), str(problem))
    # Require the decoded root to be a JSON object with a closed schema.
    root = _object(raw, "$")
    _exact(root, {"schema_version", "contracts", "contract_absence"}, "$")
    # Reject incompatible schema versions before interpreting their records.
    if root["schema_version"] != 1:
        # State the sole supported schema version at the canonical location.
        _fail("CONTRACT001_MODEL_SCHEMA", "$.schema_version", "expected 1")
    # Parse each contract-evidence element in authored order, allowing a justified empty view.
    contracts = tuple(
        _contract(item, f"$.contracts[{index}]")
        for index, item in enumerate(_records(root["contracts"], "$.contracts", allow_empty=True))
    )
    # Collect each contract identifier in authored order for uniqueness checking.
    identifiers = [item.contract_id for item in contracts]
    # A duplicate contract identity would make architecture joining ambiguous.
    if len(identifiers) != len(set(identifiers)):
        # Reject the complete registry rather than selecting one duplicate.
        _fail("CONTRACT001_MODEL_SCHEMA", "$.contracts", "contract ids must be unique")
    # Parse the optional explanation for an empty internal-contract view.
    absence = _optional_text(root["contract_absence"], "$.contract_absence")
    # Evidence and an absence rationale are mutually exclusive propositions.
    if contracts and absence is not None:
        # Reject the contradictory absence claim when contract evidence exists.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            "$.contract_absence",
            "must be null when contract evidence exists",
        )
    # An empty registry must explicitly explain why no local internal boundary exists.
    if not contracts and absence is None:
        # Reject unexplained absence rather than treating omission as a design decision.
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            "$.contract_absence",
            "explain why this repository has no internal boundary contract",
        )
    # Return the mutually consistent complete conformance model.
    return ConformanceModel(contracts=contracts, contract_absence=absence)


def _local_path(root: Path, spelling: str, diagnostic_id: str) -> Path:
    """Resolve one model path while enforcing the repository boundary.

    @param root governed repository root
    @param spelling POSIX repository-relative path, optionally with a pytest node suffix
    @param diagnostic_id diagnostic to raise for an unsafe or absent path
    @return existing confined file path
    """
    # Remove an optional pytest-node suffix before resolving the owning file.
    file_part = spelling.split("::", 1)[0]
    # Normalize accepted separators into one repository-relative POSIX spelling.
    relative = PurePosixPath(file_part.replace("\\", "/"))
    # Reject absolute, drive-qualified, and parent-traversing declarations lexically.
    if relative.is_absolute() or PureWindowsPath(file_part).drive or ".." in relative.parts:
        # Report the caller-selected diagnostic at the unsafe authored spelling.
        _fail(diagnostic_id, spelling, "path must stay inside the governed repository")
    # Resolve symlinks and normalization against the governed repository root.
    candidate = (root / Path(relative.as_posix())).resolve()
    # Prove confinement again after filesystem resolution.
    try:
        candidate.relative_to(root.resolve())
    # Translate an escaped resolved path into the caller's diagnostic namespace.
    except ValueError:
        # Reject symlink and normalization escapes at their authored spelling.
        _fail(diagnostic_id, spelling, "resolved path leaves the governed repository")
    # Evidence must name an existing regular file rather than a directory or future artifact.
    if not candidate.is_file():
        # Reject absent evidence at validation time.
        _fail(diagnostic_id, spelling, "declared test file does not exist")
    # Return the confined existing evidence path.
    return candidate


def _module_path(module: str, source_roots: Sequence[Path]) -> Path:
    """Resolve a declared module from this repository's complete source roots.

    @param module dotted absolute module
    @param source_roots local import-root elements in declared precedence order
    @return unique source module path
    """
    # Convert the dotted module into a relative import path.
    relative = Path(*module.split("."))
    # Collect each existing module-file candidate in source-root then module-form order.
    candidates = [
        candidate
        for source_root in source_roots
        for candidate in (
            source_root / relative.with_suffix(".py"),
            source_root / relative / "__init__.py",
        )
        if candidate.is_file()
    ]
    # Local evidence must resolve to exactly one module across all declared roots.
    if len(candidates) != 1:
        # Reject absence and ambiguity with the discovered candidate count.
        _fail(
            "CONTRACT003_REPRESENTATION",
            module,
            f"expected one local module, found {len(candidates)}",
        )
    # Return the sole unambiguous local module path.
    return candidates[0]


def _class(module: str, symbol: str, source_roots: Sequence[Path]) -> tuple[Path, ast.ClassDef]:
    """Resolve one top-level class from a local module.

    @param module dotted local module
    @param symbol class name
    @param source_roots local import-root elements in declared precedence order
    @return module path and class syntax node
    """
    # Resolve the module to one repository-owned Python source file.
    path = _module_path(module, source_roots)
    # Parse the file snapshot used for structural representation checks.
    try:
        # Build the module syntax tree from one decoded source snapshot.
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    # Translate source-read and syntax failures into the representation diagnostic.
    except (OSError, UnicodeError, SyntaxError) as problem:
        # Preserve the exact module path and parser detail.
        _fail("CONTRACT003_REPRESENTATION", str(path), str(problem))
    # Collect each matching top-level class in source order; nested names do not satisfy imports.
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == symbol]
    # Import resolution requires exactly one matching top-level class.
    if len(matches) != 1:
        # Reject absence and ambiguity with the discovered definition count.
        _fail(
            "CONTRACT003_REPRESENTATION",
            f"{module}.{symbol}",
            f"expected one top-level class, found {len(matches)}",
        )
    # Return both the owning source path and sole syntax node.
    return path, matches[0]


def _name(node: ast.expr) -> str:
    """Render the terminal identifier of one base or decorator expression.

    @param node expression syntax
    @return terminal name, or an empty string for another expression form
    """
    # A bare name already exposes its terminal identifier.
    if isinstance(node, ast.Name):
        # Return the lexical identifier without attempting import resolution.
        return node.id
    # A dotted attribute exposes its final symbol independently of its qualifier.
    if isinstance(node, ast.Attribute):
        # Return the terminal attribute used for base or decorator classification.
        return node.attr
    # Other expression forms do not establish a statically recognized symbol.
    return ""


def _validate_representation(
    contract: ContractEvidence,
    source_roots: Sequence[Path],
) -> None:
    """Match the declared structural or nominal representation to source.

    @param contract local conformance evidence
    @param source_roots complete production-root elements in declared precedence order
    @throws ConformanceError when source contradicts the representation
    """
    # Resolve the declared boundary class from its local production module.
    _, boundary = _class(contract.module, contract.symbol, source_roots)
    # Collect an unordered set whose each element is one terminal base-class name.
    bases = {_name(base) for base in boundary.bases}
    # Record whether the syntax declares structural Protocol conformance.
    is_protocol = "Protocol" in bases
    # Record whether any ordered class member declares abstract behavior.
    has_abstract_member = any(
        _name(decorator) == "abstractmethod"
        for member in boundary.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in member.decorator_list
    )
    # A structural declaration must be represented by a Protocol boundary.
    if contract.representation == "structural" and not is_protocol:
        # Reject source that contradicts the explicit representation decision.
        _fail(
            "CONTRACT003_REPRESENTATION",
            f"{contract.module}.{contract.symbol}",
            "declared structural but the boundary does not derive from Protocol",
        )
    # A nominal declaration must use abstract behavior without Protocol semantics.
    if contract.representation == "nominal" and (is_protocol or not has_abstract_member):
        # Reject a merely concrete or structurally typed nominal boundary.
        _fail(
            "CONTRACT003_REPRESENTATION",
            f"{contract.module}.{contract.symbol}",
            "nominal boundaries must declare abstract behavior and must not be Protocol",
        )
    # Validate each implementation-record element in authored order.
    for implementation in contract.implementations:
        # Resolve the implementation class from its declared production or test module.
        _, implementation_class = _class(
            implementation.module,
            implementation.symbol,
            source_roots,
        )
        # Structural implementations need no nominal inheritance relation.
        if contract.representation != "nominal":
            # Advance to the next implementation after source existence was established.
            continue
        # Nominal implementations must explicitly inherit the declared boundary symbol.
        if contract.symbol not in {_name(base) for base in implementation_class.bases}:
            # Reject an implementation that cannot satisfy nominal subtype selection.
            _fail(
                "CONTRACT003_REPRESENTATION",
                f"{implementation.module}.{implementation.symbol}",
                f"nominal implementation does not inherit {contract.symbol}",
            )


def _required_terms(contract: Contract) -> set[tuple[str, str, str | None]]:
    """Expand architecture operations into the evidence keys they require.

    @param contract canonical architecture contract
    @return unordered set whose each element is an operation, term, and optional error key
    """
    # Accumulate one unordered key set so duplicate architecture terms collapse by identity.
    required: set[tuple[str, str, str | None]] = set()
    # Expand each operation-record element in authored architecture order.
    for operation in contract.operations:
        # Success is executable and mandatory for every operation.
        required.add((operation.name, "success", None))
        # Interaction semantics are always represented, though some may be inapplicable.
        required.update((operation.name, term, None) for term in OPTIONAL_TEST_TERMS)
        # Each declared error variant requires its own executable evidence key.
        required.update((operation.name, "error", error) for error in operation.errors)
    # Return the complete order-independent key set for exact comparison.
    return required


def _validate_evidence(
    evidence: ContractEvidence,
    contract: Contract,
    root: Path,
) -> None:
    """Require a total, non-duplicated trace from contract terms to local tests.

    @param evidence conformance registry entry
    @param contract canonical architecture contract
    @param root governed repository root
    @throws ConformanceError when a term is missing, duplicated, or external
    """
    # Collect each authored evidence key in source order so duplicate records remain visible.
    actual = [(item.operation, item.term, item.error) for item in evidence.evidence]
    # A repeated operation-term key would make its disposition ambiguous.
    if len(actual) != len(set(actual)):
        # Reject the contract before comparing its apparent set coverage.
        _fail(
            "CONTRACT005_TERM_TRACE",
            evidence.contract_id,
            "an operation term has more than one evidence record",
        )
    # Expand the architecture operation records into the exact unordered required-key set.
    required = _required_terms(contract)
    # Registry evidence must equal the architecture requirement without omission or invention.
    if set(actual) != required:
        # Sort both set differences to produce deterministic actionable diagnostics.
        _fail(
            "CONTRACT005_TERM_TRACE",
            evidence.contract_id,
            f"missing={sorted(required - set(actual))}, unknown={sorted(set(actual) - required)}",
        )
    # Validate each authored term-evidence record in order.
    for item in evidence.evidence:
        # Only executable dispositions carry a local pytest-node path.
        if item.test is not None:
            # Prove the declared node's owning file exists inside the repository.
            _local_path(root, item.test, "CONTRACT005_TERM_TRACE")


def _validate_implementation_set(evidence: ContractEvidence) -> None:
    """Require real, controllable, and scheduled-fault capability evidence.

    @param evidence one contract's implementation registry
    @throws ConformanceError when a semantic implementation role is absent
    """
    # At least one registered implementation must exercise the production role.
    if not any(item.kind == "real" for item in evidence.implementations):
        # Reject a contract whose shared suite proves only test substitutes.
        _fail(
            "CONTRACT004_IMPLEMENTATION_SET",
            evidence.contract_id,
            "at least one real implementation is required",
        )
    # Preserve authored order while selecting each implementation assigned a test role.
    tests = [item for item in evidence.implementations if item.kind == "test"]
    # At least one test implementation must permit deterministic outcome control.
    if not any("controllable" in item.capabilities for item in tests):
        # Reject suites unable to select successful and exceptional behavior deterministically.
        _fail(
            "CONTRACT004_IMPLEMENTATION_SET",
            evidence.contract_id,
            "a controllable test implementation is required",
        )
    # At least one test implementation must inject faults at controlled interaction points.
    if not any("scheduled_fault" in item.capabilities for item in tests):
        # Reject suites unable to prove failure propagation and recovery behavior.
        _fail(
            "CONTRACT004_IMPLEMENTATION_SET",
            evidence.contract_id,
            "scheduled-fault capability is required; it may share the controllable implementation",
        )


def _validate_suite(evidence: ContractEvidence, root: Path) -> None:
    """Require every registered implementation to be selected by one suite.

    @param evidence one contract's conformance record
    @param root governed repository root
    @throws ConformanceError when the suite or parameter registry is incomplete

    @par Effects
    Reads the declared shared-suite source file after confining its path to ``root``.
    """
    # Resolve and confine the shared suite's owning test file.
    suite = _local_path(root, evidence.suite, "CONTRACT006_SUITE_REGISTRY")
    # Read one suite snapshot used for conservative parameter-name evidence.
    text = suite.read_text(encoding="utf-8")
    # Preserve implementation order while collecting each parameter absent from suite source.
    missing = [item.parameter for item in evidence.implementations if item.parameter not in text]
    # Every registered implementation must be selectable by the one declared suite.
    if missing:
        # Reject omitted parameters in their deterministic implementation order.
        _fail(
            "CONTRACT006_SUITE_REGISTRY",
            evidence.contract_id,
            f"shared suite does not name registered parameters {missing}",
        )


def validate(
    model: ConformanceModel,
    architecture_contracts: Sequence[Contract],
    source_roots: Sequence[Path],
    root: Path,
) -> None:
    """Cross-check one registry against architecture, source, and tests.

    @param model parsed conformance registry
    @param architecture_contracts canonical contract-record elements in authored order
    @param source_roots complete production-root elements in declared precedence order
    @param root governed repository root
    @throws ConformanceError on the first deterministic mismatch
    """
    # Map each internal contract-id key to its canonical contract value; order is immaterial.
    internal = {
        contract.contract_id: contract
        for contract in architecture_contracts
        if contract.direction == "internal"
    }
    # Map each registered contract-id key to its evidence value; order is immaterial.
    registered = {contract.contract_id: contract for contract in model.contracts}
    # Canonical internal contracts and conformance entries must form an exact join.
    if set(internal) != set(registered):
        # Sort both identity differences to produce deterministic diagnostics.
        _fail(
            "CONTRACT002_ARCHITECTURE_JOIN",
            "$.contracts",
            f"missing={sorted(set(internal) - set(registered))}, "
            f"unknown={sorted(set(registered) - set(internal))}",
        )
    # Validate each registered key/value pair in authored insertion order.
    for contract_id, evidence in registered.items():
        # Representation form is proved before behavioral capability and trace evidence.
        _validate_representation(evidence, source_roots)
        _validate_implementation_set(evidence)
        _validate_suite(evidence, root)
        _validate_evidence(evidence, internal[contract_id], root)


class ContractConformanceCheck(Check):
    """Check local boundary form, implementation capabilities, and test traceability."""

    ## Stable mechanism token for the v5 semantic-conformance rules.
    name = "contract_conformance"
    ## Rule-id elements in deterministic reporting order implemented by this checker.
    rules = ("ARCH-024", "ARCH-025", "TEST-020")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate only the two canonical model paths from this declaration.

        @param paths path elements in caller order, deliberately ignored because models and
            source roots are declaration-bound
        @return zero or one earliest deterministic finding
        """
        # Mark the protocol parameter consumed while retaining the common checker signature.
        _ = paths
        # Resolve the two canonical model paths from the validated project declaration.
        path = self.declaration.contract_conformance_path()
        architecture_path = self.declaration.architecture_path()
        # A project without the complete optional model pair has no conformance gate to run.
        if path is None or architecture_path is None or self.declaration.root is None:
            # Return an ordered empty finding sequence for an undeclared mechanism.
            return []
        # Parse and cross-check the complete local conformance proposition.
        try:
            # Parse the conformance registry before resolving its architecture references.
            model = parse(path)
            # Parse the canonical architecture model used as the join authority.
            architecture = parse_architecture(architecture_path)
            validate(
                model,
                architecture.contracts,
                self.declaration.source_paths(),
                self.declaration.root,
            )
        # Translate an invalid prerequisite architecture model into the join rule.
        except ArchitectureError as problem:
            # Return the sole earliest finding with prerequisite-specific remediation.
            return [
                Finding(
                    rule_id="ARCH-024",
                    path=architecture_path,
                    line=1,
                    message=(
                        f"architecture prerequisite failed at {problem.where}: "
                        f"{problem.detail}"
                    ),
                    remediation="Repair architecture.json before evaluating conformance evidence.",
                    diagnostic_id="CONTRACT002_ARCHITECTURE_JOIN",
                )
            ]
        # Translate a typed conformance failure into its owning discipline rule.
        except ConformanceError as problem:
            # Map each diagnostic-prefix key to its governing rule-id value; order is immaterial.
            rule = {
                "CONTRACT001": "ARCH-024",
                "CONTRACT002": "ARCH-024",
                "CONTRACT003": "ARCH-024",
                "CONTRACT004": "ARCH-025",
                "CONTRACT005": "TEST-020",
                "CONTRACT006": "TEST-020",
            }[problem.diagnostic_id[:11]]
            # Return the sole earliest finding with the model diagnostic preserved.
            return [
                Finding(
                    rule_id=rule,
                    path=path,
                    line=1,
                    message=f"{problem.where}: {problem.detail}",
                    remediation=(
                        "Repair the local conformance registry and rerun its declared suite; "
                        "do not add an implementation the suite does not exercise."
                    ),
                    diagnostic_id=problem.diagnostic_id,
                )
            ]
        # A complete validation produces the ordered empty finding sequence.
        return []


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    from . import main

    # Translate the checker result into the process exit status.
    raise SystemExit(main(ContractConformanceCheck()))
