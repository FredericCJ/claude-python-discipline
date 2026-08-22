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

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

## Stable identifiers shared by contracts, implementations, and operations.
IDENTIFIER: Final = re.compile(r"^[a-z][a-z0-9_]*$")
## Importable Python module names.
MODULE_NAME: Final = re.compile(r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*$")
## Importable Python symbols.
SYMBOL_NAME: Final = re.compile(r"^[A-Za-z_]\w*$")
## Representation decisions supported by the v4 boundary model.
REPRESENTATIONS: Final = frozenset({"structural", "nominal"})
## Implementation roles; capabilities carry test behavior independently.
IMPLEMENTATION_KINDS: Final = frozenset({"real", "test"})
## Capabilities required by ARCH-025, combinable on one test implementation.
CAPABILITIES: Final = frozenset({"controllable", "scheduled_fault"})
## Observable terms inherited from every architecture operation.
TERM_KINDS: Final = frozenset({
    "success",
    "error",
    "ordering",
    "idempotency",
    "concurrency",
    "timeout",
})
## Semantic terms for which explicit non-applicability can be truthful.
OPTIONAL_TEST_TERMS: Final = frozenset({"ordering", "idempotency", "concurrency", "timeout"})


class ConformanceError(ValueError):
    """One stable contract-conformance diagnostic."""

    def __init__(self, diagnostic_id: str, where: str, detail: str) -> None:
        """Build one registry failure.

        @param diagnostic_id stable mechanism diagnostic
        @param where JSON path or repository location
        @param detail actionable explanation
        """
        super().__init__(f"{diagnostic_id} {where}: {detail}")
        self.diagnostic_id = diagnostic_id
        self.where = where
        self.detail = detail


def _fail(diagnostic_id: str, where: str, detail: str) -> Never:
    """Raise a registry diagnostic without duplicating exception mechanics.

    @param diagnostic_id stable mechanism diagnostic
    @param where JSON path or repository location
    @param detail actionable explanation
    @return never; this helper always raises
    @throws ConformanceError unconditionally
    """
    raise ConformanceError(diagnostic_id, where, detail)


def _object(value: object, where: str) -> Mapping[str, object]:
    """Require one JSON object.

    @param value untrusted decoded value
    @param where JSON path
    @return typed mapping
    """
    if not isinstance(value, dict):
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected an object")
    return value


def _exact(record: Mapping[str, object], fields: set[str], where: str) -> None:
    """Reject absent and ignored fields.

    @param record decoded JSON object
    @param fields exact allowed field set
    @param where JSON path
    @throws ConformanceError when the field set differs
    """
    missing = fields - set(record)
    unknown = set(record) - fields
    if missing or unknown:
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
    if not isinstance(value, str) or not value.strip():
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected non-empty text")
    return value.strip()


def _optional_text(value: object, where: str) -> str | None:
    """Require null or a non-empty string.

    @param value untrusted decoded value
    @param where JSON path
    @return stripped text or None
    """
    return None if value is None else _text(value, where)


def _identifier(value: object, where: str) -> str:
    """Require a stable lower-snake identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated identifier
    """
    text = _text(value, where)
    if IDENTIFIER.fullmatch(text) is None:
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected lower_snake identifier")
    return text


def _module(value: object, where: str) -> str:
    """Require a dotted Python module name.

    @param value untrusted decoded value
    @param where JSON path
    @return validated module name
    """
    text = _text(value, where)
    if MODULE_NAME.fullmatch(text) is None:
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected dotted Python module")
    return text


def _symbol(value: object, where: str) -> str:
    """Require a Python identifier.

    @param value untrusted decoded value
    @param where JSON path
    @return validated symbol
    """
    text = _text(value, where)
    if SYMBOL_NAME.fullmatch(text) is None:
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected Python symbol")
    return text


def _records(value: object, where: str, *, allow_empty: bool = False) -> list[Mapping[str, object]]:
    """Require an array of JSON objects.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty whether an explicit empty registry is valid
    @return decoded mapping records
    """
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected a non-empty record array")
    return [_object(item, f"{where}[{index}]") for index, item in enumerate(value)]


def _strings(value: object, where: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    """Require a unique array of strings.

    @param value untrusted decoded value
    @param where JSON path
    @param allow_empty whether no values is meaningful
    @return strings in source order
    """
    if not isinstance(value, list) or (not value and not allow_empty):
        _fail("CONTRACT001_MODEL_SCHEMA", where, "expected a string array")
    values = tuple(_text(item, f"{where}[{index}]") for index, item in enumerate(value))
    if len(values) != len(set(values)):
        _fail("CONTRACT001_MODEL_SCHEMA", where, "duplicate values are not allowed")
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
    ## Controllability and scheduled-fault capabilities.
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
    ## Every real and test implementation under the contract.
    implementations: tuple[Implementation, ...]
    ## One suite executed unchanged across registered parameters.
    suite: str
    ## Operation-term trace records.
    evidence: tuple[TermEvidence, ...]


@dataclass(frozen=True, slots=True)
class ConformanceModel:
    """The complete local conformance registry."""

    ## Internal contract evidence, possibly empty when justified.
    contracts: tuple[ContractEvidence, ...]
    ## Explanation when this repository has no internal boundary contract.
    contract_absence: str | None


def _implementation(record: Mapping[str, object], where: str) -> Implementation:
    """Parse one implementation record.

    @param record decoded implementation object
    @param where JSON path
    @return typed implementation
    """
    _exact(record, {"id", "module", "symbol", "kind", "capabilities", "parameter"}, where)
    kind = _text(record["kind"], f"{where}.kind")
    if kind not in IMPLEMENTATION_KINDS:
        _fail("CONTRACT001_MODEL_SCHEMA", f"{where}.kind", "expected real or test")
    capabilities = _strings(record["capabilities"], f"{where}.capabilities", allow_empty=True)
    unknown = set(capabilities) - CAPABILITIES
    if unknown:
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            f"{where}.capabilities",
            f"unknown capabilities {sorted(unknown)}",
        )
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

    @param record decoded trace object
    @param where JSON path
    @return typed evidence record
    """
    _exact(record, {"operation", "term", "error", "test", "not_applicable"}, where)
    term = _text(record["term"], f"{where}.term")
    if term not in TERM_KINDS:
        _fail("CONTRACT001_MODEL_SCHEMA", f"{where}.term", "unknown contract term")
    error = _optional_text(record["error"], f"{where}.error")
    test = _optional_text(record["test"], f"{where}.test")
    not_applicable = _optional_text(
        record["not_applicable"],
        f"{where}.not_applicable",
    )
    if (test is None) == (not_applicable is None):
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            where,
            "exactly one of test and not_applicable must be non-null",
        )
    if (term == "error") != (error is not None):
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            f"{where}.error",
            "error is required only for an error term",
        )
    if not_applicable is not None and term not in OPTIONAL_TEST_TERMS:
        _fail(
            "CONTRACT005_TERM_TRACE",
            where,
            "success and declared errors require executable test evidence",
        )
    return TermEvidence(
        operation=_identifier(record["operation"], f"{where}.operation"),
        term=term,
        error=error,
        test=test,
        not_applicable=not_applicable,
    )


def _contract(record: Mapping[str, object], where: str) -> ContractEvidence:
    """Parse one contract evidence record.

    @param record decoded contract object
    @param where JSON path
    @return typed contract evidence
    """
    fields = {
        "id",
        "module",
        "symbol",
        "representation",
        "implementations",
        "suite",
        "evidence",
    }
    _exact(record, fields, where)
    representation = _text(record["representation"], f"{where}.representation")
    if representation not in REPRESENTATIONS:
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            f"{where}.representation",
            "expected structural or nominal",
        )
    implementations = tuple(
        _implementation(item, f"{where}.implementations[{index}]")
        for index, item in enumerate(
            _records(record["implementations"], f"{where}.implementations")
        )
    )
    identifiers = [item.implementation_id for item in implementations]
    parameters = [item.parameter for item in implementations]
    if len(identifiers) != len(set(identifiers)) or len(parameters) != len(set(parameters)):
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            where,
            "implementation ids and suite parameter ids must each be unique",
        )
    evidence = tuple(
        _term_evidence(item, f"{where}.evidence[{index}]")
        for index, item in enumerate(_records(record["evidence"], f"{where}.evidence"))
    )
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
    """
    try:
        raw: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as problem:
        _fail("CONTRACT001_MODEL_SCHEMA", str(path), str(problem))
    root = _object(raw, "$")
    _exact(root, {"schema_version", "contracts", "contract_absence"}, "$")
    if root["schema_version"] != 1:
        _fail("CONTRACT001_MODEL_SCHEMA", "$.schema_version", "expected 1")
    contracts = tuple(
        _contract(item, f"$.contracts[{index}]")
        for index, item in enumerate(_records(root["contracts"], "$.contracts", allow_empty=True))
    )
    identifiers = [item.contract_id for item in contracts]
    if len(identifiers) != len(set(identifiers)):
        _fail("CONTRACT001_MODEL_SCHEMA", "$.contracts", "contract ids must be unique")
    absence = _optional_text(root["contract_absence"], "$.contract_absence")
    if contracts and absence is not None:
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            "$.contract_absence",
            "must be null when contract evidence exists",
        )
    if not contracts and absence is None:
        _fail(
            "CONTRACT001_MODEL_SCHEMA",
            "$.contract_absence",
            "explain why this repository has no internal boundary contract",
        )
    return ConformanceModel(contracts=contracts, contract_absence=absence)


def _local_path(root: Path, spelling: str, diagnostic_id: str) -> Path:
    """Resolve one model path while enforcing the repository boundary.

    @param root governed repository root
    @param spelling POSIX repository-relative path, optionally with a pytest node suffix
    @param diagnostic_id diagnostic to raise for an unsafe or absent path
    @return existing confined file path
    """
    file_part = spelling.split("::", 1)[0]
    relative = PurePosixPath(file_part.replace("\\", "/"))
    if relative.is_absolute() or PureWindowsPath(file_part).drive or ".." in relative.parts:
        _fail(diagnostic_id, spelling, "path must stay inside the governed repository")
    candidate = (root / Path(relative.as_posix())).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        _fail(diagnostic_id, spelling, "resolved path leaves the governed repository")
    if not candidate.is_file():
        _fail(diagnostic_id, spelling, "declared test file does not exist")
    return candidate


def _module_path(module: str, source_roots: Sequence[Path]) -> Path:
    """Resolve a declared module from this repository's complete source roots.

    @param module dotted absolute module
    @param source_roots local import roots
    @return unique source module path
    """
    relative = Path(*module.split("."))
    candidates = [
        candidate
        for source_root in source_roots
        for candidate in (
            source_root / relative.with_suffix(".py"),
            source_root / relative / "__init__.py",
        )
        if candidate.is_file()
    ]
    if len(candidates) != 1:
        _fail(
            "CONTRACT003_REPRESENTATION",
            module,
            f"expected one local module, found {len(candidates)}",
        )
    return candidates[0]


def _class(module: str, symbol: str, source_roots: Sequence[Path]) -> tuple[Path, ast.ClassDef]:
    """Resolve one top-level class from a local module.

    @param module dotted local module
    @param symbol class name
    @param source_roots local import roots
    @return module path and class syntax node
    """
    path = _module_path(module, source_roots)
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as problem:
        _fail("CONTRACT003_REPRESENTATION", str(path), str(problem))
    matches = [node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == symbol]
    if len(matches) != 1:
        _fail(
            "CONTRACT003_REPRESENTATION",
            f"{module}.{symbol}",
            f"expected one top-level class, found {len(matches)}",
        )
    return path, matches[0]


def _name(node: ast.expr) -> str:
    """Render the terminal identifier of one base or decorator expression.

    @param node expression syntax
    @return terminal name, or an empty string for another expression form
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _validate_representation(
    contract: ContractEvidence,
    source_roots: Sequence[Path],
) -> None:
    """Match the declared structural or nominal representation to source.

    @param contract local conformance evidence
    @param source_roots complete production roots
    @throws ConformanceError when source contradicts the representation
    """
    _, boundary = _class(contract.module, contract.symbol, source_roots)
    bases = {_name(base) for base in boundary.bases}
    is_protocol = "Protocol" in bases
    has_abstract_member = any(
        _name(decorator) == "abstractmethod"
        for member in boundary.body
        if isinstance(member, (ast.FunctionDef, ast.AsyncFunctionDef))
        for decorator in member.decorator_list
    )
    if contract.representation == "structural" and not is_protocol:
        _fail(
            "CONTRACT003_REPRESENTATION",
            f"{contract.module}.{contract.symbol}",
            "declared structural but the boundary does not derive from Protocol",
        )
    if contract.representation == "nominal" and (is_protocol or not has_abstract_member):
        _fail(
            "CONTRACT003_REPRESENTATION",
            f"{contract.module}.{contract.symbol}",
            "nominal boundaries must declare abstract behavior and must not be Protocol",
        )
    for implementation in contract.implementations:
        _, implementation_class = _class(
            implementation.module,
            implementation.symbol,
            source_roots,
        )
        if contract.representation != "nominal":
            continue
        if contract.symbol not in {_name(base) for base in implementation_class.bases}:
            _fail(
                "CONTRACT003_REPRESENTATION",
                f"{implementation.module}.{implementation.symbol}",
                f"nominal implementation does not inherit {contract.symbol}",
            )


def _required_terms(contract: Contract) -> set[tuple[str, str, str | None]]:
    """Expand architecture operations into the evidence keys they require.

    @param contract canonical architecture contract
    @return operation, term, and optional error keys
    """
    required: set[tuple[str, str, str | None]] = set()
    for operation in contract.operations:
        required.add((operation.name, "success", None))
        required.update((operation.name, term, None) for term in OPTIONAL_TEST_TERMS)
        required.update((operation.name, "error", error) for error in operation.errors)
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
    actual = [(item.operation, item.term, item.error) for item in evidence.evidence]
    if len(actual) != len(set(actual)):
        _fail(
            "CONTRACT005_TERM_TRACE",
            evidence.contract_id,
            "an operation term has more than one evidence record",
        )
    required = _required_terms(contract)
    if set(actual) != required:
        _fail(
            "CONTRACT005_TERM_TRACE",
            evidence.contract_id,
            f"missing={sorted(required - set(actual))}, unknown={sorted(set(actual) - required)}",
        )
    for item in evidence.evidence:
        if item.test is not None:
            _local_path(root, item.test, "CONTRACT005_TERM_TRACE")


def _validate_implementation_set(evidence: ContractEvidence) -> None:
    """Require real, controllable, and scheduled-fault capability evidence.

    @param evidence one contract's implementation registry
    @throws ConformanceError when a semantic implementation role is absent
    """
    if not any(item.kind == "real" for item in evidence.implementations):
        _fail(
            "CONTRACT004_IMPLEMENTATION_SET",
            evidence.contract_id,
            "at least one real implementation is required",
        )
    tests = [item for item in evidence.implementations if item.kind == "test"]
    if not any("controllable" in item.capabilities for item in tests):
        _fail(
            "CONTRACT004_IMPLEMENTATION_SET",
            evidence.contract_id,
            "a controllable test implementation is required",
        )
    if not any("scheduled_fault" in item.capabilities for item in tests):
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
    """
    suite = _local_path(root, evidence.suite, "CONTRACT006_SUITE_REGISTRY")
    text = suite.read_text(encoding="utf-8")
    missing = [item.parameter for item in evidence.implementations if item.parameter not in text]
    if missing:
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
    @param architecture_contracts canonical local contracts
    @param source_roots complete local production roots
    @param root governed repository root
    @throws ConformanceError on the first deterministic mismatch
    """
    internal = {
        contract.contract_id: contract
        for contract in architecture_contracts
        if contract.direction == "internal"
    }
    registered = {contract.contract_id: contract for contract in model.contracts}
    if set(internal) != set(registered):
        _fail(
            "CONTRACT002_ARCHITECTURE_JOIN",
            "$.contracts",
            f"missing={sorted(set(internal) - set(registered))}, "
            f"unknown={sorted(set(registered) - set(internal))}",
        )
    for contract_id, evidence in registered.items():
        _validate_representation(evidence, source_roots)
        _validate_implementation_set(evidence)
        _validate_suite(evidence, root)
        _validate_evidence(evidence, internal[contract_id], root)


class ContractConformanceCheck(Check):
    """Check local boundary form, implementation capabilities, and test traceability."""

    ## Mechanism token for the v4 semantic-conformance rules.
    name = "contract_conformance"
    ## Separately diagnosable obligations implemented by the registry checker.
    rules = ("ARCH-024", "ARCH-025", "TEST-020")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Validate only the two canonical model paths from this declaration.

        @param paths ignored caller selection; models and source roots are declaration-bound
        @return zero or one earliest deterministic finding
        """
        _ = paths
        path = self.declaration.contract_conformance_path()
        architecture_path = self.declaration.architecture_path()
        if path is None or architecture_path is None or self.declaration.root is None:
            return []
        try:
            model = parse(path)
            architecture = parse_architecture(architecture_path)
            validate(
                model,
                architecture.contracts,
                self.declaration.source_paths(),
                self.declaration.root,
            )
        except ArchitectureError as problem:
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
        except ConformanceError as problem:
            rule = {
                "CONTRACT001": "ARCH-024",
                "CONTRACT002": "ARCH-024",
                "CONTRACT003": "ARCH-024",
                "CONTRACT004": "ARCH-025",
                "CONTRACT005": "TEST-020",
                "CONTRACT006": "TEST-020",
            }[problem.diagnostic_id[:11]]
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
        return []


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(ContractConformanceCheck()))
