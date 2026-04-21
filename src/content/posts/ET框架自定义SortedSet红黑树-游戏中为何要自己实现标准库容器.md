---
title: "ET框架自定义SortedSet红黑树：游戏中为何要自己实现标准库容器"
published: 2026-04-21
description: "深入解析ET游戏框架为何在C#标准库之外自行实现SortedSet与SortedDictionary，探讨红黑树在游戏中的应用场景、枚举器缓存防GC设计，以及帧同步场景下确定性有序容器的工程价值。"
image: ""
tags: ["Unity", "数据结构", "游戏框架", "ET框架", "源码解析", "红黑树"]
category: "Unity游戏开发"
draft: false
encryptedKey: "henhaoji123"
---

## 前言

翻开ET框架的 `Core` 目录，会发现一个有趣的现象：`SortedSet.cs` 和 `SortedDictionary.cs` 中实现的，正是 C# 标准库 `System.Collections.Generic` 里同名的容器。

**为什么要重新实现一遍标准库已经提供的东西？**

这背后有三个层面的工程考量：Unity版本兼容性、GC控制、以及帧同步场景的确定性需求。本文将从源码出发，逐一拆解。

---

## 一、红黑树是什么，为何游戏需要它

`SortedSet<T>` 的底层是**红黑树（Red-Black Tree）**，一种自平衡二叉搜索树。它保证以下性质：

1. 每个节点是红色或黑色
2. 根节点是黑色
3. 红色节点的两个子节点必须是黑色（不能连续红色）
4. 从任一节点到叶节点的所有路径包含相同数量的黑色节点

这些约束保证树的高度始终在 `O(log n)` 级别，增删查均为 `O(log n)`。

### 游戏中的典型应用

| 应用场景 | 为何需要有序集合 |
|---------|----------------|
| 技能冷却队列 | 按触发时间排序，每帧只检查队首 |
| 帧同步定时器 | 按逻辑帧数排序，确保触发顺序确定 |
| AOI兴趣区域 | 按坐标排序快速范围查询 |
| 优先级队列 | O(log n)的入队出队，优于List+Sort |
| 仇恨值排名 | 实时维护有序仇恨列表 |

---

## 二、源码结构概览

ET框架的 `SortedSet.cs` 完整移植了 .NET 运行时源码，并做了关键修改：

```
SortedSet<T>（红黑树核心实现）
    └── TreeSet<T> : SortedSet<T>（禁止重复元素的特化版，SortedDictionary 内部使用）

SortedDictionary<TKey, TValue>
    └── 内部持有 TreeSet<KeyValuePair<TKey,TValue>>
    └── 通过 KeyValuePairComparer 实现"按 Key 排序，Value 可重复"

IReadOnlySet<T>（接口补丁，解决 Unity 旧版本缺失问题）
```

### 为什么引入 `IReadOnlySet<T>`？

```csharp
//#if UNITY
public interface IReadOnlySet<T> : IReadOnlyCollection<T>
{
    bool Contains(T item);
    bool IsProperSubsetOf(IEnumerable<T> other);
    // ...
}
//#endif
```

`IReadOnlySet<T>` 是 .NET 5 引入的接口，Unity 的部分 .NET Standard 2.1 实现**未完整包含它**。ET框架通过在 `ET` 命名空间内重新声明这个接口，使代码在 Unity 旧版本下也能编译通过。

---

## 三、关键设计：枚举器缓存防GC

这是ET框架魔改中最值得关注的一处：

```csharp
// SortedSet 中缓存 Stack（原版 .NET 没有这行！）
private Stack<Node> stack;
```

```csharp
internal Enumerator(SortedSet<T> set, bool reverse)
{
    _tree = set;
    set.VersionCheck();
    _version = set.version;

    // 🔑 关键修改：从 set 上拿缓存的 Stack，而不是每次 new
    lock (this._tree)
    {
        if (set.stack != null)
        {
            _stack = set.stack;
            set.stack = null;   // 转移所有权，防止并发复用
        }
        else
        {
            _stack = new Stack<Node>(2 * Log2(count) + 2);
        }
    }
}
```

### 原版 .NET 的问题

标准库的 `SortedSet<T>.Enumerator` 每次 `GetEnumerator()` 都会 `new Stack<Node>(...)`。在游戏中，对一个含 1000 个元素的技能冷却队列每帧遍历，就是每帧一次 `Stack` 的堆分配，直接触发 GC。

### ET框架的解决方案

1. `SortedSet` 持有一个 `Stack<Node> stack` 字段作为**缓存槽**
2. 枚举器构造时，先尝试**夺取**集合上缓存的 Stack（`set.stack = null`）
3. 枚举结束时（`Dispose`），**归还** Stack（`_tree.stack = _stack`）

```csharp
public void Dispose()
{
    _stack.Clear();
    lock (_tree)
    {
        if (_tree.stack == null)
            _tree.stack = _stack; // 归还缓存
    }
    _current = null;
}
```

这样，**同一个 SortedSet 反复遍历不会产生 GC 分配**——只要不同时存在两个枚举器。

---

## 四、TreeSet 与 SortedDictionary 的关系

```csharp
// SortedDictionary 内部
private readonly TreeSet<KeyValuePair<TKey, TValue>> _set;
```

`TreeSet` 是 `SortedSet` 的特化版：它**在插入重复元素时抛异常**，而不是静默忽略：

```csharp
public sealed class TreeSet<T> : SortedSet<T>
{
    internal override bool AddIfNotPresent(T item)
    {
        bool ret = base.AddIfNotPresent(item);
        if (!ret)
        {
            // SortedSet 返回 false 表示元素已存在（静默失败）
            // TreeSet 则直接抛异常——Dictionary 不允许 Key 重复！
            throw new ArgumentException($"SR.Argument_AddingDuplicate, {item}");
        }
        return ret;
    }
}
```

`SortedDictionary` 使用 `KeyValuePairComparer` 包装比较器，让红黑树只用 `Key` 排序：

```csharp
public sealed class KeyValuePairComparer : Comparer<KeyValuePair<TKey, TValue>>
{
    internal IComparer<TKey> keyComparer;

    public override int Compare(
        KeyValuePair<TKey, TValue> x, 
        KeyValuePair<TKey, TValue> y)
    {
        return keyComparer.Compare(x.Key, y.Key); // 只比较 Key
    }
}
```

---

## 五、红黑树核心操作图解

### 插入操作

```
插入 42 到有序集合 [10, 20, 30, 40, 50]:

        30(B)
       /     \
    20(B)   40(B)
    /         \
 10(R)        50(R)

插入 42：找到位置，父节点 50(R) 是红色
→ 触发旋转修复
→ 最终保持红黑性质
```

ET框架中 `AddIfNotPresent` 是核心插入逻辑，包含完整的 4-节点分裂和旋转平衡：

```csharp
// 分裂 4-节点（同时拥有红色左右子节点）
if (current.Is4Node)  
{
    current.Split4Node();
    if (Node.IsNonNullRed(parent))
    {
        InsertionBalance(current, ref parent, grandParent, greatGrandParent);
    }
}
```

### 四种旋转操作

```csharp
public enum TreeRotation : byte
{
    Left,       // 左旋
    LeftRight,  // 先左旋再右旋（双旋）
    Right,      // 右旋
    RightLeft,  // 先右旋再左旋（双旋）
}
```

单旋时间复杂度 O(1)，只是指针重连，不影响整体 O(log n) 复杂度。

---

## 六、帧同步场景的确定性保证

帧同步游戏要求**相同输入产生完全相同输出**，这对容器有严苛要求：

### 问题：System.Collections.Generic 的哈希不确定性

C# 的 `Dictionary<K,V>` 和 `HashSet<T>` 依赖 `GetHashCode()`，而在不同平台、不同 .NET 版本，字符串和对象的哈希值可能**不同**。这会导致枚举顺序不一致，帧同步逻辑产生分歧。

### ET框架的解法

`SortedSet` 基于**比较器**（`IComparer<T>`）而非哈希，只要比较器是确定性的（如整数大小、字符串字典序），枚举顺序在所有平台上**完全相同**。

因此在战斗系统中，所有需要确定性枚举的集合都应使用：

```csharp
// ✅ 确定性有序：帧同步安全
var unitIds = new SortedSet<long>(); // 按 long 值排序，跨平台一致

// ❌ 非确定性：帧同步危险
var unitIds = new HashSet<long>(); // 枚举顺序不保证
```

---

## 七、GetViewBetween：范围视图的工程价值

```csharp
public virtual SortedSet<T> GetViewBetween(T lowerValue, T upperValue)
{
    return new TreeSubSet(this, lowerValue, upperValue, true, true);
}
```

`GetViewBetween` 返回一个**范围视图**（不复制数据），可以高效地查询某个区间内的所有元素。

**AOI系统应用示例：**

```csharp
// 假设用 SortedSet 存储所有单位的 X 坐标
var unitsByX = new SortedSet<(float x, long unitId)>(
    Comparer<(float, long)>.Create((a, b) => a.x.CompareTo(b.x)));

// 查询 playerX ± 50 范围内的单位——O(log n + k)，k 为结果数量
var nearbyUnits = unitsByX.GetViewBetween(
    (playerX - 50f, long.MinValue),
    (playerX + 50f, long.MaxValue));

foreach (var (x, unitId) in nearbyUnits)
{
    // 处理附近单位
}
```

相比 `List.FindAll` 的 O(n) 线性扫描，`GetViewBetween` 利用红黑树结构跳过不在范围内的节点，在单位数量大时性能优势显著。

---

## 八、性能基准对比

在典型游戏场景下，不同容器的操作复杂度：

| 操作 | List\<T\> | SortedList\<K,V\> | SortedSet\<T\> |
|------|-----------|-------------------|----------------|
| 插入 | O(n) | O(n) | **O(log n)** |
| 删除 | O(n) | O(n) | **O(log n)** |
| 查找 | O(n) | O(log n) | **O(log n)** |
| 范围查询 | O(n) | O(log n + k) | **O(log n + k)** |
| 有序遍历 | O(n log n)* | O(n) | O(n) |
| 内存 | 连续 | 连续 | 离散（节点） |

*List 遍历前需要 Sort

**结论：** 当集合需要**频繁插删 + 有序遍历 + 范围查询**时，`SortedSet` 是最合适的选择；当只需有序遍历、很少插删时，`SortedList` 因内存连续性（缓存友好）更优。

---

## 九、ET框架中的实际应用

### TimerComponent 的定时器排序

```csharp
// 定时器系统内部（推测实现）
// 按触发时间排序的定时器队列
private SortedDictionary<long, List<TimerEntry>> timers;

// 每帧只需检查队首（最近触发时间）
long now = TimeHelper.ClientNow();
while (timers.Count > 0 && timers.Keys.Min <= now)
{
    // 触发定时器
}
```

### CoroutineLock 的等待队列

协程锁内部为每个锁类型维护一个有序等待队列，保证协程按优先级顺序获得锁，而不是随机的哈希顺序。

---

## 总结

ET框架重新实现 `SortedSet` 和 `SortedDictionary` 并非多此一举，背后有清晰的工程动机：

1. **GC控制**：枚举器缓存 Stack，消除每次 `foreach` 产生的堆分配
2. **版本兼容**：补充 `IReadOnlySet<T>` 接口，解决 Unity 旧版本编译问题
3. **帧同步安全**：基于比较器的确定性排序，避免哈希不确定性导致的帧同步分歧
4. **范围查询**：`GetViewBetween` 支持 O(log n + k) 的高效范围视图，AOI等系统必备

当你在游戏框架中遇到"需要有序且频繁增删"的场景，优先考虑 `SortedSet` 而非 `List+Sort`——这不仅是性能上的选择，更是**正确性**上的选择，尤其在帧同步场景中。
