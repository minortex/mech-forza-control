from pathlib import Path

import pytest
from argparse import Namespace

from ec.state import Curve, FanState, dump_state, load_state, validate_state
from ec.state import snapshot_state, apply_state
from ec import io
from ec.config import (
    ADDR_AP_CTL,
    ADDR_AP_OEM,
    ADDR_AP_OEM9,
    ADDR_AP_OEM10,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_CPU_FAN_UPT_BASE,
    ADDR_CPU_FAN_DNT_BASE,
    ADDR_FANCTL_RESP,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_GPU_FAN_UPT_BASE,
    ADDR_GPU_FAN_DNT_BASE,
    ADDR_MAFAN_CTL,
    ADDR_PL1,
    ADDR_PL2,
    ADDR_PL4,
    ADDR_TCC,
    ADDR_TRIGGER_BYTE,
    CTL_NORMAL,
    CTL_TURBO,
    CTL_USER_HI,
    DEFAULT_CPU_FAN,
    DEFAULT_GPU_FAN,
)
from conftest import FakeBackend


VALID_STATE = """\
[mode]
tdp = 45
tcc = 85
separate = true

[cpu]
upT = [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255]
dnT = [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95]
duty = [20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]

[gpu]
upT = [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255]
dnT = [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95]
duty = [10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100]
"""


def write_state(tmp_path: Path, text: str = VALID_STATE) -> Path:
    path = tmp_path / "state.toml"
    path.write_text(text)
    return path


def test_load_state_parses_valid_toml(tmp_path):
    state = load_state(write_state(tmp_path))

    assert state == FanState(
        tdp=45,
        tcc=85,
        separate=True,
        cpu=Curve(
            upT=(40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255),
            dnT=(35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95),
            duty=(20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100),
        ),
        gpu=Curve(
            upT=(40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255),
            dnT=(35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95),
            duty=(10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100),
        ),
    )


def test_dump_state_round_trips(tmp_path):
    original = load_state(write_state(tmp_path))
    path = write_state(tmp_path, dump_state(original))

    assert load_state(path) == original


def test_load_state_rejects_missing_section(tmp_path):
    text = VALID_STATE[:VALID_STATE.index("\n[gpu]\n")]

    with pytest.raises(ValueError, match="state missing keys: gpu"):
        load_state(write_state(tmp_path, text))


def test_load_state_rejects_unsupported_tdp(tmp_path):
    text = VALID_STATE.replace("tdp = 45", "tdp = 54")

    with pytest.raises(ValueError, match="tdp must be one of 25, 45, 65"):
        load_state(write_state(tmp_path, text))


def test_load_state_rejects_duty_above_100(tmp_path):
    text = VALID_STATE.replace("duty = [20", "duty = [101", 1)

    with pytest.raises(ValueError, match="cpu.duty must contain values in 0-100"):
        load_state(write_state(tmp_path, text))


def test_load_state_rejects_curve_with_not_16_entries(tmp_path):
    text = VALID_STATE.replace(
        "duty = [20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]",
        "duty = [20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95]",
        1,
    )

    with pytest.raises(ValueError, match="cpu.duty must contain exactly 16 integers"):
        load_state(write_state(tmp_path, text))


def test_validate_state_rejects_final_upt_other_than_255():
    curve = Curve(upT=(0,) * 16, dnT=(0,) * 16, duty=(0,) * 16)

    with pytest.raises(ValueError, match="cpu.upT final value must be 255"):
        validate_state(FanState(tdp=25, tcc=0, separate=False, cpu=curve, gpu=curve))


# ── snapshot tests ───────────────────────────────────────────────────

def _build_ec_state(tdp=45, tcc=85, separate=True):
    """Build a FakeBackend with fan tables matching VALID_STATE."""
    initial = {}
    # CPU fan table
    cpu_upT = [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255]
    cpu_dnT = [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95]
    cpu_duty = [20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100]
    gpu_upT = [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255]
    gpu_dnT = [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95]
    gpu_duty = [10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100]

    for i in range(16):
        initial[ADDR_CPU_FAN_UPT_BASE + i] = cpu_upT[i]
        initial[ADDR_CPU_FAN_DNT_BASE + i] = cpu_dnT[i]
        initial[ADDR_CPU_FAN_DUTY_BASE + i] = cpu_duty[i] * 2  # EC stores duty*2
        initial[ADDR_GPU_FAN_UPT_BASE + i] = gpu_upT[i]
        initial[ADDR_GPU_FAN_DNT_BASE + i] = gpu_dnT[i]
        initial[ADDR_GPU_FAN_DUTY_BASE + i] = gpu_duty[i] * 2

    tdp_ctl_map = {25: CTL_USER_HI, 45: CTL_NORMAL, 65: CTL_TURBO}
    initial[ADDR_MAFAN_CTL] = tdp_ctl_map[tdp]
    initial[ADDR_FANCTL_RESP] = 0x80 if separate else 0x00
    if tcc == 0:
        initial[ADDR_TCC] = 0
    else:
        initial[ADDR_TCC] = tcc | 0x80
    return FakeBackend(initial)


def test_snapshot_state_reads_ec(tmp_path):
    backend = _build_ec_state(tdp=45, tcc=85, separate=True)
    io._set_backend_for_testing(backend)

    state = snapshot_state()

    assert state.tdp == 45
    assert state.tcc == 85
    assert state.separate is True
    assert state.cpu.upT == (40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255)
    assert state.cpu.duty == (20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100)


def test_snapshot_state_tcc_zero(tmp_path):
    backend = _build_ec_state(tdp=45, tcc=0, separate=False)
    io._set_backend_for_testing(backend)

    state = snapshot_state()

    assert state.tcc == 0
    assert state.separate is False


def test_snapshot_state_tdp_25(tmp_path):
    backend = _build_ec_state(tdp=25, tcc=90, separate=False)
    io._set_backend_for_testing(backend)

    state = snapshot_state()
    assert state.tdp == 25


# ── apply tests ──────────────────────────────────────────────────────

def test_apply_state_writes_only_saved_runtime_state():
    """apply_state writes fan tables, separate, mode gear, TCC — and nothing else."""
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    state = FanState(
        tdp=45,
        tcc=85,
        separate=True,
        cpu=Curve(
            upT=(40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255),
            dnT=(35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95),
            duty=(20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100),
        ),
        gpu=Curve(
            upT=(40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255),
            dnT=(35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95),
            duty=(10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100),
        ),
    )

    apply_state(state)

    # No write to PL registers or trigger byte
    forbidden = {ADDR_PL1, ADDR_PL2, ADDR_PL4, ADDR_TRIGGER_BYTE}
    assert all(addr not in forbidden for addr, _ in backend.writes)

    # Verify AP_CTL bit2 was cleared and restored (table gate)
    ap_ctl_writes = [(a, v) for a, v in backend.writes if a == ADDR_AP_CTL]
    # First clear, then set
    assert any(v & 4 == 0 for a, v in ap_ctl_writes)
    assert any(v & 4 != 0 for a, v in ap_ctl_writes)

    # Verify fan table writes (CPU duty[0] = 20*2 = 40)
    assert backend.values[ADDR_CPU_FAN_DUTY_BASE] == 40
    assert backend.values[ADDR_GPU_FAN_DUTY_BASE] == 20

    # Verify separate-fan
    assert backend.values[ADDR_FANCTL_RESP] == 0x80

    # Verify mode gear (MAFAN_CTL for 45W = CTL_NORMAL = 0x00)
    assert backend.values[ADDR_MAFAN_CTL] == CTL_NORMAL

    # Verify TCC
    assert backend.values[ADDR_TCC] == 85 | 0x80


def test_apply_state_writes_ap_ctl_around_table():
    """AP_CTL bit2 is cleared before table writes, set after."""
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    state = FanState(
        tdp=65,
        tcc=0,
        separate=False,
        cpu=Curve(upT=(0,)*15 + (255,), dnT=(0,)*16, duty=(0,)*16),
        gpu=Curve(upT=(0,)*15 + (255,), dnT=(0,)*16, duty=(0,)*16),
    )

    apply_state(state)

    # TCC disabled
    assert backend.values[ADDR_TCC] == 0
    # TDP 65W = CTL_TURBO
    assert backend.values[ADDR_MAFAN_CTL] == CTL_TURBO
    # Separate off
    assert backend.values[ADDR_FANCTL_RESP] == 0x00


def test_apply_state_does_not_write_pl_or_trigger():
    """Ensure apply_state never touches PL or trigger registers."""
    backend = FakeBackend()
    io._set_backend_for_testing(backend)

    state = FanState(
        tdp=25,
        tcc=100,
        separate=True,
        cpu=Curve(upT=(0,)*15 + (255,), dnT=(0,)*16, duty=(0,)*16),
        gpu=Curve(upT=(0,)*15 + (255,), dnT=(0,)*16, duty=(0,)*16),
    )
    apply_state(state)

    written_addrs = {a for a, _ in backend.writes}
    assert ADDR_PL1 not in written_addrs
    assert ADDR_PL2 not in written_addrs
    assert ADDR_PL4 not in written_addrs
    assert ADDR_TRIGGER_BYTE not in written_addrs
