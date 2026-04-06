---
title: 事件系统深度解析——EventSystem 的核心调度机制全景
published: 2026-03-31
description: 从架构高度全面剖析 EventSystem 单例的内部数据结构、系统注册机制、多种调度方式的实现细节，以及 Invoke 与 Publish 的精妙区别和性能优化设计。
tags: [Unity, ECS, 事件系统, 架构设计, 性能优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 事件系统深度解析——EventSystem 的核心调度机制全景

## 前言

经过前面多篇文章的铺垫，我们已经了解了 ECS 框架中的各种接口和特性。今天，我们来看这一切背后的"发动机"——`EventSystem`。

这是整个 ECS 框架最复杂也最核心的类，负责：
- 系统类的扫描和注册
- 实体的全局追踪
- 多种生命周期的调度
- 事件的发布与分发
- 精准的 Invoke 调用

---

## 一、EventSystem 的数据结构全览

```csharp
public class EventSystem : Singleton<EventSystem>, ISingletonUpdate, ISingletonLateUpdate, ISingletonFixedUpdate
{
    private readonly Dictionary<long, Entity> allEntities = new();       // 全局实体注册表
    private readonly Dictionary<string, Type> allTypes = new();          // 类型名称映射
    private readonly UnOrderMultiMapSet<Type, Type> types = new();       // 特性类型索引
    private readonly Dictionary<Type, List<EventInfo>> allEvents = new(); // 事件处理器注册
    private Dictionary<Type, Dictionary<int, object>> allInvokes = new(); // Invoke处理器注册
    private TypeSystems typeSystems = new();                              // 系统方法映射
    private readonly Queue<long>[] queues = new Queue<long>[(int)InstanceQueueIndex.Max]; // 更新队列
}
```

七个核心数据结构，每个都有其专属职责。

### 1.1 allEntities——全局实体注册表

```csharp
private readonly Dictionary<long, Entity> allEntities = new();
```

以 `InstanceId` 为键，存储所有活跃的实体。

**作用**：
1. 通过 `InstanceId` 快速查找实体（`EventSystem.Get(instanceId)`）
2. 在更新队列处理时，验证实体是否还存活
3. 调试时可以枚举所有实体（`ToString()` 方法）

### 1.2 TypeSystems——系统方法的两级索引

```csharp
private class TypeSystems
{
    private readonly Dictionary<Type, OneTypeSystems> typeSystemsMap = new();
}

private class OneTypeSystems
{
    public readonly UnOrderMultiMap<Type, object> Map = new();   // 实体类型 → 系统实例
    public readonly bool[] QueueFlag = new bool[(int)InstanceQueueIndex.Max]; // 队列标记
}
```

两级结构：
- 第一级：`实体类型` → `OneTypeSystems`
- 第二级：`系统接口类型` → `系统实例列表`

查询复杂度：两次 Dictionary 查找，O(1)。

### 1.3 allEvents 和 allInvokes

```csharp
// 事件：类型 → 处理器列表（一对多）
private readonly Dictionary<Type, List<EventInfo>> allEvents = new();

// Invoke：类型 → (intId → 处理器)（一对一）
private Dictionary<Type, Dictionary<int, object>> allInvokes = new();
```

两者的数据结构差异反映了语义差异：
- **事件**：一个事件类型对应多个处理器（广播）
- **Invoke**：一个消息类型+ID 对应唯一一个处理器（精准调用）

---

## 二、Add 方法——框架启动时的核心初始化

```csharp
public void Add(Dictionary<string, Type> addTypes)
{
    // 1. 重建类型字典
    this.allTypes.Clear();
    this.types.Clear();
    foreach ((string fullName, Type type) in addTypes)
    {
        this.allTypes[fullName] = type;
        if (type.IsAbstract) continue;
        
        // 按 BaseAttribute 类型分组
        object[] objects = type.GetCustomAttributes(typeof(BaseAttribute), true);
        foreach (object o in objects)
        {
            this.types.Add(o.GetType(), type);
        }
    }

    // 2. 扫描并注册所有 [ObjectSystem] 系统
    this.typeSystems = new TypeSystems();
    foreach (Type type in this.GetTypes(typeof(ObjectSystemAttribute)))
    {
        object obj = Activator.CreateInstance(type);
        if (obj is ISystemType iSystemType)
        {
            OneTypeSystems oneTypeSystems = 
                this.typeSystems.GetOrCreateOneTypeSystems(iSystemType.Type());
            oneTypeSystems.Map.Add(iSystemType.SystemType(), obj);
            
            InstanceQueueIndex index = iSystemType.GetInstanceQueueIndex();
            if (index > InstanceQueueIndex.None && index < InstanceQueueIndex.Max)
            {
                oneTypeSystems.QueueFlag[(int)index] = true;
            }
        }
    }

    // 3. 扫描并注册所有 [Event] 事件处理器
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

    // 4. 扫描并注册所有 [Invoke] 处理器
    this.allInvokes = new Dictionary<Type, Dictionary<int, object>>();
    foreach (var type in types[typeof(InvokeAttribute)])
    {
        // ... 类似事件注册
    }
}
```

`Add` 方法是**框架的启动和热更新入口**：
- 程序启动时调用一次，完成初始化
- 热更新后再次调用，用新的类型替换旧的注册信息（因此所有字典都先 `Clear()`）

### 2.1 为什么 allEntities 不在 Add 中清理？

```csharp
this.allTypes.Clear();   // 清理
this.types.Clear();      // 清理
this.typeSystems = new TypeSystems(); // 重建
this.allEvents.Clear();  // 清理
// allEntities 没有清理！
```

`allEntities` 不清理，因为它存储的是**运行时的实体实例**，热更新替换的是"逻辑代码"，不是"数据"。热更新后，现有的实体对象仍然存活，它们的数据没有变。

---

## 三、RegisterSystem——实体的生命周期注册

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
    if (oneTypeSystems == null) return;

    for (int i = 0; i < oneTypeSystems.QueueFlag.Length; ++i)
    {
        if (!oneTypeSystems.QueueFlag[i]) continue;
        this.queues[i].Enqueue(component.InstanceId);
    }
}
```

实体注册时：
1. 加入全局实体表
2. 根据 `QueueFlag` 加入相应的更新队列

注意：`isRegister = false` 时只是从 `allEntities` 移除，不从队列移除——队列会在下次更新时通过 `IsDisposed` 检查自然过滤。

---

## 四、帧更新调度——高效处理大量实体

```csharp
public void Update()
{
    Start(); // 先处理待 Start 的实体
    Queue<long> queue = this.queues[(int)InstanceQueueIndex.Update];
    int count = queue.Count;
    while (count-- > 0)
    {
        long instanceId = queue.Dequeue();
        
        if (!this.allEntities.TryGetValue(instanceId, out Entity component))
            continue; // 实体已被销毁
        
        if (component.IsDisposed)
            continue; // 实体已经 Dispose
        
        List<object> iUpdateSystems = 
            this.typeSystems.GetSystems(component.GetType(), typeof(IUpdateSystem));
        if (iUpdateSystems == null) continue;
        
        queue.Enqueue(instanceId); // 重新入队，下帧继续
        
        foreach (IUpdateSystem iUpdateSystem in iUpdateSystems)
        {
            try { iUpdateSystem.Run(component); }
            catch (Exception e) { Log.Error(e); }
        }
    }
}
```

**精妙的 count 先锁定设计**：

```csharp
int count = queue.Count; // 先锁定本帧需要处理的数量
while (count-- > 0)
```

这确保本帧只处理"开始时"队列中的实体，新加入的实体（本帧新创建）留到下帧处理。

**try-catch 异常隔离**：

单个实体的 Update 出错不影响其他实体。这在游戏中非常重要——一个实体的 Bug 不应该导致整个游戏崩溃。

---

## 五、Destroy 的两阶段处理

```csharp
public void Destroy(Entity component)
{
    List<object> iDestroySystems = 
        this.typeSystems.GetSystems(component.GetType(), typeof(IDestroySystem));
    
    // 第一阶段：所有 BeforeDestroy
    foreach (IDestroySystem iDestroySystem in iDestroySystems)
    {
        iDestroySystem.BeforeRun(component);
    }
    
    // 第二阶段：所有 Destroy
    foreach (IDestroySystem iDestroySystem in iDestroySystems)
    {
        iDestroySystem.Run(component);
    }
}
```

两轮遍历的价值：所有组件的 `BeforeDestroy` 都完成后，再进行 `Destroy`。

**为什么这样顺序更安全？**

假设一个实体有两个系统 A 和 B：
- A 的 `Destroy` 需要访问 B 的状态
- B 的 `Destroy` 需要访问 A 的状态

如果交叉调用 `BeforeDestroy` + `Destroy`（A-before, A-destroy, B-before, B-destroy），当 B-before 时，A 已经 destroy 了，B 访问 A 会出错。

分两轮就没有这个问题：所有 before 都完成（数据还在），再统一 destroy（清理数据）。

---

## 六、Publish 与 PublishAsync 的实现

```csharp
public void Publish<T>(Scene scene, T a)
{
    VProfiler.BeginDeepSample("EventSystem.Publish"); // 性能采样
    
    List<EventInfo> iEvents;
    if (!this.allEvents.TryGetValue(typeof(T), out iEvents)) return;

    SceneType sceneType = scene.SceneType;
    foreach (EventInfo eventInfo in iEvents)
    {
        if (sceneType != eventInfo.SceneType && eventInfo.SceneType != SceneType.None)
            continue; // 场景类型过滤
        
        if (eventInfo.IEvent is AEvent<T> aEvent)
            aEvent.Handle(scene, a);
        else if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            aAsyncEvent.Handle(scene, a).Coroutine(); // 异步事件，不等待结果
    }
    
    VProfiler.EndDeepSample();
}
```

**`aAsyncEvent.Handle(scene, a).Coroutine()`** ——异步事件在同步上下文中的"开火忘记"处理：
- `Handle` 返回 `ETTask`
- `.Coroutine()` 启动协程但不等待——让异步事件在后台运行
- 如果需要等待所有异步事件完成，使用 `PublishAsync`

```csharp
public async ETTask PublishAsync<T>(Scene scene, T a)
{
    // ... 收集所有异步任务
    using ListComponent<ETTask> list = ListComponent<ETTask>.Create();
    foreach (EventInfo eventInfo in iEvents)
    {
        if (eventInfo.IEvent is AAsyncEvent<T> aAsyncEvent)
            list.Add(aAsyncEvent.Handle(scene, a)); // 添加到等待列表
    }
    
    await ETTaskHelper.WaitAll(list); // 等待所有异步事件完成
}
```

---

## 七、ToString 方法——运行时诊断工具

```csharp
public override string ToString()
{
    StringBuilder sb = new();
    HashSet<Type> noParent = new HashSet<Type>();
    HashSet<Type> noDomain = new HashSet<Type>();
    Dictionary<Type, int> typeCount = new Dictionary<Type, int>();

    foreach (var kv in this.allEntities)
    {
        Type type = kv.Value.GetType();
        if (kv.Value.Parent == null) noParent.Add(type);
        if (kv.Value.Domain == null) noDomain.Add(type);
        if (typeCount.ContainsKey(type)) typeCount[type]++;
        else typeCount[type] = 1;
    }

    // 打印没有父节点的实体类型（可能是泄漏）
    sb.AppendLine("not set parent type: ");
    foreach (Type type in noParent)
        sb.AppendLine($"\t{type.Name}");
    
    // 打印实体数量（按数量降序）
    var ordered = typeCount.OrderByDescending(s => s.Value);
    sb.AppendLine("Entity Count: ");
    foreach (var kv in ordered)
    {
        if (kv.Value == 1) continue;
        sb.AppendLine($"\t{kv.Key.Name}: {kv.Value}");
    }

    return sb.ToString();
}
```

这个方法可以：
1. 发现没有父节点的实体（可能是内存泄漏）
2. 发现没有 Domain 的实体（可能是创建流程有误）
3. 查看各类型实体的数量（用于检测实体过多的类型）

在游戏开发中，一键打印这份报告，可以快速发现内存泄漏和配置错误。

---

## 八、EventSystem 的架构价值

`EventSystem` 是整个 ECS 框架的核心，它实现了：

| 功能 | 机制 |
|---|---|
| 自动系统注册 | 启动时扫描 [ObjectSystem] 标记的类 |
| 全局实体追踪 | allEntities 字典 |
| 生命周期驱动 | Awake/Start/Update/LateUpdate/Destroy... |
| 事件广播 | Publish → 所有匹配的 AEvent 处理器 |
| 精准调用 | Invoke → 唯一的 AInvokeHandler |
| 场景感知 | SceneType 过滤 |
| 异步支持 | AAsyncEvent + ETTask |
| 热更新支持 | Add() 可以在运行时重新注册所有系统 |

这是一个精心设计的系统，每个部分都有其存在的理由。

---

## 写给初学者

`EventSystem` 是一个值得反复研读的代码。它展示了工业级框架如何：

1. **用元数据（特性+接口）驱动行为**：框架不硬编码业务逻辑
2. **平衡性能与可维护性**：bool数组代替哈希，try-catch异常隔离
3. **支持热更新**：Add() 可以完整替换所有注册信息
4. **提供诊断工具**：ToString() 可以快速定位问题

读懂 `EventSystem`，你对 ECS 框架的理解就达到了一个新的高度。
