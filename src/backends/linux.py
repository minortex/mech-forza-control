"""Linux EC I/O backends.

The project-specific kernel bridge is the default. Legacy backends remain
available only when explicitly selected with ``MFC_EC_BACKEND``.
"""

import fcntl
import glob
import mmap
import os
import struct

from src.config import EC_MMIO_BASE, EC_MMIO_SIZE


# Linux generic ioctl encoding (asm-generic/ioctl.h).
_IOC_NRBITS = 8
_IOC_TYPEBITS = 8
_IOC_SIZEBITS = 14
_IOC_NRSHIFT = 0
_IOC_TYPESHIFT = _IOC_NRSHIFT + _IOC_NRBITS
_IOC_SIZESHIFT = _IOC_TYPESHIFT + _IOC_TYPEBITS
_IOC_DIRSHIFT = _IOC_SIZESHIFT + _IOC_SIZEBITS
_IOC_WRITE = 1
_IOC_READ = 2

_EC_IO = struct.Struct("=HBB")


def _ioc(direction: int, ioctl_type: int, number: int, size: int) -> int:
    return (
        (direction << _IOC_DIRSHIFT)
        | (ioctl_type << _IOC_TYPESHIFT)
        | (number << _IOC_NRSHIFT)
        | (size << _IOC_SIZESHIFT)
    )


_IOCTL_MAGIC = ord("M")
MECHREVO_EC_IOC_READ = _ioc(_IOC_READ | _IOC_WRITE, _IOCTL_MAGIC, 0x00, _EC_IO.size)
MECHREVO_EC_IOC_WRITE = _ioc(_IOC_WRITE, _IOCTL_MAGIC, 0x01, _EC_IO.size)
MECHREVO_EC_IOC_UPDATE_BITS = _ioc(
    _IOC_READ | _IOC_WRITE, _IOCTL_MAGIC, 0x02, _EC_IO.size
)


class KernelEcBackend:
    """EC byte I/O through the minimal ``mechrevo-ec`` kernel driver."""

    DEVICE_PATH = "/dev/mechrevo-ec"

    def __init__(self):
        self._fd = None

    def open(self):
        if self._fd is None:
            self._fd = os.open(
                self.DEVICE_PATH, os.O_RDWR | getattr(os, "O_CLOEXEC", 0)
            )

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def _ensure_open(self):
        if self._fd is None:
            self.open()

    def _call(self, request: int, addr: int, value: int = 0, mask: int = 0):
        self._ensure_open()
        data = bytearray(_EC_IO.pack(addr, value, mask))
        fcntl.ioctl(self._fd, request, data, True)
        return _EC_IO.unpack(data)

    def ec_read(self, addr):
        _, value, _ = self._call(MECHREVO_EC_IOC_READ, addr)
        return value

    def ec_write(self, addr, value):
        self._call(MECHREVO_EC_IOC_WRITE, addr, value)

    def ec_rmw(self, addr, set_bits=0, clear_bits=0):
        # src.io semantics are: (old | set_bits) & ~clear_bits. If a bit is
        # present in both arguments, clearing wins.
        set_bits &= 0xFF
        clear_bits &= 0xFF
        mask = set_bits | clear_bits
        replacement = set_bits & ~clear_bits
        _, result, _ = self._call(
            MECHREVO_EC_IOC_UPDATE_BITS, addr, replacement, mask
        )
        return result


class DevMemBackend:
    def __init__(self):
        self._fd = None
        self._map = None

    def open(self):
        if self._fd is not None:
            return
        fd = os.open("/dev/mem", os.O_RDWR | os.O_SYNC)
        try:
            ec_map = mmap.mmap(fd, EC_MMIO_SIZE, offset=EC_MMIO_BASE)
        except Exception:
            os.close(fd)
            raise
        self._fd = fd
        self._map = ec_map

    def close(self):
        if self._map is not None:
            self._map.close()
            self._map = None
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def ec_read(self, addr):
        if self._map is None:
            raise RuntimeError("/dev/mem EC mmap not open")
        return self._map[addr]

    def ec_write(self, addr, value):
        if self._map is None:
            raise RuntimeError("/dev/mem EC mmap not open")
        self._map[addr] = value & 0xFF


class AcpiCallBackend:
    PROC_PATH = "/proc/acpi/call"
    READ_CMD = "\\_SB.INOU.ECRR 0x%04X"
    WRITE_CMD = "\\_SB.INOU.ECRW 0x%04X 0x%02X"

    def open(self):
        if not os.path.exists(self.PROC_PATH):
            raise RuntimeError(
                self.PROC_PATH + " not found; try: sudo modprobe acpi_call"
            )

    def close(self):
        pass

    def ec_read(self, addr):
        with open(self.PROC_PATH, "w") as f:
            f.write(self.READ_CMD % addr + "\n")
        with open(self.PROC_PATH) as f:
            return int(f.read().strip(), 0) & 0xFF

    def ec_write(self, addr, value):
        with open(self.PROC_PATH, "w") as f:
            f.write(self.WRITE_CMD % (addr, value) + "\n")


_BACKEND_TYPES = {
    "kernel": KernelEcBackend,
    "acpi-call": AcpiCallBackend,
    "devmem": DevMemBackend,
}


def _open_backend(backend_type):
    backend = backend_type()
    try:
        backend.open()
    except Exception:
        try:
            backend.close()
        except Exception:
            pass
        raise
    return backend


def select_backend():
    name = os.environ.get("MFC_EC_BACKEND", "kernel").strip().lower()

    if name == "auto":
        errors = []
        for backend_name in ("kernel", "acpi-call", "devmem"):
            try:
                return _open_backend(_BACKEND_TYPES[backend_name])
            except Exception as exc:
                errors.append(f"  {backend_name}: {exc}")
        raise RuntimeError("No EC access method:\n" + "\n".join(errors))

    backend_type = _BACKEND_TYPES.get(name)
    if backend_type is None:
        choices = ", ".join((*_BACKEND_TYPES, "auto"))
        raise ValueError(f"unknown MFC_EC_BACKEND={name!r}; choose one of: {choices}")

    try:
        return _open_backend(backend_type)
    except Exception as exc:
        if name == "kernel":
            raise RuntimeError(
                f"Cannot open {KernelEcBackend.DEVICE_PATH}: {exc}\n"
                "Install and load the mech-forza-kmod driver first. Legacy access is "
                "available only by explicitly setting MFC_EC_BACKEND=acpi-call "
                "or MFC_EC_BACKEND=devmem."
            ) from exc
        raise


def is_ac_power():
    for p in glob.glob("/sys/class/power_supply/*/online"):
        try:
            with open(p) as f:
                return f.read().strip() == "1"
        except OSError:
            continue
    return True
