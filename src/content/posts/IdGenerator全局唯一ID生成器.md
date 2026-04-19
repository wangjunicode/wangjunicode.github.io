---
title: 08 IdGenerator 全局唯一 ID 生成器
published: 2024-01-01
description: "08 IdGenerator 全局唯一 ID 生成器 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 08 IdGenerator 全局唯一 ID 生成器

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

在游戏系统中，每个实体都需要一个唯一标识符（ID）来区分彼此。ID 的设计直接影响：

- **数据库存储**：ID 是主键，决定查询效率
- **网络通信**：客户端和服务端通过 ID 引用同一实体
- **分布式环境**：多个服务进程必须生成不重复的 ID

本框架的 `IdGenerater` 是一个**时间+进程+序号**编码的全局唯一 ID 生成器，提供三类 ID：

| ID 类型 | 方法 | 用途 | 编码结构 |
|---|---|---|---|
| `Id` | `GenerateId()` | Entity 业务 ID（当前简化为自增） | 自增 long |
| `InstanceId` | `GenerateInstanceId()` | Entity 运行时 ID | 时间(28bit)+进程(18bit)+序号(18bit) |
| `UnitId` | `GenerateUnitId(zone)` | 游戏单元（玩家/怪物）ID | 时间(30bit)+区(10bit)+进程模式(8bit)+序号(16bit) |

**核心文件**：`X:\UnityProj\Assets\Scripts\Core\IdGenerater\IdGenerater.cs`

---

## 2. 架构设计

### 2.1 ID 的位域编码原理

所有 ID 都是 `long`（64位有符号整数），通过位运算将多个字段打包进去：

```
InstanceIdStruct（64bit）：
┌─────────────────────────────┬──────────────────┬──────────────────┐
│  Time (28bit)               │  Process (18bit)  │  Value (18bit)   │
│  本年起的秒数（8年容量）    │  进程号           │  同秒内序号      │
└─────────────────────────────┴──────────────────┴──────────────────┘
  bit 63 ~ 36                   bit 35 ~ 18         bit 17 ~ 0

IdStruct（64bit）：
┌─────────────────────────────────┬──────────────────┬────────────────┐
│  Time (30bit)                   │  Process (18bit)  │  Value (16bit)│
│  2020年起的秒数（34年容量）     │  进程号           │  同秒序号     │
└─────────────────────────────────┴──────────────────┴────────────────┘
  bit 63 ~ 34                       bit 33 ~ 16         bit 15 ~ 0

UnitIdStruct（64bit）：
┌──────────────────┬──────────────┬────────────────┬────────────────┐
│  Time (30bit)    │  Zone (10bit)│ ProcessMode(8b)│  Value (16bit)│
│  2020年起的秒数  │  分区号(1024)│  进程%256      │  同秒序号     │
└──────────────────┴──────────────┴────────────────┴────────────────┘
  bit 63 ~ 34         bit 33 ~ 24    bit 23 ~ 16      bit 15 ~ 0
```

### 2.2 单例与时间基准

```
IdGenerater（Singleton）
├── epoch2020: long      ← 2020-01-01 的毫秒时间戳（IdStruct/UnitId 基准）
├── epochThisYear: long  ← 本年1月1日的毫秒时间戳（InstanceId 基准）
│
├── 状态（InstanceId）
│    ├── lastInstanceIdTime: uint  ← 上一次生成的时间点（秒）
│    └── instanceIdValue: uint     ← 当前秒内的序号
│
├── 状态（Id）
│    ├── lastIdTime: uint          ← 上一次生成的时间点（秒）
│    ├── value: ushort             ← 当前秒内的序号
│    └── _selfAddId: long          ← 简化版：自增 ID
│
└── 状态（UnitId）
     ├── lastUnitIdTime: uint
     └── unitIdValue: ushort
```

---

## 3. 核心代码展示

### 3.1 IdStruct —— 位域结构体

```csharp
// X:\UnityProj\Assets\Scripts\Core\IdGenerater\IdGenerater.cs

[StructLayout(LayoutKind.Sequential, Pack = 1)]
public struct IdStruct
{
    public uint   Time;    // 30bit：2020年起的秒数，可容纳约34年
    public int    Process; // 18bit：进程号，支持 262144 个进程
    public ushort Value;   // 16bit：同秒内序号，每秒每进程最多 65535 个

    // 将三个字段打包成一个 long
    public long ToLong()
    {
        ulong result = 0;
        result |= this.Value;                        // bit 15~0
        result |= (ulong)this.Process << 16;          // bit 33~16
        result |= (ulong)this.Time    << 34;          // bit 63~34
        return (long)result;
    }

    // 从 long 解包（调试/分析用）
    public IdStruct(long id)
    {
        ulong result = (ulong)id;
        this.Value   = (ushort)(result & ushort.MaxValue);       // 取低 16bit
        result >>= 16;
        this.Process = (int)(result & IdGenerater.Mask18bit);    // 取 18bit
        result >>= 18;
        this.Time    = (uint)result;                              // 取剩余高位
    }
}
```

### 3.2 InstanceIdStruct —— 运行时 ID 结构

```csharp
[StructLayout(LayoutKind.Sequential, Pack = 1)]
public struct InstanceIdStruct
{
    public uint Time;   // 28bit：本年起的 tick（秒），约 8 年容量
    public int  Process; // 18bit：进程号
    public uint Value;  // 18bit：同秒内序号（比 IdStruct 更大，避免运行时溢出）

    public long ToLong()
    {
        ulong result = 0;
        result |= this.Value;                         // bit 17~0
        result |= (ulong)this.Process << 18;          // bit 35~18
        result |= (ulong)this.Time    << 36;          // bit 63~36
        return (long)result;
    }

    public InstanceIdStruct(long id)
    {
        ulong result  = (ulong)id;
        this.Value    = (uint)(result & IdGenerater.Mask18bit);
        result >>= 18;
        this.Process  = (int)(result & IdGenerater.Mask18bit);
        result >>= 18;
        this.Time     = (uint)result;
    }

    // 给 SceneId 使用：Time=0（不需要时间分量）
    public InstanceIdStruct(int process, uint value)
    {
        this.Time = 0;
        this.Process = process;
        this.Value = value;
    }
}
```

### 3.3 GenerateInstanceId() —— 运行时 ID 生成

```csharp
public long GenerateInstanceId()
{
    uint time = TimeSinceThisYear();  // 本年起的秒数

    if (time > this.lastInstanceIdTime)
    {
        // 进入新的一秒：重置序号
        this.lastInstanceIdTime = time;
        this.instanceIdValue = 0;
    }
    else
    {
        // 同一秒内：序号递增
        ++this.instanceIdValue;

        if (this.instanceIdValue > IdGenerater.Mask18bit - 1) // 18bit 上限
        {
            // 当前秒内序号满了：借用下一秒
            ++this.lastInstanceIdTime;
            this.instanceIdValue = 0;
            Log.Error($"instanceid count per sec overflow: {time} {this.lastInstanceIdTime}");
        }
    }

    // 打包成 long（Process 硬编码为 1，单机客户端场景）
    InstanceIdStruct instanceIdStruct = new InstanceIdStruct(
        this.lastInstanceIdTime, 1, this.instanceIdValue);
    return instanceIdStruct.ToLong();
}

private uint TimeSinceThisYear()
{
    // (当前毫秒时间戳 - 本年1月1日毫秒) / 1000 → 秒数
    return (uint)((TimeInfo.Instance.FrameTime - this.epochThisYear) / 1000);
}
```

### 3.4 GenerateId() —— 业务 ID 生成（当前简化版）

```csharp
public long GenerateId()
{
    // 当前实现：简单自增（单机客户端足够用）
    _selfAddId++;
    return _selfAddId;

    // 注释掉的原版：基于时间+进程+序号编码（分布式服务端适用）
    // uint time = TimeSince2020();
    // if (time > this.lastIdTime) { ... }
    // IdStruct idStruct = new IdStruct(this.lastIdTime, 1, value);
    // return idStruct.ToLong();
}
```

### 3.5 UnitIdStruct —— 游戏单元 ID（含分区）

```csharp
[StructLayout(LayoutKind.Sequential, Pack = 1)]
public struct UnitIdStruct
{
    public uint   Time;        // 30bit：2020年起的秒数（34年）
    public ushort Zone;        // 10bit：分区号（最多1024个区）
    public byte   ProcessMode; // 8bit：Process % 256（一个区内最多256个进程）
    public ushort Value;       // 16bit：每秒每进程最多16K个Unit

    public long ToLong()
    {
        ulong result = 0;
        result |= this.Value;
        result |= (uint)this.ProcessMode << 16;
        result |= (ulong)this.Zone       << 24;
        result |= (ulong)this.Time       << 34;
        return (long)result;
    }

    // 从 UnitId 中快速提取分区号（无需完整解包）
    public static int GetUnitZone(long unitId)
    {
        return (int)((unitId >> 24) & 0x03ff); // 取 10bit
    }
}

public long GenerateUnitId(int zone)
{
    if (zone > MaxZone)
        throw new Exception($"zone > MaxZone: {zone}");

    uint time = TimeSince2020();
    if (time > this.lastUnitIdTime)
    {
        this.lastUnitIdTime = time;
        this.unitIdValue = 0;
    }
    else
    {
        ++this.unitIdValue;
        if (this.unitIdValue > ushort.MaxValue - 1)
        {
            this.unitIdValue = 0;
            ++this.lastUnitIdTime;
            Log.Error($"unitid count per sec overflow: {time} {this.lastUnitIdTime}");
        }
    }

    UnitIdStruct unitIdStruct = new UnitIdStruct(zone, 1, this.lastUnitIdTime, this.unitIdValue);
    return unitIdStruct.ToLong();
}
```

---

## 4. ID 类型的选择与使用场景

### 4.1 何时用 Id

```csharp
// Entity 的 child 节点，需要在 children 字典中被索引
entity.AddChild<T>();          // 框架自动调用 GenerateId()
entity.AddChildWithId<T>(id);  // 手动指定 Id（从数据库恢复时）
```

- 玩家的道具、怪物的技能、地图上的场景对象
- 需要持久化存储到数据库的 Entity

### 4.2 何时用 InstanceId

```csharp
// 由框架在 Domain 设置时自动生成，无需手动调用
this.InstanceId = IdGenerater.Instance.GenerateInstanceId();
```

- EventSystem 的 `allEntities` 字典中的键
- `IsDisposed` 判断（InstanceId == 0 表示已销毁）
- 运行时引用，不持久化，进程重启后重新生成

### 4.3 何时用 UnitId

```csharp
// 在多区游戏中创建玩家 Unit
long playerId = IdGenerater.Instance.GenerateUnitId(zone: 1);
```

- 多区服务端环境中，需要通过 ID 直接解析出所在分区
- 玩家、NPC 等核心游戏单元

---

## 5. 位运算解包示例

当你拿到一个 InstanceId，可以反向解包出各字段：

```csharp
long instanceId = someEntity.InstanceId;
InstanceIdStruct parsed = new InstanceIdStruct(instanceId);

Log.Info($"Time={parsed.Time}, Process={parsed.Process}, Value={parsed.Value}");
// 输出示例：Time=15234567, Process=1, Value=42
```

这在调试分布式问题时非常有用——通过 ID 直接知道它是哪个进程在什么时间生成的。

---

## 6. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| GenerateId | 时间+进程+序号编码 | **简化为自增**（客户端单机场景） |
| GenerateInstanceId | 相同位域结构 | 相同 |
| GenerateUnitId | 有 | 有 |
| 时间基准 | epoch2015（服务端更早） | epoch2020（客户端项目启动较晚） |
| epochThisYear | 以本年为基准（InstanceId 28bit可容纳8年） | 相同 |
| Mask18bit | 0x03ffff | 相同 |
| 进程号 | 多进程（Process=1/2/3...） | 硬编码为1（单客户端） |

---

## 7. 容量估算

### 7.1 InstanceId 容量估算

```
时间字段(28bit) = 2^28 秒 ≈ 268,435,456 秒 ≈ 8.5年
序号字段(18bit) = 2^18 = 262,144 个/秒/进程
→ 每秒最多生成 26万个 InstanceId（实际游戏中远达不到此量级）
```

### 7.2 GenerateId 的简化权衡

原版按时间+进程编码的 Id 适用于分布式场景（多服务进程并行生成不重复 Id）。本项目简化为自增 long，因为：

1. 纯客户端场景不存在多进程并发生成
2. 自增 ID 更简单，性能更好（无时间查询开销）
3. `long` 最大值 ~9.2×10¹⁸，正常游戏寿命内不会溢出

---

## 8. 常见问题与最佳实践

### Q1：两个 Entity 的 Id 相同但 InstanceId 不同，是正常现象吗？

是正常的。Component 的 Id 与宿主 Entity 相同（用于数据库关联），但每次运行创建时都会有唯一的 InstanceId。

### Q2：如何判断一个 Id 是否为 InstanceId？

InstanceId 使用 `epochThisYear`（本年起算）作为时间基准，Time 字段值较小；Id 使用 `epoch2020`（2020年起算），Time 值较大。在调试时可以通过解包来区分。

### Q3：自增 Id 在什么情况下会出问题？

```csharp
// 危险场景：从服务端恢复数据时，服务端发来的 Id 可能与本地自增 Id 冲突
// 解决方案：客户端的自增 Id 从一个较高起点开始，或与服务端 Id 使用不同命名空间
```

### Q4：GenerateInstanceId 为什么不加锁？

```csharp
// 因为整个框架是单线程模型，所有操作都在主线程上执行，无需锁保护
// 如果未来要支持多线程，需要在此添加 lock 或使用 Interlocked
```

---

## 9. 总结

IdGenerater 提供了三种针对不同场景优化的 ID 生成策略：

- **InstanceId**：运行时标识，位域编码保证唯一性，用于 EventSystem 的全局注册表
- **Id**：业务标识，当前简化为自增，满足单机客户端需求
- **UnitId**：分布式多区场景的游戏单元 ID，ID 中编码了分区信息

理解 ID 的位域编码设计，能帮助你在调试时快速分析对象的来源和创建时间。
