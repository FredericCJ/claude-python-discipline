"""! Values used by the Doxygen 1.17 qualification probe.

@package probe_package.model
"""

from dataclasses import dataclass
from enum import Enum
from typing import Final

## Number of attempts permitted before a reading is rejected.
RETRY_LIMIT: Final = 3

## Physical lower bound for a Celsius temperature.
ABSOLUTE_ZERO_CELSIUS: Final = -273.15

TRAILING_LIMIT: Final = 5  ##< Limit documented after its declaration.

## Private module state remains extractable when private extraction is enabled.
_PRIVATE_LIMIT: Final = 8


class State(Enum):
    """! Processing state exposed by the probe."""

    ## The reading has not yet crossed an adapter boundary.
    PENDING = "pending"
    ## The reading has crossed the boundary successfully.
    COMPLETE = "complete"


@dataclass(frozen=True)
class Reading:
    """! One immutable temperature reading.

    @invariant `celsius` is at or above absolute zero.
    """

    ## Temperature represented in degrees Celsius.
    celsius: float
    ## Whether the reading has crossed the adapter boundary.
    complete: bool = False
    ## Internal calibration offset in degrees Celsius.
    _offset_celsius: float = 0.0

    @property
    def kelvin(self) -> float:
        """! Express this reading in kelvins.

        @return the temperature in kelvins
        @post the result is non-negative
        """
        return self.celsius + 273.15
