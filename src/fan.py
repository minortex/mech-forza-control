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
from .io import (
    EC_OP_READ,
    EC_OP_UPDATE_BITS,
    EC_OP_WRITE,
    EcOperation,
    ec_read,
    ec_read_block,
    ec_rmw,
    ec_transaction,
    ec_write,
)

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


def _format_table_duty(value):
    return "unused" if value == 0xFF else _format_duty(value)


_CONTROL_ADDRS = (
    ADDR_AP_OEM,
    ADDR_AP_OEM10,
    ADDR_AP_CTL,
    ADDR_FANCTL_RESP,
    ADDR_MAFAN_CTL,
)
_RUNTIME_ADDRS = (
    ADDR_CPU_TEMP,
    ADDR_MAIN_FAN_RPM_HI,
    ADDR_MAIN_FAN_RPM_LO,
    ADDR_SECOND_FAN_RPM_HI,
    ADDR_SECOND_FAN_RPM_LO,
    ADDR_MAIN_FAN_DUTY,
    ADDR_SECOND_FAN_DUTY,
    ADDR_FAN_SWITCH_SPEED,
)


def _read_registers(addresses):
    addresses = tuple(addresses)
    values = ec_transaction(EcOperation(EC_OP_READ, addr) for addr in addresses)
    return dict(zip(addresses, values))


def _decode_control_state(values):
    ap_oem = values[ADDR_AP_OEM]
    ap_exist = bool(ap_oem & 0x01)
    custom = bool(values[ADDR_AP_OEM10] & 0x40)
    fan_mgmt = bool(values[ADDR_AP_CTL] & 0x04)
    independent = bool(values[ADDR_FANCTL_RESP] & 0x80)
    table_active = ap_exist and custom and fan_mgmt
    return {
        "ap_exist": ap_exist,
        "custom": custom,
        "fan_mgmt": fan_mgmt,
        "independent": independent,
        "table_active": table_active,
        "independent_active": table_active and independent,
        "zero_rpm_warning": bool(ap_oem & 0x20),
        "fan_boost": bool(values[ADDR_MAFAN_CTL] & FAN_BOOST_BIT),
    }


def _read_control_state():
    return _decode_control_state(_read_registers(_CONTROL_ADDRS))


_NON_FAN_OVERRIDES = (
    (ADDR_PL1, "PL1"),
    (ADDR_PL2, "PL2"),
    (ADDR_PL4, "PL4"),
    (ADDR_TCC, "TCC"),
)


def _update_op(addr, mask, value):
    return EcOperation(EC_OP_UPDATE_BITS, addr, value, mask)


def _append_clear_override_ops(operations):
    result_indexes = []
    for addr, name in _NON_FAN_OVERRIDES:
        result_indexes.append((len(operations), name))
        operations.append(EcOperation(EC_OP_READ, addr))
        operations.append(EcOperation(EC_OP_WRITE, addr, 0))
    return result_indexes


def _report_cleared_overrides(results, result_indexes):
    changed = [
        f"{name}=0x{results[index]:02x}"
        for index, name in result_indexes
        if results[index]
    ]
    if changed:
        print("  Cleared non-fan AP overrides: " + ", ".join(changed))
    else:
        print("  Non-fan AP overrides: clear (PL1/PL2/PL4/TCC)")


def _append_control_reads(operations):
    start = len(operations)
    operations.extend(EcOperation(EC_OP_READ, addr) for addr in _CONTROL_ADDRS)
    return start


def _control_state_from_results(results, start):
    values = dict(zip(_CONTROL_ADDRS, results[start : start + len(_CONTROL_ADDRS)]))
    return _decode_control_state(values)


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


def _decode_runtime(values):
    return (
        values[ADDR_CPU_TEMP],
        values[ADDR_MAIN_FAN_RPM_HI] * 256 + values[ADDR_MAIN_FAN_RPM_LO],
        values[ADDR_SECOND_FAN_RPM_HI] * 256 + values[ADDR_SECOND_FAN_RPM_LO],
        values[ADDR_MAIN_FAN_DUTY],
        values[ADDR_SECOND_FAN_DUTY],
        values[ADDR_FAN_SWITCH_SPEED],
    )


def _read_fan_snapshot():
    values = _read_registers(_RUNTIME_ADDRS + _CONTROL_ADDRS)
    return _decode_runtime(values), _decode_control_state(values)


def _read():
    return _decode_runtime(_read_registers(_RUNTIME_ADDRS))


def _read_curve(up_base, down_base, duty_base):
    return {
        "up": list(ec_read_block(up_base, 16)),
        "down": list(ec_read_block(down_base, 16)),
        "duty": list(ec_read_block(duty_base, 16)),
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
    (cpu_t, mr, sr, dm, ds, sw), state = _read_fan_snapshot()
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
            (cpu_t, mr, sr, dm, ds, _), state = _read_fan_snapshot()
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

    table_addrs = tuple(range(ADDR_CPU_FAN_UPT_BASE, ADDR_GPU_FAN_DUTY_BASE + 16))
    values = _read_registers(
        _RUNTIME_ADDRS
        + _CONTROL_ADDRS
        + (ADDR_MAIN_FAN_INDEX, ADDR_SECOND_FAN_INDEX)
        + table_addrs
    )
    cpu_t, main_rpm, second_rpm, main_duty_now, second_duty_now, _ = (
        _decode_runtime(values)
    )
    state = _decode_control_state(values)
    main_index = values[ADDR_MAIN_FAN_INDEX]
    second_index = values[ADDR_SECOND_FAN_INDEX]
    main = {
        "up": [0xFF]
        + [values[ADDR_CPU_FAN_UPT_BASE + i] for i in range(15)],
        "down": [values[ADDR_CPU_FAN_DNT_BASE + i] for i in range(1, 16)]
        + [0xFF],
        "duty": [values[ADDR_CPU_FAN_DUTY_BASE + i] for i in range(16)],
    }
    second = {
        "up": [0xFF]
        + [values[ADDR_GPU_FAN_UPT_BASE + i] for i in range(15)],
        "down": [values[ADDR_GPU_FAN_DNT_BASE + i] for i in range(1, 16)]
        + [0xFF],
        "duty": [values[ADDR_GPU_FAN_DUTY_BASE + i] for i in range(16)],
    }
    rom_load_mode = _rom_table_load_mode(second["duty"])

    authority = (
        "active (AP RAM table)"
        if state["table_active"]
        else "inactive snapshot (EC firmware/ROM fallback)"
    )
    print(f"Table authority      : {authority}")
    print(f"Gates A/C/M          : {_format_gate_bits(state).replace(' ', '  ')}")
    print(
        f"Live                 : CPU {cpu_t}°C | "
        f"Main {main_rpm} RPM ({_format_duty(main_duty_now)}) | "
        f"Second {second_rpm} RPM ({_format_duty(second_duty_now)})"
    )
    print(f"Current index        : Main={main_index}, Second={second_index}")
    linked_index = None
    if state["table_active"] and state["independent_active"]:
        print("Lookup mode          : independent indexes")
        print("Current marker       : M=Main, S=Second, M/S=both")
    elif state["table_active"]:
        linked_index = main_index
        print(
            "Lookup mode          : linked; Main/CPU index drives both fans"
        )
        print("Current marker       : CUR=Main/CPU curve point")
    else:
        print("Lookup mode          : EC firmware/ROM fallback")
        print("Current marker       : none (RAM table is not authoritative)")
    if rom_load_mode is not None:
        print(
            f"ROM table trigger    : pending {ROM_TABLE_MODES[rom_load_mode]} load "
            f"(FD C9 {rom_load_mode:02X})"
        )
        print("Note                 : Second duty[13..15] are trigger bytes, not duty")
    print(
        "Point semantics      : Up: k-1 -> k when T > value; "
        "Down: k+1 -> k when T < value"
    )
    print("Threshold equality   : hold the current level")

    header = (
        f"{'Lvl':>3} {'Current':>7} | {'Main Up >°C':>11} {'Down <°C':>8} "
        f"{'Duty':>7} | {'Second Up >°C':>13} {'Down <°C':>8} {'Duty':>7}"
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
        main_duty = _format_table_duty(main["duty"][i])
        if rom_load_mode is not None and i >= 13:
            second_duty = f"0x{second['duty'][i]:02X}*"
        else:
            second_duty = _format_table_duty(second["duty"][i])
        print(
            f"{i:>3} {marker:>7} | "
            f"{_format_temperature(main['up'][i]):>11} "
            f"{_format_temperature(main['down'][i]):>8} "
            f"{main_duty:>7} | "
            f"{_format_temperature(second['up'][i]):>13} "
            f"{_format_temperature(second['down'][i]):>8} "
            f"{second_duty:>7}"
        )


def cmd_switch_speed(args):
    """Set the EC fan transition/switch speed."""
    raw = _encode_switch_speed(args.steps)
    _, got = ec_transaction(
        (
            EcOperation(EC_OP_WRITE, ADDR_FAN_SWITCH_SPEED, raw),
            EcOperation(EC_OP_READ, ADDR_FAN_SWITCH_SPEED),
        )
    )
    print(
        f"  Fan switch speed: {_decode_switch_speed(got)} "
        f"(XRAM[0x{ADDR_FAN_SWITCH_SPEED:04X}] = 0x{got:02x})"
    )


def _set_independent_gate(enabled):
    value = ec_transaction(
        (
            _update_op(
                ADDR_FANCTL_RESP,
                0x80,
                0x80 if enabled else 0,
            ),
        )
    )[0]
    relationship = "independent" if enabled else "linked"
    print(
        f"  Fan relationship: {relationship} "
        f"(XRAM[0x{ADDR_FANCTL_RESP:04X}].bit7={int(enabled)}, value=0x{value:02x})"
    )


def _clear_non_fan_overrides():
    """Neutralize AP Custom inputs that must not be activated by fan control."""
    operations = []
    result_indexes = _append_clear_override_ops(operations)
    results = ec_transaction(operations)
    _report_cleared_overrides(results, result_indexes)


def _enable_ap_fan_control(clear_overrides=True):
    """Enable the minimum confirmed gates for the RAM fan tables."""
    # One vector keeps another client from re-enabling lookup halfway through
    # ownership changes or while shared Custom inputs are being cleared.
    operations = [_update_op(ADDR_AP_CTL, 0x04, 0)]
    override_indexes = (
        _append_clear_override_ops(operations) if clear_overrides else []
    )
    operations.extend(
        (
            _update_op(ADDR_AP_OEM, 0x01, 0x01),
            _update_op(ADDR_AP_OEM10, 0x40, 0x40),
            _update_op(ADDR_AP_CTL, 0x04, 0x04),
        )
    )
    state_start = _append_control_reads(operations)
    results = ec_transaction(operations)
    if clear_overrides:
        _report_cleared_overrides(results, override_indexes)
    state = _control_state_from_results(results, state_start)
    status = "active" if state["table_active"] else "FAILED"
    print(f"  Fan authority: AP RAM table ({status})")
    _print_gate_details(state)


def _disable_ap_fan_control():
    """Return fan lookup to EC firmware/ROM without changing the base mode."""
    operations = [
        _update_op(ADDR_AP_CTL, 0x04, 0),
        _update_op(ADDR_AP_OEM10, 0x40, 0),
    ]
    state_start = _append_control_reads(operations)
    results = ec_transaction(operations)
    state = _control_state_from_results(results, state_start)
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
        raise ValueError("fan set expects -t, -i/-l, and/or one/two percentages")

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

    # The whole update is one vector transaction: no monitor/mode client can
    # re-enable lookup or observe a partially written fixed-duty table.
    operations = [_update_op(ADDR_AP_CTL, 0x04, 0)]
    override_indexes = _append_clear_override_ops(operations)
    duty_readbacks = []
    for pct, base in (
        (cpu_pct, ADDR_CPU_FAN_DUTY_BASE),
        (gpu_pct, ADDR_GPU_FAN_DUTY_BASE),
    ):
        duty = pct * 2
        operations.extend(
            EcOperation(EC_OP_WRITE, base + i, duty) for i in range(16)
        )
        duty_readbacks.append(len(operations))
        operations.append(EcOperation(EC_OP_READ, base))
    relationship_index = len(operations)
    operations.append(
        _update_op(
            ADDR_FANCTL_RESP,
            0x80,
            0x80 if enable_independent else 0,
        )
    )
    operations.extend(
        (
            _update_op(ADDR_AP_OEM, 0x01, 0x01),
            _update_op(ADDR_AP_OEM10, 0x40, 0x40),
            _update_op(ADDR_AP_CTL, 0x04, 0x04),
        )
    )
    state_start = _append_control_reads(operations)
    results = ec_transaction(operations)

    _report_cleared_overrides(results, override_indexes)
    for pct, label, base, result_index in (
        (cpu_pct, "CPU", ADDR_CPU_FAN_DUTY_BASE, duty_readbacks[0]),
        (gpu_pct, "GPU", ADDR_GPU_FAN_DUTY_BASE, duty_readbacks[1]),
    ):
        duty = pct * 2
        first = results[result_index]
        print(f"  {label} fan duty: all 16 points set to {pct}% (EC value 0x{duty:02x})")
        status = "OK" if first == duty else f"FAILED expected 0x{duty:02x}"
        print(f"  XRAM[0x{base:04X}] = 0x{first:02x} -- readback {status}")

    relationship = "independent" if enable_independent else "linked"
    relation_value = results[relationship_index]
    print(
        f"  Fan relationship: {relationship} "
        f"(XRAM[0x{ADDR_FANCTL_RESP:04X}].bit7={int(enable_independent)}, "
        f"value=0x{relation_value:02x})"
    )
    state = _control_state_from_results(results, state_start)
    status = "active" if state["table_active"] else "FAILED"
    print(f"  Fan authority: AP RAM table ({status})")
    _print_gate_details(state)


def cmd_default(args):
    """Restore a configured profile while preserving linked/independent."""
    profile = load_fan_profile(getattr(args, "file", None))

    operations = [_update_op(ADDR_AP_CTL, 0x04, 0)]
    override_indexes = _append_clear_override_ops(operations)

    def _append_restore(base_upt, base_dnt, base_duty, curve: FanCurve):
        for i in range(16):
            up = curve.up[i + 1] if i < 15 else 0xFF
            down = 0 if i == 0 else curve.down[i - 1]
            operations.append(EcOperation(EC_OP_WRITE, base_upt + i, up))
            operations.append(EcOperation(EC_OP_WRITE, base_dnt + i, down))
            operations.append(
                EcOperation(EC_OP_WRITE, base_duty + i, curve.duty[i] * 2)
            )

    _append_restore(
        ADDR_CPU_FAN_UPT_BASE,
        ADDR_CPU_FAN_DNT_BASE,
        ADDR_CPU_FAN_DUTY_BASE,
        profile.main,
    )
    _append_restore(
        ADDR_GPU_FAN_UPT_BASE,
        ADDR_GPU_FAN_DNT_BASE,
        ADDR_GPU_FAN_DUTY_BASE,
        profile.second,
    )
    operations.extend(
        (
            _update_op(ADDR_AP_OEM, 0x01, 0x01),
            _update_op(ADDR_AP_OEM10, 0x40, 0x40),
            _update_op(ADDR_AP_CTL, 0x04, 0x04),
        )
    )
    state_start = _append_control_reads(operations)
    results = ec_transaction(operations)

    _report_cleared_overrides(results, override_indexes)
    print(f"  Fan profile loaded: {profile.source}")
    print("  Fan tables restored atomically (UpT, DownT, Duty)")
    state = _control_state_from_results(results, state_start)
    relationship = "independent" if state["independent"] else "linked"
    print(f"  Fan relationship: {relationship} (preserved)")
    status = "active" if state["table_active"] else "FAILED"
    print(f"  Fan authority: AP RAM table ({status})")
    _print_gate_details(state)


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
