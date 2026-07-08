"""Probe trigger and control bytes to find fan override."""

import ctypes
import struct
import time
import sys

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 3
OPEN_EXISTING = 3
IOCTL_EC_READ = 2621482120
IOCTL_EC_WRITE = 2621482124
DEVICE_PATH = r"\\.\ACPIDriver"

kernel32 = ctypes.windll.kernel32


def open_dev():
    h = kernel32.CreateFileW(DEVICE_PATH, GENERIC_READ | GENERIC_WRITE, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
    if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
        raise OSError(f"open failed {ctypes.get_last_error()}")
    return h


def close_dev(h):
    kernel32.CloseHandle(h)


def ec_read(h, addr):
    inbuf = struct.pack("<II", addr, 1)
    out = ctypes.c_int(0)
    kernel32.DeviceIoControl(h, IOCTL_EC_READ, inbuf, len(inbuf), ctypes.byref(out), 4, None, None)
    return out.value & 0xFF


def ec_write(h, addr, value):
    inbuf = struct.pack("<II", addr, value & 0xFF)
    out = ctypes.c_int(0)
    kernel32.DeviceIoControl(h, IOCTL_EC_WRITE, inbuf, len(inbuf), ctypes.byref(out), 4, None, None)


def snapshot(h):
    rpm = ec_read(h, 1124) * 256 + ec_read(h, 1125)
    dl = ec_read(h, 1883)
    dr = ec_read(h, 1884)
    ctrl = ec_read(h, 1873)
    trig = ec_read(h, 1885)
    return rpm, dl, dr, ctrl, trig


def main():
    h = open_dev()
    try:
        # Write duty table to 255
        for addr in range(3872, 3888):
            ec_write(h, addr, 255)

        rpm0, dl0, dr0, ctrl0, trig0 = snapshot(h)
        print(f"Before: rpm={rpm0} dl={dl0} dr={dr0} ctrl={ctrl0} trig={trig0}")

        # Test trigger byte 1885
        print("\n--- Trigger byte sweep (1885) ---")
        for val in [1, 2, 3, 0x80, 0xFF]:
            ec_write(h, 1885, val)
            time.sleep(0.5)
            rpm, dl, dr, ctrl, trig = snapshot(h)
            d = " *** DUTY CHANGED ***" if (dl != dl0 or dr != dr0) else ""
            print(f"  trigger={val:3d} => ctrl={ctrl} dl={dl} dr={dr} rpm={rpm}{d}")
        ec_write(h, 1885, trig0)

        # Test control byte 1873
        print("\n--- Control byte sweep (1873) ---")
        for val in [0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 24, 32, 64, 128, 144, 160, 192, 208, 224, 240, 255]:
            ec_write(h, 1873, val)
            time.sleep(0.3)
            rpm, dl, dr, ctrl, trig = snapshot(h)
            d = " *** DUTY CHANGED ***" if (dl != dl0 or dr != dr0) else ""
            print(f"  ctrl={val:3d} => dl={dl} dr={dr} rpm={rpm}{d}")

        # Restore control
        ec_write(h, 1873, ctrl0)
        print(f"\nRestored control to {ctrl0}")
    finally:
        close_dev(h)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
