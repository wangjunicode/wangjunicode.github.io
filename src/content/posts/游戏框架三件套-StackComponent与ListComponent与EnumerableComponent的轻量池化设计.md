---
title: 游戏框架三件套-StackComponent与ListComponent与EnumerableComponent的轻量池化设计
published: 2026-04-22
description: 深入解析ET游戏框架中三个轻量级池化集合组件——StackComponent、ListComponent、EnumerableComponent的设计思路，揭示继承式池化、迭代器复用、零分配过滤枚举的实现原理及游戏开发中的实战技巧。
tags: [Unity, CSharp, 游戏框架, 对象池, 设计模式, ET框架]
category: 游戏开发
draft: false
encryptedKey: henhaoji123
---

# 游戏框架三件套：StackComponent / ListComponent / EnumerableComponent

## 问题的起点：临时集合的 GC 噩梦

在游戏开发中，以下代码模式随处可见：

```csharp
// 每帧都在分配 List、Stack
List<Enemy> nearbyEnemies = new List<Enemy>();
FindEnemiesInRange(nearbyEnemies);
foreach (var e in nearbyEnemies) { /* ... */ }
// 函数结束 → nearbyEnemies 成为垃圾，等待 GC
```

一个频繁调用的函数每次都 `new` 一个临时集合，在高频逻辑（Update、战斗帧）中会产生显著的 GC 压力，引发卡顿。

ET 框架用三个极其轻量的组件解决了这个问题：**StackComponent**、**ListComponent**、**EnumerableComponent**。

---

## StackComponent：继承式池化栈

```csharp
public class StackComponent<T> : Stack<T>, IDisposable
{
    public static StackComponent<T> Create()
    {
        if (ObjectPool.Instance == null) return new StackComponent<T>();
        return ObjectPool.Instance.Fetch(typeof(StackComponent<T>)) as StackComponent<T>;
    }

    public void Dispose()
    {
        if (ObjectPool.Instance == null) return;
        this.Clear();
        ObjectPool.Instance.Recycle(this);
    }
}
```

### 设计解析

**继承而非组合**：`StackComponent<T>` 直接继承 `Stack<T>`，这意味着它**就是**一个 Stack，拥有 Push/Pop/Peek 等全部原生方法，使用者无需学习任何新 API。

**透明的池化切换**：
- `ObjectPool.Instance == null` → 框架未初始化（编辑器单元测试场景），直接 `new`，保证代码在任何环境可用。
- 正常运行时 → 从对象池 `Fetch`，避免分配。

**IDisposable 协议**：配合 `using` 语句，实现**自动归还**到对象池：

```csharp
using var stack = StackComponent<int>.Create();
stack.Push(42);
stack.Push(100);
while (stack.Count > 0)
{
    Process(stack.Pop());
}
// using 块结束 → 自动调用 Dispose → Clear + Recycle
```

**Clear 的必要性**：归还前调用 `Clear()` 是关键安全措施。若不清空，池中的对象可能持有对游戏实体的引用，导致：
1. 内存泄漏（引用阻止 GC 回收）
2. 下次取出时包含上次的脏数据

---

## ListComponent：池化动态数组

```csharp
public class ListComponent<T> : List<T>, IDisposable
{
    public static ListComponent<T> Create()
    {
        if (ObjectPool.Instance == null) return new ListComponent<T>();
        return ObjectPool.Instance.Fetch(typeof(ListComponent<T>)) as ListComponent<T>;
    }

    public void Dispose()
    {
        if (ObjectPool.Instance == null) return;
        this.Clear();
        ObjectPool.Instance.Recycle(this);
    }
}
```

与 StackComponent 设计完全对称。继承 `List<T>`，同样通过 `IDisposable` 归还池。

### 核心使用模式

```csharp
// 模式一：using 语句（推荐）
using var result = ListComponent<Unit>.Create();
GetUnitsInRadius(center, radius, result);
foreach (var unit in result)
    unit.TakeDamage(dmg);
// 自动归还

// 模式二：手动管理（跨帧场景）
var pending = ListComponent<Projectile>.Create();
// ... 多帧积累
pending.Dispose(); // 明确的生命周期终点
```

### List vs Stack：继承的权衡

| | ListComponent | StackComponent |
|--|--|--|
| 继承基类 | `List<T>` | `Stack<T>` |
| 访问方式 | 随机索引 O(1) | LIFO |
| 排序 | Sort() 可用 | 不支持 |
| 典型场景 | 收集结果、批量处理 | DFS遍历、撤销系统 |

---

## EnumerableComponent：零分配过滤枚举器

```csharp
public class EnumerableComponent<TSource, TResult>
    : IEnumerable<TResult>, IEnumerator<TResult>
    where TResult : class
    where TSource : class
{
    public delegate bool CheckHandler(TResult item);
    public delegate TResult ConvertHandler(TSource item);

    private IEnumerator<TSource> _sourceListEnumerator;
    private CheckHandler _func;
    private ConvertHandler _ConvertFunc;

    private static ConvertHandler defaultConvertFunc = defaultConvert;
    private static TResult defaultConvert(TSource source) => source as TResult;

    public static EnumerableComponent<TSource, TResult> Create(
        IEnumerable<TSource> sourceList,
        CheckHandler checkFunc,
        ConvertHandler convertFunc = null)
    {
        var item = ObjectPool.Instance.Fetch(
            typeof(EnumerableComponent<TSource, TResult>))
            as EnumerableComponent<TSource, TResult>;
        item._sourceListEnumerator = sourceList.GetEnumerator();
        item._func = checkFunc;
        item._ConvertFunc = convertFunc ?? defaultConvertFunc;
        return item;
    }

    public bool MoveNext()
    {
        while (_sourceListEnumerator.MoveNext())
        {
            var current = _ConvertFunc(_sourceListEnumerator.Current);
            if (_func(current)) return true;
        }
        return false;
    }

    public TResult Current => _ConvertFunc(_sourceListEnumerator.Current);

    public void Dispose()
    {
        Reset();
        ObjectPool.Instance.Recycle(this);
    }
}
```

### 设计亮点详解

#### 1. 自身即枚举器（IEnumerable + IEnumerator 合一）

`EnumerableComponent` 同时实现了 `IEnumerable<TResult>` 和 `IEnumerator<TResult>`，`GetEnumerator()` 返回的是 `this`：

```csharp
public IEnumerator<TResult> GetEnumerator() => this;
```

这是一个**经典的枚举器优化技巧**：避免分配独立的枚举器对象，整个类本身就是迭代状态机。代价是不能多次嵌套迭代同一个实例（单次 `foreach` 模型）。

#### 2. 惰性过滤（Lazy Filter）

```csharp
public bool MoveNext()
{
    while (_sourceListEnumerator.MoveNext())
    {
        var current = _ConvertFunc(_sourceListEnumerator.Current);
        if (_func(current)) return true; // 只要找到一个符合条件的就停
    }
    return false;
}
```

过滤在迭代过程中逐步发生，不会预先构建一个符合条件的子集合，即**不分配额外内存**。这与 LINQ 的 `Where` 原理相同，但 LINQ 每次都会分配迭代器对象，而 EnumerableComponent 走对象池。

#### 3. 默认转换器：`as` 类型转换

```csharp
private static TResult defaultConvert(TSource source) => source as TResult;
```

当 `TSource` 和 `TResult` 有继承关系时（如 `Unit → Enemy`），默认转换器自动处理向下转型，不符合类型的元素会被过滤（`as` 失败返回 `null`，然后被 `_func(null)` 过滤掉）。

---

## 三者协同：实际战斗场景

```csharp
// 场景：查找范围内存活的敌方单位，并对其施加减速

// 1. 收集范围内所有 Unit（含友方）
using var allUnits = ListComponent<Unit>.Create();
_spatialGrid.GetUnitsInRadius(caster.Pos, skillRange, allUnits);

// 2. 用 EnumerableComponent 过滤出存活的敌方 Unit
using var enemyFilter = EnumerableComponent<Unit, Enemy>.Create(
    allUnits,
    enemy => enemy != null && enemy.IsAlive && enemy.TeamId != caster.TeamId
);

// 3. 施加 Buff
foreach (var enemy in enemyFilter)
{
    BuffSystem.Apply(enemy, BuffId.Slow, duration: 2.0f);
}

// 4. 用 Stack 做 DFS 找最近路径（独立逻辑）
using var pathStack = StackComponent<NavNode>.Create();
pathStack.Push(startNode);
while (pathStack.Count > 0)
{
    var node = pathStack.Pop();
    // DFS 逻辑...
}

// using 结束 → 三个组件全部自动归还对象池
```

全程**零堆分配**（池化对象复用），没有任何 `new List`、`new Stack`、`LINQ Where` 产生的垃圾。

---

## 与其他池化集合的对比

| | ListComponent | DictionaryComponent | EnumerableComponent |
|--|--|--|--|
| 继承基类 | `List<T>` | `Dictionary<K,V>` | 无（实现接口） |
| 主要用途 | 临时结果集 | 临时键值映射 | 惰性过滤迭代 |
| 归还协议 | using/Dispose | using/Dispose | using/Dispose |
| 特殊能力 | Sort, BinarySearch | 哈希查找 | 零分配过滤+转换 |

---

## 设计哲学总结

ET 框架这三个组件体现了一套一致的设计哲学：

### 1. **继承标准集合，零学习成本**
不包装，直接继承。`ListComponent<T>` 用起来和 `List<T>` 完全一样，没有 `.Inner`、`.Value` 等间接层。

### 2. **IDisposable 作为生命周期协议**
将"归还到池"的操作语义化为"销毁"，与 C# 的 `using` 语句完美契合，代码意图清晰。

### 3. **静态工厂方法隐藏池细节**
调用方只写 `ListComponent<T>.Create()`，不需要知道背后是 `new` 还是从池取出，池的有无对调用方透明。

### 4. **EnumerableComponent 的惰性设计**
过滤逻辑不预先执行，迭代器自身即枚举器，将 LINQ 风格的链式过滤带入零 GC 的游戏世界。

### 5. **防御性空检查（ObjectPool.Instance == null）**
保证在编辑器测试、离线工具等无框架环境下代码仍可正常运行，测试友好性极高。

掌握这套模式，团队中的高频逻辑即可轻松实现**零临时分配的批量数据处理**，从根本上消除由集合分配引起的 GC 卡顿。
