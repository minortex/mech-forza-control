"""Low-level EC byte read / write / dump."""

import argparse
import sys

from src.io import ec_read, ec_write


def _int(s: str) -> int:
    """Accept decimal and 0x-hex literals."""
    return int(s, 0)


def _fmt_addr(addr: int) -> str:
    return f"0x{addr:04X} ({addr})"


def _fmt_byte(value: int) -> str:
    return f"0x{value:02X} ({value})"


def _fmt_word(value: int) -> str:
    return f"0x{value:04X} ({value})"


def cmd_read(args):
    val = ec_read(args.addr)
    low_addr = getattr(args, "low_addr", None)
    if low_addr is not None:
        low = ec_read(low_addr)
        combined = (val << 8) | low
        print(f"EC[{_fmt_addr(args.addr)}:{_fmt_addr(low_addr)}] = {_fmt_word(combined)}")
        return

    print(f"EC[{_fmt_addr(args.addr)}] = {_fmt_byte(val)}")


def cmd_write(args):
    before = ec_read(args.addr)
    ec_write(args.addr, args.value)
    after = ec_read(args.addr)
    print(f"EC[{_fmt_addr(args.addr)}] : {_fmt_byte(before)} -> {_fmt_byte(after)}")


def cmd_dump(args):
    for addr in range(args.start, args.start + args.count):
        v = ec_read(addr)
        print(f"EC[{_fmt_addr(addr)}] = {_fmt_byte(v)}")


def main():
    p = argparse.ArgumentParser(description="Low-level EC byte read / write / dump")
    sub = p.add_subparsers(dest="cmd")

    rp = sub.add_parser("read", help="Read one EC byte or combine two bytes")
    rp.add_argument(
        "addr", type=_int, help="EC address, or high-byte address when two are given"
    )
    rp.add_argument(
        "low_addr",
        type=_int,
        nargs="?",
        help="Low-byte EC address; combined value is printed in decimal",
    )

    wp = sub.add_parser("write", help="Write one EC byte")
    wp.add_argument("addr", type=_int, help="EC address (decimal or 0x hex)")
    wp.add_argument("value", type=_int, help="Byte value (0-255, decimal or 0x hex)")

    dp = sub.add_parser("dump", help="Dump EC byte range")
    dp.add_argument("start", type=_int, help="Start address (decimal or 0x hex)")
    dp.add_argument("count", type=_int, nargs="?", default=16, help="Number of bytes")

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
