"""Decide the separable static claims in v4's local dependency model.

The checker builds a module index only from this repository's declared source
roots. It reports four independent predicates:

* ``ARCH-001`` — a policy dependency crosses outward;
* ``ARCH-003`` — one adapter boundary imports another;
* ``ARCH-019`` — application orchestration imports a concrete adapter;
* ``ARCH-020`` — a declared foreign technology is directly imported outside
  its one owning adapter boundary.

Only direct imports are claimed. In particular, repository-local shell wiring
may import a real adapter and thereby reach its technology transitively; the
shell does not become a second direct owner.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING

from . import Check, Finding, iter_python_files

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence


@dataclass(frozen=True, slots=True)
class LocalModule:
    """One indexed module and its declared architectural identity."""

    ## Absolute dotted import name within one declared source root.
    name: str
    ## Local file providing the module.
    path: Path
    ## Canonical check-layer spelling resolved from the declaration.
    role: str
    ## Independently substitutable adapter boundary, or None for shared support.
    adapter_boundary: str | None


def _module_name(path: Path, source_root: Path) -> str:
    """Convert one source file into its absolute import name.

    @param path Python source file beneath ``source_root``
    @param source_root import root declared by the repository
    @return dotted module or package name
    """
    relative = path.relative_to(source_root)
    parts = list(relative.parts)
    if path.name == "__init__.py":
        parts.pop()
    else:
        parts[-1] = path.stem
    return ".".join(parts)


def _adapter_boundary(
    path: Path,
    root: Path,
    boundaries: Sequence[PurePosixPath],
) -> str | None:
    """Identify the declared independently substitutable adapter boundary.

    Adapter-role support code may sit outside every boundary and be imported by
    several of them. It is not thereby another adapter implementation.

    @param path adapter source file
    @param root governed repository root
    @param boundaries declared adapter boundary paths
    @return stable relative boundary spelling, or None outside adapters
    """
    relative = PurePosixPath(path.resolve().relative_to(root.resolve()).as_posix())
    for boundary in boundaries:
        if relative != boundary and not relative.is_relative_to(boundary):
            continue
        return boundary.as_posix()
    return None


def _index(check: DependencyBoundariesCheck) -> dict[str, LocalModule]:
    """Build this repository's complete local import index.

    @param check checker carrying the parsed project declaration
    @return dotted name to local module; duplicate names are left for packaging tools
    """
    declaration = check.declaration
    if declaration.root is None:
        return {}
    indexed: dict[str, LocalModule] = {}
    boundaries = declaration.adapter_boundaries
    for source_root in declaration.source_paths():
        if not source_root.is_dir():
            continue
        for path in iter_python_files([source_root]):
            role = declaration.role_of(path)
            if role is None:
                continue
            name = _module_name(path, source_root)
            if not name:
                continue
            indexed[name] = LocalModule(
                name=name,
                path=path,
                role=role,
                adapter_boundary=(
                    _adapter_boundary(path, declaration.root, boundaries)
                    if role == "adapters" else None
                ),
            )
    return indexed


def _absolute_imports(node: ast.Import | ast.ImportFrom, current: LocalModule) -> Iterator[str]:
    """Yield import spellings resolved relative to the current module.

    @param node import syntax node
    @param current importing local module
    @return candidate absolute module names
    """
    if isinstance(node, ast.Import):
        yield from (alias.name for alias in node.names)
        return
    base = node.module or ""
    if node.level:
        package = (
            current.name
            if current.path.name == "__init__.py"
            else current.name.rpartition(".")[0]
        )
        parts = package.split(".") if package else []
        ascend = node.level - 1
        prefix = parts[: max(0, len(parts) - ascend)]
        base = ".".join((*prefix, *(base.split(".") if base else ())))
    if base:
        yield base
    for alias in node.names:
        if alias.name != "*" and base:
            yield f"{base}.{alias.name}"


def _local_target(name: str, modules: Mapping[str, LocalModule]) -> LocalModule | None:
    """Resolve an import spelling to the most specific indexed local module.

    @param name absolute import spelling
    @param modules local module index
    @return imported local module or package, if any
    """
    candidates = [
        module for module_name, module in modules.items()
        if name == module_name or name.startswith(f"{module_name}.")
    ]
    return max(candidates, key=lambda module: len(module.name), default=None)


def _import_root(node: ast.Import | ast.ImportFrom) -> Iterable[tuple[str, int]]:
    """Yield direct absolute import roots and their source lines.

    @param node import syntax node
    @return top-level roots; relative local imports yield nothing
    """
    if isinstance(node, ast.Import):
        return tuple((alias.name.partition(".")[0], node.lineno) for alias in node.names)
    if node.level or node.module is None:
        return ()
    return ((node.module.partition(".")[0], node.lineno),)


def _edge_finding(source: LocalModule, target: LocalModule, line: int) -> Finding | None:
    """Classify one forbidden local dependency edge without double-reporting it.

    @param source importing local module
    @param target imported local module
    @param line import source line
    @return the one most specific finding, or None for an allowed edge
    """
    if source.role == target.role:
        if (
            source.role == "adapters"
            and source.adapter_boundary != target.adapter_boundary
            and target.adapter_boundary is not None
        ):
            return Finding(
                rule_id="ARCH-003", path=source.path, line=line,
                message=(
                    f"adapter boundary {source.adapter_boundary} imports independent "
                    f"adapter boundary {target.adapter_boundary}"
                ),
                remediation="Move their composition to the repository-local shell.",
                diagnostic_id="ARCH003_ADAPTER_TO_ADAPTER",
            )
        return None
    allowed = {
        "domain": {"domain"},
        "ports": {"domain", "ports"},
        "app": {"domain", "ports", "app"},
        "adapters": {"domain", "ports", "adapters"},
        "shell": {"domain", "ports", "app", "adapters", "shell"},
    }
    if source.role == "app" and target.role == "adapters":
        return Finding(
            rule_id="ARCH-019", path=source.path, line=line,
            message=f"application module imports concrete adapter {target.name}",
            remediation="Inject a port contract and select the adapter in the local shell.",
            diagnostic_id="ARCH019_APPLICATION_TO_ADAPTER",
        )
    if target.role not in allowed.get(source.role, set()):
        return Finding(
            rule_id="ARCH-001", path=source.path, line=line,
            message=f"{source.role} policy imports outward role {target.role}",
            remediation="Reverse the dependency or introduce a port contract toward policy.",
            diagnostic_id="ARCH001_OUTWARD_POLICY_EDGE",
        )
    return None


def _foreign_findings(
    check: DependencyBoundariesCheck,
    source: LocalModule,
    node: ast.Import | ast.ImportFrom,
) -> Iterator[Finding]:
    """Report direct technology imports outside their declared owner.

    @param check checker carrying ownership declarations
    @param source importing local module
    @param node import syntax node
    @return one finding per owned import root used outside its owner
    """
    root = check.declaration.root
    if root is None:
        return
    relative = PurePosixPath(source.path.resolve().relative_to(root.resolve()).as_posix())
    for import_root, line in _import_root(node):
        owner = check.declaration.foreign_ownership.get(import_root)
        if owner is None or relative == owner or relative.is_relative_to(owner):
            continue
        yield Finding(
            rule_id="ARCH-020", path=source.path, line=line,
            message=(
                f"foreign import {import_root!r} is owned by {owner}, "
                f"not {relative.parent}"
            ),
            remediation=(
                "Import the technology only inside its owning adapter boundary "
                "and reach that adapter through a port or local wiring."
            ),
            diagnostic_id="ARCH020_FOREIGN_OWNER_BREACH",
        )


def _module_findings(
    check: DependencyBoundariesCheck,
    source: LocalModule,
    modules: Mapping[str, LocalModule],
) -> list[Finding]:
    """Inspect all direct imports made by one local module.

    @param check checker carrying the project declaration
    @param source importing local module
    @param modules complete local import index
    @return boundary findings in syntax order
    """
    try:
        tree = ast.parse(
            source.path.read_text(encoding="utf-8"), filename=str(source.path),
        )
    except SyntaxError:
        return []
    findings: list[Finding] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        seen_targets: set[Path] = set()
        for imported in _absolute_imports(node, source):
            target = _local_target(imported, modules)
            if target is None or target.path in seen_targets:
                continue
            seen_targets.add(target.path)
            finding = _edge_finding(source, target, node.lineno)
            if finding is not None:
                findings.append(finding)
        findings.extend(_foreign_findings(check, source, node))
    return findings


class DependencyBoundariesCheck(Check):
    """Inspect direct local and registered foreign imports across all source roots."""

    ## Mechanism token shared by the four independently coded predicates.
    name = "dependency_boundaries"
    ## Rules whose direct-import predicates this checker reports.
    rules = ("ARCH-001", "ARCH-003", "ARCH-019", "ARCH-020")

    def run(self, _paths: Sequence[Path]) -> list[Finding]:
        """Check the complete declared source graph.

        @param _paths ignored caller selection; the local dependency view must be complete
        @return independently coded forbidden dependency findings
        """
        modules = _index(self)
        if not modules or self.declaration.root is None:
            return []
        findings: list[Finding] = []
        for source in sorted(modules.values(), key=lambda item: item.path.as_posix()):
            findings.extend(_module_findings(self, source, modules))
        return findings


if __name__ == "__main__":
    from . import main

    raise SystemExit(main(DependencyBoundariesCheck()))
