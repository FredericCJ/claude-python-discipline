"""Shared parsing for the discipline corpus.

Implements the file format specified in `discipline/meta/SCHEMA.md`. Both
`validate.py` and `build_index.py` read the corpus through this module so the two
can never disagree about what a rule is.
"""

from __future__ import annotations

import datetime
import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from enum import StrEnum
from pathlib import Path
from typing import Final

import yaml

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
DISCIPLINE_DIR: Final = REPO_ROOT / "discipline"
ENFORCE_DIR: Final = REPO_ROOT / "enforce"
EXAMPLES_DIR: Final = DISCIPLINE_DIR / "examples"

## Files written by ``build_index.py``; excluded from authored-content checks.
GENERATED_NAMES: Final[frozenset[str]] = frozenset(
    {"INDEX.md", "rules.json", "ENFORCEMENT.md"}
)

TOKEN_BUDGETS: Final[Mapping[str, int]] = {"KERNEL": 2_000, "*": 4_000}


class Kind(StrEnum):
    """The genre of a document. See SCHEMA.md section 1."""

    LAW = "law"
    FACT = "fact"
    FRAME = "frame"
    OPS = "ops"
    META = "meta"


class Force(StrEnum):
    """The normative force of a rule. See SCHEMA.md section 3.2."""

    BINDING = "BINDING"
    ADVISORY = "ADVISORY"
    OPEN = "OPEN"


_FRONT_MATTER = re.compile(r"\A---\r?\n(?P<yaml>.*?)\r?\n---\r?\n", re.DOTALL)

## ``### TYPE-012 · Domain code carries no `Any`  [BINDING] [auto:mypy]``
_RULE_HEADING = re.compile(
    r"^###\s+"
    r"(?P<id>[A-Z][A-Z0-9]{1,7}-\d{3})"
    r"\s*(?:·|\|)\s*"
    r"(?P<title>.+?)"
    r"\s*(?P<tags>(?:\[[^\]]+\]\s*)+)$"
)
_TAG = re.compile(r"\[([^\]]+)\]")
_FIELD = re.compile(
    r"^\s*[-*]\s+\*\*(?P<name>Why|Check|See|No mechanism|Superseded by)\*\*\s*(?P<body>.*)$"
)

## ``[TYPE-012]`` / ``[law/TYPE]`` / ``[fact/py-typing#strict-flags]``
_XREF = re.compile(r"\[(?P<target>(?:[A-Z][A-Z0-9]{1,7}-\d{3})|(?:[a-z]+/[A-Za-z0-9_-]+(?:#[a-z0-9-]+)?))\]")

## A version literal adjacent to a tool name, forbidden in ``law`` bodies.
_PINNED_TOOLS: Final = (
    "mypy", "pyright", "ruff", "pytest", "hypothesis", "coverage",
    "mutmut", "pydantic", "python", "cpython", "import-linter",
)
_VERSION_NEAR_TOOL = re.compile(
    r"(?i)\b(?P<tool>" + "|".join(_PINNED_TOOLS) + r")\b[^\n.]{0,24}?(?P<ver>\d+\.\d+(?:\.\d+)?)"
)

_CODE_FENCE = re.compile(r"^\s*```")
_INLINE_CODE = re.compile(r"`[^`\n]*`")


@dataclass(frozen=True, slots=True)
class Rule:
    """One normative rule, parsed from its H3 block."""

    rule_id: str
    module_id: str
    title: str
    force: Force
    mechanisms: tuple[str, ...]
    statement: str
    why: str | None
    check: str | None
    see: tuple[str, ...]
    no_mechanism: str | None
    superseded_by: str | None
    path: Path
    line: int

    @property
    def prefix(self) -> str:
        """The module prefix embedded in the rule id, e.g. ``TYPE``."""
        return self.rule_id.rsplit("-", 1)[0]

    @property
    def ordinal(self) -> int:
        return int(self.rule_id.rsplit("-", 1)[1])


@dataclass(frozen=True, slots=True)
class Document:
    """One parsed corpus file."""

    path: Path
    front_matter: Mapping[str, object]
    body: str
    body_offset: int
    rules: tuple[Rule, ...] = field(default=())

    @property
    def doc_id(self) -> str:
        raw = self.front_matter.get("id")
        return raw if isinstance(raw, str) else ""

    @property
    def kind(self) -> Kind | None:
        raw = self.front_matter.get("kind")
        if isinstance(raw, str):
            try:
                return Kind(raw)
            except ValueError:
                return None
        return None

    @property
    def module_name(self) -> str:
        """The ``NAME`` half of ``kind/NAME``."""
        return self.doc_id.split("/", 1)[-1] if "/" in self.doc_id else self.doc_id

    @property
    def relpath(self) -> str:
        return self.path.relative_to(REPO_ROOT).as_posix()

    @property
    def is_generated(self) -> bool:
        return self.path.name in GENERATED_NAMES


class ParseError(ValueError):
    """Raised when a file cannot be parsed far enough to be checked."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def _strip_code(text: str, *, inline: bool = True) -> str:
    """Blank out code, preserving line numbering.

    Fenced blocks are always removed. Inline spans are removed by default, which
    makes backticks the way to write a *format example* of a rule id or reference
    without it being read as a live one.
    """
    out: list[str] = []
    inside = False
    for line in text.splitlines():
        if _CODE_FENCE.match(line):
            inside = not inside
            out.append("")
            continue
        if inside:
            out.append("")
            continue
        out.append(_INLINE_CODE.sub(lambda m: " " * len(m.group(0)), line) if inline else line)
    return "\n".join(out)


def parse_document(path: Path) -> Document:
    """Parse one corpus file into front-matter, body and rules."""
    text = path.read_text(encoding="utf-8")
    match = _FRONT_MATTER.match(text)
    if match is None:
        raise ParseError(path, "no YAML front-matter")
    try:
        loaded = yaml.safe_load(match.group("yaml"))
    except yaml.YAMLError as exc:
        raise ParseError(path, f"front-matter is not valid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ParseError(path, "front-matter is not a mapping")
    # YAML parses an unquoted ISO date into a date object. Normalize back to the
    # string form the schema declares, so authors need not remember to quote it.
    loaded = {
        key: value.isoformat() if isinstance(value, datetime.date) else value
        for key, value in loaded.items()
    }

    body = text[match.end() :]
    body_offset = text[: match.end()].count("\n")
    doc = Document(path=path, front_matter=loaded, body=body, body_offset=body_offset)
    rules = tuple(_parse_rules(doc))
    return Document(
        path=path,
        front_matter=loaded,
        body=body,
        body_offset=body_offset,
        rules=rules,
    )


def _parse_rules(doc: Document) -> Iterator[Rule]:
    # Rule headings inside code fences are format examples, not rules; inline code
    # is kept so a statement may quote an identifier.
    lines = _strip_code(doc.body, inline=False).splitlines()
    for index, line in enumerate(lines):
        heading = _RULE_HEADING.match(line)
        if heading is None:
            continue
        tags = [t.strip() for t in _TAG.findall(heading.group("tags"))]
        force = _force_from_tags(tags)
        if force is None:
            continue
        mechanisms = tuple(t for t in tags if t not in {f.value for f in Force})
        block = _block_after(lines, index)
        yield Rule(
            rule_id=heading.group("id"),
            module_id=doc.doc_id,
            title=heading.group("title").strip(),
            force=force,
            mechanisms=mechanisms,
            statement=_statement_of(block),
            why=_field_of(block, "Why"),
            check=_field_of(block, "Check"),
            see=tuple(_XREF.findall(_field_of(block, "See") or "")),
            no_mechanism=_field_of(block, "No mechanism"),
            superseded_by=_field_of(block, "Superseded by"),
            path=doc.path,
            line=doc.body_offset + index + 1,
        )


def _force_from_tags(tags: Sequence[str]) -> Force | None:
    for tag in tags:
        try:
            return Force(tag)
        except ValueError:
            continue
    return None


def _block_after(lines: Sequence[str], index: int) -> list[str]:
    """Lines belonging to the rule that starts at ``index``, exclusive of its heading."""
    block: list[str] = []
    for line in lines[index + 1 :]:
        if line.startswith("#"):
            break
        block.append(line)
    return block


def _statement_of(block: Sequence[str]) -> str:
    parts: list[str] = []
    for line in block:
        if _FIELD.match(line):
            break
        if line.strip():
            parts.append(line.strip())
    return " ".join(parts)


def _field_of(block: Sequence[str], name: str) -> str | None:
    collected: list[str] = []
    capturing = False
    for line in block:
        found = _FIELD.match(line)
        if found is not None:
            if capturing:
                break
            if found.group("name") == name:
                capturing = True
                collected.append(found.group("body").strip())
            continue
        if capturing:
            if not line.strip():
                break
            collected.append(line.strip())
    return " ".join(collected) if collected else None


def iter_documents(root: Path = DISCIPLINE_DIR) -> Iterator[Document]:
    """Yield every parsable corpus document, in stable path order."""
    for path in sorted(root.rglob("*.md")):
        if path.name in GENERATED_NAMES:
            continue
        yield parse_document(path)


def prose_of(doc: Document) -> str:
    """Document body with all code removed, for text-level checks."""
    return _strip_code(doc.body)


def body_without_fences(doc: Document) -> str:
    """Document body with fenced blocks removed but inline code intact.

    The right scope for scanning document mentions: a filename inside a fenced
    example is illustration, one in a sentence is a live reference.
    """
    return _strip_code(doc.body, inline=False)


def find_version_literals(prose: str) -> list[tuple[str, str]]:
    """Return ``(tool, version)`` pairs found in prose. See SCHEMA.md section 1."""
    return [(m.group("tool"), m.group("ver")) for m in _VERSION_NEAR_TOOL.finditer(prose)]


def find_xrefs(text: str) -> list[str]:
    """Every cross-reference target in ``text``."""
    return _XREF.findall(text)


def count_tokens(text: str) -> int:
    """Token count, measured with tiktoken where available.

    Falls back to a character-ratio estimate when the encoding cannot be
    downloaded, so a validation run never fails for lack of network.
    """
    encoding = _encoding()
    if encoding is None:
        return round(len(text) / 3.7)
    return len(encoding.encode(text))


@lru_cache(maxsize=1)
def _encoding() -> object | None:
    """The tokenizer, constructed once.

    Building it per call made a validation run take over a minute: the graph
    measures every rule and the builders measure every file. None selects the
    character-ratio estimate instead.
    """
    try:
        import tiktoken
    except ImportError:
        return None
    try:
        return tiktoken.get_encoding("o200k_base")
    except Exception:  # ruff: ignore[blind-except] - no network, no cached vocabulary
        return None


def budget_for(doc: Document) -> int:
    return TOKEN_BUDGETS.get(doc.path.stem, TOKEN_BUDGETS["*"])
