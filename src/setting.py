"""EC setting controls — Win key lock, Fn lock, USB charger, AC recovery.

Commands:
  mfc setting status             — read current state
  mfc setting winlock   on|off   — toggle Win key lock (trigger)
  mfc setting fnlock     on|off  — toggle Fn lock (direct)
  mfc setting usbchg     on|off  — toggle USB charging when off (direct)
  mfc setting acrecov    on|off  — toggle AC recovery (ApExistFlag + XRAM[0x0726])
"""

from .registers import (
    ADDR_AP_OEM,
    ADDR_AP_OEM9,
    ADDR_BIOS_OEM_BYTE,
    ADDR_STATUS_BYTE,
    ADDR_TRIGGER_BYTE,
)
from .cli import prefix_choice
from .io import ec_read, ec_rmw, ensure_ap_exist


SETTINGS = {
    "winlock": {
        "label": "Win lock",
        "addr": ADDR_STATUS_BYTE,
        "bit": 0,
        "on": "locked",
        "off": "unlocked",
    },
    "fnlock": {
        "label": "Fn lock",
        "addr": ADDR_BIOS_OEM_BYTE,
        "bit": 4,
        "on": "locked",
        "off": "unlocked",
    },
    "usbchg": {
        "label": "USB charger",
        "addr": ADDR_TRIGGER_BYTE,
        "bit": 4,
        "on": "on",
        "off": "off",
    },
    "acrecov": {
        "label": "AC recovery",
        "addr": ADDR_AP_OEM9,
        "bit": 3,
        "on": "on",
        "off": "off",
    },
}


def _bit(value, n):
    return (value >> n) & 1


def _show_status():
    for item in SETTINGS.values():
        value = _bit(ec_read(item["addr"]), item["bit"])
        label = item["on"] if value else item["off"]
        print(
            f"  {item['label']:<12}(XRAM[0x{item['addr']:04X}] "
            f"bit{item['bit']}): {value} ({label})"
        )
    ap_exist = _bit(ec_read(ADDR_AP_OEM), 0)
    print(f"  {'ApExistFlag':<12}(XRAM[0x{ADDR_AP_OEM:04X}] bit0): {ap_exist}")


def _set_ap_exist():
    old = ensure_ap_exist()
    if old is not None:
        print(f"  XRAM[0x{ADDR_AP_OEM:04X}] ApExistFlag: 0x{old:02x} -> set bit0=1")


def _toggle(item, args):
    target = 1 if args.state == "on" else 0
    old = ec_read(item["addr"])
    if _bit(old, item["bit"]) == target:
        print(f"  {item['label']} already {args.state}, no change")
        return
    mask = 1 << item["bit"]
    if target:
        ec_rmw(item["addr"], set_bits=mask)
    else:
        ec_rmw(item["addr"], clear_bits=mask)
    after = ec_read(item["addr"])
    print(f"  XRAM[0x{item['addr']:04X}]: 0x{old:02x} -> 0x{after:02x}")
    print(f"  {item['label']} bit{item['bit']} = {_bit(after, item['bit'])}")


def cmd_status(args):
    print("[EC Settings]")
    _show_status()


def cmd_winlock(args):
    item = SETTINGS["winlock"]
    target = 1 if args.state == "on" else 0
    if _bit(ec_read(item["addr"]), item["bit"]) == target:
        print(f"  {item['label']} already {args.state}, no change")
        return
    ec_rmw(ADDR_TRIGGER_BYTE, set_bits=0x01)
    after = _bit(ec_read(item["addr"]), item["bit"])
    print(f"  {item['label']} trigger sent, status bit{item['bit']} = {after}")


def cmd_fnlock(args):
    _toggle(SETTINGS["fnlock"], args)


def cmd_usbchg(args):
    _toggle(SETTINGS["usbchg"], args)


def cmd_acrecov(args):
    _set_ap_exist()
    _toggle(SETTINGS["acrecov"], args)


SETTING_COMMANDS = {
    "winlock": cmd_winlock,
    "fnlock": cmd_fnlock,
    "usbchg": cmd_usbchg,
    "acrecov": cmd_acrecov,
}


def register(subparsers):
    s = subparsers.add_parser(
        "setting",
        help="Setting controls (Win lock, Fn lock, USB charger, AC recovery)",
    )
    s.set_defaults(func=cmd_status)
    sub = s.add_subparsers(dest="setting_op")

    sub.add_parser("status", help="Show current setting states").set_defaults(
        func=cmd_status
    )

    for name, item in SETTINGS.items():
        sp = sub.add_parser(name, help=f"Toggle {name} {item['on']}/{item['off']}")
        sp.add_argument(
            "state",
            type=prefix_choice("on", "off", label="setting state"),
            metavar="{on,off}",
            help=f"{item['on']} or {item['off']}",
        )
        sp.set_defaults(func=SETTING_COMMANDS[name])
