"""Shared test fixtures."""

import pytest

from ec import io


class FakeBackend:
    """In-memory EC backend for unit tests."""

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
