# mech-forza-control 项目指南

通过读写 EC（Embedded Controller）寄存器直接控制机械革命（Mechrevo）笔记本的 CLI 工具。Python 编写，uv 管理依赖。

## 请求权限

使用内核模块的后端已配置，向用户提权出沙盒即可无须 sudo，但是读写寄存器到内存的映射提权需要 sudo（不推荐）。

如果 uv 提示只读文件系统，那么是沙盒挡了，可以把 cache 放到/tmp 里面。

```bash
uv run mfc
```

## 目录结构

```
.
├── src/             # 源代码
│   ├── backends/    # 硬件平台后端
│   └── data/        # 默认配置数据 (如 fan-table.toml)
├── tools/           # 独立脚本
├── tests/           # pytest 测试
├── docs/            # 逆向记录和设计文档
├── ref/             # 逆向参考资料
└── pyproject.toml   # 项目配置
```

## 源代码架构 (`src/`)

| 模块 | 职责 |
|------|------|
| `registers.py` | 硬件常量：EC MMIO 基地址、寄存器地址 |
| `io.py` | EC 读写公共 API |
| `backends/` | 平台后端：`linux.py`、`windows.py` |
| `mode.py` | 电源模式切换：Office/Gaming/Turbo/Custom |
| `fan.py` | 风扇曲线写入（XRAM[3840..3935]） |
| `fan_profile.py` | 风扇表加载与验证（含 Profile Fallback 逻辑） |
| `backlight.py` | 键盘背光 |
| `setting.py` | 系统设置类功能 |
| `__main__.py` | CLI 入口 |

## 风扇配置 Fallback 顺序 (Fan Profile Loading)

程序加载风扇表时，按以下优先级依次查找，找到即停止：
1. **Explicit Path**: `--file` 命令行参数指定路径。
2. **Environment Variable**: `MFC_FAN_TABLE` 环境变量指向的路径。
3. **System Profile**: `/etc/mech-forza-control/fan-table.toml`。
4. **Bundled Fallback**: 源码包内 `src/data/fan-table.toml`。

## 探索记录 (`docs/`)

| 文档 | 内容 |
|------|------|
| `llm/ec-mode-switch.md` | EC 模式切换寄存器全景 |
| `ec-register-map.md` | 所有 EC 寄存器地址与位定义 |
| `cli-reference.md` | CLI 用法参考 |

## 运行和测试

详见 `docs/cli-reference.md`。
