import pytest

from src.__main__ import build_parser
from src.cli import AmbiguousPrefix, NoPrefixMatch, resolve_unique_prefix

CHOICES = ("set", "setting", "status")


def test_exact_choice_wins_and_unique_prefix_resolves():
    assert resolve_unique_prefix("set", CHOICES) == "set"
    assert resolve_unique_prefix("sta", CHOICES) == "status"


@pytest.mark.parametrize(
    ("token", "error"),
    [("s", AmbiguousPrefix), ("zzz", NoPrefixMatch)],
)
def test_prefix_resolution_rejects_ambiguous_or_unknown(token, error):
    with pytest.raises(error):
        resolve_unique_prefix(token, CHOICES)


@pytest.mark.parametrize(
    ("argv", "dest", "expected"),
    [
        (["f", "r"], "fan_op", "read"),
        (["m", "t"], "mode_op", "turbo"),
        (["set", "w", "of"], "setting_op", "winlock"),
        (["bat", "charge-full"], "bat_op", "charge-full"),
    ],
)
def test_subcommands_accept_unique_prefixes(argv, dest, expected):
    args = build_parser().parse_args(argv)

    assert getattr(args, dest) == expected


def test_ambiguous_subcommand_is_rejected():
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["fan", "s"])

    assert exc_info.value.code == 2


def test_battery_set_parses_window_and_upper_only():
    window = build_parser().parse_args(["bat", "se", "-d", "40", "-u", "80"])
    assert (window.bat_op, window.down, window.up) == ("set", 40, 80)

    upper = build_parser().parse_args(["bat", "set", "-u", "80"])
    assert (upper.bat_op, upper.down, upper.up) == ("set", None, 80)


@pytest.mark.parametrize(
    ("argv", "percentages", "independent"),
    [
        (["f", "se", "50"], [50], None),
        (["f", "se", "50", "60"], [50, 60], None),
        (["f", "se", "-i"], [], True),
        (["f", "se", "-l"], [], False),
        (["f", "se", "-i", "50"], [50], True),
        (["f", "se", "-l", "50", "60"], [50, 60], False),
    ],
)
def test_fan_set_parses_relationship_flags(argv, percentages, independent):
    args = build_parser().parse_args(argv)

    assert args.percentages == percentages
    assert args.independent is independent


def test_fan_set_parses_turbo_toggle():
    args = build_parser().parse_args(["f", "se", "-t"])

    assert args.percentages == []
    assert args.independent is None
    assert args.turbo is True


def test_fan_control_accepts_unique_prefix():
    args = build_parser().parse_args(["f", "con", "a"])

    assert (args.fan_op, args.authority) == ("control", "ap")
