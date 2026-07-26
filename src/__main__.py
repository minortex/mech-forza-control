"""CLI entry point — dispatch to subcommand handlers."""

import sys

from . import mode, backlight, fan, setting, battery
from .cli import UniquePrefixArgumentParser


def build_parser():
    parser = UniquePrefixArgumentParser(
        prog="mfc",
        description="Mechrevo EC direct control",
        epilog="Command names and named values accept unambiguous prefixes.",
    )
    sub = parser.add_subparsers(title="commands", dest="command", required=True)
    mode.register(sub)
    backlight.register(sub)
    fan.register(sub)
    setting.register(sub)
    battery.register(sub)
    return parser


def _run():
    args = build_parser().parse_args()
    args.func(args)


def main():
    try:
        _run()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
