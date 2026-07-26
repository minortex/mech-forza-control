import os

import pytest

from src.backends import linux
from src.io import EC_OP_READ, EC_OP_UPDATE_BITS, EcOperation


def test_ioctl_numbers_match_kernel_uapi():
    assert linux._EC_IO.size == 4
    assert linux.MECHREVO_EC_IOC_READ == 0xC0044D00
    assert linux.MECHREVO_EC_IOC_WRITE == 0x40044D01
    assert linux.MECHREVO_EC_IOC_UPDATE_BITS == 0xC0044D02
    assert linux._EC_BLOCK_SIZE == 132
    assert linux._EC_OP.size == 6
    assert linux._EC_XFER_SIZE == 772
    assert linux.MECHREVO_EC_IOC_READ_BLOCK == 0xC0844D03
    assert linux.MECHREVO_EC_IOC_WRITE_BLOCK == 0x40844D04
    assert linux.MECHREVO_EC_IOC_XFER == 0xC3044D05


def test_kernel_backend_read_and_write_ioctl(monkeypatch):
    opened = []
    closed = []
    calls = []

    def fake_open(path, flags):
        opened.append((path, flags))
        return 17

    def fake_close(fd):
        closed.append(fd)

    def fake_ioctl(fd, request, data, mutate):
        addr, value, mask = linux._EC_IO.unpack(data)
        calls.append((fd, request, addr, value, mask, mutate))
        if request == linux.MECHREVO_EC_IOC_READ:
            linux._EC_IO.pack_into(data, 0, addr, 0xA5, mask)
        return 0

    monkeypatch.setattr(linux.os, "open", fake_open)
    monkeypatch.setattr(linux.os, "close", fake_close)
    monkeypatch.setattr(linux.fcntl, "ioctl", fake_ioctl)

    backend = linux.KernelEcBackend()
    assert backend.ec_read(0x0741) == 0xA5
    backend.ec_write(0x0751, 0x50)
    backend.close()

    assert opened == [
        (
            linux.KernelEcBackend.DEVICE_PATH,
            os.O_RDWR | getattr(os, "O_CLOEXEC", 0),
        )
    ]
    assert calls == [
        (17, linux.MECHREVO_EC_IOC_READ, 0x0741, 0, 0, True),
        (17, linux.MECHREVO_EC_IOC_WRITE, 0x0751, 0x50, 0, True),
    ]
    assert closed == [17]


def test_kernel_backend_rmw_maps_clear_wins_semantics(monkeypatch):
    captured = {}

    monkeypatch.setattr(linux.os, "open", lambda path, flags: 23)
    monkeypatch.setattr(linux.os, "close", lambda fd: None)

    def fake_ioctl(fd, request, data, mutate):
        addr, value, mask = linux._EC_IO.unpack(data)
        captured.update(
            fd=fd, request=request, addr=addr, value=value, mask=mask, mutate=mutate
        )
        linux._EC_IO.pack_into(data, 0, addr, 0x23, mask)
        return 0

    monkeypatch.setattr(linux.fcntl, "ioctl", fake_ioctl)

    backend = linux.KernelEcBackend()
    result = backend.ec_rmw(
        0x0741,
        set_bits=0b1000_0011,
        clear_bits=0b1000_0100,
    )

    assert result == 0x23
    assert captured == {
        "fd": 23,
        "request": linux.MECHREVO_EC_IOC_UPDATE_BITS,
        "addr": 0x0741,
        "value": 0b0000_0011,
        "mask": 0b1000_0111,
        "mutate": True,
    }


def test_default_backend_is_kernel_and_does_not_fallback(monkeypatch):
    attempted = []
    monkeypatch.delenv("MFC_EC_BACKEND", raising=False)

    def fail_kernel(self):
        attempted.append("kernel")
        raise PermissionError("denied")

    def forbidden_legacy(self):
        attempted.append(type(self).__name__)
        raise AssertionError("legacy backend must not be attempted by default")

    monkeypatch.setattr(linux.KernelEcBackend, "open", fail_kernel)
    monkeypatch.setattr(linux.AcpiCallBackend, "open", forbidden_legacy)
    monkeypatch.setattr(linux.DevMemBackend, "open", forbidden_legacy)

    with pytest.raises(RuntimeError, match="Cannot open /dev/mechrevo-ec"):
        linux.select_backend()

    assert attempted == ["kernel"]


@pytest.mark.parametrize(
    ("name", "backend_type"),
    [
        ("kernel", linux.KernelEcBackend),
        ("acpi-call", linux.AcpiCallBackend),
        ("devmem", linux.DevMemBackend),
    ],
)
def test_explicit_backend_selection(monkeypatch, name, backend_type):
    monkeypatch.setenv("MFC_EC_BACKEND", name)
    monkeypatch.setattr(backend_type, "open", lambda self: None)

    backend = linux.select_backend()

    assert isinstance(backend, backend_type)


def test_unknown_backend_selection_is_rejected(monkeypatch):
    monkeypatch.setenv("MFC_EC_BACKEND", "mystery")

    with pytest.raises(ValueError, match="unknown MFC_EC_BACKEND"):
        linux.select_backend()


def test_kernel_backend_block_ioctls(monkeypatch):
    calls = []
    monkeypatch.setattr(linux.os, "open", lambda path, flags: 31)
    monkeypatch.setattr(linux.os, "close", lambda fd: None)

    def fake_ioctl(fd, request, data, mutate):
        addr, length = linux._EC_BLOCK_HEADER.unpack_from(data)
        start = linux._EC_BLOCK_HEADER.size
        calls.append((request, addr, length, bytes(data[start : start + length])))
        if request == linux.MECHREVO_EC_IOC_READ_BLOCK:
            data[start : start + length] = bytes(range(0xA0, 0xA0 + length))
        return 0

    monkeypatch.setattr(linux.fcntl, "ioctl", fake_ioctl)
    backend = linux.KernelEcBackend()

    assert backend.ec_read_block(0x0F00, 4) == b"\xA0\xA1\xA2\xA3"
    backend.ec_write_block(0x0F20, b"\x11\x22\x33")

    assert calls == [
        (linux.MECHREVO_EC_IOC_READ_BLOCK, 0x0F00, 4, b"\x00" * 4),
        (linux.MECHREVO_EC_IOC_WRITE_BLOCK, 0x0F20, 3, b"\x11\x22\x33"),
    ]


def test_kernel_backend_vector_transaction_pack_and_results(monkeypatch):
    captured = []
    monkeypatch.setattr(linux.os, "open", lambda path, flags: 37)
    monkeypatch.setattr(linux.os, "close", lambda fd: None)

    def fake_ioctl(fd, request, data, mutate):
        assert request == linux.MECHREVO_EC_IOC_XFER
        count, reserved = linux._EC_XFER_HEADER.unpack_from(data)
        assert (count, reserved) == (2, 0)
        for index in range(count):
            offset = linux._EC_XFER_HEADER.size + index * linux._EC_OP.size
            captured.append(linux._EC_OP.unpack_from(data, offset))
        linux._EC_OP.pack_into(data, linux._EC_XFER_HEADER.size, 0x0741, EC_OP_READ, 0xA5, 0, 0)
        linux._EC_OP.pack_into(
            data,
            linux._EC_XFER_HEADER.size + linux._EC_OP.size,
            0x0751,
            EC_OP_UPDATE_BITS,
            0x53,
            0x90,
            0,
        )
        return 0

    monkeypatch.setattr(linux.fcntl, "ioctl", fake_ioctl)
    backend = linux.KernelEcBackend()
    results = backend.ec_transaction(
        [
            EcOperation(EC_OP_READ, 0x0741),
            EcOperation(EC_OP_UPDATE_BITS, 0x0751, 0x10, 0x90),
        ]
    )

    assert captured == [
        (0x0741, EC_OP_READ, 0, 0, 0),
        (0x0751, EC_OP_UPDATE_BITS, 0x10, 0x90, 0),
    ]
    assert results == [0xA5, 0x53]
