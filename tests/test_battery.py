import pytest
from argparse import Namespace, ArgumentTypeError

from ec import battery
from ec import io
from ec.config import (
    ADDR_AP_OEM,
    ADDR_BATTERY_CHARGE_LIMIT_UP,
    ADDR_BATTERY_CHARGE_MODE,
    ADDR_BATTERY_CYCLE_COUNT,
    ADDR_BATTERY_VOLTAGE,
    ADDR_BATTERY_BASE_VOLTAGE,
    ADDR_BATTERY_CHARGE_TARGET,
)
from tests.test_io import FakeBackend


@pytest.fixture(autouse=True)
def reset_backend():
    io.close()
    yield
    io.close()


def test_battery_status_displays_default_limit(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0,
        ADDR_BATTERY_CYCLE_COUNT: 42,
        ADDR_BATTERY_CYCLE_COUNT + 1: 0,
        ADDR_BATTERY_VOLTAGE: 16818 & 0xFF,
        ADDR_BATTERY_VOLTAGE + 1: 16818 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE: 17600 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE + 1: 17600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET: 17000 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET + 1: 17000 >> 8,
        ADDR_BATTERY_CHARGE_MODE: 0x08,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "EC[0x07B9] = 0x00" in output
    assert "Charge limit (setc): 100% (default)" in output
    assert "EC[0x07A6] = 0x08" in output
    assert "Charge mode (setv):  capacity" in output
    assert "Cycle count:         42" in output
    assert "Real-time voltage:   16818 mV" in output
    assert "Base voltage:        17600 mV" in output
    assert "Charge target:       17000 mV" in output


def test_battery_status_displays_custom_limit(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_LIMIT_UP: 80,
        ADDR_BATTERY_CYCLE_COUNT: 100,
        ADDR_BATTERY_CYCLE_COUNT + 1: 0,
        ADDR_BATTERY_VOLTAGE: 16000 & 0xFF,
        ADDR_BATTERY_VOLTAGE + 1: 16000 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE: 17600 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE + 1: 17600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET: 16600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET + 1: 16600 >> 8,
        ADDR_BATTERY_CHARGE_MODE: 0x18,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "EC[0x07B9] = 0x50" in output
    assert "Charge limit (setc): 80%" in output
    assert "EC[0x07A6] = 0x18" in output
    assert "Charge mode (setv):  balanced" in output
    assert "Cycle count:         100" in output
    assert "Real-time voltage:   16000 mV" in output
    assert "Base voltage:        17600 mV" in output
    assert "Charge target:       16600 mV" in output


def test_battery_status_displays_custom_limit_with_bit7_set(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_LIMIT_UP: 188,
        ADDR_BATTERY_CYCLE_COUNT: 10,
        ADDR_BATTERY_CYCLE_COUNT + 1: 1,  # 256 + 10 = 266
        ADDR_BATTERY_VOLTAGE: 15500 & 0xFF,
        ADDR_BATTERY_VOLTAGE + 1: 15500 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE: 17600 >> 8,
        ADDR_BATTERY_BASE_VOLTAGE + 1: 17600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET: 16600 & 0xFF,
        ADDR_BATTERY_CHARGE_TARGET + 1: 16600 >> 8,
        ADDR_BATTERY_CHARGE_MODE: 0x28,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "EC[0x07B9] = 0xbc" in output
    assert "Charge limit (setc): 60%" in output
    assert "EC[0x07A6] = 0x28" in output
    assert "Charge mode (setv):  stationary" in output
    assert "Cycle count:         266" in output
    assert "Real-time voltage:   15500 mV" in output
    assert "Base voltage:        17600 mV" in output
    assert "Charge target:       16600 mV" in output


def test_battery_setc_limit_zero(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x80,
        ADDR_AP_OEM: 0,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_setc(Namespace(limit=0))

    output = capsys.readouterr().out
    assert "EC[0x07B9]: 0x80 -> 0x80" in output
    assert "Charge limit set to: 100% (default)" in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0x80
    assert (backend.values[ADDR_AP_OEM] & 1) == 1


def test_battery_setc_limit_custom(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_LIMIT_UP: 0x80,
        ADDR_AP_OEM: 0,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_setc(Namespace(limit=80))

    output = capsys.readouterr().out
    assert "EC[0x07B9]: 0x80 -> 0xd0" in output
    assert "Charge limit set to: 80%" in output
    assert backend.values[ADDR_BATTERY_CHARGE_LIMIT_UP] == 0xd0
    assert (backend.values[ADDR_AP_OEM] & 1) == 1


def test_battery_setv_capacity(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_MODE: 0x38, # bits 5:4 are 11 (unknown)
        ADDR_AP_OEM: 0,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_setv(Namespace(mode="capacity"))

    output = capsys.readouterr().out
    assert "EC[0x07A6]: 0x38 -> 0x08" in output
    assert "Charge mode set to: capacity" in output
    assert backend.values[ADDR_BATTERY_CHARGE_MODE] == 0x08
    assert (backend.values[ADDR_AP_OEM] & 1) == 1


def test_battery_setv_balanced(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_MODE: 0x08, # bits 5:4 are 00 (capacity)
        ADDR_AP_OEM: 0,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_setv(Namespace(mode="balanced"))

    output = capsys.readouterr().out
    assert "EC[0x07A6]: 0x08 -> 0x18" in output
    assert "Charge mode set to: balanced" in output
    assert backend.values[ADDR_BATTERY_CHARGE_MODE] == 0x18
    assert (backend.values[ADDR_AP_OEM] & 1) == 1


def test_battery_setv_stationary(capsys):
    backend = FakeBackend({
        ADDR_BATTERY_CHARGE_MODE: 0x08, # bits 5:4 are 00 (capacity)
        ADDR_AP_OEM: 0,
    })
    io._set_backend_for_testing(backend)

    battery.cmd_setv(Namespace(mode="stationary"))

    output = capsys.readouterr().out
    assert "EC[0x07A6]: 0x08 -> 0x28" in output
    assert "Charge mode set to: stationary" in output
    assert backend.values[ADDR_BATTERY_CHARGE_MODE] == 0x28
    assert (backend.values[ADDR_AP_OEM] & 1) == 1
def test_limit_type_validator():
    assert battery.limit_type("0") == 0
    assert battery.limit_type("80") == 80
    assert battery.limit_type("100") == 100

    with pytest.raises(ArgumentTypeError, match="integer"):
        battery.limit_type("abc")

    with pytest.raises(ArgumentTypeError, match="between 0 and 100"):
        battery.limit_type("-1")

    with pytest.raises(ArgumentTypeError, match="between 0 and 100"):
        battery.limit_type("101")
