import pytest
from argparse import Namespace

from ec import fan, mode
from ec import io
from ec.config import (
    ADDR_MAFAN_CTL,
    ADDR_AP_OEM9,
    ADDR_FAN_SWITCH_SPEED,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_TCC,
    CTL_TURBO,
    EC_MMIO_MAX,
)
from conftest import FakeBackend


def test_ec_read_rejects_out_of_range_addresses():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="out of range"):
        io.ec_read(-1)

    with pytest.raises(ValueError, match="out of range"):
        io.ec_read(EC_MMIO_MAX + 1)


def test_ec_write_rejects_out_of_range_values():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="out of range"):
        io.ec_write(1, -1)

    with pytest.raises(ValueError, match="out of range"):
        io.ec_write(1, 256)


def test_ec_rmw_reads_writes_and_returns_modified_value():
    backend = FakeBackend({10: 0b1010_0000})
    io._set_backend_for_testing(backend)

    result = io.ec_rmw(10, set_bits=0b0000_0011, clear_bits=0b1000_0000)

    assert result == 0b0010_0011
    assert backend.values[10] == 0b0010_0011
    assert backend.writes == [(10, 0b0010_0011)]


def test_close_closes_and_clears_cached_backend():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    io.close()

    assert backend.closed is True
    assert io._BACKEND is None


def test_read_word_helpers_use_expected_byte_order():
    backend = FakeBackend({20: 0x34, 21: 0x12, 30: 0xAB, 31: 0xCD})
    io._set_backend_for_testing(backend)

    assert io.ec_read_word(20) == 0x1234
    assert io.ec_read_word_be(30, 31) == 0xABCD


def test_mode_switch_handles_modes_without_optional_custom_args(capsys):
    io._set_backend_for_testing(FakeBackend())

    mode.cmd_switch(Namespace(mode_name="gaming"))

    output = capsys.readouterr().out
    assert "Mode: Gaming (45W balanced)" in output


def test_fixed_modes_do_not_write_tcc():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    mode.cmd_switch(Namespace(mode_name="gaming"))

    assert all(addr != ADDR_TCC for addr, _ in backend.writes)


def test_mode_switch_does_not_write_pl_registers():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    mode.cmd_switch(Namespace(mode_name="custom", tdp=65, tcc=95, separate=False))

    pl_addrs = {ADDR_PL1, ADDR_PL2, ADDR_PL4}
    assert all(addr not in pl_addrs for addr, _ in backend.writes)


def test_custom_mode_accepts_fixed_tdp_gear():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    mode.cmd_switch(Namespace(mode_name="custom", tdp=65, tcc=95, separate=False))

    assert backend.values[ADDR_MAFAN_CTL] == CTL_TURBO
    assert backend.values[ADDR_TCC] == 0xDF


def test_custom_mode_tcc_default_keeps_bit7_clear():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    mode.cmd_switch(Namespace(mode_name="custom", tdp=45, tcc=0, separate=False))

    assert backend.values[ADDR_TCC] == 0


def test_custom_mode_rejects_unknown_tdp_gear():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="25, 45, 65"):
        mode.cmd_switch(Namespace(mode_name="custom", tdp=54, tcc=0, separate=False))


def test_custom_mode_rejects_tcc_over_100():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="0-100"):
        mode.cmd_switch(Namespace(mode_name="custom", tdp=45, tcc=101, separate=False))


def test_status_distinguishes_gaming_from_custom(capsys):
    io._set_backend_for_testing(FakeBackend({ADDR_MAFAN_CTL: 0, ADDR_AP_OEM9: 0}))

    mode.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "Gaming 45W" in output
    assert "not authoritative" in output


def test_status_decodes_custom_from_oem9_bit7(capsys):
    io._set_backend_for_testing(FakeBackend({ADDR_MAFAN_CTL: 0, ADDR_AP_OEM9: 0x80}))

    mode.cmd_status(Namespace())

    output = capsys.readouterr().out
    assert "Custom 45W" in output


def test_fan_switch_speed_writes_steps_with_enable_bit():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_switch_speed(Namespace(steps=1))

    assert backend.writes == [(ADDR_FAN_SWITCH_SPEED, 0x81)]


def test_fan_switch_speed_zero_writes_ec_default():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_switch_speed(Namespace(steps=0))

    assert backend.writes == [(ADDR_FAN_SWITCH_SPEED, 0x00)]


def test_fan_switch_speed_rejects_values_outside_low_7_bits():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="0-127 steps"):
        fan.cmd_switch_speed(Namespace(steps=128))


def test_fan_read_decodes_zero_step_as_ec_default(capsys):
    io._set_backend_for_testing(FakeBackend({ADDR_FAN_SWITCH_SPEED: 0x80}))

    fan.cmd_read(Namespace())

    output = capsys.readouterr().out
    assert "EC default" in output
    assert "7s" in output
