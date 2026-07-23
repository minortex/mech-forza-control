# Battery Charging Mode Control (电池充电模式控制)

## 概述

控制笔记本电池的充电上限，在不同场景下平衡续航与电池寿命：
- **High (Performance)**：满充 100%，最大化续航
- **Middle (Balanced)**：~80% 限充，平衡寿命与续航
- **Low (Health)**：~60% 限充，最大程度延寿

## 数据来源

所有寄存器地址和逻辑来自 dnSpy 反编译的 GCU 控制中心程序集。

| 文件 | 作用 |
|------|------|
| `MySystem/BatteryProtection.cs` | 电池保护模式主实现（三档切换） |
| `MySystem/BatteryProtection2.cs` | 电池保护模式 v2（增加 NVRAM 自定义上下限） |
| `MySystem/Protection_Status.cs` | 模式枚举定义 |
| `MyECIO/MyEcCtrl.cs` | EC 读写 facade |

## EC 寄存器

### XRAM[1934] — 功能支持检测

```csharp
// BatteryProtection.cs:InitializeHealthSwitch()
byte b = 0;
MyEcCtrl.Instance.Read(base.GetType().Name, 1934, ref b);
BitArray bitArray = new BitArray(new byte[] { b });
this.BatteryProctionSupport = bitArray[3];  // bit3 = support flag
```

| bit | 含义 |
|-----|------|
| 3 | `1` = 硬件支持电池保护模式 |

当前实机值：`0x6c` (`0110 1100`)，bit3=1，支持。

### XRAM[1958] — 充电模式控制 (ADDR_AP_OEM_BYTE4)

该寄存器同时控制触控板 LED（bit3）和充电模式（bits 4-5）。见 `BatteryProtection.cs` 三个 setter：

```csharp
// SetProtectionHigh() — PERFORMANCEDMODE (0), 满充 100%
bitArray[4] = false;
bitArray[5] = false;

// SetProtectionMiddle() — BALANCEDMODE (1), ~80% 限充
bitArray[4] = true;
bitArray[5] = false;

// SetProtectionLow() — HEALTHYMODE (2), ~60% 限充
bitArray[4] = false;
bitArray[5] = true;
```

| 模式 | `Protection_Status` 值 | bit5 | bit4 | 行为 |
|------|------------------------|------|------|------|
| **High** (性能) | `PERFORMANCEDMODE` = 0 | 0 | 0 | 充至设计容量 100% |
| **Middle** (均衡) | `BALANCEDMODE` = 1 | 0 | 1 | 充至 ~80% (~4000 mAh/5200 mAh) |
| **Low** (保养) | `HEALTHYMODE` = 2 | 1 | 0 | 充至 ~60% |

```csharp
// Protection_Status.cs
internal enum Protection_Status {
    PERFORMANCEDMODE,  // = 0
    BALANCEDMODE,     // = 1
    HEALTHYMODE       // = 2
}
```

**实测验证**：三档 RMW 切换干净，不破坏 bit3（触控板 LED）。

## NVRAM_STRUCT 对应字段

`BatteryProtection2.cs` 在切换模式时同步写 `UniWillVariable` 的三个字段：

```csharp
// BatteryProtection2.cs
private int m_BatteryLimitationMode {
    set {
        this._BatteryLimitationMode = value;
        NvramVariable.SetFwVars("BatteryLimitation", Convert.ToByte(value));
    }
}
private int m_BatteryChargingLimit_Up {
    set {
        this._BatteryChargingLimit_Up = value;
        NvramVariable.SetFwVars("ChargeMaximumLimit", Convert.ToByte(value));
    }
}
private int m_BatteryChargingLimit_Down {
    set {
        this._BatteryChargingLimit_Down = value;
        NvramVariable.SetFwVars("ChargeMinimumLimit", Convert.ToByte(value));
    }
}
```

在 `NVRAM_STRUCT` 中的偏移：

| 字段 | 偏移 | 类型 | 取值 |
|------|------|------|------|
| `BatteryLimitation` | 48 | byte | 0=High, 1=Middle, 2=Low |
| `ChargeMaximumLimit` | 49 | byte | 自定义上限 %（0-100） |
| `ChargeMinimumLimit` | 50 | byte | 自定义下限 %（0-100） |

实测写入成功，但不直接控制燃料计学习的 "last full capacity"。

## ACPI 电池数据与燃料计行为

ACPI 通过 `acpi -V` 暴露的电池数据：

```
Battery 0: design capacity 5200 mAh, last full capacity 4000 mAh = 76%
```

`last full capacity` 由 EC 燃料计（Fuel Gauge）在 EC 内部 flash 中记录。充电模式切换通过 XRAM[1958] 控制 EC 何时停止充电，但燃料计的学习值是一种累积信息：

- 设 Middle 模式后 EC 在 ~80%（4000 mAh）停充 → 燃料计逐渐将该值学为 "满"
- 切回 High 模式后 EC 允许充至 100%，但燃料计需要一次**完整的空→满充电循环**才能重新学到 5200 mAh
- 写 NVRAM 字段也不足以立即恢复，因为燃料计使用自己的内部算法

## 实现方案

预期 CLI 接口：

```
ec setting battery status       — 显示当前模式与电量信息
ec setting battery high         — Performance 模式 (100%)
ec setting battery middle       — Balanced 模式 (~80%)
ec setting battery low          — Health 模式 (~60%)
```

切换序列：
1. `_ensure_ap_exist()` — 设 XRAM[1857] bit0=1（按 `acrecov` 模式，确保 EC 接受上层指令）
2. 写 `XRAM[1958]` bits [5:4] — 设置充电模式
3. 可选写 NVRAM `BatteryLimitation` / `ChargeMaximumLimit` / `ChargeMinimumLimit` — 持久化备份

`ec setting status` 应同步显示来自 ACPI sysfs 的实时电池数据（`capacity`、`status`、`charge_now`、`charge_full`）。

## 注意事项

- `XRAM[1958]` 同时控制触控板 LED（bit3），切换充电模式时必须 RMW。
- 燃料计恢复需要完整充放电循环，切换模式后不会立即在 `acpi -V` 中反映。
- NVRAM 字段通过 efivarfs 写入时需要先 `chattr -i` 清除 immutable 标志。
- 与 Windows GCU Service 的差异：官方还维护注册表状态，Linux 直控不复制注册表行为。
