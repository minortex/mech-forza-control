import pytest

from src import io
from src.io import EC_OP_READ, EC_OP_UPDATE_BITS, EC_OP_WRITE, EcOperation
from src.registers import EC_MMIO_MAX
from tests.support import FakeBackend, NativeBatchBackend


@pytest.mark.parametrize("addr", [-1, EC_MMIO_MAX + 1])
def test_ec_read_rejects_out_of_range_address(make_backend, addr):
    make_backend()

    with pytest.raises(ValueError, match="out of range"):
        io.ec_read(addr)


@pytest.mark.parametrize("value", [-1, 256])
def test_ec_write_rejects_out_of_range_value(make_backend, value):
    make_backend()

    with pytest.raises(ValueError, match="out of range"):
        io.ec_write(1, value)


def test_ec_rmw_reads_modifies_and_writes(make_backend):
    backend = make_backend({10: 0b1010_0000})

    result = io.ec_rmw(10, set_bits=0b0000_0011, clear_bits=0b1000_0000)

    assert result == 0b0010_0011
    assert backend.writes == [(10, 0b0010_0011)]


def test_ec_rmw_uses_backend_atomic_capability(make_backend):
    class AtomicBackend(FakeBackend):
        def __init__(self):
            super().__init__()
            self.rmw_calls = []

        def ec_rmw(self, addr, set_bits, clear_bits):
            self.rmw_calls.append((addr, set_bits, clear_bits))
            return 0x5A

    backend = make_backend(cls=AtomicBackend)

    assert io.ec_rmw(10, set_bits=0x103, clear_bits=0x180) == 0x5A
    assert backend.rmw_calls == [(10, 0x03, 0x80)]


def test_close_closes_and_forgets_backend(make_backend):
    backend = make_backend()

    io.close()

    assert backend.closed is True
    assert io._BACKEND is None


def test_word_reads_use_ec_byte_order(make_backend):
    make_backend({20: 0x34, 21: 0x12, 30: 0xAB, 31: 0xCD})

    assert io.ec_read_word(20) == 0x1234
    assert io.ec_read_word_be(30, 31) == 0xABCD


def test_native_block_io_chunks_at_uapi_limit(make_backend):
    backend = make_backend(
        {i: i & 0xFF for i in range(260)}, NativeBatchBackend
    )

    assert io.ec_read_block(0, 260) == bytes(i & 0xFF for i in range(260))
    io.ec_write_block(0x0100, bytes(range(130)))

    assert backend.block_reads == [(0, 128), (128, 128), (256, 4)]
    assert [len(data) for _, data in backend.block_writes] == [128, 2]


def test_block_io_falls_back_to_byte_access(make_backend):
    backend = make_backend({1: 0xAA, 2: 0xBB})

    assert io.ec_read_block(1, 2) == b"\xaa\xbb"
    io.ec_write_block(3, b"\x01\x02")

    assert backend.writes == [(3, 1), (4, 2)]


def test_native_transaction_sends_one_vector(make_backend):
    backend = make_backend({0x10: 0xA0}, NativeBatchBackend)
    operations = [
        EcOperation(EC_OP_READ, 0x10),
        EcOperation(EC_OP_UPDATE_BITS, 0x10, 0x03, 0x83),
        EcOperation(EC_OP_WRITE, 0x11, 0x55),
    ]

    assert io.ec_transaction(operations) == [0xA0, 0x23, 0x55]
    assert backend.transactions == [operations]
    assert backend.values[0x10] == 0x23
    assert backend.values[0x11] == 0x55


def test_transaction_falls_back_to_sequential_operations(make_backend):
    backend = make_backend({0x10: 0xA0})
    operations = [
        EcOperation(EC_OP_READ, 0x10),
        EcOperation(EC_OP_UPDATE_BITS, 0x10, 0x03, 0x83),
        EcOperation(EC_OP_WRITE, 0x11, 0x55),
    ]

    assert io.ec_transaction(operations) == [0xA0, 0x23, 0x55]
    assert backend.writes == [(0x10, 0x23), (0x11, 0x55)]


def test_transaction_rejects_more_than_128_operations(make_backend):
    make_backend()

    with pytest.raises(ValueError, match="at most 128"):
        io.ec_transaction([EcOperation(EC_OP_READ, 0)] * 129)
