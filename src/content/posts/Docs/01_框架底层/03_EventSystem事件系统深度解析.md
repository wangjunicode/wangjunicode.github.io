# 03 EventSystem 事件系统深度解析

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

`EventSystem` 是整个框架的**神经中枢**。它承担三大职责：

1. **System 调度**：统一分发 Awake、Update、LateUpdate、FixedUpdate、Destroy 等生命周期回调
2. **Publish/Subscribe 事件**：模块间解耦通信（如道具使用 → 任务系统）
3. **Invoke 调用**：类似函数调用，但支持根据 type 参数分发不同处理器

`EventSystem` 继承自 `Singleton<EventSystem>`，并实现了 `ISingletonUpdate`、`ISingletonLateUpdate`、`ISingletonFixedUpdate` 接口，由 `Game` 静态类在每帧驱动。

**源文件位置**：`X:\UnityProj\Assets\Scripts\Core\EventSystem\EventSystem.cs`

---

## 2. 架构设计

### 2.1 内部数据结构总览

```
EventSystem
├── allEntities: Dictionary<long, Entity>       ← InstanceId → Entity 全局注册表
├── allTypes: Dictionary<string, Type>          ← 全类型名 → Type 映射
├── types: UnOrderMultiMapSet<Type, Type>       ← Attribute类型 → 实现类集合
│
├── typeSystems: TypeSystems                    ← 生命周期分发核心
│    └── typeSystemsMap: Dictionary<Type, OneTypeSystems>
│         └── OneTypeSystems
│              ├── Map: UnOrderMultiMap<Type, object>  ← SystemType → System实例列表
│              └── QueueFlag: bool[]                   ← 是否加入更新队列的标志
│
├── queues: Queue<long>[]                       ← 按 InstanceQueueIndex 分类的更新队列
│    ├── [Start]
│    ├── [Update]
│    ├── [LateUpdate]
│    ├── [FixedUpdate]
│    └── [LateFixedUpdate] ...
│
├── allEvents: Dictionary<Type, List<EventInfo>> ← 事件类型 → 处理器列表
└── allInvokes: Dictionary<Type, Dictionary<int, object>> ← Invoke 分发表
```

### 2.2 TypeSystems 的嵌套设计

```
TypeSystems
  typeSystemsMap[PlayerEntity]
    ↓
  OneTypeSystems
    Map[IAwakeSystem]   → [PlayerEntityAwakeSystem实例]
    Map[IUpdateSystem]  → [PlayerEntityMoveSystem实例, PlayerEntityAnimSystem实例]
    Map[IDestroySystem] → [PlayerEntityDestroySystem实例]
    QueueFlag[Update]   = true   ← 说明此类型有 UpdateSystem，注册时入队
    QueueFlag[LateUpdate] = false
```

这种两级查找（Entity类型 → System类型 → System实例列表）的设计，查找复杂度为 O(1) + O(n_systems)，其中 n_systems 通常极小。

### 2.3 三种通信机制对比

| 机制 | 适用场景 | 是否有返回值 | 必须有接收方 |
|---|---|---|---|
| **System 生命周期** | Awake/Update/Destroy等帧驱动 | 否 | 否（无 System 则跳过） |
| **Publish/Subscribe** | 跨模块事件（道具→任务、击杀→成就） | 否 | 否（无订阅者则静默） |
| **Invoke** | 类函数调用，需要区分 type 分发 | 支持 | **是**（无处理器则异常） |

---

## 3. 核心代码展示

### 3.1 Add() —— 反射扫描注册

```csharp
// EventSystem.cs - Add()

public void Add(Dictionary<string, Type> addTypes)
{
    this.allTypes.Clear();
    this.types.Clear();

    // 第一步：建立 "Attribute类型 → 实现类" 映射
    foreach ((string fullName, Type type) in addTypes)
    {
        this.allTypes[fullName] = type;
        if (type.IsAbstract) continue;

        object[] objects = type.GetCustomAttributes(typeof(BaseAttribute), true);
        foreach (object o in objects)
            this.types.Add(o.GetType(), type);  // 如 [ObjectSystem] → AwakeSystem<T> 的类
    }

    // 第二步：注册所有 System（带 [ObjectSystem] 特性的类）
    this.typeSystems = new TypeSystems();
    foreach (Type type in this.GetTypes(typeof(ObjectSystemAttribute)))
    {
        object obj = Activator.CreateInstance(type);
        if (obj is ISystemType iSystemType)
        {
            OneTypeSystems oneTypeSystems =
                this.typeSystems.GetOrCreateOneTypeSystems(iSystemType.Type());
            oneTypeSystems.Map.Add(iSystemType.SystemType(), obj);

            // 设置更新队列标志（如 UpdateSystem → QueueFlag[Update] = true）
            InstanceQueueIndex index = iSystemType.GetInstanceQueueIndex();
            if (index > InstanceQueueIndex.None && index < InstanceQueueIndex.Max)
                oneTypeSystems.QueueFlag[(int)index] = true;
        }
    }

    // 第三步：注册 Publish/Subscribe 事件
    this.allEvents.Clear();
    foreach (var type in types[typeof(EventAttribute)])
    {
        IEvent obj = Activator.CreateInstance(type) as IEvent;
        object[] attrs = type.GetCustomAttributes(typeof(EventAttribute), false);
        foreach (object attr in attrs)
        {
            EventAttribute eventAttribute = attr as EventAttribute;
            Type eventType = obj.Type;
            EventInfo eventInfo = new(obj, eventAttribute.SceneType);
            if (!this.allEvents.ContainsKey(eventType))
                this.allEvents.Add(eventType, new List<EventInfo>());
            this.allEvents[eventType].Add(eventInfo);
        }
    }

    // 第四步：注册 Invoke 处理器
    this.allInvokes = new Dictionary<Type, Dictionary<int, object>>();
    foreach (var type in types[typeof(InvokeAttribute)])
    {
        object obj = Activator.CreateInstance(type);
        IInvoke iInvoke = obj as IInvoke;
        object[] attrs = type.GetCustomAttributes(typeof(InvokeAttribute), false);
        foreach (object attr in attrs)
        {
            if (!this.allInvokes.TryGetValue(iInvoke.Type, out var dict))
            {
                dict = new Dictionary<int, object>();
                this.allInvokes.Add(iInvoke.Type, dict);
            }
            InvokeAttribute invokeAttribute = attr as InvokeAttribute;
            dict.Add(invokeAttribute.Type, obj);
        }
    }
}
```

### 3.2 RegisterSystem() —— Entity 注册进更新队列

```csharp
public void RegisterSystem(Entity component, bool isRegister = true)
{
    if (!isRegister)
    {
        this.Remove(component.InstanceId);
        return;
    }

    this.allEntities.Add(component.InstanceId, component);

    Type type = component.GetType();
    OneTypeSystems oneTypeSystems = this.typeSystems.GetOneTypeSystems(type);
    if (oneTypeSystems == null) return;  // 该类型没有任何 System，不入队

    // 根据 QueueFlag 决定加入哪些更新队列
    for (int i = 0; i < oneTypeSystems.QueueFlag.Length; ++i)
    {
        if (!oneTypeSystems.QueueFlag[i]) continue;
        this.queues[i].Enqueue(component.InstanceId);
    }
}
```

### 3.3 Publish/Subscribe 事件发布（同步版）

```csharp
public void Publish<T>(Scene scene, T a)
{
    if (scene == null) return;

    List<EventInfo> iEvents;
    if (!this.allEvents.TryGetValue(typeof(T), out iEvents)) return;

    SceneType sceneType = scene.SceneType;
    foreach (EventInfo eventInfo in iEvents)
    {
        // SceneType 过滤：只响应同场景类型或 SceneType.None（全局）的订阅者
        if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
            continue;

        if (eventInfo.IEvent is AEvent<T> aEvent)
        {
            try { aEvent.Handle(scene, a); }
            catch (Exception e) { Log.Error(e); }
        }
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
        {
            // 异步事件：fire-and-forget 模式
            aAsyncEvent.Handle(scene, a).Coroutine();
        }
    }
}
```

### 3.4 Publish/Subscribe 事件发布（异步版）

```csharp
public async ETTask PublishAsync<T>(Scene scene, T a) where T : struct
{
    if (scene == null) return;

    List<EventInfo> iEvents;
    if (!this.allEvents.TryGetValue(typeof(T), out iEvents)) return;

    // 收集所有异步处理器的 Task，统一 WaitAll
    using ListComponent<ETTask> list = ListComponent<ETTask>.Create();

    foreach (EventInfo eventInfo in iEvents)
    {
        if (scene.SceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
            continue;

        if (eventInfo.IEvent is AEvent<T> aEvent)
            aEvent.Handle(scene, a);              // 同步直接执行
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            list.Add(aAsyncEvent.Handle(scene, a)); // 异步收集
    }

    try
    {
        await ETTaskHelper.WaitAll(list);  // 等待所有异步处理器完成
    }
    catch (Exception e) { Log.Error(e); }
}
```

### 3.5 Invoke 分发调用

```csharp
// 无返回值版本
public void Invoke<A>(int type, A args) where A : struct
{
    if (!this.allInvokes.TryGetValue(typeof(A), out var invokeHandlers))
        throw new Exception($"Invoke error: {typeof(A).Name}");    // 必须有处理器！

    if (!invokeHandlers.TryGetValue(type, out var invokeHandler))
        throw new Exception($"Invoke error: {typeof(A).Name} {type}");

    var aInvokeHandler = invokeHandler as AInvokeHandler<A>;
    if (aInvokeHandler == null)
        throw new Exception($"Invoke error, not AInvokeHandler: {typeof(A).Name} {type}");

    aInvokeHandler.Handle(args);
}

// 有返回值版本（如果找不到返回 default，不抛异常）
public T Invoke<A, T>(int type, A args) where A : struct
{
    if (!this.allInvokes.TryGetValue(typeof(A), out var invokeHandlers)) return default;
    if (!invokeHandlers.TryGetValue(type, out var invokeHandler)) return default;
    var aInvokeHandler = invokeHandler as AInvokeHandler<A, T>;
    if (aInvokeHandler == null) return default;
    return aInvokeHandler.Handle(args);
}
```

### 3.6 Destroy 的两阶段回调

```csharp
public void Destroy(Entity component)
{
    List<object> iDestroySystems = this.typeSystems.GetSystems(
        component.GetType(), typeof(IDestroySystem));
    if (iDestroySystems == null) return;

    // 第一阶段：BeforeRun（可在此做资源预清理、解除绑定等）
    foreach (IDestroySystem iDestroySystem in iDestroySystems)
    {
        try { iDestroySystem.BeforeRun(component); }
        catch (Exception e) { Log.Error(e); }
    }

    // 第二阶段：Run（正式销毁逻辑）
    foreach (IDestroySystem iDestroySystem in iDestroySystems)
    {
        try { iDestroySystem.Run(component); }
        catch (Exception e) { Log.Error(e); }
    }
}
```

---

## 4. 生命周期系统接口全览

| 接口 | 对应 System 基类 | 触发时机 | 队列索引 |
|---|---|---|---|
| `IAwake` | `AwakeSystem<T>` | AddComponent/AddChild 时立即 | 无队列（立即执行） |
| `IStart` | `StartSystem<T>` | 下一帧 Update 之前 | Start |
| `IUpdate` | `UpdateSystem<T>` | 每帧 Update | Update |
| `ILateUpdate` | `LateUpdateSystem<T>` | 每帧 LateUpdate | LateUpdate |
| `IFixedUpdate` | `FixedUpdateSystem<T>` | 每物理帧 | FixedUpdate |
| `IDestroy` | `DestroySystem<T>` | Dispose 时 | 无队列（即时） |
| `IDeserialize` | `DeserializeSystem<T>` | Domain 首次设置时 | 无队列（即时） |
| `ILoad` | `LoadSystem<T>` | 热重载时 | Load |
| `IReset` | `ResetSystem<T>` | 手动调用 Reset | Reset |

### 生命周期完整示意

```
AddComponent<T>()
    ↓ 立即
AwakeSystem.Awake()
    ↓ 下一帧 Update 之前
StartSystem.Start()   [只执行一次]
    ↓ 每帧
UpdateSystem.Update()
LateUpdateSystem.LateUpdate()
    ↓ 每物理帧
FixedUpdateSystem.FixedUpdate()
    ↓ 调用 Dispose()
DestroySystem.BeforeDestroy()
DestroySystem.Destroy()
```

---

## 5. 如何正确使用 Publish vs Invoke

框架源码注释中对此有明确说明，这里做更详细的解读：

### Publish（事件发布）—— 模块间解耦

```
适用场景：
  - 调用方不关心谁在处理
  - 可以没有任何订阅者（事件丢失是可接受的）
  - 调用方和处理方属于不同业务模块

示例：
  道具系统发布 ItemUsedEvent → 任务系统订阅并检查任务进度
  玩家击杀怪物发布 KillEvent  → 成就系统订阅并解锁成就
```

```csharp
// 定义事件结构体
public struct ItemUsedEvent
{
    public int ItemId;
    public int Count;
}

// 发布
EventSystem.Instance.Publish(scene, new ItemUsedEvent { ItemId = 101, Count = 1 });

// 订阅（在任务模块的某个类中）
[Event(SceneType.Client)]
public class ItemUsedEventHandler : AEvent<ItemUsedEvent>
{
    protected override void Run(Scene scene, ItemUsedEvent evt)
    {
        // 检查任务进度
    }
}
```

### Invoke（函数式调用）—— 同模块内的策略分发

```
适用场景：
  - 调用方明确需要一个处理器响应
  - 没有处理器是错误状态（会抛异常）
  - 调用方和处理方属于同一业务模块

示例：
  TimerComponent 根据 TimerType 分发不同的定时器回调
  Config 加载器根据平台类型分发加载策略
```

---

## 6. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| FixedUpdate 支持 | 无 | 新增 FixedUpdate / LateFixedUpdate / Physics 三个队列 |
| Destroy 阶段 | 单阶段 `Run` | 两阶段 `BeforeRun` + `Run` |
| Publish 作用域 | 无 SceneType 过滤 | 支持 SceneType 过滤，精确投递到目标场景 |
| PublishAsync | 支持 | 支持，并使用 `WaitAll` 等待所有异步处理器 |
| Reset 系统 | 无 | 新增 `ResetSystem`，支持对象池回收时重置状态 |
| `RegisterOneEvent` | 无 | 新增，支持运行时手动注册单个事件处理器 |
| `FindEntitiesOfType<T>()` | 无 | 新增，遍历所有已注册 Entity 找指定类型 |
| 性能分析标记 | 无 | 新增 `VProfiler` / `ProfilingMarker` 集成 |

---

## 7. 常见问题与最佳实践

### Q1：我的 UpdateSystem 没被调用，为什么？

检查以下几点：
1. Entity 类是否实现了 `IUpdate` 接口（空接口，作为标记）？
2. System 类是否标记了 `[ObjectSystem]` 特性？
3. Entity 是否已经加入到 ECS 树（有 Domain）？

```csharp
// ✅ 正确写法
public class MyEntity : Entity, IAwake, IUpdate { }

[ObjectSystem]
public class MyEntityUpdateSystem : UpdateSystem<MyEntity>
{
    protected override void Update(MyEntity self) { /* ... */ }
}
```

### Q2：Publish 和 PublishAsync 如何选择？

- 如果所有处理器都是同步的 → 用 `Publish`
- 如果有处理器需要 `await` → 用 `PublishAsync`，但调用方也要 `await`
- 如果调用方不需要等待异步处理完成 → 用 `Publish`，异步处理器会自动 `fire-and-forget`

### Q3：为什么 Update 循环中要先记录 `count = queue.Count`？

```csharp
int count = queue.Count;  // 快照当前数量
while (count-- > 0)
{
    // 本帧新注册的 Entity 不会被处理（它们在循环结束后才进入队列）
}
```

这是防止"注册时序"Bug 的关键：如果在 Update 中新增了 Entity，它会被加入队列末尾，但本帧的 `count` 快照不包含它，下帧才开始 Update。

### Q4：如何订阅只在特定 Scene 类型触发的事件？

```csharp
// 只在 Client Scene 中响应
[Event(SceneType.Client)]
public class MyHandler : AEvent<MyEvent> { ... }

// 在所有 Scene 类型中响应（全局事件）
[Event(SceneType.None)]
public class MyGlobalHandler : AEvent<MyEvent> { ... }
```

---

## 8. 总结

EventSystem 的三层设计（System调度 + Publish/Subscribe + Invoke）覆盖了游戏开发中绝大多数的通信需求：

- **帧驱动**用 System 生命周期，高效且统一
- **跨模块解耦**用 Publish，零依赖投递
- **同模块策略分发**用 Invoke，类型安全的函数调用

理解了这三套机制，你就能读懂项目中任何模块的通信方式。
