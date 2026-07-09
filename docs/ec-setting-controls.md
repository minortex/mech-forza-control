# EC 设置类功能逆向记录

本文记录官方 GCU 控制中心中几个非风扇设置项的实现路径：
Win 按键锁、Fn 锁、关机 USB 充电、来电自动开机。

重点是反编译 C# 证据链、EC 寄存器地址、bit 含义，以及 UEFI
NVRAM 写入路径。本文不是 Python CLI 的实现规格；后续实现时应再结合
实机验证。

## 数据来源

反编译代码位于 `ref/GCUService_decompiled/GCUService`。

| 文件 | 作用 |
|------|------|
| `Define/ServCMD.cs` | `Setting/Control` 的 Action 常量 |
| `Define/ECSpec.cs` | EC 地址、trigger/status/support 枚举 |
| `MyControlCenter/MqttClientCtrl.cs` | MQTT topic 订阅与消息接收 |
| `MyControlCenter/App.cs` | 按 topic 分发到各 Manager |
| `MyControlCenter/MySettingManager.cs` | 通用设置项主实现 |
| `MyControlCenter/MySettingManager_Intel.cs` | Intel 平台设置实现 |
| `MyControlCenter/MySettingManager_QC.cs` | QC 平台设置实现 |
| `MyControlCenter/NvramVariable.cs` | UEFI NVRAM 读写包装 |
| `MyControlCenter/NVRAM_STRUCT.cs` | NVRAM struct 字段定义 |
| `MyECIO/MyEcCtrl.cs` | EC 读写 facade |
| `MyECIO/AcpiCtrl.cs` | Windows `ACPIDriver` IOCTL 调用 |

## 公共入口与底层链路

官方服务连接本机 MQTT broker，订阅 `Setting/Control` 等 topic。
`MqttClientCtrl.SetClient()` 中 topic 列表包含 `Setting/Control`
（`MqttClientCtrl.cs:53-74`）。收到 MQTT publish 后触发
`Client_MqttMsgPublishReceived()`（`MqttClientCtrl.cs:191-199`）。

`App.Recieve()` 按 topic 分发。`Setting/Control` 会调用
`App.m_MySetting.Recieve(Message)`（`App.cs:277-283`）。

`MySettingManager.Recieve()` 解析 JSON 的 `Action` 字段，然后按字符串分发
（`MySettingManager.cs:295` 附近）。本文涉及的 Action 常量在
`ServCMD.cs`：

| 功能 | Action |
|------|--------|
| Win 锁 | `WINKEY_LOCK`, `WINKEY_UNLOCK` |
| Fn 锁 | `FNKEY_LOCK`, `FNKEY_UNLOCK` |
| 关机 USB 充电 | `USB_CHARGER_ON`, `USB_CHARGER_OFF` |
| 来电自动开机 | `ACRECOVERY_TOGGLE_ON`, `ACRECOVERY_TOGGLE_OFF` |

EC 读写链路：

```text
MySettingManager.* -> EcCtrl.Read/Write
                   -> MyEcCtrl.Read/Write
                   -> AcpiCtrl.Read/Write
                   -> ReadACPI/WriteACPI
                   -> \\.\ACPIDriver DeviceIoControl
```

`MyEcCtrl.Read/Write` 只是转发到 `AcpiCtrl`（`MyEcCtrl.cs:50-68`）。
`AcpiCtrl.Read()` 调 `ReadACPI(2621482120U, Addr, ref Data)`，
`AcpiCtrl.Write()` 调 `WriteACPI(2621482124U, Addr, Data)`
（`AcpiCtrl.cs:103-134`）。

## EC 地址与 bit 摘要

| 十进制 | 十六进制 | 官方常量 | 用途 |
|--------|----------|----------|------|
| 1830 | `0x0726` | `ADDR_AP_OEM_BYTE9` | AC recovery fallback bit3；也被其他功能复用 |
| 1870 | `0x074E` | `ADDR_BIOS_OEM_BYTE` | Fn 锁通用/Intel bit4 |
| 1895 | `0x0767` | `ADDR_TRIGGER_BYTE` | Win 锁 trigger bit0；USB 充电 bit4 |
| 1896 | `0x0768` | `ADDR_STAUTS_BYTE` | Win 锁状态 bit0 |
| 1956 | `0x07A4` | `ADDR_AP_BIOS_BYTE` | QC Fn 锁 bit3 |

`ECSpec.cs` 中对应枚举：

```csharp
TriggerByteFlag.WinLock_Trigger = 1
TriggerByteFlag.USBCharger_Trigger = 16
SupportByteTwoFlag.USBChargerMode = 2
StatusByteOneFlag.WinLock = 1
```

## Win 按键锁

### Action 与调用链

`Setting/Control` 收到：

```text
WINKEY_LOCK   -> UserSetWinKey(1)
WINKEY_UNLOCK -> UserSetWinKey(0)
```

分发位置在 `MySettingManager.cs:595-600` 与 `MySettingManager.cs:746-750`。
`UserSetWinKey()` 更新内存状态，然后调用 `SetWinKey(status)` 和
`SetWinKeyREG(status)`（`MySettingManager.cs:1996-2008`）。

`SetWinKeyREG()` 写 Windows 注册表：

```text
HKLM\<m_sRegistryPath>\WinKeyLock = 0/1
```

代码位置：`MySettingManager.cs:3141-3143`。

### EC 行为

Win 锁不是直接写状态位，而是先读状态，再按需触发切换。

`SetWinKey()`：

1. 读 EC `1896` (`0x0768`)。
2. 检查 `bit0` 是否已经等于目标状态。
3. 如果不一致，调用 `WinKeyLock_Trigger()`。

代码位置：`MySettingManager.cs:2983-3003`。

`WinKeyLock_Trigger()`：

```csharp
EcCtrl.Read(..., 1895, ref b);
b2 = b & 0xFE;
EcCtrl.Write(..., 1895, 1 + b2);
```

也就是保留 `1895` 其他 bit，清掉 bit0 后写回 bit0=1，向 EC 发出
Win 锁 toggle trigger。代码位置：`MySettingManager.cs:3007-3014`。

### 结论

| 项 | 值 |
|----|----|
| 状态位 | EC `1896/0x0768 bit0` |
| 触发位 | EC `1895/0x0767 bit0` |
| Lock | 如果状态 bit0 不是 1，则写 trigger bit0 |
| Unlock | 如果状态 bit0 不是 0，则写 trigger bit0 |
| 持久化 | 注册表 `WinKeyLock` |

实现时不要把 `1896 bit0` 当成可写控制位。官方代码通过 `1895 bit0`
触发，由 EC 自己更新 `1896 bit0`。

## Fn 锁

Fn 锁存在多个平台分支。通用实现和 Intel 实现主要写
EC `1870/0x074E bit4`；QC 实现另有 `1956/0x07A4 bit3` 写入路径。

### 通用 MySettingManager

`Setting/Control` 收到：

```text
FNKEY_LOCK   -> UserSetFnKey(1)
FNKEY_UNLOCK -> UserSetFnKey(0)
```

分发位置在 `MySettingManager.cs:530-535` 与 `MySettingManager.cs:670-675`。

`UserSetFnKey(status)`：

1. 更新 `MySettingParams.sFnKey_Status`。
2. 写注册表 `HKLM\<m_sRegistryPath>\FnKey\FnKeyStatus = 0/1`。
3. 如果 BIOS 变量支持，即 `m_BiosFnKeyStatus != 255`，写
   `NvramVariable.SetFwVars("FnKeyStatus", value)`。
4. 调用 `SetFnKey(status)` 写 EC。

代码位置：`MySettingManager.cs:2121-2143`。

`SetFnKey(status)`：

```csharp
EcCtrl.Read(..., 1870, ref b);
if (status == 1)
    b |= 16;     // set bit4
else
    b &= 239;    // clear bit4
EcCtrl.Write(..., 1870, b);
```

代码位置：`MySettingManager.cs:3080-3094`。

### Intel 分支

`MySettingManager_Intel.cs` 也处理 `FNKEY_LOCK` / `FNKEY_UNLOCK`，实际状态
读写仍围绕 EC `1870/0x074E bit4`：

```csharp
EcCtrl.Read(..., 1870, ref b);
if (status == 1)
    b |= 16;
else
    b &= 239;
EcCtrl.Write(..., 1870, b);
```

写入位置：`MySettingManager_Intel.cs:749-765`。状态读取位置：
`MySettingManager_Intel.cs:913-929`。

### QC 分支

`MySettingManager_QC.cs` 中：

1. `UserSetFnKey(uint status)` 先检查 SMBIOS 支持位
   `SMBIOSINFO.m_bSupportFnKeySetting`。
2. `SetFnKeySwapPower(status)` 写 EC `1956/0x07A4 bit3`：
   lock 置 bit3，unlock 清 bit3。
3. `GetFnKeyStatus()` 仍读取 `1870/0x074E bit4`。

`UserSetFnKey()` 位置：`MySettingManager_QC.cs:685-692`。状态读取位置：
`MySettingManager_QC.cs:847-862`。`1956 bit3` 写入位置：
`MySettingManager_QC.cs:870-886`。

### NVRAM

`NvramVariable.SetFwVars("FnKeyStatus", value)` 修改
`NVRAM_STRUCT.FnKeyStatus` 后写回 UEFI。字段定义在
`NVRAM_STRUCT.cs:318`。`SetFwVars()` 中处理 `FnKeyStatus` 的分支位于
`NvramVariable.cs:405-407`，随后序列化整个 struct 并调用
`WriteUefi(...)`。

初始化时，官方代码会读取 `fwVars.FnKeyStatus`：

1. 如果值为 `255`，表示 BIOS 变量不提供状态，回退读注册表。
2. 否则用该 NVRAM 值作为 Fn 锁状态，并调用 `SetFnKey()` 同步 EC。

代码位置：`MySettingManager.cs:2611-2640`。

### 结论

| 平台/分支 | EC 控制 | NVRAM | 注册表 |
|-----------|---------|-------|--------|
| 通用 | `1870/0x074E bit4` | `FnKeyStatus`，如果 BIOS 支持 | `FnKey\FnKeyStatus` |
| Intel | `1870/0x074E bit4` | 未在该分支主路径看到 | 有状态维护 |
| QC | 写 `1956/0x07A4 bit3`，读 `1870/0x074E bit4` | 未在主路径看到 | 有状态维护 |

后续实现在 Linux 上优先验证 `1870 bit4`。QC 平台或特殊机型需要额外验证
`1956 bit3`。

## 关机 USB 充电

### Action 与调用链

`Setting/Control` 收到：

```text
USB_CHARGER_ON  -> UserSetUSBCharger(1)
USB_CHARGER_OFF -> UserSetUSBCharger(0)
```

分发位置在 `MySettingManager.cs:785-790` 与 `MySettingManager.cs:822-827`。

`UserSetUSBCharger(status)`：

1. 更新 `MySettingParams.sUsbCharger_Status`。
2. ON 调 `USB_Charger_ON()`，OFF 调 `USB_Charger_OFF()`。
3. 调 `SetUSBChargerREG(status)` 写注册表。

代码位置：`MySettingManager.cs:1980-1993`。

### EC 行为

`USB_Charger_ON()`：

```csharp
EcCtrl.Read(..., 1895, ref b);
bitArray[4] = true;
EcCtrl.Write(..., 1895, ConvertToByte(bitArray));
```

`USB_Charger_OFF()`：

```csharp
EcCtrl.Read(..., 1895, ref b);
bitArray[4] = false;
EcCtrl.Write(..., 1895, ConvertToByte(bitArray));
```

代码位置：`MySettingManager.cs:3036-3055`。

`SetUSBChargerREG()` 写注册表：

```text
HKLM\<m_sRegistryPath>\USBCharger = 0/1
```

代码位置：`MySettingManager.cs:3123-3125`。

### 结论

| 项 | 值 |
|----|----|
| EC 位 | `1895/0x0767 bit4` |
| ON | 设置 bit4 |
| OFF | 清除 bit4 |
| NVRAM | 未看到 |
| 持久化 | 注册表 `USBCharger` |

`ECSpec.TriggerByteFlag.USBCharger_Trigger = 16`，但官方代码对 USB 充电的
写法是保留其他 bit 后直接设置/清除 bit4，不是像 Win 锁那样按状态触发。

## 来电自动开机 / AC Recovery

### Action 与调用链

`Setting/Control` 收到：

```text
ACRECOVERY_TOGGLE_ON  -> UserSetAcRecoverySwitch(1)
ACRECOVERY_TOGGLE_OFF -> UserSetAcRecoverySwitch(0)
```

分发位置在 `MySettingManager.cs:1112-1116` 与
`MySettingManager.cs:1125-1129`。

`UserSetAcRecoverySwitch(status)` 根据
`MySettingParams.sAcRecoverySwitch_BiosSupport` 分两条路径：

1. BIOS 支持：写 UEFI NVRAM 字段 `ACRecoveryStatus`。
2. BIOS 不支持：写 EC `1830/0x0726 bit3`。

代码位置：`MySettingManager.cs:2166-2197`。

### NVRAM 路径

如果 `sAcRecoverySwitch_BiosSupport == "Support"`：

```csharp
NvramVariable.SetFwVars("ACRecoveryStatus", 1); // ON
NvramVariable.SetFwVars("ACRecoveryStatus", 0); // OFF
```

`NVRAM_STRUCT` 中字段：

```csharp
public byte ACRecoverySupport;
public byte ACRecoveryStatus;
```

字段定义位置：`NVRAM_STRUCT.cs:290-294`。

`NvramVariable.SetFwVars()` 中处理 `ACRecoveryStatus` 的分支位于
`NvramVariable.cs:459-461`。写入流程是修改内存中的 `_fwvars`，序列化整个
`NVRAM_STRUCT`，然后调用 `WriteUefi(...)` 写回。

### EC fallback 路径

如果 BIOS 不支持：

```csharp
EcCtrl.Read(..., 1830, ref b);

// ON
b |= 8;
EcCtrl.Write(..., 1830, b);

// OFF
b &= 247; // 0xF7
EcCtrl.Write(..., 1830, b);
```

即 EC `1830/0x0726 bit3`。

### 初始化判断

初始化时官方代码先 `NvramVariable.GetFwVars()`：

1. 读取 `fwVars.ACRecoverySupport`。
2. 如果 `ACRecoverySupport == 1`，认为 BIOS 支持，读取
   `fwVars.ACRecoveryStatus`。
3. 否则读取 EC `1830 bit3` 作为状态。

代码位置：`MySettingManager.cs:2540-2571`。

### 结论

| 条件 | 控制路径 |
|------|----------|
| BIOS 支持 `ACRecoverySupport == 1` | NVRAM `ACRecoveryStatus = 0/1` |
| BIOS 不支持 | EC `1830/0x0726 bit3` |

Linux 直控时不要默认只写 EC `1830 bit3`。在官方逻辑里，这只是 BIOS
不支持 NVRAM 字段时的 fallback；支持时真正持久化的是 UEFI NVRAM。

## 实现注意点

1. `1895/0x0767` 被多个 trigger/setting 复用。写 Win 锁或 USB 充电时必须
   read-modify-write，不能整字节覆盖。
2. Win 锁用 `1895 bit0` 触发，状态在 `1896 bit0`。不要把状态位当控制位。
3. Fn 锁的主流路径是 `1870 bit4`，但 QC 分支有 `1956 bit3`。实现时应按
   机型或实测结果选择路径。
4. AC recovery 优先 NVRAM。EC `1830 bit3` 只应视为 fallback 路径。
5. 官方 Windows 服务还会写注册表保存 UI 状态。Linux CLI 如果只做硬件直控，
   可以不复制注册表行为，但文档或命令输出应区分“硬件状态”和“官方 UI 状态”。
6. 上述地址来自反编译与已有项目上下文，实际机型的 EC 固件可能复用 bit。
   新增写命令前应先提供 read/status 命令和 dry-run/trace 输出。
