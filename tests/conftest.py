"""Test fixtures shared by the suite."""

import pytest

from src import io
from tests.support import FakeBackend


@pytest.fixture(autouse=True)
def reset_backend():
    io.close()
    yield
    io.close()


@pytest.fixture
def make_backend():
    """Install a fresh backend and return it."""

    def factory(initial=None, cls=FakeBackend):
        backend = cls(initial) if initial is not None else cls()
        io._set_backend_for_testing(backend)
        return backend

    return factory
