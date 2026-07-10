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
    TDP_CTL,
)
from .io import ec_read, ec_write, ec_rmw


# ── helpers ──────────────────────────────────────────────────────────

def _resolve_tcc(args):
    tcc = getattr(args, "tcc", 0) or 0
    if not 0 <= tcc <= 100:
        raise ValueError(f"tcc must be 0-100, got {tcc}")
    return tcc


def _encode_tcc(tcc):
    if tcc == 0:
        return 0
    return tcc | 0x80


def _resolve_ctl(args, mode):
    tdp = getattr(args, "tdp", None)
    if mode["custom"] and tdp is not None:
        if tdp not in TDP_CTL:
            raise ValueError(f"custom TDP must be one of 25, 45, 65; got {tdp}")
        return TDP_CTL[tdp]
    return mode["ctl"]


def _status_label(ctl, custom):
    if ctl == 0xA0:
        return "Custom 25W" if custom else "Office 25W"
    if ctl == 0x00:
        return "Custom 45W" if custom else "Gaming 45W"
    if ctl == 0x10:
        return "Custom 65W" if custom else "Turbo 65W"
    return MODE_CTL_LABELS.get(ctl, "?")


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

    tcc = _resolve_tcc(args)
    ctl = _resolve_ctl(args, m)

    tdp = getattr(args, "tdp", None) if m["custom"] else m["tdp"]

    print(f"  Mode: {m['desc']} (operating={m['mode']})")
    print(f"  TDP:  {tdp}W")
    print("  PL:   managed by EC/BIOS")

    ec_rmw(ADDR_AP_CTL, set_bits=0x04)
    v = ec_read(ADDR_AP_CTL)
    print(f"  EC[{ADDR_AP_CTL}] AP_CTL = {v} (0x{v:02x})  bit2={'OK' if v&4 else 'FAIL'}")

    ec_rmw(ADDR_AP_OEM10, set_bits=0x40) if m["custom"] else ec_rmw(ADDR_AP_OEM10, clear_bits=0x40)
    ec_rmw(ADDR_AP_OEM, set_bits=0x01)
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    if m["custom"]: _write_fan_table()
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    ec_write(ADDR_FAN_SWITCH_SPEED, 0x81)
    if m["custom"]:
        ec_write(ADDR_TCC, _encode_tcc(tcc))
    ec_write(ADDR_FANCTL_RESP, 0x80 if getattr(args, "separate", False) else 0x00)
    ec_rmw(ADDR_AP_CTL, set_bits=0x04)
    ec_write(ADDR_MAFAN_CTL, ctl)
    ec_rmw(ADDR_AP_CTL, set_bits=0x04)
    ec_rmw(ADDR_AP_OEM9, set_bits=0x80) if m["custom"] else ec_rmw(ADDR_AP_OEM9, clear_bits=0x80)

    e57 = ec_read(ADDR_AP_OEM); e30 = ec_read(ADDR_AP_OEM9)
    e27 = ec_read(ADDR_FAN_SWITCH_SPEED); e89 = ec_read(ADDR_FANCTL_RESP)
    e26 = ec_read(ADDR_TCC); got = ec_read(ADDR_MAFAN_CTL)
    print(f"  EC[1857] ApExist  = {e57} (0x{e57:02x})  bit0={e57&1}")
    print(f"  EC[1830] OEM9     = {e30} (0x{e30:02x})  bit7={e30>>7}")
    sw_steps = e27 & 0x7F
    if sw_steps:
        sw_status = f"{sw_steps} step(s), about {sw_steps * 2}s"
    else:
        sw_status = "EC default, about 7s observed"
    print(f"  EC[1927] SwSpeed  = {e27}  {sw_status}")
    print(f"  EC[1989] Respct   = {e89} (0x{e89:02x})  bit7={e89>>7}")
    if not m["custom"]:
        tcc_status = "not written in fixed mode"
    elif e26 == 0:
        tcc_status = "disabled"
    elif e26 & 0x80:
        tcc_status = f"{e26 & 0x7f} (enabled, raw=0x{e26:02x})"
    else:
        tcc_status = f"{e26} (raw, enable bit clear)"
    print(f"  EC[1926] TCC      = {tcc_status}")
    ok = "OK" if got == ctl else f"FAIL expected {ctl}"
    print(f"  EC[{ADDR_MAFAN_CTL}] CTL    = {got} (0x{got:02x})  {ok}")


def cmd_status(args):
    ctl = ec_read(ADDR_MAFAN_CTL)
    pl1, pl2, pl4 = ec_read(ADDR_PL1), ec_read(ADDR_PL2), ec_read(ADDR_PL4)
    oem9, oem10 = ec_read(ADDR_AP_OEM9), ec_read(ADDR_AP_OEM10)
    oem57, ap = ec_read(ADDR_AP_OEM), ec_read(ADDR_AP_CTL)
    custom = bool(oem9 & 0x80)
    label = _status_label(ctl, custom)
    print("[EC Status]")
    print(f"  EC[1873] CTL    = {ctl} (0x{ctl:02x})  {label}")
    print(f"  EC[1830] OEM9   = {oem9} (0x{oem9:02x})  bit7={oem9>>7}")
    print(f"  EC[1831] OEM10  = {oem10} (0x{oem10:02x})  bit6={(oem10>>6)&1}")
    print(f"  EC[1857] AP_OEM = {oem57} (0x{oem57:02x})  bit0={oem57&1} (ApExist)")
    print(f"  EC[1990] AP_CTL = {ap} (0x{ap:02x})  bit2={(ap>>2)&1}")
    print(f"  EC PL readback  = {pl1}/{pl2}/{pl4}  (not authoritative for fixed modes/ryzenadj)")


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
        if name == "custom":
            sp.add_argument("tdp", type=int, nargs="?", choices=sorted(TDP_CTL), default=45,
                            help="Fixed TDP gear: 25, 45, or 65")
            sp.add_argument("--tcc", type=int, default=0, help="TCC target 0-100; 0 disables")
            sp.add_argument("--separate", action="store_true")
    sub.add_parser("status", help="Show current EC state").set_defaults(func=cmd_status)
    sub.add_parser("dump", help="Dump key EC registers").set_defaults(func=cmd_dump)
