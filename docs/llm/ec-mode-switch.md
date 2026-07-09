# EC 模式切换寄存器文档

> 本文档记录通过 EC 直接切换 GCU 电源管理模式的寄存器映射、逻辑序列及代码来源，
> 不依赖 GCUService 或 MQTT，适用于 Linux/Win 直控场景。

## 数据来源

所有寄存器地址和逻辑均来自 dnSpy 反编译的 GCU 控制中心程序集：

| 文件 | 说明 |
|------|------|
| Define/GCU2_Define.cs | OperatingMode 枚举 |
| Define/ECSpec.cs | EC 地址常量、MyFanCTLByteFlag 枚举 |
| MyControlCenter/MyFanManager.cs | 基类 SetFanMode、UserSet_Mode1-3 |
| MyControlCenter/MyFan/MyFanManager_RamFan1p5.cs | RamFan1p5 SetFanMode（核心）、Disable、EnableByService |
| MyControlCenter/MyFan/FanTable/MyFanTableCtrl.cs | SetFanTable、SetFanControlByRamFan1p5、CustomerModeLight |
| MyControlCenter/MyFan/FanTable/FanTable_Manager1p5_CML.cs | SetEcFanTable（CML 格式） |
| MyECIO/MyEcCtrl.cs | Set_APExistToEC |
| MyControlCenter/NvramVariable.cs | SetFwVarsForUninstall、WriteUefi |

## OperatingMode 定义

[MyFanManager_RamFan1p5.cs 使用 OperatingMode 枚举](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\Define\GCU2_Define.cs)，
注意这个枚举**与 ECSpec 中的 FAN 模式枚举不同**（Gaming/Office 互换）：

| Enum | Value | 含义 | FAN 模式 | EC[1873] 值 |
|------|-------|------|----------|-------------|
| Office | 0 | 安静（省电） | FAN_OFFICE_MODE=1 | 160 |
| Gaming | 1 | 均衡 | FAN_GAMING_MODE=0 | 0 |
| Turbo | 2 | 高性能 | FAN_TURBO_MODE=2 | 16 |
| Custom | 3 | 自定义手动 | FAN_CUSTOM_MODE=3 | 0 |
| Benchmark | 4 | 跑分 | — | 160 |

## 核心寄存器地图

### EC[1873] — 风扇控制字节 (ADDR_MAFAN_CONTROL_BYTE)

值来自 [ECSpec.MyFanCTLByteFlag](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\Define\ECSpec.cs)。
RamFan1p5 的 [SetFanMode(uint mode)](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\MyFanManager_RamFan1p5.cs) 决定了各模式的最终值。

#### 无 FanBoost（bit6=0）

| 模式 | EC[1873] | 说明 |
|------|----------|------|
| Gaming | 0 | Normal_Mode |
| Office | 160 (0xA0) | User_Fan_HiMode |
| Turbo | 16 (0x10) | Turbo_Mode |
| Custom | 0 | Normal_Mode |

#### 有 FanBoost（bit6=1）

| 模式 | EC[1873] | 计算 |
|------|----------|------|
| Gaming | 64 (0x40) | 0 + 64 |
| Office | 224 (0xE0) | 160 + 64 |
| Turbo | 80 (0x50) | 16 + 64 |
| Custom | 64 (0x40) | 0 + 64 |

### EC[1830] bit7 — Custom 模式标志 (ADDR_AP_OEM9)

[SetFanMode](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\MyFanManager_RamFan1p5.cs) 在写完 EC[1873] 后写入：

`
Custom (mode==3): EC[1830] |= 0x80  (bit7=1)
其他模式:         EC[1830] &= 0x7F  (bit7=0)
`

**注意：这个写入必须在 EC[1873] 之后，因为 EC 处理模式字节时可能会复位这个寄存器。**

### EC[1831] bit6 — Customer Mode 灯 (ADDR_AP_OEM10)

[MyFanTableCtrl](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\FanTable\MyFanTableCtrl.cs) 提供了两个方法：

`csharp
SetAPCustomerModeLightOn()  → EC[1831] |= 0x40
SetAPCustomerModeLightOff() → EC[1831] &= 0xBF
`

Custom 模式下 SetFanMode 调用 	his.FanTable.CustomerModeLightOn()。

### EC[1857] bit0 — ApExistFlag (ADDR_AP_OEM_BYTE)

**这是最关键的缺失寄存器。** [MyEcCtrl.Set_APExistToEC](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyECIO\MyEcCtrl.cs)：

`csharp
public void Set_APExistToEC(bool bExist) {
    byte b = 0; this.Read(..., 1857, ref b);
    if (bExist) b |= 1; else b &= 0xFE;
    this.Write(..., 1857, b);
}
`

| 值 | 含义 |
|----|------|
| bit0=1 | AP（GCU 服务）在线，EC 接受上层模式指令 |
| bit0=0 | AP 离线，BIOS 接管风扇控制 |

GCU 启动时 EnableByService → syncBiosSettings 会设这个位。
GCU 停止时 Disable 不会主动清它，但 **不设它的话 EC 不执行模式切换**。

### EC[1990] bit2 — RamFan1p5 AP 控制使能 (ADDR_AP_CTL)

[SetFanControlByRamFan1p5](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\FanTable\MyFanTableCtrl.cs)
控制 AP 侧风扇管理的开关：

`csharp
if (status) {
    // 检查风扇表是否有效
    EcCtrl.Read(3840, ref b3); EcCtrl.Read(3841, ref b4);
    if (b3 == 0 && b4 == 0) b5 = 0; else b5 = 4;
} else b5 = 0;
EcCtrl.Write(1990, (b & 0xFB) + b5);  // 0xFB 清除 bit2
`

| 值 | 含义 |
|----|------|
| bit2=1 | AP 侧风扇管理使能 |
| bit2=0 | BIOS 风扇管理 |

### EC[1923..1925] — 当前 PL 值

| 地址 | 常量名 | 含义 |
|------|--------|------|
| 1923 | ADDR_PL1_SETTING_VALUE | 当前 PL1 功率限制 |
| 1924 | ADDR_PL2_SETTING_VALUE | 当前 PL2 功率限制 |
| 1925 | ADDR_PL4_SETTING_VALUE | 当前 PL4 功率限制 |

通过 [MyFanManager.SetPL1/2/4Value](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFanManager.cs) 写入。

#### 各模式默认 PL 值（来自实测 dump）

| 模式 | PL1 | PL2 | PL4 | EC 默认值来源 |
|------|-----|-----|-----|---------------|
| Gaming | 45 | 45 | 50 | 1840-1842 |
| Office | 25 | 25 | 30 | 1844-1846 |
| Turbo (AC) | 73 | 73 | 90 | 代码硬编码 |
| Turbo (DC) | 0 | 0 | 0 | 代码硬编码 |

**AMD 平台的特殊行为：**
- 非 Custom 模式: SetPL1Value(0) — 全部写 0，由 BIOS 管理 PL
- Custom 模式: 写入 AmdSPL/SPPT/FPPT 来自 currentProfile.CPU

### EC[1989] bit7 — FanControlRespective (ADDR_FANCTL_RESP)

[SetEcFanControlRespective](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\FanTable\FanTable_Manager1p5.cs)：

`csharp
if (bEnable) EC[1989] |= 0x80; else EC[1989] &= 0x7F;
`

控制 CPU/GPU 风扇是否分离控制。设置为 1 时，CPU 和 GPU 各自按独立风扇曲线运行。

### EC[3840..3935] — 风扇表（6 组 × 16 级）

| EC 范围 | 内容 | 写入来源 |
|---------|------|----------|
| 3840-3855 | CPU UpT | SetEcFanTable (CML) |
| 3856-3871 | CPU DownT | 同上 |
| 3872-3887 | CPU Duty (×2) | 同上 |
| 3888-3903 | GPU UpT | 同上 |
| 3904-3919 | GPU DownT | 同上 |
| 3920-3935 | GPU Duty (×2) | 同上 |

CML 格式的 [SetEcFanTable](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\FanTable\FanTable_Manager1p5_CML.cs)：
`csharp
for i=0..15:
    EC[3840+i] = fantable.CPU[i+1].UpT (最后一点=0xFF)
    if i<15: EC[3856+i+1] = fantable.CPU[i].DownT
    EC[3872+i] = fantable.CPU[i].Duty * 2  // duty 在 EC 中是百分比×2
    // GPU 同理偏移到 3888/3904/3920
`

## 完整切换序列

### 启动/初始化 (GCU EnableByService)

[MyFanManager_RamFan1p5.EnableByService](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\MyFanManager_RamFan1p5.cs)：

1. 读取硬件能力：GetTurboModeSupport()、GetDefaultMode()
2. LoadProfileAll() — 从 JSON 加载所有配置
3. syncBiosSettings() — 写入 UEFI NVRAM + EC ApExistFlag
4. Init(true) — 调用 RefreshCurrentProfile() → SetUserProfile()

### SetUserProfile 完整序列

[SetUserProfile](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\MyFanManager_RamFan1p5.cs)：

`
1. SetFanMode(mode)
   ├── FanTable.CustomerModeLightOn()/Off()  → EC[1831] bit6
   ├── EC[1873] = mode_value
   └── EC[1830] bit7 = 1 (Custom) / 0 (other)

2. SetFanTable(tableName)
   ├── SetFanControlByRamFan1p5(false) → EC[1990] &= ~4
   ├── SetEcFanControlRespective()     → EC[1989] bit7
   ├── SetEcFanTable()                 → EC[3840..3935]
   └── SetFanControlByRamFan1p5(true)  → EC[1990] |= 4 (if fan table valid)

3. SetPL124Tau(PL1, PL2, PL4)  → EC[1923..1925]
4. SetCpuTccOffset()           → EC[2008..2010]
5. SetFanSwitchSpeed()         → EC[1927]
`

### 停止/禁用 (Disable)

[Disable](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\MyFan\MyFanManager_RamFan1p5.cs)：

`
1. FanTable.DisableByService() → EC[1990] &= ~4
2. SetFanMode(m_DefaultMode)   → EC[1873] = default (0 或 160)
3. SetCpuTccOffset(0, false)
4. SetFanSwitchSpeedEnabled(0) → EC[1927] = 0
`

### 独立模式切换序列（推荐，无 FanBoost）

基于 SetUserProfile 简化，去掉了 fan table 内部依赖：

`
# 1. ApExistFlag — 告诉 EC 上层活跃
EC[1857] |= 0x01

# 2. 风扇表 toggle（匹配 SetFanTable）
EC[1990] &= ~0x04                # disable
写风扇曲线到 EC[3840..3935]      # 6组×16字节
EC[1990] |= 0x04                 # re-enable (if fan table valid)

# 3. 自定义/非自定义标记
if mode == 3 (Custom):
    EC[1831] |= 0x40             # CustomerModeLightOn
else:
    EC[1831] &= ~0x40

# 4. PL 值
EC[1923..1925] = PL 值

# 5. 模式 (最后写入 — 触发 EC 状态切换)
EC[1873] = mode_value            # Gaming=0, Office=160, Turbo=16, Custom=0

# 6. Custom 标志 (必须在 mode byte 之后!)
if mode == 3 (Custom):
    EC[1830] |= 0x80
else:
    EC[1830] &= ~0x80
`


### EC[1927] — Fan Switch Speed

[SetFanSwitchSpeed] controls fan speed transition time (slew rate).

`csharp
if (bApExist) {
    int num = value / 100;           // value in centiseconds
    if (num > 0)
        EcCtrl.Write(1927, num | 0x80);  // bit7=enable, bits 0-6 = seconds
} else {
    EcCtrl.Write(1927, 0);           // disabled → instant jump
}
`

Format:

| EC[1927] | Meaning |
|----------|---------|
| 0 | Disabled, fan changes instantly |
| 0x81 | 1 second transition (minimum, value=100) |
| 0x82 | 2 second transition (value=200) |
| 0x83 | 3 second transition (value=300) |

Call chain: SetUserProfile() → SetFanSwitchSpeedEnabled(1) → SetFanSwitchSpeed(profile.FanSwitchSpeed, true) → EC[1927]

Disable() clears it: SetFanSwitchSpeed(0, false) → EC[1927]=0.



### EC[1927] -- Fan Switch Speed (ADDR_L2_PWM_DEFAULT_MYFAN3)

[SetFanSwitchSpeed] controls fan speed transition time (slew rate).
Prevents fans from oscillating due to temperature fluctuations.

```csharp
if (bApExist) {
    int num = value / 100;           // value in centiseconds (1/100s)
    if (num > 0)
        EcCtrl.Write(1927, num | 0x80);  // bit7=1=enable, low7bits=seconds
} else {
    EcCtrl.Write(1927, 0);           // disabled -> instant response
}
```

Format:

| EC[1927] | Meaning |
|----------|---------|
| 0 | Disabled - fan responds instantly |
| 0x81 | 1 second transition (minimum, value=100) |
| 0x82 | 2 second transition (value=200) |
| 0x83 | 3 second transition (value=300) |

Call chain: SetUserProfile() -> SetFanSwitchSpeedEnabled(1) -> SetFanSwitchSpeed(profile.FanSwitchSpeed, true) -> EC[1927]

Disable() clears it: SetFanSwitchSpeed(0, false) -> EC[1927]=0.

## UEFI NVRAM 变量

除了 EC 寄存器，GCU 还通过 [UEFI_Firmware.dll 的 WriteUefi](D:\UserData\Desktop\gcu\reverseCS\GCUService_decompiled\GCUService\MyControlCenter\NvramVariable.cs)
写入 UEFI NVRAM struct。Struct 中包含：

| 字段 | 作用 |
|------|------|
| ApExistFlag | AP 在线标记（**EC 1857 的 UEFI 副本**） |
| ApUseFlag | AP 使用标记 |
| PowerMode | 当前电源模式 |
| OemDisplayMode | 显示模式 |
| ACRecoveryStatus | AC 恢复状态 |
| OverClockRecoveryFlag | OC 恢复标记 |

实践证明 **EC 1857 的 ApExistFlag 足够使 BIOS 交出控制权**，不需要碰 UEFI NVRAM。

## 温度传感器来源

EC 风扇控温（UpT/DownT 比较）是 **EC 固件内部**完成的，不通过可读的 EC 寄存器。
Windows 软件读的温度是另一条路径：

| 显示 | 读取方式 | 来源文件 |
|------|----------|----------|
| CPU 温度 | Windows PerformanceCounter "Thermal Zone Information" -> "Temperature" - 273.2 | CPUInfo.cs |
| GPU 温度（NVIDIA） | NVIDIA NVAPI GetNVTemperature() | GPUTypeClass.cs |
| GPU 温度（核显本） | 无（GPUTypeClass 空实现） | GPUTypeClass.cs |

风扇表的两组曲线对应的温度源：

| 曲线 | EC 地址 | 传感器 | 对应风扇 |
|------|----------|--------|----------|
| CPU (EC[3840-3887]) | UpT/DnT/Duty | **CPU 内部 DTS (PECI)** | 1 号风扇 (EC[1883]) |
| GPU (EC[3888-3935]) | UpT/DnT/Duty | EC 固件第二路温度输入 | 2 号风扇 (EC[1884]) |

对于核显本（无 dGPU），"GPU 曲线" 的实际温度源可能是：
1. 主板 VRM/供电温度传感器
2. PCH (芯片组) 温度
3. CPU 同一封装的不同测温点

这部分取决于 EC 固件实现，反编译的 C# 代码中不可见。可通过实验确认：
设两组不同的 Duty 曲线，观察两个风扇在不同负载下的转速差异。

_注意：风扇独立输出（--separate）只在 EC[1989] bit7=1 时生效，
否则两个风扇都走 CPU 曲线。_

## 实现参考

- [ec_switch_mode.py](D:\UserData\Desktop\gcu\tools\ec_switch_mode.py) — Windows/Linux 双平台实现
- [ec_rw.py](D:\UserData\Desktop\gcu\tools\ec_rw.py) — 底层 EC 读写工具
