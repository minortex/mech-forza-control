r"""Cross-platform EC byte I/O.

Platform backends:
  Linux (preferred) - /dev/mem mmap at 0xFED50000, 4 KB
  Linux (fallback)  - /proc/acpi/call via acpi_call module (SB.INOU.ECRR / ECRW)
  Windows           - \\.\ACPIDriver + DeviceIoControl
"""

import atexit
import platform

from src.backends.base import EcBackend
from src.config import EC_MMIO_MAX, EC_MMIO_MIN

_BACKEND: EcBackend | None = None
_ATEXIT_REGISTERED = False


def _select_backend() -> EcBackend:
    if platform.system() == "Windows":
        from src.backends import windows

        return windows.select_backend()

    from src.backends import linux

    return linux.select_backend()


def _get_backend() -> EcBackend:
    global _ATEXIT_REGISTERED, _BACKEND
    if _BACKEND is None:
        _BACKEND = _select_backend()
        if not _ATEXIT_REGISTERED:
            atexit.register(close)
            _ATEXIT_REGISTERED = True
    return _BACKEND


def _set_backend_for_testing(backend: EcBackend | None) -> None:
    global _BACKEND
    _BACKEND = backend


def _check_addr(addr: int) -> None:
    if addr < EC_MMIO_MIN or addr > EC_MMIO_MAX:
        raise ValueError("EC address 0x%04X out of range" % addr)


def open_ec() -> None:
    _get_backend().open()


def close() -> None:
    global _BACKEND
    if _BACKEND is not None:
        try:
            _BACKEND.close()
        except Exception:
            pass
        _BACKEND = None


def ec_read(addr: int) -> int:
    _check_addr(addr)
    return _get_backend().ec_read(addr)


def ec_write(addr: int, value: int) -> None:
    _check_addr(addr)
    if not 0 <= value <= 255:
        raise ValueError("EC value %d out of range" % value)
    _get_backend().ec_write(addr, value)


def ec_read_word(lo_addr: int) -> int:
    lo = ec_read(lo_addr)
    hi = ec_read(lo_addr + 1)
    return (hi << 8) | lo


def ec_read_word_be(hi_addr: int, lo_addr: int) -> int:
    hi = ec_read(hi_addr)
    lo = ec_read(lo_addr)
    return (hi << 8) | lo


def ec_rmw(addr: int, set_bits: int = 0, clear_bits: int = 0) -> int:
    val = (ec_read(addr) | (set_bits & 0xFF)) & ~(clear_bits & 0xFF)
    ec_write(addr, val)
    return val


def is_ac_power() -> bool:
    if platform.system() == "Windows":
        from src.backends import windows

        return windows.is_ac_power()

    from src.backends import linux

    return linux.is_ac_power()
