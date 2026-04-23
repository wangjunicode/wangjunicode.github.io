---
title: 游戏定时器系统双轨架构-TimerComponent与LogicTimerComponent的时间驱动与帧驱动设计解析
published: 2026-04-23
description: 深入解析ET游戏框架中TimerComponent（毫秒级时间驱动）与LogicTimerComponent（逻辑帧驱动）的双定时器架构，涵盖三类定时器模式、MultiMap有序调度、ETTask异步等待和战斗确定性同步设计。
image: ''
tags: [Unity, ET框架, 定时器, 异步编程, 游戏架构]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

在游戏框架中，"时间"是驱动一切逻辑的核心维度。ET框架提供了两套定时器组件：面向客户端渲染帧的 `TimerComponent`（毫秒精度）和面向逻辑帧的 `LogicTimerComponent`（帧计数精度）。两者并行存在，各司其职，构成了**双轨定时器架构**。本文从源码层面剖析其设计思路与实现细节。

---

## 一、定时器类型枚举

框架定义了三种定时器类型，两个组件共享同一 `TimerClass` 枚举：

```csharp
public enum TimerClass
{
    None,
    OnceTimer,      // 一次性回调定时器（事件驱动）
    OnceWaitTimer,  // 一次性等待定时器（ETTask异步等待）
    RepeatedTimer,  // 重复定时器
}
```

| 类型 | 触发方式 | 适用场景 |
|------|----------|----------|
| OnceTimer | EventSystem.Invoke 回调 | 可热更，逻辑不需要连续 |
| OnceWaitTimer | ETTask.SetResult() | async/await 内联等待 |
| RepeatedTimer | EventSystem.Invoke 循环 | 周期性逻辑帧任务 |

> 框架注释揭示了设计权衡：**OnceTimer 可热更但逻辑不连贯；WaitAsync 不能热更但逻辑连贯**。这是框架团队在工程实践中做出的显式取舍。

---

## 二、TimerComponent：毫秒级时间驱动

### 2.1 核心数据结构

```csharp
public class TimerComponent: Singleton<TimerComponent>, ISingletonUpdate
{
    private readonly MultiMap<long, long> TimeId = new();   // 触发时间 -> [timerId列表]
    private readonly Queue<long> timeOutTime = new();
    private readonly Queue<long> timeOutTimerIds = new();
    private readonly Dictionary<long, TimerAction> timerActions = new();
    private long minTime = long.MaxValue;
}
```

**MultiMap** 是框架自定义的有序多值映射容器（内部基于 SortedDictionary），按触发时间排序存储定时器 ID 列表。`minTime` 记录最近一次到期时间，避免每帧遍历整个集合的开销。

### 2.2 Update 调度流程

```csharp
public void Update()
{
    if (this.TimeId.Count == 0) return;

    long timeNow = GetNow(); // TimeHelper.ClientFrameTime()

    if (timeNow < this.minTime) return; // 快速路径：还没到最早触发时间

    // 第一步：收集所有已超时的时间键
    foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
    {
        long k = kv.Key;
        if (k > timeNow) { this.minTime = k; break; }
        this.timeOutTime.Enqueue(k);
    }

    // 第二步：将超时时间键对应的所有 timerId 加入待触发队列
    while (this.timeOutTime.Count > 0)
    {
        long time = this.timeOutTime.Dequeue();
        var list = this.TimeId[time];
        for (int i = 0; i < list.Count; ++i)
            this.timeOutTimerIds.Enqueue(list[i]);
        this.TimeId.Remove(time);
    }

    // 第三步：触发所有超时定时器
    while (this.timeOutTimerIds.Count > 0)
    {
        long timerId = this.timeOutTimerIds.Dequeue();
        if (!this.timerActions.Remove(timerId, out TimerAction timerAction)) continue;
        this.Run(timerAction);
    }
}
```

这里有一个值得注意的设计：遍历 MultiMap 时**先收集再处理**，而非边遍历边修改。这是因为 `Run` 内部对于 RepeatedTimer 会调用 `AddTimer`（修改 TimeId），边遍历边修改会导致集合修改异常。

### 2.3 TimerAction 对象池

```csharp
public class TimerAction
{
    private static Stack<TimerAction> _pool = new Stack<TimerAction>();

    public static TimerAction Create(long id, TimerClass timerClass, 
                                     long startTime, long time, int type, object obj)
    {
        TimerAction timerAction = GetFromPool();
        // ... 填充字段
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

`TimerAction` 内置了一个线程安全的 `Stack<T>` 对象池。注意这里用 `lock` 保护，因为 `Recycle` 可能从 Update 线程和取消回调线程同时调用。

### 2.4 异步等待 API

```csharp
// 等待到指定时间点
public async ETTask WaitTillAsync(long tillTime, ETCancellationToken cancellationToken = null)
{
    long timeNow = GetNow();
    if (timeNow >= tillTime) return;

    ETTask tcs = ETTask.Create(true);
    TimerAction timer = TimerAction.Create(this.GetId(), TimerClass.OnceWaitTimer, timeNow, tillTime - timeNow, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId)) tcs.SetResult(); // 取消时也SetResult，让await继续
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

// 等待N毫秒
public async ETTask WaitAsync(long time, ETCancellationToken cancellationToken = null, bool bWaitFrame = false)

// 等待1帧
public async ETTask WaitFrameAsync(ETCancellationToken cancellationToken = null)

// 等待N帧
public async ETTask WaitFramesAsync(int frameCount, ETCancellationToken cancellationToken = null)
```

`ETCancellationToken` 的取消通过注册/注销 `CancelAction` 闭包实现，取消时调用 `tcs.SetResult()` 而非 `SetException`，保证了异步链的正常继续（调用方需自行判断是否真正超时）。

---

## 三、LogicTimerComponent：帧驱动逻辑定时器

### 3.1 与 TimerComponent 的核心区别

`LogicTimerComponent` 实现了 `ISingletonFixedUpdate`，在 `BeforeFixedUpdate` 中驱动：

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause) // 暂停时停止推进
    {
        Update();
    }
}
```

时间单位从**毫秒**变成了**帧计数**：

```csharp
// TimerComponent：基于毫秒时间戳
private long GetNow() => TimeHelper.ClientFrameTime();

// LogicTimerComponent：基于帧计数
private long frameNow = 0;
// Update() 内每次调用 frameNow++
```

### 3.2 时间到帧的转换

`LogicTimerAction.Create` 中将时间（FP定点数）转换为帧数：

```csharp
timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
```

使用 `TrueSync` 的定点数（`FP`）计算，避免浮点数不一致问题，这对联机游戏的逻辑帧同步至关重要。

### 3.3 暂停与重置机制

逻辑帧定时器在所有定时器移除后会重置帧计数：

```csharp
private bool Remove(long id)
{
    // ...
    timerAction.Recycle();
    if (this.timerActions.Count == 0)
    {
        frameNow = 0; // 没有任何定时器时重置帧计数
    }
    return true;
}
```

`BeforeFixedUpdate` 检查 `EngineRuntime.Pause`，游戏暂停时不推进 `frameNow`，逻辑定时器天然支持暂停，时间驱动的 `TimerComponent` 则做不到（时钟不受控）。

---

## 四、双轨架构的设计意图

| 维度 | TimerComponent | LogicTimerComponent |
|------|---------------|---------------------|
| 驱动周期 | Update（渲染帧） | FixedUpdate（逻辑帧） |
| 时间单位 | 毫秒（long） | 帧数（long） |
| 时间来源 | ClientFrameTime() | frameNow计数器 |
| 暂停支持 | ❌ 时钟持续推进 | ✅ 可暂停 |
| 确定性 | ❌ 浮点/不确定 | ✅ 定点数，确定性 |
| 适用场景 | UI动画、音效、延迟显示 | 战斗逻辑、技能CD、联机同步 |

这种分离设计体现了**表现层与逻辑层解耦**的架构思想：UI 动画跟随渲染帧，战斗逻辑跟随物理帧，两者互不干扰，且逻辑帧具有确定性，为帧同步联机奠定基础。

---

## 五、ATimer 抽象基类

```csharp
public abstract class ATimer<T>: AInvokeHandler<TimerCallback> where T: class
{
    public override void Handle(TimerCallback a)
    {
        this.Run(a.Args as T);
    }

    protected abstract void Run(T t);
}
```

`ATimer<T>` 是定时器回调的抽象模板，继承自 `AInvokeHandler<TimerCallback>`。使用者只需实现 `Run(T t)` 方法，框架通过 `EventSystem.Invoke` 分发到对应 handler。这将**定时器触发**与**具体逻辑执行**解耦，同时支持热更。

---

## 六、使用示例

### 一次性等待（async/await 风格）

```csharp
// 等待2秒
await TimerComponent.Instance.WaitAsync(2000);

// 等待到某个时间点，支持取消
var cts = new ETCancellationToken();
await TimerComponent.Instance.WaitTillAsync(TimeHelper.ClientNow() + 5000, cts);
```

### 回调式定时器（支持热更）

```csharp
// 注册定时器类型
[ObjectSystem]
public class MyTimerHandler: ATimer<MyArgs>
{
    protected override void Run(MyArgs args)
    {
        // 定时触发逻辑
    }
}

// 创建定时器
long timerId = TimerComponent.Instance.NewOnceTimer(
    TimeHelper.ClientNow() + 3000,
    (int)TimerType.MyTimer, 
    myArgs
);

// 取消定时器
TimerComponent.Instance.Remove(ref timerId);
```

### 逻辑帧等待（战斗中使用）

```csharp
// 在战斗逻辑中等待0.5秒逻辑时间（确定性）
await LogicTimerComponent.Instance.WaitAsync((FP)0.5f);

// 每逻辑帧触发的重复定时器
long id = LogicTimerComponent.Instance.NewFrameTimer((int)LogicTimerType.SkillTick, skillData);
```

---

## 七、小结

ET框架的双定时器架构通过清晰的职责划分解决了游戏开发中的两个关键矛盾：

1. **实时性 vs 确定性**：`TimerComponent` 追求实时响应，`LogicTimerComponent` 追求确定性同步。
2. **热更 vs 逻辑连贯**：`NewOnceTimer` 可热更但回调式，`WaitAsync` 不可热更但逻辑内联。

`minTime` 优化、对象池复用、双队列缓冲（先收集再处理）等实现细节，体现了框架在高频调度场景下对性能的持续打磨。理解这套架构，是编写高质量游戏逻辑的基础。
