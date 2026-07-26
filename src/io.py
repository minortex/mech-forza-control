r"""Cross-platform EC I/O.

Platform backends:
  Linux (default)   - /dev/mechrevo-ec MMIO bridge
  Linux (explicit)  - /proc/acpi/call or unsafe /dev/mem compatibility backends
  Windows           - \\.\ACPIDriver + DeviceIoControl
"""

import atexit
import platform
from dataclasses import dataclass
from typing import Iterable

from src.backends.base import EcBackend
from src.registers import EC_MMIO_MAX, EC_MMIO_MIN

EC_OP_READ = 0
EC_OP_WRITE = 1
EC_OP_UPDATE_BITS = 2
EC_BLOCK_MAX = 128
EC_TRANSACTION_MAX_OPS = 128


@dataclass(frozen=True, slots=True)
class EcOperation:
    """One operation in an atomic EC transaction."""

    type: int
    addr: int
    value: int = 0
    mask: int = 0


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


def _check_range(addr: int, length: int) -> None:
    _check_addr(addr)
    if length <= 0:
        raise ValueError("EC transfer length must be positive")
    if length > EC_MMIO_MAX - addr + 1:
        raise ValueError(
            "EC range 0x%04X..0x%04X out of range" % (addr, addr + length - 1)
        )


def _check_byte(value: int, label: str = "value") -> None:
    if not 0 <= value <= 0xFF:
        raise ValueError(f"EC {label} {value} out of range")


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
    _check_byte(value)
    _get_backend().ec_write(addr, value)


def ec_read_block(addr: int, length: int) -> bytes:
    """Read a contiguous EC range, using block ioctls when available."""
    _check_range(addr, length)
    backend = _get_backend()
    backend_read_block = getattr(backend, "ec_read_block", None)
    if callable(backend_read_block):
        chunks = []
        offset = 0
        while offset < length:
            chunk_length = min(EC_BLOCK_MAX, length - offset)
            chunks.append(backend_read_block(addr + offset, chunk_length))
            offset += chunk_length
        return b"".join(chunks)
    return bytes(backend.ec_read(addr + offset) for offset in range(length))


def ec_write_block(addr: int, data: bytes | bytearray | memoryview) -> None:
    """Write a contiguous EC range, using block ioctls when available."""
    payload = bytes(data)
    _check_range(addr, len(payload))
    backend = _get_backend()
    backend_write_block = getattr(backend, "ec_write_block", None)
    if callable(backend_write_block):
        offset = 0
        while offset < len(payload):
            chunk = payload[offset : offset + EC_BLOCK_MAX]
            backend_write_block(addr + offset, chunk)
            offset += len(chunk)
        return
    for offset, value in enumerate(payload):
        backend.ec_write(addr + offset, value)


def ec_transaction(operations: Iterable[EcOperation]) -> list[int]:
    """Execute up to 128 EC operations under one backend transaction lock.

    Native kernel backends execute the whole vector under one device mutex.
    Backends without transaction support retain compatibility by executing the
    same operations sequentially in userspace.
    """
    ops = list(operations)
    if not ops:
        return []
    if len(ops) > EC_TRANSACTION_MAX_OPS:
        raise ValueError(
            f"EC transaction accepts at most {EC_TRANSACTION_MAX_OPS} operations"
        )
    for op in ops:
        if not isinstance(op, EcOperation):
            raise TypeError("EC transaction entries must be EcOperation instances")
        _check_addr(op.addr)
        if op.type not in (EC_OP_READ, EC_OP_WRITE, EC_OP_UPDATE_BITS):
            raise ValueError(f"unknown EC operation type {op.type}")
        _check_byte(op.value)
        _check_byte(op.mask, "mask")

    backend = _get_backend()
    backend_transaction = getattr(backend, "ec_transaction", None)
    if callable(backend_transaction):
        results = list(backend_transaction(ops))
        if len(results) != len(ops):
            raise RuntimeError("EC backend returned the wrong transaction result count")
        return results

    results = []
    for op in ops:
        if op.type == EC_OP_READ:
            result = backend.ec_read(op.addr)
        elif op.type == EC_OP_WRITE:
            backend.ec_write(op.addr, op.value)
            result = op.value
        else:
            current = backend.ec_read(op.addr)
            result = (current & ~op.mask) | (op.value & op.mask)
            backend.ec_write(op.addr, result)
        results.append(result)
    return results


def ec_read_word(lo_addr: int) -> int:
    lo, hi = ec_read_block(lo_addr, 2)
    return (hi << 8) | lo


def ec_read_word_be(hi_addr: int, lo_addr: int) -> int:
    hi, lo = ec_transaction(
        (
            EcOperation(EC_OP_READ, hi_addr),
            EcOperation(EC_OP_READ, lo_addr),
        )
    )
    return (hi << 8) | lo


def ec_rmw(addr: int, set_bits: int = 0, clear_bits: int = 0) -> int:
    _check_addr(addr)
    set_bits &= 0xFF
    clear_bits &= 0xFF
    backend = _get_backend()
    backend_rmw = getattr(backend, "ec_rmw", None)
    if callable(backend_rmw):
        return backend_rmw(addr, set_bits, clear_bits)

    mask = set_bits | clear_bits
    replacement = set_bits & ~clear_bits
    return ec_transaction(
        (EcOperation(EC_OP_UPDATE_BITS, addr, replacement, mask),)
    )[0]


def is_ac_power() -> bool:
    if platform.system() == "Windows":
        from src.backends import windows

        return windows.is_ac_power()

    from src.backends import linux

    return linux.is_ac_power()
