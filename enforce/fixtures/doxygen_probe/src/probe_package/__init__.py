"""! Doxygen 1.17 qualification package.

@package probe_package
@brief Exercise the Python entity and relationship forms required by v5.
"""

from probe_package.model import Reading, State
from probe_package.service import convert_reading

## Public symbol-name elements in stable export order for qualification output.
__all__ = ["Reading", "State", "convert_reading"]
