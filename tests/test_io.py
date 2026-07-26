import pytest
from argparse import Namespace

from src import fan, mode
from src import io
from src.fan_profile import FanCurve, FanProfile
from src.registers import (
    ADDR_AP_CTL,
    ADDR_AP_OEM,
    ADDR_AP_OEM10,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_FANCTL_RESP,
    ADDR_FAN_SWITCH_SPEED,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_MAFAN_CTL,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_TCC,
    EC_MMIO_MAX,
    FAN_BOOST_BIT,
)
from src.io import EC_OP_READ, EC_OP_UPDATE_BITS, EC_OP_WRITE, EcOperation


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


class NativeBatchBackend(FakeBackend):
    def __init__(self, initial=None):
        super().__init__(initial)
        self.transactions = []
        self.block_reads = []
        self.block_writes = []

    def ec_read_block(self, addr, length):
        self.block_reads.append((addr, length))
        return bytes(self.ec_read(addr + i) for i in range(length))

    def ec_write_block(self, addr, payload):
        payload = bytes(payload)
        self.block_writes.append((addr, payload))
        for i, value in enumerate(payload):
            self.ec_write(addr + i, value)

    def ec_transaction(self, operations):
        operations = list(operations)
        self.transactions.append(operations)
        results = []
        for op in operations:
            if op.type == EC_OP_READ:
                result = self.ec_read(op.addr)
            elif op.type == EC_OP_WRITE:
                self.ec_write(op.addr, op.value)
                result = op.value
            else:
                current = self.ec_read(op.addr)
                result = (current & ~op.mask) | (op.value & op.mask)
                self.ec_write(op.addr, result)
            results.append(result)
        return results


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


def test_ec_rmw_uses_backend_atomic_operation_when_available():
    class AtomicBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.rmw_calls = []

        def ec_rmw(self, addr, set_bits, clear_bits):
            self.rmw_calls.append((addr, set_bits, clear_bits))
            return 0x5A

    backend = AtomicBackend()
    io._set_backend_for_testing(backend)

    result = io.ec_rmw(10, set_bits=0x103, clear_bits=0x180)

    assert result == 0x5A
    assert backend.rmw_calls == [(10, 0x03, 0x80)]
    assert backend.writes == []


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


def test_mode_switch_selects_base_policy_without_touching_fan_control(capsys):
    backend = FakeBackend({
        ADDR_MAFAN_CTL: 0x40,
        ADDR_AP_OEM: 0x01,
        ADDR_AP_OEM10: 0x40,
        ADDR_AP_CTL: 0x04,
        ADDR_FANCTL_RESP: 0x80,
    })
    io._set_backend_for_testing(backend)

    mode.cmd_switch(Namespace(mode_name="turbo"))

    output = capsys.readouterr().out
    assert "Base mode: Turbo (performance policy)" in output
    assert backend.values[ADDR_MAFAN_CTL] == 0x50
    assert backend.values[ADDR_AP_OEM] == 0x01
    assert backend.values[ADDR_AP_OEM10] == 0x40
    assert backend.values[ADDR_AP_CTL] == 0x04
    assert backend.values[ADDR_FANCTL_RESP] == 0x80
    assert backend.writes == [(ADDR_MAFAN_CTL, 0x50)]


def test_mode_no_longer_accepts_custom():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="unknown mode: custom"):
        mode.cmd_switch(Namespace(mode_name="custom"))


def test_mode_status_reports_base_policy_only(capsys):
    io._set_backend_for_testing(FakeBackend({
        ADDR_MAFAN_CTL: 0x00,
        ADDR_AP_OEM10: 0x40,
    }))

    mode.cmd_status(Namespace())

    assert capsys.readouterr().out.splitlines() == [
        "[EC Base Mode]",
        "  Base mode = Gaming (XRAM[0x0751] CTL = 0x00)",
    ]


def test_fan_ap_clears_non_fan_overrides_and_enables_required_gates():
    backend = FakeBackend({
        ADDR_PL1: 25,
        ADDR_PL2: 45,
        ADDR_PL4: 65,
        ADDR_TCC: 0xDF,
    })
    io._set_backend_for_testing(backend)

    fan.cmd_ap(Namespace())

    assert backend.values[ADDR_PL1] == 0
    assert backend.values[ADDR_PL2] == 0
    assert backend.values[ADDR_PL4] == 0
    assert backend.values[ADDR_TCC] == 0
    assert backend.values[ADDR_AP_OEM] & 0x01
    assert backend.values[ADDR_AP_OEM10] & 0x40
    assert backend.values[ADDR_AP_CTL] & 0x04


def test_fan_bios_releases_ram_table_without_changing_base_mode_or_relationship():
    backend = FakeBackend({
        ADDR_MAFAN_CTL: 0x10,
        ADDR_AP_OEM: 0x01,
        ADDR_AP_OEM10: 0x40,
        ADDR_AP_CTL: 0x04,
        ADDR_FANCTL_RESP: 0x80,
    })
    io._set_backend_for_testing(backend)

    fan.cmd_bios(Namespace())

    assert backend.values[ADDR_MAFAN_CTL] == 0x10
    assert backend.values[ADDR_AP_OEM] == 0x01
    assert not backend.values[ADDR_AP_OEM10] & 0x40
    assert not backend.values[ADDR_AP_CTL] & 0x04
    assert backend.values[ADDR_FANCTL_RESP] & 0x80


def test_fan_set_one_percentage_uses_linked_mode_and_ap_control():
    backend = FakeBackend({ADDR_FANCTL_RESP: 0x80})
    io._set_backend_for_testing(backend)

    fan.cmd_set(Namespace(percentages=[35], independent=None))

    assert all(backend.values[ADDR_CPU_FAN_DUTY_BASE + i] == 70 for i in range(16))
    assert all(backend.values[ADDR_GPU_FAN_DUTY_BASE + i] == 70 for i in range(16))
    assert not backend.values[ADDR_FANCTL_RESP] & 0x80
    assert backend.values[ADDR_AP_CTL] & 0x04


def test_fan_set_two_percentages_uses_independent_mode():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_set(Namespace(percentages=[40, 60], independent=None))

    assert all(backend.values[ADDR_CPU_FAN_DUTY_BASE + i] == 80 for i in range(16))
    assert all(backend.values[ADDR_GPU_FAN_DUTY_BASE + i] == 120 for i in range(16))
    assert backend.values[ADDR_FANCTL_RESP] & 0x80
    assert backend.values[ADDR_AP_CTL] & 0x04


@pytest.mark.parametrize("independent", [False, True])
def test_fan_set_can_change_only_relationship(independent):
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_set(Namespace(percentages=[], independent=independent))

    assert bool(backend.values[ADDR_FANCTL_RESP] & 0x80) is independent
    assert backend.values[ADDR_AP_CTL] & 0x04


def test_fan_set_explicit_independent_overrides_one_value_inference():
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_set(Namespace(percentages=[50], independent=True))

    assert all(backend.values[ADDR_CPU_FAN_DUTY_BASE + i] == 100 for i in range(16))
    assert all(backend.values[ADDR_GPU_FAN_DUTY_BASE + i] == 100 for i in range(16))
    assert backend.values[ADDR_FANCTL_RESP] & 0x80


def test_fan_set_explicit_linked_overrides_two_value_inference():
    backend = FakeBackend({ADDR_FANCTL_RESP: 0x80})
    io._set_backend_for_testing(backend)

    fan.cmd_set(Namespace(percentages=[40, 60], independent=False))

    assert all(backend.values[ADDR_CPU_FAN_DUTY_BASE + i] == 80 for i in range(16))
    assert all(backend.values[ADDR_GPU_FAN_DUTY_BASE + i] == 120 for i in range(16))
    assert not backend.values[ADDR_FANCTL_RESP] & 0x80


def test_fan_set_turbo_toggles_fanboost_without_enabling_ap_control(capsys):
    backend = FakeBackend({ADDR_MAFAN_CTL: 0x10})
    io._set_backend_for_testing(backend)

    args = Namespace(percentages=[], independent=None, turbo=True)
    fan.cmd_set(args)

    assert backend.values[ADDR_MAFAN_CTL] == 0x10 | FAN_BOOST_BIT
    assert backend.writes == [(ADDR_MAFAN_CTL, 0x10 | FAN_BOOST_BIT)]
    assert not backend.values.get(ADDR_AP_CTL, 0) & 0x04
    assert "FanBoost: on" in capsys.readouterr().out

    fan.cmd_set(args)

    assert backend.values[ADDR_MAFAN_CTL] == 0x10
    assert backend.writes[-1] == (ADDR_MAFAN_CTL, 0x10)
    assert "FanBoost: off" in capsys.readouterr().out


def test_fan_read_does_not_repeat_relationship_as_independent_gate(capsys):
    io._set_backend_for_testing(FakeBackend({
        ADDR_AP_OEM: 0x01,
        ADDR_AP_OEM10: 0x40,
        ADDR_AP_CTL: 0x04,
        ADDR_FANCTL_RESP: 0x80,
    }))

    fan.cmd_read(Namespace())

    output = capsys.readouterr().out
    assert "Fan relationship     : independent" in output
    assert "Gate Independent" not in output


def test_fan_read_prints_runtime_values_before_control_details(capsys):
    io._set_backend_for_testing(FakeBackend())

    fan.cmd_read(Namespace())

    lines = capsys.readouterr().out.splitlines()
    labels = [line.split(":", 1)[0].rstrip() for line in lines]
    assert labels == [
        "CPU Temp",
        "Main fan (Right) RPM",
        "Sec  fan (Left)  RPM",
        "Duty Main(R)/Sec(L)",
        "Control path",
        "Switch speed",
        "FanBoost",
        "Fan relationship",
        "Zero-RPM warning",
        "Gate APExist",
        "Gate Custom",
        "Gate FanMgmt",
    ]


def test_fan_table_file_requires_reset():
    io._set_backend_for_testing(FakeBackend())

    with pytest.raises(ValueError, match="--file requires --reset"):
        fan.cmd_table(Namespace(reset=False, file="custom.toml"))


def test_fan_table_reset_preserves_relationship(monkeypatch):
    backend = FakeBackend({ADDR_FANCTL_RESP: 0x80})
    io._set_backend_for_testing(backend)
    main = FanCurve(tuple(range(16)), tuple(range(16)), (20,) * 16)
    second = FanCurve(tuple(range(16)), tuple(range(16)), (10,) * 16)
    monkeypatch.setattr(
        fan,
        "load_fan_profile",
        lambda path=None: FanProfile(main, second, "test-profile.toml"),
    )

    fan.cmd_table(Namespace(reset=True, file=None))

    assert backend.values[ADDR_CPU_FAN_DUTY_BASE] == 40
    assert backend.values[ADDR_GPU_FAN_DUTY_BASE] == 20
    assert backend.values[ADDR_FANCTL_RESP] & 0x80
    assert backend.values[ADDR_AP_CTL] & 0x04


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


def test_block_io_uses_native_capability_and_chunks_at_uapi_limit():
    backend = NativeBatchBackend({i: i & 0xFF for i in range(260)})
    io._set_backend_for_testing(backend)

    payload = io.ec_read_block(0, 260)
    io.ec_write_block(0x0100, bytes(range(130)))

    assert payload == bytes(i & 0xFF for i in range(260))
    assert backend.block_reads == [(0, 128), (128, 128), (256, 4)]
    assert [len(data) for _, data in backend.block_writes] == [128, 2]


def test_transaction_uses_native_backend_capability():
    backend = NativeBatchBackend({0x10: 0xA0})
    io._set_backend_for_testing(backend)
    operations = [
        EcOperation(EC_OP_READ, 0x10),
        EcOperation(EC_OP_UPDATE_BITS, 0x10, 0x03, 0x83),
        EcOperation(EC_OP_WRITE, 0x11, 0x55),
    ]

    assert io.ec_transaction(operations) == [0xA0, 0x23, 0x55]
    assert backend.transactions == [operations]
    assert backend.values[0x10] == 0x23
    assert backend.values[0x11] == 0x55


def test_fan_read_is_one_atomic_snapshot(capsys):
    backend = NativeBatchBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_read(Namespace())

    assert len(backend.transactions) == 1
    assert len(backend.transactions[0]) == 13
    assert all(op.type == EC_OP_READ for op in backend.transactions[0])


def test_fan_table_is_one_103_read_atomic_snapshot(capsys):
    backend = NativeBatchBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_table(Namespace(reset=False, file=None))

    assert len(backend.transactions) == 1
    assert len(backend.transactions[0]) == 103
    assert all(op.type == EC_OP_READ for op in backend.transactions[0])


def test_mode_switch_is_one_atomic_update_and_read(capsys):
    backend = NativeBatchBackend({ADDR_MAFAN_CTL: FAN_BOOST_BIT})
    io._set_backend_for_testing(backend)

    mode.cmd_switch(Namespace(mode_name="turbo"))

    assert len(backend.transactions) == 1
    assert backend.transactions[0] == [
        EcOperation(EC_OP_UPDATE_BITS, ADDR_MAFAN_CTL, 0x10, 0x90),
        EcOperation(EC_OP_READ, ADDR_MAFAN_CTL),
    ]
    assert backend.values[ADDR_MAFAN_CTL] == FAN_BOOST_BIT | 0x10


def test_fixed_fan_set_is_one_atomic_transaction():
    backend = NativeBatchBackend()
    io._set_backend_for_testing(backend)

    fan.cmd_set(Namespace(percentages=[35], independent=None, turbo=False))

    assert len(backend.transactions) == 1
    assert len(backend.transactions[0]) == 52
    assert backend.values[ADDR_AP_CTL] & 0x04
    assert not backend.values[ADDR_FANCTL_RESP] & 0x80


def test_fan_table_reset_is_one_atomic_transaction(monkeypatch):
    backend = NativeBatchBackend({ADDR_FANCTL_RESP: 0x80})
    io._set_backend_for_testing(backend)
    curve = FanCurve(tuple(range(16)), tuple(range(16)), (20,) * 16)
    monkeypatch.setattr(
        fan,
        "load_fan_profile",
        lambda path=None: FanProfile(curve, curve, "test-profile.toml"),
    )

    fan.cmd_table(Namespace(reset=True, file=None))

    assert len(backend.transactions) == 1
    assert len(backend.transactions[0]) == 111
    assert backend.values[ADDR_FANCTL_RESP] & 0x80
    assert backend.values[ADDR_AP_CTL] & 0x04
