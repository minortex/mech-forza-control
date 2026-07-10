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

这些寄存器可读出当前功率限制状态，但在本工具的模式切换里不直接写入。

当前结论：

- Office / Gaming / Turbo 三个固定档只写模式控制字节 EC[1873]，SPL/SPPT/FPPT 由 EC/BIOS 按档位自动确定。
- 固定档对应关系是 25W / 45W / 65W，通常可理解为 SPL=SPPT=TDP，FPPT=TDP+5，但不应在配置文件中维护这些值，也不应在切换固定档时主动写 EC[1923..1925]。
- Custom 模式同样通过 25/45/65 档位选择 EC[1873] 的模式字节；除非后续确认平台需要 AP 侧覆盖 PL，否则不要写 EC[1923..1925]。
- 如果需要真正自定义 SPL/SPPT/FPPT，使用 `ryzenadj` 直接改 SMU。`ryzenadj` 修改后 EC[1923..1925] 不会随之变化；这三个 EC 寄存器只能作为切换档位/模式后的 EC 侧读出值，不能当作 ryzenadj 当前限制值。

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

3. 固定档不写 EC[1923..1926]，PL/TCC 由 EC/BIOS 按 EC[1873] 档位管理
4. Custom 模式可按需 SetCpuTccOffset() → EC[1926]
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

## EC[1926] — TCC 温度目标/使能 (ADDR_TCC_OFFSET)

`SetCpuTccOffset(int value, bool bApExist)` 控制 CPU 的 TCC 目标/使能位。
反编译得到的 RamFan1p5 实现为：

```csharp
if (bApExist)
    EcCtrl.Write(1926, (byte)(value | 128));
else
    EcCtrl.Write(1926, 0);
```

### 调用链

```
SetUserProfile()
  └── if TccOffsetSwitch == 1:
        SetCpuTccOffset(AmdTccTarget, true)    → EC[1926] = AmdTccTarget | 0x80
      else:
        SetCpuTccOffset(0, false)               → EC[1926] = 0
```

AMD 平台走 `CPU.AmdTccTarget`，默认值常见为 `95`，写入 EC 时应为 `95 | 0x80 = 0xDF`。
Intel/非 AMD 路径使用 `CPU.TccOffset`，默认常见为 `5`。两条路径复用同一个 EC[1926]，但数值语义不同。

### 寄存器格式

| EC[1926] | 含义 |
|----------|------|
| 0x00 | 禁用 AP 侧 TCC 设置 |
| 0x80 | 启用位为 1，但 low7bits=0；这是无效/危险状态 |
| 0x85 | 启用，值为 5（常见 Intel offset 默认） |
| 0xDF | 启用，值为 95（常见 AMD AmdTccTarget） |

### 已知问题

bit7 不是“永远不能置 1”，而是 **不能在 value=0 时写成 0x80**。
正确规则是：

- 禁用：写 `0x00`
- 启用：写 `value | 0x80`
- Custom 模式下限制 `value` 为 `0..100`，避免 EC 异常

历史错误：默认 `tcc=0` 时写 `0x80`，会让 EC 进入无效 TCC 状态，可能触发 CPU 锁定在最低 P-State (如 544 MHz)。

对应 ryzenadj 参数：`--tctl-temp=95` 在 AMD 路径下更接近 `EC[1926] = 0xDF`，而不是 offset 10。

---

## EC[1831] bit7 — PL4 双倍标志 (ADDR_SUPPORT_CPU_PL4_DOUBLE_FLAG)

`IsSupportCPUPL4DoubleFlag()` 读取 EC[1831] bit7 决定 PL4 写入值是否翻倍：

```csharp
EcCtrl.Read(1831, ref b);
if ((b & 0x80) == 0x80)
    g_SupportCPUDoubleFlag = 1;   // PL4 需要 ×2
else
    g_SupportCPUDoubleFlag = 0;   // PL4 直接写入
```

写入 PL4 时的处理：

```csharp
// MyFanManager (base):
if (g_SupportCPUDoubleFlag == 1)
    EcCtrl.Write(1925, (byte)(PL4 >> 1));  // 写入值减半，EC 固件自动翻倍
else
    EcCtrl.Write(1925, (byte)PL4);

// MyFanManager_RamFan1p5 (subclass):
IsSupportCPUPL4DoubleFlag();
EcCtrl.Write(1925, (byte)value);  // RamFan1p5 没有 /2，但 value 本身已正确
```

实测本机 (Mechrevo 7735H) **EC[1831] bit7 = 0**，PL4 直接写入不需要 ÷2。

---

## EC[1875..1876] — VRM 电流限制 (ADDR_CPU_VRM_CURRENT_LIMIT)

`SetCpuVrmCurrentLimit(int limit, int maximum)` 在 Custom 模式下当功率较高时设置：

```csharp
if (AmdSPL >= 75 || AmdSPPT >= 75) {
    EcCtrl.Write(1875, (byte)limit);   // = 65A
    EcCtrl.Write(1876, (byte)maximum); // = 120A
}
```

| EC 地址 | 字段 | 典型值 |
|---------|------|--------|
| 1875 | CPU VRM 持续电流限制 | 65A |
| 1876 | CPU VRM 峰值电流限制 | 120A |

仅 AMD Custom 模式下触发，保护 CPU 供电模块。

---

## EC[1926..1930] — 高级 PWM 默认值（旧路径/重叠区）

旧 `MyFanManager.GetFanTablePWMDefault()` 从 EC 读取 5 级 PWM 默认值：

```csharp
EcCtrl.Read(1926, ref b);   // PWM_L1 默认值 (最低档)
EcCtrl.Read(1927, ref b2);  // PWM_L2
EcCtrl.Read(1928, ref b3);  // PWM_L3
EcCtrl.Read(1929, ref b4);  // PWM_L4
EcCtrl.Read(1930, ref b5);  // PWM_L5 (最高档)
```

若全为 0，则使用硬编码默认值 `[60, 70, 80, 90, 100]`。

**注意：** 这是旧 MyFan3 路径中的命名/读取逻辑。RamFan1p5 的 CPU TCC 控制也使用 EC[1926]，因此不要把 EC[1926] 当作普通 PWM 默认值写入。当前工具不依赖这组 PWM 默认值，模式切换时也不写 EC[1926..1930] 作为 PWM 默认表。

---

## 寄存器汇总表

| EC 地址 | 名称 | 类型 | 描述 |
|---------|------|------|------|
| 1830 | OEM9 | flags | bit7=1 Custom 模式活动 |
| 1831 | OEM10 | flags | bit6=1 CustomerModeLight, bit7=1 PL4双倍标志 |
| 1857 | AP_OEM | flags | bit0=1 ApExist (AP在线) |
| 1873 | MAFAN_CTL | u8 | 风扇控制模式字节 |
| 1875 | CPU VRM Limit | u8 | VRM 持续电流限制 |
| 1876 | CPU VRM Max | u8 | VRM 峰值电流限制 |
| 1922 | CFG Byte | flags | bit2 Qkey定义, bit4 默认模式, bit3 Fan3支持 |
| 1923 | PL1 | u8 | 当前 PL1 功率限制 |
| 1924 | PL2 | u8 | 当前 PL2 功率限制 |
| 1925 | PL4 | u8 | 当前 PL4 功率限制 |
| 1926 | TCC Target/Enable | u8 | 0=禁用; bit7=启用; low7bits=目标/偏移值。固定档不写，仅 Custom 需要时写 |
| 1927 | Fan Switch Speed | u8 | bit7=使能, low7bits=秒数 |
| 1928-1930 | PWM Defaults | u8×3 | 3档PWM默认值 (共5档, 1926-1930) |
| 1931 | GPU D-State | u8 | bits 0-2 = GPU电源状态 |
| 1989 | FANCTL_RESP | flags | bit7=1 GPU独立风扇控制 |
| 1990 | AP_CTL | flags | bit2=1 AP侧风扇管理使能 |
| 3840-3887 | CPU Fan Table | 16×3 | CPU UpT/DnT/Duty 风扇曲线 |
| 3888-3935 | GPU Fan Table | 16×3 | GPU UpT/DnT/Duty 风扇曲线 |
