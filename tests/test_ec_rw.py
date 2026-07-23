import importlib.util
from argparse import Namespace
from pathlib import Path


SPEC = importlib.util.spec_from_file_location(
    "ec_rw", Path(__file__).parents[1] / "tools" / "ec_rw.py"
)
assert SPEC is not None and SPEC.loader is not None
ec_rw = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ec_rw)


def test_read_two_addresses_combines_high_and_low_bytes(monkeypatch, capsys):
    values = {100: 0x12, 200: 0x34}
    monkeypatch.setattr(ec_rw, "ec_read", values.__getitem__)

    ec_rw.cmd_read(Namespace(addr=100, low_addr=200))

    assert capsys.readouterr().out == "XRAM[0x0064 (100):0x00C8 (200)] = 0x1234 (4660)\n"


def test_read_one_address_keeps_byte_output(monkeypatch, capsys):
    monkeypatch.setattr(ec_rw, "ec_read", lambda _addr: 0xAB)

    ec_rw.cmd_read(Namespace(addr=100, low_addr=None))

    assert capsys.readouterr().out == "XRAM[0x0064 (100)] = 0xAB (171)\n"
