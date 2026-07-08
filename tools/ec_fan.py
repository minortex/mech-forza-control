"""EC fan read / monitor via ACPI driver."""

import argparse
import ctypes
import struct
import sys
import time

# --- constants ---
GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 3
OPEN_EXISTING = 3
IOCTL_EC_READ = 2621482120
DEVICE_PATH = r"\\.\ACPIDriver"

# --- EC addresses ---
ADDR_MAIN_FAN_RPM_H = 1124
ADDR_MAIN_FAN_RPM_L = 1125
ADDR_SEC_FAN_RPM_H = 1132
ADDR_SEC_FAN_RPM_L = 1131
ADDR_FAN_CONTROL = 1873
ADDR_MAIN_FAN_DUTY = 1883
ADDR_SEC_FAN_DUTY = 1884

kernel32 = ctypes.windll.kernel32


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


def ec_read(h, addr):
    inbuf = struct.pack("<II", addr, 1)
    out = ctypes.c_int(0)
    ret = kernel32.DeviceIoControl(
        h, IOCTL_EC_READ, inbuf, len(inbuf), ctypes.byref(out), 4, None, None
    )
    if not ret:
        raise OSError(f"EC read failed at {addr}, error={ctypes.get_last_error()}")
    return out.value & 0xFF


def read_fans(h):
    rpm_mh = ec_read(h, ADDR_MAIN_FAN_RPM_H)
    rpm_ml = ec_read(h, ADDR_MAIN_FAN_RPM_L)
    rpm_sh = ec_read(h, ADDR_SEC_FAN_RPM_H)
    rpm_sl = ec_read(h, ADDR_SEC_FAN_RPM_L)
    ctrl = ec_read(h, ADDR_FAN_CONTROL)
    duty_main = ec_read(h, ADDR_MAIN_FAN_DUTY)
    duty_sec = ec_read(h, ADDR_SEC_FAN_DUTY)
    return {
        "main_rpm": rpm_mh * 256 + rpm_ml,
        "sec_rpm": rpm_sh * 256 + rpm_sl,
        "control": ctrl,
        "control_bin": f"0b{ctrl:08b}",
        "duty_main": duty_main,
        "duty_sec": duty_sec,
    }


def cmd_read(args):
    h = open_device()
    try:
        d = read_fans(h)
        print(f"Main fan (Right) RPM : {d['main_rpm']}")
        print(f"Sec  fan (Left)  RPM : {d['sec_rpm']}")
        print(f"Control byte         : {d['control']} ({d['control_bin']})")
        print(f"Duty Main(R) / Sec(L): {d['duty_main']} / {d['duty_sec']}")
    finally:
        close_device(h)


def cmd_monitor(args):
    interval = args.interval
    print(f"Monitoring every {interval}s, Ctrl+C to stop\n")
    print(f"{'Time':>8}  {'MainRPM':>7}  {'SecRPM':>7}  {'Ctrl':>5}  {'DutyM(R)':>8}  {'DutyS(L)':>8}")
    print("-" * 60)
    h = open_device()
    try:
        while True:
            d = read_fans(h)
            print(
                f"{time.strftime('%H:%M:%S')}  {d['main_rpm']:>7}  {d['sec_rpm']:>7}"
                f"  {d['control']:>5}  {d['duty_main']:>8}  {d['duty_sec']:>8}",
                flush=True,
            )
            time.sleep(interval)
    finally:
        close_device(h)


def main():
    p = argparse.ArgumentParser(description="EC fan read / monitor")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("read", help="Read fan RPM, duty, control byte")

    mon = sub.add_parser("monitor", help="Continuously monitor fan status")
    mon.add_argument("-i", "--interval", type=float, default=1.0)

    args = p.parse_args()
    if args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "monitor":
        cmd_monitor(args)
    else:
        p.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
