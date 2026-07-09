"""Fan monitoring — read RPM, duty, control byte."""

import time

from .io import ec_read


def _read():
    return (
        ec_read(1124) * 256 + ec_read(1125),
        ec_read(1132) * 256 + ec_read(1131),
        ec_read(1873),
        ec_read(1883),
        ec_read(1884),
    )


def cmd_read(args):
    mr, sr, ctrl, dm, ds = _read()
    print(f"Main fan (Right) RPM : {mr}")
    print(f"Sec  fan (Left)  RPM : {sr}")
    print(f"Control byte         : {ctrl} (0b{ctrl:08b})")
    print(f"Duty Main(R)/Sec(L)  : {dm} / {ds}")


def cmd_monitor(args):
    iv = args.interval
    print(f"Monitoring every {iv}s, Ctrl+C to stop\n")
    hdr = f"{'Time':>8}  {'MainRPM':>7}  {'SecRPM':>7}  {'Ctrl':>5}  {'DutyM(R)':>8}  {'DutyS(L)':>8}"
    print(hdr); print("-" * 60)
    try:
        while True:
            mr, sr, ctrl, dm, ds = _read()
            print(f"{time.strftime('%H:%M:%S')}  {mr:>7}  {sr:>7}  {ctrl:>5}  {dm:>8}  {ds:>8}", flush=True)
            time.sleep(iv)
    except KeyboardInterrupt:
        pass


def register(subparsers):
    fn = subparsers.add_parser("fan", help="Fan monitoring")
    sub = fn.add_subparsers(dest="fan_op", required=True)
    sub.add_parser("read", help="Read current fan status").set_defaults(func=cmd_read)
    mon = sub.add_parser("monitor", help="Continuously monitor")
    mon.add_argument("-i", "--interval", type=float, default=1.0)
    mon.set_defaults(func=cmd_monitor)
