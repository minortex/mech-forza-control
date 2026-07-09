#!/usr/bin/env python3
r"""Cross-platform EC I/O abstraction layer.

Reads DSDT to discover that the Mechrevo EC address space (up to 4 KB) is
backed by a flat MMIO window at physical address 0xFED50000.

Platform backends (auto-selected on import):

  Linux (preferred)  – /dev/mem mmap at 0xFED50000, 4 KB
  Linux (fallback)   – /proc/acpi/call via acpi_call module
                       (\SB.INOU.ECRR / \SB.INOU.ECRW)
  Windows            – \\.\ACPIDriver + DeviceIoControl

Usage:

  import ec_io

  val = ec_io.ec_read(0x0751)       # read 1 byte
  ec_io.ec_write(0x0751, 0xA0)      # write 1 byte
  val16 = ec_io.ec_read_word(0x078C) # read 16-bit (little-endian)
  val16 = ec_io.ec_read_word_be(0x1124, 0x1125)  # big-endian pair

  if ec_io.is_ac_power(): ...       # power source detection
  ec_io.close()                     # explicit teardown (optional)
"""

import atexit
import os
import platform
import struct
import sys

# ── EC MMIO geometry (from DSDT: INOU._CRS + ECRR/ECRW) ──────────────
EC_MMIO_BASE = 0xFED50000
EC_MMIO_SIZE = 0x1000          # 4 KB
EC_MMIO_MIN  = 0
EC_MMIO_MAX  = EC_MMIO_SIZE - 1


# ═══════════════════════════════════════════════════════════════════════
#  Windows backend  –  \\.\ACPIDriver + DeviceIoControl
# ═══════════════════════════════════════════════════════════════════════

if platform.system() == 'Windows':
    import ctypes
    from ctypes import wintypes as wt

    _kernel32 = ctypes.windll.kernel32

    GENERIC_READ  = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_RW = 3
    OPEN_EXISTING = 3
    IOCTL_EC_READ  = 2621482120   # 0x9C402488
    IOCTL_EC_WRITE = 2621482124   # 0x9C40248C
    DEVICE_PATH = r"\\.\ACPIDriver"

    class _WindowsBackend:
        def __init__(self):
            self._h = None

        def open(self):
            if self._h is not None:
                return
            h = _kernel32.CreateFileW(
                DEVICE_PATH,
                GENERIC_READ | GENERIC_WRITE,
                FILE_SHARE_RW, None, OPEN_EXISTING, 0, None,
            )
            if h in (-1, 0xFFFFFFFFFFFFFFFF):
                raise OSError(
                    f"Cannot open {DEVICE_PATH}, error={ctypes.get_last_error()}"
                )
            self._h = h

        def close(self):
            if self._h is not None:
                _kernel32.CloseHandle(self._h)
                self._h = None

        def ec_read(self, addr):
            self._ensure_open()
            inbuf = struct.pack("<II", addr, 1)
            out = ctypes.c_int(0)
            ret = _kernel32.DeviceIoControl(
                self._h, IOCTL_EC_READ, inbuf, len(inbuf),
                ctypes.byref(out), 4, None, None,
            )
            if not ret:
                raise OSError(
                    f"EC read failed at 0x{addr:04X}, "
                    f"error={ctypes.get_last_error()}"
                )
            return out.value & 0xFF

        def ec_write(self, addr, value):
            self._ensure_open()
            inbuf = struct.pack("<II", addr, value & 0xFF)
            out = ctypes.c_int(0)
            ret = _kernel32.DeviceIoControl(
                self._h, IOCTL_EC_WRITE, inbuf, len(inbuf),
                ctypes.byref(out), 4, None, None,
            )
            if not ret:
                raise OSError(
                    f"EC write failed at 0x{addr:04X}, "
                    f"error={ctypes.get_last_error()}"
                )

        def _ensure_open(self):
            try:
                self.open()
            except Exception:
                pass
            if self._h is None:
                raise RuntimeError(
                    "ACPIDriver not available; run as Administrator?"
                )

    def _is_ac_backend():
        """Return True if on AC power (Windows)."""
        class _SPS(ctypes.Structure):
            _fields_ = [
                ("ACLineStatus", ctypes.c_ubyte),
                ("BatteryFlag", ctypes.c_ubyte),
                ("BatteryLifePercent", ctypes.c_ubyte),
                ("Reserved1", ctypes.c_ubyte),
                ("BatteryLifeTime", ctypes.c_uint),
                ("BatteryFullLifeTime", ctypes.c_uint),
            ]
        sps = _SPS()
        if _kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            return sps.ACLineStatus == 1
        return True


# ═══════════════════════════════════════════════════════════════════════
#  Linux backends
# ═══════════════════════════════════════════════════════════════════════

else:
    import mmap

    class _DevMemBackend:
        """Direct MMIO access via /dev/mem at 0xFED50000."""

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

    class _AcpiCallBackend:
        """EC access via acpi_call kernel module -- /proc/acpi/call.

        Requires 'acpi_call' module:  sudo modprobe acpi_call
        """

        PROC_PATH = "/proc/acpi/call"

        def open(self):
            if not os.path.exists(self.PROC_PATH):
                raise RuntimeError(
                    f"{self.PROC_PATH} does not exist -- "
                    "load acpi_call:  sudo modprobe acpi_call"
                )

        def close(self):
            pass

        def ec_read(self, addr):
            self._call(f"\\_SB.INOU.ECRR 0x{addr:04X}")
            return _acpi_result_byte()

        def ec_write(self, addr, value):
            self._call(f"\\_SB.INOU.ECRW 0x{addr:04X} 0x{value:02X}")

        @staticmethod
        def _call(cmd):
            with open(_AcpiCallBackend.PROC_PATH, "w") as f:
                f.write(cmd + "\n")

    def _acpi_result_byte():
        with open(_AcpiCallBackend.PROC_PATH, "r") as f:
            raw = f.read().strip()
        # ACPI returns results like "0x5A" or "90"
        return int(raw, 0) & 0xFF

    def _is_ac_backend():
        """Return True if on AC power (Linux)."""
        for entry in os.listdir("/sys/class/power_supply/"):
            if entry.startswith("AC") or entry.startswith("C"):
                try:
                    with open(f"/sys/class/power_supply/{entry}/online") as f:
                        return f.read().strip() == "1"
                except OSError:
                    pass
            if entry.startswith("BAT"):
                try:
                    with open(f"/sys/class/power_supply/{entry}/online") as f:
                        return f.read().strip() == "0"
                except OSError:
                    pass
        return True  # assume AC if undetermined


# ── back-end selection (auto) ─────────────────────────────────────────

def _select_backend():
    """Pick the first working backend for the current platform."""
    system = platform.system()

    if system == "Windows":
        return _WindowsBackend()

    # Linux: try /dev/mem first, fall back to acpi_call
    for cls in (_DevMemBackend, _AcpiCallBackend):
        be = cls()
        try:
            be.open()
            be.ec_read(0)      # quick health check
            return be
        except Exception:
            try:
                be.close()
            except Exception:
                pass
            continue

    raise RuntimeError(
        "No EC access method available.\n"
        "  /dev/mem:  access denied or range unavailable\n"
        "  acpi_call: /proc/acpi/call not found\n"
        "  Try:  sudo modprobe acpi_call"
    )


# ── public functions ──────────────────────────────────────────────────

_BACKEND = None


def _get_backend():
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _select_backend()
        atexit.register(close)
    return _BACKEND


def open_ec():
    """Explicitly open the EC device (idempotent)."""
    _get_backend().open()


def close():
    """Explicitly close / tear down the EC backend."""
    global _BACKEND
    if _BACKEND is not None:
        try:
            _BACKEND.close()
        except Exception:
            pass
        _BACKEND = None


def ec_read(addr):
    """Read one byte from EC address *addr* (0 .. 0xFFF)."""
    if addr < EC_MMIO_MIN or addr > EC_MMIO_MAX:
        raise ValueError(
            f"EC address 0x{addr:04X} out of range "
            f"[{EC_MMIO_MIN}, {EC_MMIO_MAX}]"
        )
    return _get_backend().ec_read(addr)


def ec_write(addr, value):
    """Write *value* (byte, 0-255) to EC address *addr*."""
    if addr < EC_MMIO_MIN or addr > EC_MMIO_MAX:
        raise ValueError(
            f"EC address 0x{addr:04X} out of range "
            f"[{EC_MMIO_MIN}, {EC_MMIO_MAX}]"
        )
    if not 0 <= value <= 255:
        raise ValueError(f"EC value {value} out of range [0, 255]")
    _get_backend().ec_write(addr, value)


def ec_read_word(lo_addr):
    """Read a 16-bit little-endian word starting at *lo_addr*."""
    lo = ec_read(lo_addr)
    hi = ec_read(lo_addr + 1)
    return (hi << 8) | lo


def ec_read_word_be(hi_addr, lo_addr):
    """Read a 16-bit big-endian word with explicit hi/lo addresses."""
    hi = ec_read(hi_addr)
    lo = ec_read(lo_addr)
    return (hi << 8) | lo


def ec_rmw(addr, set_bits=0, clear_bits=0):
    """Atomic-ish read-modify-write on one EC byte.

    Reads *addr*, ORs *set_bits*, ANDs NOT *clear_bits*, writes back.
    Returns the new value.
    """
    val = ec_read(addr)
    val = (val | (set_bits & 0xFF)) & ~(clear_bits & 0xFF)
    ec_write(addr, val)
    return val


def is_ac_power():
    """Return True if the system is running on AC power."""
    return _is_ac_backend()
