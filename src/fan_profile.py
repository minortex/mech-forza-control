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


def _level_value(
    level: dict[str, Any], location: str, field: str, minimum: int, maximum: int
) -> int:
    value = level.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"invalid fan profile {location}.{field} must be an integer")
    if not minimum <= value <= maximum:
        raise ValueError(
            f"invalid fan profile {location}.{field} must be "
            f"{minimum}-{maximum}, got {value}"
        )
    return value


def _require_strictly_increasing(
    values: tuple[int, ...], locations: tuple[str, ...], field: str
) -> None:
    for index in range(1, len(values)):
        if values[index] <= values[index - 1]:
            raise ValueError(
                f"invalid fan profile {locations[index]}.{field} must be greater "
                f"than the previous {field} ({values[index - 1]}), "
                f"got {values[index]}"
            )


def _convert_ec_levels(levels: list[Any], location: str) -> list[dict[str, Any]]:
    """Convert the previous EC-slot profile layout to GCU curve points."""
    for index, level in enumerate(levels):
        item_location = f"{location}[{index}]"
        if not isinstance(level, dict):
            raise ValueError(f"invalid fan profile {item_location} must be a table")
        expected = {"duty"}
        if index < 15:
            expected.add("up")
        if index > 0:
            expected.add("down")
        if set(level) != expected:
            fields = ", ".join(sorted(expected))
            raise ValueError(
                f"invalid fan profile {item_location} must contain exactly: {fields}"
            )

    converted = []
    for index, level in enumerate(levels):
        point = {"duty": level["duty"]}
        if index > 0:
            point["up"] = levels[index - 1]["up"]
        if index < 15:
            point["down"] = levels[index + 1]["down"]
        converted.append(point)
    return converted


def _validate_curve(data: dict[str, Any], name: str, source: str) -> FanCurve:
    section = data.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"invalid fan profile {source}: missing [{name}] table")
    if set(section) != {"levels"}:
        raise ValueError(
            f"invalid fan profile {source}: [{name}] must contain only levels"
        )
    levels = section["levels"]
    location = f"{source}: [{name}].levels"
    if not isinstance(levels, list):
        raise ValueError(f"invalid fan profile {location} must be an array")
    if len(levels) != 16:
        raise ValueError(
            f"invalid fan profile {location} must contain exactly 16 levels, "
            f"got {len(levels)}"
        )
    if (
        isinstance(levels[0], dict)
        and set(levels[0]) == {"up", "duty"}
        and isinstance(levels[-1], dict)
        and set(levels[-1]) == {"down", "duty"}
    ):
        levels = _convert_ec_levels(levels, location)

    up: list[int] = []
    down: list[int] = []
    duty: list[int] = []
    up_locations: list[str] = []
    down_locations: list[str] = []
    for index, level in enumerate(levels):
        item_location = f"{location}[{index}]"
        if not isinstance(level, dict):
            raise ValueError(f"invalid fan profile {item_location} must be a table")
        expected = {"duty"}
        if index > 0:
            expected.add("up")
        if index < 15:
            expected.add("down")
        if set(level) != expected:
            fields = ", ".join(sorted(expected))
            raise ValueError(
                f"invalid fan profile {item_location} must contain exactly: {fields}"
            )

        duty.append(_level_value(level, item_location, "duty", 0, 100))
        if index > 0:
            up.append(_level_value(level, item_location, "up", 0, 254))
            up_locations.append(item_location)
        if index < 15:
            down.append(_level_value(level, item_location, "down", 0, 254))
            down_locations.append(item_location)
    up_values = tuple(up)
    down_values = tuple(down)
    duty_values = tuple(duty)
    _require_strictly_increasing(up_values, tuple(up_locations), "up")
    _require_strictly_increasing(down_values, tuple(down_locations), "down")
    for index in range(15):
        if down_values[index] >= up_values[index]:
            raise ValueError(
                f"invalid fan profile {down_locations[index]}.down must be less "
                f"than {up_locations[index]}.up to provide hysteresis"
            )
    for index in range(1, 16):
        if duty_values[index] < duty_values[index - 1]:
            raise ValueError(
                f"invalid fan profile {location}[{index}].duty must not be less "
                f"than the previous duty ({duty_values[index - 1]}), "
                f"got {duty_values[index]}"
            )
    return FanCurve(
        up=(0,) + up_values,
        down=down_values + (255,),
        duty=duty_values,
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
