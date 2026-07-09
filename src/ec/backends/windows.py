"""Windows EC I/O backend using ACPIDriver."""

import ctypes
import struct

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 3
OPEN_EXISTING = 3
IOCTL_EC_READ = 2621482120
IOCTL_EC_WRITE = 2621482124
DEVICE_PATH = r"\\.\ACPIDriver"

_kernel32 = ctypes.windll.kernel32


class WindowsBackend:
    def __init__(self):
        self._h = None

    def open(self):
        if self._h is not None:
            return
        h = _kernel32.CreateFileW(
            DEVICE_PATH,
            GENERIC_READ | GENERIC_WRITE,
            FILE_SHARE_RW,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if h in (-1, 0xFFFFFFFFFFFFFFFF):
            raise OSError(
                "Cannot open " + DEVICE_PATH + ", error=" + str(ctypes.get_last_error())
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
        if not _kernel32.DeviceIoControl(
            self._h, IOCTL_EC_READ, inbuf, 8, ctypes.byref(out), 4, None, None
        ):
            raise OSError("EC read failed at 0x%04X" % addr)
        return out.value & 0xFF

    def ec_write(self, addr, value):
        self._ensure_open()
        inbuf = struct.pack("<II", addr, value & 0xFF)
        out = ctypes.c_int(0)
        if not _kernel32.DeviceIoControl(
            self._h, IOCTL_EC_WRITE, inbuf, 8, ctypes.byref(out), 4, None, None
        ):
            raise OSError("EC write failed at 0x%04X" % addr)

    def _ensure_open(self):
        try:
            self.open()
        except Exception:
            pass
        if self._h is None:
            raise RuntimeError("ACPIDriver not available; run as Administrator?")


class _SystemPowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("Reserved1", ctypes.c_ubyte),
        ("BatteryLifeTime", ctypes.c_uint),
        ("BatteryFullLifeTime", ctypes.c_uint),
    ]


def select_backend():
    return WindowsBackend()


def is_ac_power():
    sps = _SystemPowerStatus()
    if _kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
        return sps.ACLineStatus == 1
    return True
