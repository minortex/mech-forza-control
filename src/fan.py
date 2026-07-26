"""Fan monitoring and curve control."""

import time

from .registers import (
    ADDR_AP_CTL,
    ADDR_AP_OEM,
    ADDR_AP_OEM10,
    ADDR_CPU_TEMP,
    ADDR_MAIN_FAN_DUTY,
    ADDR_MAIN_FAN_INDEX,
    ADDR_MAIN_FAN_RPM_HI,
    ADDR_MAIN_FAN_RPM_LO,
    ADDR_MAFAN_CTL,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_TCC,
    ADDR_SECOND_FAN_DUTY,
    ADDR_SECOND_FAN_INDEX,
    ADDR_SECOND_FAN_RPM_HI,
    ADDR_SECOND_FAN_RPM_LO,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_CPU_FAN_UPT_BASE,
    ADDR_CPU_FAN_DNT_BASE,
    ADDR_FAN_SWITCH_SPEED,
    ADDR_FANCTL_RESP,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_GPU_FAN_UPT_BASE,
    ADDR_GPU_FAN_DNT_BASE,
    FAN_BOOST_BIT,
)
from .cli import prefix_choice
from .fan_profile import FanCurve, load_fan_profile
from .io import ec_read, ec_rmw, ec_write

ROM_TABLE_MODES = {
    1: "Turbo",
    2: "Gaming",
    3: "Office",
}


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


def _format_duty(value):
    return f"{value / 2:.1f}%"


def _read_control_state():
    ap_oem = ec_read(ADDR_AP_OEM)
    ap_exist = bool(ap_oem & 0x01)
    custom = bool(ec_read(ADDR_AP_OEM10) & 0x40)
    fan_mgmt = bool(ec_read(ADDR_AP_CTL) & 0x04)
    independent = bool(ec_read(ADDR_FANCTL_RESP) & 0x80)
    table_active = ap_exist and custom and fan_mgmt
    return {
        "ap_exist": ap_exist,
        "custom": custom,
        "fan_mgmt": fan_mgmt,
        "independent": independent,
        "table_active": table_active,
        "independent_active": table_active and independent,
        "zero_rpm_warning": bool(ap_oem & 0x20),
        "fan_boost": bool(ec_read(ADDR_MAFAN_CTL) & FAN_BOOST_BIT),
    }


def _format_gate_bits(state):
    return (
        f"A={int(state['ap_exist'])} C={int(state['custom'])} "
        f"M={int(state['fan_mgmt'])}"
    )


def _print_gate_details(state):
    print(
        f"Gate APExist         : {int(state['ap_exist'])} "
        f"(XRAM[0x{ADDR_AP_OEM:04X}].bit0)"
    )
    print(
        f"Gate Custom          : {int(state['custom'])} "
        f"(XRAM[0x{ADDR_AP_OEM10:04X}].bit6)"
    )
    print(
        f"Gate FanMgmt         : {int(state['fan_mgmt'])} "
        f"(XRAM[0x{ADDR_AP_CTL:04X}].bit2)"
    )


def _read():
    return (
        ec_read(ADDR_CPU_TEMP),
        ec_read(ADDR_MAIN_FAN_RPM_HI) * 256 + ec_read(ADDR_MAIN_FAN_RPM_LO),
        ec_read(ADDR_SECOND_FAN_RPM_HI) * 256 + ec_read(ADDR_SECOND_FAN_RPM_LO),
        ec_read(ADDR_MAIN_FAN_DUTY),
        ec_read(ADDR_SECOND_FAN_DUTY),
        ec_read(ADDR_FAN_SWITCH_SPEED),
    )


def _read_curve(up_base, down_base, duty_base):
    return {
        "up": [ec_read(up_base + i) for i in range(16)],
        "down": [ec_read(down_base + i) for i in range(16)],
        "duty": [ec_read(duty_base + i) for i in range(16)],
    }


def _format_temperature(value):
    return "--" if value == 0xFF else str(value)


def _rom_table_load_mode(second_duty):
    if second_duty[13] == 0xFD and second_duty[14] == 0xC9:
        mode = second_duty[15]
        if mode in ROM_TABLE_MODES:
            return mode
    return None


def cmd_read(args):
    cpu_t, mr, sr, dm, ds, sw = _read()
    state = _read_control_state()
    print(f"CPU Temp             : {cpu_t}\u00b0C")
    print(f"Main fan (Right) RPM : {mr}")
    print(f"Sec  fan (Left)  RPM : {sr}")
    print(
        f"Duty Main(R)/Sec(L)  : {_format_duty(dm)} / {_format_duty(ds)} "
        f"(raw {dm} / {ds})"
    )
    print(
        "Control path         : "
        + (
            "AP RAM table (active)"
            if state["table_active"]
            else "EC firmware/ROM fallback"
        )
    )
    print(
        f"Switch speed         : {_decode_switch_speed(sw)} "
        f"(XRAM[0x{ADDR_FAN_SWITCH_SPEED:04X}] = 0x{sw:02x})"
    )
    print(
        f"FanBoost             : {'on' if state['fan_boost'] else 'off'} "
        f"(XRAM[0x{ADDR_MAFAN_CTL:04X}].bit6)"
    )
    print(
        "Fan relationship     : "
        + (
            "independent"
            if state["independent_active"]
            else "linked"
            if state["table_active"]
            else "EC firmware fallback"
        )
    )
    warning = (
        "SET (startup/recovery zero-RPM report)"
        if state["zero_rpm_warning"]
        else "clear"
    )
    print(f"Zero-RPM warning     : {warning} (XRAM[0x{ADDR_AP_OEM:04X}].bit5)")
    _print_gate_details(state)


def cmd_monitor(args):
    iv = args.interval
    print(f"Monitoring every {iv}s, Ctrl+C to stop")
    print("Gates: A=APExist C=Custom M=FanMgmt\n")
    hdr = (
        f"{'Time':<8} | {'CPU':>5} | {'Path':<4} | {'Link':<4} | "
        f"{'Boost':<5} | {'Warn':<4} | {'Gates':<11} | "
        f"{'MainRPM':>7} | {'SecRPM':>7} | "
        f"{'DutyM(R)':>8} | {'DutyS(L)':>8}"
    )
    print(hdr)
    print("-" * len(hdr))
    try:
        while True:
            cpu_t, mr, sr, dm, ds, _ = _read()
            state = _read_control_state()
            path = "AP" if state["table_active"] else "EC"
            link = "IND" if state["independent_active"] else "LINK"
            boost = "ON" if state["fan_boost"] else "OFF"
            warning = "ZERO" if state["zero_rpm_warning"] else "-"
            gate_bits = _format_gate_bits(state)
            print(
                f"{time.strftime('%H:%M:%S'):<8} | {cpu_t:>3}\u00b0C | "
                f"{path:<4} | {link:<4} | {boost:<5} | {warning:<4} | "
                f"{gate_bits:<11} | "
                f"{mr:>7} | {sr:>7} | {_format_duty(dm):>8} | "
                f"{_format_duty(ds):>8}",
                flush=True,
            )
            time.sleep(iv)
    except KeyboardInterrupt:
        pass


def cmd_table(args):
    profile_file = getattr(args, "file", None)
    if profile_file and not getattr(args, "reset", False):
        raise ValueError("fan table --file requires --reset")
    if getattr(args, "reset", False):
        cmd_default(args)
        return

    state = _read_control_state()
    main_index = ec_read(ADDR_MAIN_FAN_INDEX)
    second_index = ec_read(ADDR_SECOND_FAN_INDEX)
    main = _read_curve(
        ADDR_CPU_FAN_UPT_BASE,
        ADDR_CPU_FAN_DNT_BASE,
        ADDR_CPU_FAN_DUTY_BASE,
    )
    second = _read_curve(
        ADDR_GPU_FAN_UPT_BASE,
        ADDR_GPU_FAN_DNT_BASE,
        ADDR_GPU_FAN_DUTY_BASE,
    )
    rom_load_mode = _rom_table_load_mode(second["duty"])

    authority = (
        "active (AP RAM table)"
        if state["table_active"]
        else "inactive snapshot (EC firmware/ROM fallback)"
    )
    print(f"Table authority      : {authority}")
    _print_gate_details(state)
    print(f"Current index        : Main={main_index}, Second={second_index}")
    linked_index = None
    if state["table_active"] and state["independent_active"]:
        print("Lookup mode          : independent indexes")
        print("Current marker       : M=Main, S=Second, M/S=both")
    elif state["table_active"]:
        linked_index = max(main_index, second_index)
        print(
            "Lookup mode          : linked; shared candidate index "
            f"max({main_index}, {second_index}) = {linked_index}"
        )
        print("Current marker       : CUR=linked shared candidate index")
    else:
        print("Lookup mode          : EC firmware/ROM fallback")
        print("Current marker       : none (RAM table is not authoritative)")
    print("Table format         : temperatures in °C, duty shown as raw / 2")
    if rom_load_mode is None:
        print("ROM table trigger    : idle (FD C9 mode sentinel absent)")
    else:
        print(
            f"ROM table trigger    : pending {ROM_TABLE_MODES[rom_load_mode]} load "
            f"(FD C9 {rom_load_mode:02X})"
        )
        print("Note                 : Second duty[13..15] are trigger bytes, not duty")

    header = (
        f"{'Idx':>3} {'Current':>7} | {'Main UpT':>8} {'DownT':>5} {'Duty':>7} | "
        f"{'Second UpT':>10} {'DownT':>5} {'Duty':>7}"
    )
    print(header)
    print("-" * len(header))
    for i in range(16):
        if state["independent_active"]:
            is_main = i == main_index
            is_second = i == second_index
            if is_main and is_second:
                marker = "M/S"
            elif is_main:
                marker = "M"
            elif is_second:
                marker = "S"
            else:
                marker = ""
        elif linked_index is not None and i == linked_index:
            marker = "CUR"
        else:
            marker = ""
        main_duty = _format_duty(main["duty"][i])
        if rom_load_mode is not None and i >= 13:
            second_duty = f"0x{second['duty'][i]:02X}*"
        else:
            second_duty = _format_duty(second["duty"][i])
        print(
            f"{i:>3} {marker:>7} | "
            f"{_format_temperature(main['up'][i]):>8} "
            f"{_format_temperature(main['down'][i]):>5} "
            f"{main_duty:>7} | "
            f"{_format_temperature(second['up'][i]):>10} "
            f"{_format_temperature(second['down'][i]):>5} "
            f"{second_duty:>7}"
        )


def cmd_switch_speed(args):
    """Set the EC fan transition/switch speed."""
    raw = _encode_switch_speed(args.steps)
    ec_write(ADDR_FAN_SWITCH_SPEED, raw)
    got = ec_read(ADDR_FAN_SWITCH_SPEED)
    print(
        f"  Fan switch speed: {_decode_switch_speed(got)} "
        f"(XRAM[0x{ADDR_FAN_SWITCH_SPEED:04X}] = 0x{got:02x})"
    )


def _set_independent_gate(enabled):
    if enabled:
        value = ec_rmw(ADDR_FANCTL_RESP, set_bits=0x80)
        relationship = "independent"
    else:
        value = ec_rmw(ADDR_FANCTL_RESP, clear_bits=0x80)
        relationship = "linked"
    print(
        f"  Fan relationship: {relationship} "
        f"(XRAM[0x{ADDR_FANCTL_RESP:04X}].bit7={int(enabled)}, value=0x{value:02x})"
    )


def _clear_non_fan_overrides():
    """Neutralize AP Custom inputs that must not be activated by fan control."""
    registers = (
        (ADDR_PL1, "PL1"),
        (ADDR_PL2, "PL2"),
        (ADDR_PL4, "PL4"),
        (ADDR_TCC, "TCC"),
    )
    changed = []
    for addr, name in registers:
        previous = ec_read(addr)
        ec_write(addr, 0)
        if previous:
            changed.append(f"{name}=0x{previous:02x}")
    if changed:
        print("  Cleared non-fan AP overrides: " + ", ".join(changed))
    else:
        print("  Non-fan AP overrides: clear (PL1/PL2/PL4/TCC)")


def _enable_ap_fan_control(clear_overrides=True):
    """Enable the minimum confirmed gates for the RAM fan tables."""
    # Keep the fan worker away from a table while ownership is changing, and
    # clear shared Custom inputs before enabling 0x0727.bit6.
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    if clear_overrides:
        _clear_non_fan_overrides()
    ec_rmw(ADDR_AP_OEM, set_bits=0x01)
    ec_rmw(ADDR_AP_OEM10, set_bits=0x40)
    ec_rmw(ADDR_AP_CTL, set_bits=0x04)

    state = _read_control_state()
    status = "active" if state["table_active"] else "FAILED"
    print(f"  Fan authority: AP RAM table ({status})")
    _print_gate_details(state)


def _disable_ap_fan_control():
    """Return fan lookup to EC firmware/ROM without changing the base mode."""
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    ec_rmw(ADDR_AP_OEM10, clear_bits=0x40)

    state = _read_control_state()
    status = "active" if not state["table_active"] else "FAILED"
    print(f"  Fan authority: EC firmware/ROM ({status})")
    _print_gate_details(state)


def cmd_ap(args):
    """Use the current RAM fan tables under AP control."""
    _enable_ap_fan_control()


def cmd_bios(args):
    """Release RAM fan-table control to EC firmware/ROM."""
    _disable_ap_fan_control()


def cmd_control(args):
    """Select whether AP RAM tables or EC firmware own fan control."""
    if args.authority == "ap":
        cmd_ap(args)
    else:
        cmd_bios(args)


def _toggle_fan_boost():
    old = ec_read(ADDR_MAFAN_CTL)
    requested = old ^ FAN_BOOST_BIT
    ec_write(ADDR_MAFAN_CTL, requested)
    got = ec_read(ADDR_MAFAN_CTL)
    enabled = bool(got & FAN_BOOST_BIT)
    expected = bool(requested & FAN_BOOST_BIT)
    status = "OK" if enabled == expected else "FAILED"
    print(
        f"  FanBoost: {'on' if enabled else 'off'} "
        f"(XRAM[0x{ADDR_MAFAN_CTL:04X}]: 0x{old:02x} -> 0x{got:02x}, {status})"
    )


def _parse_set_values(percentages, explicit_relationship):
    if len(percentages) > 2:
        raise ValueError("fan set accepts at most two percentages")

    if not percentages:
        return None, explicit_relationship

    if len(percentages) == 1:
        cpu_pct = gpu_pct = percentages[0]
        inferred_relationship = False
    else:
        cpu_pct, gpu_pct = percentages
        inferred_relationship = True
    relationship = (
        inferred_relationship
        if explicit_relationship is None
        else explicit_relationship
    )
    return (cpu_pct, gpu_pct), relationship


def cmd_set(args):
    """Set fixed duty values or select linked/independent table lookup."""
    toggle_boost = getattr(args, "turbo", False)
    if not args.percentages and args.independent is None and not toggle_boost:
        raise ValueError(
            "fan set expects -t, -i/-l, and/or one/two percentages"
        )

    percentages, enable_independent = _parse_set_values(
        args.percentages,
        args.independent,
    )

    if toggle_boost:
        _toggle_fan_boost()

    if percentages is None:
        if enable_independent is not None:
            _set_independent_gate(enable_independent)
            _enable_ap_fan_control()
        return

    cpu_pct, gpu_pct = percentages
    for pct, label in ((cpu_pct, "CPU"), (gpu_pct, "GPU")):
        if pct < 0 or pct > 100:
            raise ValueError(f"{label} fan percentage must be 0-100, got {pct}")

    # Suspend table lookup so EC cannot observe a partially updated table.
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    _clear_non_fan_overrides()
    for pct, label, base in (
        (cpu_pct, "CPU", ADDR_CPU_FAN_DUTY_BASE),
        (gpu_pct, "GPU", ADDR_GPU_FAN_DUTY_BASE),
    ):
        duty = pct * 2
        for i in range(16):
            ec_write(base + i, duty)
        first = ec_read(base)
        print(f"  {label} fan duty: all 16 points set to {pct}% (EC value 0x{duty:02x})")
        print(f"  XRAM[0x{base:04X}] = 0x{first:02x} -- readback OK")

    _set_independent_gate(enable_independent)
    _enable_ap_fan_control(clear_overrides=False)


def cmd_default(args):
    """Restore a configured profile while preserving linked/independent."""
    profile = load_fan_profile(getattr(args, "file", None))
    independent = bool(ec_read(ADDR_FANCTL_RESP) & 0x80)

    def _restore(base_upt, base_dnt, base_duty, curve: FanCurve):
        for i in range(16):
            ec_write(base_upt + i, curve.up[i + 1] if i < 15 else 255)
            if i < 15:
                ec_write(base_dnt + i + 1, curve.down[i])
            ec_write(base_duty + i, curve.duty[i] * 2)

    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)
    _clear_non_fan_overrides()
    _restore(
        ADDR_CPU_FAN_UPT_BASE,
        ADDR_CPU_FAN_DNT_BASE,
        ADDR_CPU_FAN_DUTY_BASE,
        profile.main,
    )
    _restore(
        ADDR_GPU_FAN_UPT_BASE,
        ADDR_GPU_FAN_DNT_BASE,
        ADDR_GPU_FAN_DUTY_BASE,
        profile.second,
    )
    print(f"  Fan profile loaded: {profile.source}")
    print("  Fan tables restored (UpT, DownT, Duty)")
    _set_independent_gate(independent)
    _enable_ap_fan_control(clear_overrides=False)


def register(subparsers):
    fn = subparsers.add_parser("fan", help="Fan monitoring and control")
    fn.set_defaults(func=cmd_read)
    sub = fn.add_subparsers(dest="fan_op")
    sub.add_parser("read", help="Read current fan status").set_defaults(func=cmd_read)
    mon = sub.add_parser("monitor", help="Continuously monitor")
    mon.add_argument("-i", "--interval", type=float, default=1.0)
    mon.set_defaults(func=cmd_monitor)
    table = sub.add_parser("table", help="Show or reset the current fan tables")
    table.add_argument(
        "--reset",
        action="store_true",
        help="Restore configured default AP fan curves",
    )
    table.add_argument(
        "--file",
        metavar="PATH",
        help="Load this TOML profile instead of the configured/default profile",
    )
    table.set_defaults(func=cmd_table)
    control = sub.add_parser(
        "control",
        help="Select AP RAM-table or EC firmware fan control",
    )
    control.add_argument(
        "authority",
        type=prefix_choice("ap", "bios", label="fan control authority"),
        metavar="{ap,bios}",
        help="ap uses RAM tables; bios returns control to EC firmware/ROM",
    )
    control.set_defaults(func=cmd_control)
    speed = sub.add_parser(
        "speed",
        help="Set fan transition speed (unit: 2 seconds per step, 0-127)",
    )
    speed.add_argument(
        "steps",
        type=int,
        help="Unit: 2 seconds per step. 1=2s, 3=6s; 0 uses EC default (~7s observed)",
    )
    speed.set_defaults(func=cmd_switch_speed)
    set_cmd = sub.add_parser("set", help="Set fixed duty or linked/independent lookup")
    set_cmd.add_argument(
        "percentages",
        nargs="*",
        type=int,
        metavar="PCT",
        help="Zero, one, or two duty percentages (Main then Second)",
    )
    relationship = set_cmd.add_mutually_exclusive_group()
    relationship.add_argument(
        "-i",
        "--independent",
        dest="independent",
        action="store_const",
        const=True,
        help="Use separate Main/Second table indexes",
    )
    relationship.add_argument(
        "-l",
        "--linked",
        dest="independent",
        action="store_const",
        const=False,
        help="Use one shared table index",
    )
    set_cmd.add_argument(
        "-t",
        "--turbo",
        action="store_true",
        help=f"Toggle FanBoost (XRAM[0x{ADDR_MAFAN_CTL:04X}].bit6)",
    )
    set_cmd.set_defaults(independent=None)
    set_cmd.set_defaults(func=cmd_set)
