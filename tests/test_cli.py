import pytest

from src import fan, mode, setting
from src.__main__ import build_parser
from src.cli import resolve_unique_prefix


def test_exact_choice_wins_over_longer_prefix_match():
    assert resolve_unique_prefix("set", ("set", "setting")) == "set"


@pytest.mark.parametrize(
    ("argv", "command", "operation", "handler"),
    [
        (["f", "r"], "fan", "read", fan.cmd_read),
        (["f", "se", "-i"], "fan", "set", fan.cmd_set),
        (["m", "t"], "mode", "turbo", mode.cmd_switch),
        (["set", "w", "of"], "setting", "winlock", setting.cmd_winlock),
    ],
)
def test_commands_and_enum_values_accept_unique_prefixes(
    argv, command, operation, handler
):
    args = build_parser().parse_args(argv)

    assert args.command == command
    assert args.func is handler
    operation_dest = {
        "fan": "fan_op",
        "mode": "mode_op",
        "setting": "setting_op",
    }[command]
    assert getattr(args, operation_dest) == operation


def test_battery_enum_value_is_canonicalized_from_prefix():
    args = build_parser().parse_args(["bat", "setv", "sta"])

    assert args.command == "bat"
    assert args.bat_op == "setv"
    assert args.mode == "stationary"


def test_fan_control_authority_accepts_unique_prefix():
    args = build_parser().parse_args(["f", "con", "a"])

    assert args.command == "fan"
    assert args.fan_op == "control"
    assert args.authority == "ap"
    assert args.func is fan.cmd_control


def test_fan_table_reset_uses_long_option_abbreviation():
    args = build_parser().parse_args(["f", "tab", "--res"])

    assert args.fan_op == "table"
    assert args.reset is True
    assert args.func is fan.cmd_table


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


def test_ambiguous_top_level_command_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["b"])

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "ambiguous command 'b': backlight, bat" in error


def test_ambiguous_nested_command_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["fan", "s"])

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "ambiguous command 's': set, speed" in error


@pytest.mark.parametrize("legacy_command", ["ap", "bios", "default", "switch-speed"])
def test_removed_fan_commands_are_rejected(legacy_command, capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["fan", legacy_command])

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert f"invalid choice: '{legacy_command}'" in error


def test_ambiguous_enum_value_is_rejected(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["setting", "winlock", "o"])

    assert exc_info.value.code == 2
    error = capsys.readouterr().err
    assert "ambiguous setting state 'o': off, on" in error
