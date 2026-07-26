"""Cross-platform loading and validation for RamFan1p5 profiles."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
import os
from pathlib import Path
import sys
import tomllib
from typing import Any, BinaryIO

PROFILE_ENV = "MFC_FAN_TABLE"
PROFILE_FILENAME = "fan-table.toml"
PROFILE_DIRNAME = "mech-forza-control"


@dataclass(frozen=True)
class FanCurve:
    up: tuple[int, ...]
    down: tuple[int, ...]
    duty: tuple[int, ...]


@dataclass(frozen=True)
class FanProfile:
    main: FanCurve
    second: FanCurve
    source: str


def system_profile_path() -> Path:
    """Return the machine-wide profile path for the current platform."""
    if sys.platform == "win32":
        root = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData"))
    else:
        root = Path("/etc")
    return root / PROFILE_DIRNAME / PROFILE_FILENAME


def _read_toml(stream: BinaryIO, source: str) -> dict[str, Any]:
    try:
        data = tomllib.load(stream)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"invalid fan profile {source}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"invalid fan profile {source}: root must be a TOML table")
    return data


def _validate_values(
    section: dict[str, Any],
    section_name: str,
    field: str,
    source: str,
    minimum: int,
    maximum: int,
) -> tuple[int, ...]:
    values = section.get(field)
    location = f"{source}: [{section_name}].{field}"
    if not isinstance(values, list):
        raise ValueError(f"invalid fan profile {location} must be an array")
    if len(values) != 16:
        raise ValueError(
            f"invalid fan profile {location} must contain exactly 16 values, "
            f"got {len(values)}"
        )
    for index, value in enumerate(values):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(
                f"invalid fan profile {location}[{index}] must be an integer"
            )
        if not minimum <= value <= maximum:
            raise ValueError(
                f"invalid fan profile {location}[{index}] must be "
                f"{minimum}-{maximum}, got {value}"
            )
    return tuple(values)


def _validate_curve(data: dict[str, Any], name: str, source: str) -> FanCurve:
    section = data.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"invalid fan profile {source}: missing [{name}] table")
    return FanCurve(
        up=_validate_values(section, name, "up", source, 0, 255),
        down=_validate_values(section, name, "down", source, 0, 255),
        duty=_validate_values(section, name, "duty", source, 0, 100),
    )


def _profile_from_data(data: dict[str, Any], source: str) -> FanProfile:
    return FanProfile(
        main=_validate_curve(data, "main", source),
        second=_validate_curve(data, "second", source),
        source=source,
    )


def _load_external(path: Path) -> FanProfile:
    path = path.expanduser()
    try:
        with path.open("rb") as stream:
            data = _read_toml(stream, str(path))
    except FileNotFoundError as exc:
        raise ValueError(f"fan profile not found: {path}") from exc
    except OSError as exc:
        raise ValueError(f"cannot read fan profile {path}: {exc}") from exc
    return _profile_from_data(data, str(path))


def _load_bundled() -> FanProfile:
    resource = resources.files("src").joinpath("data", PROFILE_FILENAME)
    source = f"package:{PROFILE_FILENAME}"
    try:
        with resource.open("rb") as stream:
            data = _read_toml(stream, source)
    except (FileNotFoundError, OSError) as exc:
        raise ValueError(f"bundled fan profile is unavailable: {exc}") from exc
    return _profile_from_data(data, source)


def load_fan_profile(path: str | os.PathLike[str] | None = None) -> FanProfile:
    """Load a profile using explicit, environment, system, then bundled order."""
    if path is not None:
        return _load_external(Path(path))

    env_path = os.environ.get(PROFILE_ENV)
    if env_path:
        return _load_external(Path(env_path))

    system_path = system_profile_path()
    if system_path.is_file():
        return _load_external(system_path)

    return _load_bundled()
