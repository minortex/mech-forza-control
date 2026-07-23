"""Hardware constants for Mechrevo EC control."""

EC_MMIO_BASE = 0xFED50000
EC_MMIO_SIZE = 0x1000
EC_MMIO_MIN = 0
EC_MMIO_MAX = EC_MMIO_SIZE - 1

ADDR_CPU_TEMP = 0x043E

ADDR_MAIN_FAN_RPM_HI = 0x0464
ADDR_MAIN_FAN_RPM_LO = 0x0465
ADDR_SECOND_FAN_RPM_HI = 0x046C
ADDR_SECOND_FAN_RPM_LO = 0x046B
ADDR_BATTERY_VOLTAGE = 0x0438
ADDR_BATTERY_BASE_VOLTAGE = 0x030E
ADDR_BATTERY_CHARGE_TARGET = 0x0522
ADDR_BATTERY_CYCLE_COUNT = 0x04A6

ADDR_AP_OEM9 = 0x0726
ADDR_AP_OEM10 = 0x0727
ADDR_AP_OEM = 0x0741
ADDR_BIOS_OEM_BYTE = 0x074E
ADDR_MAFAN_CTL = 0x0751
ADDR_MAIN_FAN_DUTY = 0x075B
ADDR_SECOND_FAN_DUTY = 0x075C
ADDR_TRIGGER_BYTE = 0x0767
ADDR_STATUS_BYTE = 0x0768
ADDR_PL1 = 0x0783
ADDR_PL2 = 0x0784
ADDR_BATTERY_CHARGE_MODE = 0x07A6
ADDR_BATTERY_CHARGE_LIMIT_UP = 0x07B9
ADDR_PL4 = 0x0785
ADDR_TCC = 0x0786
ADDR_FAN_SWITCH_SPEED = 0x0787
ADDR_BACKLIGHT = 0x078C
ADDR_FANCTL_RESP = 0x07C5
ADDR_AP_CTL = 0x07C6

ADDR_CPU_FAN_UPT_BASE = 0x0F00
ADDR_CPU_FAN_DNT_BASE = 0x0F10
ADDR_CPU_FAN_DUTY_BASE = 0x0F20
ADDR_GPU_FAN_UPT_BASE = 0x0F30
ADDR_GPU_FAN_DNT_BASE = 0x0F40
ADDR_GPU_FAN_DUTY_BASE = 0x0F50

CTL_NORMAL = 0
CTL_TURBO = 16
CTL_USER_HI = 160

DEFAULT_CPU_FAN = {
    "upT": [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255],
    "dnT": [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95],
    "duty": [20, 30, 35, 44, 48, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100],
}
DEFAULT_GPU_FAN = {
    "upT": [40, 45, 50, 55, 60, 65, 68, 72, 76, 80, 83, 86, 89, 92, 95, 255],
    "dnT": [35, 40, 45, 50, 55, 60, 63, 67, 71, 75, 78, 81, 84, 87, 90, 95],
    "duty": [10, 20, 25, 30, 35, 40, 45, 50, 65, 70, 75, 80, 85, 90, 95, 100],
}

MODES = {
    "office": {
        "desc": "Office (25W silent)",
        "mode": 0,
        "tdp": 25,
        "ctl": CTL_USER_HI,
        "custom": False,
    },
    "gaming": {
        "desc": "Gaming (45W balanced)",
        "mode": 1,
        "tdp": 45,
        "ctl": CTL_NORMAL,
        "custom": False,
    },
    "turbo": {
        "desc": "Turbo (65W performance)",
        "mode": 2,
        "tdp": 65,
        "ctl": CTL_TURBO,
        "custom": False,
    },
    "custom": {
        "desc": "Custom (manual fan)",
        "mode": 3,
        "tdp": None,
        "ctl": CTL_NORMAL,
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

TDP_CTL = {
    25: CTL_USER_HI,
    45: CTL_NORMAL,
    65: CTL_TURBO,
}

# Brightness order (brightest to dimmest): 2 > 4 > 1 > 3 > 0
# Keyboard shortcut cycle: 0 (off) -> 1 (dim, 001) -> 2 (max, 010)
BACKLIGHT_LABELS = {
    0: "off",
    1: "dim",
    2: "bright",
}

BACKLIGHT_CYCLE = [0, 1, 2]  # off -> dim -> bright

SETTING_LABELS = {
    "winlock": {"addr": ADDR_STATUS_BYTE, "bit": 0, "on": "locked", "off": "unlocked"},
    "fnlock": {"addr": ADDR_BIOS_OEM_BYTE, "bit": 4, "on": "locked", "off": "unlocked"},
    "usbchg": {"addr": ADDR_TRIGGER_BYTE, "bit": 4, "on": "on", "off": "off"},
    "acrecov": {"addr": ADDR_AP_OEM9, "bit": 3, "on": "on", "off": "off"},
}
