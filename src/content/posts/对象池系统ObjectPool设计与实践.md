---
title: 06 对象池系统 ObjectPool 设计与实践
published: 2024-01-01
description: "06 对象池系统 ObjectPool 设计与实践 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 06 对象池系统 ObjectPool 设计与实践

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

在游戏开发中，频繁创建和销毁对象会触发 .NET 垃圾回收（GC），导致明显的卡顿。对象池（Object Pool）通过**预分配 + 复用**机制，将"创建/销毁"变成"取出/放回"，从根本上消除 GC 压力。

本框架实现了**两套对象池**，各有适用场景：

| 对象池 | 命名空间 | 适用对象 | 特点 |
|---|---|---|---|
| `ET.ObjectPool` | ET（ECS框架层） | Entity 及其内部容器 | 单例模式，无类型约束，支持 `Fetch<T>` / `Recycle` |
| `VGame.Framework.ObjectPool<T>` | VGame.Framework（业务层） | 任意引用类型 | 泛型强类型，支持自定义回调，线程安全（lock） |

本项目还在 `VGame.Framework` 层为常用容器封装了静态工厂池：`ListPool<T>`、`HashSetPool<T>`、`DictionaryPool<T,K>`、`StackPool<T>`、`QueuePool<T>`。

---

## 2. 架构设计

### 2.1 ET.ObjectPool（ECS 层对象池）

```
ObjectPool（Singleton）
  └── pool: Dictionary<Type, Queue<object>>

Fetch(Type)
  → pool 中有该类型的队列 且 非空 → 出队返回
  → 否则 → Activator.CreateInstance(type) 创建新实例

Recycle(object)
  → 取 obj.GetType() 为键，找到对应队列（没有则创建）
  → 入队
```

**特点**：简单、无限制，不做容量控制，不做回调。  
**用途**：Entity、Dictionary、List、HashSet 等 ECS 内部使用的容器对象。

### 2.2 VGame.Framework.ObjectPool<T>（业务层对象池）

```
ObjectPool<T>
  ├── m_CreateFunc: Func<T>             ← 对象创建工厂
  ├── m_ActionOnGet: Action<T>          ← 取出时的回调（如重置状态）
  ├── m_ActionOnRelease: Action<T>      ← 放回时的回调（如清空数据）
  ├── m_ActionOnDestroy: Action<T>      ← 销毁时的回调
  ├── m_Stack: Stack<T>                 ← 空闲对象栈（LIFO）
  ├── CountAll: int                     ← 总创建数量
  ├── CountActive: int                  ← 使用中数量（= CountAll - CountInactive）
  └── CountInactive: int                ← 池中空闲数量
```

### 2.3 静态容器池的层次

```
ListPool<T>
  └── ObjectPool<List<T>>
        m_ActionOnRelease = list => list.Clear()  ← 放回时自动清空
        m_CreateFunc = () => new List<T>()
```

---

## 3. 核心代码展示

### 3.1 ET.ObjectPool —— 无类型约束的简单池

```csharp
// X:\UnityProj\Assets\Scripts\Core\ECS\ObjectPool\ObjectPool.cs

public class ObjectPool : Singleton<ObjectPool>
{
    // Type → 对象队列
    private readonly Dictionary<Type, Queue<object>> pool = new();

    // 泛型版本（内部调用非泛型版本）
    public T Fetch<T>() where T : class
    {
        return this.Fetch(typeof(T)) as T;
    }

    public object Fetch(Type type)
    {
        if (!pool.TryGetValue(type, out Queue<object> queue) || queue.Count == 0)
            return Activator.CreateInstance(type);  // 池为空则反射创建

        return queue.Dequeue();
    }

    public void Recycle(object obj)
    {
        Type type = obj.GetType();
        if (!pool.TryGetValue(type, out Queue<object> queue))
        {
            queue = new Queue<object>();
            pool.Add(type, queue);
        }
        queue.Enqueue(obj);
    }
}
```

### 3.2 VGame.Framework.ObjectPool<T> —— 功能完整的泛型池

```csharp
// X:\UnityProj\Assets\Scripts\Core\Pool\ObjectPool.cs

public class ObjectPool<T> : IDisposable, IObjectPool<T> where T : class
{
    // 共享实例（简单场景直接用）
    public static ObjectPool<T> Shared = new ObjectPool<T>(null, null);

    private readonly Func<T> m_CreateFunc;
    private readonly Action<T> m_ActionOnGet;
    private readonly Action<T> m_ActionOnRelease;
    private readonly Action<T> m_ActionOnDestroy;
    private readonly Stack<T> m_Stack = new();

    // 构造 1：使用 Activator.CreateInstance 默认构造
    public ObjectPool(Action<T> actionOnGet, Action<T> actionOnRelease)
    {
        m_CreateFunc = () => (T)Activator.CreateInstance(typeof(T));
        m_ActionOnGet = actionOnGet;
        m_ActionOnRelease = actionOnRelease;
    }

    // 构造 2：完全自定义生命周期回调
    public ObjectPool(Func<T> actionCreate, Action<T> actionOnGet,
                      Action<T> actionOnRelease, Action<T> actionOnDestroy = null)
    {
        m_CreateFunc = actionCreate;
        m_ActionOnGet = actionOnGet;
        m_ActionOnRelease = actionOnRelease;
        m_ActionOnDestroy = actionOnDestroy;
    }

    public T Get()
    {
        T element;
        lock (m_Stack)  // 线程安全（虽然主要在主线程使用）
        {
            if (m_Stack.Count == 0)
            {
                element = m_CreateFunc.Invoke();
                CountAll++;
            }
            else
            {
                element = m_Stack.Pop();
            }
        }
        m_ActionOnGet?.Invoke(element);  // 取出回调（如重置 dirty 标志）
        return element;
    }

    // PooledObject<T> 版本：配合 using 语句自动归还
    public PooledObject<T> Get(out T v) => new(v = Get(), this);

    public void Release(T element)
    {
        lock (m_Stack)
        {
            // 安全检查：防止重复 Release 同一对象
            if (m_Stack.Count > 0 && ReferenceEquals(m_Stack.Peek(), element))
                Log.Error("Internal error. Trying to destroy object that is already released to pool.");

            m_ActionOnRelease?.Invoke(element);  // 放回回调（如 list.Clear()）
            m_Stack.Push(element);
        }
    }

    public void Clear()
    {
        CountAll = 0;
        lock (m_Stack)
        {
            if (m_ActionOnDestroy != null)
                foreach (var v in m_Stack)
                    m_ActionOnDestroy.Invoke(v);
            m_Stack.Clear();
        }
    }
}
```

### 3.3 PooledObject<T> —— using 自动归还

```csharp
// 配合 using 语句实现 RAII 风格的对象池使用
public struct PooledObject<T> : IDisposable where T : class
{
    private readonly T m_ToReturn;
    private readonly IObjectPool<T> m_Pool;

    internal PooledObject(T value, IObjectPool<T> pool)
    {
        this.m_ToReturn = value;
        this.m_Pool = pool;
    }

    // using 块结束时自动调用，将对象归还池中
    void IDisposable.Dispose() => this.m_Pool.Release(this.m_ToReturn);
}

// 使用示例：
using (var pooled = ListPool<int>.Get(out var list))
{
    list.Add(1);
    list.Add(2);
    // using 块结束，list 自动归还到 ListPool，并被 Clear()
}
```

### 3.4 静态容器池（ListPool / HashSetPool / DictionaryPool）

```csharp
// X:\UnityProj\Assets\Scripts\Core\Pool\ObjectPool.cs（节选）

public static class ListPool<T>
{
    // 内部持有一个 ObjectPool<List<T>>，放回时自动清空
    private static readonly ObjectPool<List<T>> s_ListPool =
        new(null, l => l?.Clear());  // actionOnRelease = Clear

    public static List<T> Get() => s_ListPool.Get();

    // using 自动归还版本
    public static PooledObject<List<T>> Get(out List<T> v) => s_ListPool.Get(out v);

    public static void Release(List<T> toRelease) => s_ListPool.Release(toRelease);
}

// HashSetPool<T>、DictionaryPool<T,K>、StackPool<T>、QueuePool<T> 同理
```

---

## 4. Entity 如何使用对象池

Entity 内部大量使用 `ET.ObjectPool` 来管理容器对象，避免频繁 new：

```csharp
// Entity.cs - Children 属性（按需分配，用完回收）
private Dictionary<long, Entity> children;

public Dictionary<long, Entity> Children
{
    get
    {
        if (this.children == null)
            this.children = ObjectPool.Instance.Fetch<Dictionary<long, Entity>>();
        return this.children;
    }
}

private void RemoveFromChildren(Entity entity)
{
    if (this.children == null) return;
    this.children.Remove(entity.Id);

    if (this.children.Count == 0)
    {
        // 字典为空时立即回收到对象池
        ObjectPool.Instance.Recycle(this.children);
        this.children = null;
    }
    // ...
}
```

**要点**：
- 字典/HashSet 使用**懒加载**（第一次访问才分配）
- 集合为空时**立即回收**，不等到 Dispose
- 这样一个 Entity 在没有子节点时，`children` 字段为 null，零内存占用

---

## 5. ListComponent<T> —— 临时列表的最佳实践

框架提供了 `ListComponent<T>` 作为 `EventSystem` 内部临时列表的标准用法：

```csharp
// 典型用法（在 EventSystem 的 BeforeFixedUpdate 中）
public void BeforeFixedUpdate()
{
    using var entities = ListComponent<Entity>.Create();  // 从对象池取出
    // ... 填充 entities ...
    // using 块结束自动归还
}

// ListComponent 内部实现
public class ListComponent<T> : List<T>, IDisposable
{
    public static ListComponent<T> Create()
    {
        return ObjectPool.Instance.Fetch<ListComponent<T>>();
    }

    public void Dispose()
    {
        this.Clear();
        ObjectPool.Instance.Recycle(this);
    }
}
```

---

## 6. 设计亮点

### 6.1 两级对象池分层设计

- **ET.ObjectPool（框架层）**：无限制，灵活，支持 Entity 等特殊对象的池化
- **VGame.Framework.ObjectPool<T>（业务层）**：类型安全，有回调支持，适合业务逻辑中频繁使用的容器

两套池互不干扰，框架层的简单需求不必为回调机制付出额外开销。

### 6.2 PooledObject + using RAII 模式

```csharp
// 不用手动 Release，using 结束自动归还
using (ListPool<int>.Get(out var numbers))
{
    for (int i = 0; i < 1000; i++) numbers.Add(i);
    ProcessNumbers(numbers);
}  // ← 这里自动调用 Release，numbers.Clear()
```

对比手动管理：
```csharp
// 手动管理容易忘 Release（内存泄漏）
var numbers = ListPool<int>.Get();
try { ProcessNumbers(numbers); }
finally { ListPool<int>.Release(numbers); }  // 必须写 finally
```

### 6.3 重复 Release 安全检查

```csharp
// ObjectPool<T>.Release 中的保护
if (m_Stack.Count > 0 && ReferenceEquals(m_Stack.Peek(), element))
    Log.Error("Internal error. Trying to destroy object that is already released to pool.");
```

这个检查能立即发现"同一对象被 Release 两次"的 Bug，避免同一对象被两个地方同时使用。

---

## 7. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| ET.ObjectPool | 相同 | 相同 |
| 泛型对象池 | 无（主要用 ET.ObjectPool） | 新增 `VGame.Framework.ObjectPool<T>` |
| 静态容器池 | 无 | 新增 ListPool / HashSetPool / DictionaryPool 等 |
| PooledObject | 无 | 新增，支持 using 自动归还 |
| 线程安全 | 无（单线程） | ObjectPool<T> 内部加 lock |
| Shared 实例 | 无 | 新增 `ObjectPool<T>.Shared` 便捷访问 |

---

## 8. 常见问题与最佳实践

### Q1：从池中取出的对象有脏数据怎么办？

对象池不会自动清零对象的字段。需要在 `m_ActionOnGet` 回调中重置状态：

```csharp
var pool = new ObjectPool<MyData>(
    createFunc:  () => new MyData(),
    actionOnGet: data => data.Reset(),      // 取出时重置
    actionOnRelease: data => data.Cleanup() // 放回时清理
);
```

### Q2：Entity 使用 isFromPool 时需要注意什么？

```csharp
// 从池中取出的 Entity 字段不会被自动清零
// 框架在 Create 时手动设置了必要字段
Entity component = Entity.Create(type, isFromPool: true);
// 会设置：IsFromPool=true, IsCreated=true, IsNew=true, Id=0
// 不会清零的：业务字段（如 Speed、Health 等）

// 因此，建议在 AwakeSystem 中初始化所有业务字段：
public class PlayerMoveSystem : AwakeSystem<PlayerMoveComponent>
{
    protected override void Awake(PlayerMoveComponent self)
    {
        self.Speed = 5.0f;  // ← 每次 Awake 都重置，不依赖默认值
    }
}
```

### Q3：哪些情况不适合使用对象池？

1. **对象创建成本极低**（如 `int`、`bool` 等值类型）
2. **对象生命周期很长**（如全局单例），池化意义不大
3. **对象有复杂的初始化状态**，每次取出都需要完整重置，开销可能超过 new

### Q4：如何监控对象池的使用情况？

```csharp
// VGame.Framework.ObjectPool<T> 提供调试信息
var pool = ListPool<int>.s_ListPool;  // 或你自己的池
Log.Info(pool.GetDebugInfo());
// 输出：ListPool:System.Collections.Generic.List`1[System.Int32]
//        Count All: 50, Count Active: 12, Count Inactive: 38, Max Capacity: 128
```

---

## 9. 总结

本框架的对象池系统分两层设计，各司其职：

- **ET.ObjectPool**：轻量级、无约束，为 ECS 框架内部服务
- **ObjectPool<T> + 静态容器池**：功能完整，为业务逻辑提供类型安全、自动回调的对象复用

核心实践要点：
1. 临时容器（List/Dict/HashSet）一律使用 `ListPool<T>.Get(out var list)` + `using` 模式
2. 业务 Entity 使用 `isFromPool: true` 参数，配合 AwakeSystem 重置状态
3. `PooledObject` 的 `using` 模式是防止忘记归还的最佳实践
