from argparse import Namespace

import pytest

from src import fan
from src.fan_profile import FanCurve, FanProfile
from src.io import EC_OP_READ
from src.registers import (
    ADDR_AP_CTL,
    ADDR_AP_OEM,
    ADDR_AP_OEM10,
    ADDR_CPU_FAN_DNT_BASE,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_CPU_FAN_UPT_BASE,
    ADDR_CPU_TEMP,
    ADDR_FANCTL_RESP,
    ADDR_FAN_SWITCH_SPEED,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_MAFAN_CTL,
    ADDR_MAIN_FAN_DUTY,
    ADDR_MAIN_FAN_INDEX,
    ADDR_MAIN_FAN_RPM_HI,
    ADDR_MAIN_FAN_RPM_LO,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_SECOND_FAN_DUTY,
    ADDR_SECOND_FAN_RPM_HI,
    ADDR_SECOND_FAN_RPM_LO,
    ADDR_TCC,
    FAN_BOOST_BIT,
)
from tests.support import NativeBatchBackend


def test_fan_ap_clears_non_fan_overrides_and_sets_gates(make_backend):
    backend = make_backend(
        {ADDR_PL1: 25, ADDR_PL2: 45, ADDR_PL4: 65, ADDR_TCC: 0xDF}
    )

    fan.cmd_ap(Namespace())

    for addr in (ADDR_PL1, ADDR_PL2, ADDR_PL4, ADDR_TCC):
        assert backend.values[addr] == 0
    assert backend.values[ADDR_AP_OEM] & 0x01
    assert backend.values[ADDR_AP_OEM10] & 0x40
    assert backend.values[ADDR_AP_CTL] & 0x04


def test_fan_bios_releases_ram_table_without_touching_mode_or_relationship(
    make_backend,
):
    backend = make_backend(
        {
            ADDR_MAFAN_CTL: 0x10,
            ADDR_AP_OEM: 0x01,
            ADDR_AP_OEM10: 0x40,
            ADDR_AP_CTL: 0x04,
            ADDR_FANCTL_RESP: 0x80,
        }
    )

    fan.cmd_bios(Namespace())

    assert backend.values[ADDR_MAFAN_CTL] == 0x10
    assert backend.values[ADDR_FANCTL_RESP] == 0x80
    assert not backend.values[ADDR_AP_OEM10] & 0x40
    assert not backend.values[ADDR_AP_CTL] & 0x04


@pytest.mark.parametrize(
    ("percentages", "independent", "expected_independent", "main", "second"),
    [
        ([35], None, False, 70, 70),
        ([40, 60], None, True, 80, 120),
        ([50], True, True, 100, 100),
        ([40, 60], False, False, 80, 120),
    ],
)
def test_fan_set_maps_duty_and_relationship(
    make_backend, percentages, independent, expected_independent, main, second
):
    backend = make_backend(
        {ADDR_FANCTL_RESP: 0x80 if independent is False else 0}
    )

    fan.cmd_set(Namespace(percentages=percentages, independent=independent))

    assert all(
        backend.values[ADDR_CPU_FAN_DUTY_BASE + i] == main for i in range(16)
    )
    assert all(
        backend.values[ADDR_GPU_FAN_DUTY_BASE + i] == second for i in range(16)
    )
    assert bool(backend.values[ADDR_FANCTL_RESP] & 0x80) is expected_independent
    assert backend.values[ADDR_AP_CTL] & 0x04


@pytest.mark.parametrize("independent", [False, True])
def test_fan_set_relationship_only_preserves_duties(make_backend, independent):
    backend = make_backend({ADDR_CPU_FAN_DUTY_BASE: 0x22})

    fan.cmd_set(Namespace(percentages=[], independent=independent))

    assert bool(backend.values[ADDR_FANCTL_RESP] & 0x80) is independent
    assert backend.values[ADDR_CPU_FAN_DUTY_BASE] == 0x22
    assert backend.values[ADDR_AP_CTL] & 0x04


def test_fan_set_is_one_atomic_transaction(make_backend):
    backend = make_backend(cls=NativeBatchBackend)

    fan.cmd_set(Namespace(percentages=[35], independent=None))

    assert len(backend.transactions) == 1


def test_fan_set_turbo_only_toggles_fanboost(make_backend):
    backend = make_backend({ADDR_MAFAN_CTL: 0x10})
    args = Namespace(percentages=[], independent=None, turbo=True)

    fan.cmd_set(args)

    assert backend.writes == [(ADDR_MAFAN_CTL, 0x10 | FAN_BOOST_BIT)]
    assert not backend.values.get(ADDR_AP_CTL, 0) & 0x04

    fan.cmd_set(args)

    assert backend.values[ADDR_MAFAN_CTL] == 0x10


def test_fan_read_uses_one_atomic_snapshot(make_backend):
    backend = make_backend(cls=NativeBatchBackend)

    fan.cmd_read(Namespace())

    assert len(backend.transactions) == 1
    assert all(op.type == EC_OP_READ for op in backend.transactions[0])


def test_fan_read_decodes_runtime_values(make_backend, capsys):
    make_backend(
        {
            ADDR_CPU_TEMP: 73,
            ADDR_MAIN_FAN_RPM_HI: 12,
            ADDR_MAIN_FAN_RPM_LO: 128,
            ADDR_SECOND_FAN_RPM_HI: 10,
            ADDR_SECOND_FAN_RPM_LO: 0,
            ADDR_MAIN_FAN_DUTY: 88,
            ADDR_SECOND_FAN_DUTY: 76,
        }
    )

    fan.cmd_read(Namespace())

    output = capsys.readouterr().out
    assert "73" in output
    assert "RPM : 3200" in output
    assert "RPM : 2560" in output
    assert "44.0%" in output
    assert "38.0%" in output


def test_fan_table_read_is_one_atomic_snapshot(make_backend):
    backend = make_backend(cls=NativeBatchBackend)

    fan.cmd_table(Namespace(reset=False, file=None))

    assert len(backend.transactions) == 1


def test_fan_table_reports_live_values_and_unused_sentinel(make_backend, capsys):
    initial = {
        ADDR_CPU_TEMP: 73,
        ADDR_MAIN_FAN_INDEX: 5,
        ADDR_MAIN_FAN_RPM_HI: 12,
        ADDR_MAIN_FAN_RPM_LO: 128,
        ADDR_SECOND_FAN_RPM_HI: 10,
        ADDR_SECOND_FAN_RPM_LO: 0,
        ADDR_MAIN_FAN_DUTY: 88,
        ADDR_SECOND_FAN_DUTY: 76,
        ADDR_CPU_FAN_DUTY_BASE + 15: 0xFF,
        ADDR_GPU_FAN_DUTY_BASE + 15: 0xFF,
    }
    make_backend(initial)

    fan.cmd_table(Namespace(reset=False, file=None))

    output = capsys.readouterr().out
    assert "CPU 73" in output
    assert "3200 RPM" in output
    assert "2560 RPM" in output
    assert "44.0%" in output
    assert "38.0%" in output
    last_row = next(
        line for line in output.splitlines() if line.startswith(" 15")
    )
    assert last_row.count("unused") == 2


def test_fan_table_reset_derives_ec_table_from_profile(make_backend, monkeypatch):
    backend = make_backend({ADDR_FANCTL_RESP: 0x80}, NativeBatchBackend)
    curve = FanCurve(tuple(range(16)), tuple(range(16)), (20,) * 16)
    monkeypatch.setattr(
        fan,
        "load_fan_profile",
        lambda path=None: FanProfile(curve, curve, "test.toml"),
    )

    fan.cmd_table(Namespace(reset=True, file=None))

    assert backend.values[ADDR_CPU_FAN_UPT_BASE] == 1
    assert backend.values[ADDR_CPU_FAN_UPT_BASE + 15] == 0xFF
    assert backend.values[ADDR_CPU_FAN_DNT_BASE] == 0
    assert backend.values[ADDR_CPU_FAN_DNT_BASE + 15] == 14
    assert backend.values[ADDR_CPU_FAN_DUTY_BASE] == 40
    assert backend.values[ADDR_FANCTL_RESP] & 0x80
    assert len(backend.transactions) == 1


def test_fan_table_file_requires_reset(make_backend):
    make_backend()

    with pytest.raises(ValueError, match="--file requires --reset"):
        fan.cmd_table(Namespace(reset=False, file="custom.toml"))


@pytest.mark.parametrize(("steps", "raw"), [(0, 0x00), (1, 0x81), (127, 0xFF)])
def test_fan_switch_speed_encodes_steps(make_backend, steps, raw):
    backend = make_backend()

    fan.cmd_switch_speed(Namespace(steps=steps))

    assert backend.writes == [(ADDR_FAN_SWITCH_SPEED, raw)]


def test_fan_switch_speed_rejects_out_of_range(make_backend):
    make_backend()

    with pytest.raises(ValueError, match="0-127"):
        fan.cmd_switch_speed(Namespace(steps=128))
