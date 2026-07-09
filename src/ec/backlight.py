"""Keyboard backlight control — EC[1932] register."""

from .config import ADDR_BACKLIGHT, BACKLIGHT_LABELS
from .io import ec_read, ec_write


def _set_level(lvl):
    if not 0 <= lvl <= 4:
        raise ValueError("level must be 0-4")
    reg = ec_read(ADDR_BACKLIGHT)
    reg |= 0x10
    reg &= 0x1F
    reg |= (lvl & 7) << 5
    reg &= ~2
    ec_write(ADDR_BACKLIGHT, reg)
    print(f"Keyboard backlight level {lvl} ({BACKLIGHT_LABELS.get(lvl,'?')})")
    print(f"EC[1932] = {reg} (0x{reg:02x})")


def cmd_status(args):
    reg = ec_read(ADDR_BACKLIGHT)
    lvl = (reg >> 5) & 7
    label = BACKLIGHT_LABELS.get(lvl, '?')
    print(f"EC[1932] = {reg:3d} (0x{reg:02x})")
    print(f"  Power:  {'ON' if not reg&2 else 'OFF'}")
    print(f"  Level:  {lvl} ({label})")
    print(f"  Bits:   {reg:08b}")


def cmd_set(args):
    _set_level(args.level)


def cmd_on(args):
    _set_level(4)


def cmd_off(args):
    _set_level(0)


def cmd_dim(args):
    _set_level(2)


def register(subparsers):
    bl = subparsers.add_parser("backlight", help="Keyboard backlight control")
    sub = bl.add_subparsers(dest="bl_op", required=True)
    sub.add_parser("status", help="Show backlight state").set_defaults(func=cmd_status)
    sub.add_parser("on", help="Bright backlight").set_defaults(func=cmd_on)
    sub.add_parser("off", help="Turn off").set_defaults(func=cmd_off)
    sub.add_parser("dim", help="Dim backlight").set_defaults(func=cmd_dim)
    sp = sub.add_parser("level", help="Set level 0-4")
    sp.add_argument("level", type=int, help="0=off, 1-2=dim, 3-4=bright")
    sp.set_defaults(func=cmd_set)
