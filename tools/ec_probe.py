"""Probe trigger and control bytes to find fan override."""

import sys
import time

from src.io import ec_read, ec_write


def snapshot():
    rpm = ec_read(1124) * 256 + ec_read(1125)
    dl = ec_read(1883)
    dr = ec_read(1884)
    ctrl = ec_read(1873)
    trig = ec_read(1885)
    return rpm, dl, dr, ctrl, trig


def main():
    for addr in range(3872, 3888):
        ec_write(addr, 255)

    rpm0, dl0, dr0, ctrl0, trig0 = snapshot()
    print(f"Before: rpm={rpm0} dl={dl0} dr={dr0} ctrl={ctrl0} trig={trig0}")

    print("\n--- Trigger byte sweep (1885) ---")
    for val in [1, 2, 3, 0x80, 0xFF]:
        ec_write(1885, val)
        time.sleep(0.5)
        rpm, dl, dr, ctrl, trig = snapshot()
        d = " *** DUTY CHANGED ***" if (dl != dl0 or dr != dr0) else ""
        print(f"  trigger={val:3d} => ctrl={ctrl} dl={dl} dr={dr} rpm={rpm}{d}")
    ec_write(1885, trig0)

    print("\n--- Control byte sweep (1873) ---")
    for val in [0, 1, 2, 3, 4, 5, 6, 7, 8, 16, 17, 18, 24, 32, 64, 128, 144, 160, 192, 208, 224, 240, 255]:
        ec_write(1873, val)
        time.sleep(0.3)
        rpm, dl, dr, ctrl, trig = snapshot()
        d = " *** DUTY CHANGED ***" if (dl != dl0 or dr != dr0) else ""
        print(f"  ctrl={val:3d} => dl={dl} dr={dr} rpm={rpm}{d}")

    ec_write(1873, ctrl0)
    print(f"\nRestored control to {ctrl0}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
