---
title: xgame框架通用对象池ObjectPool泛型架构与集合池族设计深度解析
published: 2026-04-30
description: 深入解析 xgame 框架 Pool 目录中 ObjectPool<T> 的泛型通用对象池架构，以及基于它构建的 ListPool、HashSetPool、DictionaryPool、StackPool、QueuePool 集合池族，揭示线程安全、PooledObject using 模式与零 GC 设计思路。
tags: [Unity, 游戏框架, 对象池, ObjectPool, 零GC, 内存优化, C#]
category: 游戏开发
encryptedKey: henhaoji123
---

## 前言

对象池是游戏开发中对抗 GC 的核心武器。xgame 框架在 `Core/Pool/` 目录下实现了一套高度通用的泛型对象池 `ObjectPool<T>`，并在此基础上衍生出 `ListPool<T>`、`HashSetPool<T>`、`DictionaryPool<T,K>`、`StackPool<T>`、`QueuePool<T>` 等集合专用池族，覆盖了游戏开发中几乎所有常见的临时集合分配场景。

---

## ObjectPool<T> 核心架构

### 接口设计

```csharp
public interface IObjectPool<T> where T : class
{
    int CountInactive { get; }
    T Get();
    PooledObject<T> Get(out T v);
    void Release(T element);
    void Clear();
}
```

这个接口抽象了对象池的四个核心操作：获取、带出参获取、归还、清空。它的泛型约束 `where T : class` 限定只能池化引用类型（引用类型才有池化的意义）。

### PooledObject<T>：using 模式的零侵入归还

```csharp
public struct PooledObject<T> : IDisposable where T : class
{
    private readonly T m_ToReturn;
    private readonly IObjectPool<T> m_Pool;

    internal PooledObject(T value, IObjectPool<T> pool)
    {
        this.m_ToReturn = value;
        this.m_Pool = pool;
    }

    void IDisposable.Dispose() => this.m_Pool.Release(this.m_ToReturn);
}
```

`PooledObject<T>` 是一个值类型（`struct`），封装了"对象 + 其归属的池"的元组。它实现了 `IDisposable`，因此可以配合 `using` 语句使用：

```csharp
using (ListPool<int>.Get(out var list))
{
    list.Add(1);
    list.Add(2);
    // 离开 using 块，自动调用 Dispose() → 归还 list 到池
}
```

这种模式完全消除了手动 `Release` 可能造成的泄漏风险，同时不影响代码可读性。

### 两种构造函数

```csharp
// 简化版：自动用 Activator.CreateInstance 创建对象
public ObjectPool(Action<T> actionOnGet, Action<T> actionOnRelease)
{
    m_CreateFunc = () => (T) Activator.CreateInstance(typeof(T));
    // ...
}

// 完整版：自定义创建、获取、归还、销毁的全部钩子
public ObjectPool(Func<T> actionCreate, Action<T> actionOnGet, 
                  Action<T> actionOnRelease, Action<T> actionOnDestroy = null)
{
    m_CreateFunc = actionCreate;
    // ...
}
```

简化版适合有无参构造函数的对象；完整版允许自定义创建逻辑，比如从外部系统分配，或需要在销毁时释放 Native 资源。

### 线程安全的 Get/Release

```csharp
public T Get()
{
    T element;
    lock (m_Stack)
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
    m_ActionOnGet?.Invoke(element);  // 钩子在 lock 外调用，避免死锁风险
    return element;
}

public void Release(T element)
{
    lock (m_Stack)
    {
        if (m_Stack.Count > 0 && ReferenceEquals(m_Stack.Peek(), element))
            Log.Error("Internal error. Trying to destroy object that is already released to pool.");
        m_ActionOnRelease?.Invoke(element);
        m_Stack.Push(element);
    }
}
```

几个值得注意的细节：

1. **lock 范围最小化**：`Get` 中的 `m_ActionOnGet` 钩子在 `lock` 外调用，避免钩子内部再次操作池时发生死锁。
2. **双重归还检测**：`Release` 中检查栈顶是否与待归还对象相同（`ReferenceEquals`），防止同一对象被归还两次。
3. **CountAll 统计**：只在创建新对象时 `++`，配合 `CountActive = CountAll - CountInactive` 可以实时监控活跃对象数量。

### 调试信息

```csharp
public string GetDebugInfo()
{
    var info = "ListPool:" + typeof(T) + "\n";
    info += "Count All: " + CountAll + ", Count Active: " + CountActive + ", Count Inactive: " + CountInactive;
    // 对于 List<string>，还会统计最大容量
    return info;
}
```

这个方法在开发期间可用于检查池的使用情况，判断是否存在对象泄漏（`CountActive` 持续增长）。

---

## 集合池族：统一的零配置设计

基于 `ObjectPool<T>`，框架构建了一批"开箱即用"的集合专用池，每种集合只需一行声明：

```csharp
// ListPool
private static readonly ObjectPool<List<T>> s_ListPool = new(null, l => l?.Clear());

// HashSetPool
private static readonly ObjectPool<HashSet<T>> s_HashSetPool = new(null, l => l.Clear());

// DictionaryPool
private static readonly ObjectPool<Dictionary<T, K>> s_DictPool = new(null, l => l.Clear());

// StackPool
private static readonly ObjectPool<Stack<T>> s_StackPool = new(null, l => l.Clear());

// QueuePool
private static readonly ObjectPool<Queue<T>> s_QueuePool = new(null, l => l.Clear());
```

构造参数的关键：
- `actionOnGet = null`：获取时不做任何初始化（对象从池中取出时保持上次归还后的状态）
- `actionOnRelease = l => l.Clear()`：**归还时立即清空内容**，确保下次取出是干净的空集合

这个约定非常重要：**池中的集合始终是"空但已分配容量"的状态**，既不需要重新分配内存，也不会携带上次使用的脏数据。

### 双接口访问模式

每个集合池都提供两种访问方式：

```csharp
// 方式一：手动管理生命周期
var list = ListPool<int>.Get();
list.Add(item);
ListPool<int>.Release(list);

// 方式二：using 自动归还（推荐）
using (ListPool<int>.Get(out var list))
{
    list.Add(item);
    ProcessList(list);
}  // 自动归还
```

方式二通过 `PooledObject<T>` 的 `Dispose` 机制实现自动归还，适合生命周期明确的局部临时集合；方式一适合跨帧、跨函数持有集合的场景。

---

## Shared 静态实例

`ObjectPool<T>` 还提供了一个全局共享实例：

```csharp
public static ObjectPool<T> Shared = new ObjectPool<T>(null, null);
```

这是一个用空钩子初始化的默认实例，对于没有特殊初始化/清理需求的对象，可以直接通过 `ObjectPool<T>.Shared.Get()` 使用，不需要在每个使用方自行创建池实例。

---

## 与 ECS 对象池的对比

框架中存在两套对象池：

| 特性 | Pool/ObjectPool<T>（本篇） | ECS/ObjectPool |
|------|--------------------------|----------------|
| **泛型约束** | `where T : class` | ET 框架实体/组件 |
| **线程安全** | ✅ lock | 通常单线程（主线程 ECS） |
| **适用对象** | 任意引用类型（集合、工具类） | ECS 组件和实体 |
| **using 模式** | ✅ PooledObject<T> | ❌ |
| **归还钩子** | ✅ actionOnRelease | 特定接口（IReset等） |

两套池各有分工，不互相替代。`Core/Pool/` 的通用池偏向"集合类、工具类"的临时借用；ECS 对象池专注于实体/组件的生命周期管理。

---

## 实际应用场景

**场景一：战斗伤害目标收集**

```csharp
using (ListPool<Unit>.Get(out var targets))
{
    GetNearbyUnits(position, radius, targets);
    foreach (var unit in targets)
    {
        ApplyDamage(unit, damage);
    }
}  // targets 自动归还，无 GC
```

**场景二：事件参数临时字典**

```csharp
using (DictionaryPool<string, object>.Get(out var args))
{
    args["damage"] = 100;
    args["type"] = DamageType.Physical;
    EventSystem.Publish(EventId.OnDamage, args);
}
```

**场景三：寻路结果路径**

```csharp
var path = ListPool<Vector3>.Get();
if (Pathfinder.FindPath(start, end, path))
{
    MoveAgent(agent, path);
}
ListPool<Vector3>.Release(path);  // 跨帧持有，手动归还
```

---

## 总结

xgame 框架的 `ObjectPool<T>` 用不到 100 行代码，实现了一个生产级别的泛型对象池，其设计亮点包括：

1. **PooledObject<T> 结构体 + using 模式**，零侵入自动归还
2. **lock 范围最小化**，钩子在 lock 外执行，防止死锁
3. **双重归还检测**，及早发现归还错误
4. **集合池族统一模式**：`(null, l => l.Clear())` 一行声明，保证干净出池

这套设计在 Unity 移动端开发中极为实用——每帧数百次的集合分配全部通过池化消除，GC 压力大幅降低，是零 GC 编程实践的典范。
