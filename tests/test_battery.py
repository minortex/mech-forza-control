import pytest
from argparse import ArgumentTypeError, Namespace

from src import battery
from src import io
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
from tests.test_io import FakeBackend


@pytest.fixture(autouse=True)
def reset_backend():
    io.close()
    yield
    io.close()


def test_battery_status_displays_upper_only_state(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 78,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x00,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0x00,
        ADDR_BATTERY_CYCLE_COUNT: 42,
        ADDR_BATTERY_CYCLE_COUNT + 1: 0,
        ADDR_BATTERY_VOLTAGE: 16818 & 0xFF,
        ADDR_BATTERY_VOLTAGE + 1: 16818 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE: 17600 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE + 1: 17600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET: 17000 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET + 1: 17000 >> 8,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "RSOC:                 78%" in output
    assert "XRAM[0x07B9] upper = 0x00" in output
    assert "limit=100%/unrestricted, stop-bit=clear" in output
    assert "XRAM[0x07D0] lower = 0x00" in output
    assert "limit=0%, cycle-active=no" in output
    assert "Mode:                 unrestricted; charging is allowed to 100%" in output
    assert "Cycle count:          42" in output
    assert "Real-time voltage:    16818 mV" in output
    assert "Base voltage:         17600 mV" in output
    assert "Charge target:        17000 mV" in output


def test_battery_status_displays_hysteresis_state(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 60,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x50,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0xA8,
        ADDR_BATTERY_CYCLE_COUNT: 10,
        ADDR_BATTERY_CYCLE_COUNT + 1: 1,
        ADDR_BATTERY_VOLTAGE: 15500 & 0xFF,
        ADDR_BATTERY_VOLTAGE + 1: 15500 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE: 17600 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE + 1: 17600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET: 16600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET + 1: 16600 >> 8,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "RSOC:                 60%" in output
    assert "XRAM[0x07B9] upper = 0x50" in output
    assert "limit=80%, stop-bit=clear" in output
    assert "XRAM[0x07D0] lower = 0xa8" in output
    assert "limit=40%, cycle-active=yes" in output
    assert "Mode:                 middle band: an existing low-started cycle remains active" in output
    assert "Cycle count:          266" in output


def test_battery_set_upper_only_sets_stop_bit_when_rsoc_is_above_threshold(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 82,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x00,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0x00,
        ADDR_AP_OEM: 0,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_set(Namespace(disable=False, up=80, down=None))

    output = capsys.readouterr().out
    assert "Configured upper threshold: 80% (lower hysteresis disabled)" in output
    assert "Stop-bit initialization: set (current RSOC 82% vs upper 80%)" in output
    assert "w568 script" in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0x00
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0xD0
    assert backend.values[ADDR_AP_OEM] & 0x01
    assert backend.writes[-2:] == [
        (ADDR_BATTERY_CHARGE_LIMIT_DOWN, 0x00),
        (ADDR_BATTERY_CHARGE_LIMIT_UP, 0xD0),
    ]


def test_battery_charge_full_clears_limits_without_touching_charge_mode(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 50,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0xD0,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0xA8,
        ADDR_BATTERY_CHARGE_MODE: 0x28,
        ADDR_AP_OEM: 1,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_charge_full(Namespace())

    output = capsys.readouterr().out
    assert "Charge limits cleared; charging is allowed up to 100%." in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0x00
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0x00
    assert backend.values[ADDR_BATTERY_CHARGE_MODE] == 0x28
    assert backend.writes == [
        (ADDR_BATTERY_CHARGE_LIMIT_DOWN, 0x00),
        (ADDR_BATTERY_CHARGE_LIMIT_UP, 0x00),
    ]


def test_battery_set_window_defaults_to_middle_band_hold(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 60,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x00,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0x00,
        ADDR_AP_OEM: 1,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_set(Namespace(disable=False, down=40, up=80))

    output = capsys.readouterr().out
    assert "Configured FlexiCharge window: 40% -> 80%" in output
    assert "Phase initialization: middle-band hold until RSOC reaches the lower threshold" in output
    assert "compatible EC firmware" in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0x28
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0xD0
    assert backend.writes == [
        (ADDR_BATTERY_CHARGE_LIMIT_DOWN, 0x28),
        (ADDR_BATTERY_CHARGE_LIMIT_UP, 0xD0),
    ]


def test_battery_set_window_preserves_active_phase_for_same_window(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 60,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x50,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0xA8,
        ADDR_AP_OEM: 1,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_set(Namespace(disable=False, down=40, up=80))

    output = capsys.readouterr().out
    assert "Phase initialization: active low-started charge cycle" in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0xA8
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0x50
    assert backend.writes == [
        (ADDR_BATTERY_CHARGE_LIMIT_DOWN, 0xA8),
        (ADDR_BATTERY_CHARGE_LIMIT_UP, 0x50),
    ]


def test_battery_set_window_starts_active_when_rsoc_is_below_lower_limit(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 35,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x00,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0x00,
        ADDR_AP_OEM: 1,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_set(Namespace(disable=False, down=40, up=80))

    output = capsys.readouterr().out
    assert "Phase initialization: active low-started charge cycle" in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_DOWN] == 0xA8
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0x50


def test_battery_status_displays_v22_persistence_state(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_RSOC: 60,
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0xD0,
        ADDR_BATTERY_CHARGE_LIMIT_DOWN: 0x3C,
        ADDR_BATTERY_CHARGE_LIMIT_LOW_SHADOW: 0xA8,
        ADDR_BATTERY_CHARGE_LIMIT_SAVE_MAGIC_0: 0xA5,
        ADDR_BATTERY_CHARGE_LIMIT_SAVE_MAGIC_1: 0x78,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "valid, saved lower=40%" in output
    assert "commit requested/pending" in output
    assert "runtime lower has not reached persistent storage yet" in output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (Namespace(disable=False, down=80, up=40), "less than upper threshold"),
    ],
)
def test_battery_set_rejects_invalid_window_arguments(args, message):
    with pytest.raises(ValueError, match=message):
        battery.cmd_set(args)


def test_upper_type_validator():
    assert battery.upper_type("80") == 80

    with pytest.raises(ArgumentTypeError, match="integer"):
        battery.upper_type("abc")

    with pytest.raises(ArgumentTypeError, match="between 1 and 99"):
        battery.upper_type("0")

    with pytest.raises(ArgumentTypeError, match="between 1 and 99"):
        battery.upper_type("100")


def test_lower_type_validator():
    assert battery.lower_type("1") == 1
    assert battery.lower_type("95") == 95

    with pytest.raises(ArgumentTypeError, match="integer"):
        battery.lower_type("abc")

    with pytest.raises(ArgumentTypeError, match="between 1 and 95"):
        battery.lower_type("0")

    with pytest.raises(ArgumentTypeError, match="between 1 and 95"):
        battery.lower_type("96")
