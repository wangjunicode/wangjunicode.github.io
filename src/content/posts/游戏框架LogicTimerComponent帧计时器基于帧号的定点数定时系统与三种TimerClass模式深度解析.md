---
title: 游戏框架LogicTimerComponent帧计时器基于帧号的定点数定时系统与三种TimerClass模式深度解析
published: 2026-04-26
description: 深入解析ET/ECS游戏框架中LogicTimerComponent帧级逻辑定时器的完整设计：TrueSync FP定点数帧时间转换、MultiMap帧号有序索引、minTime快速剪枝优化，以及OnceTimer/OnceWaitTimer/RepeatedTimer三种计时模式的工程选型策略与暂停安全机制。
tags: [Unity, ECS, 游戏框架, C#, 定时器, 帧同步, TrueSync]
category: 技术
draft: false
encryptedKey: henhaoji123
---

## 前言

游戏中有两类计时需求：一类是**显示时间驱动**（实际流逝的秒数），适合处理UI倒计时、动画播放等；另一类是**逻辑帧驱动**（固定步长帧计数），适合战斗逻辑、帧同步状态机等对时间精度要求严格的场景。

`LogicTimerComponent` 是后者的代表。它抛弃了依赖系统时钟的实现方式，完全基于**逻辑帧号**驱动，天然与帧同步系统对齐，是 ET 框架中战斗层计时的核心单例。

---

## 一、TrueSync FP定点数：逻辑时间的精度基础

```csharp
public static LogicTimerAction Create(long id, TimerClass timerClass,
    long startFrame, FP time, int type, object obj)
{
    timerAction.Frame = TSMath.RoundToInt(time / EngineDefine.fixedDeltaTime_Orignal);
    // ...
}
```

`FP`（Fixed Point）是 TrueSync 库提供的 64 位定点数类型，专为跨平台帧同步设计。浮点数（float/double）在不同 CPU 架构上可能产生微小精度差异，在帧同步场景下会导致**逻辑分叉**（desync）。FP 定点数通过纯整数运算确保多端完全一致的结果。

计时逻辑的核心转换公式：

```
目标帧偏移 = RoundToInt(时间(FP秒) / 固定步长(FP秒))
触发帧号   = 起始帧号 + 目标帧偏移
```

`EngineDefine.fixedDeltaTime_Orignal` 是全局固定物理帧步长（典型值 0.033FP 即 30fps，或 0.0166FP 即 60fps），所有逻辑定时器统一对齐到此步长，避免与 Unity FixedUpdate 的浮点误差耦合。

---

## 二、MultiMap 帧号索引：有序触发的数据结构设计

```csharp
private readonly MultiMap<long, long> TimeId = new();
// Key: 触发帧号, Value: List<timerId>
```

`MultiMap<long, long>` 是框架自定义的**有序多值字典**（基于 `SortedDictionary`），以触发帧号为键，支持同帧多个定时器。这个选型是精心设计的：

- **有序性**：遍历时按帧号升序，天然支持早退出（遇到未到期帧即停止）
- **多值性**：同一帧可挂载任意数量的定时器，无冲突

### minTime 快速剪枝优化

```csharp
private long minTime = long.MaxValue;

public void Update()
{
    if (this.TimeId.Count == 0) return;
    
    frameNow++;
    
    if (frameNow < this.minTime) return; // O(1) 快速剪枝
    // ...
}
```

`minTime` 记录当前注册的**最早触发帧号**。绝大多数帧里 `frameNow < minTime`，直接 `return`，完全跳过 MultiMap 遍历，将常规帧的时间复杂度降至 `O(1)`。只有真正有定时器到期时（相对低频），才执行 `O(k)` 的遍历（k 为到期帧数量）。

---

## 三、帧推进的三阶段处理流程

每次触发到期定时器的完整流程分三步，使用两个临时 Queue 避免并发修改问题：

```csharp
// 第一阶段：收集到期的帧号
foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
{
    long k = kv.Key;
    if (k > frameNow)
    {
        this.minTime = k; // 更新下一个最小帧
        break;            // SortedDictionary 有序，安全早退出
    }
    this.timeOutTime.Enqueue(k);
}

// 第二阶段：收集到期帧的所有 timerId，并从 TimeId 中移除
while (this.timeOutTime.Count > 0)
{
    long time = this.timeOutTime.Dequeue();
    var list = this.TimeId[time];
    for (int i = 0; i < list.Count; ++i)
        this.timeOutTimerIds.Enqueue(list[i]);
    this.TimeId.Remove(time);
}

// 第三阶段：执行到期定时器的回调
while (this.timeOutTimerIds.Count > 0)
{
    long timerId = this.timeOutTimerIds.Dequeue();
    if (!this.timerActions.Remove(timerId, out LogicTimerAction timerAction)) continue;
    this.Run(timerAction);
}
```

两阶段分离的原因：回调执行（`Run`）可能触发新的定时器注册或移除，如果边遍历边修改 `TimeId` 和 `timerActions`，会引发 `InvalidOperationException`。临时 Queue 缓冲彻底规避了这个问题。

---

## 四、三种 TimerClass 模式：选型指南

```csharp
private void Run(LogicTimerAction timerAction)
{
    switch (timerAction.TimerClass)
    {
        case TimerClass.OnceTimer:
            EventSystem.Instance.Invoke(timerAction.Type,
                new TimerCallback() { Args = timerAction.Object });
            timerAction.Recycle(); // 执行后回收
            break;

        case TimerClass.OnceWaitTimer:
            ETTask tcs = timerAction.Object as ETTask;
            tcs.SetResult(); // 唤醒等待的协程
            timerAction.Recycle();
            break;

        case TimerClass.RepeatedTimer:
            timerAction.StartFrame = frameNow;
            this.AddTimer(timerAction);  // 重新注册下一次触发
            EventSystem.Instance.Invoke(timerAction.Type,
                new TimerCallback() { Args = timerAction.Object });
            break;
    }
}
```

| 模式 | 触发次数 | 编程风格 | 适用场景 |
|---|---|---|---|
| `OnceTimer` | 一次 | 回调式（Invoke分发） | 延迟执行、技能冷却到期、可热更 |
| `OnceWaitTimer` | 一次 | await 协程式 | 逻辑连贯的等待，如 `await WaitAsync(0.5)` |
| `RepeatedTimer` | 循环 | 回调式 | 周期性 Tick，如 Buff 每帧/每秒效果 |

框架源码注释中有一段珍贵的选型建议：

> **OnceTimer 优点**：可以热更（代码重载后 Invoke 分发表更新，但定时器还在）。  
> **OnceWaitTimer/WaitAsync 优点**：逻辑连贯，协程式书写自然。  
> **推荐**：wait 时间短且逻辑连贯用 WaitAsync；wait 时间长且不需要逻辑连贯用 NewOnceTimer。

---

## 五、WaitAsync 的协程挂起与取消机制

```csharp
public async ETTask WaitAsync(FP time, ETCancellationToken cancellationToken = null)
{
    ETTask tcs = ETTask.Create(true);
    LogicTimerAction timer = LogicTimerAction.Create(
        this.GetId(), TimerClass.OnceWaitTimer, frameNow, time, 0, tcs);
    this.AddTimer(timer);
    long timerId = timer.Id;

    void CancelAction()
    {
        if (this.Remove(timerId))
            tcs.SetResult(); // 取消时也要唤醒协程，避免泄漏
    }

    try
    {
        cancellationToken?.Add(CancelAction);
        await tcs;
    }
    finally
    {
        cancellationToken?.Remove(CancelAction); // 确保取消动作注销
    }
}
```

`WaitAsync` 的实现是 ET 框架协程与定时器系统深度整合的典范：

1. 创建一个 `ETTask` 作为 `OnceWaitTimer` 的 "Object" 载荷
2. 当定时器到期，`Run()` 调用 `tcs.SetResult()` 唤醒协程
3. 取消令牌（`ETCancellationToken`）注册了 `CancelAction`，保证在外部取消时**立即唤醒协程**而非等到超时，同时在 `finally` 块中移除取消监听，防止二次触发

这个模式完整覆盖了"等待完成"、"主动取消"、"超时完成"三种场景，是生产级异步等待的标准实现范式。

---

## 六、暂停安全机制

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
    {
        Update(); // 只在非暂停状态推进帧号
    }
}

public void FixedUpdate() { }
public void LateFixedUpdate() { }
```

`LogicTimerComponent` 实现了 `ISingletonFixedUpdate` 接口，真正的帧推进逻辑放在 `BeforeFixedUpdate` 中，并接受 `EngineRuntime.Pause` 全局暂停标志的控制。

当游戏暂停时（调试/战斗暂停/网络等待），`frameNow` **不再递增**，所有逻辑定时器自然冻结，无需修改各定时器的触发帧号。这是帧号计时相比时间戳计时的天然优势：**暂停即停止，恢复即继续，零侵入**。

---

## 七、LogicTimerAction 对象池复用

```csharp
public static LogicTimerAction Create(...) 
{
    LogicTimerAction timerAction = ObjectPool.Instance.Fetch<LogicTimerAction>();
    // ... 赋值 ...
    return timerAction;
}

public void Recycle()
{
    this.Id = 0;
    this.Object = null;
    this.StartFrame = 0;
    this.Frame = 0;
    this.TimerClass = TimerClass.None;
    this.Type = 0;
    ObjectPool.Instance.Recycle(this);
}
```

每个 `LogicTimerAction` 都通过 `ObjectPool.Instance` 进行池化复用，避免在高频定时器场景下产生大量 GC 压力。`Recycle()` 方法在回收前**清零所有字段**，防止旧数据污染下次使用。

`Remove()` 方法还有一个细节：

```csharp
if (this.timerActions.Count == 0)
{
    frameNow = 0; // 所有定时器清空后重置帧计数器
}
```

当定时器全部清空时，`frameNow` 归零，防止 `long` 溢出（理论上 long 上限约 9.2×10¹⁸，但良好习惯是在自然边界重置）。

---

## 八、与 TimerComponent 的对比

| 特性 | LogicTimerComponent | TimerComponent |
|---|---|---|
| 时间基准 | 逻辑帧号 | 毫秒时间戳 |
| 适用层 | 战斗逻辑/帧同步 | UI/网络/业务逻辑 |
| 精度单位 | FP 定点数（无浮点误差） | long 毫秒（受系统时钟影响） |
| 暂停支持 | 内置（EngineRuntime.Pause） | 需额外处理 |
| 驱动接口 | ISingletonFixedUpdate | ISingletonUpdate |

两者共存于框架中，各司其职。战斗层的定时需求（技能持续时间、状态效果 Tick、帧同步超时检测）应使用 `LogicTimerComponent`；而与真实时间强相关的需求（网络超时、UI 倒计时、日程任务）则由 `TimerComponent` 负责。

---

## 小结

`LogicTimerComponent` 展示了一种将**定点数精度**、**帧号语义**、**协程集成**和**暂停安全**融为一体的游戏定时器设计范式。其核心思想是：逻辑时间不应依赖物理时钟，而应作为逻辑帧的副产品——帧推进则时间流逝，帧冻结则时间停止。这种设计让战斗逻辑与帧同步系统天然对齐，也是现代竞技游戏引擎中处理战斗计时的成熟实践。
