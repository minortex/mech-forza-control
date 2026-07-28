import pytest

from src import battery, fan, mode, setting
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


def test_battery_set_parses_upper_only_mode():
    args = build_parser().parse_args(["bat", "set", "-u", "80"])

    assert args.command == "bat"
    assert args.bat_op == "set"
    assert args.up == 80
    assert args.down is None
    assert args.disable is False
    assert args.func is battery.cmd_set


def test_battery_set_parses_window_mode_from_prefixes():
    args = build_parser().parse_args(["bat", "se", "-d", "40", "-u", "80"])

    assert args.command == "bat"
    assert args.bat_op == "set"
    assert args.down == 40
    assert args.up == 80
    assert args.disable is False
    assert args.func is battery.cmd_set


def test_battery_set_parses_disable_mode():
    args = build_parser().parse_args(["bat", "set", "--disable"])

    assert args.command == "bat"
    assert args.bat_op == "set"
    assert args.disable is True
    assert args.up is None
    assert args.down is None
    assert args.func is battery.cmd_set


def test_battery_help_mentions_enablement_and_ec_firmware(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["bat", "-h"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "w568" in output
    assert "compatible EC" in output


def test_battery_set_help_mentions_window_examples(capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(["bat", "set", "-h"])

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "mfc bat set -u 80" in output
    assert "mfc bat set -d 40 -u 80" in output
    assert "compatible EC firmware" in output


@pytest.mark.parametrize(
    "argv",
    [
        ["bat", "set"],
        ["bat", "set", "-d", "40"],
        ["bat", "set", "--disable", "-u", "80"],
    ],
)
def test_battery_invalid_parser_combinations_are_rejected(argv, capsys):
    with pytest.raises(SystemExit) as exc_info:
        build_parser().parse_args(argv)

    assert exc_info.value.code == 2
    assert capsys.readouterr().err


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


def test_fan_set_parses_turbo_toggle():
    args = build_parser().parse_args(["f", "se", "-t"])

    assert args.percentages == []
    assert args.independent is None
    assert args.turbo is True


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
