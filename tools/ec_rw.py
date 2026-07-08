"""Low-level EC byte read / write / dump via ACPI driver."""

import argparse
import ctypes
import struct
import sys

# --- Win32 constants ---
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 3
OPEN_EXISTING = 3
IOCTL_EC_READ = 2621482120   # 0x9C402488
IOCTL_EC_WRITE = 2621482124  # 0x9C40248C
DEVICE_PATH = r"\\.\ACPIDriver"

kernel32 = ctypes.windll.kernel32


# ---------- device helpers ----------

def open_device():
    h = kernel32.CreateFileW(
        DEVICE_PATH,
        GENERIC_READ | GENERIC_WRITE,
        FILE_SHARE_RW,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if h == -1 or h == 0xFFFFFFFFFFFFFFFF:
        raise OSError(f"Cannot open {DEVICE_PATH}, error={ctypes.get_last_error()}")
    return h


def close_device(h):
    kernel32.CloseHandle(h)


# ---------- EC primitives ----------

def ec_read(h, addr):
    inbuf = struct.pack("<II", addr, 1)
    out = ctypes.c_int(0)
    ret = kernel32.DeviceIoControl(
        h, IOCTL_EC_READ, inbuf, len(inbuf), ctypes.byref(out), 4, None, None
    )
    if not ret:
        raise OSError(f"EC read failed at {addr}, error={ctypes.get_last_error()}")
    return out.value & 0xFF


def ec_write(h, addr, value):
    inbuf = struct.pack("<II", addr, value & 0xFF)
    out = ctypes.c_int(0)
    ret = kernel32.DeviceIoControl(
        h, IOCTL_EC_WRITE, inbuf, len(inbuf), ctypes.byref(out), 4, None, None
    )
    if not ret:
        raise OSError(f"EC write failed at {addr}, error={ctypes.get_last_error()}")


# ---------- commands ----------

def cmd_read(args):
    h = open_device()
    try:
        val = ec_read(h, args.addr)
        print(f"EC[{args.addr}] = {val} (0x{val:02X})")
    finally:
        close_device(h)


def cmd_write(args):
    h = open_device()
    try:
        before = ec_read(h, args.addr)
        ec_write(h, args.addr, args.value)
        after = ec_read(h, args.addr)
        print(f"EC[{args.addr}] : {before} (0x{before:02X}) -> {after} (0x{after:02X})")
    finally:
        close_device(h)


def cmd_dump(args):
    h = open_device()
    try:
        for addr in range(args.start, args.start + args.count):
            val = ec_read(h, addr)
            print(f"EC[{addr:4d}] = {val:3d} (0x{val:02X})")
    finally:
        close_device(h)


# ---------- entry ----------

def main():
    p = argparse.ArgumentParser(description="Low-level EC byte read / write / dump")
    sub = p.add_subparsers(dest="cmd")

    rp = sub.add_parser("read", help="Read one EC byte")
    rp.add_argument("addr", type=int, help="EC address")

    wp = sub.add_parser("write", help="Write one EC byte")
    wp.add_argument("addr", type=int, help="EC address")
    wp.add_argument("value", type=int, help="Byte value (0-255)")

    dp = sub.add_parser("dump", help="Dump EC byte range")
    dp.add_argument("start", type=int, help="Start address")
    dp.add_argument("count", type=int, nargs="?", default=16, help="Number of bytes")

    args = p.parse_args()
    if args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "write":
        cmd_write(args)
    elif args.cmd == "dump":
        cmd_dump(args)
    else:
        p.print_help()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
