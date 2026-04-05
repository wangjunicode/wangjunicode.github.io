---
title: 游戏逻辑帧定时器组件——帧驱动的精准调度系统设计解析
published: 2026-03-31
description: 深入剖析基于逻辑帧驱动的定时器组件 LogicTimerComponent，理解帧计数调度、对象池复用和三种定时器类型的设计原理。
tags: [Unity, ECS, 定时器, 帧同步, 对象池]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 游戏逻辑帧定时器组件——帧驱动的精准调度系统设计解析

## 前言

上篇文章我们了解了 `ATimer<T>` 这个定时器回调的抽象基类。这篇文章，我们来看定时器系统的核心——**调度器** `LogicTimerComponent`。

它负责回答一个根本性问题：**什么时候该触发哪个定时器？**

理解这个组件，你不仅能学到定时器的实现原理，还能深入理解**帧同步**、**对象池**、**多集合协同**等高级游戏开发技术。

---

## 一、为什么用"帧"而不是"时间"？

首先要回答一个关键问题：为什么这个定时器叫 `LogicTimerComponent`，而且用帧（Frame）而不是毫秒来计时？

看这段初始化代码：

```csharp
timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
```

这里把时间（以 `FP` 即定点数表示）除以固定帧间隔，转换成帧数。`FP` 是 TrueSync 库中的定点数类型，专门用于确定性计算。

**为什么要用帧而不是毫秒？**

这是为了支持**帧同步**（Lockstep）多人游戏。

在帧同步游戏中（如早期的星际争霸、最近流行的格斗游戏），所有客户端必须以完全相同的逻辑步骤推进游戏状态。如果用真实时间（毫秒）来计时，不同设备因为性能差异、网络延迟等原因，可能在"同一时刻"处于不同的帧，导致状态不同步。

用逻辑帧计时，结合定点数（`FP`）替代浮点数（`float`），能保证在所有机器上产生完全相同的计算结果。

**类比**：国际象棋比赛不说"白方在第5分22秒落子"，而说"白方在第3步落子"。用步骤而非时间来同步。

---

## 二、核心数据结构解析

```csharp
private readonly MultiMap<long, long> TimeId = new();
private readonly Queue<long> timeOutTime = new();
private readonly Queue<long> timeOutTimerIds = new();
private readonly Dictionary<long, LogicTimerAction> timerActions = new();
private long idGenerator;
private long frameNow = 0;
private long minTime = long.MaxValue;
```

这里有四个集合，各司其职：

### 2.1 MultiMap<long, long> TimeId

`MultiMap` 是一个"一对多"的字典，键是"第N帧"，值是"这一帧需要触发的所有定时器ID列表"。

**为什么需要多个 ID 对应同一帧？** 因为可能同时有多个定时器在同一帧到期。

例如：
```
第100帧: [定时器1, 定时器2]
第200帧: [定时器3]
第350帧: [定时器4, 定时器5, 定时器6]
```

### 2.2 Queue<long> timeOutTime 和 timeOutTimerIds

这两个队列是**临时缓冲区**，用于在遍历时收集已到期的定时器，避免在遍历 `TimeId` 时直接修改它（会引发集合修改异常）。

这是一个经典的"先收集，后处理"的编程技巧，在游戏开发中非常常见。

### 2.3 Dictionary<long, LogicTimerAction> timerActions

通过定时器 ID 快速查找完整的定时器信息。

### 2.4 minTime 优化

```csharp
private long minTime = long.MaxValue;
```

记录所有定时器中最早的触发帧。每次 `Update` 时先比较 `frameNow < minTime`，如果当前帧还没到最早的定时器触发时间，直接跳过，**无需遍历整个集合**。

这是一个重要的性能优化：如果你设置了100个定时器，分别在未来1分钟到1小时内触发，那么在它们到期之前的每一帧，`Update` 方法都会在第一行就直接返回，几乎零开销。

---

## 三、LogicTimerAction——数据对象 + 对象池

```csharp
public class LogicTimerAction
{
    public static LogicTimerAction Create(long id, TimerClass timerClass, long startFrame, FP time, int type, object obj)
    {
        LogicTimerAction timerAction = ObjectPool.Instance.Fetch<LogicTimerAction>();
        // ... 初始化字段
        return timerAction;
    }
    
    public void Recycle()
    {
        // 重置所有字段
        ObjectPool.Instance.Recycle(this);
    }
}
```

`LogicTimerAction` 承载了一个定时器的完整信息：
- `Id`：唯一标识符
- `TimerClass`：定时器类型（一次性/等待/循环）
- `Frame`：触发帧数（相对帧数，不是绝对帧）
- `StartFrame`：开始帧，配合 Frame 计算绝对触发帧
- `Type`：回调类型（用于 EventSystem 分发）
- `Object`：回调参数

**关键设计：对象池（Object Pool）**

注意 `Create` 方法不是 `new LogicTimerAction()`，而是从 `ObjectPool.Instance.Fetch<LogicTimerAction>()` 获取。

为什么要用对象池？

在游戏中，定时器可能每秒被创建和销毁几十次。如果每次都 `new` 一个新对象，C# 的垃圾回收（GC）就会频繁触发，造成游戏卡顿（俗称"GC Spike"）。

对象池的思路是：用完不扔，存起来复用。就像餐厅的碗碟用完洗干净再用，而不是每次都买新的。

**对象池模式伪代码**：
```
Pool 里有对象 → 直接取出来用
Pool 是空的  → 创建新对象
用完了      → 清空状态，放回 Pool
```

`Recycle` 方法会将所有字段重置，确保下次取出时是"干净"的状态。

---

## 四、三种定时器类型

```csharp
public enum TimerClass
{
    None,
    OnceTimer,      // 一次性定时器
    OnceWaitTimer,  // 一次性等待定时器（async/await）
    RepeatedTimer   // 循环定时器
}
```

这三种类型决定了定时器触发后的行为：

### 4.1 OnceTimer——回调式一次性定时器

```csharp
case TimerClass.OnceTimer:
{
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    timerAction.Recycle();
    break;
}
```

触发后通过 EventSystem 调用回调，然后回收。适合"触发一次后不再需要"的场景。

**使用方式**：
```csharp
LogicTimerComponent.Instance.NewOnceTimer(FP.FromFloat(3f), TimerType.SkillEffect, skillArgs);
```

3秒后触发 `SkillEffect` 类型的回调，参数是 `skillArgs`。

### 4.2 OnceWaitTimer——异步等待定时器

```csharp
case TimerClass.OnceWaitTimer:
{
    ETTask tcs = timerAction.Object as ETTask;
    tcs.SetResult();
    timerAction.Recycle();
    break;
}
```

这个定时器存储的不是普通回调，而是一个 `ETTask`（类似 C# 的 `TaskCompletionSource`）。

触发时调用 `tcs.SetResult()`，会唤醒所有等待这个 Task 的 `await` 代码。

**使用方式**：
```csharp
// 在任意 async 方法中
await LogicTimerComponent.Instance.WaitAsync(FP.FromFloat(3f));
// 3秒后继续执行这里
DoNextStep();
```

这让你可以用**线性的、同步风格的代码**写出"等待X时间后继续"的逻辑，而不用写回调嵌套。

这就是 `async/await` 的威力——用顺序的写法表达异步的逻辑。

### 4.3 RepeatedTimer——循环定时器

```csharp
case TimerClass.RepeatedTimer:
{
    timerAction.StartFrame = frameNow; // 重置开始帧
    this.AddTimer(timerAction);        // 重新注册，不回收
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    break;
}
```

触发后，重新把自己注册进去，形成循环。不调用 `Recycle`，因为对象还要继续使用。

注意这里更新了 `StartFrame = frameNow`，这样下一次触发时间是"从现在起再过 Frame 帧"，保持精确的间隔。

---

## 五、Update 方法——调度核心

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;

    frameNow++;

    if (frameNow < this.minTime) return;

    // 第一步：收集已到期的帧
    foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
    {
        long k = kv.Key;
        if (k > frameNow)
        {
            this.minTime = k;
            break;
        }
        this.timeOutTime.Enqueue(k);
    }

    // 第二步：收集已到期帧对应的所有定时器ID
    while (this.timeOutTime.Count > 0)
    {
        long time = this.timeOutTime.Dequeue();
        var list = this.TimeId[time];
        for (int i = 0; i < list.Count; ++i)
        {
            this.timeOutTimerIds.Enqueue(list[i]);
        }
        this.TimeId.Remove(time);
    }

    // 第三步：逐个执行已到期的定时器
    while (this.timeOutTimerIds.Count > 0)
    {
        long timerId = this.timeOutTimerIds.Dequeue();
        if (!this.timerActions.Remove(timerId, out LogicTimerAction timerAction))
        {
            continue;
        }
        this.Run(timerAction);
    }
}
```

这里分三步执行，避免了在遍历时修改集合的问题。

**为什么要分三步？**

考虑这种情况：一个定时器在触发时，又创建了新的定时器（比如循环定时器把自己重新注册）。如果我们在遍历 `TimeId` 的同时修改它，C# 会抛出 `InvalidOperationException: Collection was modified`。

先收集到 Queue，再统一处理，就避免了这个问题。

---

## 六、异步取消机制

```csharp
public async ETTask WaitAsync(FP time, ETCancellationToken cancellationToken = null)
{
    ETTask tcs = ETTask.Create(true);
    LogicTimerAction timer = LogicTimerAction.Create(this.GetId(), TimerClass.OnceWaitTimer, frameNow, time, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId))
        {
            tcs.SetResult(); // 取消时也要唤醒等待者
        }
    }

    try
    {
        cancellationToken?.Add(CancelAction);
        await tcs;
    }
    finally
    {
        cancellationToken?.Remove(CancelAction);
    }
}
```

这段代码展示了如何正确实现**可取消的异步等待**：

1. 创建一个 `ETTask`（Promise）
2. 如果有 `cancellationToken`，注册取消回调
3. 等待 Task 完成（可能是定时器到期，也可能是取消）
4. 在 `finally` 块中移除取消回调（无论如何都要清理）

`finally` 块的使用非常重要，确保即使发生异常，取消回调也不会留下"幽灵"，导致内存泄漏或意外行为。

---

## 七、暂停逻辑

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
    {
        Update();
    }
}
```

定时器更新放在 `BeforeFixedUpdate` 而非 `Update` 中，且检查了游戏暂停状态。

当游戏暂停时（`EngineRuntime.Pause == true`），`frameNow` 不增加，所有定时器都不推进。这实现了游戏暂停时定时器自动停止的效果。

这个设计对于"游戏内倒计时"非常重要：暂停游戏后，技能 CD 不继续减少，这才是玩家期望的行为。

---

## 八、帧同步场景下的精度保证

```csharp
timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
```

这里的时间计算使用了几个关键类型：

- `FP`（Fixed Point）：定点数，跨平台确定性计算
- `TSMath.RoundToInt`：TrueSync 的定点数四舍五入，也是确定性的
- `EngineDefine.fixedDeltaTime_Orignal`：固定的帧间隔时间

全部使用定点数计算，保证在所有设备上，同样的输入产生完全相同的帧数结果。

如果使用 `float` 计算，不同 CPU 的浮点运算可能产生微小差异，这在帧同步游戏中是灾难性的——所有客户端会逐渐偏离，游戏状态不同步。

---

## 九、设计亮点总结

| 设计点 | 实现方式 | 解决的问题 |
|---|---|---|
| 帧驱动 | 用帧数而非毫秒 | 帧同步精确性 |
| 定点数 | FP 类型 | 跨平台确定性 |
| 对象池 | ObjectPool.Fetch/Recycle | 减少 GC 压力 |
| minTime 优化 | 记录最小触发帧 | 减少无效遍历 |
| 三步遍历 | 先收集再处理 | 避免并发修改异常 |
| 可取消异步 | ETCancellationToken | 灵活的异步控制 |
| 暂停支持 | BeforeFixedUpdate 检查 | 游戏暂停时正确停止 |

---

## 十、写给初学者的总结

这个组件看起来复杂，但核心思路非常清晰：

**每帧递增帧计数器，到时间了就触发对应的定时器。**

所有的复杂性都来自于"如何做得更好"：
- 用帧而非时间 → 帧同步精度
- 对象池 → 性能
- 三步遍历 → 安全
- minTime → 效率
- 可取消异步 → 灵活性

这就是工程师思维的体现：先让它能跑，再让它跑得好，再让它在各种情况下都跑得好。

学会欣赏这些细节，你就能写出生产级别的代码。
