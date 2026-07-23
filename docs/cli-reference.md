# CLI 命令参考

所有 `ec` 命令需要 sudo 运行（读写 `/dev/mem`）。

```bash
sudo uv run ec <command>
```

---

## ec mode — 电源模式切换

### 固定模式

```bash
sudo uv run ec mode office    # Office (25W)
sudo uv run ec mode gaming    # Gaming (45W)
sudo uv run ec mode turbo     # Turbo (65W)
```

固定模式由 EC[1873] 控制字节 + 默认风扇表决定，PL 由 EC/BIOS 自动管理。

### Custom 模式

```bash
sudo uv run ec mode custom [25|45|65] [--tcc TCC] [--separate]
```

| 参数 | 说明 |
|------|------|
| `25` `45` `65` | TDP 档位（可选，默认 45W） |
| `--tcc TCC` | TCC 目标温度 0-100°C。省略则保持当前值，0 禁用 |
| `--separate` | CPU/GPU 风扇独立控制（EC[1989] bit7） |

Custom 模式的关键差异：
- EC[1830] bit7 = 1（Custom 标志）
- 写入默认风扇曲线到 EC[3840..3935]
- TCC 和独立风扇控制生效

### 状态查看

```bash
sudo uv run ec mode status    # 当前模式、CTL 字节、PL 读数
sudo uv run ec mode dump      # dump EC[1829..1844] + EC[1989..1994]
```

`status` 输出包括 EC[1873] CTL 字节、EC[1830] OEM9、EC[1831] OEM10、
EC[1857] ApExistFlag、EC[1990] AP_CTL、PL1/PL2/PL4 读数。

`dump` 输出两段原始寄存器值，用于快速排查。

---

## ec fan — 风扇监控与控制

### 读取

```bash
sudo uv run ec fan read       # 当前 RPM、Duty、控制字节、切换速度
```

输出：主/副风扇 RPM、EC[1873] 控制字节、主/副 Duty 读数、切换速度。

### 持续监控

```bash
sudo uv run ec fan monitor [-i INTERVAL]
```

| 参数 | 说明 |
|------|------|
| `-i INTERVAL` | 刷新间隔（秒），默认 1.0 |

Ctrl+C 停止。输出时间戳 + RPM + Duty 表格。

### 强制转速

```bash
sudo uv run ec fan set PCT              # 两个风扇同一百分比
sudo uv run ec fan set CPU_PCT GPU_PCT  # 分别设置 CPU 和 GPU 风扇
```

`PCT` 范围 0-100。通过把风扇表 16 级 Duty 全部写入同一值实现。

### 切换速度

```bash
sudo uv run ec fan switch-speed STEPS
```

| STEPS | 效果 |
|-------|------|
| 0 | EC 默认渐变，约 7s 完成 10% 变化 |
| 1 | 约 2 秒（工具默认值） |
| 3 | 约 6 秒 |
| N | 约 N*2 秒 |

写入 EC[1927]，bit7=使能，bit6:0=step。

### 恢复默认

```bash
sudo uv run ec fan default    # 恢复 config.py 中的出厂风扇曲线
```

写入 UpT + DownT + Duty 到 EC[3840..3935]。

---

## ec backlight — 键盘背光

```bash
sudo uv run ec backlight status   # 当前 EC[1932] 值、亮度等级、位模式
sudo uv run ec backlight off      # 关闭（等级 0）
sudo uv run ec backlight dim      # 暗（等级 1，bit7:5=001）
sudo uv run ec backlight bright   # 亮（等级 2，bit7:5=010）
sudo uv run ec backlight cycle    # 循环：off -> dim -> bright -> off
sudo uv run ec backlight level N  # 直接设置等级 0-4（高级用法）
```

等级 0-4 对应 bit7:5 编码 `000`/`011`/`001`/`100`/`010`。
键盘快捷键只在 0/2/4 循环。等级 1 和 3 是中间值，切入后会导致 EC 位错乱，
需切回 0 恢复。EC[1932] bit4 写入时必须为 1。

---

## ec setting — 设置类功能

### 查看状态

```bash
sudo uv run ec setting status
```

输出：Win lock、Fn lock、USB charger、AC recovery 当前状态和 ApExistFlag。

### Win 锁

```bash
sudo uv run ec setting winlock on     # 锁定 Win 键
sudo uv run ec setting winlock off    # 解锁
```

通过 EC[1895] bit0 触发 toggle，状态在 EC[1896] bit0。

### Fn 锁

```bash
sudo uv run ec setting fnlock on      # 锁定 Fn 键
sudo uv run ec setting fnlock off     # 解锁
```

直接写 EC[1870] bit4。

### USB 关机充电

```bash
sudo uv run ec setting usbchg on      # 开启关机 USB 充电
sudo uv run ec setting usbchg off     # 关闭
```

直接写 EC[1895] bit4（RMW）。

### AC Recovery（来电自动开机）

```bash
sudo uv run ec setting acrecov on     # 开启
sudo uv run ec setting acrecov off    # 关闭
```

自动设置 ApExistFlag（EC[1857] bit0），然后写 EC[1830] bit3。
这是 BIOS 不支持 NVRAM 时的 fallback 路径；支持时应走 NVRAM。

---

## ec bat — 充电控制（电池寿命保护与限制电压）

通过 EC[1977] 与 EC[1958] 寄存器直接设置电池的充电上限百分比与限制电压模式。

### 查看充电限制状态

```bash
sudo uv run ec bat status
```

输出当前充电限制上限（setc，`EC[1977]`）、限制电压模式（setv，`EC[1958]`），以及实时电池信息。

### 设置充电上限百分比 (setc)

```bash
sudo uv run ec bat setc <limit>
```

其中 `<limit>` 为 0-100 的整数（写入时保留 `EC[1977]` bit7，并确保 `EC[1857]` bit0 的 `ApExistFlag` 处于开启状态）：
- `0`：恢复默认的 100% 充电上限。
- `1-100`：设置具体的充电限制百分比（例如设置 `80` 表示充电至 80% 即停止）。

### 设置限制电压模式 (setv)

```bash
sudo uv run ec bat setv <mode>
```

通过设置 `EC[1958]` 的 bits [5:4] 来限制电池的充电截止电压（写入时保留触控板 LED 等其他 bit 状态）：
- `capacity`：高电量模式 (100% 电压上限，bits [5:4] = `00`)。
- `balanced`：均衡模式 (~80% 电压上限，bits [5:4] = `01`)。
- `stationary`：固定保养模式 (~60% 电压上限，bits [5:4] = `10`)。

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
