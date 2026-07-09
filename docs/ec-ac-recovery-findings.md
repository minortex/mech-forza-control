# AC Recovery (来电自动开机) 实测记录

## 背景

开机后插入 AC 电源适配器时，笔记本是否自动开机。
官方 GCU Service 对此功能通过两条路径实现，由 `NVRAM_STRUCT.ACRecoverySupport` 字段决定。

## 反编译结论

| 条件 | 路径 |
|------|------|
| `NVRAM_STRUCT.ACRecoverySupport == 1` | 写 UEFI NVRAM（`SetFwVars("ACRecoveryStatus", 0/1)`） |
| `ACRecoverySupport != 1` | 写 EC fallback（`EC[1830] bit3`） |

详见 [docs/ec-setting-controls.md](ec-setting-controls.md) 的"来电自动开机"一节。

## 实测发现

### 1. `ACRecoverySupport = 0`（EC fallback 路径）

通过读取 UEFI 变量 `UniWillVariable` 解析 `NVRAM_STRUCT` 得到：

```
ACRecoverySupport (offset 94) = 0x00
ACRecoveryStatus  (offset 95) = 0x00
```

说明这台机器的 BIOS **不支持** NVRAM 持久化路径，只能走 EC fallback。

### 2. `UniWillVariable` — 对应的 UEFI 变量

| 项目 | 值 |
|------|-----|
| 变量名 | `UniWillVariable` |
| GUID | `9f33f85c-13ca-4fd1-9c4a-96217722c593` |
| 总大小 | 184 字节（前 4 字节 EFI attr，后 180 字节 struct） |
| struct 偏移 | `NVRAM_STRUCT` 的 Marshal 内存布局 |

结构体重合校验通过：

| 字段 | 偏移 | 值 | 预期 |
|------|------|-----|------|
| `OemBoardSsid` | 0 | `0x137d1d05` | uint32 |
| `ProjectID` | 6 | `0x1a` (26) | byte |
| `PowerMode` | 47 | `0x01` (1=Gaming) | byte |
| `ApExistFlag` | 93 | `0x00` | byte，AP 未标记 |
| `ACRecoverySupport` | 94 | `0x00` | byte，不支持 |
| `ACRecoveryStatus` | 95 | `0x00` | byte，关闭 |
| `FnKeyStatus` | 102 | `0x00` | byte，未锁定 |

### 3. 写入 UEFI 变量的权限限制与持久性验证

efivarfs 即使 mount 为 rw，每个 efivar 文件默认带了 immutable 属性：

```bash
$ lsattr /sys/firmware/efi/efivars/UniWillVariable-*
----i----------------- UniWillVariable-9f33f85c-...
```

使用 `efivar --write` 可以绕过。

**实测结果：NVRAM 写入未持久化**

```
$ sudo uv run tools/ec_acrecov_test.py nvram on
[NVRAM] ACRecoveryStatus: 0 -> 1 (via efivar)
$ sudo uv run tools/ec_acrecov_test.py nvram on
[NVRAM] ACRecoveryStatus: 0 -> 1 (via efivar)
```

`efivar --write` 返回 0（成功），但每次读回仍为 0。结论：UEFI 固件拒绝了写入。

### 4. 缺失的前置条件：ApExistFlag（EC[1857] bit0）

反编译 `MyEcCtrl.cs` 发现关键方法 `Set_APExistToEC()`：

```csharp
public void Set_APExistToEC(bool bExist) {
    // 读 EC[1857], set/clear bit0, 写回
    if (bExist) b |= 1; else b &= 254;
    this.Write(..., 1857, b);
}
```

Windows GCU Service 启动时（`EnableByService` → `syncBiosSettings`）会调用 `Set_APExistToEC(true)`，设 `EC[1857] bit0=1` 通知 EC 上层服务在线。

**首次 Linux 直写 EC[1830] bit3 失败原因：** EC 在没有收到 ApExistFlag 的情况下忽略了 1830 的写入。需要先写 1857 bit0=1，再写 1830 bit3，EC 才会接受。

测试脚本 `tools/ec_acrecov_test.py` 已更新：`ec` 和 `both` 路径会在写 AC Recovery 字节前自动设 `ApExistFlag=1`。

### 5. 测试工具

`tools/ec_acrecov_test.py` 提供三种测试路径：

| 命令 | 操作内容 |
|------|----------|
| `ec on\|off` | 设 EC[1857] bit0=1 → 写 EC[1830] bit3 |
| `nvram on\|off` | 写 UniWillVariable ACRecoveryStatus（用 efivar） |
| `both on\|off` | 两条路径同时 |

每次操作后必须**完全关机（不重启）**，拔 AC → 插 AC 观察。

## 后续建议

1. **测试 EC fallback + ApExistFlag** — 运行 `ec on`，关机，插 AC 测试。
2. **NVRAM 路径结论** — `efivar --write` 返回成功但值不持久化，除外仅文档记录，实际操作无效。
3. **验收后整合** — 如果 `ec on` 工作，把 ApExistFlag + EC[1830] 逻辑合入 `ec.setting` 模块。
4. **注意点** —
   - efivar 文件每次重启后重设 immutable 属性。
   - EC[1830] bit7 同时被 mode 切换用于 custom 模式标志，写 AC Recovery 时用 RMW。
   - ApExistFlag 设了之后不需要清，EC 侧的 GCU 服务标志不影响其他操作。
