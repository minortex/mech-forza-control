# EC 风扇直控研究报告

## 概述

机械革命笔记本（GCU 控制中心）的风扇可以通过 ACPI 驱动直接读写 EC 寄存器来控制，绕过 GCUService 和 MQTT 总线。

## 数据来源

所有 EC 地址和常量均来自 dnSpy 反编译的 GCU 控制中心程序集：

- `GCUService/Define/ECSpec.cs` -- EC 地址常量、控制字节枚举、Duty-Speed 映射
- `GCUService/Define/RamFan1p5_ECSpec.cs` -- 风扇表 EC 地址
- `GCUService/Define/ServCMD.cs` -- MQTT Action 常量
- `GCUService/MyECIO/AcpiCtrl.cs` -- ACPI 驱动 IOCTL 码
- `SystrayComponent_decompiled/` -- MQTT topic 和风扇控制入口

注意：核心实现方法（`FanInfo.GetEcCpuFanRpm()`、`MyEcCtrl` 读写等）均被混淆器替换为 `throw new Exception("Runtime exception")`，无法直接读到换算逻辑。本文档中的换算公式由以下线索推断并经实测验证。

## ACPI 驱动接口

### 设备路径

```
\\.\\ACPIDriver
```

对应 PnP 设备实例 `ACPI\INOU0000\0`，需要管理员权限打开。

### IOCTL 码

| 操作 | IOCTL 值 | 十六进制 |
|------|----------|----------|
| EC 读 | 2621482120 | 0x9C416C78 |
| EC 写 | 2621482124 | 0x9C416C7C |

### 读写格式

输入缓冲区：`struct('<II', ec_addr, byte_value)`

EC 读输出：4 字节 int，低字节为 EC 值。

## 转速 RPM 读取与换算

### 原理

EC 寄存器每个地址只存 1 字节（0-255），风扇转速需要用两个字节拼成 16 位整数。`ECSpec.cs` 中定义了 `ADDR_EC_*_FAN_RPM_BYTE1` 和 `ADDR_EC_*_FAN_RPM_BYTE2`，命名中的 BYTE1/BYTE2 即高字节/低字节。

### 地址（只读）

| 常量名 | 地址 | 角色 |
|--------|------|------|
| `ADDR_EC_MAIN_FAN_RPM_BYTE1` | 1124 | 主风扇高字节 |
| `ADDR_EC_MAIN_FAN_RPM_BYTE2` | 1125 | 主风扇低字节 |
| `ADDR_EC_SECOND_FAN_RPM_BYTE1` | 1132 | 副风扇高字节 |
| `ADDR_EC_SECOND_FAN_RPM_BYTE2` | 1131 | 副风扇低字节 |

### 换算公式

```
主风扇 RPM = byte[1124] * 256 + byte[1125]
副风扇 RPM = byte[1132] * 256 + byte[1131]
```

推断依据：
1. EC 每地址仅 1 字节，RPM 必须由两个字节组合
2. 常量名 BYTE1/BYTE2 明确标识高/低字节角色
3. 主风扇 1124/1125 顺序递增，符合嵌入式 big-endian 惯例
4. 副风扇地址反序（1131 < 1132），但 BYTE1 仍代表高字节，印证命名与地址无关
5. 首次实读 `EC[1124]=13, EC[1125]=35 => 3363 RPM` 在正常范围内，验证公式成立

### 实测数据

```
EC[1124]=13, EC[1125]=35  => 13*256+35 = 3363 RPM（主风扇）
EC[1131]=45, EC[1132]=11  => 11*256+45 = 2861 RPM（副风扇）
```

## 占空比 Duty 与百分比换算

### 地址（只读）

| 常量名 | 地址 | 含义 |
|--------|------|------|
| `ADDR_EC_MAIN_FAN_L_DUTY_BYTE` | 1883 | 主风扇 Duty |
| `ADDR_EC_MAIN_FAN_R_DUTY_BYTE` | 1884 | 副风扇 Duty |

### 换算公式

```
百分比 = duty_byte / 2
duty_byte = 百分比 * 2
```

满量程 200 = 100%。分辨率 0.5%/单位。

推断依据：`ECSpec.cs` 中的 `MyFan2SpeedByteFlag` 枚举直接给出了映射关系：

| 枚举值 | duty_byte | 对应百分比 |
|--------|-----------|-----------|
| `Speed00` | 0 | 0% |
| `Speed30` | 60 | 30% |
| `Speed35` | 70 | 35% |
| `Speed40` | 80 | 40% |
| `Speed45` | 90 | 45% |
| `Speed50` | 100 | 50% |
| `Speed55` | 110 | 55% |
| `Speed60` | 120 | 60% |
| `Speed70` | 140 | 70% |

规律：`Speed{N}` 的 duty_byte = N * 2。

## 控制字节 1873（MyFanCTLByteFlag）

这是风扇控制的核心开关。`ECSpec.cs` 中定义了 `MyFanCTLByteFlag` 枚举：

| 枚举值 | 值 | 二进制 | 含义 |
|--------|-----|--------|------|
| `Normal_Mode` | 0 | 00000000 | BIOS 自动控制（默认） |
| `Turbo_Mode` | 16 | 00010000 | Turbo 模式 |
| `FanBoost_Mode` | 64 | 01000000 | FanBoost 模式 |
| `User_Fan_Mode` | 128 | 10000000 | 用户自定义风扇模式 |
| `User_Fan_Level1` | 129 | 10000001 | 用户档位 1（User_Fan_Mode + Bit0） |
| `User_Fan_Level2` | 130 | 10000010 | 用户档位 2（User_Fan_Mode + Bit1） |
| `User_Fan_Level3` | 131 | 10000011 | 用户档位 3（User_Fan_Mode + Bit1 + Bit0） |


实际上风扇用户模式根本不生效，为 0 只要在 custom 的电源计划，就会遵守风扇表。

### 位定义

| Bit | 掩码 | 含义 |
|-----|------|------|
| 0 | 0x01 | 用户档位 Bit0 |
| 1 | 0x02 | 用户档位 Bit1 |
| 4 | 0x10 | Turbo 模式 |
| 6 | 0x40 | FanBoost 模式 |
| 7 | 0x80 | 用户自定义模式 |

### 叠加逻辑与发现

控制字节 `EC[1873]` 支持多状态的二进制位叠加（按位或 / 异或关系）：
- 当系统处于 `Turbo` 模式（值为 `16` 即 `00010000`）时，若对其写入 `64`（强冷模式 `01000000`），读取出来的最终状态值会是 **`80`** (`01010000`)。
- 这证明了 EC 内部是用位标志来控制不同的工作模式，而并非简单的模式互斥，修改时若只想叠加特定模式，需要结合位掩码进行读写。

### 实测验证

| 控制值 | 二进制 | 主 Duty | 副 Duty | RPM | 效果 |
|--------|--------|---------|---------|-----|------|
| 16 | 00010000 | ~60 | ~50 | ~2648 | BIOS 自动控制（默认） |
| 64 | 01000000 | 100 | 50 | ~2461 | FanBoost 模式 (强冷开启，显示 OSD 提示) |
| 0 | 00000000 | 100 | 50 | ~2461 | 退出强冷返回自动控制模式 |

## 触发字节 1895（TriggerByteFlag）

与触发相关的关键寄存器是 `EC[1895]` (即 `ADDR_TRIGGER_BYTE`)。`ECSpec.cs` 中定义了对应的 `TriggerByteFlag` 枚举：

| 枚举值 | 值 | 含义 |
|--------|-----|------|
| `WinLock_Trigger` | 1 | Win 锁定 |
| `LightBar_Trigger` | 2 | 灯条 |
| `FanBoost_Trigger` | 4 | **风扇 Boost 触发** |
| `SilentMode_Trigger` | 8 | 静音模式 |
| `USBCharger_Trigger` | 16 | USB 充电 |
| `RGBKeybaord_Trigger` | 32 | RGB 键盘 |
| `RGBLogo_Trigger` | 64 | RGB Logo |

*注意：原文档中曾误记为 `EC[1885]`，实测和源码表明，`EC[1885]` 是 `ADDR_TRIGGER_BYTE2`，而在本机器上真正用于触发的风扇控制是 `EC[1895]` (ADDR_TRIGGER_BYTE)。*

向 `EC[1895]` 写入 `FanBoost_Trigger` (4) 可以在系统层面开关风扇 Boost，但该方法并不稳定：
- 写入 `4` 属于 Toggle 逻辑（开与关循环切换）。
- 此外，此触发方式还会产生系统级的强冷 OSD 提示弹窗。


## 其他相关地址

### 风扇表（16 级温控曲线）

| 地址范围 | 含义 |
|----------|------|
| 3840-3855 | CPU 温度上限 (UpT)，16 级 |
| 3856-3871 | CPU 温度下限 (DownT)，16 级 |
| 3872-3887 | CPU 风扇占空比 (Duty)，16 级 |
| 3888-3903 | GPU 温度上限 (UpT)，16 级 |
| 3904-3919 | GPU 温度下限 (DownT)，16 级 |
| 3920-3935 | GPU 风扇占空比 (Duty)，16 级 |

每级 1 字节，Duty 范围 0-200（0-100%）。

## 已验证的事实

1. MQTT `Fan/Control` 只能切换模式，不能直接控制风扇 Duty。
2. `FAN_GAMING_MODE_BOOST_ON` / `FAN_OFFICE_MODE_ADVANCED` 等 Action 在此机器上无效。
3. `FanBoostBtnSupport=false`，MQTT FanBoost 不可用。
4. 改磁盘 JSON + 重启服务不能改变风扇行为。
5. 直接写 EC 控制字节 1873 = 240/255 可触发 FanBoost 并加速风扇。
6. **更加稳定可靠的触发重载机制**：
7. Duty 值范围 0-200（对应 0-100%），非 0-255。实际输出 Duty 通常可能会比风扇表写入的值少 1（例如表写入 100，实际 1883/1884 输出为 99）。
8. 转速 RPM 由两个相邻 EC 字节按 big-endian 拼接：`RPM = HIGH * 256 + LOW`。
   - **主风扇 (物理右侧)**：对应 `EC[1883]` 作为 Duty 控制，`EC[1124]` (H) 与 `EC[1125]` (L) 作为 RPM 读取。
   - **副风扇 (物理左侧)**：对应 `EC[1884]` 作为 Duty 控制，`EC[1132]` (H) 与 `EC[1131]` (L) 作为 RPM 读取。
9. 当副风扇停转或低转速时，RPM 读取会出现大约 45 的底噪值（例如 Duty = 0 时转速显示 45），这属于转速计的物理噪声，并非实际转动。
10. **恢复自动控制最安全有效的方法**：
    由于 `GCUService` 进程常驻后台运行，因此无需手动计算恢复原本的 Duty 曲线。只需在控制中心随意切换一次模式，或者重启电脑，甚至执行切换模式脚本，`GCUService` 就会将配置好的标准风扇表重新下发，完美恢复 BIOS 的原始温控状态。


## 逆向验证批注

以下批注对照反编译后的 GCU 程序集（
everseCS/GCUService_decompiled/）验证原文档中的推断。

### [注 1] 控制字节 1873 — 模式映射更新

原文档中 1873 的枚举定义来自 ECSpec.MyFanCTLByteFlag，值是正确的。
但 RamFan1p5 平台实际写入的值是 MyFanManager_RamFan1p5.SetFanMode(uint mode) 决定的，
**OperatingMode 枚举与 ECSpec 的 FAN 模式枚举不同**（Gaming/Office 互换）：

| OperatingMode | EC[1873] 无 FanBoost | EC[1873] 有 FanBoost |
|--------------|---------------------|---------------------|
| Office (0) | 160 | 224 |
| Gaming (1) | 0 | 64 |
| Turbo (2) | 16 | 80 |
| Custom (3) | 0 | 64 |

额外增加的寄存器：
- EC[1830] bit7 — Custom 模式标志（SetFanMode 最后一步写入）
- EC[1831] bit6 — CustomerModeLight 指示灯（MyFanTableCtrl.CustomerModeLightOn/Off）

### [注 2] 触发字节 1895 — 确认

ECSpec.cs 中的 TriggerByteFlag 枚举定义与文档一致。
但稳定的风扇切换路径是 SetFanControlByRamFan1p5 + 风扇表写入序列，
不是 1895 的触发方式。

### [注 3] Duty 换算公式 — 代码确认

FanTable_Manager1p5_CML.SetEcFanTable:
`csharp
if (fantable.CPU[i].Duty <= 100)
    b = fantable.CPU[i].Duty * 2;
else
    b = byte.MaxValue;  // 255
`
原文档的 百分比 x 2 公式完全正确。

### [注 4] 风扇表 3840-3935 格式 — 代码确认

SetEcFanTable (CML 变体) 的每条曲线写入逻辑：
`csharp
// CPU 曲线
for i = 0..15:
    EC[3840 + i] = fantable.CPU[i+1].UpT  (最后一点=0xFF)
    if i < 15: EC[3856 + i + 1] = fantable.CPU[i].DownT
    EC[3872 + i] = fantable.CPU[i].Duty * 2
// GPU 曲线同理偏移到 3888/3904/3920
`
注意 UpT/DownT 在 bank 内部**偏移了一位**（i+1 和 i），不是简单的一一对应。

### [注 5] 第二点锁定 — 未找到代码依据

原文档提到"只有第二个点 EC[3873] 生效"，这**未在反编译代码中找到对应逻辑**。
这可能是 EC 固件特性，或者是特定机型的 BIOS 行为。如果完整写入全部 16 点后风扇行为符合预期，
说明所有点都生效，不需要特殊处理。

### [注 6] 已验证事实 5-7 — 理解根本原因

64 -> 0 -> 64 -> 0 序列之所以能刷新风扇 Duty，是因为这触发了：
1. SetFanControlByRamFan1p5(false) -> EC[1990] &= ~4（AP 控制关闭）
2. 此时写风扇表 -> EC[3840-3935]
3. SetFanControlByRamFan1p5(true) -> EC[1990] |= 4（AP 控制恢复）

这个使能/禁用切换让 EC 重载了风扇表。相当于模拟了 MyFanTableCtrl.SetFanTable() 的流程。

### [注 7] 已验证事实 11 — 代码确认

GCU 恢复机制：
1. EnableByService() -> LoadProfileAll() + syncBiosSettings() + Init(true)
2. Init(true) -> RefreshCurrentProfile(OperatingMode) + SetUserProfile(OperatingMode)
3. SetUserProfile() -> SetFanMode() + FanTable.SetFanTable() + PL/TCC 写入

所以重启 GCU 或切换模式确实能完整恢复风扇行为。

### [注 8] 新发现：关键缺失寄存器

原文档未涉及但实际必须的寄存器：

| 地址 | 名称 | 作用 |
|------|------|------|
| 1857 | ADDR_AP_OEM_BYTE bit0 | **ApExistFlag** — 必须设=1，否则 BIOS 不收控制权 |
| 1830 | ADDR_AP_OEM9 bit7 | Custom 模式标志 |
| 1831 | ADDR_AP_OEM10 bit6 | Custom 模式指示灯 |
| 1989 | ADDR_FANCTL_RESP bit7 | FanControlRespective（独立风扇曲线） |
| 1926 | ADDR_L1_PWM_DEFAULT_MYFAN3 | TCC offset 控制 |
| 1927 | ADDR_L2_PWM_DEFAULT_MYFAN3 | FanSwitchSpeed 渐变时间 |

详细说明见 [ec-mode-switch.md](./ec-mode-switch.md)。
