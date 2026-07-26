"""Base EC performance-policy switching: Office / Gaming / Turbo."""

from .config import ADDR_MAFAN_CTL, MODES
from .io import ec_read, ec_write


_MODE_MASK = 0x90
_FAN_BOOST_BIT = 0x40
_MODE_LABELS = {
    0x80: "Office",
    0x00: "Gaming",
    0x10: "Turbo",
}


def _status_label(ctl):
    return _MODE_LABELS.get(ctl & _MODE_MASK, "Unknown")


def cmd_switch(args):
    name = args.mode_name
    mode = MODES.get(name)
    if mode is None:
        raise ValueError(f"unknown mode: {name}")

    # 0x0751 also carries FanBoost in bit6.  A base-mode change must not
    # silently alter fan ownership, fan tables, or the FanBoost selection.
    current = ec_read(ADDR_MAFAN_CTL)
    requested = mode["ctl"] | (current & _FAN_BOOST_BIT)
    ec_write(ADDR_MAFAN_CTL, requested)
    got = ec_read(ADDR_MAFAN_CTL)

    print(f"  Base mode: {mode['desc']} (operating={mode['mode']})")
    print("  Power:     EC/BIOS policy (actual limits depend on platform and power state)")
    print("  Fan:       ownership and RAM tables unchanged")
    expected_mode = requested & _MODE_MASK
    got_mode = got & _MODE_MASK
    ok = "OK" if got_mode == expected_mode else f"FAIL expected base bits 0x{expected_mode:02x}"
    print(f"  XRAM[0x{ADDR_MAFAN_CTL:04X}] CTL = 0x{got:02x}  {ok}")


def cmd_status(args):
    ctl = ec_read(ADDR_MAFAN_CTL)
    print("[EC Base Mode]")
    print(f"  Base mode      = {_status_label(ctl)}")
    print(f"  FanBoost       = {'on' if ctl & _FAN_BOOST_BIT else 'off'}")
    print(f"  XRAM[0x{ADDR_MAFAN_CTL:04X}] CTL = 0x{ctl:02x}")
    print("  Note           = fan ownership is reported by `mfc fan read`")


def cmd_dump(args):
    for addr in range(1829, 1829 + 16):
        value = ec_read(addr)
        print(f"  XRAM[0x{addr:04X}] = 0x{value:02x}")
    for addr in range(1989, 1989 + 6):
        value = ec_read(addr)
        print(f"  XRAM[0x{addr:04X}] = 0x{value:02x}")


def register(subparsers):
    parser = subparsers.add_parser("mode", help="Base performance-policy operations")
    parser.set_defaults(func=cmd_status)
    sub = parser.add_subparsers(dest="mode_op")
    for name, info in MODES.items():
        command = sub.add_parser(name, help=info["desc"])
        command.set_defaults(func=cmd_switch, mode_name=name)
    sub.add_parser("status", help="Show current base policy").set_defaults(func=cmd_status)
    sub.add_parser("dump", help="Dump key EC registers").set_defaults(func=cmd_dump)
