"""Backend protocol for primitive EC byte I/O.

Block and transaction methods are optional capabilities discovered by
``src.io`` at runtime, so legacy and Windows backends only need byte access.
"""

from typing import Protocol


class EcBackend(Protocol):
    def open(self) -> None:
        """Open the backend if it is not already open."""

    def close(self) -> None:
        """Close the backend."""

    def ec_read(self, addr: int) -> int:
        """Read one EC byte."""

    def ec_write(self, addr: int, value: int) -> None:
        """Write one EC byte."""
