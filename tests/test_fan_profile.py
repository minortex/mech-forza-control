from pathlib import Path

import pytest

from src import fan_profile


PROFILE_TEXT = """
[main]
up = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 255]
down = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
duty = [10, 10, 20, 20, 30, 30, 40, 40, 50, 50, 60, 60, 70, 80, 90, 100]

[second]
up = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 255]
down = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15]
duty = [5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 80, 100]
"""


def write_profile(path: Path, text: str = PROFILE_TEXT) -> Path:
    path.write_text(text)
    return path


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
    assert profile.main.duty[0] == 20
    assert profile.second.duty[0] == 10


def test_profile_requires_exactly_16_values(tmp_path):
    path = write_profile(
        tmp_path / "short.toml",
        PROFILE_TEXT.replace(
            "up = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 255]",
            "up = [0, 1]",
            1,
        ),
    )

    with pytest.raises(ValueError, match=r"\[main\]\.up.*exactly 16"):
        fan_profile.load_fan_profile(path)


def test_profile_rejects_duty_above_100(tmp_path):
    path = write_profile(
        tmp_path / "invalid-duty.toml",
        PROFILE_TEXT.replace("90, 100]", "90, 101]", 1),
    )

    with pytest.raises(ValueError, match=r"\[main\]\.duty\[15\].*0-100"):
        fan_profile.load_fan_profile(path)


def test_missing_explicit_profile_does_not_silently_fallback(tmp_path):
    path = tmp_path / "missing.toml"

    with pytest.raises(ValueError, match=f"fan profile not found: {path}"):
        fan_profile.load_fan_profile(path)
