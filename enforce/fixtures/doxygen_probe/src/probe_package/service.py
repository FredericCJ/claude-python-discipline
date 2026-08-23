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
    # Reject an impossible value before constructing any reading.
    if value < ABSOLUTE_ZERO_CELSIUS:
        # Preserve stable refusal detail for callers and qualification output.
        message = "below absolute zero"
        # Expose the boundary violation as the documented public exception.
        raise ValueError(message)
    # Return the unchanged value after the physical lower-bound check succeeds.
    return value


def convert_reading(value: float) -> Reading:
    """! Validate and construct a reading.

    @param value candidate temperature in degrees Celsius
    @return the validated immutable reading
    @see validate_celsius()
    """
    # Preserve the validated representation used to construct the domain value.
    validated_celsius = validate_celsius(value)
    # Construct the immutable reading only from the validated representation.
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
        # Apply the multiplier captured when the nested operation was created.
        return value * factor

    # Expose the configured nested operation to the caller.
    return scale
