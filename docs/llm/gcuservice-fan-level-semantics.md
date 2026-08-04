# GCUService 风扇挡位与 UpT/DownT 语义

本文只以机械革命官方控制台的 `GCUService.exe` 反编译结果作为上层软件蓝本，
并以 EC 固件二进制确认运行时行为。项目当前的 MFC 实现不作为逆向依据。

分析对象：

- 官方服务反编译：`ref/GCUService_decompiled`
- 官方配置示例：`ref/ControlCenter[CN]/UniwillService/MyControlCenter/UserFanTables`
- EC 固件：`/home/texsd/Workdir/ec_reverse/samples/GXxHXxx_21.200`
- 固件关键代码：bank 1 的 `0x95F0..0x9640`，取表辅助函数位于 `0xE4FC`、`0xE50C`

## 结论

GCU JSON 的每一行表示一个**目标挡位**：

- `Duty[k]`：挡位 `k` 的目标占空比。
- `UpT[k]`：从 `k-1` 升入挡位 `k` 所使用的阈值。
- `DownT[k]`：从 `k+1` 降入挡位 `k` 所使用的阈值。

因此，同一行的 `UpT` 和 `DownT` 不是“离开当前挡位的上下边界”。对相邻挡位
`k` 与 `k+1`，实际切换条件是：

```text
k -> k+1：T > GCU[k+1].UpT
k+1 -> k：T < GCU[k].DownT
```

比较是严格大于和严格小于：

- `T == UpT` 时不升挡。
- `T == DownT` 时不降挡。

所以相邻挡位之间的保持区间为闭区间：

```text
GCU[k].DownT <= T <= GCU[k+1].UpT
```

处于这个区间时，最终挡位取决于此前处于哪一挡，这就是该表的迟滞行为。

## GCU 表到 EC 表的映射

官方 CML 表写入逻辑位于：

`ref/GCUService_decompiled/GCUService/MyControlCenter/MyFan/FanTable/FanTable_Manager1p5_CML.cs`

`SetEcFanTable()` 不会把 JSON 的每一行原样并排写入 EC。对 GCU 挡位 `k` 和
EC 槽位 `i`，CPU 表的映射为：

```text
EC_UpT[i]     = GCU_Point[i+1].UpT    (i = 0..14)
EC_UpT[15]    = 255

EC_DownT[i+1] = GCU_Point[i].DownT    (i = 0..14)

EC_Duty[i]    = GCU_Point[i].Duty * 2
```

若 JSON 中 `Duty > 100`，CML 写入器会写 `0xFF`，而不是继续乘以 2。GPU 表
使用完全相同的重排规则，只是地址不同。

| EC 范围 | 内容 | GCU 来源 |
|---|---|---|
| `XRAM[3840..3855]` | CPU `UpT[0..15]` | 下一挡的 `UpT`，末项固定 `255` |
| `XRAM[3856..3871]` | CPU `DownT[0..15]` | 前一挡的 `DownT` 写到索引 `1..15` |
| `XRAM[3872..3887]` | CPU `Duty[0..15]` | 当前挡 `Duty * 2` |
| `XRAM[3888..3903]` | 第二组 `UpT[0..15]` | 同 CPU 规则 |
| `XRAM[3904..3919]` | 第二组 `DownT[0..15]` | 同 CPU 规则 |
| `XRAM[3920..3935]` | 第二组 `Duty[0..15]` | 同 CPU 规则 |

`GetEcFanTable()` 使用上述映射的逆过程读回表格，并将 GCU 第 0 挡的 `UpT`
直接补成 0。这进一步说明 `GCU[0].UpT` 是界面/数据模型中的虚拟端点，不参与
从更低挡升入第 0 挡。

## EC 运行时状态机

`GXxHXxx_21.200` 固件中，普通 AP Custom 路径的单次更新可以简化为：

```text
index = current_level

if temperature > EC_UpT[index]:
    index += 1
elif temperature < EC_DownT[index]:
    index -= 1
else:
    index不变

target_duty = EC_Duty[index]
```

严格比较由 bank 1 原始指令直接确认：

```asm
; 升挡判断：T - UpT - 1，借位表示 T <= UpT
SETB C
SUBB A,R7
JC   check_down
INC  index

; 降挡判断：T - DownT，不借位表示 T >= DownT
CLR  C
SUBB A,R7
JNC  keep
DEC  index
```

使用 `XRAM[0x9413]` 的另一温度源分支具有相同的严格比较。取表辅助函数只读取
表项，没有隐藏的 `+1` 或 `-1` 修正。

每次风扇控制 worker 调用最多只改变一级。即使温度一次跨过多个阈值，EC 也会在
后续多次调用中逐级追赶，而不是一次跳到最终挡位；表项之间也没有插值。

选出新挡位后，EC 才查该挡的目标 `Duty`。实际 PWM 还会独立地向目标值渐变，
`FanSwitchSpeed` 控制的是这段占空比渐变的节奏，不改变 `UpT`/`DownT` 的比较语义。

## 官方配置实例

官方 `PH4AQE3/M1T1.json` 的 CPU 表开头为：

| GCU 挡位 | UpT | DownT | Duty |
|---:|---:|---:|---:|
| 0 | 0 | 37 | 0% |
| 1 | 46 | 50 | 30% |
| 2 | 51 | 53 | 35% |

实际边界不是按一行内的两个温度解释，而是：

```text
0 -> 1：T > 46；若温度为整数，首次升挡温度是 47 C
1 -> 0：T < 37；若温度为整数，首次降挡温度是 36 C

1 -> 2：T > 51；若温度为整数，首次升挡温度是 52 C
2 -> 1：T < 50；若温度为整数，首次降挡温度是 49 C
```

例如当前为第 1 挡时，温度从 37 C 到 51 C（含两端）都保持第 1 挡。

## 端点、哨兵与有效挡位数

- GCU 第 0 挡的 `UpT` 不参与运行时切换；服务读回时固定显示为 0。
- `EC_UpT[15]` 由服务固定写成 `255`，使最高物理挡无法继续正常升挡。
- `EC_DownT[0]` 不由 GCU 的 CML 写表路径写入。固件对挡位索引另有范围检查，
  发生下溢时会恢复为 0。
- EC 表始终有 16 个物理槽位，即 `0..15`。
- 官方配置常只使用前 11 挡（`0..10`），其余行用 `255` 填充作为哨兵。
- `CpuTemp_DefaultMaxLevel` 和 `GpuTemp_DefaultMaxLevel` 是 GCU 元数据：服务按
  “最后一次 Duty 增长所在索引 + 1”计算。它不改变 EC 的 16 槽物理布局。

`Duty=255` 不是正常百分比值。它与 `UpT=DownT=255` 一起表示未使用的尾部表项，
不应当作第 16 挡的“255% 风扇”解释。

## 双风扇限制

以下结论只对已核对的 `GXxHXxx_21.200` 固件成立，不应无条件推广到其他 EC 版本：

- AP Custom 路径持续更新主挡位索引。
- 第二挡位索引在该路径中不会按第二温度持续执行同样的升降状态机，只会被保留
  或清零。
- 联动模式用选定的/较大的索引分别查询两张 Duty 表。
- 独立模式下，主风扇使用主索引，第二风扇使用被保留的第二索引。

因此，官方服务能够写入第二组阈值表，并不等于该固件在 Custom 模式下必然按照
第二路实时温度推进第二条曲线。是否成立必须按具体 EC 固件验证。

目前能从固件中确定的是运行时变量地址：普通主温度路径使用
`XRAM[0x043E]`，条件分支的替代源使用 `XRAM[0x9413]`，第二路相关温度值位于
`XRAM[0x9141]`。这些地址本身不足以证明其物理传感器一定是 CPU PECI、GPU、
VRM 或 PCH，因此本文不对传感器物理来源作推断。

## 证据边界

官方 `GCUService.exe` 能证明配置模型、字段重排、地址和写入顺序，但无法单独证明
EC 对阈值采用 `>` 还是 `>=`。严格边界和逐级推进来自 EC 固件原始操作码。

外部 EC 逆向文档
`/home/texsd/Workdir/ec_reverse/docs/performance_power/ec_ac_battery_power_profile_investigation_20260726.md`
曾将升挡条件记为 `temperature >= UpT[index]`；这与上述原始指令不符。准确条件是
`temperature > UpT[index]`。
