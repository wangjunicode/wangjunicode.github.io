---
title: 帧同步逻辑定时器LogicTimerComponent-定点数驱动的确定性调度系统深度解析
published: 2026-04-19
description: 深度解析游戏框架中LogicTimerComponent帧同步逻辑定时器的完整实现，涵盖与TimerComponent的本质区别、TrueSync定点数FP帧计算、三种定时器类型（OnceTimer / OnceWaitTimer / RepeatedTimer）的工作机制、暂停恢复设计，以及帧同步游戏中确定性调度的工程实践。
tags: [Unity, 帧同步, 定时器, LogicTimerComponent, 确定性, 游戏框架]
category: 游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

在帧同步游戏中，时间的概念与普通游戏完全不同。普通游戏可以用现实时间（毫秒）驱动定时器，但帧同步游戏的一切逻辑必须基于**逻辑帧号**——所有客户端执行相同帧号的逻辑，得到完全一致的结果。

`LogicTimerComponent` 正是为这一场景专门设计的逻辑定时器系统，它与异步 `TimerComponent` 并行存在，各司其职。

---

## 与 TimerComponent 的本质区别

| 特性 | `TimerComponent` | `LogicTimerComponent` |
|------|-----------------|----------------------|
| 时间单位 | 毫秒（long） | 逻辑帧号（long） |
| 挂载方式 | ECS 组件 | 单例（Singleton） |
| 驱动方式 | Update（现实时间） | FixedUpdate（物理帧） |
| 时间基准 | 系统时钟 | 帧计数器 |
| 确定性 | ❌ 受帧率影响 | ✅ 逻辑帧号一致 |
| 暂停支持 | ❌ | ✅（EngineRuntime.Pause） |
| 时间类型 | `long` | `FP`（TrueSync 定点数） |
| 应用场景 | UI 动画、网络超时 | 战斗技能 CD、帧同步逻辑 |

最关键的区别：**LogicTimerComponent 的所有时间计算基于帧号，而非现实时间**。这确保了在帧同步对战中，所有客户端的定时器在相同逻辑帧触发，结果完全一致。

---

## 核心数据结构

```csharp
public class LogicTimerComponent : Singleton<LogicTimerComponent>, ISingletonFixedUpdate
{
    // 有序多值映射：帧号 → 定时器 ID 列表
    private readonly MultiMap<long, long> TimeId = new();
    
    // 超时帧号队列（避免迭代时修改集合）
    private readonly Queue<long> timeOutTime = new();
    private readonly Queue<long> timeOutTimerIds = new();
    
    // 定时器数据存储
    private readonly Dictionary<long, LogicTimerAction> timerActions = new();
    
    // 自增 ID 生成器
    private long idGenerator;
    
    // 当前逻辑帧号（从 0 开始计数）
    private long frameNow = 0;
    
    // 最小触发帧号缓存（优化：避免每帧遍历 MultiMap）
    private long minTime = long.MaxValue;
}
```

`MultiMap<long, long>` 是框架内自定义的有序多值映射（内部为 `SortedDictionary`），以**触发帧号**为键，**定时器 ID 列表**为值，天然按帧号排序，便于快速判断是否有定时器到期。

---

## LogicTimerAction：定时器数据对象

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
        
        // 关键：将 FP 时间转换为帧数
        timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
        timerAction.Type = type;
        return timerAction;
    }
    
    public void Recycle() { ... ObjectPool.Instance.Recycle(this); }
}
```

**帧数计算公式：**
```
帧数 = RoundToInt(时间 / 每帧时长)
```

`EngineDefine.fixedDeltaTime_Orignal` 是游戏配置的固定帧时长（通常为 `1/30` 或 `1/60` 秒的定点数）。使用 `TSMath.RoundToInt` 而非浮点运算，保证在所有客户端上的计算结果完全一致。

`LogicTimerAction` 通过 `ObjectPool` 池化管理，避免频繁创建销毁带来的 GC 压力。

---

## FixedUpdate 驱动机制

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
    {
        Update();  // 只在非暂停状态下推进帧号
    }
}

public void FixedUpdate() { }
public void LateFixedUpdate() { }
```

`LogicTimerComponent` 实现了 `ISingletonFixedUpdate` 接口，在每个物理帧的 `BeforeFixedUpdate` 阶段执行调度逻辑。

**暂停机制**：通过 `EngineRuntime.Pause` 标志控制帧号是否推进。暂停时所有定时器"冻结"，恢复后从暂停时的帧号继续计数，完全不会影响定时器的触发时序。这对于战斗暂停功能至关重要。

---

## 核心调度循环 Update()

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;
    
    // ① 推进帧号
    frameNow++;
    
    // ② 快速路径：当前帧小于最小触发帧，直接跳过
    if (frameNow < this.minTime) return;
    
    // ③ 收集所有已超时的定时器
    foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
    {
        long k = kv.Key;
        if (k > frameNow)
        {
            this.minTime = k;  // 更新最小帧号缓存
            break;
        }
        this.timeOutTime.Enqueue(k);
    }
    
    // ④ 移除超时条目，收集定时器 ID
    while (this.timeOutTime.Count > 0)
    {
        long time = this.timeOutTime.Dequeue();
        var list = this.TimeId[time];
        for (int i = 0; i < list.Count; ++i)
            this.timeOutTimerIds.Enqueue(list[i]);
        this.TimeId.Remove(time);
    }
    
    // ⑤ 执行超时定时器
    while (this.timeOutTimerIds.Count > 0)
    {
        long timerId = this.timeOutTimerIds.Dequeue();
        if (!this.timerActions.Remove(timerId, out LogicTimerAction timerAction))
            continue;
        this.Run(timerAction);
    }
}
```

**两阶段队列设计**（`timeOutTime` + `timeOutTimerIds`）：

不在遍历 `TimeId` 的过程中直接删除条目，而是先收集到队列，遍历完成后再统一处理。这避免了"遍历时修改集合"导致的迭代器失效问题，是处理此类问题的标准模式。

**minTime 缓存优化**：

每次更新 `minTime` 为下一个最近的触发帧号。在大多数帧中，`frameNow < minTime` 条件成立，可以立即返回，完全跳过 MultiMap 的遍历，将高频调用的性能开销降至最低。

---

## 三种定时器类型

### OnceTimer（一次性回调定时器）

```csharp
public long NewOnceTimer(FP time, int type, object args)
{
    LogicTimerAction timer = LogicTimerAction.Create(
        GetId(), TimerClass.OnceTimer, frameNow, time, type, args);
    this.AddTimer(timer);
    return timer.Id;
}
```

触发时通过 `EventSystem.Instance.Invoke` 分发回调：
```csharp
case TimerClass.OnceTimer:
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    timerAction.Recycle();
    break;
```

适合：技能冷却结束通知、延迟伤害触发等**"发射后不管"**的场景。

### OnceWaitTimer（一次性异步等待定时器）

```csharp
public async ETTask WaitAsync(FP time, ETCancellationToken cancellationToken = null)
{
    ETTask tcs = ETTask.Create(true);
    LogicTimerAction timer = LogicTimerAction.Create(
        GetId(), TimerClass.OnceWaitTimer, frameNow, time, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId))
            tcs.SetResult();
    }

    try
    {
        cancellationToken?.Add(CancelAction);
        await tcs;  // 挂起，等待帧号触发
    }
    finally
    {
        cancellationToken?.Remove(CancelAction);
    }
}
```

触发时唤醒等待的 ETTask：
```csharp
case TimerClass.OnceWaitTimer:
    ETTask tcs = timerAction.Object as ETTask;
    tcs.SetResult();  // 唤醒 await
    timerAction.Recycle();
    break;
```

适合：需要用 `await` 写出线性逻辑的场景，如技能序列、动画等待等。

**取消支持**：通过 `ETCancellationToken` 注册取消回调，当外部取消时（如技能被打断）移除定时器并立即唤醒，避免协程泄漏。

### RepeatedTimer（重复定时器）

```csharp
case TimerClass.RepeatedTimer:
    timerAction.StartFrame = frameNow;  // 重置起始帧
    this.AddTimer(timerAction);          // 重新加入调度
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    break;
```

重复定时器触发后，**重新计算下次触发帧号**（从当前帧 + 间隔帧数），实现周期性调度。适合：持续性 Buff 效果、周期性 AI 决策等。

---

## 辅助定时器接口

```csharp
// 等待一帧
public async ETTask WaitFrameAsync(ETCancellationToken cancellationToken = null)
{
    await this.WaitAsync(EngineDefine.fixedDeltaTime_Orignal, cancellationToken);
}

// 每帧执行的定时器
public long NewFrameTimer(int type, object args)
{
    return this.NewRepeatedTimerInner(EngineDefine.fixedDeltaTime_Orignal, type, args);
}
```

`WaitFrameAsync` 等待一个固定帧时长，相当于 Unity 协程中的 `yield return new WaitForFixedUpdate()`，但完全基于逻辑帧，可用于帧同步逻辑中。

`NewFrameTimer` 创建每帧触发的重复定时器，适合需要在每个逻辑帧执行的持续性效果。

---

## 定时器移除与帧号重置

```csharp
private bool Remove(long id)
{
    if (id == 0) return false;
    
    if (!this.timerActions.Remove(id, out LogicTimerAction timerAction))
        return false;
    
    timerAction.Recycle();
    
    // 当所有定时器都被移除时，重置帧号
    if (this.timerActions.Count == 0)
        frameNow = 0;
    
    return true;
}
```

**帧号重置**是一个重要细节：当所有定时器被清空时（如战斗结束），将 `frameNow` 重置为 0。这确保下次战斗开始时从第 0 帧重新计数，避免帧号溢出问题，同时保持战斗生命周期内的逻辑独立性。

---

## 帧同步场景下的使用规范

**允许使用 LogicTimerComponent 的场景：**
- 战斗技能冷却、持续效果
- 帧同步逻辑中的延迟触发
- Buff/Debuff 持续时间计算

**禁止使用的场景：**
- UI 动画（应使用 `TimerComponent` 或 DOTween）
- 网络请求超时（应使用 `TimerComponent`）
- 任何非确定性的时间相关逻辑

**操作规范：**
```csharp
// ✅ 正确：基于定点数时间，确定性
await LogicTimerComponent.Instance.WaitAsync((FP)0.5f);

// ✅ 正确：使用 CancellationToken 支持中断
await LogicTimerComponent.Instance.WaitAsync((FP)1.0f, cancellationToken);

// ❌ 错误：不要在帧同步逻辑中使用 TimerComponent
await TimerComponent.Instance.WaitAsync(500);  // 毫秒，非确定性
```

---

## 总结

`LogicTimerComponent` 是帧同步战斗系统的时间基础设施，其设计要点：

| 设计决策 | 原因 |
|---------|------|
| 单例而非 ECS 组件 | 战斗全局唯一，无需跟随 Entity 生命周期 |
| FP 定点数时间 | 跨客户端确定性，避免浮点误差 |
| 帧号而非毫秒 | 与帧同步逻辑帧对齐 |
| FixedUpdate 驱动 | 物理帧稳定，与战斗逻辑帧步调一致 |
| minTime 缓存 | 避免每帧遍历 MultiMap 的性能开销 |
| 两阶段队列 | 安全地在调度循环中修改定时器集合 |
| Pause 检测 | 支持战斗暂停，冻结逻辑时间 |

理解 `LogicTimerComponent` 与 `TimerComponent` 的边界，是构建正确帧同步战斗系统的关键一步。
