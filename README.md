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

This laptop support control the charging process through capacity and voltage limit. However, you can't control it via official control center because the EC register is not initialized correctly.


If you want to control the capacity limit, here are two ways:
1. follow this [guide](https://gist.github.com/w568w/957976b59906e0ce5d6c13ad342e1593) 
2. flash [slimbook firmware](https://slimbook.com/en/downloads?ruta=%2FLaptops%2FEvo-14%2FRyzen-8845HS%2FBIOS) then turn on the charge limit on BIOS.

then use `mfc bat setc <limit>`.

Without modifying the EC firmware, the voltage limit `setv` or the official control center will never take effect.

---

> [!WARNING]
> IT'S REALLY DANGEROUS TO FLASH EC IF YOU DIDN'T HAVE A SPI PROGRAMMER!
> YOU CAN TRY FLASHING IT VIA `ifux64.efi`, BUT IT TAKES HIGH RISKS!

Moreover, most of users charge limit is limit to about 16.4v, which is below the charge limit voltage by 1V, making the battery can't be charged to full so the battery health drops quickly.

Luckily, the laptop EC has no signing verification, we can flash it with custom EC firmware.

You can try flash [this](https://github.com/minortex/ec_reverse/tree/main/firmware_mods/GXxHXxx_21.200), with absolutely no warranty.

## Config

The location of config is in `src/config.py`, you can manually change the fan curve.

## Thanks

- [@w568w](https://github.com/w568w) for providing decompiled official control center.
- [@LongSang01](https://github.com/LongSang01) for switch fixed tdp on this laptop.
- Peoples in [this post](https://gist.github.com/w568w/b2fc5f9d1f4dff13efe751abec27b396).
