"""Battery charging limit control — XRAM[1977] register."""

import argparse
import os

from .config import (
    ADDR_AP_OEM,
    ADDR_BATTERY_CHARGE_LIMIT_UP,
    ADDR_BATTERY_CHARGE_MODE,
    ADDR_BATTERY_CYCLE_COUNT,
    ADDR_BATTERY_VOLTAGE,
    ADDR_BATTERY_BASE_VOLTAGE,
    ADDR_BATTERY_CHARGE_TARGET,
)
from .io import ec_read, ec_write, ec_read_word, ec_read_word_be


def _ensure_ap_exist():
    v = ec_read(ADDR_AP_OEM)
    if not (v & 1):
        ec_write(ADDR_AP_OEM, v | 1)
        print(f"  XRAM[0x{ADDR_AP_OEM:04X}] ApExistFlag: 0x{v:02x} -> set bit0=1")


def _get_sysfs_battery_info():
    info = []
    base_path = "/sys/class/power_supply"
    if not os.path.exists(base_path):
        return info

    try:
        for name in os.listdir(base_path):
            if name.startswith("BAT"):
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


def cmd_status(args):
    reg = ec_read(ADDR_BATTERY_CHARGE_LIMIT_UP)
    limit = reg & 0x7F
    limit_str = "100% (default)" if limit == 0 else f"{limit}%"
    
    mode_reg = ec_read(ADDR_BATTERY_CHARGE_MODE)
    mode_bits = (mode_reg >> 4) & 0x03
    if mode_bits == 0:
        mode_str = "capacity"
    elif mode_bits == 1:
        mode_str = "balanced"
    elif mode_bits == 2:
        mode_str = "stationary"
    else:
        mode_str = f"unknown (0x{mode_bits:x})"

    cycle_count = ec_read_word(ADDR_BATTERY_CYCLE_COUNT)
    voltage = ec_read_word(ADDR_BATTERY_VOLTAGE)
    base_voltage = ec_read_word_be(ADDR_BATTERY_BASE_VOLTAGE, ADDR_BATTERY_BASE_VOLTAGE + 1)
    charge_target = ec_read_word(ADDR_BATTERY_CHARGE_TARGET)
    
    print(f"XRAM[0x{ADDR_BATTERY_CHARGE_LIMIT_UP:04X}] = 0x{reg:02x}")
    print(f"  Charge limit (setc): {limit_str}")
    print(f"XRAM[0x{ADDR_BATTERY_CHARGE_MODE:04X}] = 0x{mode_reg:02x}")
    print(f"  Charge mode (setv):  {mode_str}")
    print(f"  Cycle count:         {cycle_count}")
    print(f"  Real-time voltage:   {voltage} mV")
    print(f"  Base voltage:        {base_voltage} mV")
    print(f"  Charge target:       {charge_target} mV")
    
    sysfs_info = _get_sysfs_battery_info()
    if sysfs_info:
        print("\n[ACPI Battery Info]")
        for bat in sysfs_info:
            print(f"  Device:       {bat['name']}")
            if bat.get("status"):
                print(f"  Status:       {bat['status']}")
            if bat.get("capacity"):
                print(f"  Capacity:     {bat['capacity']}%")
            if bat.get("charge_now") and bat.get("charge_full"):
                print(f"  Remaining:    {bat['charge_now']} / {bat['charge_full']}")
            if bat.get("charge_design"):
                print(f"  Design capacity: {bat['charge_design']}")
            if bat.get("health"):
                print(f"  Battery health:  {bat['health']}")


def cmd_setc(args):
    _ensure_ap_exist()
    limit = args.limit
    reg = ec_read(ADDR_BATTERY_CHARGE_LIMIT_UP)
    new_reg = (reg & 0x80) | (limit & 0x7F)
    ec_write(ADDR_BATTERY_CHARGE_LIMIT_UP, new_reg)
    
    after = ec_read(ADDR_BATTERY_CHARGE_LIMIT_UP)
    after_limit = after & 0x7F
    limit_str = "100% (default)" if after_limit == 0 else f"{after_limit}%"
    
    print(f"  XRAM[0x{ADDR_BATTERY_CHARGE_LIMIT_UP:04X}]: 0x{reg:02x} -> 0x{after:02x}")
    print(f"  Charge limit set to: {limit_str}")


def cmd_setv(args):
    _ensure_ap_exist()
    mode = args.mode
    reg = ec_read(ADDR_BATTERY_CHARGE_MODE)
    new_reg = reg & ~0x30
    if mode == "balanced":
        new_reg |= 0x10
    elif mode == "stationary":
        new_reg |= 0x20
        
    ec_write(ADDR_BATTERY_CHARGE_MODE, new_reg)
    after = ec_read(ADDR_BATTERY_CHARGE_MODE)
    after_bits = (after >> 4) & 0x03
    
    if after_bits == 0:
        after_mode = "capacity"
    elif after_bits == 1:
        after_mode = "balanced"
    elif after_bits == 2:
        after_mode = "stationary"
    else:
        after_mode = f"unknown (0x{after_bits:x})"
        
    print(f"  XRAM[0x{ADDR_BATTERY_CHARGE_MODE:04X}]: 0x{reg:02x} -> 0x{after:02x}")
    print(f"  Charge mode set to: {after_mode}")


def limit_type(value):
    try:
        val = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Limit must be an integer")
    if not (0 <= val <= 100):
        raise argparse.ArgumentTypeError("Limit must be between 0 and 100")
    return val


def register(subparsers):
    s = subparsers.add_parser(
        "bat",
        help="Battery charging control (capacity percentage and voltage restriction mode)",
    )
    s.set_defaults(func=cmd_status)
    sub = s.add_subparsers(dest="bat_op")
    
    sub.add_parser("status", help="Show current battery charging limit and status").set_defaults(func=cmd_status)
    
    sp_c = sub.add_parser("setc", help="Set battery charging limit percentage (0-100, 0=100%% default)")
    sp_c.add_argument("limit", type=limit_type, help="Charge limit percentage (0 to 100)")
    sp_c.set_defaults(func=cmd_setc)
    
    sp_v = sub.add_parser("setv", help="Set battery charging voltage restriction mode (stationary, balanced, capacity)")
    sp_v.add_argument("mode", choices=("stationary", "balanced", "capacity"), help="Voltage restriction mode")
    sp_v.set_defaults(func=cmd_setv)
