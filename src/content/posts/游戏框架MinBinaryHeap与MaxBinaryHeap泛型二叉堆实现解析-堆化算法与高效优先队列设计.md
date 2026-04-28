---
title: 游戏框架MinBinaryHeap与MaxBinaryHeap泛型二叉堆实现解析-堆化算法与高效优先队列设计
published: 2026-04-28
description: 深入解析xgame框架中的 MinBinaryHeap 和 MaxBinaryHeap 泛型二叉堆实现，涵盖 IBinaryHeap 接口设计、SiftUp/SiftDown 堆化算法、Heapify 批量建堆优化、PushPop/PopPush 复合操作以及有序迭代的副本遍历策略。
tags: [Unity, xgame, 数据结构, 二叉堆, 优先队列, 算法]
category: xgame框架
draft: false
encryptedKey: henhaoji123
---

## 前言

二叉堆是实现**优先队列**的经典数据结构，广泛用于定时器管理、寻路算法（A*）、任务调度等场景。xgame 框架提供了泛型的 `MinBinaryHeap<T>` 和 `MaxBinaryHeap<T>`，并通过 `IBinaryHeap<T>` 接口统一抽象。本文从源码角度深度解析其设计与算法细节。

---

## IBinaryHeap\<T\>：接口设计

```csharp
public interface IBinaryHeap<T> : IEnumerable<T>
{
    int Count { get; }
    bool IsEmpty { get; }
    IComparer<T> Comparer { get; }

    T Peek();                              // 查看堆顶，不移除
    bool TryPeek(out T item);
    T Pop();                               // 移除堆顶
    bool TryPop(out T item);
    void Push(T item);                     // 插入元素
    void PushRange(IEnumerable<T> collection);

    T PushPop(T item);                     // 插入后弹出（优化版）
    T PopPush(T item);                     // 弹出后插入（优化版）

    void Clear();
    void Rebuild();                        // 重建堆结构
    bool Contains(T item);
    bool Contains(Func<T, bool> predicate);
    bool TryGet(Func<T, bool> predicate, out T element);
    bool TryGetAll(Func<T, bool> predicate, out IList<T> elements);
    bool Remove(T item);
    int RemoveAll(Func<T, bool> predicate);
    T[] ToArray();
}
```

接口继承 `IEnumerable<T>`，支持 foreach 有序遍历（从小到大/从大到小）。

---

## 内部存储结构

```csharp
private readonly List<T> _items;
private readonly IComparer<T> _comparer;
```

二叉堆用**数组（List）模拟完全二叉树**，索引关系为：
- 父节点 `i` 的左子节点：`2*i + 1`
- 父节点 `i` 的右子节点：`2*i + 2`
- 子节点 `i` 的父节点：`(i-1) / 2`

这种表示方式无需指针，内存连续，缓存友好。

---

## 建堆：Heapify 批量建堆

```csharp
private void Heapify()
{
    if (_items.Count <= 1) return;

    // 从最后一个非叶子节点向根节点方向依次 SiftDown
    var lastParentWithChildren = (_items.Count - 1) / 2;
    for (var i = lastParentWithChildren; i >= 0; --i)
        SiftDown(i);
}
```

**为什么从中间开始？**

- 叶子节点（索引 > `(n-1)/2`）本身就满足堆属性，无需处理
- 从最后一个非叶子节点开始，逐个执行 SiftDown，时间复杂度为 **O(n)**
- 相比逐一 Push 的 O(n log n)，批量建堆效率更高

---

## 核心算法：SiftUp 与 SiftDown

### SiftUp（上浮）

```csharp
// MinBinaryHeap 版本
private void SiftUp(int start)
{
    var child  = start;
    var parent = (child - 1) / 2;
    while (child > 0)
    {
        // 子节点 >= 父节点（最小堆条件满足），停止
        if (_comparer.Compare(_items[child], _items[parent]) >= 0)
            break;

        Swap(_items, parent, child);
        child  = parent;
        parent = (child - 1) / 2;
    }
}
```

Push 新元素时，将元素放到末尾，然后不断与父节点比较并交换，直到满足堆属性。时间复杂度 **O(log n)**。

### SiftDown（下沉）

```csharp
// MinBinaryHeap 版本
private void SiftDown(int start)
{
    var parent = start;
    var lChild = parent * 2 + 1;
    var rChild = parent * 2 + 2;
    while (lChild < _items.Count)
    {
        var temp = parent;
        // 找出父节点与两个子节点中的最小值
        if (lChild < _items.Count && _comparer.Compare(_items[lChild], _items[temp]) < 0)
            temp = lChild;
        if (rChild < _items.Count && _comparer.Compare(_items[rChild], _items[temp]) < 0)
            temp = rChild;

        if (temp == parent) break;  // 无需交换，堆属性已满足

        Swap(_items, parent, temp);
        parent = temp;
        lChild = parent * 2 + 1;
        rChild = parent * 2 + 2;
    }
}
```

Pop 操作时，将根节点与末尾元素交换，删除末尾（原根），然后从根开始 SiftDown。时间复杂度 **O(log n)**。

---

## 弹出堆顶：RemoveRootNode

```csharp
private T RemoveRootNode()
{
    var head = 0;
    var tail = _items.Count - 1;
    Swap(_items, head, tail);       // 根与末尾交换

    var item = _items[tail];
    _items.RemoveAt(tail);          // 移除末尾（原根）
    SiftDown(head);                 // 从根 SiftDown 恢复堆属性
    return item;
}
```

---

## 复合操作优化：PushPop 与 PopPush

### PushPop（先入后出的快捷版）

```csharp
// MinBinaryHeap
public T PushPop(T item)
{
    var root = _items[0];
    // 如果新元素 <= 堆顶，直接返回新元素（新元素不会改变堆结构）
    if (_comparer.Compare(item, root) <= 0)
        return item;

    // 否则用新元素替换堆顶，SiftDown 恢复堆结构
    _items[0] = item;
    SiftDown(0);
    return root;
}
```

相比先 Push 再 Pop，PushPop 最多执行一次 SiftDown，避免了额外的 SiftUp。

### PopPush（先出后入的快捷版）

```csharp
// MinBinaryHeap
public T PopPush(T item)
{
    var root = _items[0];
    // 如果新元素 <= 堆顶，直接用新元素替换堆顶（不需要 SiftDown）
    if (_comparer.Compare(item, root) <= 0)
    {
        _items[0] = item;
        return root;
    }

    // 否则替换堆顶后 SiftDown
    _items[0] = item;
    SiftDown(0);
    return root;
}
```

---

## PushRange：批量插入

```csharp
public void PushRange(IEnumerable<T> collection)
{
    _items.AddRange(collection);
    Heapify();  // 整体重建，O(n)
}
```

大批量插入时，直接用 `Heapify()` 比逐个 Push 更高效。

---

## Remove 与 RemoveAll：任意元素删除

```csharp
public bool Remove(T item)
{
    var success = _items.Remove(item);
    if (success)
        Heapify();  // 删除后整体重建
    return success;
}

public int RemoveAll(Func<T, bool> predicate)
{
    var num = _items.RemoveAll(x => predicate(x));
    if (num > 0)
        Heapify();
    return num;
}
```

删除任意元素后调用 `Heapify()` 整体重建，时间复杂度 O(n)。虽不如定点删除的 O(log n) 高效，但实现简单且不需要维护位置索引。

---

## 有序遍历：副本迭代策略

```csharp
public IEnumerator<T> GetEnumerator()
{
    // 克隆一个新堆，避免修改源堆
    var clone = new MinBinaryHeap<T>(_items, _comparer);
    while (clone._items.Count > 0)
        yield return clone.RemoveRootNode();
}
```

每次遍历创建副本，有序弹出所有元素（MinBinaryHeap 从小到大，MaxBinaryHeap 从大到小）。这保证了：

1. **源堆不被破坏**
2. **遍历顺序正确**（满足堆序）

代价是额外 O(n) 空间和 O(n log n) 时间。

---

## MinBinaryHeap vs MaxBinaryHeap 对比

| 操作 | MinBinaryHeap | MaxBinaryHeap |
|------|--------------|--------------|
| Peek/Pop | 返回最小值 | 返回最大值 |
| SiftUp 停止条件 | `child >= parent` | `child <= parent` |
| SiftDown 比较方向 | 找最小子节点 | 找最大子节点 |
| PushPop 跳过条件 | `item <= root` | `item >= root` |

两个实现代码结构完全对称，唯一区别是比较器的方向。

---

## 典型使用场景

```csharp
// 定时器系统：最小堆按到期时间排序
var timerHeap = new MinBinaryHeap<TimerTask>(
    Comparer<TimerTask>.Create((a, b) => a.ExpireTime.CompareTo(b.ExpireTime))
);

timerHeap.Push(new TimerTask { ExpireTime = now + 1000 });
timerHeap.Push(new TimerTask { ExpireTime = now + 500  });

// 最近到期的任务优先弹出
var next = timerHeap.Pop();  // ExpireTime = now + 500

// A* 寻路：最小堆按 f(n) 排序
var openSet = new MinBinaryHeap<PathNode>(
    Comparer<PathNode>.Create((a, b) => a.F.CompareTo(b.F))
);
```

---

## 总结

xgame 的二叉堆实现具有以下特点：

1. **泛型 + 比较器**：支持任意类型，灵活定制排序规则
2. **O(n) 批量建堆**：Heapify 从最后非叶子节点向上 SiftDown
3. **复合操作优化**：PushPop/PopPush 减少不必要的 SiftUp/SiftDown
4. **安全迭代**：创建副本遍历，不破坏源堆
5. **接口抽象**：IBinaryHeap 统一最小堆和最大堆 API，方便业务切换
