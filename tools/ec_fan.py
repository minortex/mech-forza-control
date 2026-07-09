#!/usr/bin/env python3
"""EC fan read / monitor."""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import ec_io

# --- EC addresses ---
ADDR_MAIN_FAN_RPM_H = 1124
ADDR_MAIN_FAN_RPM_L = 1125
ADDR_SEC_FAN_RPM_H = 1132
ADDR_SEC_FAN_RPM_L = 1131
ADDR_FAN_CONTROL = 1873
ADDR_MAIN_FAN_DUTY = 1883
ADDR_SEC_FAN_DUTY = 1884


def read_fans():
    rpm_mh = ec_io.ec_read(ADDR_MAIN_FAN_RPM_H)
    rpm_ml = ec_io.ec_read(ADDR_MAIN_FAN_RPM_L)
    rpm_sh = ec_io.ec_read(ADDR_SEC_FAN_RPM_H)
    rpm_sl = ec_io.ec_read(ADDR_SEC_FAN_RPM_L)
    ctrl = ec_io.ec_read(ADDR_FAN_CONTROL)
    duty_main = ec_io.ec_read(ADDR_MAIN_FAN_DUTY)
    duty_sec = ec_io.ec_read(ADDR_SEC_FAN_DUTY)
    return {
        "main_rpm": rpm_mh * 256 + rpm_ml,
        "sec_rpm": rpm_sh * 256 + rpm_sl,
        "control": ctrl,
        "control_bin": f"0b{ctrl:08b}",
        "duty_main": duty_main,
        "duty_sec": duty_sec,
    }


def cmd_read(args):
    d = read_fans()
    print(f"Main fan (Right) RPM : {d['main_rpm']}")
    print(f"Sec  fan (Left)  RPM : {d['sec_rpm']}")
    print(f"Control byte         : {d['control']} ({d['control_bin']})")
    print(f"Duty Main(R) / Sec(L): {d['duty_main']} / {d['duty_sec']}")


def cmd_monitor(args):
    interval = args.interval
    print(f"Monitoring every {interval}s, Ctrl+C to stop\n")
    print(f"{'Time':>8}  {'MainRPM':>7}  {'SecRPM':>7}  {'Ctrl':>5}  {'DutyM(R)':>8}  {'DutyS(L)':>8}")
    print("-" * 60)
    while True:
        d = read_fans()
        print(
            f"{time.strftime('%H:%M:%S')}  {d['main_rpm']:>7}  {d['sec_rpm']:>7}"
            f"  {d['control']:>5}  {d['duty_main']:>8}  {d['duty_sec']:>8}",
            flush=True,
        )
        time.sleep(interval)


def main():
    p = argparse.ArgumentParser(description="EC fan read / monitor")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("read", help="Read fan RPM, duty, control byte")

    mon = sub.add_parser("monitor", help="Continuously monitor fan status")
    mon.add_argument("-i", "--interval", type=float, default=1.0)

    args = p.parse_args()
    if args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "monitor":
        cmd_monitor(args)
    else:
        p.print_help()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
