---
title: 游戏框架TimeInfo与TimeHelper时间系统——客户端帧时间与服务器同步差值的双轨设计解析
published: 2026-04-27
description: 深入解析ET框架中TimeInfo单例与TimeHelper静态工具类的协作设计：帧时间冻结机制、服务器/客户端双轨时间、时区支持与ISingletonFixedUpdate驱动的时间同步体系。
tags: [Unity, ECS, 游戏框架, 时间系统, 源码解析]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

在游戏开发中，"时间"是一个看似简单却暗藏陷阱的基础设施。客户端时间和服务器时间之间存在差值；每帧需要一个**固定快照**而非每次调用都触发系统调用；时区问题也会导致日期相关功能出现诡异Bug。

ET框架通过 `TimeInfo`（单例）与 `TimeHelper`（静态代理）的双层设计，优雅地解决了上述问题。本文将结合源码逐行剖析这套时间系统的设计哲学。

---

## 整体架构

```
TimeHelper（静态API）
    └── 代理 TimeInfo.Instance（单例）
            ├── ClientNow()      // 客户端当前时间（线程安全）
            ├── ServerNow()      // 服务器时间 = 客户端 + 差值
            ├── FrameTime        // 帧快照时间（每帧固定）
            ├── ClientFrameTime()
            ├── ServerFrameTime()
            └── ISingletonFixedUpdate // 由FixedUpdate驱动更新FrameTime
```

两个类的职责分工清晰：
- **TimeInfo**：持有状态、执行计算、对外暴露精确时间
- **TimeHelper**：无状态静态工具，对业务层隐藏单例细节，提供便捷调用入口

---

## TimeInfo 源码解析

### 1. 时间基准点与时区

```csharp
public readonly DateTime dt1970;
private DateTime dt;

public TimeInfo()
{
    this.dt1970 = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    this.dt = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    this.FrameTime = this.ClientNow();
}

public int TimeZone
{
    get => this.timeZone;
    set
    {
        this.timeZone = value;
        dt = dt1970.AddHours(TimeZone);  // 时区修正
    }
}
```

`dt1970` 是**只读常量**，永远表示 UTC 1970-01-01，用于 `ClientNow()` 的时间戳计算。

`dt` 是**可变基准**，随时区偏移。当 `TimeZone` 被设置时，`dt` 会向后偏移对应小时数，这样 `Transition(DateTime d)` 转换本地时间戳时会自动包含时区。

> **注意**：`ClientNow()` 不使用 `dt`，始终基于 `dt1970`，所以它是纯 UTC 毫秒时间戳，不受时区影响。时区只影响 `ToDateTime` 和 `Transition` 这两个日期转换方法。

### 2. 线程安全的 ClientNow

```csharp
// 线程安全
public long ClientNow()
{
    return ((DateTime.UtcNow).Ticks - this.dt1970.Ticks) / 10000;
}
```

这行代码每次调用都执行一次 `DateTime.UtcNow` 系统调用，返回当前 UTC 时间距 1970-01-01 的**毫秒数**。

- `Ticks` 精度为 100纳秒，除以 10000 得到毫秒
- `DateTime.UtcNow` 在 .NET 中是线程安全的
- 每次调用结果都不同，反映真实流逝时间

### 3. 服务器时间差值

```csharp
public long ServerMinusClientTime { private get; set; }

public long ServerNow()
{
    return ClientNow() + Instance.ServerMinusClientTime;
}
```

`ServerMinusClientTime` 由网络层在登录或心跳时写入，表示**服务器时间 - 客户端时间**的差值（可正可负）。

服务器时间 = 客户端本地时间 + 差值，这是客户端游戏中最常见的时间同步方案。框架将"如何获取差值"完全解耦，网络模块只需写入这个字段，其余代码无感知。

### 4. 帧时间快照机制

```csharp
public long FrameTime;

public void Update()
{
    this.FrameTime = this.ClientNow();
}

public long ClientFrameTime()
{
    return this.FrameTime;
}

public long ServerFrameTime()
{
    return this.FrameTime + Instance.ServerMinusClientTime;
}
```

`FrameTime` 是**帧快照**：在每帧开始时由 `ISingletonFixedUpdate.BeforeFixedUpdate` 刷新一次，同一帧内所有对 `ClientFrameTime()` 的调用都返回相同值。

**为什么需要帧时间？**

```
// 错误做法：同一帧内多次调用，时间不一致
long t1 = TimeHelper.ClientNow(); // 比如 1000ms
// ... 一些逻辑 ...
long t2 = TimeHelper.ClientNow(); // 可能是 1001ms（差了1ms）
// t1 != t2，逻辑出现细微不一致
```

```
// 正确做法：帧快照
long t1 = TimeHelper.ClientFrameTime(); // 1000ms（帧开始时的快照）
// ... 一些逻辑 ...
long t2 = TimeHelper.ClientFrameTime(); // 1000ms（同一帧，同一值）
// t1 == t2，逻辑一致
```

对于定时器触发、倒计时显示等需要"这一帧的时间"的场景，`FrameTime` 是首选。

### 5. ISingletonFixedUpdate 驱动

```csharp
public class TimeInfo: Singleton<TimeInfo>, ISingletonFixedUpdate
{
    public void BeforeFixedUpdate()
    {
        Update();  // 每个物理帧开始前刷新 FrameTime
    }

    public void FixedUpdate() { }
    public void LateFixedUpdate() { }
}
```

`TimeInfo` 实现了 `ISingletonFixedUpdate` 接口，由框架的物理更新循环驱动。`BeforeFixedUpdate` 是物理帧的最早阶段，确保 `FrameTime` 在任何游戏逻辑执行之前就已更新到本帧的时间值。

---

## TimeHelper 源码解析

```csharp
public static class TimeHelper
{
    public const long OneDay  = 86400000;  // 一天的毫秒数
    public const long Hour    = 3600000;   // 一小时的毫秒数
    public const long Minute  = 60000;     // 一分钟的毫秒数

    public static long ClientNow()        => TimeInfo.Instance.ClientNow();
    public static long ClientNowSeconds() => ClientNow() / 1000;
    public static DateTime DateTimeNow()  => DateTime.Now;
    public static long ServerNow()        => TimeInfo.Instance.ServerNow();
    public static long ClientFrameTime()  => TimeInfo.Instance.ClientFrameTime();
    public static long ServerFrameTime()  => TimeInfo.Instance.ServerFrameTime();
}
```

**TimeHelper 的价值不在于复杂逻辑，而在于：**

1. **常量聚合**：`OneDay`、`Hour`、`Minute` 统一定义，消除魔法数字
2. **API统一入口**：业务代码 `using` 时只需记住 `TimeHelper`，不用关心 `TimeInfo.Instance`
3. **可测试性**：Mock `TimeHelper` 比直接 Mock 系统时间更容易
4. **`ClientNowSeconds()`**：直接返回秒级时间戳，省去除法运算

---

## 两种时间 vs 两种精度

| API | 精度 | 每帧变化 | 适用场景 |
|-----|------|----------|----------|
| `ClientNow()` | 毫秒 | 每次调用不同 | 精确计时、性能测量 |
| `ClientFrameTime()` | 毫秒 | 同帧相同 | 定时器、倒计时、帧逻辑 |
| `ServerNow()` | 毫秒 | 每次调用不同 | 服务端时间展示 |
| `ServerFrameTime()` | 毫秒 | 同帧相同 | 帧同步逻辑校验 |
| `ClientNowSeconds()` | 秒 | 每次调用不同 | 签到、活动截止判断 |

**选择原则：**
- 需要"这一帧统一的时间基准" → `FrameTime` 系列
- 需要"精确的当前实际时间" → `ClientNow` 系列
- 涉及服务端数据、活动、倒计时 → `Server` 系列

---

## ToDateTime 与 Transition 的时区转换

```csharp
// 时间戳 → DateTime（受时区影响）
public DateTime ToDateTime(long timeStamp)
{
    return dt.AddTicks(timeStamp * 10000);
}

// DateTime → 时间戳（受时区影响）
public long Transition(DateTime d)
{
    return (d.Ticks - dt.Ticks) / 10000;
}
```

当 `TimeZone = 8`（东八区）时，`dt = 1970-01-01 08:00:00`。

- `ToDateTime(0)` 返回 `1970-01-01 08:00:00`（北京时间）
- `Transition(new DateTime(1970, 1, 1, 8, 0, 0))` 返回 `0`

这使得时间戳和本地时间可以无缝互转，日历系统、签到逻辑等功能直接调用这两个方法即可，无需手动处理时区。

---

## 实战使用模式

### 倒计时判断（推荐用 FrameTime）

```csharp
// 活动截止时间（服务器时间）
long endTime = serverResponse.EndTime;

// 每帧检查（用帧快照，同帧逻辑一致）
bool IsExpired() => TimeHelper.ServerFrameTime() >= endTime;
```

### 性能计时（用 ClientNow）

```csharp
long start = TimeHelper.ClientNow();
DoHeavyWork();
long elapsed = TimeHelper.ClientNow() - start;
Log.Info($"耗时: {elapsed}ms");
```

### 服务器时间校准（网络层写入）

```csharp
// 收到服务器心跳包时
void OnHeartbeatResponse(long serverTimestamp)
{
    long clientNow = TimeHelper.ClientNow();
    TimeInfo.Instance.ServerMinusClientTime = serverTimestamp - clientNow;
}
```

---

## 设计总结

ET框架的时间系统展示了一个优秀基础设施的几个关键特质：

1. **职责分离**：`TimeInfo` 管状态，`TimeHelper` 管接口，各司其职
2. **帧快照隔离**：`FrameTime` 保证同帧时间一致性，消除微小时间差引发的逻辑错误
3. **服务器时间解耦**：差值由外部注入，时间模块不关心网络细节
4. **时区显式管理**：时区作为可配置属性，而非隐式系统依赖
5. **线程安全**：`ClientNow()` 直接调用线程安全的 `DateTime.UtcNow`，无需额外锁

下次在游戏里需要处理时间时，不妨思考：这里需要的是"这一帧的固定基准"还是"精确的当前时刻"？答案往往决定了你该用哪个API。
