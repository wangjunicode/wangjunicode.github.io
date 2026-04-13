---
title: ECS对象池架构设计与双层Pool体系的分层职责解析
published: 2026-04-11
description: 深度剖析游戏框架中对象池的双层架构设计：Core/Pool 通用对象池与 ECS/ObjectPool 实体感知对象池的职责边界、实现差异、协作机制与工程取舍。
tags: [Unity, ECS, 对象池, 设计模式, 内存管理]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

# ECS 对象池架构设计与双层 Pool 体系的分层职责解析

对象池是游戏开发中最核心的性能优化手段之一。在精心设计的游戏框架里，对象池并非单一的实现，而是形成了一套有层次的体系结构。本文深入剖析框架中"双层对象池"的设计动机、实现细节与分工边界，帮助读者从架构层面理解对象复用的工程艺术。

---

## 一、为什么需要双层对象池

### 1.1 对象的两种生命周期语义

在游戏框架中存在两类本质不同的对象：

**POCO 类对象**（如 ETTask、StateMachineWrap、CoroutineLockItem 等）
- 没有 ECS 生命周期回调
- 使用 `Get/Return` 即可

**ECS 实体/组件对象**（Entity/Component，如 BattleComponent、Scene、Unit 等）
- 有 `InstanceId`、`Parent`、`Children` 等 ECS 状态
- Fetch 时需要触发 `Awake` 系统
- Recycle 时需要触发 `Destroy` 系统，并从 Scene 中注销

用同一套对象池处理这两类对象，要么过度封装，要么职责混乱。因此框架拆分为两层：

| 层次 | 适用对象 | 特点 |
|------|----------|------|
| `Core/Pool`（通用层） | ETTask、StateMachineWrap 等 POCO | 轻量、无 ECS 感知 |
| `ECS/ObjectPool`（实体层） | Entity、Component 及其容器 | ECS 感知，绑定 Awake/Destroy |

---

## 二、Core/Pool —— 通用对象池

### 2.1 设计结构

```csharp
namespace Core.Pool
{
    public class ObjectPool
    {
        // key = Type，value = Queue<object>，按类型分桶存储
        private static readonly Dictionary<Type, Queue<object>> pools
            = new Dictionary<Type, Queue<object>>();

        // 防止单个类型的池无限膨胀
        private const int MaxPoolSize = 1000;
    }
}
```

### 2.2 Get / Return 核心逻辑

```csharp
public static T Fetch<T>() where T : class, new()
{
    if (!pools.TryGetValue(typeof(T), out Queue<object> queue) || queue.Count == 0)
        return new T();
    return (T)queue.Dequeue();
}

public static void Recycle<T>(T obj) where T : class
{
    if (obj == null) return;
    if (!pools.TryGetValue(typeof(T), out Queue<object> queue))
    {
        queue = new Queue<object>();
        pools[typeof(T)] = queue;
    }
    if (queue.Count < MaxPoolSize)
        queue.Enqueue(obj);
    // 超出上限则直接丢弃，让 GC 回收
}
```

**设计要点：**
- **无回调**：取出/放回时不执行任何重置，调用方负责清理
- **容量上限**：设置 1000 防止内存无限增长
- **线程安全**：主线程单线程使用，无需加锁
- **泛型强类型**：编译期保证类型安全，避免装箱

### 2.3 典型使用场景

```csharp
// ETTask 对象池（框架内部使用）
public class ETTask
{
    private static readonly Queue<ETTask> pool = new Queue<ETTask>();

    public static ETTask Fetch()
    {
        if (pool.Count == 0)
            return new ETTask();
        ETTask task = pool.Dequeue();
        task.Reset();
        return task;
    }

    public void Return()
    {
        if (pool.Count < 1000)
            pool.Enqueue(this);
    }
}
```

ETTask 使用专属队列而非共享池，是因为它的复用频率极高，专属队列减少了字典查找开销。

---

## 三、ECS/ObjectPool —— 实体感知对象池

### 3.1 为何需要绑定 Entity 概念

```csharp
namespace Core.ECS
{
    /// <summary>
    /// ECS 实体/组件对象池，以 Scene 为作用域，管理 Scene 内部的实体复用
    /// </summary>
    public static class ObjectPool
    {
        // 以 Scene 为 Key，隔离不同场景的对象池
        private static readonly Dictionary<Scene, Dictionary<Type, Queue<Entity>>>
            scenePools = new Dictionary<Scene, Dictionary<Type, Queue<Entity>>>();
    }
}
```

**为什么以 Scene 为 Key？**

ECS 中每个 Entity 归属一个 Scene，`InstanceId` 由 Scene 分配，组件的 `Awake/Destroy` 也与 Scene 上下文绑定。如果跨 Scene 复用 Entity，会导致：
- `InstanceId` 冲突
- Scene 管理的 `components`/`id` 字段错乱
- Destroy 事件发给错误的 Scene

因此对象池必须以 Scene 为隔离单位。

### 3.2 Fetch 时触发 Awake 系统

```csharp
public static T Fetch<T>(Scene scene) where T : Entity, new()
{
    T entity;
    if (TryDequeue(scene, typeof(T), out Entity cached))
    {
        entity = (T)cached;
        entity.IsFromPool = true;
    }
    else
    {
        entity = new T();
        entity.IsFromPool = true;
    }

    // 1. 分配新的 InstanceId，绑定到 Scene
    entity.InstanceId = scene.GenId();
    scene.AddEntity(entity);

    // 2. 触发所有注册的 Awake 系统
    EntitySystemSingleton.Instance.Awake(entity);
    return entity;
}
```

**与 Core/Pool 的关键区别：**
1. 分配 `InstanceId`，注册到 Scene 的实体表
2. 触发 `Awake` 系统，初始化业务状态
3. 以 `Scene` 为作用域，不跨 Scene 共享对象

### 3.3 Recycle 时触发 Destroy 系统

```csharp
public static void Recycle(Entity entity)
{
    Scene scene = entity.Scene;

    // 1. 触发 Destroy 系统，执行业务清理逻辑
    EntitySystemSingleton.Instance.Destroy(entity);

    // 2. 从 Scene 的实体注册表中移除
    scene.RemoveEntity(entity.InstanceId);

    // 3. 重置 ECS 专有状态
    entity.InstanceId = 0;
    entity.Parent = null;
    entity.ComponentDict?.Clear();
    entity.Children?.Clear();

    // 4. 放入对应 Scene 的池中
    Enqueue(scene, entity.GetType(), entity);
}
```

**安全保证：**
- 先 `Destroy` 再清状态，防止 Destroy 回调访问已清零的字段
- 清零 `InstanceId` 后，`EntityRef<T>` 的有效性检查会自动失效
- 清空 `Components` 防止旧数据污染下一次 Awake

---

## 四、两层对象池的协作关系

```
┌────────────────────────────────────────────────────────────────┐
│ 对象类型            │ 使用哪层对象池         │ 关键操作              │
├────────────────────┼──────────────────────┼─────────────────────┤
│ ETTask / Coroutine │ Core/Pool（各自专属队列）│ Reset() → Return()   │
│ LockItem           │ Core/Pool             │ Get/Return           │
│ BattleComponent /  │ ECS/ObjectPool        │ Fetch → Awake 触发   │
│ Scene 等 ECS 对象   │                       │ Recycle → Destroy 触发│
│                    │ ECS/ObjectPool        │                      │
│ StateMachineWrap 等 │ 不经过 ECS           │ 直接 Core/Pool       │
│ Awaiter            │ StateMachineWrap →   │ Core/Pool            │
│                    │ Core/Pool            │                      │
└────────────────────┴──────────────────────┴─────────────────────┘
```

ECS 对象池在内部也会调用 Core/Pool 来管理 `Dictionary<long, Entity>`（children）等容器字段，形成嵌套使用模式。ECS 层负责生命周期语义，Core 层负责原始内存复用。

---

## 五、IsFromPool 标志位的工程价值

```csharp
public class Entity
{
    public bool IsFromPool { get; set; }
}
```

框架在 Entity.Dispose 时用这个标志决定回收策略：

```csharp
// Destroy 回调内
protected virtual void Dispose()
{
    if (IsFromPool)
    {
        // 走对象池回收，重置状态后放回队列
        ObjectPool.Recycle(this);
    }
    else
    {
        // 不走对象池，直接标记销毁交给 GC
        IsDisposed = true;
    }
}
```

这意味着框架中"是否用对象池"不是全局配置，而是**每个对象在 Fetch 时按需决定**。测试代码或一次性对象可以直接 `new`，不必走对象池，而高频复用的战斗组件则通过 `Fetch` 进池管理。规避了"强制所有对象都走池"带来的 `new ??"隐式丢失 Awake" Bug`。

---

## 六、对比总结

| 维度 | Core/Pool | ECS/ObjectPool |
|------|-----------|----------------|
| 容量上限 | 有（MaxPoolSize = 1000） | 跟随 Scene Dispose 清空 |
| 作用域 | 全局（静态） | 按 Scene 隔离 |
| 回调 | 无（调用方自行重置） | 触发 ECS Awake/Destroy |
| 重置 | 调用方负责 | 由 Clear() 逻辑清零 |

ECS 层在 Awake/Destroy 中封装了"业务初始化与清理"的全部复杂性，Core 层只专注于内存块的高效复用，两层分工清晰，避免了"对象池知道太多业务"或"业务代码手动管理 ECS 状态"的双重坏味道。

---

## 七、常见陷阱

### 7.1 错误：直接 new ECS 对象绕过 Awake

```csharp
// ❌ 错误做法：直接 new，Awake 不会被触发
var comp = new BattleComponent();
scene.AddComponent(comp);

// ✅ 正确做法：通过 Entity.AddComponent<T>() 走 ECS 路径
var comp = entity.AddComponent<BattleComponent>();
```

### 7.2 错误：Recycle 后继续持有引用

```csharp
BattleComponent comp = entity.GetComponent<BattleComponent>();
ObjectPool.Recycle(comp);
// ❌ comp.InstanceId 已被清零，EntityRef 已失效
// ❌ 继续读写 comp 会得到垃圾数据或污染下一个使用者
comp = null;  // ✅ 立刻置空

```

### 7.3 错误：跨 Scene 传递对象

```csharp
// ❌ 错误做法：将 SceneA 的对象回收到 SceneB 的池
// ECS 对象池以 Scene 为 Key，不支持跨 Scene 共享
```

---

## 八、小结

框架的双层对象池设计体现了"**职责单一**"原则：
- **Core/Pool** 只关心"有没有空闲内存块"
- **ECS/ObjectPool** 只关心"ECS 生命周期是否正确执行"

两层各自独立演进，ECS 层的 Awake/Destroy 机制升级不影响 Core 层，Core 层的容量策略调整也不影响 ECS 语义。这种分层思想在大型项目中能显著降低维护成本，也是阅读框架源码时理解"为什么有两个 ObjectPool"的核心答案。
