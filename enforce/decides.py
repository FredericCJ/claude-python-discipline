"""What a fitness test decides, declared where a machine can read it.

A `[check:<name>]` tag has been resolvable against the check's own `rules` tuple
since v3.0.0, and doing so found that eight checks named seventeen rules they
could never report -- five of them saying so in their own docstrings while the
tuple claimed the rule anyway. Nothing read the tuple, so nothing noticed.

**A `fitness:` tag had the same defect and no tuple to fix it with.** It resolved
by searching for `def <name>(` and answering yes if the text was found anywhere:
existence, not agreement. Sixty-four binding rules rested on that answer, and
seventeen fitness functions carried more than one rule between them -- the exact
one-mechanism-many-claims shape that was wrong 23% of the time on the check side.
`OPEN-015` recorded the consequence: `V080` was a floor rather than a count.

This decorator is the missing half. It gives a fitness function the same thing a
check has -- a written list of what it decides, beside the code that decides it,
where the two drift apart under review rather than silently.

    @decides("ARCH-009", "TEST-005", "TEST-006")
    def test_contract_suite_per_adapter() -> None:

**Nothing at runtime depends on it.** The function is returned unchanged, so a
decorated test runs exactly as it did before and pytest collects it identically.
The declaration is read by `tools/discipline_core.py::rules_declared_by`, which
parses the source rather than importing it, for the same reason the check side
does: `build_index.py` takes the census and must not execute a test suite to find
out what it claims.

**An undecorated function declares nothing, and a rule resting on it is reported
undecided.** That is deliberate and it is the whole point. The alternative --
treating a missing declaration as consent, the way the check arm treats a missing
`rules` tuple -- would leave every unmigrated function claiming whatever its tags
happened to say, which is the state this module exists to end.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

## The shape of a rule id, as `discipline/meta/SCHEMA.md` defines it: a family in
## capitals, a hyphen, three digits. Checked at import time so a typo fails when
## the suite is collected rather than resolving to a rule that does not exist and
## quietly deciding nothing.
RULE_ID: re.Pattern[str] = re.compile(r"^[A-Z]{3,6}-\d{3}$")

## The attribute the declaration is stored under. Named for what it is rather
## than prefixed private, because `rules_declared_by` reads the source and a
## reader comparing the two needs to see the same word in both places.
ATTRIBUTE: str = "__decides__"

## The decorated function's own type, so `@decides` is transparent to a type
## checker: what goes in comes back out, and a decorated test keeps its signature
## rather than degrading to an untyped callable.
_F = TypeVar("_F", bound="Callable[..., object]")


def decides(*rule_ids: str) -> Callable[[_F], _F]:
    """Declare the rules a fitness test decides, and return it unchanged.

    Refuses an empty list. `@decides()` reads as a declaration while asserting
    nothing, which is worse than no decorator at all: it looks migrated. A test
    that decides no rule should carry no decorator and no `fitness:` tag.

    @param rule_ids every rule this test decides, each in `FAMILY-NNN` form
    @return a decorator that records the ids on the function and returns it
    @raise ValueError if no rule is named, or one is not a well-formed rule id
    """
    if not rule_ids:
        msg = (
            "@decides() names no rule. A test that decides nothing should "
            "carry no decorator, and no rule should tag it."
        )
        raise ValueError(msg)
    malformed = [rule for rule in rule_ids if not RULE_ID.match(rule)]
    if malformed:
        msg = (
            f"not rule ids: {', '.join(malformed)}. Expected FAMILY-NNN, "
            f"as discipline/meta/SCHEMA.md defines it."
        )
        raise ValueError(msg)

    def record(function: _F) -> _F:
        """Attach the declaration and hand the function back untouched.

        @param function the fitness test being declared
        @return the same object, so collection and execution are unaffected
        """
        setattr(function, ATTRIBUTE, frozenset(rule_ids))
        return function

    return record
