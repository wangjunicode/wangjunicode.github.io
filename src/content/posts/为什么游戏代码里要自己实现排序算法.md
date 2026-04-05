---
title: 为什么游戏代码里要自己实现排序算法？
published: 2026-03-31
description: 以零分配插入排序为例，探讨游戏代码中算法选型的第一性原理：场景特征驱动算法选择，而非教科书上的渐进复杂度。
tags: [Unity, 算法, 性能优化, 数据结构]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 一个看起来"多此一举"的实现

打开 `InsertionSort.cs`，会看到这样一段代码：

```csharp
public static class InsertionSort
{
    public static void Sort<T, TComparer>(IList<T> list)
        where TComparer : struct, IComparer<T>
    {
        int count = list.Count;
        TComparer comparer = default;

        for (int i = 1; i < count; i++)
        {
            T key = list[i];
            int j = i - 1;

            while (j >= 0 && comparer.Compare(list[j], key) > 0)
            {
                list[j + 1] = list[j];
                j--;
            }

            list[j + 1] = key;
        }
    }
}
```

C# 已经有 `List<T>.Sort()`、`Array.Sort()`，为什么还要自己实现插入排序？

这个问题的答案，揭示了一种非常重要的工程思维：**在特定约束下，"次优"的通用方案往往比"最优"的专用方案差**。

---

## 泛型比较器的零分配技巧

首先注意这个不寻常的泛型约束：

```csharp
public static void Sort<T, TComparer>(IList<T> list)
    where TComparer : struct, IComparer<T>
```

`TComparer` 是 **struct**（结构体），而不是 class。

C# 标准的 `List<T>.Sort(IComparer<T> comparer)` 接受的是 `IComparer<T>` 接口，通常通过传入 class 对象实现：

```csharp
list.Sort(new MyComparer());  // 每次调用都可能分配堆对象
```

但当 `TComparer : struct` 时，编译器会把比较器**内联**到排序代码中：

```csharp
// 调用时
InsertionSort.Sort<HeroInfo, HeroLevelComparer>(heroes);

// 编译器生成的代码等效于（无虚函数调用，无装箱）
// comparer.Compare(a, b) → HeroLevelComparer.Compare(a, b)（直接调用）
```

这消除了虚方法调用的开销，也消除了比较器对象的分配。对于每帧可能调用数百次的排序，这是显著的优化。

---

## 插入排序为什么在小数组上胜过快速排序？

算法课告诉我们：
- 插入排序：O(n²) 平均时间复杂度
- 快速排序：O(n log n) 平均时间复杂度

**但这只适用于大数组！**

对于 n ≤ 16 的小数组，插入排序往往更快，原因有三：

### 1. 内存局部性

插入排序按顺序访问内存（从左到右），CPU 缓存命中率高。快速排序的 Partition 步骤需要从两端向中间访问，缓存友好性差。

### 2. 无递归开销

快速排序是递归的，每次递归调用都有函数栈帧的开销。插入排序只有简单的循环，栈帧开销为零。

### 3. 最优的最佳情况

插入排序对**接近有序**的数组是 O(n)（每个元素只需比较一次）。游戏中的排序数据往往是：上一帧已经排好序，这一帧只有少量变动。在这种情况下，插入排序比快速排序快很多。

### 实验数据（参考）

| 数组大小 | 随机数组 | 接近有序数组 |
|---------|---------|------------|
| n=8 | 插入排序更快 | 插入排序快 5-10x |
| n=16 | 相当 | 插入排序快 3-5x |
| n=32 | 快速排序开始领先 | 插入排序快 2-3x |
| n=1000 | 快速排序明显领先 | 相当 |

---

## 游戏中的典型小数组排序场景

### 场景一：技能优先级排序

```csharp
// 一个角色同时有多少个技能？通常 ≤ 10 个
public struct SkillPriorityComparer : IComparer<Skill>
{
    public int Compare(Skill x, Skill y)
    {
        return y.Priority.CompareTo(x.Priority);  // 降序
    }
}

// 每帧排序：零 GC，O(n) 时间（技能列表几乎不变，接近有序）
InsertionSort.Sort<Skill, SkillPriorityComparer>(hero.Skills);
```

### 场景二：渲染层级排序

```csharp
// 同屏特效通常 ≤ 20 个
public struct EffectRenderOrderComparer : IComparer<Effect>
{
    public int Compare(Effect x, Effect y)
    {
        return x.RenderOrder.CompareTo(y.RenderOrder);
    }
}

InsertionSort.Sort<Effect, EffectRenderOrderComparer>(activeEffects);
```

### 场景三：事件优先级（复习上篇）

回想上一篇的 `EventDispatcher`：

```csharp
// 按优先级插入是线性扫描，本质上也是插入排序的思路
private void InsertBack(List<EventListenerInfo> listeners, EventListenerInfo listener)
{
    for (var i = listeners.Count - 1; i >= 0; i--)
        if (listeners[i].priority >= listener.priority)
        {
            listeners.Insert(i + 1, listener);
            return;
        }
    listeners.Insert(0, listener);
}
```

---

## 与 LINQ OrderBy 的对比

新手常见的"排序"代码：

```csharp
// ❌ 每次调用都分配新数组！
var sorted = heroes.OrderBy(h => h.Level).ToList();

// ❌ 委托分配 + 间接调用
heroes.Sort((a, b) => a.Level.CompareTo(b.Level));
```

`LINQ.OrderBy` 的问题：
1. 返回新的 `IOrderedEnumerable`，调用 `.ToList()` 再次分配
2. Lambda 可能导致委托分配（如果捕获了外部变量）
3. 底层使用的是通用排序（TimSort），对小数组有额外开销

`List<T>.Sort(Comparison<T>)` 的问题：
1. `Comparison<T>` 是委托，每次传入新 Lambda 就有分配

`InsertionSort.Sort<T, TComparer>` 的优势：
1. 零分配（struct 比较器，原地排序）
2. 对小数组和接近有序数组最优
3. 编译器内联比较逻辑，无虚调用

---

## OBBClosestPoint：另一个专用算法

目录里还有 `OBBClosestPoint.cs`（OBB = Oriented Bounding Box，有向包围盒最近点）。这同样体现了"为特定场景实现专用算法"的思路：

Unity 自带的物理查询 API 可以做类似的事，但需要 PhysX 的调用开销。在一些需要纯数学计算（不涉及 Unity 物理系统）的场景，比如帧同步游戏中的碰撞检测，使用纯 C# 实现的算法更可控、更高效。

---

## 何时选择什么排序算法？

```
游戏中的排序场景分析：

数组大小 ≤ 16？
├─ 是 → 插入排序（零分配 struct 比较器版本）
└─ 否 → 继续分析
    │
    数据是否接近有序？
    ├─ 是（大多数游戏数据）→ 插入排序 or TimSort
    └─ 否（完全随机数据）→ 继续分析
        │
        是否在主线程/热路径？
        ├─ 是 → 自定义排序（零分配）
        └─ 否 → List.Sort 或 LINQ.OrderBy 即可
```

---

## 总结

`InsertionSort.cs` 只有 20 行代码，但它背后蕴含了几个重要的工程原则：

1. **渐进复杂度不是唯一指标**：O(n log n) 的算法在小 n 下未必优于 O(n²)
2. **零分配是实时游戏的刚性需求**：struct 泛型比较器是实现零分配排序的关键技巧
3. **利用数据特征**：游戏数据通常接近有序，这正是插入排序的最优场景
4. **内联优化**：struct 约束让编译器内联比较函数，消除虚调用开销

掌握这种"从场景出发选择算法"的思维，是从初级到高级工程师的重要转变。
