"""AST checks for discipline rules no off-the-shelf linter enforces.

Each module here implements one `[check:<name>]` mechanism named by a rule in
`discipline/law/`. Run one directly::

    python -m checks.domain_purity src/

Or all of them::

    python -m checks src/

Every check emits findings carrying the rule id, so the output can be acted on
without consulting the rules first -- the same property `law/DIAG` requires of
program errors. Every check has a proof-of-failure test in `test_checks.py`; a
check never observed to fail has not been shown to check anything (`FLOW-007`).
"""

from __future__ import annotations

import argparse
import ast
import sys
from abc import ABC, abstractmethod
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Finding:
    """One rule violation, at a source location."""

    rule_id: str
    path: Path
    line: int
    message: str
    remediation: str

    def render(self, root: Path | None = None) -> str:
        shown = self.path
        if root is not None:
            try:
                shown = self.path.relative_to(root)
            except ValueError:
                pass
        return (
            f"{shown.as_posix()}:{self.line}: {self.rule_id} {self.message}\n"
            f"    -> {self.remediation}"
        )


class Check(ABC):
    """One mechanism. Subclasses implement `visit_module` and declare their rules."""

    name: str
    rules: tuple[str, ...]

    @abstractmethod
    def visit_module(self, tree: ast.Module, path: Path, layer: str) -> Iterator[Finding]:
        """Yield findings for one parsed module."""

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        findings: list[Finding] = []
        for path in iter_python_files(paths):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except SyntaxError as exc:
                findings.append(
                    Finding(
                        rule_id="CHECK-000",
                        path=path,
                        line=exc.lineno or 1,
                        message=f"could not parse: {exc.msg}",
                        remediation="Fix the syntax error; no check can run on this file.",
                    )
                )
                continue
            findings.extend(self.visit_module(tree, path, layer_of(path)))
        return findings


def iter_python_files(paths: Sequence[Path]) -> Iterator[Path]:
    """Every `.py` file under the given paths, in stable order."""
    for entry in paths:
        if entry.is_file() and entry.suffix == ".py":
            yield entry
        elif entry.is_dir():
            yield from sorted(entry.rglob("*.py"))


## The layer names `law/ARCH` defines. A path segment match is deliberate: the
## layer is a directory, so it is visible in every traceback frame.
LAYERS = ("domain", "app", "adapters", "shell")


def layer_of(path: Path) -> str:
    """Which architectural layer a file belongs to, or 'unknown'."""
    for part in path.parts:
        if part in LAYERS:
            return part
    return "unknown"


def is_test_path(path: Path) -> bool:
    return "tests" in path.parts or path.name.startswith("test_")


def main(check: Check, argv: Sequence[str] | None = None) -> int:
    """Standard entry point shared by every check module."""
    parser = argparse.ArgumentParser(description=check.__doc__ or check.name)
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("src")])
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    findings = check.run(args.paths or [Path("src")])
    for finding in findings:
        print(finding.render(args.root))
    rules = ", ".join(check.rules)
    print(f"\n{check.name}: {len(findings)} finding(s) [{rules}]")
    return 1 if findings else 0
