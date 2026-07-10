import pytest
from argparse import Namespace

from ec import mode
from ec import io
from ec.config import (
    ADDR_MAFAN_CTL,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_TCC,
    CTL_TURBO,
    EC_MMIO_MAX,
)


class FakeBackend:
    def __init__(self, initial=None):
        self.values = dict(initial or {})
        self.writes = []
        self.closed = False

    def open(self):
        pass

    def close(self):
        self.closed = True

    def ec_read(self, addr):
        return self.values.get(addr, 0)

    def ec_write(self, addr, value):
        self.writes.append((addr, value))
        self.values[addr] = value


@pytest.fixture(autouse=True)
def reset_backend():
    io.close()
    yield
    io.close()


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
