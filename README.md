# mechrevo-ec

> Warning: This project is mostly developed by LLM.

Mechrevo notebook EC direct control CLI.

Currently support power profiles configuration, fan control and keyboard light control, more functions are coming soon.

## Usage

> [!IMPORTANT]
> Remember to mask or uninstall tccd first, or fan may not take effect.

On Linux: need `sudo` to write `/dev/mem`

```bash
cd mechrevo-forza-control
sudo uv run ec
```

Help information via `-h` parameters.

## Config

The location of config is in `src/ec/config.py`, you can manually change the fan curve.

## Thanks

- [@w568w](https://github.com/w568w) for providing decompiled official control center.
- [@LongSang01](https://github.com/LongSang01) for switch fixed tdp on this laptop.
- Peoples in [this post](https://gist.github.com/w568w/b2fc5f9d1f4dff13efe751abec27b396).

