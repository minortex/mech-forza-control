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

输入缓冲区: `struct('<II', ec_addr, byte_value)`

EC 读输出: 4 字节 int，低字节为 EC 值。

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

### 地址（读写，但 BIOS 持续覆盖）

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

### 1883/1884 的行为

这两个地址是 EC 当前输出的 Duty 值。直接写入可以短暂改变风扇转速，但 BIOS 的温控循环会持续覆盖。要实现持久控制，需要先通过控制字节 1873 接管风扇模式并修改风扇表。

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

### 位定义

| Bit | 掩码 | 含义 |
|-----|------|------|
| 0 | 0x01 | 用户档位 Bit0 |
| 1 | 0x02 | 用户档位 Bit1 |
| 4 | 0x10 | Turbo 模式 |
| 6 | 0x40 | FanBoost 模式 |
| 7 | 0x80 | 用户自定义模式 |

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
- 如果写入频率过快或时间间隔不对，极易触发 EC 状态机异常，导致风扇占空比直接退回到默认的 50 或 0。
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

#### 特殊厂商设计：第二点锁定机制
厂商在设计此风扇曲线时，存在一个关键特点：**只有第二个点（即 `EC[3873]`）是生效的，无论 CPU 温度是多少度，风扇占空比永远定格在第二个点对应的 Duty 上。**
因此，只需改写 `EC[3873]` 的值即可控制 CPU 风扇的固定输出。

## 已验证的事实

1. MQTT `Fan/Control` 只能切换模式，不能直接控制风扇 Duty。
2. `FAN_GAMING_MODE_BOOST_ON` / `FAN_OFFICE_MODE_ADVANCED` 等 Action 在此机器上无效。
3. `FanBoostBtnSupport=false`，MQTT FanBoost 不可用。
4. 改磁盘 JSON + 重启服务不能改变风扇行为。
5. 直接写 EC 控制字节 1873 = 240/255 可触发 FanBoost 并加速风扇。
6. EC 风扇表 3872-3887 可写入，生效行为存在“迟滞/单向触发”特征：
   - **从高占空比调到低占空比**：系统能自己慢慢检测并降下来，不需要对 1873 寄存器强冷触发。
   - **从低占空比调到高占空比**：直接写入表不生效。必须对 `1873` (MyFanCTLByteFlag) 反复交替写入强冷模式 `64` 和自动模式 `0` （即 `64 -> 0 -> 64 -> 0` 序列），且动作之间必须保持约 **1.0 秒**的固定时间间隔，才能使 EC 成功重新载入表中的更高占空比。
7. **更加稳定可靠的触发重载机制**：
   当修改 `EC[3873]` 占空比后，直接对控制字节 `EC[1873]` 写入 `64 -> 0 -> 64 -> 0` 的交替触发逻辑（每步间隔 1.0 秒）。该方案比向 `EC[1895]` 写入 `4` 稳定得多，能 100% 保证新 Duty 在 `EC[1883]` 上生效，且由于避开了系统的 Boost Toggle 逻辑，不会弹出 OSD 强冷弹窗，也不会因为状态机重置导致 Duty 回退到 BIOS 默认值。
8. Duty 值范围 0-200（对应 0-100%），非 0-255。实际输出 Duty 通常可能会比风扇表写入的值少 1（例如表写入 100，实际 1883/1884 输出为 99）。
9. 转速 RPM 由两个相邻 EC 字节按 big-endian 拼接：`RPM = HIGH * 256 + LOW`。
   - **主风扇 (物理右侧)**：对应 `EC[1883]` 作为 Duty 控制，`EC[1124]` (H) 与 `EC[1125]` (L) 作为 RPM 读取。
   - **副风扇 (物理左侧)**：对应 `EC[1884]` 作为 Duty 控制，`EC[1132]` (H) 与 `EC[1131]` (L) 作为 RPM 读取。
10. 当副风扇停转或低转速时，RPM 读取会出现大约 45 的底噪值（例如 Duty = 0 时转速显示 45），这属于转速计的物理噪声，并非实际转动。

## 工具脚本

### tools/ec_fan.py

EC 风扇只读监视/读取工具，支持 read / monitor 子命令。已删除了 `setduty`、`dump` 和 `write` 函数，仅用于风扇状态的安全监视。

```powershell
python tools/ec_fan.py read
python tools/ec_fan.py monitor -i 0.5
```

### tools/fan_read.py

读取当前 CPU 和副风扇的 Duty 和 RPM 情况。

```powershell
python tools/fan_read.py read
python tools/fan_read.py monitor
```

### tools/fan_control.py

利用稳定的 1873 寄存器重载序列（`64 -> 0 -> 64 -> 0`，每次间隔 1.0s），实现 100% 稳定的 CPU 自定义占空比重载。

```powershell
python tools/fan_control.py 35
```
