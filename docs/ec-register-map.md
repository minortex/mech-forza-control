# EC 寄存器功能总表

> 本文档汇总所有已探明的 EC 寄存器地址和位定义。适用于机械革命（Mechrevo）
> 无界 14x / Forza 系列（AMD 7735H / 8845HS 平台）。
>
> **阅读约定**：
> - 地址以十进制为主，括号内标注十六进制
> - 位布局表中 `?` 表示未知/未使用，`-` 表示该 bit 已知无功能
> - R = 只读，R/W = 可读写

## 数据来源

| 文件 | 说明 |
|------|------|
| `ref/GCUService_decompiled/GCUService/Define/ECSpec.cs` | 官方常量名、地址、位枚举（最权威） |
| `ref/GCUService_decompiled/GCUService/Define/RamFan1p5_ECSpec.cs` | RamFan1p5 风扇表地址常量 |
| `ref/wujie14xCC.go` | 社区 Go 实现，交叉验证地址 |
| `docs/llm/ec-mode-switch.md` | 模式切换寄存器逆向记录 |
| `docs/llm/ec-setting-controls.md` | 设置类功能逆向记录 |
| `docs/llm/ec-battery-charging-findings.md` | 电池充电模式逆向记录 |
| `docs/keyboard-backlight.md` | 键盘背光位编码 |
| `src/ec/config.py` | 工具当前使用的地址 |

---

## 一、电池数据寄存器（只读，0x04xx 区域）

电池相关寄存器位于十进制 1026-1195，为 EC 燃料计暴露的只读数据。
多字节值为 Little-Endian 16-bit word。

### 设计参数

| 地址 | 十六进制 | 官方常量名 | 宽度 | 单位 | 说明 |
|------|----------|------------|------|------|------|
| 1026-1027 | `0x0402` | `ADDR_EC_BIF_DC_BYTE1/2` | word LE | mAh | 设计容量 |
| 1028-1029 | `0x0404` | — | word LE | mAh | 满充容量（last full capacity） |
| 1032-1033 | `0x0408` | `ADDR_EC_BIF_DV_BYTE1/2` | word LE | mV | 设计电压 |

### 实时状态

| 地址 | 十六进制 | 官方常量名 | 宽度 | 单位 | 说明 |
|------|----------|------------|------|------|------|
| 1076-1077 | `0x0434` | `ADDR_EC_BST_BPR_BYTE1/2` | word LE | mA | 放电电流（正值=放电） |
| 1078-1079 | `0x0436` | `ADDR_EC_BST_BRC_BYTE1/2` | word LE | mAh | 剩余容量 |
| 1080-1081 | `0x0438` | `ADDR_EC_BST_BPV_BYTE1/2` | word LE | mV | 电池电压 |
| 1186 | `0x04A2` | `ecBt1Temperature` | word LE | 0.1K | 温度，换算: `(raw - 2732) / 10` °C |
| 1190-1191 | `0x04A6` | `ADDR_EC_BT1CycleCount_BYTE1/2` | word LE | 次 | 循环次数 |
| 1195 | `0x04AB` | `ecBt1RSOC` | byte | % | 相对充电状态 (0-100) |

### 其他只读信息

| 地址 | 十六进制 | 官方常量名 | 说明 |
|------|----------|------------|------|
| 1108 | `0x0454` | `ecOEM_EC_VER` | EC 固件版本 |
| 1110 | `0x0456` | `ADDR_SystemID` | 系统 ID |
| 1115 | `0x045B` | `ADDR_SILENTMODE_STATUS_BYTE` | 静音模式状态 |
| 1124-1125 | `0x0464` | `ADDR_EC_MAIN_FAN_RPM_BYTE1/2` | 主风扇 RPM（hi\*256+lo） |
| 1126 | `0x0466` | `ADDR_EC_BIOS_INFO5` | BIOS 信息 5 |
| 1131-1132 | `0x046B` | `ADDR_EC_SECOND_FAN_RPM_BYTE2/1` | 副风扇 RPM（低位在 1131，高位在 1132） |
| 1142 | `0x0476` | `BIOSFuncReg` | BIOS 功能寄存器 |
| 1149 | `0x047D` | `ecOEM_SUB_VER2` | EC 子版本 2 |
| 1168 | `0x0490` | `ecPowSource` | 电源来源 |
| 1172 | `0x0494` | `ADDR_BATTERY_ALERT_BYTE` | 电池告警 |
| 1183 | `0x049F` | `ADDR_BIOS_INFO_3_BYTE` | BIOS 信息 3 |

---

## 二、控制寄存器（读写，0x07xx 区域）

控制寄存器位于十进制 1798-2043，是模式切换、风扇曲线、功率限制的主要操作区域。

### EC[1798] — AP BIOS 控制字节

`ADDR_AP_BIOS_CONTROL_BYTE` R/W

位定义未完全探明。

### EC[1830] — AP OEM 字节 9

`ADDR_AP_OEM_BYTE9` R/W，RMW 写入

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| Custom 标志 | ? | ? | ? | AC Recovery | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit3 | `0x08` | AC Recovery | 来电自动开机。BIOS 不支持 NVRAM 时的 fallback 路径；支持时走 NVRAM `ACRecoveryStatus` |
| bit7 | `0x80` | Custom 模式标志 | `1` = Custom 模式活动。**必须在 EC[1873] 之后写入**，否则 EC 可能复位此寄存器 |

### EC[1831] — AP OEM 字节 10

`ADDR_AP_OEM_BYTE10_CUSTOM_LIGHT_TEST` / `ADDR_ESHUTTER_STATUS` / `ADDR_CPU_DOUBLE_FLAG_SUPPORT` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| PL4 双倍标志 | Custom 指示灯 | ? | ? | ? | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit6 | `0x40` | CustomerModeLight | `1` = Custom 模式指示灯亮 |
| bit7 | `0x80` | PL4 双倍标志 | `1` = PL4 值需 x2 写入 EC。本机实测为 `0`（不需要翻倍） |

### EC[1856] — 项目 ID

`ADDR_PROJECT_ID_BYTE` R

只读，项目标识。

### EC[1857] — AP OEM 字节

`ADDR_AP_OEM_BYTE` / `ADDR_FAN_ALERT_BYTE` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | ? | ? | ? | ? | ApExistFlag |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit0 | `0x01` | ApExistFlag | **最关键标志**。`1` = AP 在线，EC 接受模式指令；`0` = BIOS 接管。不设此位则 EC 不执行任何模式切换。每次操作前必须先置 `1` |

### EC[1858] — 支持字节 5

`ADDR_SUPPORT_BYTE5` R

位定义未完全探明。

### EC[1859-1863] — MyFan2 PWM / TGP DynamicBoost（地址复用）

同一地址被两个路径复用：

| 地址 | MyFan2 常量名 | TGP 常量名 |
|------|---------------|------------|
| 1859 | `ADDR_MYFAN2_L1_PWM` | `ADDR_ConfigurableTGP_DynamicBoost_CTRL_BYTE` |
| 1860 | `ADDR_MYFAN2_L2_PWM` | `ADDR_ConfigurableTGP_VALUE` |
| 1861 | `ADDR_MYFAN2_L3_PWM` | `ADDR_DynamicBoost_TotalProcessingPowerTarget_VALUE` |
| 1862 | `ADDR_MYFAN2_L4_PWM` | `ADDR_DynamicBoost_MaxinumTGP_VALUE` |
| 1863 | `ADDR_MYFAN2_L5_PWM` | — |

均为 R/W 字节值寄存器。

### EC[1864] — LightBar 控制字节

`ADDR_LIGHTBAR_CONTROL_BYTE` R/W，`RGBLightBarCtrlByteFlag` 枚举

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| Welcome 灯模式 | Breath/ModernStandby | LB10 按键 | LB10 无按键 | S3 待机 | S0 唤醒 | 节能模式 | ApExit |

| Bit | 掩码 | 功能 |
|-----|------|------|
| bit0 | `0x01` | ApExit |
| bit1 | `0x02` | PowerSaveMode |
| bit2 | `0x04` | Switch_S0 |
| bit3 | `0x08` | Switch_S3 |
| bit4 | `0x10` | LB10NoKey |
| bit5 | `0x20` | LB10KeyPress |
| bit6 | `0x40` | Switch_Breath_ModernStandby |
| bit7 | `0x80` | WelcomeLightMode |

### EC[1865-1867] — LightBar RGB 分量

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1865 | `ADDR_REDBAR_CONTROL_BYTE` | 红色分量，R/W |
| 1866 | `ADDR_GREENBAR_CONTROL_BYTE` | 绿色分量，R/W |
| 1867 | `ADDR_BLUEBAR_CONTROL_BYTE` | 蓝色分量，R/W |

### EC[1868] — OEM 服务项目 ID

`ADDR_OEMSERVICE_PROJECT_ID_BYTE` R

### EC[1870] — BIOS OEM 字节

`ADDR_BIOS_OEM_BYTE` R/W，RMW 写入

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | Fn Lock | ? | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit4 | `0x10` | Fn Lock | `1` = Fn 键锁定，`0` = 解锁 |

### EC[1873] — 风扇控制模式字节

`ADDR_MAFAN_CONTROL_BYTE` R/W。这是一个**字节值寄存器**，不同值代表不同模式。

**位分解**

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| User_Fan | FanBoost | 模式高位 | 模式低位 | 等级 bit3 | 等级 bit2 | 等级 bit1 | 等级 bit0 |

- `bit7` (User_Fan): `1` = 自定义风扇模式
- `bit6` (FanBoost): `1` = FanBoost 叠加，与底层模式 OR 组合
- `bit5:4` (模式类型): `00` = Normal/Turbo 基值，`10` = Turbo，`01` 不用，`11` 不用（此处仅为高位=0 时 Turbo=10 的特例）
- `bit3:0` (等级): 在 User_Fan 模式下表示 1-5 级

**`MyFanCTLByteFlag` 枚举——所有已知值**

| 值 | 十六进制 | 名称 | 位模式 | 对应模式 |
|----|----------|------|--------|----------|
| 0 | `0x00` | `Normal_Mode` | `0000_0000` | Gaming 45W |
| 16 | `0x10` | `Turbo_Mode` | `0001_0000` | Turbo 65W |
| 64 | `0x40` | `FanBoost_Mode` | `0100_0000` | FanBoost（Gaming 基值） |
| 80 | `0x50` | — | `0101_0000` | Turbo + FanBoost |
| 128 | `0x80` | `User_Fan_Mode` | `1000_0000` | 自定义风扇基值 |
| 129 | `0x81` | `User_Fan_Level1` | `1000_0001` | 自定义 1 级 |
| 130 | `0x82` | `User_Fan_Level2` | `1000_0010` | 自定义 2 级 |
| 131 | `0x83` | `User_Fan_Level3` | `1000_0011` | 自定义 3 级 |
| 132 | `0x84` | `User_Fan_Level4` | `1000_0100` | 自定义 4 级 |
| 133 | `0x85` | `User_Fan_Level5` | `1000_0101` | 自定义 5 级 |
| 160 | `0xA0` | `User_Fan_HiMode` | `1010_0000` | Office 25W |
| 224 | `0xE0` | — | `1110_0000` | Office + FanBoost |

**模式解码——需结合 EC[1830] bit7**

| EC[1873] | EC[1830] bit7 | 模式 |
|----------|---------------|------|
| `0xA0` | 0 | Office |
| `0x00` | 0 | Gaming |
| `0x10` | 0 | Turbo |
| `0xA0` | 1 | Custom (Office 档) |
| `0x00` | 1 | Custom (Gaming 档) |
| `0x10` | 1 | Custom (Turbo 档) |

### EC[1875] — CPU VRM 持续电流限制

`ADDR_CPU_VRM_CURRENT_LIMIT_BYTE` R/W。字节值，单位 A。典型 65A。
仅 AMD Custom 模式下高功率时写入。

### EC[1876] — CPU VRM 峰值电流限制

`ADDR_CPU_VRM_MAXI_CURRENT_LIMIT_BYTE` R/W。字节值，单位 A。典型 120A。

### EC[1883] — 主风扇 Duty 读数

`ADDR_EC_MAIN_FAN_L_DUTY_BYTE` R。字节值，`value / 2` ≈ 百分比。

### EC[1884] — 副风扇 Duty 读数

`ADDR_EC_MAIN_FAN_R_DUTY_BYTE` R。字节值，`value / 2` ≈ 百分比。

### EC[1885] — 触发字节 2

`ADDR_TRIGGER_BYTE2` R/W。位定义未完全探明。

### EC[1893] — 支持字节 1（硬件能力）

`ADDR_SUPPORT_BYTE1` R，`SupportByteOneFlag` 枚举

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| FanBoost | LightBar | WinLock | ShortCut | MacroKey | OverClock | GPS | 飞行模式 |

| Bit | 掩码 | 功能 |
|-----|------|------|
| bit0 | `0x01` | AirplaneMode |
| bit1 | `0x02` | GPSSwitch |
| bit2 | `0x04` | OverClock |
| bit3 | `0x08` | MacroKey |
| bit4 | `0x10` | ShortCutKey |
| bit5 | `0x20` | WinLockKey |
| bit6 | `0x40` | LightBar |
| bit7 | `0x80` | FanBoost |

### EC[1894] — 支持字节 2（硬件能力）

`ADDR_SUPPORT_BYTE2` R，`SupportByteTwoFlag` 枚举

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | MyBat | ? | ? | ? | RGB 键盘 | USB 充电 | 静音模式 |

| Bit | 掩码 | 功能 |
|-----|------|------|
| bit0 | `0x01` | SilentMode |
| bit1 | `0x02` | USBChargerMode |
| bit2 | `0x04` | RGBKeyBoard |
| bit6 | `0x40` | MyBat（电池保护模式） |

### EC[1895] — 触发字节

`ADDR_TRIGGER_BYTE` R/W，`TriggerByteFlag` 枚举。**被多个功能复用，写入必须 RMW。**

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| RGB 键盘欢迎 | RGB Logo | RGB 键盘 | USB 充电/E-Shutter | 静音/E-Shutter | FanBoost | LightBar | Win Lock |

| Bit | 掩码 | 功能 | 写入方式 |
|-----|------|------|----------|
| bit0 | `0x01` | WinLock_Trigger | toggle：先清后置 bit0 |
| bit1 | `0x02` | LightBar_Trigger | — |
| bit2 | `0x04` | FanBoost_Trigger | — |
| bit3 | `0x08` | SilentMode_Trigger / E-Shutter Camera_On bit3 | — |
| bit4 | `0x10` | USBCharger_Trigger / E-Shutter Camera_Off | 直接设置/清除 |
| bit5 | `0x20` | RGBKeyboard_Trigger | — |
| bit6 | `0x40` | RGBLogo_Trigger | — |
| bit7 | `0x80` | RGBKeyboardWelcome_Trigger | — |

E-Shutter 复用 bit3:4：`Camera_Off = 0x10` (bit4)，`Camera_On = 0x18` (bit3+bit4)。

### EC[1896] — 状态字节

`ADDR_STAUTS_BYTE` R（EC 写入，AP 只读），`StatusByteOneFlag` 枚举

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | 电池保护 | MacroKey | FanBoost | 呼吸灯 | Win Lock |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit0 | `0x01` | WinLock | `1` = 锁定 |
| bit1 | `0x02` | BreathLed | `1` = 呼吸灯亮 |
| bit2 | `0x04` | FanBoost | `1` = FanBoost 活动 |
| bit3 | `0x08` | MacroKey | `1` = 宏键活动 |
| bit4 | `0x10` | MyBatPowerBat | `1` = 电池保护活动 |

**不要把状态位当控制位写入。** Win 锁通过 EC[1895] bit0 触发，EC 自动更新此寄存器。

### EC[1897-1903] — RGB 键盘颜色

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1897 | `ADDR_RGBKB_LEVEL_R` | 红色分量，R/W |
| 1898 | `ADDR_RGBKB_LEVEL_G` | 绿色分量，R/W |
| 1899 | `ADDR_RGBKB_LEVEL_B` | 蓝色分量，R/W |
| 1900 | `ADDR_RGBKB_LEVEL_DEFAULT_R` | 默认红色，R |
| 1901 | `ADDR_RGBKB_LEVEL_DEFAULT_G` | 默认绿色，R |
| 1902 | `ADDR_RGBKB_LEVEL_DEFAULT_B` | 默认蓝色，R |
| 1903 | `ADDR_RGBKB_MUSIC_NO` | 音乐模式编号，R/W。`0xFE` = 启用 RGB 音乐模式，`0x00` = 禁用 |

### EC[1905-1906] — ROM ID

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1905 | `ADDR_ROMID` | ROM ID 1，R |
| 1906 | `ADDR_ROMID2` | ROM ID 2，R |

### EC[1922] — BIOS OEM 字节 2

`ADDR_BIOS_OEM_BYTE2` / `Light_SetToChinaMode` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | 默认模式 | Fan3 支持 | Qkey 定义 | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit2 | `0x04` | Qkey 定义 | `0` = 模式切换，`1` = FanBoost |
| bit3 | `0x08` | Fan3 支持 | `1` = 支持三风扇 |
| bit4 | `0x10` | 默认模式标志 | — |

### EC[1923-1925] — 当前 PL 值

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1923 | `ADDR_PL1_SETTING_VALUE` | 当前 PL1 (SPL)，R |
| 1924 | `ADDR_PL2_SETTING_VALUE` | 当前 PL2 (sPPT)，R |
| 1925 | `ADDR_PL4_SETTING_VALUE` | 当前 PL4 (fPPT)，R |

字节值，固定档下由 EC/BIOS 自动管理，只读语义。如需真正自定义 PL，用 `ryzenadj`。

### EC[1926] — TCC 温度目标与使能

`ADDR_TimAP_TccOffset_Setting` R/W。被旧 MyFan3 路径复用为 `ADDR_L1_PWM_DEFAULT_MYFAN3`。

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| 使能 | 目标温度 bit6 | 目标温度 bit5 | 目标温度 bit4 | 目标温度 bit3 | 目标温度 bit2 | 目标温度 bit1 | 目标温度 bit0 |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit6:0 | `0x7F` | TCC 目标温度 | 有效范围 0-100（°C） |
| bit7 | `0x80` | 使能 | `1` = 启用 AP 侧 TCC 设置 |

**写入规则**

| 操作 | 写入值 | 说明 |
|------|--------|------|
| 禁用 | `0x00` | 清 bit7 |
| 启用，目标 N°C | `N | 0x80` | 如 95°C → `0xDF` (95 \| 0x80) |

**警告**：bit7=1 且 bit6:0=0（即写入 `0x80`）是无效/危险状态，可导致 CPU 锁定在最低频率。

### EC[1927] — 风扇切换速度

`ADDR_TimAP_FanSwitchSpeedT100mSec` R/W。被旧 MyFan3 路径复用为 `ADDR_L2_PWM_DEFAULT_MYFAN3`。

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| 使能 | step bit6 | step bit5 | step bit4 | step bit3 | step bit2 | step bit1 | step bit0 |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit6:0 | `0x7F` | step 值 | 每 step 约 2 秒 |
| bit7 | `0x80` | 使能 | `1` = 启用渐变控制 |

**已知值**

| 写入值 | 效果 |
|--------|------|
| `0x00` | EC 默认渐变，约 7s 完成 10% 变化 |
| `0x80` | 同 `0x00`（使能=1 但 step=0 走默认） |
| `0x81` | 启用 + 1 step ≈ 2s（工具默认值） |
| `0x83` | 启用 + 3 step ≈ 6s |

### EC[1928-1930] — MyFan3 PWM 默认值（旧路径）

EC[1926-1930] 在旧 MyFan3 路径中作为 5 级 PWM 默认值读取。RamFan1p5 模式下
EC[1926] 和 EC[1927] 已被复用，不要混用。

| 地址 | MyFan3 常量名 | RamFan1p5 用途 |
|------|---------------|----------------|
| 1926 | `ADDR_L1_PWM_DEFAULT_MYFAN3` | TCC 温度目标 |
| 1927 | `ADDR_L2_PWM_DEFAULT_MYFAN3` | 风扇切换速度 |
| 1928 | `ADDR_L3_PWM_DEFAULT_MYFAN3` | — |
| 1929 | `ADDR_L4_PWM_DEFAULT_MYFAN3` / `ADDR_L1_PWM_DEFAULT_MYFAN2` | — |
| 1930 | `ADDR_L5_PWM_DEFAULT_MYFAN3` / `ADDR_L2_PWM_DEFAULT_MYFAN2` | — |

### EC[1931] — GPU D-State / MyFan3 GPU 设置

`ADDR_MYFAN3_GPU_SETTING` / `ADDR_L3_PWM_DEFAULT_MYFAN2` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | ? | GPU D-State bit2 | GPU D-State bit1 | GPU D-State bit0 | ? |

### EC[1932] — 键盘背光控制

`ADDR_SINGLEKBL_ENABLE` / `ADDR_AP_OEM_BYTE2` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| 等级 bit2 | 等级 bit1 | 等级 bit0 | 使能 | - | - | - | - |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit3:0 | — | 未使用 | — |
| bit4 | `0x10` | 使能位 | 写入时**必须为 1** |
| bit7:5 | `0xE0` | 亮度等级编码 | 3 bit，见下表 |

**亮度等级映射（bit7:5）**

| 等级 | bit7:5 | 亮度 | 说明 |
|------|--------|------|------|
| 0 | `000` | 关闭 | — |
| 1 | `011` | 最暗 | 不建议，会导致快捷键位错乱 |
| 2 | `001` | 暗 (Dim) | 快捷键循环低档 |
| 3 | `100` | 亮 | 不建议 |
| 4 | `010` | 最亮 (Bright) | 快捷键循环高档 |

亮度从亮到暗：`010` > `100` > `001` > `011` > `000`。
键盘快捷键只在等级 0/2/4 循环。等级 1 和 3 是中间值，切入后会导致 EC 位错乱，需切回 0 恢复。

### EC[1933] — MyFan2 PWM L5 默认值

`ADDR_L5_PWM_DEFAULT_MYFAN2` R/W

### EC[1934] — 支持字节 6

`ADDR_SINGLEKBL_SUPPORTPOWER` / `ADDR_SUPPORT_BYTE6` R

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | ? | 电池保护支持 | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit3 | `0x08` | 电池保护模式支持 | `1` = 硬件支持三档充电模式切换 |

### EC[1950-1952] — 风扇额外参数

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1950 | `ADDR_MYFANI_MIN_SPEED` | 最低风扇速度，R/W |
| 1951 | `ADDR_MYFANI_MIN_TEMP` | 最低温度阈值，R/W |
| 1952 | `ADDR_MYFANI_EXTRA_SPEED` | 额外风扇速度，R/W |

### EC[1955] — BIOS OEM 字节 3

`ADDR_BIOS_OEM_BYTE3` R

### EC[1956] — AP BIOS 字节

`ADDR_AP_BIOS_BYTE` R/W。QC 平台 Fn 锁 bit3，通用平台不使用。

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | ? | QC Fn Lock | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit3 | `0x08` | QC Fn Lock | QC 平台专用，本机不使用 |

### EC[1957] — AP OEM 字节 3

`ADDR_AP_OEM_BYTE3` R/W。位定义未完全探明。

### EC[1958] — 充电模式 / 触控板 LED

`ADDR_AP_OEM_BYTE4` R/W，RMW 写入

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | 充电模式 bit1 | 充电模式 bit0 | 触控板 LED | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit3 | `0x08` | 触控板 LED | `1` = 亮。RMW 时必须保留 |
| bit4 | `0x10` | 充电模式 bit0 | 见充电模式表 |
| bit5 | `0x20` | 充电模式 bit1 | 见充电模式表 |

**充电模式表（bit5:4）**

| bit5 | bit4 | 模式 | 充电上限 |
|------|------|------|----------|
| 0 | 0 | High (Performance) | 100% |
| 0 | 1 | Middle (Balanced) | ~80% |
| 1 | 0 | Low (Health) | ~60% |
| 1 | 1 | 未使用 | — |

### EC[1959-1962] — BatterySaver 默认 PL 值

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1959 | `ADDR_BATTERYSAVER_PL1_DEFAULT_VALUE` | BatterySaver PL1 默认值，R |
| 1960 | `ADDR_BATTERYSAVER_PL2_DEFAULT_VALUE` | BatterySaver PL2 默认值，R |
| 1961 | `ADDR_BATTERYSAVER_PL4_DEFAULT_VALUE` | BatterySaver PL4 默认值，R |
| 1962 | `ADDR_BATTERYSAVER_D_DEFAULT_VALUE` | BatterySaver Duration 默认值，R |

### EC[1963] — CCI 模式索引

`ADDR_MyFanCCI_Mode_Index` R/W

### EC[1968-1970] — CCI 模式 Profile

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1968 | `ADDR_MyFanCCI_Mode_Profile1` | Profile 1，R/W |
| 1969 | `ADDR_MyFanCCI_Mode_Profile2` | Profile 2，R/W |
| 1970 | `ADDR_MyFanCCI_Mode_Profile3` | Profile 3，R/W |

### EC[1977] — 充电上限百分比

`ADDR_BATTERY_CHARGE_LIMIT_UP` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| 保留 | 上限 bit6 | 上限 bit5 | 上限 bit4 | 上限 bit3 | 上限 bit2 | 上限 bit1 | 上限 bit0 |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit6:0 | `0x7F` | 充电上限 % | `0` = 默认 100%，1-100 = 实际百分比 |
| bit7 | `0x80` | 保留 | RMW 时保留原值 |

### EC[1989] — AP OEM 字节 5

`ADDR_AP_OEM_BYTE5` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| 独立风扇 | ? | ? | ? | ? | ? | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit7 | `0x80` | FanControlRespective | `1` = CPU/GPU 风扇独立控制（`--separate`），`0` = 同步 |

### EC[1990] — AP OEM 字节 6

`ADDR_AP_OEM_BYTE6` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| ? | ? | ? | ? | ? | AP 风扇管理使能 | ? | ? |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit2 | `0x04` | AP 风扇管理使能 | `1` = AP 侧风扇曲线生效；`0` = BIOS 接管 |

**风扇表刷新序列**：清 bit2 → 写 EC[3840..3935] → 置 bit2

### EC[1991-1992] — AP OEM 字节 7/8

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 1991 | `ADDR_AP_OEM_BYTE7` | R/W，位定义未探明 |
| 1992 | `ADDR_AP_OEM_BYTE8` | R/W，位定义未探明 |

### EC[1994] — BIOS OEM 字节 8

`ADDR_BIOS_OEM_BYTE8` R

### EC[1996] — 复合电源状态

`ADDR_COMPLEX_POWER_STATUS` R

### EC[2000] — 充电下限百分比

`ADDR_BATTERY_CHARGE_LIMIT_DOWN` R/W

| bit7 | bit6 | bit5 | bit4 | bit3 | bit2 | bit1 | bit0 |
|------|------|------|------|------|------|------|------|
| 保留 | 下限 bit6 | 下限 bit5 | 下限 bit4 | 下限 bit3 | 下限 bit2 | 下限 bit1 | 下限 bit0 |

| Bit | 掩码 | 功能 | 说明 |
|-----|------|------|------|
| bit6:0 | `0x7F` | 充电下限 % | `0` = 默认 95%，1-95 = 实际百分比 |
| bit7 | `0x80` | 保留 | RMW 时保留原值 |

### EC[2002-2003] — 模组 ID

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 2002 | `ADDR_ModuleID_GPU` | GPU 模组 ID，R |
| 2003 | `ADDR_ModuleID` | 主模组 ID，R |

### EC[2008-2010] — TCC 默认偏移

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 2008 | `ADDR_GAMING_TCC_OFFSET_DEFAULT_VALUE` | Gaming 模式默认值，R |
| 2009 | `ADDR_OFFICE_TCC_OFFSET_DEFAULT_VALUE` | Office 模式默认值，R |
| 2010 | `ADDR_TURBO_TCC_OFFSET_DEFAULT_VALUE` | Turbo 模式默认值，R |

### EC[2022-2023] — 水冷控制

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 2022 | `ADDR_LC_FAN_VALUE` | 水冷风扇值，R/W |
| 2023 | `ADDR_LC_PUMP_VALUE` | 水冷泵值，R/W |

### EC[2043] — 端口 ID 变更

`ADDR_CHANGE_PORT_ID_WKD` R/W

### EC[3328] — 单区域模式

`ADDR_AP_OEM_SingleZone` R/W

---

## 三、风扇曲线表（3840-3935）

风扇曲线表共 96 字节，分 6 组 x 16 级。每级包含温度阈值和对应的 Duty 百分比。

| EC 范围 | 官方常量名 | 内容 | 说明 |
|---------|------------|------|------|
| 3840-3855 | `ADDR_CPU_FAN_TABLE_TEMP_UP0` | CPU 升温阈值 (UpT) | 最后一点写 `0xFF` |
| 3856-3871 | `ADDR_CPU_FAN_TABLE_TEMP_DOWN0` | CPU 降温阈值 (DownT) | 第 0 级无 DownT |
| 3872-3887 | `ADDR_CPU_FAN_TABLE_DUTY0` | CPU Duty | 值 = 百分比 x 2，范围 0-200 |
| 3888-3903 | `ADDR_GPU_FAN_TABLE_TEMP_UP0` | GPU 升温阈值 | — |
| 3904-3919 | `ADDR_GPU_FAN_TABLE_TEMP_DOWN0` | GPU 降温阈值 | — |
| 3920-3935 | `ADDR_GPU_FAN_TABLE_DUTY0` | GPU Duty | 值 = 百分比 x 2 |

**Duty 值**：写入值 = 百分比 x 2。如 50% 写 100，100% 写 200。实测 readback 可能比写入少 1。

**温度传感器**
- CPU 曲线 (3840-3887) → CPU 内部 DTS (PECI)，控制 1 号风扇 (EC[1883])
- GPU 曲线 (3888-3935) → EC 固件第二路温度输入，控制 2 号风扇 (EC[1884])
- 核显本的 "GPU" 温度源可能是 VRM / PCH / CPU 封装另一测温点

**RamFan1p5 表状态控制**

| 地址 | 官方常量名 | 说明 |
|------|------------|------|
| 3933 | `ADDR_RAMFAN1P5_TABLE_STATUS1` | 表状态 1，R |
| 3934 | `ADDR_RAMFAN1P5_TABLE_STATUS2` | 表状态 2，R |
| 3935 | `ADDR_RAMFAN1P5_TABLE_CTRL` | 表控制，R/W |

---

## 四、地址复用说明

以下地址被不同固件路径复用，使用时需注意当前模式：

| 地址 | 路径 A | 路径 B |
|------|--------|--------|
| 1859-1863 | MyFan2 PWM L1-L5 | ConfigurableTGP / DynamicBoost |
| 1894 | SupportByte2 | Light_ChinaMode |
| 1922 | BIOS_OEM_BYTE2 | Light_SetToChinaMode |
| 1926 | TCC 温度目标（RamFan1p5） | L1_PWM_DEFAULT_MYFAN3 |
| 1927 | 风扇切换速度（RamFan1p5） | L2_PWM_DEFAULT_MYFAN3 |
| 1929-1930 | L4/L5_PWM_DEFAULT_MYFAN3 | L1/L2_PWM_DEFAULT_MYFAN2 |
| 1932 | 键盘背光 (SINGLEKBL_ENABLE) | AP_OEM_BYTE2 / L4_PWM_DEFAULT_MYFAN2 |

---

## 五、OSD 事件码（非 EC 寄存器）

`ECSpec.cs` 中定义的 OSD 事件码，用于 GCU 服务的 UI 通知，不是 EC 寄存器地址：

| 码 | 常量名 | 事件 |
|----|--------|------|
| 1 | `OSD_CAPSLOCK` | CapsLock |
| 2 | `OSD_NUMLOCK` | NumLock |
| 4/5 | `OSD_TPON/TPOFF` | 触控板开关 |
| 59-63 | `OSD_KB_LED_LEVEL0-4` | 键盘背光等级 0-4 |
| 64/65 | `OSD_WINKEY_LOCK/UNLOCK` | Win 锁 |
| 144/145 | `OSD_CAMERAON/OFF` | 摄像头开关 |
| 165 | `WinKey_Update` | Win 键更新 |
| 167 | `OSD_FANBOOST_UPDATE` | FanBoost 更新 |
| 176 | `OSD_FanModeSwitch` | 风扇模式切换 |
| 179/180 | `BacklightLevelChange/PowerChange` | 背光变化 |
| 184 | `OSD_FnChange` | Fn 键变化 |

---

## 六、快速索引（按地址排序）

| 地址 (十进制) | 十六进制 | 主要功能 | R/W |
|---------------|----------|----------|-----|
| 1026-1027 | `0x0402` | 设计容量 | R |
| 1028-1029 | `0x0404` | 满充容量 | R |
| 1032-1033 | `0x0408` | 设计电压 | R |
| 1076-1077 | `0x0434` | 放电电流 | R |
| 1078-1079 | `0x0436` | 剩余容量 | R |
| 1080-1081 | `0x0438` | 电池电压 | R |
| 1108 | `0x0454` | EC 固件版本 | R |
| 1110 | `0x0456` | 系统 ID | R |
| 1115 | `0x045B` | 静音模式状态 | R |
| 1124-1125 | `0x0464` | 主风扇 RPM | R |
| 1131-1132 | `0x046B` | 副风扇 RPM | R |
| 1142 | `0x0476` | BIOS 功能寄存器 | R |
| 1149 | `0x047D` | EC 子版本 | R |
| 1168 | `0x0490` | 电源来源 | R |
| 1172 | `0x0494` | 电池告警 | R |
| 1183 | `0x049F` | BIOS 信息 3 | R |
| 1186 | `0x04A2` | 电池温度 | R |
| 1190-1191 | `0x04A6` | 循环次数 | R |
| 1195 | `0x04AB` | RSOC 百分比 | R |
| 1798 | `0x0706` | AP BIOS 控制 | R/W |
| 1830 | `0x0726` | Custom 标志 / AC Recovery | R/W |
| 1831 | `0x0727` | Custom 灯 / PL4 双倍标志 | R/W |
| 1856 | `0x0740` | 项目 ID | R |
| 1857 | `0x0741` | ApExistFlag | R/W |
| 1858 | `0x0742` | 支持字节 5 | R |
| 1859-1863 | `0x0743` | MyFan2 PWM / TGP DynamicBoost | R/W |
| 1864 | `0x0748` | LightBar 控制 | R/W |
| 1865-1867 | `0x0749` | LightBar RGB | R/W |
| 1868 | `0x074C` | OEM 服务项目 ID | R |
| 1870 | `0x074E` | Fn Lock | R/W |
| 1873 | `0x0751` | 风扇/电源模式 | R/W |
| 1875 | `0x0753` | CPU VRM 持续电流 | R/W |
| 1876 | `0x0754` | CPU VRM 峰值电流 | R/W |
| 1883 | `0x075B` | 主风扇 Duty 读数 | R |
| 1884 | `0x075C` | 副风扇 Duty 读数 | R |
| 1885 | `0x075D` | 触发字节 2 | R/W |
| 1893 | `0x0765` | 支持字节 1（硬件能力） | R |
| 1894 | `0x0766` | 支持字节 2（硬件能力） | R |
| 1895 | `0x0767` | 触发字节（Win 锁/USB 充电等） | R/W |
| 1896 | `0x0768` | 状态字节（Win 锁/FanBoost 等） | R |
| 1897-1903 | `0x0769` | RGB 键盘颜色 + 音乐模式 | R/W |
| 1905-1906 | `0x0771` | ROM ID | R |
| 1922 | `0x0782` | Qkey / 默认模式 / Fan3 支持 | R/W |
| 1923-1925 | `0x0783` | PL1/PL2/PL4 当前值 | R |
| 1926 | `0x0786` | TCC 温度目标与使能 | R/W |
| 1927 | `0x0787` | 风扇切换速度 | R/W |
| 1928-1930 | `0x0788` | MyFan3 PWM 默认值（旧路径） | R |
| 1931 | `0x078B` | GPU D-State | R/W |
| 1932 | `0x078C` | 键盘背光 | R/W |
| 1934 | `0x078E` | 背光/电池保护支持标志 | R |
| 1950-1952 | `0x079E` | 风扇最低速度/温度/额外速度 | R/W |
| 1955 | `0x07A3` | BIOS OEM 3 | R |
| 1956 | `0x07A4` | AP BIOS（QC Fn 锁） | R/W |
| 1957 | `0x07A5` | AP OEM 3 | R/W |
| 1958 | `0x07A6` | 充电模式 / 触控板 LED | R/W |
| 1959-1962 | `0x07A7` | BatterySaver PL 默认值 | R |
| 1963 | `0x07AB` | CCI 模式索引 | R/W |
| 1968-1970 | `0x07B0` | CCI 模式 Profile | R/W |
| 1977 | `0x07B9` | 充电上限 % | R/W |
| 1989 | `0x07C5` | 独立风扇控制 | R/W |
| 1990 | `0x07C6` | AP 风扇管理使能 | R/W |
| 1991-1992 | `0x07C7` | AP OEM 7/8 | R/W |
| 1994 | `0x07CA` | BIOS OEM 8 | R |
| 1996 | `0x07CC` | 复合电源状态 | R |
| 2000 | `0x07D0` | 充电下限 % | R/W |
| 2002-2003 | `0x07D2` | GPU/主模组 ID | R |
| 2008-2010 | `0x07D8` | TCC 默认偏移 | R |
| 2022-2023 | `0x07E6` | 水冷风扇/泵 | R/W |
| 2043 | `0x07FB` | 端口 ID 变更 | R/W |
| 3328 | `0x0D00` | 单区域模式 | R/W |
| 3840-3855 | `0x0F00` | CPU 风扇表 UpT | R/W |
| 3856-3871 | `0x0F10` | CPU 风扇表 DownT | R/W |
| 3872-3887 | `0x0F20` | CPU 风扇表 Duty | R/W |
| 3888-3903 | `0x0F30` | GPU 风扇表 UpT | R/W |
| 3904-3919 | `0x0F40` | GPU 风扇表 DownT | R/W |
| 3920-3935 | `0x0F50` | GPU 风扇表 Duty | R/W |
