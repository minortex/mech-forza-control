"""Backend protocol for EC byte I/O."""

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
