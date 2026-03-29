---
title: 全局唯一 ID 的位运算编码方案
published: 2026-03-30
description: "深度解析三种 ID 的位布局设计、借用下一秒机制，以及时间+进程+序号组合保证分布式唯一性的原理。"
tags: [Unity, 框架设计]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

## 为什么这样设计（第一性原理）

ID 生成是分布式系统中最基础也最容易被忽视的问题。最朴素的方案是自增整数，但自增整数有两个致命缺陷：

1. **分布式不唯一**：多个服务器进程同时生成，ID 会冲突
2. **信息密度低**：纯序号无法携带任何业务信息，排查问题时需要再查数据库

**第一性原理的解法**：把一个 64 位长整型（`long`）视为一个**位字段结构体**，把时间戳、进程号、序号等多个维度的信息编码进去。只要各维度组合不重复，ID 就全局唯一。

这与 Twitter 的 Snowflake 算法思路完全一致，但针对游戏业务做了三种差异化设计：`IdStruct`（普通实体）、`InstanceIdStruct`（实例/组件）、`UnitIdStruct`（玩家单位）。

---

## 源码解析

### 1. 三种 ID 的位布局对比

**IdStruct（64位 = 30+18+16）**

```
 63      34 33    16 15       0
 ┌─────────┬────────┬──────────┐
 │  Time   │Process │  Value   │
 │  30bit  │ 18bit  │  16bit   │
 └─────────┴────────┴──────────┘
  自2020年的  进程ID   序号
  秒数

最大表示：约34年 × 262144个进程 × 65536/秒
```

```csharp
public long ToLong()
{
    ulong result = 0;
    result |= this.Value;                        // [15:0]  16bit 序号
    result |= (ulong)this.Process << 16;         // [33:16] 18bit 进程号
    result |= (ulong)this.Time    << 34;         // [63:34] 30bit 时间
    return (long)result;
}
```

**InstanceIdStruct（64位 = 28+18+18）**

```
 63      36 35    18 17       0
 ┌─────────┬────────┬──────────┐
 │  Time   │Process │  Value   │
 │  28bit  │ 18bit  │  18bit   │
 └─────────┴────────┴──────────┘
  自当年年初  进程ID   序号
  的秒数

特点：时间从"当年年初"起算，缩短了时间基准，腾出位给序号（18bit=262143/秒，远高于IdStruct的65536/秒）
```

```csharp
public long ToLong()
{
    ulong result = 0;
    result |= this.Value;                        // [17:0]  18bit 序号
    result |= (ulong)this.Process << 18;         // [35:18] 18bit 进程号
    result |= (ulong)this.Time    << 36;         // [63:36] 28bit 时间
    return (long)result;
}
```

**UnitIdStruct（64位 = 30+10+8+16）**

```
 63      34 33    24 23    16 15       0
 ┌─────────┬────────┬────────┬──────────┐
 │  Time   │  Zone  │Process │  Value   │
 │  30bit  │ 10bit  │  8bit  │  16bit   │
 └─────────┴────────┴────────┴──────────┘
  自2020年   大区号   进程%256  序号
  的秒数
  
最大支持：1024个大区 × 256个进程/区 × 16384个Unit/秒
```

```csharp
public long ToLong()
{
    ulong result = 0;
    result |= this.Value;                            // [15:0]  16bit 序号
    result |= (uint)this.ProcessMode << 16;          // [23:16] 8bit  进程%256
    result |= (ulong)this.Zone       << 24;          // [33:24] 10bit 大区号
    result |= (ulong)this.Time       << 34;          // [63:34] 30bit 时间
    return (long)result;
}
```

### 2. 解码的对称性

编码和解码完全对称，`IdStruct(long id)` 构造函数是 `ToLong()` 的逆操作：

```csharp
public IdStruct(long id)
{
    ulong result = (ulong)id;
    this.Value   = (ushort)(result & ushort.MaxValue);       // 取低16bit
    result >>= 16;
    this.Process = (int)(result & IdGenerater.Mask18bit);    // 取18bit
    result >>= 18;
    this.Time    = (uint)result;                             // 剩余全是Time
}
```

`Mask18bit = 0x03ffff`（即 `0b11_1111_1111_1111_1111`，18个1），用位与来截取固定宽度的位段，是位运算的经典技巧。

这种对称设计使得从 ID 反解出生成时间、进程号等信息变得极其简单，对排查线上问题非常有价值：

```csharp
// 已知一个 InstanceId，立刻知道它是什么时候、哪个进程生成的
var info = new InstanceIdStruct(instanceId);
Log.Info($"生成时间: 当年第{info.Time}秒, 进程: {info.Process}, 序号: {info.Value}");
```

### 3. 借用下一秒机制

这是一个优雅的容错设计，处理"同一秒内序号耗尽"的极端情况：

```csharp
public long GenerateInstanceId()
{
    uint time = TimeSinceThisYear();

    if (time > this.lastInstanceIdTime)
    {
        // 新的一秒，重置序号
        this.lastInstanceIdTime = time;
        this.instanceIdValue = 0;
    }
    else
    {
        // 还在同一秒内，序号递增
        ++this.instanceIdValue;

        if (this.instanceIdValue > IdGenerater.Mask18bit - 1) // 超过 18bit 上限
        {
            ++this.lastInstanceIdTime;  // 借用下一秒！
            this.instanceIdValue = 0;
            Log.Error($"instanceid count per sec overflow: {time} {this.lastInstanceIdTime}");
        }
    }

    InstanceIdStruct instanceIdStruct = 
        new InstanceIdStruct(this.lastInstanceIdTime, 1, this.instanceIdValue);
    return instanceIdStruct.ToLong();
}
```

**借用下一秒的含义**：当前秒内的序号已经用完（超过 262143 个），把时间字段强制 +1，从"逻辑上的下一秒"借用序号空间。这保证了**ID 的全局单调递增性**，不会回滚到已经用过的序号区间。

代价是：如果真的用完了当前秒，接下来实际到达的下一秒的序号会从已借用的偏移继续，`lastInstanceIdTime` 会比实际时间超前。`Log.Error` 是一个明确的报警——正常游戏下每秒生成超过 26 万个实例 ID，说明系统存在严重异常。

### 4. 时间基准的差异化选择

| ID 类型 | 时间基准 | 原因 |
|---------|---------|------|
| IdStruct | 2020年1月1日 | 通用实体，需要跨年度有效，2020是框架起始年 |
| InstanceIdStruct | 当年1月1日 | 实例ID每年刷新基准，28bit能覆盖约8.5年，但实例不需要跨年持久化 |
| UnitIdStruct | 2020年1月1日 | 玩家Unit ID需要长期持久化到数据库，不能年年重置 |

```csharp
// 构造时计算时间基准（单位：毫秒）
this.epoch2020     = new DateTime(2020,1,1,0,0,0,DateTimeKind.Utc).Ticks/10000 - epoch1970tick;
this.epochThisYear = new DateTime(DateTime.Now.Year,1,1,0,0,0,DateTimeKind.Utc).Ticks/10000 - epoch1970tick;

// 生成时取秒数差
private uint TimeSince2020()    => (uint)((TimeInfo.Instance.FrameTime - this.epoch2020) / 1000);
private uint TimeSinceThisYear() => (uint)((TimeInfo.Instance.FrameTime - this.epochThisYear) / 1000);
```

注意：时间戳用的是**帧时间**（`FrameTime`），而不是 `DateTime.Now`。在同一帧内生成的多个 ID，时间字段相同，靠序号区分。这避免了频繁调用系统时钟的开销。

---

## 快速开新项目的方案/清单

### 复用清单

```
Core/IdGenerater/IdGenerater.cs   // 主文件，三种 ID 结构体 + 生成器单例
```

### 三种 ID 的使用场景选择

```csharp
// 场景1：生成普通实体/组件的 InstanceId（进程内唯一，重启后可复用）
long instanceId = IdGenerater.Instance.GenerateInstanceId();

// 场景2：生成玩家 Unit 的持久化 ID（全服唯一，写入数据库）
long unitId = IdGenerater.Instance.GenerateUnitId(zone: 1);

// 场景3：自增 ID（最简单，当前实现直接自增，不含时间信息）
long id = IdGenerater.Instance.GenerateId();
```

### 从 ID 反解信息（用于日志排查）

```csharp
// 解析 InstanceId
var s = new InstanceIdStruct(instanceId);
Debug.Log($"进程:{s.Process} 当年第{s.Time}秒 序号:{s.Value}");

// 解析 UnitId，获取所在大区
int zone = UnitIdStruct.GetUnitZone(unitId);

// 解析 UnitId 完整信息
var u = new UnitIdStruct(unitId);
Debug.Log($"大区:{u.Zone} 进程模:{u.ProcessMode} 时间:{u.Time} 序号:{u.Value}");
```

### 接入新项目步骤

- [ ] 启动时 `Game.AddSingleton<IdGenerater>()`
- [ ] 确认 `TimeInfo.Instance.FrameTime` 能正确返回毫秒级 UTC 时间戳
- [ ] 多进程部署时，确保每个进程有唯一的 Process 编号（通过启动参数传入）
- [ ] 如果有大区概念，`GenerateUnitId(zone)` 传入正确的大区号

### 注意事项

- ✅ `InstanceId` 在进程重启后可以重用（时间会推进，序号会重置）
- ✅ `UnitId` 是玩家的全局持久化 ID，一旦生成不应改变
- ⚠️ `Process` 字段当前实现写死为 `1`，多进程部署时需要修改为从配置读取
- ⚠️ 收到 `overflow` 错误日志时，立即排查是否有 ID 生成循环或实例化泄漏
- ⚠️ `IdStruct.Value` 是 `ushort`（16bit），每秒最多 65535 个普通 ID；`InstanceIdStruct.Value` 是 18bit，每秒最多 262143 个实例 ID
