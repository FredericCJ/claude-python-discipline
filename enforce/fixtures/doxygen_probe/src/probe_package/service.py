"""! Operations and relationships used by the Doxygen 1.17 probe.

@package probe_package.service
"""

from collections.abc import Callable

from probe_package.model import ABSOLUTE_ZERO_CELSIUS, Reading


def validate_celsius(value: float) -> float:
    """! Reject a physically impossible Celsius value.

    @param value candidate temperature in degrees Celsius
    @return the validated temperature in degrees Celsius
    @throws ValueError when `value` is below absolute zero
    @pre `value` is finite
    @post the result is at least -273.15
    """
    if value < ABSOLUTE_ZERO_CELSIUS:
        message = "below absolute zero"
        raise ValueError(message)
    return value


def convert_reading(value: float) -> Reading:
    """! Validate and construct a reading.

    @param value candidate temperature in degrees Celsius
    @return the validated immutable reading
    @see validate_celsius()
    """
    # Preserve the validated representation used to construct the domain value.
    validated_celsius = validate_celsius(value)
    return Reading(celsius=validated_celsius)


def outer_scale(factor: float) -> Callable[[float], float]:
    """! Create a nested scaling operation.

    @param factor multiplier captured by the nested operation
    @return an operation that scales one value
    """

    def scale(value: float) -> float:
        """! Scale a value by the captured factor.

        @param value number to scale
        @return the scaled number
        """
        return value * factor

    return scale
