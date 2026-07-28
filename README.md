# Mechrevo Forza Control

> Warning: This project is mostly developed by LLM.

Mechrevo Forza EC direct control CLI.

Currently support almost all settings in official control center.

## Usage

> [!IMPORTANT]
> Remember to mask or uninstall tccd first, or fan may not take effect.

On Linux, the default backend is the GX4HRXL-specific kernel bridge at
`/dev/mechrevo-ec`. The driver owns the firmware-declared 4 KiB EC MMIO resource and exposes
checked byte, block, and atomic vector ioctls; userspace never maps `/dev/mem`. Multiple clients
may open the device (for example monitor plus mode switching), while a device mutex serializes
hardware transactions. The driver is maintained separately in
[`mech-forza-kmod`](https://github.com/minortex/mech-forza-kmod). Install its DKMS package
and load it manually after ensuring no other driver owns `INOU0000`.

The DKMS package installs a udev rule that exposes the device as `0660 root:wheel`.
Members of `wheel` can use the default kernel backend without running the whole CLI as root:

```bash
cd mechrevo-forza-control
uv run mfc
```

Do not make the EC device world-writable. Users outside `wheel`, and explicitly selected legacy
`devmem`/`acpi-call` backends, still require suitable elevated privileges.

Help information via `-h` parameters.

### About battery control

This laptop can control charging through EC charge thresholds, but the vendor setup leaves part of the path uninitialized, so the official control center usually cannot make it work reliably.

If you want to use the upper threshold control, enable it first by one of these ways:
1. follow this [guide](https://gist.github.com/w568w/957976b59906e0ce5d6c13ad342e1593)
2. flash [SlimBook firmware BIOS N1.1.14GOS07 + EC2.12](https://slimbook.com/en/downloads?ruta=%2FLaptops%2FEvo-14%2FRyzen-8845HS%2FBIOS) and then turn on the charge limit option in BIOS. Note that the charge limit menu is removed in the latest version.

Then use `mfc bat set -u <limit>`.

---

Moreover, most of users charge limit is limit to about 16.4v, which is below the charge limit voltage by 1V, making the battery can't be charged to full so the battery health drops quickly.

Since the EC does not enforce cryptographic signature verification, you can bypass this limitation by flashing a modded EC firmware:

> [!WARNING]
> FLASHING EC FIRMWARE WITHOUT A EXTERNAL SPI PROGRAMMER CARRIES RISK OF BRICKING YOUR DEVICE!
> WHILE FLASHING VIA `ifux64.efi` IS POSSIBLE, DO SO AT YOUR OWN RISK!

- Unlocked Charge Voltage: Removes the 16.4V ceiling, allowing the battery to reach its true full capacity.
- Hysteresis Charging Window: Supports configurable lower and upper thresholds (e.g., stops at 80%, resumes at 70%) to avoid rapid, wear-inducing charge cycles.

Important Note: You must flash the modded EC firmware for hysteresis control to work. On stock firmware, the register doesn't implement the lower threshold function, charging behavior will remain unchanged.

You can try flashing the customized firmware here (provided strictly as-is, with no warranty):

[https://github.com/minortex/ec_reverse/tree/main/firmware_mods/GXxHXxx_21.200]

## Config

The location of config is in `src/config.py`, you can manually change the fan curve.

## Thanks

- [@w568w](https://github.com/w568w) for providing decompiled official control center.
- [@LongSang01](https://github.com/LongSang01) for switch fixed tdp on this laptop.
- Peoples in [this post](https://gist.github.com/w568w/b2fc5f9d1f4dff13efe751abec27b396).
