"""EC setting controls — Win key lock, Fn lock, USB charger, AC recovery.

Commands:
  ec setting status             — read current state
  ec setting winlock   on|off   — toggle Win key lock (trigger)
  ec setting fnlock     on|off  — toggle Fn lock (direct)
  ec setting usbchg     on|off  — toggle USB charging when off (direct)
  ec setting acrecov    on|off  — toggle AC recovery (ApExistFlag + XRAM[1830])
"""

import argparse

from .config import (
    ADDR_AP_OEM,
    ADDR_AP_OEM9,
    ADDR_BIOS_OEM_BYTE,
    ADDR_STATUS_BYTE,
    ADDR_TRIGGER_BYTE,
    SETTING_LABELS,
)
from .io import ec_read, ec_write


# ── helpers ──────────────────────────────────────────────────────────

def _ensure_ap_exist():
    """Set XRAM[1857] bit0 (ApExistFlag) if not already set.

    The official GCU Service always sets this on startup. Without it the
    EC may ignore writes to certain registers (e.g. AC Recovery 1830 bit3).
    """
    v = ec_read(ADDR_AP_OEM)
    if v & 1:
        return False
    ec_write(ADDR_AP_OEM, v | 1)
    print(f"  XRAM[0x{ADDR_AP_OEM:04X}] ApExistFlag: 0x{v:02x} -> set bit0=1")
    return True


def _bit(val, n):
    return (val >> n) & 1


def _rmw(addr, set_bits=0, clear_bits=0):
    v = (ec_read(addr) | (set_bits & 0xFF)) & ~(clear_bits & 0xFF)
    ec_write(addr, v)
    return v


def _show_status():
    t = ec_read(ADDR_TRIGGER_BYTE)
    s = ec_read(ADDR_STATUS_BYTE)
    f = ec_read(ADDR_BIOS_OEM_BYTE)
    a = ec_read(ADDR_AP_OEM9)
    e = ec_read(ADDR_AP_OEM)
    wl = _bit(s, 0)
    fl = _bit(f, 4)
    uc = _bit(t, 4)
    ac = _bit(a, 3)
    print(f"  Win lock    (XRAM[0x{ADDR_STATUS_BYTE:04X}] bit0): {wl} "
          f"({SETTING_LABELS['winlock']['on'] if wl else SETTING_LABELS['winlock']['off']})")
    print(f"  Fn lock     (XRAM[0x{ADDR_BIOS_OEM_BYTE:04X}] bit4): {fl} "
          f"({SETTING_LABELS['fnlock']['on'] if fl else SETTING_LABELS['fnlock']['off']})")
    print(f"  USB charger (XRAM[0x{ADDR_TRIGGER_BYTE:04X}] bit4): {uc} "
          f"({SETTING_LABELS['usbchg']['on'] if uc else SETTING_LABELS['usbchg']['off']})")
    print(f"  AC recovery (XRAM[0x{ADDR_AP_OEM9:04X}] bit3): {ac} "
          f"({SETTING_LABELS['acrecov']['on'] if ac else SETTING_LABELS['acrecov']['off']})")
    print(f"  ApExistFlag (XRAM[0x{ADDR_AP_OEM:04X}] bit0): {_bit(e, 0)}")


# ── individual command handlers ──────────────────────────────────────

def cmd_status(args):
    print("[EC Settings]")
    _show_status()


def cmd_winlock(args):
    state = _bit(ec_read(ADDR_STATUS_BYTE), 0)
    target = 1 if args.state == "on" else 0
    if state == target:
        print(f"  Win lock already {args.state}, no change")
        return
    _rmw(ADDR_TRIGGER_BYTE, set_bits=0x01)
    after = _bit(ec_read(ADDR_STATUS_BYTE), 0)
    print(f"  Win lock trigger sent, status bit0 = {after}")


def cmd_fnlock(args):
    target = 1 if args.state == "on" else 0
    old = ec_read(ADDR_BIOS_OEM_BYTE)
    old_bit = _bit(old, 4)
    if old_bit == target:
        print(f"  Fn lock already {args.state}, no change")
        return
    new = old | 0x10 if target else old & 0xEF
    ec_write(ADDR_BIOS_OEM_BYTE, new)
    after = ec_read(ADDR_BIOS_OEM_BYTE)
    print(f"  XRAM[0x{ADDR_BIOS_OEM_BYTE:04X}] : 0x{old:02x} -> 0x{after:02x}")
    print(f"  Fn lock bit4 = {_bit(after, 4)}")


def cmd_usbchg(args):
    target = 1 if args.state == "on" else 0
    old = _bit(ec_read(ADDR_TRIGGER_BYTE), 4)
    if old == target:
        print(f"  USB charger already {args.state}, no change")
        return
    if target:
        _rmw(ADDR_TRIGGER_BYTE, set_bits=0x10)
    else:
        _rmw(ADDR_TRIGGER_BYTE, clear_bits=0x10)
    after = _bit(ec_read(ADDR_TRIGGER_BYTE), 4)
    print(f"  USB charger bit4 = {after}")


def cmd_acrecov(args):
    target = 1 if args.state == "on" else 0
    _ensure_ap_exist()
    old = ec_read(ADDR_AP_OEM9)
    old_bit = _bit(old, 3)
    if old_bit == target:
        print(f"  AC recovery already {args.state}, no change")
        return
    new = old | 0x08 if target else old & 0xF7
    ec_write(ADDR_AP_OEM9, new)
    after = ec_read(ADDR_AP_OEM9)
    print(f"  XRAM[0x{ADDR_AP_OEM9:04X}]: 0x{old:02x} -> 0x{after:02x}")
    print(f"  AC recovery bit3 = {_bit(after, 3)}")


# ── CLI registration ────────────────────────────────────────────────

def register(subparsers):
    s = subparsers.add_parser(
        "setting",
        help="Setting controls (Win lock, Fn lock, USB charger, AC recovery)",
    )
    s.set_defaults(func=cmd_status)
    sub = s.add_subparsers(dest="setting_op")

    sub.add_parser("status", help="Show current setting states").set_defaults(func=cmd_status)

    for name in ("winlock", "fnlock", "usbchg"):
        label = SETTING_LABELS[name]
        sp = sub.add_parser(name, help=f"Toggle {name} {label['on']}/{label['off']}")
        sp.add_argument("state", choices=("on", "off"), help=f"{label['on']} or {label['off']}")
        sp.set_defaults(func={"winlock": cmd_winlock, "fnlock": cmd_fnlock, "usbchg": cmd_usbchg}[name])

    name = "acrecov"
    label = SETTING_LABELS[name]
    sp = sub.add_parser(name, help=f"Toggle {name} {label['on']}/{label['off']}")
    sp.add_argument("state", choices=("on", "off"), help=f"{label['on']} or {label['off']}")
    sp.set_defaults(func=cmd_acrecov)
