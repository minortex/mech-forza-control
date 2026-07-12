# mech-forza-control 项目指南

通过读写 EC（Embedded Controller）寄存器直接控制机械革命（Mechrevo）笔记本的 CLI 工具。Python 编写，uv 管理依赖。

## 请求权限

运行任何 `uv run` 命令都需要跳出沙盒并 sudo（sudo 免密码），因为需要读写 `/dev/mem`。

```bash
sudo uv run ec
```

## 目录结构

```
.
├── src/ec/          # 源代码，分模块
├── tools/           # 独立脚本（调试、探测用）
├── tests/           # pytest 测试（无硬件 mock）
├── docs/            # 探索过程中的逆向记录和设计文档
├── ref/             # 逆向参考资料（反编译代码、ACPI 表等）
├── build/           # Arch Linux PKGBUILD 打包产物
└── pyproject.toml   # 项目配置，入口点 ec.__main__:main
```

## 源代码架构 (`src/ec/`)

| 模块 | 职责 |
|------|------|
| `config.py` | 硬件常量：EC MMIO 基地址、寄存器地址、模式标签、默认风扇表 |
| `io.py` | EC 读写公共 API：`ec_read()`、`ec_write()`、`ec_rmw()`、`open_ec()`、`close()` |
| `backends/` | 平台后端：`linux.py`（/dev/mem + acpi_call）、`windows.py`（ACPIDriver） |
| `mode.py` | 电源模式切换：Office(25W) / Gaming(45W) / Turbo(65W) / Custom |
| `fan.py` | 风扇曲线写入（EC[3840..3935]，6 组 x16 级） |
| `backlight.py` | 键盘背光亮度（5 挡，EC[1932]） |
| `setting.py` | 设置类功能：Win 锁、Fn 锁、USB 充电、AC Recovery、电池充电模式 |
| `__main__.py` | CLI 入口，argparse 子命令分发 |

## 工具脚本 (`tools/`)

| 脚本 | 用途 |
|------|------|
| `ec_rw.py` | 底层 EC 字节读写，调试用 |
| `ec_probe.py` | EC 寄存器批量探测 |
| `switch_mode.py` | 模式切换的早期独立脚本 |
| `mqtt_pub.py` | MQTT 消息发送（模拟官方 GCU Service） |
| `mqtt_sniff.py` | MQTT 消息抓包（监听官方控制台通信） |

## 逆向参考资料 (`ref/`)

### 反编译代码

- **`ref/GCUService_decompiled/`** — dnSpy 反编译的 GCU 控制中心程序集，**可读性最好的版本**，文件名和类名还原。关键目录：
  - `Define/ECSpec.cs` — EC 地址常量、触发/状态/支持位枚举
  - `Define/GCU2_Define.cs` — OperatingMode 枚举（Office=0, Gaming=1, Turbo=2, Custom=3）
  - `Define/ServCMD.cs` — MQTT Action 常量（WINKEY_LOCK, FNKEY_LOCK 等）
  - `Define/RamFan1p5_ECSpec.cs` — RamFan1p5 风扇控制器的 EC 规格
  - `MyECIO/MyEcCtrl.cs` — EC 读写 facade（调用 AcpiCtrl）
  - `MyECIO/AcpiCtrl.cs` — Windows ACPI IOCTL 封装
  - `MyControlCenter/MyFanManager_RamFan1p5.cs` — **核心**：模式切换、风扇表写入、TCC 控制
  - `MyControlCenter/MyFan/FanTable/MyFanTableCtrl.cs` — 风扇表控制、AP_CTL toggle
  - `MyControlCenter/MyFan/FanTable/FanTable_Manager1p5_CML.cs` — CML 格式风扇表写入
  - `MyControlCenter/MySettingManager.cs` — 通用设置项（Win 锁、Fn 锁、USB 充电、AC Recovery）
  - `MyControlCenter/NvramVariable.cs` — UEFI NVRAM 读写（UniWillVariable）
  - `MyControlCenter/NVRAM_STRUCT.cs` — NVRAM 结构体定义（含 BatteryLimitation、ACRecoveryStatus 等）
  - `MySystem/BatteryProtection.cs` — 电池充电模式三档切换

- **`ref/GCUService/`** — 同一程序集的混淆版反编译，文件名为乱码，**不推荐直接阅读**，仅供交叉验证。

- **`ref/GCUService_5.17.49.19/`** — 旧版本（5.17.49.19）的反编译，用于对比不同版本的实现差异。

### ACPI 表

- **`ref/acpi_tables/`** — 从本机提取的原始 ACPI 二进制表（DSDT + SSDT1~25）
- **`ref/acpi_tables/dsl/`** — 反编译后的 ACPI Source Language 文本（可搜索 EC 方法、寄存器定义）
- **`ref/DSDT.dsl`** — 根 DSDT 的另一份反编译副本（顶层方便查找）

### 其他参考

- **`ref/wujie14xCC.go`** — 社区提供的 Go 语言 EC 控制实现（546 行），针对无界 14x 机型，通过 `\_SB.INOU.ECRR/ECRW` ACPI 方法读写 EC。包含电池信息读取、充电模式控制、键盘背光、性能模式切换等寄存器地址定义，可作为交叉参考。

## 探索记录 (`docs/`)

在此区域读取的时候，尽量不要一次`cat`，使用`rg`获取需要的信息即可。

### `docs/llm/` — 逆向分析文档（核心参考）

| 文档 | 内容 |
|------|------|
| `ec-mode-switch.md` | **最重要**：EC 模式切换寄存器全景，含完整寄存器地图、切换序列、风扇表格式、RPM/Duty 读数换算 |
| `ec-setting-controls.md` | Win 锁/Fn 锁/USB 充电/AC Recovery 的 EC 寄存器和调用链逆向记录 |
| `ec-battery-charging-findings.md` | 电池充电模式三档控制（EC[1958] bits[5:4]）、NVRAM 持久化、燃料计行为 |

### `docs/` 根目录 — 功能记录

| 文档 | 内容 |
|------|------|
| `ec-register-map.md` | **EC 寄存器功能总表**：所有已探明的寄存器地址、位定义、快速索引，开发时首选参考 |
| `cli-reference.md` | **CLI 完整参考**：所有 `ec` 子命令、参数、用法示例，以及 `tools/` 脚本说明 |
| `keyboard-backlight.md` | 键盘背光 EC[1932] 寄存器位定义和 5 挡亮度映射 |
| `perf.md` | 三种固定模式的 SPL/sPPT/fPPT 功率值、Custom 模式行为、TCC 覆盖问题 |

## 运行和测试

详见 [`docs/cli-reference.md`](docs/cli-reference.md)。
