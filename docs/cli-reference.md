# CLI 命令参考

Linux 默认通过 `/dev/mechrevo-ec` 内核桥接受控访问固件声明的 4 KiB EC MMIO 资源，
不会把物理内存映射给用户态，也不会静默回退到 `/dev/mem`。后端支持连续 block 和原子 vector
transaction；多个客户端可以同时打开设备，一边 monitor 一边切换模式，硬件事务仍由设备 mutex
串行化。DKMS 包安装的 udev 规则将设备设置为 `0660 root:wheel`；用户属于 `wheel` 时，默认内核
后端不需要 sudo。不要将 EC 设备开放为 `0666`。驱动构建和 DKMS 打包见独立仓库
[`mech-forza-kmod`](https://github.com/minortex/mech-forza-kmod)。

```bash
uv run mfc <command>
```

---

## mfc mode — 电源模式切换

### 固定模式

```bash
uv run mfc mode office    # Office (25W)
uv run mfc mode gaming    # Gaming (45W)
uv run mfc mode turbo     # Turbo (65W)
```

固定模式由 XRAM[1873] 控制字节 + 默认风扇表决定，PL 由 EC/BIOS 自动管理。

### Custom 模式

```bash
uv run mfc mode custom [25|45|65] [--tcc TCC] [--separate]
```

| 参数 | 说明 |
|------|------|
| `25` `45` `65` | TDP 档位（可选，默认 45W） |
| `--tcc TCC` | TCC 目标温度 0-100°C。省略则保持当前值，0 禁用 |
| `--separate` | CPU/GPU 风扇独立控制（XRAM[1989] bit7） |

Custom 模式的关键差异：
- XRAM[1830] bit7 = 1（Custom 标志）
- 写入默认风扇曲线到 XRAM[3840..3935]
- TCC 和独立风扇控制生效

### 状态查看

```bash
uv run mfc mode status    # 当前模式、CTL 字节、PL 读数
uv run mfc mode dump      # dump XRAM[1829..1844] + XRAM[1989..1994]
```

`status` 输出包括 XRAM[1873] CTL 字节、XRAM[1830] OEM9、XRAM[1831] OEM10、
XRAM[1857] ApExistFlag、XRAM[1990] AP_CTL、PL1/PL2/PL4 读数。

`dump` 输出两段原始寄存器值，用于快速排查。

---

## mfc fan — 风扇监控与控制

### 读取

```bash
uv run mfc fan read       # 当前 RPM、Duty、控制字节、切换速度
```

输出：主/副风扇 RPM、XRAM[1873] 控制字节、主/副 Duty 读数、切换速度。

### 持续监控

```bash
uv run mfc fan monitor [-i INTERVAL]
```

| 参数 | 说明 |
|------|------|
| `-i INTERVAL` | 刷新间隔（秒），默认 1.0 |

Ctrl+C 停止。输出时间戳 + RPM + Duty 表格。

### 强制转速

```bash
uv run mfc fan set PCT              # 两个风扇同一百分比
uv run mfc fan set CPU_PCT GPU_PCT  # 分别设置 CPU 和 GPU 风扇
```

`PCT` 范围 0-100。通过把风扇表 16 级 Duty 全部写入同一值实现。

### 切换速度

```bash
uv run mfc fan switch-speed STEPS
```

| STEPS | 效果 |
|-------|------|
| 0 | EC 默认渐变，约 7s 完成 10% 变化 |
| 1 | 约 2 秒（工具默认值） |
| 3 | 约 6 秒 |
| N | 约 N*2 秒 |

写入 XRAM[1927]，bit7=使能，bit6:0=step。

### 恢复默认

```bash
uv run mfc fan default    # 恢复 config.py 中的出厂风扇曲线
```

从 `fan-table.toml` 读取 `[main].levels` 和 `[second].levels`，写入 UpT +
DownT + Duty 到 XRAM[3840..3935]。每组必须包含 16 个 GCU 曲线点：
第 0 点省略 `up`，第 15 点省略 `down`。相邻点必须满足前一点的
`down` 小于后一点的 `up` 以形成滞回；UpT/DownT 必须严格递增，
Duty 不得递减。写入 EC 时按官方 RamFan1p5 格式偏移阈值。
旧版 EC-slot 端点格式仍可读取，并会在内存中转换为 GCU 曲线点。

`mfc fan table` 也按 GCU 目标挡位展示：第 `k` 行的 Up 表示温度严格大于
该值时从 `k-1` 升入 `k`，Down 表示温度严格小于该值时从 `k+1` 降入
`k`；温度等于阈值时保持当前挡位。值为 `255` 的 Duty 是未使用槽位的
哨兵，显示为 `unused`，不是百分比。`Current` 列在联动模式用 `CUR` 标记
主/CPU 当前挡位；独立模式分别用 `M`、`S` 标记两路挡位，重合时显示 `M/S`。

---

## mfc backlight — 键盘背光

```bash
uv run mfc backlight status   # 当前 XRAM[1932] 值、亮度等级、位模式
uv run mfc backlight off      # 关闭（等级 0）
uv run mfc backlight dim      # 暗（等级 1，bit7:5=001）
uv run mfc backlight bright   # 亮（等级 2，bit7:5=010）
uv run mfc backlight cycle    # 循环：off -> dim -> bright -> off
uv run mfc backlight level N  # 直接设置等级 0-4（高级用法）
```

等级 0-4 对应 bit7:5 编码 `000`/`011`/`001`/`100`/`010`。
键盘快捷键只在 0/2/4 循环。等级 1 和 3 是中间值，切入后会导致 EC 位错乱，
需切回 0 恢复。XRAM[1932] bit4 写入时必须为 1。

---

## mfc setting — 设置类功能

### 查看状态

```bash
uv run mfc setting status
```

输出：Win lock、Fn lock、USB charger、AC recovery 当前状态和 ApExistFlag。

### Win 锁

```bash
uv run mfc setting winlock on     # 锁定 Win 键
uv run mfc setting winlock off    # 解锁
```

通过 XRAM[1895] bit0 触发 toggle，状态在 XRAM[1896] bit0。

### Fn 锁

```bash
uv run mfc setting fnlock on      # 锁定 Fn 键
uv run mfc setting fnlock off     # 解锁
```

直接写 XRAM[1870] bit4。

### USB 关机充电

```bash
uv run mfc setting usbchg on      # 开启关机 USB 充电
uv run mfc setting usbchg off     # 关闭
```

直接写 XRAM[1895] bit4（RMW）。

### AC Recovery（来电自动开机）

```bash
uv run mfc setting acrecov on     # 开启
uv run mfc setting acrecov off    # 关闭
```

自动设置 ApExistFlag（XRAM[1857] bit0），然后写 XRAM[1830] bit3。
这是 BIOS 不支持 NVRAM 时的 fallback 路径；支持时应走 NVRAM。

---

## mfc bat — 充电阈值控制

通过 `XRAM[1977]`（上限，`0x07B9`）与 `XRAM[2000]`（下限，`0x07D0`）直接设置电池充电阈值。

- `0x07B9[6:0]`：上限百分比；bit7 为停止/抑制充电标志。
- `0x07D0[6:0]`：下限百分比；bit7 为当前是否处于充电周期中的 phase/cycle-active 标志。

### 查看当前状态

```bash
uv run mfc bat status
```

输出当前 RSOC、上下限寄存器原始值、stop-bit / cycle-active 标志，以及实时电池信息。

### 仅设置上限（上限模式）

```bash
uv run mfc bat set -u <up>
```

其中 `<up>` 为 `1-99` 的整数，例如 `80` 表示达到 80% 后应停止充电。

> [!NOTE]
> 上限控制通常需要额外先启用：
> 1. 运行 w568 的脚本开启；或
> 2. 刷入支持的 BIOS/固件，并在 BIOS 中打开 charge limit 选项。

### 设置下限/上限窗口（迟滞模式）

```bash
uv run mfc bat set -d <down> -u <up>
```

- `<down>`：`1-95`
- `<up>`：`2-99`
- 且必须满足 `<down> < <up>`

工具会按 `flexicharge.py` 的语义初始化两个 flag：
- 先写 `0x07D0`，再写 `0x07B9`；
- 若当前 RSOC `<= down`，则初始化为 active cycle；
- 若当前 RSOC `>= up`，则初始化为 stopped / inhibited；
- 若当前 RSOC 位于中间区间，则默认进入 hold；若重设的是同一窗口且原本已处于 active cycle，则保留 active 状态。

> [!WARNING]
> 下限/上限窗口功能必须刷入兼容的 EC 固件后才能真正生效。原厂 EC 上寄存器写入可能成功，但充电行为未必会变化。

### 取消限制并充到 100%

```bash
uv run mfc bat charge-full
```

工具在同一个事务中先清空 `0x07D0`，再清空 `0x07B9`，立即解除
FlexiCharge、upper-only 和 stop/inhibit 状态，允许电池充到 100%。实际是否开始充电仍取决于
AC 连接、电池温度和硬件保护条件。

兼容 v2.2 的 EC 固件会异步把 lower=0 写入持久化配置；`mfc bat status` 会显示保存记录及
`A5/78`（待提交）或 `55/AA`（已消费）握手状态。

---

## 工具脚本 (`tools/`)

独立脚本，不通过 `ec` 入口调用：

```bash
# 底层 EC 字节读写（调试用）
sudo uv run tools/ec_rw.py <addr>              # 读
sudo uv run tools/ec_rw.py <addr> <value>      # 写
sudo uv run tools/ec_rw.py <start> <end>       # dump 范围

# EC 寄存器批量探测
sudo uv run tools/ec_probe.py

# 模式切换早期独立脚本
sudo python tools/switch_mode.py

# MQTT 消息发送（模拟官方 GCU Service）
python tools/mqtt_pub.py

# MQTT 消息抓包（监听官方控制台通信）
python tools/mqtt_sniff.py
```

---

## 开发 / 测试

```bash
# 测试（无需硬件，mock 读写）
uv run pytest

# 语法检查
uv run python -m compileall src/ec
```
