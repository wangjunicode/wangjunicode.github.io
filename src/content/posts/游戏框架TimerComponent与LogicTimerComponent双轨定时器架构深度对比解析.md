---
title: 游戏框架TimerComponent与LogicTimerComponent双轨定时器架构深度对比解析
published: 2026-04-30
description: 深入对比 xgame 框架中 TimerComponent（毫秒时间驱动）与 LogicTimerComponent（定点数帧驱动）两套定时器系统的设计差异，揭示为何战斗逻辑必须使用帧定时器以保证确定性。
tags: [Unity, 游戏框架, ECS, 定时器, TimerComponent, LogicTimerComponent, 帧同步, 确定性]
category: 游戏开发
encryptedKey: henhaoji123
---

## 前言

在 xgame 框架中，定时器系统被拆分为两套并行实现：`TimerComponent` 和 `LogicTimerComponent`。两者结构高度相似，却服务于完全不同的场景——一个面向客户端时间驱动的逻辑，另一个专为帧同步战斗中的确定性调度设计。

理解这种"一框架、双定时器"的架构决策，是掌握 xgame 战斗体系的重要一环。

---

## 核心数据结构对比

### TimerComponent 的 TimerAction

```csharp
public class TimerAction
{
    private static Stack<TimerAction> _pool = new Stack<TimerAction>();

    public long Id;
    public TimerClass TimerClass;
    public object Object;
    public long StartTime;   // 毫秒时间戳
    public long Time;        // 毫秒间隔
    public int Type;

    public void Recycle()
    {
        // ... 手动 lock + Stack 池
        lock (_pool) { _pool.Push(this); }
    }
}
```

### LogicTimerComponent 的 LogicTimerAction

```csharp
public class LogicTimerAction
{
    public long Id;
    public TimerClass TimerClass;
    public object Object;
    public long StartFrame;  // 帧号（整数）
    public long Frame;       // 间隔帧数
    public int Type;

    public void Recycle()
    {
        // 使用框架统一 ObjectPool
        ObjectPool.Instance.Recycle(this);
    }
}
```

**关键差异一：时间单位**

| 属性 | TimerAction | LogicTimerAction |
|------|-------------|-----------------|
| 时间基准 | 毫秒（`long`） | 帧号（`long`） |
| 时间换算 | `long StartTime + Time` | `StartFrame + Frame` |
| 输入类型 | `long time (ms)` | `FP time` → 换算帧数 |

`LogicTimerAction.Create` 中有一行关键代码：

```csharp
timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
```

它将 `FP`（定点数）类型的时间换算为整数帧数，确保在不同机器上得到完全相同的结果——这正是帧同步确定性的基础。

**关键差异二：对象池实现**

`TimerAction` 使用了内联的 `static Stack<TimerAction> _pool`，并通过 `lock` 保证线程安全；而 `LogicTimerAction` 直接委托给框架的 `ObjectPool.Instance`，体现了对象池管理的统一化趋势。

---

## 驱动方式对比

### TimerComponent：ISingletonUpdate

```csharp
public class TimerComponent : Singleton<TimerComponent>, ISingletonUpdate
{
    public void Update()
    {
        // 依赖 TimeHelper.ClientFrameTime() 获取毫秒时间戳
        long timeNow = GetNow();
        // ...
    }
}
```

`TimerComponent` 实现 `ISingletonUpdate`，在每帧的 `Update` 中被驱动。它通过 `TimeHelper.ClientFrameTime()` 获取当前客户端毫秒时间，会受到真实时间流逝影响，因此不适合帧同步。

### LogicTimerComponent：ISingletonFixedUpdate

```csharp
public class LogicTimerComponent : Singleton<LogicTimerComponent>, ISingletonFixedUpdate
{
    private long frameNow = 0;

    public void BeforeFixedUpdate()
    {
        if (!EngineRuntime.Pause)
        {
            Update(); // 在物理帧前执行，自增 frameNow
        }
    }

    public void Update()
    {
        frameNow++;
        // ...
    }
}
```

`LogicTimerComponent` 实现 `ISingletonFixedUpdate`，在 `BeforeFixedUpdate` 中被调用，且支持通过 `EngineRuntime.Pause` 暂停。更重要的是，`frameNow` 是一个纯粹的整数计数器，不依赖任何真实时间——每次 `FixedUpdate` 自增一次，在所有客户端上完全同步。

---

## 三种 TimerClass 模式

两套系统共用同一个枚举：

```csharp
public enum TimerClass
{
    None,
    OnceTimer,       // 一次性回调（热更兼容）
    OnceWaitTimer,   // 一次性 async/await
    RepeatedTimer,   // 重复执行
}
```

执行逻辑也几乎一致，以 `RepeatedTimer` 为例：

```csharp
// TimerComponent 版
case TimerClass.RepeatedTimer:
{
    long timeNow = GetNow();
    timerAction.StartTime = timeNow;  // 更新起始时间（ms）
    this.AddTimer(timerAction);
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    break;
}

// LogicTimerComponent 版
case TimerClass.RepeatedTimer:
{
    timerAction.StartFrame = frameNow;  // 更新起始帧号
    this.AddTimer(timerAction);
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    break;
}
```

两者逻辑完全对称，只是时间单位不同。

---

## minTime 优化：避免全量遍历

两套系统都使用了相同的性能优化策略：

```csharp
private long minTime = long.MaxValue;

private void AddTimer(TimerAction timer)
{
    long tillTime = timer.StartTime + timer.Time;
    this.TimeId.Add(tillTime, timer.Id);
    if (tillTime < this.minTime)
    {
        this.minTime = tillTime;  // 记录最近触发时间
    }
}

public void Update()
{
    long timeNow = GetNow();
    if (timeNow < this.minTime)
    {
        return;  // 没有定时器到期，直接跳过
    }
    // ...
}
```

`TimeId` 是 `MultiMap<long, long>`（有序多值映射），`minTime` 缓存了其中最小的触发时间，避免每帧都遍历整个 Map。

---

## 独特的 WaitFramesAsync

`TimerComponent` 提供了一个 `LogicTimerComponent` 没有的方法：

```csharp
public async ETTask WaitFramesAsync(int frameCount, ETCancellationToken cancellationToken = null)
{
    if (frameCount <= 0) return;

    for (int i = 0; i < frameCount; i++)
    {
        await this.WaitFrameAsync(cancellationToken);
    }
}
```

这是客户端业务代码中等待"N帧后执行"的便捷封装，循环调用 `WaitFrameAsync`（内部是 `WaitAsync(0, ..., bWaitFrame: true)`），适用于 UI 动画、过场演出等非战斗场景。

---

## 逻辑帧暂停支持

`LogicTimerComponent` 独有的特性：

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
    {
        Update();
    }
}
```

通过检测 `EngineRuntime.Pause`，在游戏暂停时完全停止帧计数，所有逻辑定时器同步暂停。这在 `TimerComponent` 中是做不到的（真实时间不会因为游戏暂停而停止）。

---

## 架构设计总结

| 维度 | TimerComponent | LogicTimerComponent |
|------|---------------|---------------------|
| **时间基准** | 毫秒时间戳（float） | 整数帧号（long） |
| **驱动接口** | ISingletonUpdate | ISingletonFixedUpdate |
| **确定性** | ❌ 不确定（受真实时间影响） | ✅ 确定（帧号整数） |
| **暂停支持** | ❌ 不支持 | ✅ EngineRuntime.Pause |
| **适用场景** | UI动画、非战斗业务 | 帧同步战斗逻辑 |
| **对象池** | 内联 static Stack | 框架 ObjectPool.Instance |

---

## 总结

xgame 框架用两套并行定时器完美解决了一个根本矛盾：**客户端业务逻辑需要"真实时间"，而帧同步战斗逻辑需要"确定性帧"**。

`TimerComponent` 用毫秒驱动，直接对应现实世界的时间流逝；`LogicTimerComponent` 用帧号驱动，与 `FixedUpdate` 完全对齐，在所有参与者的机器上产生完全一致的触发顺序。

这种"相同接口，不同时间基准"的双轨设计，是游戏框架工程化的典范——它用最小的代码冗余换来了最大的架构清晰度。
