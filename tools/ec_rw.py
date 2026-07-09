"""Low-level EC byte read / write / dump."""

import argparse
import sys

from ec.io import ec_read, ec_write


def cmd_read(args):
    val = ec_read(args.addr)
    print(f"EC[{args.addr}] = {val} (0x{val:02X})")


def cmd_write(args):
    before = ec_read(args.addr)
    ec_write(args.addr, args.value)
    after = ec_read(args.addr)
    print(f"EC[{args.addr}] : {before} (0x{before:02X}) -> {after} (0x{after:02X})")


def cmd_dump(args):
    for addr in range(args.start, args.start + args.count):
        v = ec_read(addr)
        print(f"EC[{addr:4d}] = {v:3d} (0x{v:02X})")


def main():
    p = argparse.ArgumentParser(description="Low-level EC byte read / write / dump")
    sub = p.add_subparsers(dest="cmd")

    rp = sub.add_parser("read", help="Read one EC byte")
    rp.add_argument("addr", type=int, help="EC address")

    wp = sub.add_parser("write", help="Write one EC byte")
    wp.add_argument("addr", type=int, help="EC address")
    wp.add_argument("value", type=int, help="Byte value (0-255)")

    dp = sub.add_parser("dump", help="Dump EC byte range")
    dp.add_argument("start", type=int, help="Start address")
    dp.add_argument("count", type=int, nargs="?", default=16, help="Number of bytes")

    args = p.parse_args()
    if args.cmd == "read":
        cmd_read(args)
    elif args.cmd == "write":
        cmd_write(args)
    elif args.cmd == "dump":
        cmd_dump(args)
    else:
        p.print_help()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)
