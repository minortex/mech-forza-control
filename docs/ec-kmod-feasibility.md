# EC 直控 Linux 内核模块可行性分析

> 评估将 GCU EC 控制功能从 Python 用户态迁移到 Linux 内核模块（kmod）的可行性与收益。

## 现状：用户态方案

当前所有功能通过 Python 脚本 +c_sys debugfs 实现：

| 脚本 | 依赖 | 工作方式 |
|------|------|----------|
| ec_switch_mode.py | /sys/kernel/debug/ec/ec0/io | 写字节到 EC |
| ec_kb_backlight.py | 同上 | 写字节到 EC |
| ec_rw.py | 同上或 /dev/port | 字节级读写 |

### 能做的

- 模式切换（Gaming/Office/Turbo/Custom）
- 风扇曲线写入（3840-3935）
- PL/TCC/ApExistFlag 写入
- 键盘背光亮度控制
- 开机自启（systemd service）

### 做不了的

- **键盘背光在空闲超时后自动关、按键自动亮**
  需要监听 evdev 输入事件，Python 起守护进程轮询有延迟且增加功耗。
- **温度触发风扇曲线调整**
  需要轮询 hwmon/	hermal sysfs，调度延迟 ~100ms 起步。

## 内核模块方案

### 混合架构

`
kmod (gcu_core.ko)              ← ~500-600 行 C，只做内核必须做的事
├── sysfs 接口
│   /sys/bus/platform/devices/GCU/
│   ├── operating_mode          ← Gaming/Office/Turbo/Custom
│   ├── backlight_level         ← 0-4
│   ├── backlight_timeout       ← 空闲秒数，0=禁用
│   ├── fan_table_cpu/duty      ← 16 点占空比
│   └── fan_table_gpu/duty      ← 16 点占空比
├── input 事件监听              ← 背光超时自动管理
└── (可选) thermal 通知链        ← 温控风扇

用户态 (Python/C CLI)           ← 其他全部
├── ec_switch_mode.py           ← 写 sysfs operating_mode
├── ec_kb_backlight.py          ← 写 sysfs backlight_*
├── ec_rw.py                    ← 直读 ec_sys debugfs
└── systemd service             ← 开机加载模块 + 恢复上次设置
`

### 各功能的层归属

| 功能 | 放 kmod 的原因 | 放用户态的原因 |
|------|----------------|----------------|
| EC 字节读写 | — | ec_sys debugfs 已有，零收益 |
| 模式切换 | — | 偶尔写一次，sysfs 或 ec_sys 没区别 |
| 风扇表写入 | — | 设好就不动了 |
| PL/TCC/ApExist | — | 一次性的 |
| **键盘背光超时** | 需要 input 子系统监听，用户态做不了 | — |
| **温控风扇** | 需要 thermal 通知链，用户态轮询有延迟 | 也可以用户态做，看精度要求 |
| sysfs 接口层 | 给用户态统一入口 | sysfs 本身就是内核暴露的，ec_sys debugfs 不稳定 |

### 键盘背光超时的实现方案

Python 方案（查表用 evdev 轮询）：

`python
dev = InputDevice('/dev/input/eventX')
for event in dev.read_loop():
    if event.type == ec.EV_KEY:
        ec_write(1932, ec_read(1932) & ~2)  # 开灯
        last_activity = time.time()
    if time.time() - last_activity > timeout:
        ec_write(1932, ec_read(1932) | 2)   # 关灯
`

kmod 方案：

`c
static int gcu_input_event(struct input_handle *handle,
                           unsigned int type, unsigned int code, int value)
{
    if (type == EV_KEY && value) {
        gcu_set_backlight(true);            /* 按键开灯 */
        mod_timer(&kb_timer, jiffies + timeout * HZ);
    }
    return 0;
}
static void kb_timeout(struct timer_list *t)
{
    gcu_set_backlight(false);               /* 超时关灯 */
}
`

差异：kmod 是事件驱动的零延迟回调，Python 需要 
ead_loop() 轮询。

### 温控风扇的实现方案

Python 方案：

`python
while True:
    temp = int(open('/sys/class/thermal/thermal_zone0/temp').read()) / 1000
    duty = lookup_table(temp)
    ec_write(3872 + 1, duty * 2)
    time.sleep(2)
`

kmod 方案：

`c
static int gcu_thermal_notify(struct notifier_block *nb,
                               unsigned long temp, void *dev)
{
    int duty = lookup_table(temp / 1000);
    ec_write_cmd(3872 + 1, duty * 2);       /* 写第二个点 */
    return NOTIFY_OK;
}
`

差异：kmod 通过 	hermal_zone_device_register 注册通知链，温度变化时内核自动回调。Python 轮询间隔 2s，有延迟。

## 风险分析

### 内核模块签名

| 情况 | 影响 |
|------|------|
| Secure Boot ON + 官方发行版 | 需要自己签模块，或关 Secure Boot |
| Secure Boot OFF | 直接 insmod，没问题 |
| 自编译内核 | 没问题 |

大部分笔记本用户默认 Secure Boot 是开的。这个是最大的门槛。

### 内核 API 稳定性

| 子系统 | 稳定性 |
|--------|--------|
| ec_sys | 6.x 内核稳定，但 debugfs 不是稳定 ABI |
| input | 稳定，几十年没大改 |
| 	hermal | 6.x 有重构，通知链接口稳定 |
| sysfs | 稳定 |
| 	imer_list | 稳定 |

### EC 写入安全性

最大风险：**EC 写错了能导致整机断电或硬件损坏**。

缓解措施：
- kmod 内做参数校验（PL/TCC 值范围检查）
- sysfs 写入不直接暴露 raw EC 地址
- 只暴露语义化的接口（"设置温度为 85°C"），不做 ec_write any_addr any_value

### 调试复杂度

| 方式 | kmod | Python |
|------|------|--------|
| print 调试 | printk + dmesg | print() |
| crash 调试 | oops → kexec 或硬重启 | Python traceback → 无事 |
| 开发迭代 | 编译 → insmod → rmmod → 编译 | 直接改.py → 运行 |

开发效率 Python 比 C 高至少 5 倍。

## 结论

| 方案 | 键盘背光超时 | 温控风扇 | 开发成本 | 部署门槛 |
|------|-------------|----------|----------|----------|
| Python 用户态 | 需轮询 evdev | 需轮询 thermal | 低 | 低 |
| kmod 混合 | 原生 input 回调 | 原生 thermal 回调 | 高 | 高 |
| kmod 纯 sysfs 壳 | 仍需要用户态轮询 | 仍需要用户态轮询 | 中 | 高 |

### 建议

**优先走纯用户态路线**。理由：

1. ec_sys debugfs 已经为你做了最核心的 EC 读写
2. Python-evdev 轮询键盘超时够用（笔记本用户不会在开机 15 分钟无操作时还在意 ~1W 功耗差异）
3. 温控风扇用 hwmon 轮询 2-3 秒一次足够了——EC 固件自己本来就有温控，用户态只是辅助
4. kmod 需要 Secure Boot 签名、跨内核版本维护，一个人维护成本太高

**唯一值得迁移的情况**：你需要纯内核态的温控风扇响应（<5ms 延迟），或者用 C 重写只是为了减少 Python 依赖。否则 Python + ec_sys 已经覆盖了 95% 的需求。
