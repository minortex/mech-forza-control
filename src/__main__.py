"""CLI entry point — dispatch to subcommand handlers."""

import sys

from . import mode, backlight, fan, setting, battery


def main():
    import argparse
    p = argparse.ArgumentParser(prog="mfc", description="Mechrevo EC direct control")
    sub = p.add_subparsers(title="commands", dest="command", required=True)
    mode.register(sub)
    backlight.register(sub)
    fan.register(sub)
    setting.register(sub)
    battery.register(sub)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
