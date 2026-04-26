---
title: 游戏框架EventSystem双总线架构Publish与Invoke的设计哲学与TypeSystems分层调度深度解析
published: 2026-04-26
description: 深度剖析ET/ECS游戏框架中EventSystem单例的完整实现：从TypeSystems两级缓存结构、InstanceQueueIndex队列调度机制，到Publish异步事件总线与Invoke强约束函数分发总线的核心差异，揭示场景感知过滤、VProfiler性能埋点与热更新注册的工程设计精要。
tags: [Unity, ECS, 游戏框架, C#, 事件系统, 架构设计]
category: 技术
draft: false
encryptedKey: henhaoji123
---

## 前言

事件系统是游戏框架解耦的核心基础设施。ET框架的 `EventSystem` 并不是一个简单的观察者模式容器——它同时承担了**ECS组件的生命周期调度中枢**、**跨模块事件总线**和**强类型函数分发器**三重职责。理解它的设计，能让我们对整个框架的运转逻辑豁然开朗。

---

## 一、TypeSystems：两级类型缓存架构

`EventSystem` 内部用两个私有嵌套类构建了类型系统缓存：

```csharp
private class OneTypeSystems
{
    public readonly UnOrderMultiMap<Type, object> Map = new();
    public readonly bool[] QueueFlag = new bool[(int)InstanceQueueIndex.Max];
}

private class TypeSystems
{
    private readonly Dictionary<Type, OneTypeSystems> typeSystemsMap = new();

    public OneTypeSystems GetOrCreateOneTypeSystems(Type type) { ... }
    public List<object> GetSystems(Type type, Type systemType) { ... }
}
```

**第一层：TypeSystems** —— 以 Entity 组件类型为键，存储对应的所有 System 实现；  
**第二层：OneTypeSystems** —— 以 System 接口类型（如 `IUpdateSystem`、`IAwakeSystem`）为键，存储多个实现对象。

`QueueFlag` 数组是一个重要的性能优化点：在 `Add()` 注册阶段，对每个 System 检查 `GetInstanceQueueIndex()` 返回值，预先标记该类型是否参与对应帧更新队列（Update/FixedUpdate/LateUpdate等）。这样在运行时无需重复反射查询，直接 `O(1)` 判断。

---

## 二、Add()：框架的"类型注册引导阶段"

```csharp
public void Add(Dictionary<string, Type> addTypes)
{
    // 1. 刷新全类型表
    // 2. 按 ObjectSystemAttribute 构建 TypeSystems
    // 3. 按 EventAttribute 注册事件处理器
    // 4. 按 InvokeAttribute 注册 Invoke 分发表
}
```

整个 `Add()` 是框架启动或热更重载时触发的**全量注册流程**，分三个阶段：

| 阶段 | 特性 | 目标容器 |
|---|---|---|
| ObjectSystem 阶段 | `ObjectSystemAttribute` | `typeSystems`（组件生命周期） |
| Event 阶段 | `EventAttribute` | `allEvents`（跨模块事件） |
| Invoke 阶段 | `InvokeAttribute` | `allInvokes`（强类型回调） |

值得注意的是，`typeSystems` 在每次 `Add()` 时**全量重建**（`this.typeSystems = new TypeSystems()`），这保证了热更代码重载后不会残留旧的 System 引用。

---

## 三、InstanceQueueIndex 队列调度：ECS 帧驱动引擎

`EventSystem` 维护一个 `Queue<long>[] queues` 数组，每个槽对应一种帧更新类型：

```csharp
private readonly Queue<long>[] queues = new Queue<long>[(int)InstanceQueueIndex.Max];
```

当调用 `RegisterSystem(entity)` 时，根据 `QueueFlag` 将实体的 `InstanceId` 入队：

```csharp
for (int i = 0; i < oneTypeSystems.QueueFlag.Length; ++i)
{
    if (!oneTypeSystems.QueueFlag[i]) continue;
    this.queues[i].Enqueue(component.InstanceId);
}
```

**关键设计**：每帧调度时，队列采用"快照计数"模式：

```csharp
int count = queue.Count;   // 记录帧初队列长度
while (count-- > 0)
{
    long instanceId = queue.Dequeue();
    // ... 执行系统 ...
    queue.Enqueue(instanceId); // 重新入队，循环驱动
}
```

这个 `count` 快照确保**本帧内新注册的实体不会立刻参与本帧调度**，避免无限循环，也是 Start 系统"延迟一帧执行"的实现基础。

---

## 四、Publish vs Invoke：两条总线的哲学差异

框架作者在源码注释中留下了这段极具价值的设计说明：

> **Invoke** 类似函数，必须有被调用方，否则异常。调用者跟被调用者属于**同一模块**，比如 TimerComponent 中的计时器回调。  
> **Publish** 是事件，抛出去可以没人订阅。调用者跟被调用者属于**两个模块**，比如任务系统订阅道具使用事件。

### Publish：场景感知的异步事件总线

```csharp
public void Publish<T>(Scene scene, T a)
{
    foreach (EventInfo eventInfo in iEvents)
    {
        // 场景类型过滤 —— 核心设计
        if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
            continue;

        if (eventInfo.IEvent is AEvent<T> aEvent)
            aEvent.Handle(scene, a);
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            aAsyncEvent.Handle(scene, a).Coroutine(); // 异步事件即发即忘
    }
}
```

Publish 的 **SceneType 过滤**是其最核心的设计亮点：同一事件类型在不同场景（客户端大厅/战斗场景/服务端等）可以有不同的处理器，`EventAttribute(SceneType.xxx)` 标记决定了处理器的适用范围。`SceneType.None` 表示全场景通用。

`PublishAsync` 变体会收集所有异步任务，统一 `await ETTaskHelper.WaitAll(list)`，实现事件的并行异步执行。

### Invoke：强约束的类型化函数分发

```csharp
public void Invoke<A>(int type, A args) where A : struct
{
    if (!this.allInvokes.TryGetValue(typeof(A), out var invokeHandlers))
        throw new Exception($"Invoke error: {typeof(A).Name}"); // 无注册 = 报错

    if (!invokeHandlers.TryGetValue(type, out var invokeHandler))
        throw new Exception($"Invoke error: {typeof(A).Name} {type}");

    var aInvokeHandler = invokeHandler as AInvokeHandler<A>;
    aInvokeHandler.Handle(args);
}
```

Invoke 的参数类型 `A` 要求是 `struct`（值类型），配合 `type` 整数作为二级分发键（例如 TimerType 枚举值），构成 **两级分发表**：`typeof(A) → type → handler`。

泛型返回值版本 `Invoke<A, T>(...)` 当找不到处理器时**返回 default 而非抛异常**，体现了它在"函数调用场景"中的容错设计。

---

## 五、VProfiler 性能埋点的条件编译集成

```csharp
public void Publish<T>(Scene scene, T a)
{
    VProfiler.BeginDeepSample("EventSystem.Publish");
    // ...
#if ONLY_CLIENT
    using var _ = ProfilingMarker.EvtMarker<T>.Marker.Auto();
#endif
    // ...
    VProfiler.EndDeepSample();
}
```

通过 `#if ONLY_CLIENT` 条件编译，性能埋点**仅在客户端构建中生效**，避免服务端运行时引入额外开销。`ProfilingMarker.EvtMarker<T>` 是一个泛型静态类，每个事件类型 T 对应独立的 Marker 实例，可以精确追踪每种事件的 CPU 耗时分布。

---

## 六、RegisterOneEvent2 的热更新陷阱

```csharp
/// <summary>
/// This is bad, when EventSystem reloads, all event registered by this is dropped
/// </summary>
public void RegisterOneEvent2(Type hdrType, SceneType scenType) { ... }
```

框架作者在此留下了一个明确的警告注释：通过 `RegisterOneEvent2` 手动注册的事件处理器，**在热更重载（`Add()` 重建 allEvents）时会丢失**。这是因为它绕过了 `EventAttribute` 反射注册流程，直接向 `allEvents` 添加条目，无法被重载机制感知。

在生产代码中应优先使用 `EventAttribute + Add()` 模式，仅在特殊场景（动态运行时注册、不参与热更的模块）才考虑 `RegisterOneEvent2`。

---

## 七、FindEntitiesOfType 与实体全局索引

```csharp
private readonly Dictionary<long, Entity> allEntities = new();

public ListComponent<Entity> FindEntitiesOfType<T>() where T : Entity
{
    var result = ListComponent<Entity>.Create();
    foreach (var entity in allEntities.Values)
    {
        if (entity is T) result.Add(entity);
    }
    return result;
}
```

`allEntities` 是全局实体索引，所有注册到 EventSystem 的 Entity 都在此留档。`FindEntitiesOfType<T>` 返回 `ListComponent<Entity>`（对象池复用的列表），调用方需要记得 Dispose，避免内存泄漏。

在大型场景中该方法的时间复杂度是 `O(n)`（n 为实体总数），**不适合每帧高频调用**，更适用于调试、初始化或低频查询场景。

---

## 八、设计总结

| 特性 | Publish | Invoke |
|---|---|---|
| 订阅者为空 | 静默通过 | 抛出异常 |
| 调用关系 | 跨模块，弱耦合 | 同模块，强约束 |
| 返回值 | 无（或 async） | 支持泛型返回 |
| 场景过滤 | 支持 SceneType | 不适用 |
| 注册方式 | EventAttribute | InvokeAttribute |

EventSystem 的精妙之处在于将**ECS生命周期调度**（Awake/Update/Destroy等）和**业务事件通信**（Publish/Invoke）统一到一个单例中，通过反射注册+实例队列驱动，在零手写连接代码的前提下实现了完整的框架运转。这是 ET 框架架构设计中值得反复品味的核心设计之一。
