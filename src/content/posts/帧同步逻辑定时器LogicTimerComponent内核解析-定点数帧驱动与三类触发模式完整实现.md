---
title: 帧同步逻辑定时器LogicTimerComponent内核解析-定点数帧驱动与三类触发模式完整实现
encryptedKey: henhaoji123
published: 2026-04-20
description: 深入剖析游戏框架中LogicTimerComponent的完整实现，从定点数帧计算、MultiMap有序调度、三类TimerClass触发模式，到ETTask异步等待与取消令牌，全面掌握帧同步定时器的设计精髓。
tags: [Unity, ECS, 帧同步, 定时器, 异步编程, 游戏框架]
category: 游戏框架源码解析
draft: false
---

# 帧同步逻辑定时器 LogicTimerComponent 内核解析

## 前言

在帧同步战斗系统中，时间的度量必须是**确定性**的——任何两台机器在相同的逻辑帧下运行同样的代码，必须产生同样的结果。浮点数的不确定性是帧同步的天敌，因此我们的逻辑定时器不能依赖 `Time.deltaTime`，而要以**逻辑帧号**作为计时基准。

`LogicTimerComponent` 正是为此而生的定时器组件。本文将逐层拆解它的每一行代码。

---

## 整体定位

```
游戏循环 (FixedUpdate)
    └── LogicTimerComponent.BeforeFixedUpdate()
            └── Update()  // 推进 frameNow，检查到期定时器
```

`LogicTimerComponent` 是一个 `Singleton<LogicTimerComponent>`，实现了 `ISingletonFixedUpdate`，在每个物理帧的 `BeforeFixedUpdate` 阶段执行调度逻辑。它与 `TimerComponent`（毫秒级时间定时器）的最大区别在于：

| 对比维度 | TimerComponent | LogicTimerComponent |
|---------|---------------|---------------------|
| 计时单位 | 毫秒（long） | 逻辑帧号（long） |
| 时间来源 | `TimeHelper.ClientNow()` | 内部 `frameNow` 自增 |
| 确定性 | 受系统时钟影响 | 完全确定性 |
| 适用场景 | UI动画、通用延迟 | 帧同步战斗逻辑 |

---

## 核心数据结构

```csharp
private readonly MultiMap<long, long> TimeId = new();       // 到期帧号 → 定时器ID列表
private readonly Queue<long> timeOutTime = new();           // 临时：已到期的帧号
private readonly Queue<long> timeOutTimerIds = new();       // 临时：已到期的定时器ID
private readonly Dictionary<long, LogicTimerAction> timerActions = new(); // 所有活跃定时器

private long idGenerator;    // ID自增器
private long frameNow = 0;   // 当前逻辑帧号
private long minTime = long.MaxValue; // 最近一个到期帧号的缓存优化
```

这套数据结构和 `TimerComponent` 几乎同构，区别只在于 key 是帧号而非毫秒时间戳。`MultiMap<long, long>` 按帧号有序存储，这是高效遍历的基础。

---

## LogicTimerAction：定时器动作的值对象

```csharp
public class LogicTimerAction
{
    public static LogicTimerAction Create(
        long id, TimerClass timerClass,
        long startFrame, FP time, int type, object obj)
    {
        LogicTimerAction timerAction = ObjectPool.Instance.Fetch<LogicTimerAction>();
        timerAction.Id = id;
        timerAction.TimerClass = timerClass;
        timerAction.Object = obj;
        timerAction.StartFrame = startFrame;
        // 关键：将 FP 类型的时间转换为逻辑帧数
        timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
        timerAction.Type = type;
        return timerAction;
    }
    
    public void Recycle()
    {
        // 归零所有字段后放回对象池
        ObjectPool.Instance.Recycle(this);
    }
}
```

### 定点数帧换算

这是整个设计中最关键的一处：

```csharp
timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
```

- `time` 是 `FP`（Fixed Point）类型，即定点数，避免浮点误差
- `EngineDefine.fixedDeltaTime_Orignal` 是每逻辑帧的时长（如 0.066 秒，即 15fps）
- `TSMath.RoundToInt` 是确定性的四舍五入
- 结果 `Frame` 是"需要等待多少逻辑帧"

这样，`WaitAsync(FP time)` 中的 `time = 1.0f` 表示"等待1秒"，内部会换算成约 15 帧（若帧率为15fps）。

---

## Update 调度核心

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;

    frameNow++;  // ① 推进当前帧号

    if (frameNow < this.minTime) return;  // ② 快速剪枝，无到期定时器

    // ③ 收集所有到期帧号
    foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
    {
        long k = kv.Key;
        if (k > frameNow)
        {
            this.minTime = k;  // 更新下一个最小帧号
            break;
        }
        this.timeOutTime.Enqueue(k);
    }

    // ④ 收集到期定时器ID
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

    // ⑤ 依次执行到期定时器
    while (this.timeOutTimerIds.Count > 0)
    {
        long timerId = this.timeOutTimerIds.Dequeue();
        if (!this.timerActions.Remove(timerId, out LogicTimerAction timerAction)) continue;
        this.Run(timerAction);
    }
}
```

**两阶段分离**的原因：
- 步骤③先收集到期帧号，步骤④再收集ID，步骤⑤再执行
- 这样可以避免在 foreach 遍历 TimeId 的同时修改它（回调中可能新增定时器）

**minTime 优化**：每帧开始时先比较 `frameNow < minTime`，如果还没到最近的到期帧就直接返回，节省遍历开销。每次更新后 `minTime` 被更新为下一个最近到期帧号。

---

## 三类触发模式

```csharp
private void Run(LogicTimerAction timerAction)
{
    switch (timerAction.TimerClass)
    {
        case TimerClass.OnceTimer:        // 单次回调式
        case TimerClass.OnceWaitTimer:    // 单次异步等待式
        case TimerClass.RepeatedTimer:    // 重复触发式
    }
}
```

### 模式一：OnceTimer（单次回调）

```csharp
case TimerClass.OnceTimer:
{
    EventSystem.Instance.Invoke(timerAction.Type, 
        new TimerCallback() { Args = timerAction.Object });
    timerAction.Recycle();
    break;
}
```

通过 `EventSystem.Invoke` 分发，是"热更友好"的设计——回调通过类型 ID 注册，可以在热更后重新注册新实现。**缺点**是逻辑分散，不如 `await` 方式直观连贯。

### 模式二：OnceWaitTimer（异步等待）

```csharp
case TimerClass.OnceWaitTimer:
{
    ETTask tcs = timerAction.Object as ETTask;
    tcs.SetResult();  // 唤醒等待中的协程
    timerAction.Recycle();
    break;
}
```

`Object` 字段存储的是一个 `ETTask`（类似 TaskCompletionSource），调用 `SetResult()` 即可唤醒 `await` 处的协程。这是 `WaitAsync` 的实现基础。

### 模式三：RepeatedTimer（重复定时器）

```csharp
case TimerClass.RepeatedTimer:
{
    timerAction.StartFrame = frameNow;  // 以当前帧为新起点
    this.AddTimer(timerAction);          // 重新加入调度
    EventSystem.Instance.Invoke(timerAction.Type, 
        new TimerCallback() { Args = timerAction.Object });
    break;
}
```

不回收 `timerAction`，而是更新 `StartFrame` 后重新加入 `TimeId`，实现周期触发。

---

## AddTimer：注册定时器

```csharp
private void AddTimer(LogicTimerAction timer)
{
    long tillFrame = timer.StartFrame + timer.Frame;  // 到期帧号
    this.TimeId.Add(tillFrame, timer.Id);
    this.timerActions.Add(timer.Id, timer);
    if (tillFrame < this.minTime)
    {
        this.minTime = tillFrame;  // 更新最小帧号缓存
    }
}
```

`tillFrame = StartFrame + Frame` 是"从创建时的帧号，经过 Frame 帧后到期"。

---

## WaitAsync：异步等待实现

```csharp
public async ETTask WaitAsync(FP time, ETCancellationToken cancellationToken = null)
{
    if (time == 0) return;

    ETTask tcs = ETTask.Create(true);  // 创建可等待的 Task
    LogicTimerAction timer = LogicTimerAction.Create(
        this.GetId(), TimerClass.OnceWaitTimer, frameNow, time, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId))
        {
            tcs.SetResult();  // 取消时也完成 Task
        }
    }

    try
    {
        cancellationToken?.Add(CancelAction);
        await tcs;  // 在这里挂起，等待 SetResult 唤醒
    }
    finally
    {
        cancellationToken?.Remove(CancelAction);
    }
}
```

这个实现展示了一个完整的异步等待模式：

1. 创建 `ETTask`（作为信号量）
2. 将 Task 存入 `LogicTimerAction.Object`
3. 注册取消回调（取消时主动 `SetResult`，避免挂起永远不醒）
4. `await tcs` 挂起当前协程
5. 到期后 `Run()` 调用 `tcs.SetResult()` 唤醒

---

## Remove：安全取消定时器

```csharp
private bool Remove(long id)
{
    if (id == 0) return false;

    if (!this.timerActions.Remove(id, out LogicTimerAction timerAction)) return false;
    
    timerAction.Recycle();
    
    // 特殊处理：所有定时器清空时重置帧号
    if (this.timerActions.Count == 0)
    {
        frameNow = 0;
    }
    return true;
}
```

注意 `timerActions.Count == 0` 时会**重置 `frameNow`**。这是因为当没有任何定时器时，帧号无需保持绝对值，重置为 0 可以防止 `long` 溢出，并使新注册的定时器在相对帧号上工作。

---

## 与 TimerComponent 的设计对比

| 特性 | TimerComponent | LogicTimerComponent |
|-----|---------------|---------------------|
| 暂停支持 | 无 | `EngineRuntime.Pause` 控制 |
| 时间精度 | 毫秒 | 逻辑帧（约66ms） |
| 热更支持 | 回调式支持热更 | 同样通过 EventSystem |
| 帧号重置 | 不重置 | 清空后重置为0 |
| 适用场景 | 通用 | 帧同步战斗专用 |

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)  // 暂停时停止推进帧号
    {
        Update();
    }
}
```

暂停功能是 `LogicTimerComponent` 专有的——在 `EngineRuntime.Pause = true` 时，`frameNow` 停止自增，所有逻辑定时器同步暂停，这是帧同步系统的必要特性。

---

## 使用示例

```csharp
// 单次异步等待（1秒后继续）
await LogicTimerComponent.Instance.WaitAsync(1.0f, cancellationToken);

// 重复定时器（每0.5秒触发一次）
long timerId = LogicTimerComponent.Instance.NewRepeatedTimer(
    0.5f, TimerCoreCallbackId.BattleAIUpdate, this);

// 取消定时器
LogicTimerComponent.Instance.Remove(ref timerId);

// 等待一帧
await LogicTimerComponent.Instance.WaitFrameAsync();
```

---

## 总结

`LogicTimerComponent` 是帧同步战斗系统中定时调度的核心组件，其设计要点：

1. **以逻辑帧号计时**，彻底消除浮点不确定性
2. **定点数换算帧数**，通过 `TSMath.RoundToInt(time / fixedDeltaTime)` 保证确定性
3. **两阶段调度**，避免在遍历中修改集合
4. **minTime 剪枝**，大多数帧直接 O(1) 返回
5. **三类触发模式**覆盖所有使用场景
6. **ETTask 信号量模式**实现协程等待与取消

配合 `TimerComponent` 使用时的原则：战斗逻辑用 `LogicTimerComponent`，UI 动效和通用延迟用 `TimerComponent`。
