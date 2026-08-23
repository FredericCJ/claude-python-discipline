"""Infer additive repository capabilities and reject under-declaration.

The project manifest is the authority for intent. This checker supplies the
one safe inference direction: an observed import, build surface, contract, or
source operation can require a capability to be true, but absence of a pattern
can never prove it false. Every observation is therefore a narrow syntactic
predicate with an explicit residual in the rule evidence.
"""

from __future__ import annotations

import ast
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Final

from . import Check, Finding, is_test_path, iter_python_files
from .architecture_model import ArchitectureError
from .architecture_model import parse as parse_architecture
from .project import Capability

# Import annotation-only collection contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

## Mapping from each imported-root key to capability-value elements in implication order;
## mapping insertion order is deterministic but direct lookup owns classification.
IMPORT_CAPABILITIES: Final[Mapping[str, tuple[Capability, ...]]] = {
    "pathlib": (Capability.FILESYSTEM_IO,),
    "shutil": (Capability.FILESYSTEM_IO,),
    "tempfile": (Capability.FILESYSTEM_IO,),
    "sqlite3": (Capability.FILESYSTEM_IO, Capability.PERSISTENT_STATE),
    "shelve": (Capability.FILESYSTEM_IO, Capability.PERSISTENT_STATE),
    "dbm": (Capability.FILESYSTEM_IO, Capability.PERSISTENT_STATE),
    "sqlalchemy": (Capability.PERSISTENT_STATE,),
    "socket": (Capability.NETWORK_IO,),
    "ssl": (Capability.NETWORK_IO,),
    "urllib": (Capability.NETWORK_IO,),
    "requests": (Capability.NETWORK_IO,),
    "httpx": (Capability.NETWORK_IO,),
    "aiohttp": (Capability.NETWORK_IO,),
    "websockets": (Capability.NETWORK_IO,),
    "subprocess": (Capability.LAUNCHES_SUBPROCESSES,),
    "threading": (Capability.CONCURRENCY,),
    "multiprocessing": (
        Capability.LAUNCHES_SUBPROCESSES,
        Capability.CONCURRENCY,
    ),
    "concurrent": (Capability.CONCURRENCY,),
    "asyncio": (Capability.CONCURRENCY,),
}
## Unordered destructive-call set whose each terminal-name element implies irreversible change.
DESTRUCTIVE_CALLS: Final = frozenset({
    "delete", "remove", "removedirs", "rmdir", "rmtree", "unlink",
})
## Unordered bounded-call set whose each terminal-name element implies finite waiting.
BOUNDED_CALLS: Final = frozenset({"wait_for", "wait_for_completion"})
## Environment-key vocabulary narrow enough to infer intentional secret handling.
SENSITIVE_NAME: Final = re.compile(
    r"(?:^|_)(?:api_key|credential|password|private_key|secret)(?:$|_)",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class Observation:
    """One source/build/contract fact implying an additive capability."""

    ## Capability that must be enabled.
    capability: Capability
    ## Local evidence path.
    path: Path
    ## One-indexed source location.
    line: int
    ## Exact narrow predicate that matched.
    reason: str


def _import_roots(tree: ast.Module) -> Iterable[tuple[str, int]]:
    """Yield imported root names and their lines.

    @param tree parsed production module
    @return root-module/one-indexed-line pair elements in deterministic AST and alias order
    """
    # Inspect each syntax-node element in deterministic AST walk order.
    for node in ast.walk(tree):
        # Direct imports may carry several aliases in authored order.
        if isinstance(node, ast.Import):
            # Inspect each import-alias element in authored statement order.
            for alias in node.names:
                # Yield the root package and statement line at this alias position.
                yield alias.name.split(".", 1)[0], node.lineno
        # From-imports supply one non-empty module spelling.
        elif isinstance(node, ast.ImportFrom) and node.module:
            # Yield its root package and statement line at this walk position.
            yield node.module.split(".", 1)[0], node.lineno


def _call_name(node: ast.Call) -> str:
    """Return the terminal spelling of one called expression.

    @param node call syntax
    @return terminal identifier or an empty string
    """
    # Bare calls expose their complete lexical identifier.
    if isinstance(node.func, ast.Name):
        # Return the bare function name.
        return node.func.id
    # Qualified calls expose their terminal method or function attribute.
    if isinstance(node.func, ast.Attribute):
        # Return the final attribute spelling.
        return node.func.attr
    # Other callable expression forms have no reliable terminal identifier.
    return ""


def _sensitive_environment_key(node: ast.Call) -> str | None:
    """Recognize an explicit secret-bearing environment-key lookup.

    @param node call syntax
    @return matched constant key, or None
    """
    # Resolve the terminal called name for closed-vocabulary classification.
    name = _call_name(node)
    # Only explicit environment lookup calls with at least one argument can carry a key.
    if name not in {"getenv", "get"} or not node.args:
        # Reject unrelated call shapes from this narrow predicate.
        return None
    # Select the first positional argument as the environment key candidate.
    value = node.args[0]
    # Only a literal string key provides reliable sensitive-name evidence.
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        # Reject dynamic key expressions without guessing their runtime content.
        return None
    # Return the literal key only when it matches the intentional secret vocabulary.
    return value.value if SENSITIVE_NAME.search(value.value) is not None else None


def _call_observations(node: ast.Call, path: Path) -> tuple[Observation, ...]:
    """Translate one call into its narrow capability witnesses.

    @param node production call syntax
    @param path source path containing the call
    @return independent observation elements in destructive, bound, then sensitive order
    """
    # Accumulate observation elements in fixed predicate order.
    found: list[Observation] = []
    # Resolve the call's terminal spelling once for destructive and bounded lookup.
    call = _call_name(node)
    # A recognized destructive terminal name implies the additive capability.
    if call in DESTRUCTIVE_CALLS:
        # Append the irreversible-state-change witness at the call location.
        found.append(Observation(
            Capability.DESTRUCTIVE_EFFECTS,
            path,
            node.lineno,
            f"destructive call spelling {call!r}",
        ))
    # Record whether any keyword element explicitly names a finite timeout.
    has_timeout = any(keyword.arg == "timeout" for keyword in node.keywords)
    # A recognized bounded call or timeout keyword implies bounded latency intent.
    if call in BOUNDED_CALLS or has_timeout:
        # Append the bounded-execution witness at the call location.
        found.append(Observation(
            Capability.BOUNDED_LATENCY,
            path,
            node.lineno,
            "finite timeout call or keyword",
        ))
    # Resolve an explicit secret-bearing environment key, if present.
    secret = _sensitive_environment_key(node)
    # A matching literal key implies intentional sensitive-data handling.
    if secret is not None:
        # Append the sensitive-data witness at the call location.
        found.append(Observation(
            Capability.SENSITIVE_DATA,
            path,
            node.lineno,
            f"secret-bearing environment key {secret!r}",
        ))
    # Freeze the independently applicable observations in predicate order.
    return tuple(found)


def _source_observations(source_roots: Sequence[Path]) -> list[Observation]:
    """Collect narrow capability witnesses from production Python.

    @param source_roots complete production-root elements in declaration order
    @return observation elements in stable source then AST order

    @par Effects
    Reads and parses each non-test Python file beneath the declared source roots.
    """
    # Accumulate observation elements in stable source traversal order.
    observations: list[Observation] = []
    # Inspect each Python source-path element in stable root and descendant order.
    for path in iter_python_files(source_roots):
        # Test fixtures do not imply production capabilities.
        if is_test_path(path):
            # Advance to the next production candidate.
            continue
        # Parse one strict UTF-8 production source snapshot.
        try:
            # Build the syntax tree while retaining the path in parser diagnostics.
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        # Another check reports unreadable or invalid source; inference never converts
        # absence to false.
        except (OSError, UnicodeError, SyntaxError):
            # Advance without emitting a capability observation from unavailable syntax.
            continue
        # Conventional generator-module spelling is a narrow generated-artifact witness.
        if path.stem.startswith(("build_", "generate_")):
            # Append the module-level observation before its imports and calls.
            observations.append(Observation(
                Capability.GENERATED_ARTIFACTS,
                path,
                1,
                f"production generator module {path.name!r}",
            ))
        # Inspect each imported-root/line pair in deterministic AST and alias order.
        for root, line in _import_roots(tree):
            # Extend with capability elements implied by this root in declared tuple order.
            observations.extend(
                Observation(
                    capability,
                    path,
                    line,
                    f"production import root {root!r}",
                )
                for capability in IMPORT_CAPABILITIES.get(root, ())
            )
        # Inspect each syntax-node element in deterministic AST walk order for calls.
        for node in ast.walk(tree):
            # Calls may independently imply destructive, bounded, or sensitive behavior.
            if isinstance(node, ast.Call):
                # Extend with call observations in fixed predicate order.
                observations.extend(_call_observations(node, path))
    # Return every observation in stable source and syntax order.
    return observations


def _project_observations(root: Path) -> list[Observation]:
    """Infer a public interface from standard build metadata.

    @param root governed repository root
    @return zero or one public-api observation element when scripts or entry points exist

    @par Effects
    Reads and parses the repository's ``pyproject.toml`` once.
    """
    # Resolve the standard build-metadata path under the governed root.
    path = root / "pyproject.toml"
    # Decode one immutable TOML project snapshot.
    try:
        # Parse strict UTF-8 text into an untrusted table mapping.
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    # Absence or malformed build metadata provides no positive capability witness.
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        # Return the ordered empty observation sequence without inferring false.
        return []
    # Select the decoded project table, defaulting absence to an empty mapping value.
    project = document.get("project", {})
    # A non-table project value cannot carry recognized build-surface fields.
    if not isinstance(project, dict):
        # Return the ordered empty observation sequence.
        return []
    # Select the optional entry-point table without coercing its shape.
    entry_points = project.get("entry-points")
    # Scripts or any non-empty entry-point mapping imply a published executable interface.
    if project.get("scripts") or (isinstance(entry_points, dict) and entry_points):
        # Return the sole project-level public-interface observation.
        return [Observation(
            Capability.PUBLIC_API,
            path,
            1,
            "build metadata declares scripts or entry points",
        )]
    # Build metadata exposes no recognized public entry surface.
    return []


def infer(check: Check) -> tuple[Observation, ...]:
    """Infer every observable capability for one configured check.

    @param check check carrying the local project declaration
    @return de-duplicated observation elements in canonical capability order
    """
    # Select the declaration-bound repository root.
    root = check.declaration.root
    # Legacy declarations without a root cannot authorize ambient inference.
    if root is None:
        # Return the ordered empty observation sequence.
        return ()
    # Collect observation elements in a sequence preserving project-before-source order.
    found = [
        *_project_observations(root),
        *_source_observations(check.declaration.source_paths()),
    ]
    # Resolve the optional canonical architecture model path.
    architecture_path = check.declaration.architecture_path()
    # A declared architecture may add a published-contract public API witness.
    if architecture_path is not None:
        # Parse the architecture without duplicating its own schema diagnostics here.
        try:
            # Build the typed architecture snapshot used only for positive inference.
            architecture = parse_architecture(architecture_path)
        # Invalid architecture supplies no trustworthy positive witness to this check.
        except ArchitectureError:
            # Preserve the absence-of-inference direction rather than reporting false.
            architecture = None
        # Any published contract implies a public API capability.
        if architecture is not None and any(
            contract.direction == "published" for contract in architecture.contracts
        ):
            # Append the architecture-level witness after build and source observations.
            found.append(Observation(
                Capability.PUBLIC_API,
                architecture_path,
                1,
                "canonical architecture declares a published contract",
            ))
    # Map each capability key to its first observation value in discovery order.
    unique: dict[Capability, Observation] = {}
    # Inspect each discovered observation element in source precedence order.
    for observation in found:
        # Preserve the first witness so diagnostics remain stable as later evidence is added.
        unique.setdefault(observation.capability, observation)
    # Return observation values in canonical Capability enum order.
    return tuple(unique[capability] for capability in Capability if capability in unique)


class CapabilitiesCheck(Check):
    """Require a coherent manifest that never under-declares observed behavior."""

    ## Mechanism token for capability manifest rules.
    name = "capabilities"
    ## Rule-id elements in deterministic reporting order for coherence and declaration coverage.
    rules = ("OPS-001", "OPS-002")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Compare explicit facts with local source, build, and contract witnesses.

        @param paths path elements in caller order, deliberately ignored for declared scope
        @return finding elements in relationship then canonical capability order
        """
        # Mark the protocol parameter consumed while retaining the common checker signature.
        _ = paths
        # Select the declaration path for manifest findings, or the conventional fallback.
        source = self.declaration.source or Path("pyproject.toml")
        # Accumulate finding elements in manifest-relation then capability order.
        findings: list[Finding] = []
        # Lifecycle ownership logically requires the capability to launch the subprocess.
        if (
            self.declaration.has(Capability.OWNS_SUBPROCESS_LIFECYCLE)
            and not self.declaration.has(Capability.LAUNCHES_SUBPROCESSES)
        ):
            # Append the incoherent-manifest finding before source observations.
            findings.append(Finding(
                rule_id="OPS-001",
                path=source,
                line=1,
                message=(
                    "owns_subprocess_lifecycle is true while "
                    "launches_subprocesses is false"
                ),
                remediation=(
                    "Enable launches_subprocesses or correct the lifecycle-ownership fact."
                ),
                diagnostic_id="CAP001_MANIFEST_RELATION",
            ))
        # Inspect each de-duplicated observation element in canonical capability order.
        for observation in infer(self):
            # An explicitly true capability satisfies this one-way inference witness.
            if self.declaration.has(observation.capability):
                # Advance without claiming that absence of other evidence proves anything false.
                continue
            # Append the under-declaration finding at the exact local witness location.
            findings.append(Finding(
                rule_id="OPS-002",
                path=observation.path,
                line=observation.line,
                message=(
                    f"{observation.capability.value} is false but local evidence "
                    f"observes {observation.reason}"
                ),
                remediation=(
                    f"Set capabilities.{observation.capability.value} = true and "
                    "satisfy the obligations it activates; do not suppress the observation."
                ),
                diagnostic_id="CAP002_UNDERDECLARED",
            ))
        # Return every finding in relationship then canonical capability order.
        return findings


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    from . import main

    # Translate the checker result into the process exit status.
    raise SystemExit(main(CapabilitiesCheck()))
