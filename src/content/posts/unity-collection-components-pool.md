---
title: 集合组件大全——ListComponent、StackComponent 与 EnumerableComponent 的池化设计
published: 2026-03-31
description: 对比分析 ListComponent、StackComponent 和 EnumerableComponent 三种池化集合组件的设计，理解懒加载迭代器模式的零分配遍历思想，以及不同集合类型的适用场景。
tags: [Unity, ECS, 集合设计, 迭代器, GC优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 集合组件大全——ListComponent、StackComponent 与 EnumerableComponent 的池化设计

## 前言

上篇文章分析了 `DictionaryComponent` 的设计模式。今天我们来看其他几个集合组件：`ListComponent`、`StackComponent` 和最复杂的 `EnumerableComponent`。

这几个组件共享相同的设计理念，但 `EnumerableComponent` 有其独特的"懒加载迭代器"设计，值得深入分析。

---

## 一、ListComponent——最常用的集合组件

```csharp
public class ListComponent<T>: List<T>, IDisposable
{
    public static ListComponent<T> Create()
    {
        if(ObjectPool.Instance == null) return new ListComponent<T>();
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

与 `DictionaryComponent` 非常相似，主要区别：

### 1.1 使用非泛型 Fetch

```csharp
ObjectPool.Instance.Fetch(typeof(ListComponent<T>))
```

而不是：

```csharp
ObjectPool.Instance.Fetch<ListComponent<T>>()
```

两种方式等效，只是语法不同。第一种方式直接传入 `Type` 对象，第二种通过泛型推断类型。

`ListComponent` 使用第一种，可能是写法习惯，也可能是为了支持某些特殊情况下 `T` 是运行时类型而非编译时类型的场景。

### 1.2 Dispose 的空值检查

```csharp
public void Dispose()
{
    if (ObjectPool.Instance == null) return; // 池不存在时安全返回
    this.Clear();
    ObjectPool.Instance.Recycle(this);
}
```

与 `DictionaryComponent` 相比，`ListComponent` 在 Dispose 也检查了池是否存在。

这是因为 `ListComponent` 在 `Create` 时就支持无池创建，销毁时自然也要支持无池情况（此时只需让 GC 正常回收即可）。

### 1.3 使用场景

```csharp
// 临时存储一批需要处理的实体
using var entities = ListComponent<Entity>.Create();
foreach (var entity in allEntities)
{
    if (entity.IsActive) entities.Add(entity);
}
foreach (var entity in entities)
{
    ProcessEntity(entity);
}
// 方法返回，entities 自动回收
```

---

## 二、StackComponent——LIFO 临时栈

```csharp
public class StackComponent<T>: Stack<T>, IDisposable
{
    public static StackComponent<T> Create()
    {
        if(ObjectPool.Instance == null) return new StackComponent<T>();
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

`StackComponent` 与 `ListComponent` 的代码几乎完全相同，只是继承自 `Stack<T>` 而非 `List<T>`。

### 2.1 Stack 的适用场景

栈（Stack）适用于"后进先出"（LIFO）的场景：

```csharp
// 场景1：深度优先遍历实体树
using var stack = StackComponent<Entity>.Create();
stack.Push(rootEntity);

while (stack.Count > 0)
{
    var entity = stack.Pop();
    ProcessEntity(entity);
    foreach (var child in entity.Children.Values)
    {
        stack.Push(child);
    }
}

// 场景2：撤销/重做历史记录（临时计算时）
using var undoStack = StackComponent<Command>.Create();
// ... 积累操作
while (undoStack.Count > 0) undoStack.Pop().Undo();
```

---

## 三、HashSetComponent——去重集合

```csharp
public class HashSetComponent<T>: HashSet<T>, IDisposable
{
    public static HashSetComponent<T> Create()
    {
        return ObjectPool.Instance.Fetch(typeof(HashSetComponent<T>)) as HashSetComponent<T>;
    }

    public void Dispose()
    {
        this.Clear();
        ObjectPool.Instance.Recycle(this);
    }
}
```

注意 `HashSetComponent` 没有对象池为空的检查（与 `ListComponent` 不同）：

```csharp
// 直接调用，不检查 Instance 是否为 null
return ObjectPool.Instance.Fetch(typeof(HashSetComponent<T>)) as HashSetComponent<T>;
```

这意味着 `HashSetComponent` 假设对象池必然存在。在 `HashSetComponent` 被使用的上下文（ECS 运行时）中，对象池确实已经初始化了。

**使用场景**：

```csharp
// 临时去重，找出一帧内不重复的伤害目标
using var targets = HashSetComponent<Entity>.Create();
foreach (var attackHit in attackHits)
{
    targets.Add(attackHit.Target); // HashSet 自动去重
}
foreach (var target in targets)
{
    ApplyDamage(target, totalDamage / targets.Count);
}
```

---

## 四、EnumerableComponent——懒加载过滤迭代器

这是本批最复杂的组件，设计思想完全不同：

```csharp
public class EnumerableComponent<TSource, TResult>
    : IEnumerable<TResult>, IEnumerator<TResult>
    where TResult: class
    where TSource: class
{
    public delegate bool CheckHandler(TResult item);      // 过滤条件
    public delegate TResult ConvertHandler(TSource item); // 类型转换
    
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
        var item = ObjectPool.Instance.Fetch(typeof(EnumerableComponent<TSource, TResult>)) 
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
            if (_func(current)) return true; // 找到符合条件的元素
        }
        return false; // 没有更多元素
    }
    
    public TResult Current => _ConvertFunc(_sourceListEnumerator.Current);
    
    public void Dispose()
    {
        Reset();
        ObjectPool.Instance.Recycle(this);
    }
}
```

### 4.1 同时实现 IEnumerable 和 IEnumerator

```csharp
public class EnumerableComponent<TSource, TResult>
    : IEnumerable<TResult>, IEnumerator<TResult>
```

这个组件同时是"可枚举的"（IEnumerable）和"枚举器"（IEnumerator）。

通常这两个接口由不同的对象实现：集合实现 `IEnumerable`，然后 `GetEnumerator()` 返回一个新的枚举器对象（这会产生 GC）。

这里合二为一——同一个对象既是集合又是枚举器，`GetEnumerator()` 返回 `this`，**完全避免了额外的枚举器对象分配**。

### 4.2 懒加载过滤的原理

`EnumerableComponent` 不把符合条件的元素先复制到新 List，而是**在遍历时即时过滤**：

```csharp
public bool MoveNext()
{
    while (_sourceListEnumerator.MoveNext())
    {
        var current = _ConvertFunc(_sourceListEnumerator.Current);
        if (_func(current)) return true; // 找到一个符合条件的
    }
    return false;
}
```

`MoveNext()` 不断推进源迭代器，直到找到符合 `_func` 条件的元素才返回 `true`。

**这就是 LINQ 的 `Where` 的原理——延迟执行（Lazy Evaluation）**。

### 4.3 与 LINQ.Where 的对比

```csharp
// LINQ.Where：创建新的枚举，但不提前过滤
var filtered = entities.Where(e => e.IsActive); // 懒加载，不立即执行

// foreach 时才真正执行过滤
foreach (var entity in filtered) { ... }
```

`EnumerableComponent` 实现了类似的效果，但：
1. 对象通过对象池管理（使用后放回，不被 GC）
2. 支持类型转换（`ConvertHandler`）
3. 可以更精确地控制对象的生命周期

### 4.4 使用示例

```csharp
// 场景：遍历所有活跃的 Player 实体
var allEntities = EntityManager.GetAllEntities();

using var players = EnumerableComponent<Entity, PlayerComponent>.Create(
    allEntities,
    (player) => player != null && player.IsActive, // 过滤条件
    (entity) => entity.GetComponent<PlayerComponent>() // 类型转换
);

foreach (var player in players)
{
    player.UpdateLogic();
}
```

**零 GC 开销**（对象池提供）+ **懒过滤**（不创建临时 List）+ **类型转换**（inline 转换，不分配）。

---

## 五、各集合组件的选择指南

| 需求 | 使用组件 |
|---|---|
| 临时有序列表 | `ListComponent<T>` |
| 临时 LIFO 操作 | `StackComponent<T>` |
| 临时键值对映射 | `DictionaryComponent<T,K>` |
| 临时去重集合 | `HashSetComponent<T>` |
| 过滤+转换遍历（无需中间 List） | `EnumerableComponent<TSource,TResult>` |

---

## 六、集合组件的内存模型

```
对象池 (ObjectPool)
├── List<Entity> 池
│   ├── [空的 ListComponent实例1]
│   └── [空的 ListComponent实例2]
├── Dictionary<int,string> 池
│   └── [空的 DictionaryComponent实例1]
└── ...

运行时：
  Create() → 从池取出 → 使用 → Dispose() → Clear() + 放回池
```

关键：**对象在池中是已清空的状态**（Dispose 时先 Clear）。这确保从池中取出的对象是"干净"的，没有旧数据残留。

---

## 七、写给初学者

这些集合组件体现了 C# 中一个重要的性能优化模式：**用对象池避免临时集合的 GC 压力**。

**什么时候需要这些组件？**

- 在每帧逻辑中创建的临时集合（每帧 `new List<>()` 很快积累 GC）
- 在频繁调用的方法中需要集合（如每次技能计算需要一个命中列表）
- 性能敏感的代码路径（战斗计算、碰撞检测）

**什么时候不需要？**

- 长生命周期的集合（实体数据、全局缓存）—— 这种集合只创建一次，GC 开销可忽略
- 极少调用的代码（初始化、配置加载）—— 即使有 GC，对整体影响也微乎其微

学会识别"高频创建临时对象"的场景，在这些地方使用对象池，是游戏性能优化的重要技能。
