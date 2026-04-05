---
title: 列表组件对象池：消灭临时集合对象的 GC 分配
published: 2026-03-31
description: 深入解析 ListComponent 对象池的设计，理解如何通过 IDisposable 模式实现集合对象的零 GC 复用，以及 using 语句在资源管理中的应用。
tags: [Unity, 对象池, GC优化, 集合设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 临时 List 的 GC 问题

在事件分发系统的源码中，我们看到了这样的代码：

```csharp
using var tmpList = ListComponent<EventListenerInfo>.Create();
tmpList.Clear();
tmpList.AddRange(listeners);
```

为什么要用 `ListComponent<T>` 而不是直接 `new List<T>()`？

**答案是：减少 GC 分配。**

在高频调用的代码路径（如每帧触发的游戏事件），每次 `new List<>()` 都会在堆上分配内存，增加 GC 压力。

`ListComponent<T>` 是一个对象池化的 List 包装：

```csharp
public class ListComponent<T> : List<T>, IDisposable
{
    private static readonly Queue<ListComponent<T>> _pool = new();
    
    public static ListComponent<T> Create()
    {
        ListComponent<T> list;
        lock (_pool)
        {
            if (!_pool.TryDequeue(out list))
            {
                list = new ListComponent<T>();
            }
        }
        return list;
    }
    
    public void Dispose()
    {
        Clear();  // 清空数据（但保留内部数组容量）
        lock (_pool)
        {
            if (_pool.Count < 50)  // 池容量上限
            {
                _pool.Enqueue(this);
            }
        }
    }
}
```

---

## using 语句的 RAII 模式

```csharp
using var tmpList = ListComponent<EventListenerInfo>.Create();
// ... 使用 tmpList ...
// using 块结束，自动调用 Dispose() → 归还到池
```

这是 C# 的 **RAII（Resource Acquisition Is Initialization）** 模式：

- 资源获取（Create from pool）发生在变量声明时
- 资源释放（Return to pool）发生在作用域结束时
- `IDisposable` + `using` 是这个模式的 C# 实现

---

## 保留容量的 Clear()

```csharp
public void Dispose()
{
    Clear();  // 清空元素，但不释放内部数组！
    _pool.Enqueue(this);
}
```

`List<T>.Clear()` 只是把 `Count` 设为 0，内部数组的容量不变。

这意味着：池中的 `ListComponent` 对象保留了上次使用时扩展的内部数组。下次取出时，如果元素数量不超过这个容量，`Add` 操作不会触发数组扩容（即不会有新的堆分配）。

这是 `List<T>` 对象池效率高的核心原因——**容量的内存一直存在，只是被复用**。

---

## 池容量限制的考量

```csharp
if (_pool.Count < 50)  // 最多缓存 50 个
{
    _pool.Enqueue(this);
}
```

如果不限制，池可能无限增长（特别是在并发激增场景后，大量对象进池但之后不再被取出）。

50 是一个经验值——对于事件系统来说，极少会同时有超过 50 个并发的临时列表需求。

---

## 什么时候应该用对象池 List？

```
判断依据：
1. 该代码路径每帧或每秒被调用多次？ → 使用 ListComponent
2. 临时 List 的生命周期很短（方法级别）？ → 使用 ListComponent
3. 长生命周期的 List（存在于字段中）？ → 用普通 List，不用池

示例：
✅ 用 ListComponent：
   - 每帧触发的事件监听器临时副本
   - 查询结果临时存储（立即消费）
   
❌ 不用 ListComponent：
   - Entity 的组件列表（长期存在）
   - 场景中的所有单位列表（长期存在）
```

---

## 总结

`ListComponent<T>` 展示了对象池技术在集合类上的应用：

- **继承 List<T>**：保留所有 List 功能，无学习成本
- **实现 IDisposable**：配合 `using` 语句自动归还
- **保留容量**：Clear 不释放内部数组，减少扩容次数
- **容量上限**：防止池无限膨胀

这个模式可以推广到任何频繁创建销毁的对象类型，是游戏运行时性能优化的标准武器之一。
