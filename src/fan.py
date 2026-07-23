"""Fan monitoring — read RPM, duty, control byte."""

import time

from .config import (
    ADDR_CPU_TEMP,
    ADDR_MAIN_FAN_DUTY,
    ADDR_MAIN_FAN_RPM_HI,
    ADDR_MAIN_FAN_RPM_LO,
    ADDR_MAFAN_CTL,
    ADDR_SECOND_FAN_DUTY,
    ADDR_SECOND_FAN_RPM_HI,
    ADDR_SECOND_FAN_RPM_LO,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_CPU_FAN_UPT_BASE,
    ADDR_CPU_FAN_DNT_BASE,
    ADDR_FAN_SWITCH_SPEED,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_GPU_FAN_UPT_BASE,
    ADDR_GPU_FAN_DNT_BASE,
    DEFAULT_CPU_FAN,
    DEFAULT_GPU_FAN,
)
from .io import ec_read, ec_write


def _encode_switch_speed(steps):
    if not 0 <= steps <= 127:
        raise ValueError(f"fan switch speed must be 0-127 steps, got {steps}")
    if steps == 0:
        return 0
    return 0x80 | steps


def _decode_switch_speed(value):
    steps = value & 0x7f
    if steps == 0:
        return "EC default, about 7s observed"
    return f"{steps} step(s), about {steps * 2}s"


def _read():
    return (
        ec_read(ADDR_CPU_TEMP),
        ec_read(ADDR_MAIN_FAN_RPM_HI) * 256 + ec_read(ADDR_MAIN_FAN_RPM_LO),
        ec_read(ADDR_SECOND_FAN_RPM_HI) * 256 + ec_read(ADDR_SECOND_FAN_RPM_LO),
        ec_read(ADDR_MAFAN_CTL),
        ec_read(ADDR_MAIN_FAN_DUTY),
        ec_read(ADDR_SECOND_FAN_DUTY),
        ec_read(ADDR_FAN_SWITCH_SPEED),
    )


def cmd_read(args):
    cpu_t, mr, sr, ctrl, dm, ds, sw = _read()
    print(f"CPU Temp             : {cpu_t}\u00b0C")
    print(f"Main fan (Right) RPM : {mr}")
    print(f"Sec  fan (Left)  RPM : {sr}")
    print(f"Control byte         : 0x{ctrl:02x} (0b{ctrl:08b})")
    print(f"Duty Main(R)/Sec(L)  : {dm}% / {ds}%")
    print(
        f"Switch speed         : {_decode_switch_speed(sw)} "
        f"(XRAM[0x{ADDR_FAN_SWITCH_SPEED:04X}] = 0x{sw:02x})"
    )


def cmd_monitor(args):
    iv = args.interval
    print(f"Monitoring every {iv}s, Ctrl+C to stop\n")
    hdr = f"{'Time':>8}  {'CPU':>4}  {'MainRPM':>7}  {'SecRPM':>7}  {'Ctrl':>5}  {'DutyM(R)':>8}  {'DutyS(L)':>8}"
    print(hdr); print("-" * 68)
    try:
        while True:
            cpu_t, mr, sr, ctrl, dm, ds, _ = _read()
            print(f"{time.strftime('%H:%M:%S')}  {cpu_t:>3}\u00b0C  {mr:>7}  {sr:>7}  {ctrl:>5}  {dm:>8}  {ds:>8}", flush=True)
            time.sleep(iv)
    except KeyboardInterrupt:
        pass


def cmd_switch_speed(args):
    """Set the EC fan transition/switch speed."""
    raw = _encode_switch_speed(args.steps)
    ec_write(ADDR_FAN_SWITCH_SPEED, raw)
    got = ec_read(ADDR_FAN_SWITCH_SPEED)
    print(
        f"  Fan switch speed: {_decode_switch_speed(got)} "
        f"(XRAM[0x{ADDR_FAN_SWITCH_SPEED:04X}] = 0x{got:02x})"
    )


def cmd_set(args):
    """Force fan to a fixed speed percentage by writing all duty-table entries."""
    pcts = args.percentage
    if len(pcts) == 1:
        cpu_pct = gpu_pct = pcts[0]
    elif len(pcts) == 2:
        cpu_pct, gpu_pct = pcts
    else:
        raise ValueError(f"expected 1 or 2 percentages, got {len(pcts)}")

    for pct, label, base in ((cpu_pct, "CPU", ADDR_CPU_FAN_DUTY_BASE),
                              (gpu_pct, "GPU", ADDR_GPU_FAN_DUTY_BASE)):
        if pct < 0 or pct > 100:
            raise ValueError(f"{label} fan percentage must be 0-100, got {pct}")
        duty = pct * 2
        for i in range(16):
            ec_write(base + i, duty)
        first = ec_read(base)
        print(f"  {label} fan duty: all 16 points set to {pct}% (EC value 0x{duty:02x})")
        print(f"  XRAM[0x{base:04X}] = 0x{first:02x} -- readback OK")


def cmd_default(args):
    """Restore the default fan curves from config."""
    def _restore(base_upt, base_dnt, base_duty, table):
        for i in range(16):
            ec_write(base_upt + i, table["upT"][i + 1] if i < 15 else 255)
            if i < 15:
                ec_write(base_dnt + i + 1, table["dnT"][i])
            ec_write(base_duty + i, min(table["duty"][i], 100) * 2)

    _restore(ADDR_CPU_FAN_UPT_BASE, ADDR_CPU_FAN_DNT_BASE,
             ADDR_CPU_FAN_DUTY_BASE, DEFAULT_CPU_FAN)
    _restore(ADDR_GPU_FAN_UPT_BASE, ADDR_GPU_FAN_DNT_BASE,
             ADDR_GPU_FAN_DUTY_BASE, DEFAULT_GPU_FAN)
    print("  Fan tables restored to factory defaults (UpT, DownT, Duty)")


def register(subparsers):
    fn = subparsers.add_parser("fan", help="Fan monitoring")
    fn.set_defaults(func=cmd_read)
    sub = fn.add_subparsers(dest="fan_op")
    sub.add_parser("read", help="Read current fan status").set_defaults(func=cmd_read)
    mon = sub.add_parser("monitor", help="Continuously monitor")
    mon.add_argument("-i", "--interval", type=float, default=1.0)
    mon.set_defaults(func=cmd_monitor)
    sw = sub.add_parser(
        "switch-speed",
        help="Set fan transition speed (unit: 2 seconds per step, 0-127)",
    )
    sw.add_argument(
        "steps",
        type=int,
        help="Unit: 2 seconds per step. 1=2s, 3=6s; 0 uses EC default (~7s observed)",
    )
    sw.set_defaults(func=cmd_switch_speed)
    sp = sub.add_parser("set", help="Force fan speed(s) (0-100%%)")
    sp.add_argument("percentage", type=int, nargs="+",
                    help="1 value for both fans, or 2 values (CPU then GPU)")
    sp.set_defaults(func=cmd_set)
    sub.add_parser("default", help="Restore default fan curves").set_defaults(func=cmd_default)
