---
title: 游戏框架TimerComponent定时器系统深度解析-单次重复与异步等待的完整调度设计
published: 2026-04-17
description: '深度剖析 ET/xgame 框架中 TimerComponent 单例定时器的完整实现：TimerClass 枚举、TimerAction 对象池、MultiMap 时间索引、OnceTimer/RepeatedTimer/WaitAsync 三类调度接口及 LogicTimerComponent 帧驱动变体的工程细节。'
image: ''
tags: [Unity, 游戏框架, 定时器, ETTask, 异步编程, 对象池]
category: '技术分享'
draft: false
encryptedKey: henhaoji123
---

## 前言

定时器是游戏框架的基础设施之一。无论是技能冷却、BUFF 倒计时、Tween 动画，还是网络心跳、定期存档，背后都离不开一个高效、低 GC 的调度系统。

ET/xgame 框架提供了两套定时器实现：

- **TimerComponent**：基于真实毫秒时间，挂载于 Singleton 并实现 ISingletonUpdate，每帧驱动。
- **LogicTimerComponent**：基于帧号（FixedUpdate 帧计数），配合 TrueSync 定点数，专为帧同步战斗服务。

本文从源码出发，系统梳理两套定时器的设计思路与工程细节。

---

## 一、核心数据结构

### 1.1 TimerClass 枚举

```csharp
public enum TimerClass
{
    None,
    OnceTimer,       // 单次触发（事件回调式）
    OnceWaitTimer,   // 单次触发（异步等待式）
    RepeatedTimer,   // 重复触发
}
```

三类定时器覆盖了两种编程风格：
- **OnceTimer / RepeatedTimer**：回调驱动，适合逻辑跨帧、可热更的场景。
- **OnceWaitTimer**：Promise 风格，配合 `await` 使代码逻辑连贯，适合短等待。

### 1.2 TimerAction 对象池

```csharp
public class TimerAction
{
    private static Stack<TimerAction> _pool = new Stack<TimerAction>();

    public static TimerAction Create(long id, TimerClass timerClass,
        long startTime, long time, int type, object obj)
    {
        TimerAction timerAction = GetFromPool();
        // ...字段初始化
        return timerAction;
    }

    public void Recycle()
    {
        // 清空字段
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

**设计亮点：**

1. **自管理静态池**：不依赖外部 ObjectPool，Stack + lock 实现线程安全复用。
2. **零分配创建**：优先从池中取，减少 GC 压力。
3. **Recycle 语义**：手动回收，明确生命周期边界。

---

## 二、TimerComponent 核心实现

```csharp
public class TimerComponent : Singleton<TimerComponent>, ISingletonUpdate
{
    private readonly MultiMap<long, long> TimeId = new();      // 时间 -> 定时器ID列表
    private readonly Queue<long> timeOutTime = new();           // 超时时间暂存队列
    private readonly Queue<long> timeOutTimerIds = new();       // 超时ID暂存队列
    private readonly Dictionary<long, TimerAction> timerActions = new(); // ID -> Action
    private long minTime = long.MaxValue;                        // 最小到期时间缓存
}
```

### 2.1 MultiMap 时间索引

使用 `MultiMap<long, long>`（有序字典 + 列表值）维护"时间 → ID 集合"的映射：

- **有序性**：遍历时可按时间从小到大处理，一旦遇到未到期的 key 即可 break。
- **多值**：同一毫秒可有多个定时器同时触发。
- **minTime 优化**：缓存最小到期时间，避免每帧遍历整个 MultiMap。

### 2.2 Update 驱动逻辑

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;

    long timeNow = TimeHelper.ClientFrameTime();
    if (timeNow < this.minTime) return;   // 早退：未到最早计时器

    // 阶段一：找出所有到期 key
    foreach (var kv in this.TimeId)
    {
        if (kv.Key > timeNow)
        {
            this.minTime = kv.Key;
            break;
        }
        this.timeOutTime.Enqueue(kv.Key);
    }

    // 阶段二：收集到期 ID
    while (this.timeOutTime.Count > 0)
    {
        long time = this.timeOutTime.Dequeue();
        foreach (var id in this.TimeId[time])
            this.timeOutTimerIds.Enqueue(id);
        this.TimeId.Remove(time);
    }

    // 阶段三：执行回调
    while (this.timeOutTimerIds.Count > 0)
    {
        long timerId = this.timeOutTimerIds.Dequeue();
        if (!this.timerActions.Remove(timerId, out var action)) continue;
        this.Run(action);
    }
}
```

**两阶段队列模式**的意义：在遍历 TimeId 的过程中，`Run()` 可能触发新的定时器注册（修改 TimeId），直接在遍历中修改集合会抛异常。使用暂存队列将"收集"和"执行"解耦，避免迭代器失效。

### 2.3 Run 分发逻辑

```csharp
private void Run(TimerAction timerAction)
{
    switch (timerAction.TimerClass)
    {
        case TimerClass.OnceTimer:
            EventSystem.Instance.Invoke(timerAction.Type,
                new TimerCallback { Args = timerAction.Object });
            timerAction.Recycle();
            break;

        case TimerClass.OnceWaitTimer:
            ETTask tcs = timerAction.Object as ETTask;
            tcs.SetResult();    // 唤醒 await 的协程
            timerAction.Recycle();
            break;

        case TimerClass.RepeatedTimer:
            timerAction.StartTime = GetNow();
            this.AddTimer(timerAction);    // 重新入队
            EventSystem.Instance.Invoke(timerAction.Type,
                new TimerCallback { Args = timerAction.Object });
            break;
    }
}
```

- `OnceTimer`：触发 EventSystem 的 Invoke，然后回收 Action。
- `OnceWaitTimer`：通过 ETTask 的 SetResult() 唤醒挂起的协程。
- `RepeatedTimer`：先重新注册（维持重复），再触发回调，确保下一次准时触发。

---

## 三、异步等待接口

### 3.1 WaitAsync（等待 N 毫秒）

```csharp
public async ETTask WaitAsync(long time, ETCancellationToken cancellationToken = null, bool bWaitFrame = false)
{
    if (time == 0 && !bWaitFrame) return;

    long timeNow = GetNow();
    ETTask tcs = ETTask.Create(true);  // true = 从对象池分配
    TimerAction timer = TimerAction.Create(GetId(), TimerClass.OnceWaitTimer, timeNow, time, 0, tcs);
    AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (Remove(timerId)) tcs.SetResult();
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

**关键设计：**

1. `ETTask.Create(true)` 从对象池分配 Task，避免 new 分配。
2. 取消令牌通过闭包注入 `CancelAction`，取消时直接 SetResult 唤醒等待者。
3. `finally` 块确保无论正常结束还是取消，都会清理 CancelAction 注册。

### 3.2 WaitFrameAsync（等待一帧）

```csharp
public async ETTask WaitFrameAsync(ETCancellationToken cancellationToken = null)
{
    await WaitAsync(0, cancellationToken, true);  // time=0 但 bWaitFrame=true
}
```

`bWaitFrame = true` 时，即使 time=0 也会创建 OnceWaitTimer，确保真正等到下一帧，而不是立即返回。

### 3.3 WaitTillAsync（等待到指定时刻）

```csharp
public async ETTask WaitTillAsync(long tillTime, ETCancellationToken cancellationToken = null)
{
    long timeNow = GetNow();
    if (timeNow >= tillTime) return;   // 已过期，立即返回

    ETTask tcs = ETTask.Create(true);
    TimerAction timer = TimerAction.Create(GetId(), TimerClass.OnceWaitTimer,
        timeNow, tillTime - timeNow, 0, tcs);
    AddTimer(timer);
    // ... 同 WaitAsync 的取消处理
}
```

适合需要等到某个绝对时间点的场景（如活动结束时间）。

---

## 四、外部调用接口

```csharp
// 单次定时器（回调式，可热更）
public long NewOnceTimer(long tillTime, int type, object args);

// 重复定时器
public long NewRepeatedTimer(long time, int type, object args);

// 逐帧定时器
public long NewFrameTimer(int type, object args);

// 取消定时器（传 ref，取消后自动置零）
public bool Remove(ref long id);
```

**`Remove(ref long id)` 的设计哲学：**

传引用并置零，防止外部持有过期 ID 再次调用 Remove 造成错误取消。这是一种防御性编程模式，强制调用者的 ID 变量失效。

---

## 五、LogicTimerComponent：帧同步变体

与 TimerComponent 相比，LogicTimerComponent 的核心差异：

| 对比项 | TimerComponent | LogicTimerComponent |
|--------|---------------|---------------------|
| 时间单位 | 毫秒（long） | 帧数（long，由 FP 转换） |
| 驱动接口 | ISingletonUpdate | ISingletonFixedUpdate |
| 时间获取 | TimeHelper.ClientFrameTime() | 内部 frameNow++ |
| 暂停支持 | 无 | EngineRuntime.Pause 检测 |
| 对象池 | 自管理 Stack | ObjectPool 统一管理 |

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
        Update();
}
```

帧同步中，逻辑时间由 FixedUpdate 驱动，而非真实时间，确保所有客户端在相同帧号触发相同定时器，保证确定性。

FP（定点数）转帧数的转换：
```csharp
timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
```

使用定点数除法保证跨平台确定性，避免浮点误差导致不同端在不同帧触发。

---

## 六、使用示例

### 6.1 异步等待（推荐，逻辑连贯）

```csharp
// 等待 3 秒后执行
await TimerComponent.Instance.WaitAsync(3000);
Log.Info("3秒后执行");

// 等待到下一帧
await TimerComponent.Instance.WaitFrameAsync();
```

### 6.2 回调式定时器（可热更场景）

```csharp
// 注册回调处理器
[Invoke(TimerInvokeType.BuffExpire)]
public class BuffExpireTimer : AInvokeHandler<TimerCallback>
{
    public override void Handle(TimerCallback args)
    {
        var buffId = (long)args.Args;
        BuffComponent.Instance.RemoveBuff(buffId);
    }
}

// 注册定时器
long timerId = TimerComponent.Instance.NewOnceTimer(
    TimeHelper.ClientFrameTime() + 3000,
    TimerInvokeType.BuffExpire,
    buffId
);
```

### 6.3 可取消的等待

```csharp
var cts = new ETCancellationToken();
await TimerComponent.Instance.WaitAsync(5000, cts);

// 其他逻辑中取消
cts.Cancel();
```

---

## 七、性能优化总结

1. **minTime 早退**：每帧先判断最小时间，未到期直接跳过，时间复杂度 O(1)。
2. **两阶段队列**：分离遍历和执行，避免集合修改冲突。
3. **TimerAction 自管理池**：减少 GC，复用 TimerAction 对象。
4. **ETTask 对象池**：`ETTask.Create(true)` 从池分配，WaitAsync 零堆分配。
5. **有序 MultiMap**：按时间排序，遍历时可提前终止。

---

## 八、设计模式总结

TimerComponent 体现了以下设计原则：

- **单一职责**：只负责时间调度，不感知业务逻辑。
- **开闭原则**：通过 `type + object` 参数对接 EventSystem，无需修改定时器代码扩展业务。
- **对象复用**：TimerAction / ETTask 均有对象池，零 GC 是核心目标。
- **防御性设计**：`Remove(ref id)` 强制置零，避免悬空 ID 引发错误。

定时器系统看似简单，实则是整个异步编程体系的重要支柱——每一个 `await WaitAsync()` 的背后，都是一次 TimerComponent 的精准调度。

---

*本文基于 xgame/ET 框架源码分析，适用于 Unity 客户端游戏框架深度学习。*
