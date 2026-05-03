---
title: xgame框架EventSystem核心调度架构深度解析-TypeSystems分层队列与Publish和Invoke双通道机制设计
date: 2026-05-03
tags:
  - Unity
  - 游戏框架
  - ECS
  - EventSystem
  - 设计模式
categories:
  - xgame框架源码解析
description: 深度剖析xgame框架中EventSystem单例的完整实现，重点讲解TypeSystems/OneTypeSystems双层结构、InstanceQueueIndex分帧队列调度、Publish事件广播与Invoke精准调用的哲学差异，以及全生命周期（Awake/Start/Load/Update/Destroy）的驱动机制与工程最佳实践。
encryptedKey: henhaoji123
---

## 前言

在xgame框架的ECS体系中，`EventSystem` 是整个框架的神经中枢——它不仅管理所有 `Entity` 的生命周期钩子，还负责两套截然不同的消息分发机制：**Publish（事件广播）** 与 **Invoke（精准调用）**。理解这个类，就是理解整个框架的消息哲学。

本文将以 `EventSystem.cs` 源码为蓝本，逐层解剖其内部结构，帮助你真正掌握这套调度引擎的运作原理。

---

## 一、整体架构一览

```csharp
public class EventSystem : Singleton<EventSystem>, ISingletonUpdate, ISingletonLateUpdate, ISingletonFixedUpdate
```

`EventSystem` 本身是一个**单例**，同时实现了 `ISingletonUpdate` / `ISingletonLateUpdate` / `ISingletonFixedUpdate` 三个帧驱动接口，意味着它每帧都会被 `Game` 主循环驱动，集中处理所有注册实体的帧级逻辑。

其核心数据结构可以拆成四大模块：

| 模块 | 数据结构 | 职责 |
|------|---------|------|
| 实体注册表 | `Dictionary<long, Entity> allEntities` | InstanceId → Entity 快速查找 |
| 系统分发层 | `TypeSystems typeSystems` | Type → System列表，驱动生命周期 |
| 事件总线 | `Dictionary<Type, List<EventInfo>> allEvents` | 事件类型 → 订阅者列表 |
| 调用表 | `Dictionary<Type, Dictionary<int, object>> allInvokes` | 参数类型+Type → 处理器 |

---

## 二、TypeSystems 双层嵌套结构

### 2.1 OneTypeSystems

```csharp
private class OneTypeSystems
{
    public readonly UnOrderMultiMap<Type, object> Map = new();
    public readonly bool[] QueueFlag = new bool[(int)InstanceQueueIndex.Max];
}
```

`OneTypeSystems` 代表**某一个具体 Entity 类型**所拥有的全部 System 信息：

- `Map`：`UnOrderMultiMap<Type, object>`，键是系统接口类型（如 `IUpdateSystem`），值是实现该接口的系统对象列表
- `QueueFlag`：布尔数组，长度等于 `InstanceQueueIndex.Max`，预计算该类型的实体是否需要进入对应更新队列

这里有个巧妙的优化：**不用哈希查找，直接用 bool 数组做标志位**。因为 `InstanceQueueIndex` 枚举数量有限，数组下标访问远比字典快，且实体数量大时收益显著。

### 2.2 TypeSystems

```csharp
private class TypeSystems
{
    private readonly Dictionary<Type, OneTypeSystems> typeSystemsMap = new();
    ...
}
```

`TypeSystems` 是更上层的映射：**Entity 类型 → OneTypeSystems**。

当框架初始化或热重载时，`EventSystem.Add(addTypes)` 会遍历所有带 `ObjectSystemAttribute` 的类型，通过反射实例化后，按 `ISystemType.Type()` 分类存入对应的 `OneTypeSystems.Map`。

---

## 三、InstanceQueueIndex 分帧调度机制

```csharp
public enum InstanceQueueIndex
{
    None = -1,
    Start,
    Update,
    LateUpdate,
    Load,
    FixedUpdate,
    LateFixedUpdate,
    Physics,
    Reset,
    Max,
}
```

框架维护了一个与枚举等长的 **Queue 数组**：

```csharp
private readonly Queue<long>[] queues = new Queue<long>[(int)InstanceQueueIndex.Max];
```

每个队列存储的是 **InstanceId**（long），而非实体引用本身，这样即使实体被销毁也不会有悬空引用风险。

### 注册流程

当 `RegisterSystem(entity)` 被调用时：

```csharp
for (int i = 0; i < oneTypeSystems.QueueFlag.Length; ++i)
{
    if (!oneTypeSystems.QueueFlag[i]) continue;
    this.queues[i].Enqueue(component.InstanceId);
}
```

框架通过预计算的 `QueueFlag` 数组，快速决定该实体应入哪些队列，**零反射、零字典查找**，极致高效。

### 驱动流程（以 Update 为例）

```csharp
public void Update()
{
    Start();  // 先驱动 Start 队列（只执行一次）
    Queue<long> queue = this.queues[(int)InstanceQueueIndex.Update];
    int count = queue.Count;
    while (count-- > 0)
    {
        long instanceId = queue.Dequeue();
        if (!this.allEntities.TryGetValue(instanceId, out component)) continue;
        if (component.IsDisposed) continue;

        // 取出系统列表
        List<object> iUpdateSystems = this.typeSystems.GetSystems(component.GetType(), typeof(IUpdateSystem));
        queue.Enqueue(instanceId);  // 重新入队（下帧继续）

        foreach (IUpdateSystem iUpdateSystem in iUpdateSystems)
            iUpdateSystem.Run(component);
    }
}
```

关键设计点：
1. **快照 count**：用 `count = queue.Count` 冻结本帧处理数量，防止新注册的实体在本帧被意外驱动
2. **先出后入**：`Dequeue` 后 `Enqueue`，实现循环队列驱动
3. **已销毁跳过**：通过 `IsDisposed` 安全跳过已回收实体
4. `Start` 队列不重新入队，确保**只执行一次**

---

## 四、Publish 与 Invoke 的哲学差异

这是 EventSystem 中**最值得深思**的设计。源码注释写得非常直白：

```
// Invoke 类似函数，必须有被调用方，否则异常，调用者跟被调用者属于同一模块
// Publish 是事件，抛出去可以没人订阅，调用者跟被调用者属于两个模块
```

### 4.1 Publish —— 跨模块广播

```csharp
public void Publish<T>(Scene scene, T a)
{
    if (!this.allEvents.TryGetValue(typeof(T), out iEvents)) return; // 没人订阅就忽略
    
    foreach (EventInfo eventInfo in iEvents)
    {
        if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None) continue;
        
        if (eventInfo.IEvent is AEvent<T> aEvent)
            aEvent.Handle(scene, a);
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            aAsyncEvent.Handle(scene, a).Coroutine(); // 异步版本：即发即忘
    }
}
```

特点：
- **Scene 感知**：通过 `SceneType` 过滤，只有对应场景的订阅者才会收到
- **无人订阅不报错**：纯粹的广播语义
- **同步+异步两套**：`AEvent<T>` 同步执行，`AAsyncEvent<T>` 发起协程
- **ProfilingMarker 插桩**：带 `#if ONLY_CLIENT` 条件编译的性能采样

### 4.2 PublishAsync —— 等待所有订阅者

```csharp
public async ETTask PublishAsync<T>(Scene scene, T a)
{
    using ListComponent<ETTask> list = ListComponent<ETTask>.Create();
    foreach (EventInfo eventInfo in iEvents)
    {
        if (eventInfo.IEvent is AEvent<T> aEvent)
            aEvent.Handle(scene, a);
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            list.Add(aAsyncEvent.Handle(scene, a));
    }
    await ETTaskHelper.WaitAll(list); // 等待所有异步订阅者完成
}
```

`PublishAsync` 会收集所有异步处理器的 `ETTask`，然后用 `WaitAll` 并发等待全部完成。适合需要保证所有模块都处理完才能继续的场景（如场景卸载前的清理）。

### 4.3 Invoke —— 同模块精准调用

```csharp
public void Invoke<A>(int type, A args) where A : struct
{
    if (!this.allInvokes.TryGetValue(typeof(A), out var invokeHandlers))
        throw new Exception($"Invoke error: {typeof(A).Name}"); // 没有处理器就报错！
    
    if (!invokeHandlers.TryGetValue(type, out var invokeHandler))
        throw new Exception($"Invoke error: {typeof(A).Name} {type}");
    
    aInvokeHandler.Handle(args);
}
```

Invoke 的关键区别：
- **必须存在处理器**，否则抛异常（和函数调用语义一致）
- 通过 `int type` 区分同一参数类型下的不同处理器（类似 TimerComponent 的 Timer 分发）
- 参数类型必须是 `struct`，天然零 GC

典型用例：`TimerComponent` 内的计时器到期回调，Timer 模块知道自己注册了处理器，所以可以放心使用 Invoke。

---

## 五、生命周期完整链路

```
Add(addTypes)        ← 反射扫描，初始化 TypeSystems
    ↓
RegisterSystem()     ← 实体创建时注册，进入对应更新队列
    ↓
Awake()              ← 立即执行，不进队列
    ↓
[进入帧循环]
    Update()
      └─ Start()     ← 先执行 Start（一次性，不重入队）
      └─ Update 队列处理
    LateUpdate()
      └─ PhysicsLateUpdate()
      └─ LateUpdate 队列处理
    FixedUpdate()
      └─ Start()
      └─ FixedUpdate 队列处理
    ↓
Load()               ← 热重载时执行，会持续留在队列
    ↓
Destroy()            ← 销毁前执行（含 BeforeRun 两阶段）
    ↓
Remove()             ← 从 allEntities 移除
```

特别注意 `Destroy` 的两阶段设计：

```csharp
public void Destroy(Entity component)
{
    // 第一阶段：BeforeRun（所有 DestroySystem 的前置处理）
    foreach (IDestroySystem iDestroySystem in iDestroySystems)
        iDestroySystem.BeforeRun(component);
    
    // 第二阶段：Run（真正的销毁逻辑）
    foreach (IDestroySystem iDestroySystem in iDestroySystems)
        iDestroySystem.Run(component);
}
```

两阶段设计确保所有系统的 `BeforeRun` 都在任何 `Run` 之前完成，防止销毁顺序带来的依赖问题。

---

## 六、实体查找与诊断工具

`EventSystem` 还提供了一些实用的诊断接口：

### 孤儿实体检测

```csharp
public override string ToString()
{
    HashSet<Type> noParent = new();  // 没有 Parent 的实体
    HashSet<Type> noDomain = new();  // 没有 Domain 的实体
    
    foreach (var kv in this.allEntities)
    {
        if (kv.Value.Parent == null) noParent.Add(type);
        if (kv.Value.Domain == null) noDomain.Add(type);
        typeCount[type]++;
    }
    // 输出统计报告
}
```

在开发阶段可以定期调用 `EventSystem.Instance.ToString()` 来检查是否有实体忘记设置 Parent 或 Domain，这是排查内存泄漏的有效手段。

### 类型查找

```csharp
public ListComponent<Entity> FindEntitiesOfType<T>() where T : Entity
{
    var result = ListComponent<Entity>.Create();
    foreach (var entity in allEntities.Values)
    {
        if (entity is T) result.Add(entity);
    }
    return result; // 注意：使用后需释放
}
```

---

## 七、工程最佳实践

### 正确使用 Publish vs Invoke

```csharp
// ✅ 跨模块广播：任务系统订阅道具使用事件
EventSystem.Instance.Publish(scene, new ItemUsedEvent { ItemId = 1001 });

// ✅ 同模块精准调用：计时器内部分发
EventSystem.Instance.Invoke(TimerCoreCallbackId.MoveTimer, new MoveTimerArgs { ... });

// ❌ 滥用 Invoke 替代普通函数调用
// 能用函数的地方就用函数，不要为了"解耦"而滥用 Invoke
```

### 热重载场景

注意 `RegisterOneEvent2` 方法上的警告注释：
```
// This is bad, when EventSystem reloads, all event registered by this is dropped
```

通过该方法手动注册的事件，在 EventSystem 热重载后会丢失。生产代码应通过 `[EventAttribute]` 特性标注，走 `Add(addTypes)` 自动注册路径。

---

## 八、总结

`EventSystem` 是 xgame 框架中设计最精密的系统之一。它的核心设计哲学可以归纳为：

1. **分层索引**：TypeSystems → OneTypeSystems 双层结构，兼顾查找性能与内存布局
2. **预计算路由**：QueueFlag 布尔数组避免运行时判断，注册时一次性计算
3. **双通道消息**：Publish（广播，无处理器不报错）vs Invoke（精准，无处理器抛异常），职责泾渭分明
4. **Scene 感知**：事件分发携带 SceneType 过滤，天然支持多场景隔离
5. **诊断友好**：内置孤儿实体检测、类型统计等开发期工具

理解了 EventSystem，你就掌握了整个框架的消息流向和实体驱动机制的核心。
