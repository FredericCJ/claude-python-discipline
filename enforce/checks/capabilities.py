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

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

## Imported module roots whose production use is a capability observation.
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
## Terminal call names that visibly request an irreversible state change.
DESTRUCTIVE_CALLS: Final = frozenset({
    "delete", "remove", "removedirs", "rmdir", "rmtree", "unlink",
})
## Calls that visibly introduce a finite wait or execution bound.
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
    @return root module and one-indexed line pairs
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name.split(".", 1)[0], node.lineno
        elif isinstance(node, ast.ImportFrom) and node.module:
            yield node.module.split(".", 1)[0], node.lineno


def _call_name(node: ast.Call) -> str:
    """Return the terminal spelling of one called expression.

    @param node call syntax
    @return terminal identifier or an empty string
    """
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _sensitive_environment_key(node: ast.Call) -> str | None:
    """Recognize an explicit secret-bearing environment-key lookup.

    @param node call syntax
    @return matched constant key, or None
    """
    name = _call_name(node)
    if name not in {"getenv", "get"} or not node.args:
        return None
    value = node.args[0]
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        return None
    return value.value if SENSITIVE_NAME.search(value.value) is not None else None


def _call_observations(node: ast.Call, path: Path) -> tuple[Observation, ...]:
    """Translate one call into its narrow capability witnesses.

    @param node production call syntax
    @param path source path containing the call
    @return zero or more independent observations
    """
    found: list[Observation] = []
    call = _call_name(node)
    if call in DESTRUCTIVE_CALLS:
        found.append(Observation(
            Capability.DESTRUCTIVE_EFFECTS,
            path,
            node.lineno,
            f"destructive call spelling {call!r}",
        ))
    has_timeout = any(keyword.arg == "timeout" for keyword in node.keywords)
    if call in BOUNDED_CALLS or has_timeout:
        found.append(Observation(
            Capability.BOUNDED_LATENCY,
            path,
            node.lineno,
            "finite timeout call or keyword",
        ))
    secret = _sensitive_environment_key(node)
    if secret is not None:
        found.append(Observation(
            Capability.SENSITIVE_DATA,
            path,
            node.lineno,
            f"secret-bearing environment key {secret!r}",
        ))
    return tuple(found)


def _source_observations(source_roots: Sequence[Path]) -> list[Observation]:
    """Collect narrow capability witnesses from production Python.

    @param source_roots complete declared production roots
    @return stable source-order observations
    """
    observations: list[Observation] = []
    for path in iter_python_files(source_roots):
        if is_test_path(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (OSError, UnicodeError, SyntaxError):
            continue
        if path.stem.startswith(("build_", "generate_")):
            observations.append(Observation(
                Capability.GENERATED_ARTIFACTS,
                path,
                1,
                f"production generator module {path.name!r}",
            ))
        for root, line in _import_roots(tree):
            observations.extend(
                Observation(
                    capability,
                    path,
                    line,
                    f"production import root {root!r}",
                )
                for capability in IMPORT_CAPABILITIES.get(root, ())
            )
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                observations.extend(_call_observations(node, path))
    return observations


def _project_observations(root: Path) -> list[Observation]:
    """Infer a public interface from standard build metadata.

    @param root governed repository root
    @return public-api observation when scripts or entry points are declared
    """
    path = root / "pyproject.toml"
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError):
        return []
    project = document.get("project", {})
    if not isinstance(project, dict):
        return []
    entry_points = project.get("entry-points")
    if project.get("scripts") or (isinstance(entry_points, dict) and entry_points):
        return [Observation(
            Capability.PUBLIC_API,
            path,
            1,
            "build metadata declares scripts or entry points",
        )]
    return []


def infer(check: Check) -> tuple[Observation, ...]:
    """Infer every observable capability for one configured check.

    @param check check carrying the local project declaration
    @return de-duplicated observations in deterministic order
    """
    root = check.declaration.root
    if root is None:
        return ()
    found = [
        *_project_observations(root),
        *_source_observations(check.declaration.source_paths()),
    ]
    architecture_path = check.declaration.architecture_path()
    if architecture_path is not None:
        try:
            architecture = parse_architecture(architecture_path)
        except ArchitectureError:
            architecture = None
        if architecture is not None and any(
            contract.direction == "published" for contract in architecture.contracts
        ):
            found.append(Observation(
                Capability.PUBLIC_API,
                architecture_path,
                1,
                "canonical architecture declares a published contract",
            ))
    unique: dict[Capability, Observation] = {}
    for observation in found:
        unique.setdefault(observation.capability, observation)
    return tuple(unique[capability] for capability in Capability if capability in unique)


class CapabilitiesCheck(Check):
    """Require a coherent manifest that never under-declares observed behavior."""

    ## Mechanism token for capability manifest rules.
    name = "capabilities"
    ## Manifest coherence and under-declaration are separate obligations.
    rules = ("OPS-001", "OPS-002")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Compare explicit facts with local source, build, and contract witnesses.

        @param paths ignored; source scope comes only from the declaration
        @return one relationship finding plus each under-declared observed fact
        """
        _ = paths
        source = self.declaration.source or Path("pyproject.toml")
        findings: list[Finding] = []
        if (
            self.declaration.has(Capability.OWNS_SUBPROCESS_LIFECYCLE)
            and not self.declaration.has(Capability.LAUNCHES_SUBPROCESSES)
        ):
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
        for observation in infer(self):
            if self.declaration.has(observation.capability):
                continue
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
        return findings


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(CapabilitiesCheck()))
