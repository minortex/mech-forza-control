from pathlib import Path

import pytest

from src import fan_profile


def profile_text(base=30):
    rows = []
    for index in range(16):
        fields = []
        if index:
            fields.append(f"up = {base + index * 10}")
        if index < 15:
            fields.append(f"down = {base + index * 10}")
        fields.append(f"duty = {20 + index * 5}")
        rows.append("  { " + ", ".join(fields) + " },")
    levels = "\n".join(rows)
    return f"[main]\nlevels = [\n{levels}\n]\n\n[second]\nlevels = [\n{levels}\n]\n"


def legacy_profile_text():
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


def write_profile(path: Path, text: str | None = None) -> Path:
    path.write_text(profile_text() if text is None else text)
    return path


def test_windows_system_profile_uses_programdata(tmp_path, monkeypatch):
    monkeypatch.setattr(fan_profile.sys, "platform", "win32")
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

    assert fan_profile.system_profile_path() == (
        tmp_path / "mech-forza-control" / "fan-table.toml"
    )


def test_profile_source_precedence(tmp_path, monkeypatch):
    explicit = write_profile(tmp_path / "explicit.toml")
    environment = write_profile(tmp_path / "environment.toml")
    system = write_profile(tmp_path / "system.toml")
    monkeypatch.setenv(fan_profile.PROFILE_ENV, str(environment))
    monkeypatch.setattr(fan_profile, "system_profile_path", lambda: system)

    assert fan_profile.load_fan_profile(explicit).source == str(explicit)
    assert fan_profile.load_fan_profile().source == str(environment)

    monkeypatch.delenv(fan_profile.PROFILE_ENV)
    assert fan_profile.load_fan_profile().source == str(system)


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


def test_previous_ec_slot_layout_is_converted_to_gcu_points(tmp_path):
    path = write_profile(tmp_path / "ec-slots.toml", legacy_profile_text())

    profile = fan_profile.load_fan_profile(path)

    assert profile.main.up[:3] == (0, 40, 45)
    assert profile.main.down[:3] == (35, 40, 45)
    assert profile.main.up[-1] == 110
    assert profile.main.down[-1] == 255


def test_missing_explicit_profile_does_not_silently_fallback(tmp_path):
    path = tmp_path / "missing.toml"

    with pytest.raises(ValueError, match=f"fan profile not found: {path}"):
        fan_profile.load_fan_profile(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "  { up = 180, duty = 95 },\n",
            "",
            r"\[main\]\.levels must contain exactly 16",
        ),
        ("duty = 95 },", "duty = 101 },", r"levels\[15\]\.duty.*0-100"),
        (
            "up = 40, down = 40",
            "up = 30, down = 40",
            r"levels\[0\]\.down.*provide hysteresis",
        ),
        (
            "up = 50, down = 50, duty = 30",
            "up = 50, down = 50, duty = 15",
            r"levels\[2\]\.duty.*previous duty",
        ),
        (
            "up = 50, down = 50",
            "up = 40, down = 50",
            r"levels\[2\]\.up.*previous up",
        ),
        (
            "up = 50, down = 50",
            "up = 50, down = 40",
            r"levels\[2\]\.down.*previous down",
        ),
    ],
)
def test_profile_validation_rejects_invalid_curves(tmp_path, old, new, message):
    path = write_profile(
        tmp_path / "invalid.toml", profile_text().replace(old, new, 1)
    )

    with pytest.raises(ValueError, match=message):
        fan_profile.load_fan_profile(path)


def test_profile_rejects_legacy_parallel_arrays(tmp_path):
    path = write_profile(
        tmp_path / "legacy.toml",
        "[main]\nup = [1]\ndown = [0]\nduty = [20]\n\n"
        "[second]\nup = [1]\ndown = [0]\nduty = [20]\n",
    )

    with pytest.raises(ValueError, match=r"\[main\] must contain only levels"):
        fan_profile.load_fan_profile(path)
