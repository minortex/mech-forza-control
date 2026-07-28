"""Battery charge threshold control.

Upper-threshold support may need separate enablement first (for example the
w568 script, or a supported BIOS/firmware with the BIOS charge-limit option
turned on). Lower-threshold hysteresis requires compatible EC firmware.
"""

import argparse
import os
import textwrap

from .io import EC_OP_WRITE, EcOperation, ec_read, ec_read_word, ec_read_word_be, ec_transaction, ec_write
from .registers import (
    ADDR_AP_OEM,
    ADDR_BATTERY_BASE_VOLTAGE,
    ADDR_BATTERY_CHARGE_LIMIT_DOWN,
    ADDR_BATTERY_CHARGE_LIMIT_UP,
    ADDR_BATTERY_CHARGE_TARGET,
    ADDR_BATTERY_CYCLE_COUNT,
    ADDR_BATTERY_RSOC,
    ADDR_BATTERY_VOLTAGE,
)


LIMIT_MASK = 0x7F
FLAG_BIT = 0x80

BAT_HELP = textwrap.dedent(
    """    Battery charge threshold control.

    Upper-threshold support may need separate enablement first:
      - run the w568 script, or
      - flash a supported BIOS/firmware and enable charge limit in BIOS.

    Lower-threshold hysteresis (-d/--down with -u/--up) requires compatible EC
    firmware. On stock EC firmware the register writes may succeed, but the
    charging behavior may stay unchanged.
    """
)

SET_HELP = textwrap.dedent(
    """    Configure battery charge thresholds.

    Use -u/--up alone for stock upper-only behavior.
    Use -d/--down together with -u/--up for a lower/upper hysteresis window.
    Use --disable to clear both registers and restore unrestricted charging.
    """
)

SET_EPILOG = textwrap.dedent(
    """    Examples:
      mfc bat set -u 80
      mfc bat set -d 40 -u 80
      mfc bat set --disable

    Notes:
      - Upper-threshold support may need separate enablement first: w568 script,
        or supported BIOS/firmware + BIOS charge-limit option.
      - Lower-threshold hysteresis requires compatible EC firmware.
    """
)


def _ensure_ap_exist():
    v = ec_read(ADDR_AP_OEM)
    if not (v & 1):
        ec_write(ADDR_AP_OEM, v | 1)
        print(f"  XRAM[0x{ADDR_AP_OEM:04X}] ApExistFlag: 0x{v:02x} -> set bit0=1")


def _parse_int(value, *, label):
    try:
        return int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"{label} must be an integer") from exc


def upper_type(value):
    limit = _parse_int(value, label="upper threshold")
    if not 0 <= limit <= 100:
        raise argparse.ArgumentTypeError(
            "upper threshold must be between 0 and 100"
        )
    return limit


def lower_type(value):
    limit = _parse_int(value, label="lower threshold")
    if not 1 <= limit <= 95:
        raise argparse.ArgumentTypeError(
            "lower threshold must be between 1 and 95"
        )
    return limit


def _get_sysfs_battery_info():
    info = []
    base_path = "/sys/class/power_supply"
    if not os.path.exists(base_path):
        return info

    try:
        for name in os.listdir(base_path):
            if not name.startswith("BAT"):
                continue
            bat_dir = os.path.join(base_path, name)

            def read_val(filename):
                path = os.path.join(bat_dir, filename)
                if os.path.exists(path):
                    with open(path, "r") as f:
                        return f.read().strip()
                return None

            status = read_val("status")
            capacity = read_val("capacity")

            charge_now = read_val("charge_now")
            charge_full = read_val("charge_full")
            charge_design = read_val("charge_full_design")
            unit = "mAh"

            if charge_now is None:
                charge_now = read_val("energy_now")
                charge_full = read_val("energy_full")
                charge_design = read_val("energy_full_design")
                unit = "Wh"

            bat_info = {
                "name": name,
                "status": status,
                "capacity": capacity,
            }

            if charge_now and charge_full:
                try:
                    if unit == "mAh":
                        now_val = int(charge_now) / 1000.0
                        full_val = int(charge_full) / 1000.0
                        bat_info["charge_now"] = f"{now_val:.0f} {unit}"
                        bat_info["charge_full"] = f"{full_val:.0f} {unit}"

                        if charge_design:
                            design_val = int(charge_design) / 1000.0
                            bat_info["charge_design"] = f"{design_val:.0f} {unit}"
                            if design_val > 0:
                                health = (full_val / design_val) * 100
                                bat_info["health"] = f"{health:.1f}%"
                    else:
                        now_val = int(charge_now) / 1000000.0
                        full_val = int(charge_full) / 1000000.0
                        bat_info["charge_now"] = f"{now_val:.3f} {unit}"
                        bat_info["charge_full"] = f"{full_val:.3f} {unit}"

                        if charge_design:
                            design_val = int(charge_design) / 1000000.0
                            bat_info["charge_design"] = f"{design_val:.3f} {unit}"
                            if design_val > 0:
                                health = (full_val / design_val) * 100
                                bat_info["health"] = f"{health:.1f}%"
                except ValueError:
                    pass

            info.append(bat_info)
    except Exception:
        pass
    return info


def _limit_text(limit):
    return "100%/unrestricted" if limit == 0 else f"{limit}%"


def _read_state():
    high_raw = ec_read(ADDR_BATTERY_CHARGE_LIMIT_UP)
    low_raw = ec_read(ADDR_BATTERY_CHARGE_LIMIT_DOWN)
    return {
        "rsoc": ec_read(ADDR_BATTERY_RSOC),
        "high_raw": high_raw,
        "high": high_raw & LIMIT_MASK,
        "stopped": bool(high_raw & FLAG_BIT),
        "low_raw": low_raw,
        "low": low_raw & LIMIT_MASK,
        "cycle_active": bool(low_raw & FLAG_BIT),
    }


def _describe_mode(state):
    if state["low"] == 0:
        return "stock upper-only behavior (lower hysteresis disabled)"
    if not (1 <= state["low"] <= 95 and 1 <= state["high"] <= 99 and state["low"] < state["high"]):
        return "invalid lower/upper pair; firmware should fall back to stock upper-only behavior"
    if state["rsoc"] <= state["low"]:
        return "lower reached: a charge cycle should be active"
    if state["rsoc"] >= state["high"]:
        return "upper reached: charging should be inhibited"
    if state["cycle_active"]:
        return "middle band: an existing low-started cycle remains active"
    return "middle band hold: charging remains inhibited until RSOC <= lower"


def _convergence_warning(state):
    if not (1 <= state["low"] <= 95 and 1 <= state["high"] <= 99 and state["low"] < state["high"]):
        return None

    expected_stopped = not state["cycle_active"]
    if state["rsoc"] <= state["low"]:
        expected_stopped = False
    elif state["rsoc"] >= state["high"]:
        expected_stopped = True

    if state["stopped"] != expected_stopped:
        return "stop-bit has not yet converged to the current hysteresis phase decision"
    return None


def _print_state(state):
    print(f"RSOC:                 {state['rsoc']}%")
    print(
        f"XRAM[0x{ADDR_BATTERY_CHARGE_LIMIT_UP:04X}] upper = 0x{state['high_raw']:02x} "
        f"(limit={_limit_text(state['high'])}, stop-bit={'set' if state['stopped'] else 'clear'})"
    )
    print(
        f"XRAM[0x{ADDR_BATTERY_CHARGE_LIMIT_DOWN:04X}] lower = 0x{state['low_raw']:02x} "
        f"(limit={state['low']}%, cycle-active={'yes' if state['cycle_active'] else 'no'})"
    )
    print(f"Mode:                 {_describe_mode(state)}")
    warning = _convergence_warning(state)
    if warning:
        print(f"Warning:              {warning}")


def cmd_status(args):
    state = _read_state()
    cycle_count = ec_read_word(ADDR_BATTERY_CYCLE_COUNT)
    voltage = ec_read_word(ADDR_BATTERY_VOLTAGE)
    base_voltage = ec_read_word_be(ADDR_BATTERY_BASE_VOLTAGE, ADDR_BATTERY_BASE_VOLTAGE + 1)
    charge_target = ec_read_word(ADDR_BATTERY_CHARGE_TARGET)

    _print_state(state)
    print(f"Cycle count:          {cycle_count}")
    print(f"Real-time voltage:    {voltage} mV")
    print(f"Base voltage:         {base_voltage} mV")
    print(f"Charge target:        {charge_target} mV")

    sysfs_info = _get_sysfs_battery_info()
    if sysfs_info:
        print("\n[ACPI Battery Info]")
        for bat in sysfs_info:
            print(f"  {bat['name']}:")
            if bat["status"]:
                print(f"    Status:          {bat['status']}")
            if bat["capacity"]:
                print(f"    Capacity:        {bat['capacity']}%")
            if bat.get("charge_now"):
                print(f"    Current charge:  {bat['charge_now']}")
            if bat.get("charge_full"):
                print(f"    Full charge:     {bat['charge_full']}")
            if bat.get("charge_design"):
                print(f"    Design capacity: {bat['charge_design']}")
            if bat.get("health"):
                print(f"    Battery health:  {bat['health']}")


def _choose_cycle_active(old, low, high):
    if old["rsoc"] <= low:
        return True
    if old["rsoc"] >= high:
        return False
    same_window = old["low"] == low and old["high"] == high
    return same_window and old["cycle_active"]


def _validate_set_args(args):
    if args.disable:
        if args.down is not None:
            raise ValueError("--disable cannot be combined with --down")
        return "disable"

    if args.up is None:
        raise ValueError("set requires --up unless --disable is given")

    if args.down is None:
        return "upper"

    if not 2 <= args.up <= 99:
        raise ValueError(
            "upper threshold must be between 2 and 99 when --down is used"
        )
    if args.down >= args.up:
        raise ValueError("lower threshold must be less than upper threshold")
    return "window"


def _write_limits(low_raw, high_raw):
    ec_transaction(
        (
            EcOperation(EC_OP_WRITE, ADDR_BATTERY_CHARGE_LIMIT_DOWN, low_raw),
            EcOperation(EC_OP_WRITE, ADDR_BATTERY_CHARGE_LIMIT_UP, high_raw),
        )
    )


def cmd_set(args):
    mode = _validate_set_args(args)
    _ensure_ap_exist()
    old = _read_state()

    if mode == "disable":
        low_raw = 0x00
        high_raw = 0x00
    elif mode == "upper":
        stop = bool(args.up and old["rsoc"] >= args.up)
        low_raw = 0x00
        high_raw = args.up | (FLAG_BIT if stop else 0x00)
    else:
        active = _choose_cycle_active(old, args.down, args.up)
        low_raw = args.down | (FLAG_BIT if active else 0x00)
        high_raw = args.up | (0x00 if active else FLAG_BIT)

    _write_limits(low_raw, high_raw)
    new = _read_state()

    print(f"XRAM[0x{ADDR_BATTERY_CHARGE_LIMIT_DOWN:04X}]: 0x{old['low_raw']:02x} -> 0x{new['low_raw']:02x}")
    print(f"XRAM[0x{ADDR_BATTERY_CHARGE_LIMIT_UP:04X}]: 0x{old['high_raw']:02x} -> 0x{new['high_raw']:02x}")

    if mode == "disable":
        print("FlexiCharge disabled; restored unrestricted stock upper setting")
    elif mode == "upper":
        print(
            f"Configured upper threshold: {_limit_text(args.up)} "
            "(lower hysteresis disabled)"
        )
        if args.up == 0:
            print("Stop-bit initialization: cleared (unrestricted upper setting)")
        else:
            print(
                "Stop-bit initialization: "
                f"{'set' if new['stopped'] else 'clear'} "
                f"(current RSOC {old['rsoc']}% vs upper {args.up}%)"
            )
        print(
            "Note: upper-threshold support may need separate enablement first "
            "(w568 script, or supported BIOS/firmware + BIOS charge-limit option)."
        )
    else:
        print(f"Configured FlexiCharge window: {args.down}% -> {args.up}%")
        if new["cycle_active"]:
            print("Phase initialization: active low-started charge cycle")
        else:
            print(
                "Phase initialization: middle-band hold until RSOC reaches the lower threshold"
            )
        print(
            "Note: lower-threshold hysteresis requires compatible EC firmware; "
            "on stock EC firmware these register writes may succeed without "
            "changing charging behavior."
        )

    _print_state(new)


def register(subparsers):
    bat = subparsers.add_parser(
        "bat",
        help="Battery charge threshold control",
        description=BAT_HELP,
        epilog="Command names and named values accept unambiguous prefixes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    bat.set_defaults(func=cmd_status)
    sub = bat.add_subparsers(dest="bat_op")

    sub.add_parser(
        "status",
        help="Show current RSOC, thresholds, and battery status",
    ).set_defaults(func=cmd_status)

    set_parser = sub.add_parser(
        "set",
        help="Set upper-only or lower/upper charge thresholds",
        description=SET_HELP,
        epilog=SET_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = set_parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "-u",
        "--up",
        type=upper_type,
        help="Upper threshold (0-100). Use alone for upper-only mode.",
    )
    mode_group.add_argument(
        "--disable",
        action="store_true",
        help="Disable lower hysteresis and restore unrestricted charging.",
    )
    set_parser.add_argument(
        "-d",
        "--down",
        type=lower_type,
        help="Lower threshold (1-95). Requires -u/--up and compatible EC firmware.",
    )
    set_parser.set_defaults(func=cmd_set)
