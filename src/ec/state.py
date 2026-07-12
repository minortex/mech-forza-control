"""Persisted Mechrevo fan and Custom-mode state.

This module deliberately contains no EC I/O.  It defines the strict TOML
format used by the CLI restore command, so a malformed configuration is
rejected before any hardware write is attempted.
"""

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from . import mode
from .config import (
    ADDR_AP_CTL,
    ADDR_CPU_FAN_DNT_BASE,
    ADDR_CPU_FAN_DUTY_BASE,
    ADDR_CPU_FAN_UPT_BASE,
    ADDR_FANCTL_RESP,
    ADDR_GPU_FAN_DNT_BASE,
    ADDR_GPU_FAN_DUTY_BASE,
    ADDR_GPU_FAN_UPT_BASE,
    ADDR_MAFAN_CTL,
    ADDR_TCC,
    DEFAULT_CPU_FAN,
    DEFAULT_GPU_FAN,
    TDP_CTL,
)
from .io import ec_read, ec_write, ec_rmw

try:
    import tomllib
except ModuleNotFoundError:
    import tomli as tomllib


_SECTION_KEYS = frozenset(("mode", "cpu", "gpu"))
_MODE_KEYS = frozenset(("tdp", "tcc", "separate"))
_CURVE_KEYS = frozenset(("upT", "dnT", "duty"))


@dataclass(frozen=True)
class Curve:
    """One 16-point fan curve, expressed in user-facing units."""

    upT: tuple[int, ...]
    dnT: tuple[int, ...]
    duty: tuple[int, ...]


@dataclass(frozen=True)
class FanState:
    """The complete state restored by a future ``ec apply`` command."""

    tdp: int
    tcc: int
    separate: bool
    cpu: Curve
    gpu: Curve


def _require_exact_keys(section: Mapping[str, Any], expected: frozenset[str], name: str) -> None:
    actual = frozenset(section)
    missing = expected - actual
    extra = actual - expected
    if missing:
        raise ValueError(f"{name} missing keys: {', '.join(sorted(missing))}")
    if extra:
        raise ValueError(f"{name} has unsupported keys: {', '.join(sorted(extra))}")


def _require_table(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a TOML table")
    return value


def _as_int(value: Any, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    return value


def _as_curve(value: Any, name: str) -> Curve:
    table = _require_table(value, name)
    _require_exact_keys(table, _CURVE_KEYS, name)

    arrays: dict[str, tuple[int, ...]] = {}
    for field in ("upT", "dnT", "duty"):
        raw = table[field]
        field_name = f"{name}.{field}"
        if not isinstance(raw, list) or len(raw) != 16 or any(
            isinstance(item, bool) or not isinstance(item, int) for item in raw
        ):
            raise ValueError(f"{field_name} must contain exactly 16 integers")
        arrays[field] = tuple(raw)

    return Curve(upT=arrays["upT"], dnT=arrays["dnT"], duty=arrays["duty"])


def validate_state(state: FanState) -> None:
    """Validate a state created by a parser or programmatic caller."""
    if state.tdp not in (25, 45, 65):
        raise ValueError("tdp must be one of 25, 45, 65")
    if isinstance(state.tcc, bool) or not isinstance(state.tcc, int) or not 0 <= state.tcc <= 100:
        raise ValueError("tcc must be 0-100")
    if not isinstance(state.separate, bool):
        raise ValueError("separate must be a boolean")

    for curve_name, curve in (("cpu", state.cpu), ("gpu", state.gpu)):
        if not isinstance(curve, Curve):
            raise ValueError(f"{curve_name} must be a Curve")
        for field, maximum in (("upT", 255), ("dnT", 255), ("duty", 100)):
            values = getattr(curve, field)
            name = f"{curve_name}.{field}"
            if (
                not isinstance(values, tuple)
                or len(values) != 16
                or any(isinstance(item, bool) or not isinstance(item, int) for item in values)
            ):
                raise ValueError(f"{name} must contain exactly 16 integers")
            if any(not 0 <= item <= maximum for item in values):
                raise ValueError(f"{name} must contain values in 0-{maximum}")
        if curve.upT[-1] != 255:
            raise ValueError(f"{curve_name}.upT final value must be 255")


def load_state(path: Path) -> FanState:
    """Load and strictly validate one persisted state TOML file."""
    with path.open("rb") as file:
        document = tomllib.load(file)

    _require_exact_keys(document, _SECTION_KEYS, "state")
    mode = _require_table(document["mode"], "mode")
    _require_exact_keys(mode, _MODE_KEYS, "mode")

    tdp = _as_int(mode["tdp"], "tdp")
    tcc = _as_int(mode["tcc"], "tcc")
    separate = mode["separate"]
    if not isinstance(separate, bool):
        raise ValueError("separate must be a boolean")

    state = FanState(
        tdp=tdp,
        tcc=tcc,
        separate=separate,
        cpu=_as_curve(document["cpu"], "cpu"),
        gpu=_as_curve(document["gpu"], "gpu"),
    )
    validate_state(state)
    return state


# ── EC I/O helpers ───────────────────────────────────────────────────

_CTL_TO_TDP = {v: k for k, v in TDP_CTL.items()}


def _read_curve(base_upt, base_dnt, base_duty):
    upT = []
    dnT = []
    duty = []
    for i in range(16):
        upT.append(ec_read(base_upt + i))
        dnT.append(ec_read(base_dnt + i))
        duty.append(ec_read(base_duty + i) // 2)
    return Curve(upT=tuple(upT), dnT=tuple(dnT), duty=tuple(duty))


def snapshot_state() -> FanState:
    """Read current EC fan-table state and return a FanState."""
    cpu = _read_curve(ADDR_CPU_FAN_UPT_BASE, ADDR_CPU_FAN_DNT_BASE,
                      ADDR_CPU_FAN_DUTY_BASE)
    gpu = _read_curve(ADDR_GPU_FAN_UPT_BASE, ADDR_GPU_FAN_DNT_BASE,
                      ADDR_GPU_FAN_DUTY_BASE)

    resp = ec_read(ADDR_FANCTL_RESP)
    separate = bool(resp & 0x80)

    ctl = ec_read(ADDR_MAFAN_CTL)
    tdp = _CTL_TO_TDP.get(ctl, 45)

    tcc_raw = ec_read(ADDR_TCC)
    if tcc_raw == 0:
        tcc = 0
    elif tcc_raw & 0x80:
        tcc = tcc_raw & 0x7F
    else:
        tcc = tcc_raw

    return FanState(tdp=tdp, tcc=tcc, separate=separate, cpu=cpu, gpu=gpu)


def _write_table(cpu: Curve, gpu: Curve) -> None:
    """Write all six 16-entry fan-table blocks to EC."""
    for i in range(16):
        ec_write(ADDR_CPU_FAN_UPT_BASE + i, cpu.upT[i + 1] if i < 15 else 255)
        if i < 15:
            ec_write(ADDR_CPU_FAN_DNT_BASE + i + 1, cpu.dnT[i])
        ec_write(ADDR_CPU_FAN_DUTY_BASE + i, min(cpu.duty[i], 100) * 2)

        ec_write(ADDR_GPU_FAN_UPT_BASE + i, gpu.upT[i + 1] if i < 15 else 255)
        if i < 15:
            ec_write(ADDR_GPU_FAN_DNT_BASE + i + 1, gpu.dnT[i])
        ec_write(ADDR_GPU_FAN_DUTY_BASE + i, min(gpu.duty[i], 100) * 2)


def apply_state(state: FanState) -> None:
    """Apply a saved FanState to the EC in the documented order.

    Order:
      1. EC[1990] clear bit2 (fan-table gate)
      2. write all six table blocks
      3. EC[1990] set bit2
      4. EC[1989] bit7 = separate
      5. Custom mode gear (apply_custom_gear)
      6. TCC
    """
    validate_state(state)

    # 1. Clear fan-table gate
    ec_rmw(ADDR_AP_CTL, clear_bits=0x04)

    # 2. Write fan tables
    _write_table(state.cpu, state.gpu)

    # 3. Restore fan-table gate
    ec_rmw(ADDR_AP_CTL, set_bits=0x04)

    # 4. Separate-fan control
    ec_write(ADDR_FANCTL_RESP, 0x80 if state.separate else 0x00)

    # 5. Custom mode gear (no fan-table write, no AP_CTL touch)
    mode.apply_custom_gear(state.tdp)

    # 6. TCC last
    ec_write(ADDR_TCC, mode._encode_tcc(state.tcc))


# ── CLI ──────────────────────────────────────────────────────────────

DEFAULT_CONFIG = Path("/etc/mechrevo/state.toml")


def cmd_save(args):
    path = Path(args.config)
    state = snapshot_state()
    text = dump_state(state)
    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    path.write_text(text)
    path.chmod(0o600)
    print(f"  Saved to {path}")
    print(f"  TDP: {state.tdp}W, TCC: {state.tcc}, separate: {state.separate}")


def cmd_apply(args):
    path = Path(args.config)
    state = load_state(path)
    apply_state(state)
    # Readback verification
    ctl = ec_read(ADDR_MAFAN_CTL)
    tcc_raw = ec_read(ADDR_TCC)
    resp = ec_read(ADDR_FANCTL_RESP)
    tcc_display = "disabled" if tcc_raw == 0 else f"{tcc_raw & 0x7f}"
    print(f"  Applied from {path}")
    print(f"  TDP: {state.tdp}W, TCC: {tcc_display}, separate: {bool(resp & 0x80)}")


def register(subparsers):
    s = subparsers.add_parser("state", help="Save/restore fan and Custom-mode state")
    sub = s.add_subparsers(dest="state_op", required=True)
    save = sub.add_parser("save", help="Snapshot current EC state to file")
    save.add_argument("--config", default=str(DEFAULT_CONFIG))
    save.set_defaults(func=cmd_save)


def register_apply(subparsers):
    ap = subparsers.add_parser("apply", help="Apply saved state from file")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.set_defaults(func=cmd_apply)


def _format_values(values: tuple[int, ...]) -> str:
    return ", ".join(str(value) for value in values)


def dump_state(state: FanState) -> str:
    """Serialize a validated state into the canonical TOML representation."""
    validate_state(state)
    return (
        "[mode]\n"
        f"tdp = {state.tdp}\n"
        f"tcc = {state.tcc}\n"
        f"separate = {'true' if state.separate else 'false'}\n"
        "\n"
        "[cpu]\n"
        f"upT = [{_format_values(state.cpu.upT)}]\n"
        f"dnT = [{_format_values(state.cpu.dnT)}]\n"
        f"duty = [{_format_values(state.cpu.duty)}]\n"
        "\n"
        "[gpu]\n"
        f"upT = [{_format_values(state.gpu.upT)}]\n"
        f"dnT = [{_format_values(state.gpu.dnT)}]\n"
        f"duty = [{_format_values(state.gpu.duty)}]\n"
    )
