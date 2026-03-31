---
title: 碰撞接口与通用对象池——ICollider 和 ObjectPool 的设计精要
published: 2026-03-31
description: 解析确定性物理引擎的碰撞接口 ICollider 的设计，以及通用对象池 ObjectPool<T> 的线程安全实现和专用静态池（ListPool、HashSetPool 等）的便捷封装模式。
tags: [Unity, ECS, 对象池, 物理引擎, 线程安全]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 碰撞接口与通用对象池——ICollider 和 ObjectPool 的设计精要

## 前言

本系列的最后一篇，我们来分析两个相对独立的系统：

- `ICollider`：确定性物理引擎的碰撞体接口
- `ObjectPool<T>`：通用对象池的完整实现

虽然两者功能完全不同，但都体现了框架的核心设计理念：**接口隔离** 和 **资源复用**。

---

## 一、ICollider——确定性物理的碰撞体接口

```csharp
using TrueSync;

namespace VGame
{
    public interface ICollider
    {
        public int ColliderType { get; set; }
        public TSVector Center { get; set; }
        public TSVector Size { get; set; }
        public FP Radius { get; set; }
        public TSQuaternion Rotation { get; set; }
    }
}
```

### 1.1 TrueSync 类型——确定性物理的基础

这里出现了三个 TrueSync 类型：

| 类型 | 含义 |
|---|---|
| `TSVector` | 确定性三维向量（替代 `Vector3`） |
| `FP` | 固定点数（替代 `float`） |
| `TSQuaternion` | 确定性四元数（替代 `Quaternion`） |

为什么不用 Unity 原生的 `Vector3`、`float`、`Quaternion`？

在**帧同步**游戏中，所有客户端必须产生完全相同的物理计算结果。Unity 的浮点运算在不同 CPU 上可能有微小差异，而 TrueSync 的定点数类型保证跨平台一致性。

### 1.2 接口设计——统一多种碰撞形状

```csharp
public int ColliderType { get; set; }  // 碰撞体类型（盒子/球/...）
public TSVector Center { get; set; }   // 中心点
public TSVector Size { get; set; }     // 大小（盒子用）
public FP Radius { get; set; }         // 半径（球/圆柱用）
public TSQuaternion Rotation { get; set; }  // 旋转
```

接口包含了所有碰撞形状共有的属性。不同形状会使用其中的一个子集：

- **球（Sphere）**：使用 `Center` + `Radius`
- **立方体（Box）**：使用 `Center` + `Size` + `Rotation`
- **胶囊（Capsule）**：使用 `Center` + `Radius` + `Size`（高度）

`ColliderType` 是整数枚举，决定哪些字段有意义：

```csharp
public static class ColliderType
{
    public const int Sphere = 0;
    public const int Box = 1;
    public const int Capsule = 2;
}
```

### 1.3 为什么注释掉了 Height？

```csharp
//public float Height { get; set; }
```

`Height` 被注释掉了，可能是因为：
1. `Size` 字段可以用某个分量代表高度（如 `Size.y`）
2. 或者后来发现 Capsule 类型可以用 `Size.y` 而不是单独的 `Height`

被注释的代码是"设计演化的化石"——它告诉我们曾经有这个想法，但后来被放弃了。

---

## 二、ObjectPool<T>——通用对象池的完整实现

```csharp
public class ObjectPool<T> : IDisposable, IObjectPool<T> where T : class
{
    public static ObjectPool<T> Shared = new ObjectPool<T>(null, null); // 全局共享实例
    
    private readonly Func<T> m_CreateFunc;
    private readonly Action<T> m_ActionOnGet;
    private readonly Action<T> m_ActionOnRelease;
    private readonly Action<T> m_ActionOnDestroy;
    private readonly Stack<T> m_Stack = new();
```

### 2.1 四个可注入的委托

```csharp
public ObjectPool(
    Func<T> actionCreate,        // 如何创建新对象
    Action<T> actionOnGet,       // 从池中取出时的回调
    Action<T> actionOnRelease,   // 放回池时的回调
    Action<T> actionOnDestroy = null) // 清理池时的销毁回调
```

这四个委托让 `ObjectPool` 完全通用：

```csharp
// 字典对象池（取出时不操作，放回时清空）
var dictPool = new ObjectPool<Dictionary<string, int>>(
    () => new Dictionary<string, int>(),  // 创建
    null,                                  // 取出：不操作
    d => d.Clear()                         // 放回：清空
);

// 粒子特效对象池（取出时激活，放回时禁用）
var particlePool = new ObjectPool<ParticleSystem>(
    () => GameObject.Instantiate(prefab).GetComponent<ParticleSystem>(),
    p => p.gameObject.SetActive(true),      // 取出：激活
    p => { p.Stop(); p.gameObject.SetActive(false); } // 放回：停止并禁用
);
```

### 2.2 线程安全的 Get 和 Release

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
    m_ActionOnGet?.Invoke(element);
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

两处都有 `lock (m_Stack)` 锁，确保多线程安全。

### 2.3 重复释放检测

```csharp
if (m_Stack.Count > 0 && ReferenceEquals(m_Stack.Peek(), element))
    Log.Error("Internal error. Trying to destroy object that is already released to pool.");
```

如果被释放的对象与栈顶的对象是同一个（`ReferenceEquals`），说明对象被重复释放了。

这是一个防御性检查——重复释放是严重的 Bug，会导致同一对象被同时使用两次（数据污染）。

注意：只检查栈顶，而不是遍历整个栈——O(1) 开销，虽然不能检测所有的重复释放（对象可能不在栈顶），但能检测最常见的情况。

### 2.4 PooledObject<T>——RAII 风格的便捷 API

```csharp
public struct PooledObject<T> : IDisposable where T : class
{
    private readonly T m_ToReturn;
    private readonly IObjectPool<T> m_Pool;

    void IDisposable.Dispose() => this.m_Pool.Release(this.m_ToReturn);
}

// 使用方式
using var _ = pool.Get(out var obj);
// 使用 obj...
// using 块结束时自动调用 Release
```

`PooledObject<T>` 是一个 struct（不产生 GC），配合 `using`，实现了 RAII 风格的对象池使用：

```csharp
using (pool.Get(out var list))
{
    list.Add(item1);
    list.Add(item2);
    ProcessList(list);
} // 自动 Release
```

### 2.5 统计信息

```csharp
public int CountAll { get; private set; }     // 总创建量
public int CountActive => CountAll - CountInactive;  // 使用中
public int CountInactive { get; }              // 池中等待
```

这些统计信息对于调试内存泄漏非常有用：

```csharp
// 如果 CountActive 持续增长，说明有对象没有被正确放回池
Debug.Log($"池中等待: {pool.CountInactive}, 使用中: {pool.CountActive}");
```

---

## 三、专用静态池——便捷的标准集合池

```csharp
public static class ListPool<T>
{
    private static readonly ObjectPool<List<T>> s_ListPool = new(null, l => l?.Clear());
    
    public static List<T> Get() => s_ListPool.Get();
    public static PooledObject<List<T>> Get(out List<T> v) => s_ListPool.Get(out v);
    public static void Release(List<T> toRelease) => s_ListPool.Release(toRelease);
    public static string GetDebugInfo() => s_ListPool.GetDebugInfo();
}

// 类似的：HashSetPool<T>、DictionaryPool<T,K>、StackPool<T>、QueuePool<T>
```

**为什么用静态类而非实例？**

这些是"全局共享的"标准集合池——整个程序只需要一个 `List<int>` 池。静态类提供了全局唯一的访问入口，无需管理实例：

```csharp
// 使用
using var _ = ListPool<Entity>.Get(out var entities);
entities.Add(entity1);
// ... 操作 entities
// 自动放回 ListPool<Entity>
```

与前面分析的 `ListComponent<T>` 不同，`ListPool<T>` 直接包装原生 `List<T>`，不需要子类化，适合更简单的使用场景。

---

## 四、两套对象池的比较

框架中有两套对象池体系：

| 特性 | ListComponent<T> 等 | ListPool<T> 等 |
|---|---|---|
| 方式 | 继承 List<T>，实现 IDisposable | 包装 List<T>，提供 Get/Release |
| using 支持 | ✅ 直接 using var | ✅ 通过 PooledObject |
| 集成深度 | 深（ECS 框架内置） | 浅（独立工具类） |
| 适用场景 | ECS 系统内部临时集合 | 任意代码的临时集合 |

两套系统共存，给开发者更多选择。在 ECS 系统代码中用 `ListComponent`（与框架集成），在其他代码中用 `ListPool`（更通用）。

---

## 五、本系列总结

至此，40 篇 Unity Core 系统技术文章全部完成。回顾这段旅程：

| 批次 | 主题 | 核心收获 |
|---|---|---|
| 批次1 | Timer & Time | 帧同步定时器、安全引用 EntityRef |
| 批次2 | Entity 扩展 | 工厂模式、特性系统、Scene 架构 |
| 批次3 | EventSystem 接口 | 生命周期系统、发布-订阅、元数据调度 |
| 批次4 | Singleton & Object | 单例设计、游戏调度、IDisposable |
| 批次5 | Handler & Define | 处理器模式、对象池集合 |
| 批次6 | Performance & 工具 | VProfiler、拼音搜索、线程安全、对象池 |

这套框架的核心设计理念：
1. **数据与逻辑分离**（ECS）
2. **接口驱动的松耦合**（各种接口标记）
3. **反射驱动的自动注册**（[ObjectSystem]、[EntitySystem]）
4. **对象复用减少 GC**（多套对象池）
5. **确定性计算支持帧同步**（FP 定点数、TSVector）
6. **热更新友好**（[StaticField]、ILoad）

这些原则不仅适用于这个框架，也是大型游戏项目架构设计的普遍智慧。
