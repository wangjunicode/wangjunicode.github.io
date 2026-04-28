---
title: 游戏框架TimeInfo单例时间系统设计-客户端与服务端时钟同步的精妙实现
published: 2026-04-28
description: 深入解析游戏框架中TimeInfo单例的设计原理，包括客户端本地时钟、服务端时间校准、帧时间快照、时区处理，以及为何要用ISingletonFixedUpdate而非Update来驱动时间帧。
tags: [Unity, 游戏框架, 时间系统, 客户端服务端同步, ECS, 单例, CSharp]
category: Unity
encryptedKey: henhaoji123
draft: false
---

## 概述

在网络游戏开发中，时间管理是一个看似简单却暗藏玄机的模块。每帧调用一次 `DateTime.UtcNow` 代价不低，客户端时间与服务端时间存在偏差，多线程场景需要线程安全的时间查询……这些问题都需要一个专门的时间单例来统一处理。

本文从 `TimeInfo.cs` 源码出发，逐行拆解这个"游戏世界的时钟"是如何设计的。

---

## 核心数据结构

```csharp
public class TimeInfo : Singleton<TimeInfo>, ISingletonFixedUpdate
{
    private int timeZone;
    public readonly DateTime dt1970;
    private DateTime dt;
    public long ServerMinusClientTime { private get; set; }
    public long FrameTime;
}
```

### 字段解析

| 字段 | 类型 | 作用 |
|------|------|------|
| `timeZone` | int | 时区偏移（小时数），影响 `dt` 基准时间 |
| `dt1970` | DateTime | UTC 1970-01-01，用于计算客户端时间戳，**只读** |
| `dt` | DateTime | 受时区影响的基准时间，用于时间戳转 DateTime |
| `ServerMinusClientTime` | long | 服务端与客户端时间差（ms），外部只写，内部只读 |
| `FrameTime` | long | 每帧起点时间戳（ms），避免帧内多次调用系统时钟 |

---

## 时区的精妙处理

```csharp
public int TimeZone
{
    get => this.timeZone;
    set
    {
        this.timeZone = value;
        dt = dt1970.AddHours(TimeZone);
    }
}
```

**为什么要维护两个 DateTime？**

- `dt1970`：永远是 UTC 0点，用于毫秒时间戳计算（不受时区影响）
- `dt`：加了时区偏移的基准时间，用于将毫秒时间戳还原为本地 DateTime

这样 `ClientNow()` 永远基于 UTC 计算，保证多端一致性；而 `ToDateTime()` 时才考虑时区，实现逻辑与展示的分离。

---

## 四种时间接口设计

### 1. ClientNow - 线程安全的真实时钟

```csharp
public long ClientNow()
{
    return ((DateTime.UtcNow).Ticks - this.dt1970.Ticks) / 10000;
}
```

- 基于 `DateTime.UtcNow` 计算 Unix 时间戳（毫秒）
- `Ticks` 是 100纳秒单位，除以 10000 转为毫秒
- 注释写明"线程安全"，因为 `DateTime.UtcNow` 本身是线程安全的

### 2. ServerNow - 带服务器校准的时间

```csharp
public long ServerNow()
{
    return ClientNow() + Instance.ServerMinusClientTime;
}
```

客户端与服务端时钟不可能完全同步，通过握手阶段计算 `ServerMinusClientTime`（服务端时间 - 客户端时间），之后所有需要"服务端时间"的场合只需加上这个偏移量即可。

### 3. ClientFrameTime / ServerFrameTime - 帧快照时间

```csharp
public long ClientFrameTime() => this.FrameTime;
public long ServerFrameTime() => this.FrameTime + Instance.ServerMinusClientTime;
```

`FrameTime` 是每帧开始时拍下的快照，**一帧之内所有逻辑使用同一个时间基准**，避免帧内时间漂移问题。

### 4. ToDateTime - 时间戳转可读时间

```csharp
public DateTime ToDateTime(long timeStamp)
{
    return dt.AddTicks(timeStamp * 10000);
}
```

毫秒时间戳 → DateTime，用于显示、日志、存档等场景。

---

## ISingletonFixedUpdate 驱动 FrameTime 更新

```csharp
public void BeforeFixedUpdate()
{
    Update();  // 每个物理帧前更新 FrameTime
}

public void FixedUpdate() { }
public void LateFixedUpdate() { }

private void Update()
{
    this.FrameTime = this.ClientNow();
}
```

**关键设计问答：为什么用 `ISingletonFixedUpdate` 而不是 `ISingletonUpdate`？**

游戏的战斗逻辑通常运行在固定帧率（Fixed Update）上，而非渲染帧（Update）上。时间系统必须与战斗逻辑帧对齐，在 `BeforeFixedUpdate` 阶段最先更新 `FrameTime`，确保当帧所有战斗计算使用一致的时间基准。

若改用 `ISingletonUpdate`，则 `FrameTime` 每渲染帧更新，战斗逻辑帧内可能出现时间不一致的问题。

---

## 构造函数的初始化顺序

```csharp
public TimeInfo()
{
    this.dt1970 = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    this.dt = new DateTime(1970, 1, 1, 0, 0, 0, DateTimeKind.Utc);
    this.FrameTime = this.ClientNow();
}
```

注意三点：

1. `dt1970` 是 `readonly`，只能在构造函数赋值
2. `dt` 初始也是 UTC 零点，未设置时区前与 `dt1970` 相同
3. `FrameTime` 在构造时立即初始化为当前时间，避免首帧出现 0 时间戳的问题

---

## ServerMinusClientTime 的设置时机

```csharp
public long ServerMinusClientTime { private get; set; }
```

这个属性只允许外部写入（set 公开），内部读取（get 私有）。典型的设置时机是：

1. 客户端向服务器发送 `C2S_Ping`
2. 服务器返回 `S2C_Pong`（携带服务器当前时间）
3. 客户端计算：`ServerMinusClientTime = serverTime - clientTime - roundTripTime/2`
4. 赋值给 `TimeInfo.Instance.ServerMinusClientTime`

此后所有调用 `ServerNow()` 的代码都自动得到经过校准的服务器时间。

---

## TimeHelper 工具类：FrameTime 的快速入口

```csharp
public static class TimeHelper
{
    public static long ClientFrameTime() => TimeInfo.Instance.ClientFrameTime();
    public static long ServerFrameTime() => TimeInfo.Instance.ServerFrameTime();
    public static long ClientNow() => TimeInfo.Instance.ClientNow();
    public static long ServerNow() => TimeInfo.Instance.ServerNow();
}
```

`TimeHelper` 是静态工具类，提供便捷的全局调用入口，所有游戏逻辑代码应优先使用 `TimeHelper.ClientFrameTime()` 而非直接访问单例，以保证统一的调用习惯。

---

## 实际应用场景

### 场景一：定时器系统

```csharp
private static long GetNow()
{
    return TimeHelper.ClientFrameTime(); // 使用帧快照时间
}
```

定时器系统使用 `ClientFrameTime()` 而非 `ClientNow()`，确保同一帧触发的所有定时器基准时间一致，避免"同时到期但触发顺序不同导致时间差异"的问题。

### 场景二：服务端时间展示

```csharp
long serverTime = TimeHelper.ServerNow();
DateTime dt = TimeInfo.Instance.ToDateTime(serverTime);
displayText.text = dt.ToString("HH:mm:ss");
```

### 场景三：倒计时计算

```csharp
long remaining = endTime - TimeHelper.ServerNow();
if (remaining <= 0) TriggerEvent();
```

---

## 架构亮点总结

| 设计亮点 | 说明 |
|---------|------|
| 帧快照时间 | `FrameTime` 避免帧内时间漂移，确保一帧内时间一致 |
| 客户端/服务端双时钟 | `ClientNow` 和 `ServerNow` 分开设计，校准逻辑透明化 |
| 时区分离 | 计算用 UTC，显示时才加时区，逻辑与展示解耦 |
| ISingletonFixedUpdate | 时间更新与战斗逻辑帧对齐，而非渲染帧 |
| ServerMinusClientTime 封装 | 服务端时差对外只写，防止业务代码直接依赖偏移量 |

`TimeInfo` 是游戏框架中最底层的基础设施之一，它的正确性直接影响定时器、网络同步、活动系统、倒计时等所有时间相关功能。这种单职责、精确对齐物理帧的设计，值得在自研框架中借鉴。
