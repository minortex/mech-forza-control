"""Power mode switching — EC register sequences for Gaming / Office / Turbo / Custom."""

from .config import (
    ADDR_AP_CTL,
    ADDR_AP_OEM,
    ADDR_AP_OEM9,
    ADDR_AP_OEM10,
    ADDR_CPU_FAN_DNT_BASE,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_CPU_FAN_UPT_BASE,
    ADDR_FAN_SWITCH_SPEED,
    ADDR_FANCTL_RESP,
    ADDR_GPU_FAN_DNT_BASE,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_GPU_FAN_UPT_BASE,
    ADDR_MAFAN_CTL,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_TCC,
    DEFAULT_CPU_FAN,
    DEFAULT_GPU_FAN,
    MODE_CTL_LABELS,
    MODES,
    PL_DC,
    PL_DEFAULTS,
)
from .io import ec_read, ec_write, ec_rmw, is_ac_power


# ── helpers ──────────────────────────────────────────────────────────

def _write_fan_table(cpu=None, gpu=None):
    cpu = cpu or DEFAULT_CPU_FAN
    gpu = gpu or DEFAULT_GPU_FAN
    for i in range(16):
        ec_write(ADDR_CPU_FAN_UPT_BASE + i, cpu["upT"][i + 1] if i < 15 else 255)
        if i < 15:
            ec_write(ADDR_CPU_FAN_DNT_BASE + i + 1, cpu["dnT"][i])
        ec_write(ADDR_CPU_FAN_DUTY_BASE + i, min(cpu["duty"][i], 100) * 2)
        ec_write(ADDR_GPU_FAN_UPT_BASE + i, gpu["upT"][i + 1] if i < 15 else 255)
        if i < 15:
            ec_write(ADDR_GPU_FAN_DNT_BASE + i + 1, gpu["dnT"][i])
        ec_write(ADDR_GPU_FAN_DUTY_BASE + i, min(gpu["duty"][i], 100) * 2)


# ── commands ─────────────────────────────────────────────────────────

def cmd_switch(args):
    name = args.mode_name
    m = MODES.get(name)
    if m is None:
        raise ValueError(f"unknown mode: {name}")

    pl1 = getattr(args, "pl1", None)
    pl2 = getattr(args, "pl2", None)
    pl4 = getattr(args, "pl4", None)
    if m["pl"] is not None and pl1 is None:
        pl1, pl2, pl4 = m["pl"]
    elif m["pl"] is None and pl1 is None:
        if is_ac_power():
            pl1, pl2, pl4 = PL_DEFAULTS["turbo"]
        else:
            pl1, pl2, pl4 = PL_DC
        print(f"  Turbo PL (AC={is_ac_power()}): {pl1}/{pl2}/{pl4}")
    pl1 = pl1 or 0
    pl2 = pl2 or 0
    pl4 = pl4 or 0

    print(f"  Mode: {m['desc']} (operating={m['mode']})")
    print(f"  PL:   {pl1}/{pl2}/{pl4}")

    ec_rmw(ADDR_AP_CTL, set_bits=0x04)
    v = ec_read(ADDR_AP_CTL)
    print(f"  EC[{ADDR_AP_CTL}] AP_CTL = {v} (0x{v:02x})  bit2={'OK' if v&4 else 'FAIL'}")

    ec_rmw(ADDR_AP_OEM10, set_bits=0x40) if m["custom"] else ec_rmw(ADDR_AP_OEM10, clear_bits=0x40)
    ec_rmw(ADDR_AP_OEM, set_bits=0x01)
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    if m["custom"]: _write_fan_table()
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    ec_write(ADDR_FAN_SWITCH_SPEED, 0x81)
    ec_write(ADDR_TCC, getattr(args, "tcc", 0) | 0x80)
    ec_write(ADDR_FANCTL_RESP, 0x80 if getattr(args, "separate", False) else 0x00)
    ec_rmw(ADDR_AP_CTL, set_bits=0x04)
    ec_write(ADDR_PL1, pl1 & 0xFF)
    ec_write(ADDR_PL2, pl2 & 0xFF)
    ec_write(ADDR_PL4, pl4 & 0xFF)
    ec_write(ADDR_MAFAN_CTL, m["ctl"])
    ec_rmw(ADDR_AP_CTL, set_bits=0x04)
    ec_rmw(ADDR_AP_OEM9, set_bits=0x80) if m["custom"] else ec_rmw(ADDR_AP_OEM9, clear_bits=0x80)

    e57 = ec_read(ADDR_AP_OEM); e30 = ec_read(ADDR_AP_OEM9)
    e27 = ec_read(ADDR_FAN_SWITCH_SPEED); e89 = ec_read(ADDR_FANCTL_RESP)
    e26 = ec_read(ADDR_TCC); got = ec_read(ADDR_MAFAN_CTL)
    print(f"  EC[1857] ApExist  = {e57} (0x{e57:02x})  bit0={e57&1}")
    print(f"  EC[1830] OEM9     = {e30} (0x{e30:02x})  bit7={e30>>7}")
    print(f"  EC[1927] SwSpeed  = {e27}  {f'{e27&0x7F}s' if e27&0x80 else 'instant'}")
    print(f"  EC[1989] Respct   = {e89} (0x{e89:02x})  bit7={e89>>7}")
    print(f"  EC[1926] TCC      = {'disabled' if not e26&0x80 else f'{e26}  Tj-{e26&0x7F}C'}")
    ok = "OK" if got == m["ctl"] else f"FAIL expected {m['ctl']}"
    print(f"  EC[{ADDR_MAFAN_CTL}] CTL    = {got} (0x{got:02x})  {ok}")


def cmd_status(args):
    ctl = ec_read(ADDR_MAFAN_CTL)
    pl1, pl2, pl4 = ec_read(ADDR_PL1), ec_read(ADDR_PL2), ec_read(ADDR_PL4)
    oem9, oem10 = ec_read(ADDR_AP_OEM9), ec_read(ADDR_AP_OEM10)
    oem57, ap = ec_read(ADDR_AP_OEM), ec_read(ADDR_AP_CTL)
    label = MODE_CTL_LABELS.get(ctl, "?")
    custom = " (custom)" if oem9 & 0x80 else ""
    print("[EC Status]")
    print(f"  EC[1873] CTL    = {ctl} (0x{ctl:02x})  {label}{custom}")
    print(f"  EC[1830] OEM9   = {oem9} (0x{oem9:02x})  bit7={oem9>>7}")
    print(f"  EC[1831] OEM10  = {oem10} (0x{oem10:02x})  bit6={(oem10>>6)&1}")
    print(f"  EC[1857] AP_OEM = {oem57} (0x{oem57:02x})  bit0={oem57&1} (ApExist)")
    print(f"  EC[1990] AP_CTL = {ap} (0x{ap:02x})  bit2={(ap>>2)&1}")
    print(f"  PL:  {pl1}/{pl2}/{pl4}")


def cmd_dump(args):
    for addr in range(1829, 1829 + 16):
        v = ec_read(addr)
        print(f"  EC[{addr}] = {v:3d} (0x{v:02x})")
    for addr in range(1989, 1989 + 6):
        v = ec_read(addr)
        print(f"  EC[{addr}] = {v:3d} (0x{v:02x})")


# ── CLI registration ─────────────────────────────────────────────────

def register(subparsers):
    m = subparsers.add_parser("mode", help="Power mode operations")
    sub = m.add_subparsers(dest="mode_op", required=True)
    for name, info in MODES.items():
        sp = sub.add_parser(name, help=info["desc"])
        sp.set_defaults(func=cmd_switch, mode_name=name)
        if name in ("custom", "turbo"):
            sp.add_argument("--pl1", type=int, default=None)
            sp.add_argument("--pl2", type=int, default=None)
            sp.add_argument("--pl4", type=int, default=None)
        if name == "custom":
            sp.add_argument("--tcc", type=int, default=0)
            sp.add_argument("--separate", action="store_true")
    sub.add_parser("status", help="Show current EC state").set_defaults(func=cmd_status)
    sub.add_parser("dump", help="Dump key EC registers").set_defaults(func=cmd_dump)
