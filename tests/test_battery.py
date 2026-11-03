from argparse import ArgumentTypeError, Namespace

import pytest

from src import battery
from src.registers import (
    ADDR_AP_OEM,
    ADDR_BATTERY_BASE_VOLTAGE,
    ADDR_BATTERY_CHARGE_LIMIT_DOWN,
    ADDR_BATTERY_CHARGE_LIMIT_LOW_SHADOW,
    ADDR_BATTERY_CHARGE_LIMIT_SAVE_MAGIC_0,
    ADDR_BATTERY_CHARGE_LIMIT_SAVE_MAGIC_1,
    ADDR_BATTERY_CHARGE_LIMIT_UP,
    ADDR_BATTERY_CHARGE_MODE,
    ADDR_BATTERY_CHARGE_TARGET,
    ADDR_BATTERY_CYCLE_COUNT,
    ADDR_BATTERY_RSOC,
    ADDR_BATTERY_VOLTAGE,
)


@pytest.fixture(autouse=True)
def isolated_sysfs(monkeypatch):
    monkeypatch.setattr(battery, "_get_sysfs_battery_info", lambda: [])


def status_backend(make_backend, rsoc, upper, lower, extra=None):
    initial = {
        ADDR_BATTERY_RSOC: rsoc,
        ADDR_BATTERY_CHARGE_LIMIT_UP: upper,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: lower,
        ADDR_BATTERY_CYCLE_COUNT: 42,
        ADDR_BATTERY_CYCLE_COUNT + 1: 0,
        ADDR_BATTERY_VOLTAGE: 16818 & 0xFF,
        ADDR_BATTERY_VOLTAGE + 1: 16818 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE: 17600 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE + 1: 17600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET: 17000 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET + 1: 17000 >> 8,
    }
    if extra:
        initial.update(extra)
    return make_backend(initial)


def test_battery_status_decodes_unrestricted_state(make_backend, capsys):
    status_backend(make_backend, rsoc=78, upper=0x00, lower=0x00)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "78%" in output
    assert "100%/unrestricted" in output
    assert "16818 mV" in output
    assert "17600 mV" in output
    assert "17000 mV" in output


def test_battery_status_decodes_hysteresis_state(make_backend, capsys):
    status_backend(
        make_backend,
        rsoc=60,
        upper=0x50,
        lower=0xA8,
        extra={ADDR_BATTERY_CYCLE_COUNT: 10, ADDR_BATTERY_CYCLE_COUNT + 1: 1},
    )

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "limit=80%" in output
    assert "limit=40%" in output
    assert "cycle-active=yes" in output
    assert "266" in output


def test_battery_status_decodes_persistence_handshake(make_backend, capsys):
    status_backend(
        make_backend,
        rsoc=60,
        upper=0xD0,
        lower=0x3C,
        extra={
            ADDR_BATTERY_CHARGE_LIMIT_LOW_SHADOW: 0xA8,
            ADDR_BATTERY_CHARGE_LIMIT_SAVE_MAGIC_0: 0xA5,
            ADDR_BATTERY_CHARGE_LIMIT_SAVE_MAGIC_1: 0x78,
        },
    )

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "saved lower=40%" in output
    assert "commit requested/pending" in output


def test_battery_set_upper_only_sets_stop_bit_above_threshold(make_backend):
    backend = make_backend({ADDR_BATTERY_RSOC: 82, ADDR_AP_OEM: 0})

    battery.cmd_set(Namespace(disable=False, up=80, down=None))

    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0x00
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0xD0
    assert backend.values[ADDR_AP_OEM] & 0x01


@pytest.mark.parametrize(
    ("rsoc", "existing", "expected"),
    [
        (60, (0x00, 0x00), (0x28, 0xD0)),
        (60, (0xA8, 0x50), (0xA8, 0x50)),
        (35, (0x00, 0x00), (0xA8, 0x50)),
    ],
    ids=["middle-band-hold", "preserve-active-cycle", "below-lower-starts"],
)
def test_battery_set_window_selects_phase(
    make_backend, rsoc, existing, expected
):
    backend = make_backend(
        {
            ADDR_BATTERY_RSOC: rsoc,
            ADDR_BATTERY_CHARGE_LIMIT_DOWN: existing[0],
            ADDR_BATTERY_CHARGE_LIMIT_UP: existing[1],
            ADDR_AP_OEM: 1,
        }
    )

    battery.cmd_set(Namespace(disable=False, down=40, up=80))

    assert (
        backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN],
        backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP],
    ) == expected


def test_battery_charge_full_clears_limits_without_touching_charge_mode(
    make_backend,
):
    backend = make_backend(
        {
            ADDR_BATTERY_RSOC: 50,
            ADDR_BATTERY_CHARGE_LIMIT_UP: 0xD0,
            ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0xA8,
            ADDR_BATTERY_CHARGE_MODE: 0x28,
            ADDR_AP_OEM: 1,
        }
    )

    battery.cmd_charge_full(Namespace())

    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0x00
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0x00
    assert backend.values[ADDR_BATTERY_CHARGE_MODE] == 0x28


def test_battery_set_rejects_inverted_window(make_backend):
    make_backend()

    with pytest.raises(ValueError, match="less than upper threshold"):
        battery.cmd_set(Namespace(disable=False, down=80, up=40))


@pytest.mark.parametrize(
    ("parse", "value", "expected"),
    [
        (battery.upper_type, "80", 80),
        (battery.lower_type, "1", 1),
        (battery.lower_type, "95", 95),
    ],
)
def test_threshold_parsers_accept_valid_input(parse, value, expected):
    assert parse(value) == expected


@pytest.mark.parametrize(
    ("parse", "value"),
    [
        (battery.upper_type, "abc"),
        (battery.upper_type, "0"),
        (battery.upper_type, "100"),
        (battery.lower_type, "abc"),
        (battery.lower_type, "0"),
        (battery.lower_type, "96"),
    ],
)
def test_threshold_parsers_reject_invalid_input(parse, value):
    with pytest.raises(ArgumentTypeError):
        parse(value)
