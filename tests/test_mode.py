from argparse import Namespace

from src import mode
from src.io import EC_OP_READ, EC_OP_UPDATE_BITS, EcOperation
from src.registers import ADDR_MAFAN_CTL, FAN_BOOST_BIT
from tests.support import NativeBatchBackend


def test_mode_switch_updates_only_base_bits_in_one_transaction(make_backend):
    backend = make_backend({ADDR_MAFAN_CTL: FAN_BOOST_BIT}, NativeBatchBackend)

    mode.cmd_switch(Namespace(mode_name="turbo"))

    assert backend.values[ADDR_MAFAN_CTL] == FAN_BOOST_BIT | 0x10
    assert backend.transactions == [
        [
            EcOperation(EC_OP_UPDATE_BITS, ADDR_MAFAN_CTL, 0x10, 0x90),
            EcOperation(EC_OP_READ, ADDR_MAFAN_CTL),
        ]
    ]


def test_mode_status_labels_base_bits(make_backend, capsys):
    make_backend({ADDR_MAFAN_CTL: 0x00})

    mode.cmd_status(Namespace())

    assert "Gaming" in capsys.readouterr().out
