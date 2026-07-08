#!/usr/bin/env python3
"""Switch GCU power mode directly via EC on Windows (ACPIDriver).

Usage:
  python ec_switch_mode.py gaming
  python ec_switch_mode.py office
  python ec_switch_mode.py turbo
  python ec_switch_mode.py custom [--pl1 X --pl2 Y --pl4 Z]
  python ec_switch_mode.py status
"""

import argparse
import ctypes
import struct
import sys

# --- ACPI driver ---
GENERIC_READ  = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 3
OPEN_EXISTING = 3
IOCTL_EC_READ  = 2621482120   # 0x9C402488
IOCTL_EC_WRITE = 2621482124   # 0x9C40248C
DEVICE_PATH = r"\\.\ACPIDriver"

kernel32 = ctypes.windll.kernel32

# --- Key EC addresses ---
ADDR_MAFAN_CTL = 1873
ADDR_AP_OEM9   = 1830
ADDR_AP_OEM10  = 1831
ADDR_PL1       = 1923
ADDR_PL2       = 1924
ADDR_PL4       = 1925
ADDR_AP_OEM  = 1857      # 0x0741 – bit0 = ApExistFlag
ADDR_AP_CTL    = 1990

# EC 1873 values (no FanBoost)
CTL_NORMAL  = 0
CTL_TURBO   = 16
CTL_USER_HI = 160

# PL defaults from your EC dump
PL_DEFAULTS = {
    "gaming": (45, 45, 50),
    "office": (25, 25, 30),
    "turbo":  (73, 73, 90),
    "custom": (45, 45, 50),
}
PL_DC = (0, 0, 0)
# ---- Default CPU fan curve (16-point, CML format) ----
# From SetEcFanTable: EC[x] = upT[i+1] or 0xFF, EC[x+1] = dnT[i], EC[x+2] = duty*2
DEFAULT_CPU_FAN = {
    "upT":   [ 40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255],
    "dnT":   [ 35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90,  95],
    "duty":  [ 20, 25, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100],
}
DEFAULT_GPU_FAN = {
    "upT":   [ 40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255],
    "dnT":   [ 35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90,  95],
    "duty":  [ 10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100],
}


# ---------- EC primitives ----------

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
    if h in (-1, 0xFFFFFFFFFFFFFFFF):
        raise OSError(f"Cannot open {DEVICE_PATH}, error={ctypes.get_last_error()}")
    return h


def close_device(h):
    kernel32.CloseHandle(h)


def ec_read(h, addr):
    inbuf = struct.pack("<II", addr, 1)
    out = ctypes.c_int(0)
    if not kernel32.DeviceIoControl(h, IOCTL_EC_READ, inbuf, len(inbuf),
                                     ctypes.byref(out), 4, None, None):
        raise OSError(f"EC read failed at {addr}, error={ctypes.get_last_error()}")
    return out.value & 0xFF


def ec_write(h, addr, value):
    inbuf = struct.pack("<II", addr, value & 0xFF)
    out = ctypes.c_int(0)
    if not kernel32.DeviceIoControl(h, IOCTL_EC_WRITE, inbuf, len(inbuf),
                                     ctypes.byref(out), 4, None, None):
        raise OSError(f"EC write failed at {addr}, error={ctypes.get_last_error()}")


# ---------- helpers ----------

def _rmw(h, addr, set_bits=0, clear_bits=0):
    val = ec_read(h, addr)
    val = (val | set_bits) & ~clear_bits
    ec_write(h, addr, val)
    return val


def _is_ac():
    import ctypes.wintypes
    # kernel32.GetSystemPowerStatus
    class SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", ctypes.c_ubyte),
            ("BatteryFlag", ctypes.c_ubyte),
            ("BatteryLifePercent", ctypes.c_ubyte),
            ("Reserved1", ctypes.c_ubyte),
            ("BatteryLifeTime", ctypes.c_uint),
            ("BatteryFullLifeTime", ctypes.c_uint),
        ]
    sps = SYSTEM_POWER_STATUS()
    if kernel32.GetSystemPowerStatus(ctypes.byref(sps)):
        return sps.ACLineStatus == 1
    return True


# ---------- mode switch ----------

MODES = {
    "office": {
        "desc": "Office (silent)", "mode": 0,
        "ctl": CTL_USER_HI, "pl": PL_DEFAULTS["office"], "custom": False,
    },
    "gaming": {
        "desc": "Gaming (balanced)", "mode": 1,
        "ctl": CTL_NORMAL, "pl": PL_DEFAULTS["gaming"], "custom": False,
    },
    "turbo": {
        "desc": "Turbo (performance)", "mode": 2,
        "ctl": CTL_TURBO, "pl": None, "custom": False,
    },
    "custom": {
        "desc": "Custom (manual fan)", "mode": 3,
        "ctl": CTL_NORMAL, "pl": PL_DEFAULTS["custom"], "custom": True,
    },
}


def _write_fan_table(h, cpu=None, gpu=None):
    """Write CPU/GPU fan curve to EC 3840-3935 (SetEcFanTable CML format)."""
    cpu = cpu or DEFAULT_CPU_FAN
    gpu = gpu or DEFAULT_GPU_FAN
    for i in range(16):
        ec_write(h, 3840 + i, cpu['upT'][i + 1] if i < 15 else 255)
        if i < 15:
            ec_write(h, 3856 + i + 1, cpu['dnT'][i])
        ec_write(h, 3872 + i, min(cpu['duty'][i], 100) * 2)
        ec_write(h, 3888 + i, gpu['upT'][i + 1] if i < 15 else 255)
        if i < 15:
            ec_write(h, 3904 + i + 1, gpu['dnT'][i])
        ec_write(h, 3920 + i, min(gpu['duty'][i], 100) * 2)


def switch_mode(h, name, pl1=None, pl2=None, pl4=None, tcc=0, separate=False):
    m = MODES.get(name)
    if m is None:
        raise ValueError(f"unknown mode: {name}")

    if m["pl"] is not None and pl1 is None:
        pl1, pl2, pl4 = m["pl"]
    elif m["pl"] is None and pl1 is None:
        if _is_ac():
            pl1, pl2, pl4 = PL_DEFAULTS["turbo"]
        else:
            pl1, pl2, pl4 = PL_DC
        print(f"  Turbo PL (AC={_is_ac()}): {pl1}/{pl2}/{pl4}")
    pl1 = pl1 or 0; pl2 = pl2 or 0; pl4 = pl4 or 0

    print(f"  Mode: {m['desc']} (operating={m['mode']})")
    print(f"  PL:   {pl1}/{pl2}/{pl4}")

    # re-enable AP control
    _rmw(h, ADDR_AP_CTL, set_bits=0x04)
    val = ec_read(h, ADDR_AP_CTL)
    ok = "OK" if val & 4 else "FAIL"
    print(f"  EC[{ADDR_AP_CTL}] AP_CTL  = {val} (0x{val:02x})  bit2={ok}")

    if m["custom"]:
        _rmw(h, ADDR_AP_OEM10, set_bits=0x40)
    else:
        _rmw(h, ADDR_AP_OEM10, clear_bits=0x40)

    # toggle AP control off, write fan table, then on (matching SetFanTable flow)
    # mark AP as alive (EC 1857 bit0) – matches Set_APExistToEC(true)
    _rmw(h, ADDR_AP_OEM, set_bits=0x01)

    _rmw(h, ADDR_AP_CTL, clear_bits=0x04)
    if m["custom"]:
        _write_fan_table(h)

    # FanSwitchSpeed = minimum (value=100 -> 1s transition)
    _rmw(h, ADDR_AP_CTL, clear_bits=0x04)  # ensure AP exists before write
    ec_write(h, 1927, 0x81)                # 1s slew rate, enable
    ec_write(h, 1926, tcc | 0x80)          # TCC offset (0=disabled, bit7=enable)
    ec_write(h, 1989, 0x80 if separate else 0x00)  # FanControlRespective (bit7=1=separate)
    _rmw(h, ADDR_AP_CTL, set_bits=0x04)

    ec_write(h, ADDR_PL1, pl1 & 0xFF)
    ec_write(h, ADDR_PL2, pl2 & 0xFF)
    ec_write(h, ADDR_PL4, pl4 & 0xFF)

    ec_write(h, ADDR_MAFAN_CTL, m["ctl"])

    # re-enable AP control only after mode byte is set
    # re-enable AP control
    _rmw(h, ADDR_AP_CTL, set_bits=0x04)

    if m["custom"]:
        _rmw(h, ADDR_AP_OEM9, set_bits=0x80)
    else:
        _rmw(h, ADDR_AP_OEM9, clear_bits=0x80)

    # verify
    got = ec_read(h, ADDR_MAFAN_CTL)
    oem9 = ec_read(h, ADDR_AP_OEM9)
    oem57 = ec_read(h, ADDR_AP_OEM)
    sws = ec_read(h, 1927)
    tcc_val = ec_read(h, 1926)
    print(f"  EC[1857] ApExist  = {oem57} (0x{oem57:02x})  bit0={oem57&1}")
    print(f"  EC[1830] OEM9     = {oem9} (0x{oem9:02x})  bit7={(oem9>>7)&1}")
    print(f"  EC[1927] SwSpeed  = {sws} (0x{sws:02x})  {f'{sws&0x7F}s' if sws&0x80 else 'instant'}")
    resp = ec_read(h, 1989)
    print(f"  EC[1989] Respct  = {resp} (0x{resp:02x})  bit7={(resp>>7)&1}")
    print(f"  EC[1926] TCC      = {tcc_val} (0x{tcc_val:02x})  Tj-{tcc_val&0x7F}C" if tcc_val&0x80 else f"  EC[1926] TCC      = disabled")
    ok = "OK" if got == m["ctl"] else f"FAIL expected {m['ctl']}"
    print(f"  EC[{ADDR_MAFAN_CTL}] CTL    = {got} (0x{got:02x})  {ok}")
    return True


# ---------- status ----------

EC_1873_LABELS = {
    0: "Normal (Gaming/Custom)", 16: "Turbo",
    64: "FanBoost", 80: "Turbo+FanBoost",
    128: "User_Fan", 160: "HiMode (Office)", 224: "HiMode+FanBoost",
}


def show_status(h):
    ctl = ec_read(h, ADDR_MAFAN_CTL)
    pl1 = ec_read(h, ADDR_PL1); pl2 = ec_read(h, ADDR_PL2); pl4 = ec_read(h, ADDR_PL4)
    oem9 = ec_read(h, ADDR_AP_OEM9); oem10 = ec_read(h, ADDR_AP_OEM10)
    oem57 = ec_read(h, ADDR_AP_OEM)
    ap = ec_read(h, ADDR_AP_CTL)
    label = EC_1873_LABELS.get(ctl, "?")
    custom = " (custom)" if oem9 & 0x80 else ""
    print("[EC Status]")
    print(f"  EC[1873] CTL    = {ctl} (0x{ctl:02x})  {label}{custom}")
    print(f"  EC[1830] OEM9   = {oem9} (0x{oem9:02x})  bit7={oem9>>7}")
    print(f"  EC[1831] OEM10  = {oem10} (0x{oem10:02x})  bit6={(oem10>>6)&1}")
    print(f"  EC[1857] AP_OEM = {oem57} (0x{oem57:02x})  bit0={oem57&1} (ApExist)")
    print(f"  EC[1990] AP_CTL = {ap} (0x{ap:02x})  bit2={(ap>>2)&1}")
    print(f"  PL:  {pl1}/{pl2}/{pl4}")


# ---------- CLI ----------

def main():
    p = argparse.ArgumentParser(description="Switch GCU mode directly via EC")
    sub = p.add_subparsers(dest="cmd", required=True)

    for name, m in MODES.items():
        sp = sub.add_parser(name, help=m["desc"])
        sp.set_defaults(action="switch", mode_name=name)
        if name in ("custom", "turbo"):
            sp.add_argument("--pl1", type=int, default=None, help="PL1 / SPL")
            sp.add_argument("--pl2", type=int, default=None, help="PL2 / SPPT")
            sp.add_argument("--pl4", type=int, default=None, help="PL4 / FPPT")
        if name == "custom":
            sp.add_argument("--tcc", type=int, default=0,
                help="TCC offset 0-31 (0=disable, 15=Tj-15C)")
            sp.add_argument("--separate", action="store_true",
                help="Separate fan curves (bit7=1)")

    sp = sub.add_parser("status", help="Show current EC state")
    sp.set_defaults(action="status")
    sp = sub.add_parser("dump", help="Dump key EC registers")
    sp.set_defaults(action="dump")

    args = p.parse_args()

    h = open_device()
    try:
        if args.action == "switch":
            switch_mode(h, args.mode_name,
                        getattr(args, "pl1", None),
                        getattr(args, "pl2", None),
                        getattr(args, "pl4", None),
                        getattr(args, "tcc", 0),
                        getattr(args, "separate", False))
        elif args.action == "status":
            show_status(h)
        elif args.action == "dump":
            for addr in range(1829, 1829 + 16):
                val = ec_read(h, addr)
                print(f"  EC[{addr}] = {val:3d} (0x{val:02x})")
            for addr in range(1989, 1989 + 6):
                val = ec_read(h, addr)
                print(f"  EC[{addr}] = {val:3d} (0x{val:02x})")
    finally:
        close_device(h)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

