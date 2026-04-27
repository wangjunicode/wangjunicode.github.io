---
title: 游戏框架TimerComponent完整实现解析——TimerClass四模式、MultiMap最小时间优化与异步等待设计
published: 2026-04-27
description: 深度解析ET框架TimerComponent定时器组件的完整源码：TimerClass四种定时模式、基于MultiMap的最小时间优化、OnceWaitTimer与ETTask的异步等待集成，以及TimerAction对象池设计。
tags: [Unity, ECS, 游戏框架, 定时器, 异步编程, 源码解析]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

游戏中的定时器无处不在：技能冷却、Buff持续时间、每隔N秒的心跳包、"等待1帧"的协程……这些需求对应着完全不同的调用模式。

ET框架的 `TimerComponent` 以极简的设计支撑了所有这些场景：一个 `MultiMap` 管理触发时间，一个枚举区分四种模式，配合 `ETTask` 实现无回调的异步等待。本文从源码出发，逐层拆解这套定时器系统的工程精髓。

---

## 架构总览

```
TimerComponent (Singleton + ISingletonUpdate)
├── MultiMap<long, long>      TimeId          // time -> List<timerId>（有序）
├── Dictionary<long, TimerAction> timerActions // timerId -> action
├── Queue<long> timeOutTime                   // 本帧超时的时间点
├── Queue<long> timeOutTimerIds               // 本帧超时的 timerId
└── long minTime                              // 最小触发时间（快速跳过检查）

TimerAction（轻量对象池）
├── long Id
├── TimerClass  (OnceTimer / OnceWaitTimer / RepeatedTimer)
├── long StartTime
├── long Time         // 间隔时长（毫秒）
├── int  Type         // Invoke 类型 ID
└── object Object     // 回调数据 / ETTask TCS
```

整个系统的驱动由 `ISingletonUpdate.Update()` 每帧触发一次，时间来源是 `TimeHelper.ClientFrameTime()`（帧快照时间，同帧一致）。

---

## TimerClass：四种定时模式

```csharp
public enum TimerClass
{
    None,
    OnceTimer,       // 单次回调（热更友好）
    OnceWaitTimer,   // 单次异步等待（逻辑连贯）
    RepeatedTimer,   // 周期重复
}
```

### OnceTimer — 单次回调式

```csharp
case TimerClass.OnceTimer:
{
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    timerAction.Recycle();
    break;
}
```

触发时通过 `EventSystem.Invoke` 分发回调，支持热更新（因为回调是通过类型ID注册的，热更后可以替换实现）。

**适用场景**：等待时间较长（> 几秒）且逻辑不需要连贯（如定时发送心跳包、定时存档）。

```csharp
// 使用方式
long timerId = TimerComponent.Instance.NewOnceTimer(
    TimeHelper.ClientFrameTime() + 5000,  // 5秒后触发
    MyTimerType.HeartBeat,
    args
);
```

### OnceWaitTimer — 单次异步等待式

```csharp
case TimerClass.OnceWaitTimer:
{
    ETTask tcs = timerAction.Object as ETTask;
    tcs.SetResult();  // 唤醒等待中的异步方法
    timerAction.Recycle();
    break;
}
```

`Object` 字段存的是一个 `ETTask` TCS（Task Completion Source）。触发时调用 `SetResult()` 唤醒 `await`。

**适用场景**：等待时间短且逻辑需要连贯（如技能释放后等待0.5秒播放特效）。

```csharp
// 使用方式（业务层无感知底层）
await TimerComponent.Instance.WaitAsync(500);  // 等500ms
DoEffect(); // 上下文连贯，像同步代码一样写
```

### RepeatedTimer — 周期重复式

```csharp
case TimerClass.RepeatedTimer:
{
    long timeNow = GetNow();
    timerAction.StartTime = timeNow;       // 以本次触发时间为新起点
    this.AddTimer(timerAction);            // 重新加入队列
    EventSystem.Instance.Invoke(timerAction.Type, new TimerCallback() { Args = timerAction.Object });
    break;
}
```

重复定时器不销毁，触发后更新 `StartTime` 重新加入时间队列。注意用"实际触发时间"而非"预期触发时间 + 间隔"作为新起点，避免时间漂移累积。

```csharp
// 使用方式
long timerId = TimerComponent.Instance.NewRepeatedTimer(1000, MyTimerType.PerSecond, null);
// 每秒触发一次 MyTimerType.PerSecond 对应的 Handler
```

---

## MultiMap + minTime：高效的时间队列

```csharp
private readonly MultiMap<long, long> TimeId = new();
private long minTime = long.MaxValue;
```

`MultiMap<long, long>` 是有序多值映射（内部基于 `SortedDictionary`），Key 是触发时间戳，Value 是该时间点注册的所有 timerId 列表。

### 快速跳过优化

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;

    long timeNow = GetNow();
    if (timeNow < this.minTime) return;  // 最小触发时间未到，直接跳过
    // ...
}
```

`minTime` 缓存了下一个最早触发时间。每帧 `Update` 首先与 `minTime` 比较：若当前时间连最早的定时器都没到，直接返回，完全跳过遍历。对于大量定时器的场景，这一行代码节省了绝大多数帧的开销。

### 超时收集 → 分离触发

```csharp
// 第一步：收集所有超时的时间点
foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
{
    long k = kv.Key;
    if (k > timeNow)
    {
        this.minTime = k;  // 更新新的最小未到时间
        break;
    }
    this.timeOutTime.Enqueue(k);
}

// 第二步：从 TimeId 移除，收集 timerId
while (this.timeOutTime.Count > 0)
{
    long time = this.timeOutTime.Dequeue();
    var list = this.TimeId[time];
    for (int i = 0; i < list.Count; ++i)
        this.timeOutTimerIds.Enqueue(list[i]);
    this.TimeId.Remove(time);
}

// 第三步：执行回调
while (this.timeOutTimerIds.Count > 0)
{
    long timerId = this.timeOutTimerIds.Dequeue();
    if (!this.timerActions.Remove(timerId, out TimerAction timerAction))
        continue;  // 已被取消，跳过
    this.Run(timerAction);
}
```

**为什么分三步？**

直接在遍历 `TimeId` 时执行回调是危险的——回调内部可能注册新的定时器，修改 `TimeId`，导致迭代器失效。三步分离：收集 → 移除 → 执行，保证了执行阶段 `TimeId` 已经整理完毕，回调内的注册操作不会干扰当前帧的触发逻辑。

---

## TimerAction 对象池

```csharp
public class TimerAction
{
    private static Stack<TimerAction> _pool = new Stack<TimerAction>();

    public static TimerAction Create(long id, TimerClass timerClass, long startTime, long time, int type, object obj)
    {
        TimerAction timerAction = GetFromPool();
        timerAction.Id = id;
        // ... 填充字段
        return timerAction;
    }

    public void Recycle()
    {
        this.Id = 0;
        this.Object = null;
        // ... 清空字段
        lock (_pool) { _pool.Push(this); }
    }

    private static TimerAction GetFromPool()
    {
        lock (_pool)
        {
            if (_pool.Count > 0) return _pool.Pop();
        }
        return new TimerAction();
    }
}
```

`TimerAction` 自带静态对象池，使用 `Stack<T>` + `lock` 实现线程安全的复用。每次定时器触发后调用 `Recycle()` 归还对象，避免频繁 GC 分配。

---

## WaitAsync / WaitTillAsync 异步等待实现

```csharp
public async ETTask WaitAsync(long time, ETCancellationToken cancellationToken = null, bool bWaitFrame = false)
{
    if (time == 0 && !bWaitFrame) return;

    long timeNow = GetNow();
    ETTask tcs = ETTask.Create(true);  // 创建一个未完成的 ETTask

    // 创建 OnceWaitTimer，持有 tcs 引用
    TimerAction timer = TimerAction.Create(this.GetId(), TimerClass.OnceWaitTimer, timeNow, time, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId))
            tcs.SetResult();  // 取消时也完成 TCS（不抛异常）
    }

    try
    {
        cancellationToken?.Add(CancelAction);
        await tcs;  // 挂起，等待定时器触发 SetResult
    }
    finally
    {
        cancellationToken?.Remove(CancelAction);
    }
}
```

**工作流程：**

1. 创建 `ETTask` TCS（未完成状态）
2. 创建 `OnceWaitTimer`，将 TCS 存入 `Object` 字段
3. `await tcs` 挂起当前异步方法
4. N毫秒后，`TimerComponent.Update` 触发，执行 `tcs.SetResult()`
5. 异步方法从 `await` 处恢复，继续执行后续逻辑

**取消支持：**

`ETCancellationToken` 提供取消能力。取消时 `CancelAction` 被调用，移除定时器并 `SetResult()`，确保 `await` 不会永久挂起。

### WaitTillAsync — 等待到绝对时间点

```csharp
public async ETTask WaitTillAsync(long tillTime, ETCancellationToken cancellationToken = null)
{
    long timeNow = GetNow();
    if (timeNow >= tillTime) return;  // 时间已过，直接返回

    ETTask tcs = ETTask.Create(true);
    TimerAction timer = TimerAction.Create(this.GetId(), TimerClass.OnceWaitTimer, timeNow, tillTime - timeNow, 0, tcs);
    // ...
}
```

`WaitTillAsync` 接受绝对时间戳，内部转换为相对等待时间。适合"等待到XX时刻"的语义。

### WaitFrameAsync / WaitFramesAsync

```csharp
public async ETTask WaitFrameAsync(ETCancellationToken cancellationToken = null)
{
    await this.WaitAsync(0, cancellationToken, true);  // bWaitFrame=true
}

public async ETTask WaitFramesAsync(int frameCount, ETCancellationToken cancellationToken = null)
{
    for (int i = 0; i < frameCount; i++)
        await this.WaitFrameAsync(cancellationToken);
}
```

`WaitAsync(0, bWaitFrame: true)` 特殊处理：time=0 通常直接返回，但 `bWaitFrame=true` 时仍创建定时器，等待下一帧触发。`WaitFramesAsync` 通过循环实现精确的帧数等待。

---

## NewOnceTimer vs WaitAsync 的选择

源码注释给出了明确的指导：

```
// 用这个优点是可以热更，缺点是回调式的写法，逻辑不连贯。
// WaitTillAsync 不能热更，优点是逻辑连贯。
// wait 时间短并且逻辑需要连贯的建议 WaitTillAsync
// wait 时间长不需要逻辑连贯的建议用 NewOnceTimer
```

| 特性 | NewOnceTimer | WaitAsync/WaitTillAsync |
|------|-------------|------------------------|
| 支持热更新 | ✅（EventSystem 分发）| ❌（闭包捕获） |
| 逻辑连贯 | ❌（回调碎片化） | ✅（await 上下文连续）|
| 适用等待时长 | 长（分钟级）| 短（秒级以内）|
| 取消支持 | 手动 Remove | ETCancellationToken |

---

## AddTimer 细节

```csharp
private void AddTimer(TimerAction timer)
{
    long tillTime = timer.StartTime + timer.Time;
    this.TimeId.Add(tillTime, timer.Id);
    this.timerActions.Add(timer.Id, timer);
    if (tillTime < this.minTime)
    {
        this.minTime = tillTime;  // 更新最小时间缓存
    }
}
```

每次添加定时器时，若新定时器的触发时间比当前 `minTime` 更早，则更新 `minTime`。这保证了 `minTime` 始终是系统中最早的一个触发时间点，使 `Update` 中的快速跳过判断始终有效。

---

## 实战使用模式

### 技能冷却（RepeatedTimer）

```csharp
long cooldownTimer = TimerComponent.Instance.NewRepeatedTimer(
    100,  // 每100ms更新一次冷却UI
    SkillTimerType.UpdateCooldown,
    skillComponent
);

// 技能结束时移除
TimerComponent.Instance.Remove(ref cooldownTimer);
```

### 异步技能序列（WaitAsync）

```csharp
public async ETTask CastSkill()
{
    PlayCastAnimation();
    await TimerComponent.Instance.WaitAsync(300);  // 等待施法前摇300ms
    
    SpawnProjectile();
    await TimerComponent.Instance.WaitAsync(500);  // 等待投射物飞行500ms
    
    ApplyDamage();
    PlayHitEffect();
}
```

### 延迟单次事件（NewOnceTimer）

```csharp
// 5分钟后自动保存存档
long saveTimerId = TimerComponent.Instance.NewOnceTimer(
    TimeHelper.ClientFrameTime() + 5 * TimeHelper.Minute,
    GameTimerType.AutoSave,
    null
);
```

---

## 总结

`TimerComponent` 的设计充分体现了"简单机制支撑复杂需求"的哲学：

1. **MultiMap + minTime**：有序多值映射 + 最小时间缓存，O(log n) 插入，每帧 O(1) 快速跳过
2. **TimerClass 枚举**：4种模式覆盖所有定时场景，统一在 `Run()` 方法中处理
3. **ETTask TCS 桥接**：`OnceWaitTimer` 将回调模型转换为异步等待，消除回调碎片
4. **TimerAction 对象池**：静态 Stack 池化，消除频繁创建的 GC 压力
5. **三步分离执行**：收集→移除→触发，防止回调内修改集合导致迭代异常

理解了这套设计，你会发现游戏中的所有时间驱动逻辑都可以被优雅地纳入这个统一的定时器体系。
