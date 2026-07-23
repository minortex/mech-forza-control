"""Linux EC I/O backends."""

import glob
import mmap
import os

from src.config import EC_MMIO_BASE, EC_MMIO_SIZE


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


def select_backend():
    for cls in (DevMemBackend, AcpiCallBackend):
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
        "  Try:  sudo modprobe acpi_call"
    )


def is_ac_power():
    for p in glob.glob("/sys/class/power_supply/*/online"):
        try:
            with open(p) as f:
                return f.read().strip() == "1"
        except OSError:
            continue
    return True
