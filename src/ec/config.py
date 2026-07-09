"""Hardware constants for Mechrevo EC control."""

EC_MMIO_BASE = 0xFED50000
EC_MMIO_SIZE = 0x1000
EC_MMIO_MIN = 0
EC_MMIO_MAX = EC_MMIO_SIZE - 1

ADDR_MAIN_FAN_RPM_HI = 1124
ADDR_MAIN_FAN_RPM_LO = 1125
ADDR_SECOND_FAN_RPM_HI = 1132
ADDR_SECOND_FAN_RPM_LO = 1131

ADDR_AP_OEM9 = 1830
ADDR_AP_OEM10 = 1831
ADDR_AP_OEM = 1857
ADDR_BIOS_OEM_BYTE = 1870
ADDR_MAFAN_CTL = 1873
ADDR_MAIN_FAN_DUTY = 1883
ADDR_SECOND_FAN_DUTY = 1884
ADDR_TRIGGER_BYTE = 1895
ADDR_STATUS_BYTE = 1896
ADDR_PL1 = 1923
ADDR_PL2 = 1924
ADDR_PL4 = 1925
ADDR_TCC = 1926
ADDR_FAN_SWITCH_SPEED = 1927
ADDR_BACKLIGHT = 1932
ADDR_FANCTL_RESP = 1989
ADDR_AP_CTL = 1990

ADDR_CPU_FAN_UPT_BASE = 3840
ADDR_CPU_FAN_DNT_BASE = 3856
ADDR_CPU_FAN_DUTY_BASE = 3872
ADDR_GPU_FAN_UPT_BASE = 3888
ADDR_GPU_FAN_DNT_BASE = 3904
ADDR_GPU_FAN_DUTY_BASE = 3920

CTL_NORMAL = 0
CTL_TURBO = 16
CTL_USER_HI = 160

PL_DEFAULTS = {
    "gaming": (45, 45, 50),
    "office": (25, 25, 30),
    "turbo": (73, 73, 90),
    "custom": (45, 45, 50),
}
PL_DC = (0, 0, 0)

DEFAULT_CPU_FAN = {
    "upT": [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255],
    "dnT": [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95],
    "duty": [20, 25, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100],
}
DEFAULT_GPU_FAN = {
    "upT": [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255],
    "dnT": [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95],
    "duty": [10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100],
}

MODES = {
    "office": {
        "desc": "Office (silent)",
        "mode": 0,
        "ctl": CTL_USER_HI,
        "pl": PL_DEFAULTS["office"],
        "custom": False,
    },
    "gaming": {
        "desc": "Gaming (balanced)",
        "mode": 1,
        "ctl": CTL_NORMAL,
        "pl": PL_DEFAULTS["gaming"],
        "custom": False,
    },
    "turbo": {
        "desc": "Turbo (performance)",
        "mode": 2,
        "ctl": CTL_TURBO,
        "pl": None,
        "custom": False,
    },
    "custom": {
        "desc": "Custom (manual fan)",
        "mode": 3,
        "ctl": CTL_NORMAL,
        "pl": PL_DEFAULTS["custom"],
        "custom": True,
    },
}

MODE_CTL_LABELS = {
    0: "Normal (Gaming/Custom)",
    16: "Turbo",
    64: "FanBoost",
    80: "Turbo+FanBoost",
    128: "User_Fan",
    160: "HiMode (Office)",
    224: "HiMode+FanBoost",
}

BACKLIGHT_LABELS = {
    0: "off",
    1: "level1",
    2: "dim",
    3: "level3",
    4: "bright",
}

SETTING_LABELS = {
    "winlock": {"addr": ADDR_STATUS_BYTE, "bit": 0, "on": "locked", "off": "unlocked"},
    "fnlock": {"addr": ADDR_BIOS_OEM_BYTE, "bit": 4, "on": "locked", "off": "unlocked"},
    "usbchg": {"addr": ADDR_TRIGGER_BYTE, "bit": 4, "on": "on", "off": "off"},
    "acrecov": {"addr": ADDR_AP_OEM9, "bit": 3, "on": "on", "off": "off"},
}
