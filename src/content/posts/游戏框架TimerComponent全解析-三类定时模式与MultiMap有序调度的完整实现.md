---
title: 游戏框架TimerComponent全解析-三类定时模式与MultiMap有序调度的完整实现
published: 2026-04-28
description: 深入分析游戏框架TimerComponent的完整实现，包括OnceTimer单次定时、OnceWaitTimer异步等待、RepeatedTimer重复定时三种模式，以及基于MultiMap的高效时间堆调度、TimerAction对象池复用、取消令牌集成等核心设计。
tags: [Unity, 游戏框架, 定时器系统, ETTask, 异步编程, 对象池, CSharp]
category: Unity
encryptedKey: henhaoji123
draft: false
---

## 概述

定时器是游戏框架中使用频率极高的基础设施：技能冷却、BUFF倒计时、延迟特效、轮询检查……无处不在。一个设计优秀的定时器系统需要同时满足：**高频添加/删除的低开销**、**精确触发**、**与异步框架深度集成**、**内存可控**。

本文从 `TimerComponent.cs` 源码出发，完整解析这个定时器系统的每一个设计决策。

---

## 核心数据结构设计

### TimerClass - 三种定时模式

```csharp
public enum TimerClass
{
    None,
    OnceTimer,       // 单次回调，触发后销毁
    OnceWaitTimer,   // 单次异步等待，触发后唤醒协程
    RepeatedTimer,   // 重复定时，自动续期
}
```

三种模式覆盖了游戏开发中 99% 的定时需求：

| 模式 | 使用场景 | 底层机制 |
|------|---------|---------|
| `OnceTimer` | 延迟事件触发、BUFF到期 | EventSystem.Invoke 回调 |
| `OnceWaitTimer` | await 等待 N 毫秒 | ETTask.SetResult 唤醒协程 |
| `RepeatedTimer` | 心跳检测、周期轮询 | 自动续期 + EventSystem.Invoke |

### TimerAction - 带对象池的定时任务描述

```csharp
public class TimerAction
{
    public long Id;
    public TimerClass TimerClass;
    public object Object;    // 回调数据（回调定时器）或 ETTask（等待定时器）
    public long StartTime;
    public long Time;        // 延迟时长（ms）
    public int Type;         // EventSystem 事件类型

    private static Stack<TimerAction> _pool = new Stack<TimerAction>();
    
    public static TimerAction Create(...) { /* 从池中取 */ }
    public void Recycle() { /* 归还到池中 */ }
}
```

**为什么用 `Stack` 而不是 `ObjectPool<T>`？**

注意代码中 `ObjectPool.Instance.Recycle(this)` 被注释掉了，改用了静态 `Stack`。原因是：

- `TimerAction` 使用频率极高，静态 Stack 避免单例查找开销
- 使用 `lock (_pool)` 保证多线程安全
- Stack（后进先出）比 Queue（先进先出）在内存局部性上略优，最近回收的对象大概率还在 CPU 缓存中

### 主存储容器

```csharp
private readonly MultiMap<long, long> TimeId = new();      // 触发时间 -> [定时器ID列表]
private readonly Dictionary<long, TimerAction> timerActions = new(); // ID -> TimerAction
private long minTime = long.MaxValue;                        // 最近触发时间缓存
```

`MultiMap<long, long>` 是一个有序多值映射（内部基于 SortedDictionary），**key 是触发时间戳，value 是同一时刻要触发的多个定时器 ID 列表**。

这个结构实现了 O(log n) 的插入和 O(1) 的最小时间查询（通过 `minTime` 缓存），非常适合大量定时器并发的场景。

---

## Update 驱动的调度核心

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;
    
    long timeNow = GetNow();
    if (timeNow < this.minTime) return;  // 最近定时器还未到期，直接跳出

    // 第一步：收集所有已到期的时间点
    foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
    {
        long k = kv.Key;
        if (k > timeNow)
        {
            this.minTime = k;  // 顺手更新 minTime
            break;
        }
        this.timeOutTime.Enqueue(k);
    }

    // 第二步：将到期时间点的所有定时器 ID 移到待触发队列
    while (this.timeOutTime.Count > 0)
    {
        long time = this.timeOutTime.Dequeue();
        var list = this.TimeId[time];
        for (int i = 0; i < list.Count; ++i)
            this.timeOutTimerIds.Enqueue(list[i]);
        this.TimeId.Remove(time);
    }

    // 第三步：逐个触发
    while (this.timeOutTimerIds.Count > 0)
    {
        long timerId = this.timeOutTimerIds.Dequeue();
        if (!this.timerActions.Remove(timerId, out TimerAction timerAction))
            continue;
        this.Run(timerAction);
    }
}
```

**为什么要分三步而不是一步遍历触发？**

分步设计防止了**触发过程中修改集合**的问题：
- 第一步只读取，不修改 `TimeId`
- 第二步从 `TimeId` 删除已到期条目（此时第一步已完成）
- 第三步执行回调（回调内可能添加新定时器，但此时遍历已结束）

`timeOutTime` 和 `timeOutTimerIds` 是帧级复用的 Queue，避免每帧 new 临时集合产生 GC。

**minTime 缓存优化：**

```csharp
if (timeNow < this.minTime) return;
```

绝大多数帧没有定时器到期，这一行直接 return，完全跳过 MultiMap 的遍历。这是性能优化的关键——把"无工作帧"的开销压缩到最低。

---

## 三种模式的触发逻辑

```csharp
private void Run(TimerAction timerAction)
{
    switch (timerAction.TimerClass)
    {
        case TimerClass.OnceTimer:
            EventSystem.Instance.Invoke(timerAction.Type, 
                new TimerCallback() { Args = timerAction.Object });
            timerAction.Recycle();
            break;

        case TimerClass.OnceWaitTimer:
            ETTask tcs = timerAction.Object as ETTask;
            tcs.SetResult();        // 唤醒 await 协程
            timerAction.Recycle();
            break;

        case TimerClass.RepeatedTimer:
            long timeNow = GetNow();
            timerAction.StartTime = timeNow;
            this.AddTimer(timerAction); // 重新入队（续期）
            EventSystem.Instance.Invoke(timerAction.Type,
                new TimerCallback() { Args = timerAction.Object });
            break;
    }
}
```

**OnceWaitTimer 的异步唤醒原理：**

`ETTask tcs = timerAction.Object as ETTask` —— 这个 ETTask 是在 `WaitAsync` 中创建的"手动完成任务"，相当于一个协程挂起点。调用 `tcs.SetResult()` 后，协程从 `await` 处恢复执行。

**RepeatedTimer 的时间漂移问题：**

注意续期时用的是 `timerAction.StartTime = GetNow()`（当前时间），而非 `timerAction.StartTime + timerAction.Time`（精确续期）。

这意味着如果某帧执行耗时过长导致定时器延迟触发，下一次触发时间是从"实际触发时刻"计算的，而非"理论触发时刻"。这避免了一帧触发大量堆积的定时器，但会造成轻微的时间漂移——对游戏逻辑而言通常可以接受。

---

## 异步等待接口

### WaitAsync - 等待 N 毫秒

```csharp
public async ETTask WaitAsync(long time, ETCancellationToken cancellationToken = null, bool bWaitFrame = false)
{
    if (time == 0 && !bWaitFrame) return;  // 0ms且非帧等待，直接返回

    long timeNow = GetNow();
    ETTask tcs = ETTask.Create(true);      // 创建可手动完成的 ETTask
    TimerAction timer = TimerAction.Create(this.GetId(), TimerClass.OnceWaitTimer, timeNow, time, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId))
            tcs.SetResult();  // 取消时也要唤醒协程，避免永久挂起
    }

    try
    {
        cancellationToken?.Add(CancelAction);
        await tcs;
    }
    finally
    {
        cancellationToken?.Remove(CancelAction);  // 必须清理，防止内存泄漏
    }
}
```

取消令牌的集成非常精妙：

- 外部调用 `cancellationToken.Cancel()` 时，会触发 `CancelAction`
- `CancelAction` 移除定时器并调用 `tcs.SetResult()` 唤醒协程
- `finally` 确保无论是否取消，都会从令牌中移除监听，防止悬空引用

### WaitFrameAsync / WaitFramesAsync

```csharp
public async ETTask WaitFrameAsync(ETCancellationToken cancellationToken = null)
{
    await this.WaitAsync(0, cancellationToken, true);  // time=0, bWaitFrame=true
}

public async ETTask WaitFramesAsync(int frameCount, ETCancellationToken cancellationToken = null)
{
    for (int i = 0; i < frameCount; i++)
        await this.WaitFrameAsync(cancellationToken);
}
```

`WaitFrameAsync` 实质上是 `OnceWaitTimer` + time=0，在下一帧的定时器处理阶段会立即触发（因为 0 + startTime <= timeNow）。

---

## 三种定时器的创建接口

```csharp
// 单次定时（回调式，可热更）
public long NewOnceTimer(long tillTime, int type, object args)

// 每帧执行（RepeatedTimer with time=0 or 100ms）
public long NewFrameTimer(int type, object args)

// 重复定时（最小间隔 100ms）
public long NewRepeatedTimer(long time, int type, object args)
```

**代码注释中的设计建议：**

```csharp
// 用这个优点是可以热更，缺点是回调式的写法，逻辑不连贯。
// WaitTillAsync不能热更，优点是逻辑连贯。
// wait时间短并且逻辑需要连贯的建议WaitTillAsync
// wait时间长不需要逻辑连贯的建议用NewOnceTimer
```

这段注释揭示了一个深层的设计权衡：
- `NewOnceTimer` + `EventSystem` 回调 → 支持热更，但逻辑分散
- `await WaitAsync()` → 逻辑连贯，但热更时需要重启协程

---

## DeltaTime 计量

```csharp
private float m_deltaTime;
public float DeltaTime => m_deltaTime;
```

`TimerComponent` 还维护了一个 `DeltaTime` 字段，供外部查询本帧的实际经过时间（通常在 Update 末尾更新）。这让定时器系统同时承担了"帧时间统计"的职责。

---

## 与 LogicTimerComponent 的对比

游戏框架中存在两个定时器：`TimerComponent`（时钟驱动）和 `LogicTimerComponent`（帧驱动）。

| 维度 | TimerComponent | LogicTimerComponent |
|------|---------------|---------------------|
| 时间单位 | 毫秒（ms） | 逻辑帧 |
| 触发精度 | 取决于渲染帧率 | 精确到逻辑帧 |
| 适用场景 | UI倒计时、延迟特效 | 帧同步战斗逻辑 |
| 确定性 | 不确定（受帧率影响） | 确定性（固定帧驱动） |

网络同步类游戏的战斗逻辑必须使用 `LogicTimerComponent`，普通游戏逻辑使用 `TimerComponent` 即可。

---

## 架构亮点总结

1. **MultiMap 有序调度**：O(log n) 插入 + minTime 缓存的双重优化，绝大多数帧的调度开销接近 O(1)
2. **TimerAction 对象池**：静态 Stack + lock 实现轻量级线程安全池，消除高频 GC
3. **三步触发分离**：先收集，再删除，最后触发，安全处理回调内修改集合的问题
4. **ETTask 深度集成**：OnceWaitTimer 直接唤醒协程，异步代码流畅自然
5. **取消令牌闭包**：CancelAction 闭包捕获 timerId，与 ETCancellationToken 无缝协作
6. **帧等待特殊处理**：`bWaitFrame` 标志区分"0ms等待"和"下一帧等待"，避免逻辑错误

`TimerComponent` 的设计体现了游戏框架在性能、可用性、安全性三者之间的精妙平衡，是理解整个 ECS 框架异步调度机制的核心入口之一。
