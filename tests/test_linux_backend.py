import os

import pytest

from src.backends import linux


def test_ioctl_numbers_match_kernel_uapi():
    assert linux._EC_IO.size == 4
    assert linux.MECHREVO_EC_IOC_READ == 0xC0044D00
    assert linux.MECHREVO_EC_IOC_WRITE == 0x40044D01
    assert linux.MECHREVO_EC_IOC_UPDATE_BITS == 0xC0044D02


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
