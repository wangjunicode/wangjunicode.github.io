---
title: 游戏框架中二叉堆数据结构的设计与实现MinBinaryHeap与MaxBinaryHeap深度解析
published: 2026-04-13
description: 深入剖析ET框架中二叉堆（BinaryHeap）的接口设计与双堆实现，详解SiftUp/SiftDown堆化算法、O(n)建堆优化、PushPop/PopPush原子操作，以及在游戏定时器、优先级队列等场景中的应用。
tags: [Unity, 数据结构, 二叉堆, 优先队列, ET框架, 算法]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 概述

在游戏框架中，定时器系统、技能优先级队列、寻路开放列表等场景都需要高效的优先队列支持。ET框架在 `Core/BinaryHeap/` 目录下实现了完整的二叉堆体系，包含 `IBinaryHeap<T>` 接口、`MinBinaryHeap<T>`（最小堆）和 `MaxBinaryHeap<T>`（最大堆）。本文将从接口设计到算法实现逐层拆解，并结合游戏开发中的典型用例说明其工程价值。

---

## 一、IBinaryHeap 接口设计

```csharp
public interface IBinaryHeap<T> : IEnumerable<T>
{
    int Count { get; }
    bool IsEmpty { get; }
    IComparer<T> Comparer { get; }

    T Peek();
    bool TryPeek(out T item);
    T Pop();
    bool TryPop(out T item);
    void Push(T item);
    void PushRange(IEnumerable<T> collection);
    T PushPop(T item);   // 先Push再Pop（原子操作，避免无效堆化）
    T PopPush(T item);   // 先Pop再Push（原子操作）

    void Clear();
    void Rebuild();
    bool Contains(T item);
    bool Contains(Func<T, bool> predicate);
    bool TryGet(Func<T, bool> predicate, out T element);
    bool TryGetAll(Func<T, bool> predicate, out IList<T> elements);
    bool Remove(T item);
    int RemoveAll(Func<T, bool> predicate);
    T[] ToArray();
}
```

### 设计亮点

| 特性 | 说明 |
|------|------|
| `IEnumerable<T>` 继承 | 支持有序遍历（通过克隆堆逐步Pop实现） |
| `TryXxx` 方法族 | 防止在空堆上操作抛出异常，更安全 |
| `PushPop` / `PopPush` | 原子操作，比分开调用效率更高 |
| `IComparer<T>` 注入 | 支持自定义排序，灵活应对复杂对象 |
| `Rebuild()` | 外部修改元素后可重建堆，支持可变优先级 |

---

## 二、最小堆（MinBinaryHeap）实现

### 2.1 内部结构

```csharp
public class MinBinaryHeap<T> : IBinaryHeap<T>
{
    private readonly List<T> _items;          // 底层线性存储
    private readonly IComparer<T> _comparer;  // 比较器

    // 父子节点索引关系（0-based）：
    // parent(i) = (i - 1) / 2
    // lChild(i) = i * 2 + 1
    // rChild(i) = i * 2 + 2
}
```

ET 框架选择 `List<T>` 而非数组，优势在于动态扩容无需手动管理容量，且 `RemoveAt` 末尾操作为 O(1)。

### 2.2 SiftUp —— 向上堆化

```csharp
private void SiftUp(int start)
{
    var child  = start;
    var parent = (child - 1) / 2;

    while (child > 0)
    {
        // 子节点 >= 父节点：最小堆性质已满足，停止
        if (_comparer.Compare(_items[child], _items[parent]) >= 0)
            break;

        Swap(_items, parent, child);
        child  = parent;
        parent = (child - 1) / 2;
    }
}
```

**时间复杂度：O(log n)**，每次 Push 后调用一次，将新元素上浮到合适位置。

### 2.3 SiftDown —— 向下堆化

```csharp
private void SiftDown(int start)
{
    var parent = start;
    var lChild = parent * 2 + 1;
    var rChild = parent * 2 + 2;

    while (lChild < _items.Count)
    {
        var temp = parent;
        // 找到父节点与两子节点中最小的
        if (lChild < _items.Count && _comparer.Compare(_items[lChild], _items[temp]) < 0)
            temp = lChild;
        if (rChild < _items.Count && _comparer.Compare(_items[rChild], _items[temp]) < 0)
            temp = rChild;

        if (temp == parent) break;  // 无需交换，终止

        Swap(_items, parent, temp);
        parent = temp;
        lChild = parent * 2 + 1;
        rChild = parent * 2 + 2;
    }
}
```

**时间复杂度：O(log n)**，Pop 根节点后将末尾元素置于根并向下调整。

### 2.4 O(n) 建堆优化（Heapify）

```csharp
private void Heapify()
{
    if (_items.Count <= 1) return;

    // 从最后一个有子节点的父节点开始，向上执行 SiftDown
    var lastParentWithChildren = (_items.Count - 1) / 2;
    for (var i = lastParentWithChildren; i >= 0; --i)
        SiftDown(i);
}
```

这是经典的 Floyd 建堆算法，时间复杂度 **O(n)**，远优于逐个 Push 的 **O(n log n)**。

**原理：** 叶节点无需调整，只需对一半节点执行 SiftDown，叶层节点数是内部节点数的约 2 倍，整体收敛到 O(n)。

---

## 三、PushPop 与 PopPush 原子优化

### 3.1 PushPop

```csharp
public T PushPop(T item)
{
    var root = _items[0];
    // 新元素比堆顶还小：直接返回，不需要进堆
    if (_comparer.Compare(item, root) <= 0)
        return item;

    // 替换堆顶并向下调整
    _items[0] = item;
    SiftDown(0);
    return root;
}
```

**典型场景：** 维护 Top-K 最大值时，每次用新元素替换堆中最小值。

### 3.2 PopPush

```csharp
public T PopPush(T item)
{
    var root = _items[0];
    if (_comparer.Compare(item, root) <= 0)
    {
        _items[0] = item;
        return root;
    }
    _items[0] = item;
    SiftDown(0);
    return root;
}
```

两者都避免了"先 Pop → 再 Push → 触发两次堆化"的冗余操作，性能提升约 50%。

---

## 四、有序遍历实现

```csharp
public IEnumerator<T> GetEnumerator()
{
    // 克隆堆，避免破坏原始数据
    var clone = new MinBinaryHeap<T>(_items, _comparer);
    while (clone._items.Count > 0)
        yield return clone.RemoveRootNode();
}
```

**注意：** 遍历时克隆整个堆，时间复杂度 O(n log n)，空间复杂度 O(n)。若只需访问堆顶，直接用 `Peek()` 即可，成本 O(1)。

---

## 五、MaxBinaryHeap 与 MinBinaryHeap 的区别

两者代码几乎对称，唯一差异在比较方向：

| 操作 | MinBinaryHeap | MaxBinaryHeap |
|------|---------------|---------------|
| SiftUp 终止条件 | `child >= parent` | `child <= parent` |
| SiftDown 选取方向 | 选最小子节点 | 选最大子节点 |
| PushPop 快速路径 | `item <= root` 直接返回 | `item >= root` 直接返回 |

ET 框架没有通过"翻转比较器"的 Hack 方式实现最大堆，而是保持两份清晰独立的实现，可读性更好。

---

## 六、游戏场景应用示例

### 6.1 帧定时器（最小堆）

```csharp
// 按触发时间排序的定时器堆
var timerHeap = new MinBinaryHeap<TimerTask>(Comparer<TimerTask>.Create(
    (a, b) => a.TriggerTime.CompareTo(b.TriggerTime)
));

timerHeap.Push(new TimerTask { TriggerTime = now + 1000 });
timerHeap.Push(new TimerTask { TriggerTime = now + 500 });

// 每帧检查堆顶，时间到则弹出执行
while (timerHeap.TryPeek(out var task) && task.TriggerTime <= now)
{
    timerHeap.Pop();
    task.Execute();
}
```

### 6.2 A* 开放列表（最小堆）

```csharp
var openList = new MinBinaryHeap<PathNode>(Comparer<PathNode>.Create(
    (a, b) => a.F.CompareTo(b.F)  // F = G + H
));

openList.Push(startNode);
while (!openList.IsEmpty)
{
    var current = openList.Pop();
    if (current == targetNode) break;
    // 展开邻居...
    openList.Push(neighbor);
}
```

### 6.3 Top-K 排行榜（最小堆维护）

```csharp
// 维护得分最高的 K 名玩家
var topK = new MinBinaryHeap<PlayerScore>();
foreach (var score in allScores)
{
    if (topK.Count < K)
        topK.Push(score);
    else
        topK.PushPop(score);  // 自动淘汰最低分（原子操作）
}
```

---

## 七、性能特性总结

| 操作 | 时间复杂度 |
|------|-----------|
| Push | O(log n) |
| Pop | O(log n) |
| Peek | O(1) |
| PushPop / PopPush | O(log n)，常数更小 |
| Heapify（批量建堆） | O(n) |
| Contains | O(n) |
| Remove（任意元素） | O(n)，需全堆重建 |
| 有序遍历 | O(n log n) |

---

## 八、总结

ET框架的二叉堆实现体现了以下工程思想：

1. **接口与实现分离**：`IBinaryHeap<T>` 定义约定，便于替换实现（如 Fibonacci Heap）
2. **原子操作优化**：`PushPop`/`PopPush` 减少堆化次数，对高频定时器场景意义重大
3. **O(n) 建堆**：批量初始化时远优于逐个 Push，适合大量数据初始化场景
4. **安全优先**：Try 系列方法防止空堆异常，适合多状态的游戏逻辑
5. **克隆遍历**：遍历时不破坏原始堆，保证游戏逻辑安全

掌握堆数据结构不仅有助于理解定时器系统的底层实现，也是游戏开发中处理优先级问题的核心工具之一。
