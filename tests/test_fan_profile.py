from pathlib import Path

import pytest

from src import fan_profile


PROFILE_TEXT = """
[main]
levels = [
  { down = 35, duty = 10 },
  { up = 40, down = 40, duty = 10 },
  { up = 45, down = 45, duty = 20 },
  { up = 50, down = 50, duty = 20 },
  { up = 55, down = 55, duty = 30 },
  { up = 60, down = 60, duty = 30 },
  { up = 65, down = 65, duty = 40 },
  { up = 70, down = 70, duty = 40 },
  { up = 75, down = 75, duty = 50 },
  { up = 80, down = 80, duty = 50 },
  { up = 85, down = 85, duty = 60 },
  { up = 90, down = 90, duty = 60 },
  { up = 95, down = 95, duty = 70 },
  { up = 100, down = 100, duty = 80 },
  { up = 105, down = 105, duty = 90 },
  { up = 110, duty = 100 },
]

[second]
levels = [
  { down = 35, duty = 5 },
  { up = 40, down = 40, duty = 10 },
  { up = 45, down = 45, duty = 15 },
  { up = 50, down = 50, duty = 20 },
  { up = 55, down = 55, duty = 25 },
  { up = 60, down = 60, duty = 30 },
  { up = 65, down = 65, duty = 35 },
  { up = 70, down = 70, duty = 40 },
  { up = 75, down = 75, duty = 45 },
  { up = 80, down = 80, duty = 50 },
  { up = 85, down = 85, duty = 55 },
  { up = 90, down = 90, duty = 60 },
  { up = 95, down = 95, duty = 65 },
  { up = 100, down = 100, duty = 70 },
  { up = 105, down = 105, duty = 80 },
  { up = 110, duty = 100 },
]
"""


def write_profile(path: Path, text: str = PROFILE_TEXT) -> Path:
    path.write_text(text)
    return path


def ec_slot_profile_text() -> str:
    sections = []
    for name in ("main", "second"):
        levels = []
        for index in range(16):
            fields = []
            if index > 0:
                fields.append(f"down = {30 + index * 5}")
            if index < 15:
                fields.append(f"up = {40 + index * 5}")
            fields.append(f"duty = {10 + index * 5}")
            levels.append("  { " + ", ".join(fields) + " },")
        sections.append(f"[{name}]\nlevels = [\n" + "\n".join(levels) + "\n]")
    return "\n\n".join(sections)


def test_windows_system_profile_uses_programdata(tmp_path, monkeypatch):
    monkeypatch.setattr(fan_profile.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

    assert fan_profile.system_profile_path() == (
        tmp_path / "mech-forza-control" / "fan-table.toml"
    )


def test_explicit_profile_has_highest_priority(tmp_path, monkeypatch):
    explicit = write_profile(tmp_path / "explicit.toml")
    environment = write_profile(tmp_path / "environment.toml")
    monkeypatch.setenv(fan_profile.PROFILE_ENV, str(environment))

    profile = fan_profile.load_fan_profile(explicit)

    assert profile.source == str(explicit)
    assert profile.main.duty[0] == 10
    assert profile.second.duty[-1] == 100


def test_environment_profile_is_used(tmp_path, monkeypatch):
    path = write_profile(tmp_path / "environment.toml")
    monkeypatch.setenv(fan_profile.PROFILE_ENV, str(path))

    assert fan_profile.load_fan_profile().source == str(path)


def test_system_profile_precedes_bundled_profile(tmp_path, monkeypatch):
    path = write_profile(tmp_path / "system.toml")
    monkeypatch.delenv(fan_profile.PROFILE_ENV, raising=False)
    monkeypatch.setattr(fan_profile, "system_profile_path", lambda: path)

    assert fan_profile.load_fan_profile().source == str(path)


def test_bundled_profile_is_final_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv(fan_profile.PROFILE_ENV, raising=False)
    monkeypatch.setattr(
        fan_profile, "system_profile_path", lambda: tmp_path / "missing.toml"
    )

    profile = fan_profile.load_fan_profile()

    assert profile.source == "package:fan-table.toml"
    assert len(profile.main.up) == 16
    assert profile.main.up[0] == 0
    assert profile.main.down[-1] == 255
    assert profile.main.duty[0] == 20
    assert profile.second.duty[0] == 10


def test_previous_ec_slot_layout_is_converted_to_gcu_points(tmp_path):
    path = write_profile(tmp_path / "ec-slots.toml", ec_slot_profile_text())

    profile = fan_profile.load_fan_profile(path)

    assert profile.main.up[:3] == (0, 40, 45)
    assert profile.main.down[:3] == (35, 40, 45)
    assert profile.main.up[-1] == 110
    assert profile.main.down[-1] == 255


def test_profile_requires_exactly_16_values(tmp_path):
    path = write_profile(
        tmp_path / "short.toml",
        PROFILE_TEXT.replace("  { up = 110, duty = 100 },\n", "", 1),
    )

    with pytest.raises(ValueError, match=r"\[main\]\.levels.*exactly 16"):
        fan_profile.load_fan_profile(path)


def test_profile_rejects_duty_above_100(tmp_path):
    path = write_profile(
        tmp_path / "invalid-duty.toml",
        PROFILE_TEXT.replace("duty = 100 },", "duty = 101 },", 1),
    )

    with pytest.raises(ValueError, match=r"\[main\]\.levels\[15\]\.duty.*0-100"):
        fan_profile.load_fan_profile(path)


def test_profile_rejects_missing_hysteresis_between_levels(tmp_path):
    path = write_profile(
        tmp_path / "invalid-hysteresis.toml",
        PROFILE_TEXT.replace("up = 40, down = 40", "up = 35, down = 40", 1),
    )

    with pytest.raises(ValueError, match=r"levels\[0\]\.down.*provide hysteresis"):
        fan_profile.load_fan_profile(path)


def test_profile_rejects_decreasing_duty(tmp_path):
    path = write_profile(
        tmp_path / "invalid-duty-order.toml",
        PROFILE_TEXT.replace(
            "up = 45, down = 45, duty = 20",
            "up = 45, down = 45, duty = 9",
            1,
        ),
    )

    with pytest.raises(ValueError, match=r"levels\[2\]\.duty.*previous duty"):
        fan_profile.load_fan_profile(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (
            "  { up = 45, down = 45, duty = 20 },\n"
            "  { up = 50, down = 50, duty = 20 },",
            "  { up = 40, down = 45, duty = 20 },\n"
            "  { up = 50, down = 50, duty = 20 },",
            r"levels\[2\]\.up.*previous up",
        ),
        (
            "up = 45, down = 45, duty = 20",
            "up = 45, down = 40, duty = 20",
            r"levels\[2\]\.down.*previous down",
        ),
    ),
)
def test_profile_rejects_non_increasing_thresholds(tmp_path, old, new, message):
    path = write_profile(
        tmp_path / "invalid-threshold-order.toml",
        PROFILE_TEXT.replace(old, new, 1),
    )

    with pytest.raises(ValueError, match=message):
        fan_profile.load_fan_profile(path)


def test_profile_rejects_legacy_parallel_arrays(tmp_path):
    path = write_profile(
        tmp_path / "legacy.toml",
        """
[main]
up = [1]
down = [0]
duty = [20]

[second]
up = [1]
down = [0]
duty = [20]
""",
    )

    with pytest.raises(ValueError, match=r"\[main\] must contain only levels"):
        fan_profile.load_fan_profile(path)


def test_missing_explicit_profile_does_not_silently_fallback(tmp_path):
    path = tmp_path / "missing.toml"

    with pytest.raises(ValueError, match=f"fan profile not found: {path}"):
        fan_profile.load_fan_profile(path)
