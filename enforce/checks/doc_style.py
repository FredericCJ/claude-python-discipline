"""Documentation says what an element guarantees, in a form Doxygen can read.

Enforces DOC-004 (docstrings where Python has a slot), DOC-008 (types are not
restated in prose), DOC-009 (the contract, not the name and not the mechanism)
and DOC-010 (no code span that breaks the Doxygen build). DOC-008/009/010 apply
equally to `##` blocks: `doc_coverage` proves one is present; this module reads
what it says.

Deliberately narrow. Whether a sentence is *informative* is a reading judgment no
check can make; what is checkable is the detectable half — documentation that
merely restates the identifier, that duplicates a type the signature already
carries, or that is written in a form the engine will not parse.
"""

from __future__ import annotations

import ast
import re
from typing import TYPE_CHECKING

from . import Finding, ModuleCheck, main
from .doc_coverage import EXEMPT_NAMES, _named_assignments
from .documentation_model import governed_paths

# Import annotation-only collection contracts without runtime dependencies.
if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence
    from pathlib import Path

## Unordered filler-word set whose each element carries no semantic content by itself.
FILLER = frozenset({
    "a",
    "an",
    "the",
    "this",
    "that",
    "of",
    "for",
    "to",
    "and",
    "or",
    "is",
    "it",
    "helper",
    "function",
    "method",
    "class",
    "module",
    "utility",
    "wrapper",
    "returns",
    "return",
    "get",
    "gets",
    "set",
    "sets",
    "do",
    "does",
    "handle",
    "handles",
    "process",
    "processes",
    "simple",
    "basic",
    "internal",
})

## A type restated in prose -- naming a parameter's type in parens or after a
## colon following its name, when the signature already carries it. Written
## here without the literal trigger spelled out in full: this block is itself
## read by the check it describes, so an example in the exact shape it hunts
## for would flag its own comment.
_TYPE_IN_PROSE = re.compile(
    r"@param\s+\**\w+\s*(?:\(\s*(?:int|str|bool|float|bytes|list|dict|set|tuple|"
    r"Path|Sequence|Mapping|Iterable|Iterator|Optional|Any)\b[^)]*\)|"
    r":\s*(?:int|str|bool|float|bytes|list|dict|set|tuple)\b)",
    re.IGNORECASE,
)

## The return-value counterpart of the pattern above: a type named in parens or
## after a colon, following @return or @returns -- again the signature's job.
_TYPE_IN_RETURN = re.compile(
    r"@(?:return|returns)\s*(?:\(\s*(?:int|str|bool|float|bytes|list|dict|set|tuple|"
    r"None)\s*\)|(?:int|str|bool|float|bytes|list|dict|set|tuple|None)\s*:)",
    re.IGNORECASE,
)

## Word tokens, for comparing a summary against an identifier.
_WORD = re.compile(r"[a-z0-9]+")
## Maximum informative-word count eligible for the conservative restatement predicate.
MAX_RESTATEMENT_WORDS = 4
## Minimum remaining stem length permitting an inflectional suffix removal.
MIN_STEM_LENGTH = 3

## A code span whose content ends in a single period, which Doxygen cannot parse.
## Established by bisection against doxygen 1.10.0: a span holding foo. or x. or
## a.b. aborts the comment block, while one holding an ellipsis, a leading dot,
## foo.bar or plain foo is read normally -- so the trigger is a final period
## preceded by anything but another period. The examples here are deliberately
## written without code spans around them: an earlier draft of this very comment
## put them in spans and broke the documentation build, which is how the gap
## below was found. Doxygen catches this too, but reports only an unclosed inline
## code tag, naming neither the span nor the remedy.
##
## This check now reads a `##` block like this one as well as a docstring, so
## a span written the broken way here would flag its own comment -- which is
## exactly how the gap this paragraph once described was found and closed.
_TRAILING_DOT_SPAN = re.compile(r"`([^`\n]*[^.`]\.)`")


class DocStyleCheck(ModuleCheck):
    """Report documentation that is unparseable, redundant or empty of content."""

    ## Invoked as `python -m checks.doc_style`.
    name = "doc_style"
    ## Rule-id elements in deterministic reporting order; each has an independent predicate.
    rules = ("DOC-004", "DOC-008", "DOC-009", "DOC-010")

    def run(self, paths: Sequence[Path]) -> list[Finding]:
        """Inspect all production, test, maintenance, and generated Python.

        @param paths fallback path elements in caller order when the model is unavailable
        @return finding elements in governed scope order
        """
        # Replace caller narrowing with the documentation model's complete governed path sequence.
        return super().run(governed_paths(self.declaration, paths))

    def visit_module(self, tree: ast.Module, path: Path, _layer: str) -> Iterator[Finding]:
        """Yield findings for every badly formed documentation comment in `tree`.

        @param tree the parsed module
        @param path the file it came from
        @param _layer the architectural layer, unused here
        @return finding elements in entity walk then hash-block order

        @par Effects
        Reads the source file at ``path`` once because Doxygen hash comments are absent from ASTs.
        """
        # Read source-line elements in order for adjacent hash-block allocation and content.
        source = path.read_text(encoding="utf-8").splitlines()

        # Inspect function and class entities for Doxygen-compatible docstring style.
        for node in ast.walk(tree):
            # Only functions and classes own Python docstring entity slots here.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                # Advance without interpreting unrelated syntax nodes.
                continue
            # Extract the entity's Python docstring without inherited cleanup.
            docstring = ast.get_docstring(node)
            # Absence may still reveal a misplaced Doxygen hash block.
            if docstring is None:
                # Absence is DOC-001's business, not this check's.
                # Yield only a wrong-allocation finding, never duplicate missing coverage.
                yield from self._misplaced_block(node, path, source)
                # Advance because content predicates require actual documentation text.
                continue
            # Yield type, Doxygen parse, and restatement findings in stable predicate order.
            yield from self._content(node, docstring, path)

        # Inspect module and class value hash blocks after all docstring-capable entities.
        yield from self._hash_block_content(tree, path, source)

    def _misplaced_block(self, node: ast.AST, path: Path, source: list[str]) -> Iterator[Finding]:
        """Report a `##` block used where a docstring belongs.

        @param node the element
        @param path the file it came from
        @param source source-line elements in file order
        @return one finding when documentation was written in the wrong form
        """
        # Resolve the entity's one-based source line with a stable fallback.
        lineno = getattr(node, "lineno", 1)
        # Start at the immediately preceding zero-based source-line index.
        index = lineno - 2
        # Walk upward through the contiguous comment block nearest the entity.
        while index >= 0 and source[index].strip().startswith("#"):
            # A Doxygen hash marker proves documentation was authored in the wrong slot.
            if source[index].strip().startswith("##"):
                # Resolve a stable display name for classes and callables.
                name = getattr(node, "name", "element")
                # Yield the wrong-form finding at the entity line.
                yield Finding(
                    "DOC-004",
                    path,
                    lineno,
                    f"{name} is documented with a ## block instead of a docstring",
                    "Move it into the docstring; a ## block is invisible to help(), "
                    "to editors and to every other Python tool.",
                )
                # Stop after the first marker because one entity allocation reports once.
                return
            # Continue upward through ordinary comment lines in the same contiguous block.
            index -= 1

    def _content(self, node: ast.AST, docstring: str, path: Path) -> Iterator[Finding]:
        """Report a docstring that restates the name or duplicates a type.

        @param node the documented element
        @param docstring its docstring
        @param path the file it came from
        @return findings for redundant or contentless documentation
        """
        # Resolve the entity's one-based source line with a stable fallback.
        lineno = getattr(node, "lineno", 1)
        # Resolve a stable entity display name, or empty text for another node shape.
        name = getattr(node, "name", "")

        # Inspect each type-restatement pattern/rule/message tuple in fixed order.
        for pattern, rule, message in (
            (_TYPE_IN_PROSE, "DOC-008", "a parameter's type is restated in the prose"),
            (_TYPE_IN_RETURN, "DOC-008", "the return type is restated in the prose"),
        ):
            # A matched parameter or result form duplicates signature-owned type information.
            if pattern.search(docstring):
                # Yield the redundant-type finding at the entity line.
                yield Finding(
                    rule,
                    path,
                    lineno,
                    f"{name}: {message}",
                    "The signature carries the type; the documentation carries the "
                    "meaning. A type written twice diverges once.",
                )

        # Inspect each broken code-span text element in document occurrence order.
        for span in _TRAILING_DOT_SPAN.findall(docstring):
            # Yield the Doxygen parse-risk finding at the owning entity line.
            yield Finding(
                "DOC-010",
                path,
                lineno,
                f"{name}: the code span `{span}` ends in a period, which breaks the Doxygen build",
                "Move the period outside the span: write `foo`. rather than "
                '`foo.`. Doxygen reports this only as "end of comment block '
                "while expecting command </tt>\", naming neither the file's real "
                "problem nor the fix.",
            )

        # A summary whose informative vocabulary comes only from the name adds no contract.
        if _restates_the_name(name, docstring):
            # Yield the identifier-restatement finding at the entity line.
            yield Finding(
                "DOC-009",
                path,
                lineno,
                f"{name}: the documentation only restates the name",
                "Say what it guarantees -- the result, the invariant, the failure mode. "
                "A comment that repeats the identifier answers nothing.",
            )

    def _hash_block_content(
        self, tree: ast.Module, path: Path, source: list[str]
    ) -> Iterator[Finding]:
        """Report a `##` block that restates a name, a type, or breaks the Doxygen build.

        The same content rules DOC-008/DOC-009/DOC-010 hold docstrings to,
        applied to the `##` blocks documenting module constants, class
        attributes, dataclass fields and enum members -- forms
        `doc_coverage` locates but never reads the text of, since it only
        proves a block is present.

        @param tree the parsed module
        @param path the file it came from
        @param source source-line elements in file order for reading block text
        @return finding elements in module-value then class/value and predicate order
        """
        # Inspect each module-level named assignment pair in source order.
        for target, lineno in _named_assignments_in(tree.body):
            # Explicit exempt names have no Doxygen entity documentation obligation.
            if target in EXEMPT_NAMES:
                # Advance without applying content rules where coverage does not apply.
                continue
            # Yield content findings for this module value in stable predicate order.
            yield from self._hash_block_at(target, target, lineno, path, source)

        # Inspect class bodies for value documentation allocated through hash blocks.
        for node in ast.walk(tree):
            # Only classes own class-level value blocks.
            if not isinstance(node, ast.ClassDef):
                # Advance without interpreting unrelated syntax nodes.
                continue
            # Inspect each class-body named assignment pair in source order.
            for target, lineno in _named_assignments_in(node.body):
                # Explicit exempt names have no Doxygen entity documentation obligation.
                if target in EXEMPT_NAMES:
                    # Advance to the next class value.
                    continue
                # Yield content findings with a class-qualified display identity.
                yield from self._hash_block_at(
                    target,
                    f"{node.name}.{target}",
                    lineno,
                    path,
                    source,
                )

    def _hash_block_at(
        self, bare_name: str, display_name: str, lineno: int, path: Path, source: list[str]
    ) -> Iterator[Finding]:
        """Report content faults in the `##` block documenting one named value.

        Silent when no block is found: absence is DOC-002's business, not
        this check's.

        @param bare_name the identifier alone, for the restates-the-name test
        @param display_name the identifier as shown in a finding, qualified
            with its class when the value is an attribute
        @param lineno the 1-based line the value is bound on
        @param path the file it came from
        @param source source-line elements in file order
        @return finding elements for a restated type, broken code span, or
            summary that adds nothing beyond the name
        """
        # Resolve the contiguous Doxygen hash-block text immediately above the value.
        text = _hash_block_text(source, lineno)
        # Absence is owned by coverage and produces no duplicate content finding.
        if text is None:
            # Stop iteration for this value.
            return

        # Inspect each type-restatement pattern/rule/message tuple in fixed order.
        for pattern, rule, message in (
            (_TYPE_IN_PROSE, "DOC-008", "a parameter's type is restated in the prose"),
            (_TYPE_IN_RETURN, "DOC-008", "the return type is restated in the prose"),
        ):
            # A matched parameter or result form duplicates signature-owned type information.
            if pattern.search(text):
                # Yield the redundant-type finding at the value binding line.
                yield Finding(
                    rule,
                    path,
                    lineno,
                    f"{display_name}: {message}",
                    "The signature carries the type; the documentation carries the "
                    "meaning. A type written twice diverges once.",
                )

        # Inspect each broken code-span text element in block occurrence order.
        for span in _TRAILING_DOT_SPAN.findall(text):
            # Yield the Doxygen parse-risk finding at the owning value line.
            yield Finding(
                "DOC-010",
                path,
                lineno,
                f"{display_name}: the code span `{span}` ends in a period, which "
                f"breaks the Doxygen build",
                "Move the period outside the span: write `foo`. rather than "
                '`foo.`. Doxygen reports this only as "end of comment block '
                "while expecting command </tt>\", naming neither the file's real "
                "problem nor the fix.",
            )

        # A summary whose informative vocabulary comes only from the name adds no meaning.
        if _restates_the_name(bare_name, text):
            # Yield the identifier-restatement finding at the value line.
            yield Finding(
                "DOC-009",
                path,
                lineno,
                f"{display_name}: the documentation only restates the name",
                "Say what it guarantees -- the result, the invariant, the failure mode. "
                "A comment that repeats the identifier answers nothing.",
            )


def _named_assignments_in(statements: list[ast.stmt]) -> Iterator[tuple[str, int]]:
    """Every name bound at the top of a module or class body, with its line.

    Thin pass-through over `doc_coverage._named_assignments`, one statement
    at a time, so this module walks a body the same way `doc_coverage` does
    rather than a second, differently-behaved way.

    @param statements top-level statement elements in source order from a module or class
    @return bound-name/one-based-line pair elements in statement order
    """
    # Inspect each top-level statement element in source order.
    for statement in statements:
        # Delegate binding extraction so coverage and content share exact supported forms.
        yield from _named_assignments(statement)


def _hash_block_text(source: list[str], lineno: int) -> str | None:
    """The text of the `##` block documenting the value bound at `lineno`.

    Walks upward exactly as `doc_coverage._has_hash_block` does -- through
    contiguous `#`-prefixed lines, stopping at the first that is not one --
    so presence and content agree on what counts as the block. Returns the
    text with each line's leading `#` markers and surrounding space removed
    and joined back into reading order.

    @param source source-line elements in file order
    @param lineno the 1-based line the value is bound on
    @return the block's text, or None when no `##` line precedes it
    """
    # Accumulate stripped comment-text elements while walking upward in reverse source order.
    collected: list[str] = []
    # Track marker presence: false means only ordinary narration seen; true means at least one
    # Doxygen entity line belongs to the block.
    saw_hash_block = False
    # Start at the immediately preceding zero-based source-line index.
    index = lineno - 2
    # Walk upward until reaching the file head or a non-comment boundary.
    while index >= 0:
        # Normalize surrounding whitespace for marker classification and extraction.
        line = source[index].strip()
        # Doxygen hash lines contribute entity documentation and satisfy block presence.
        if line.startswith("##"):
            # Set marker presence true because a Doxygen line was seen; false would still mean
            # the contiguous block contains ordinary narration only.
            saw_hash_block = True
            # Append stripped content after both marker characters.
            collected.append(line[2:].strip())
            # Move to the preceding source line.
            index -= 1
            # Continue upward within the same contiguous comment block.
            continue
        # Ordinary hash lines may be continuations belonging to a Doxygen-started block.
        if line.startswith("#"):
            # Append stripped continuation content after one marker character.
            collected.append(line[1:].strip())
            # Move to the preceding source line.
            index -= 1
            # Continue upward within the same contiguous comment block.
            continue
        # A non-comment line terminates the nearest association block.
        break
    # A contiguous ordinary-comment block alone does not document a named Doxygen entity.
    if not saw_hash_block:
        # Return explicit absence for caller-owned coverage behavior.
        return None
    # Reverse collected text back into source reading order and join line elements.
    return "\n".join(reversed(collected))


def _restates_the_name(name: str, docstring: str) -> bool:
    """Whether a docstring's summary adds nothing beyond the identifier.

    True only when every informative word in the first line already appears in
    the name. Conservative on purpose: a false positive here would push authors
    toward padding, which is the failure this rule exists to avoid.

    An all-capitals name is split on its underscores alone. Splitting it before
    each capital instead turns `MAX_RETRIES` into eleven single letters, which
    no summary can be a subset of -- so the rule was silent on exactly the
    elements a `##` block documents, module constants and enum members, where
    upper case is the convention rather than the exception.

    @param name the element's identifier
    @param docstring its docstring
    @return true when the summary carries no word absent from the name; false otherwise
    """
    # Select the first stripped documentation-line element, or empty text for no content.
    summary = docstring.strip().splitlines()[0] if docstring.strip() else ""
    # Build an unordered set whose each element is a stemmed informative summary word.
    words = {_stem(w) for w in _WORD.findall(summary.lower()) if w not in FILLER}
    # Empty summaries and longer prose are not the narrow detectable restatement shape.
    if not words or len(words) > MAX_RESTATEMENT_WORDS:
        # Reject the summary from this conservative predicate.
        return False
    # Preserve all-uppercase underscore boundaries; otherwise expose camel-case word boundaries.
    split_name = (name if name.isupper() else re.sub(r"(?<!^)(?=[A-Z])", " ", name)).lower()
    # Build an unordered set whose each element is a stemmed identifier word.
    from_name = {_stem(w) for w in _WORD.findall(split_name)}
    # A subset proves every informative summary word was already present in the identifier.
    return words <= from_name


def _stem(word: str) -> str:
    """A crude root, so `parses`, `parsing` and `parse` compare equal.

    Both sides of the comparison are stemmed the same way, so the stem only has
    to be consistent, not linguistically correct.

    @param word one lowercase word
    @return its root form
    """
    # Inspect suffix elements in longest-transform-first order.
    for suffix in ("ing", "ed"):
        # Strip only when the remaining root meets the minimum useful length.
        if word.endswith(suffix) and len(word) - len(suffix) >= MIN_STEM_LENGTH:
            # Replace the word with its bounded suffix-free root.
            word = word[: -len(suffix)]
            # Stop after one inflectional suffix transformation.
            break
    # Normalize a trailing plural marker then terminal silent e consistently on both sides.
    return word.removesuffix("s").removesuffix("e")


# Permit direct module execution through the common checker command-line adapter.
if __name__ == "__main__":
    # Translate the checker result into the process exit status.
    raise SystemExit(main(DocStyleCheck()))
