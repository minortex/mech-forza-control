"""CLI entry point — dispatch to subcommand handlers.

Invoke via:
  python -m ec mode gaming
  python -m ec backlight on
  python -m ec fan read
"""

import sys

from . import mode, backlight, fan, setting
from . import state


def main():
    import argparse
    p = argparse.ArgumentParser(prog="ec", description="Mechrevo EC direct control")
    sub = p.add_subparsers(title="commands", dest="command", required=True)
    mode.register(sub)
    backlight.register(sub)
    fan.register(sub)
    setting.register(sub)
    state.register(sub)
    state.register_apply(sub)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
