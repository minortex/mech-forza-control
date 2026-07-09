r"""Cross-platform EC I/O - flat MMIO at 0xFED50000 (DSDT INOU device).

Platform backends:
  Linux (preferred) - /dev/mem mmap at 0xFED50000, 4 KB
  Linux (fallback)  - /proc/acpi/call via acpi_call module (SB.INOU.ECRR / ECRW)
  Windows           - \\.\ACPIDriver + DeviceIoControl
"""

import atexit
import os
import platform
import struct
import sys

EC_MMIO_BASE = 0xFED50000
EC_MMIO_SIZE = 0x1000
EC_MMIO_MIN  = 0
EC_MMIO_MAX  = EC_MMIO_SIZE - 1


# ── Windows backend ──────────────────────────────────────────────────

if platform.system() == 'Windows':
    import ctypes
    from ctypes import wintypes as wt

    _kernel32 = ctypes.windll.kernel32
    GENERIC_READ  = 0x80000000
    GENERIC_WRITE = 0x40000000
    FILE_SHARE_RW = 3
    OPEN_EXISTING = 3
    IOCTL_EC_READ  = 2621482120
    IOCTL_EC_WRITE = 2621482124
    DEVICE_PATH = r"\\.\ACPIDriver"

    class _WindowsBackend:
        def __init__(self):
            self._h = None

        def open(self):
            if self._h is not None:
                return
            h = _kernel32.CreateFileW(DEVICE_PATH, GENERIC_READ | GENERIC_WRITE,
                                      FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
            if h in (-1, 0xFFFFFFFFFFFFFFFF):
                raise OSError("Cannot open " + DEVICE_PATH + ", error=" + str(ctypes.get_last_error()))
            self._h = h

        def close(self):
            if self._h is not None:
                _kernel32.CloseHandle(self._h)
                self._h = None

        def ec_read(self, addr):
            self._ensure_open()
            inbuf = struct.pack("<II", addr, 1)
            out = ctypes.c_int(0)
            if not _kernel32.DeviceIoControl(self._h, IOCTL_EC_READ, inbuf, 8,
                                              ctypes.byref(out), 4, None, None):
                raise OSError("EC read failed at 0x%04X" % addr)
            return out.value & 0xFF

        def ec_write(self, addr, value):
            self._ensure_open()
            inbuf = struct.pack("<II", addr, value & 0xFF)
            out = ctypes.c_int(0)
            if not _kernel32.DeviceIoControl(self._h, IOCTL_EC_WRITE, inbuf, 8,
                                              ctypes.byref(out), 4, None, None):
                raise OSError("EC write failed at 0x%04X" % addr)

        def _ensure_open(self):
            try:
                self.open()
            except Exception:
                pass
            if self._h is None:
                raise RuntimeError("ACPIDriver not available; run as Administrator?")

    def _is_ac_backend():
        class _SPS(ctypes.Structure):
            _fields_ = [("ACLineStatus", ctypes.c_ubyte), ("BatteryFlag", ctypes.c_ubyte),
                        ("BatteryLifePercent", ctypes.c_ubyte), ("Reserved1", ctypes.c_ubyte),
                        ("BatteryLifeTime", ctypes.c_uint), ("BatteryFullLifeTime", ctypes.c_uint)]
        sps = _SPS()
        if _kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
            return sps.ACLineStatus == 1
        return True

# ── Linux backends ──────────────────────────────────────────────────

else:
    import mmap

    class _DevMemBackend:
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
        PROC_PATH = "/proc/acpi/call"
        READ_CMD  = "\\_SB.INOU.ECRR 0x%04X"
        WRITE_CMD = "\\_SB.INOU.ECRW 0x%04X 0x%02X"

        def open(self):
            if not os.path.exists(self.PROC_PATH):
                raise RuntimeError(
                    self.PROC_PATH + " not found; try: sudo modprobe acpi_call")

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

    def _is_ac_backend():
        import glob
        for p in glob.glob("/sys/class/power_supply/*/online"):
            try:
                with open(p) as f:
                    return f.read().strip() == "1"
            except OSError:
                continue
        return True


# ── Backend selection ────────────────────────────────────────────────

def _select_backend():
    if platform.system() == "Windows":
        return _WindowsBackend()
    for cls in (_DevMemBackend, _AcpiCallBackend):
        be = cls()
        try:
            be.open()
            be.ec_read(0)
            return be
        except Exception:
            try:
                be.close()
            except Exception:
                pass
            continue
    raise RuntimeError(
        "No EC access method.\n"
        "  /dev/mem:  access denied or range unavailable\n"
        "  acpi_call: /proc/acpi/call not found\n"
        "  Try:  sudo modprobe acpi_call")


# ── Public API ───────────────────────────────────────────────────────

_BACKEND = None


def _get_backend():
    global _BACKEND
    if _BACKEND is None:
        _BACKEND = _select_backend()
        atexit.register(close)
    return _BACKEND


def open_ec():
    _get_backend().open()


def close():
    global _BACKEND
    if _BACKEND is not None:
        try:
            _BACKEND.close()
        except Exception:
            pass
        _BACKEND = None


def ec_read(addr):
    if addr < EC_MMIO_MIN or addr > EC_MMIO_MAX:
        raise ValueError("EC address 0x%04X out of range" % addr)
    return _get_backend().ec_read(addr)


def ec_write(addr, value):
    if addr < EC_MMIO_MIN or addr > EC_MMIO_MAX:
        raise ValueError("EC address 0x%04X out of range" % addr)
    if not 0 <= value <= 255:
        raise ValueError("EC value %d out of range" % value)
    _get_backend().ec_write(addr, value)


def ec_read_word(lo_addr):
    lo = ec_read(lo_addr)
    hi = ec_read(lo_addr + 1)
    return (hi << 8) | lo


def ec_read_word_be(hi_addr, lo_addr):
    hi = ec_read(hi_addr)
    lo = ec_read(lo_addr)
    return (hi << 8) | lo


def ec_rmw(addr, set_bits=0, clear_bits=0):
    val = (ec_read(addr) | (set_bits & 0xFF)) & ~(clear_bits & 0xFF)
    ec_write(addr, val)
    return val


def is_ac_power():
    return _is_ac_backend()
