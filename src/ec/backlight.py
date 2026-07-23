"""Keyboard backlight control — EC[1932] register.

Levels (bit7:5), brightest to dimmest:
  010 (2) > 100 (4) > 001 (1) > 011 (3) > 000 (0 off)
"""

from .config import ADDR_BACKLIGHT, BACKLIGHT_CYCLE, BACKLIGHT_LABELS
from .io import ec_read, ec_write


def _set_level(lvl):
    if not 0 <= lvl <= 4:
        raise ValueError("level must be 0-4")
    reg = ec_read(ADDR_BACKLIGHT)
    reg |= 0x10      # bit4 must be 1
    reg &= 0x1F       # clear bit7:5
    reg |= (lvl & 7) << 5
    reg &= ~2          # bit1 = 0 -> power on
    ec_write(ADDR_BACKLIGHT, reg)
    label = BACKLIGHT_LABELS.get(lvl)
    suffix = f" ({label})" if label else ""
    print(f"EC[0x{ADDR_BACKLIGHT:04X}] = 0x{reg:02x}  level {lvl}{suffix}")


def _get_level():
    return (ec_read(ADDR_BACKLIGHT) >> 5) & 7


def cmd_status(args):
    reg = ec_read(ADDR_BACKLIGHT)
    lvl = (reg >> 5) & 7
    label = BACKLIGHT_LABELS.get(lvl)
    suffix = f" ({label})" if label else ""
    print(f"EC[0x{ADDR_BACKLIGHT:04X}] = 0x{reg:02x}")
    print(f"  Power:  {'ON' if not reg & 2 else 'OFF'}")
    print(f"  Level:  {lvl}{suffix}")
    print(f"  Bits:   {reg:08b}")


def cmd_off(args):
    _set_level(0)      # off


def cmd_dim(args):
    _set_level(1)      # dim, 001


def cmd_bright(args):
    _set_level(2)      # max, 010 — same as keyboard "bright"


def cmd_level(args):
    _set_level(args.level)


def cmd_cycle(args):
    cur = _get_level()
    try:
        idx = BACKLIGHT_CYCLE.index(cur)
    except ValueError:
        idx = -1
    nxt = BACKLIGHT_CYCLE[(idx + 1) % len(BACKLIGHT_CYCLE)]
    _set_level(nxt)


def register(subparsers):
    bl = subparsers.add_parser("backlight",
        help="Keyboard backlight control",
        epilog="4 brightness levels (0-4) for advanced players, use 'level N' to set directly.")
    bl.set_defaults(func=cmd_status)
    sub = bl.add_subparsers(dest="bl_op")
    sub.add_parser("status", help="Show backlight state").set_defaults(func=cmd_status)
    sub.add_parser("bright", help="Maximum brightness (010)").set_defaults(func=cmd_bright)
    sub.add_parser("dim", help="Dim (001)").set_defaults(func=cmd_dim)
    sub.add_parser("off", help="Turn off").set_defaults(func=cmd_off)
    sub.add_parser("cycle", help="Cycle: off -> dim -> bright").set_defaults(func=cmd_cycle)

    lvl = sub.add_parser("level", help="Set level 0-4 directly (advanced)")
    lvl.add_argument("level", type=int, choices=range(5), help="Brightness level (0-4)")
    lvl.set_defaults(func=cmd_level)
