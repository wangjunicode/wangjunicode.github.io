---
title: ET框架自定义SortedDictionary深度解析-红黑树驱动的有序字典与视图切片架构
published: 2026-04-22
description: 深入分析ET游戏框架中自定义SortedDictionary的完整实现，揭秘其底层红黑树TreeSet结构、KeyValuePairComparer策略、KeyCollection/ValueCollection视图设计以及与标准库SortedSet协作的架构哲学。
tags: [Unity, CSharp, 游戏框架, 数据结构, 红黑树, ET框架]
category: 游戏开发
draft: false
encryptedKey: henhaoji123
---

# ET框架自定义SortedDictionary深度解析

## 为什么不直接用 `System.Collections.Generic.SortedDictionary<TKey,TValue>`？

在 ET 游戏框架的 Core 模块中存在一个 `SortedDictionary.cs`，它并不是一个简单的包装，而是**从头移植的完整实现**。原因有三：

1. **Unity 旧版 .NET 运行时缺少部分 API**（如 `IReadOnlyDictionary` 的完整支持），自行实现可精确控制接口版本。
2. **与框架内 `SortedSet<T>` 共享底层 TreeSet**，方便统一 GC 策略和调试工具。
3. **热更新友好**：框架自有类可在 HybridCLR 热更代码中自由扩展，而系统类在 AOT 端存在泛型约束。

---

## 整体架构一览

```
SortedDictionary<TKey, TValue>
│
├── _set : TreeSet<KeyValuePair<TKey,TValue>>   ← 核心红黑树
│     └── Comparer : KeyValuePairComparer       ← 只比 Key
│
├── KeyCollection   ← 键视图（共享 _set，不额外分配）
└── ValueCollection ← 值视图（共享 _set，不额外分配）
```

整个字典只有 **一棵红黑树**，不存在另一张哈希表。所有操作时间复杂度均为 O(log N)。

---

## 核心：KeyValuePairComparer

```csharp
private sealed class KeyValuePairComparer : IComparer<KeyValuePair<TKey, TValue>>
{
    internal readonly IComparer<TKey> keyComparer;

    public KeyValuePairComparer(IComparer<TKey> keyComparer)
    {
        this.keyComparer = keyComparer ?? Comparer<TKey>.Default;
    }

    public int Compare(KeyValuePair<TKey, TValue> x, KeyValuePair<TKey, TValue> y)
    {
        return keyComparer.Compare(x.Key, y.Key);
    }
}
```

**设计精髓**：将 `KeyValuePair<TKey,TValue>` 整体作为 TreeSet 的元素，但**排序只看 Key**，Value 对树的结构完全透明。这样字典的查找、插入、删除都可以直接复用 SortedSet 的红黑树算法，代码复用率极高。

**查找时的妙用**：

```csharp
public bool TryGetValue(TKey key, out TValue value)
{
    // 构造一个 dummy pair，Value 可以是任意值
    SortedSet<KeyValuePair<TKey, TValue>>.Node node =
        _set.FindNode(new KeyValuePair<TKey, TValue>(key, default));
    if (node == null)
    {
        value = default;
        return false;
    }
    value = node.Item.Value;
    return true;
}
```

用一个带 `default` Value 的临时 `KeyValuePair` 做查找键，比较器只看 Key，所以能准确定位到目标节点，再取出真正的 Value。

---

## 构造函数的优化路径

```csharp
public SortedDictionary(IDictionary<TKey, TValue> dictionary, IComparer<TKey> comparer)
{
    var keyValuePairComparer = new KeyValuePairComparer(comparer);

    if (dictionary is SortedDictionary<TKey, TValue> sortedDictionary &&
        sortedDictionary._set.Comparer is KeyValuePairComparer kv &&
        kv.keyComparer.Equals(keyValuePairComparer.keyComparer))
    {
        // 快速路径：相同比较器的 SortedDictionary 可以直接深拷贝红黑树
        _set = new TreeSet<KeyValuePair<TKey, TValue>>(sortedDictionary._set, keyValuePairComparer);
    }
    else
    {
        // 通用路径：逐条插入
        _set = new TreeSet<KeyValuePair<TKey, TValue>>(keyValuePairComparer);
        foreach (KeyValuePair<TKey, TValue> pair in dictionary)
            _set.Add(pair);
    }
}
```

**快速路径的意义**：当从同比较器的 SortedDictionary 复制时，直接克隆红黑树结构（O(N)），跳过了 N 次 O(log N) 的重新插入，总体从 O(N log N) 降至 O(N)。

---

## 索引器的实现

```csharp
public TValue this[TKey key]
{
    get
    {
        SortedSet<KeyValuePair<TKey, TValue>>.Node node =
            _set.FindNode(new KeyValuePair<TKey, TValue>(key, default));
        if (node == null)
            throw new KeyNotFoundException();
        return node.Item.Value;
    }
    set
    {
        // FindNode 找到则修改，否则插入
        SortedSet<KeyValuePair<TKey, TValue>>.Node node =
            _set.FindNode(new KeyValuePair<TKey, TValue>(key, default));
        if (node != null)
        {
            node.Item = new KeyValuePair<TKey, TValue>(key, value);
            _set.UpdateVersion(); // 使迭代器失效
        }
        else
        {
            _set.Add(new KeyValuePair<TKey, TValue>(key, value));
        }
    }
}
```

**就地修改（in-place update）**：当 Key 已存在时，不删除旧节点再插入，而是直接修改节点的 Item 字段，调用 `UpdateVersion()` 通知迭代器树结构已更新。这避免了一次删除+插入的开销（两次树旋转），代价是一次 O(log N) 的 FindNode。

---

## 视图集合的零分配设计

### KeyCollection

```csharp
public sealed class KeyCollection : ICollection<TKey>, ICollection, IReadOnlyCollection<TKey>
{
    private readonly SortedDictionary<TKey, TValue> _dictionary;

    public KeyCollection(SortedDictionary<TKey, TValue> dictionary)
    {
        _dictionary = dictionary;
    }

    public Enumerator GetEnumerator() => new Enumerator(_dictionary);
    
    // ...
    
    public struct Enumerator : IEnumerator<TKey>, IEnumerator
    {
        private SortedDictionary<TKey, TValue>.Enumerator _dictEnum;

        internal Enumerator(SortedDictionary<TKey, TValue> dictionary)
        {
            _dictEnum = dictionary.GetEnumerator();
        }

        public TKey Current => _dictEnum.Current.Key;
    }
}
```

**关键点**：
- `KeyCollection` 不持有任何集合数据，只持有字典的引用。
- 它的迭代器直接复用字典的迭代器，每次 `Current` 取出 `.Key` 字段。
- 对 `dict.Keys` 的 `foreach` 不会分配新集合，只分配一个栈上的迭代器结构体。

```csharp
// 属性是懒加载的，反复访问不重复创建
public KeyCollection Keys => _keys ??= new KeyCollection(this);
```

---

## 字典迭代器：从 TreeSet 到 KeyValuePair 的转换层

```csharp
public struct Enumerator : IEnumerator<KeyValuePair<TKey, TValue>>, IDictionaryEnumerator
{
    private readonly SortedDictionary<TKey, TValue> _dictionary;
    private SortedSet<KeyValuePair<TKey, TValue>>.Enumerator _treeEnum;
    private readonly int _getEnumeratorRetType; // 1=KeyValuePair, 2=DictionaryEntry

    internal Enumerator(SortedDictionary<TKey, TValue> dictionary, int getEnumeratorRetType)
    {
        _dictionary = dictionary;
        _treeEnum = dictionary._set.GetEnumerator();
        _getEnumeratorRetType = getEnumeratorRetType;
    }

    public KeyValuePair<TKey, TValue> Current => _treeEnum.Current;

    // IDictionaryEnumerator 要求 Entry 属性
    DictionaryEntry IDictionaryEnumerator.Entry
    {
        get
        {
            if (_getEnumeratorRetType == DictEntry)
                return new DictionaryEntry(_treeEnum.Current.Key, _treeEnum.Current.Value);
            throw new InvalidOperationException();
        }
    }
}
```

字典的迭代器是 TreeSet 迭代器的**薄包装层**，额外处理了旧式 `IDictionaryEnumerator` 接口（用于 `foreach` 在非泛型 `IDictionary` 上的兼容）。

---

## SortedDictionary 与 SortedSet 的关系图

```
SortedSet<T>                   SortedDictionary<TKey, TValue>
    │                                     │
    │  实现                        _set 字段  │
    ▼                                     ▼
TreeSet<T> ◄─────────────── TreeSet<KeyValuePair<TKey,TValue>>
    │                                     │
    └── 红黑树节点 Node                    └── 同一套红黑树算法
         Item: T                               Item: KeyValuePair<TKey,TValue>
```

`TreeSet` 是 `SortedSet` 的内部类，框架将其提取出来作为 `SortedDictionary` 的存储引擎。两个高层容器共享同一套经过验证的红黑树旋转逻辑，维护成本大幅降低。

---

## 游戏开发中的典型使用场景

### 场景一：定时器优先队列

```csharp
// 用 SortedDictionary 维护下一次触发时间 → 定时器列表的映射
private SortedDictionary<long, List<Timer>> _timerMap = new();

public void AddTimer(long triggerTime, Timer timer)
{
    if (!_timerMap.TryGetValue(triggerTime, out var list))
    {
        list = new List<Timer>();
        _timerMap[triggerTime] = list;
    }
    list.Add(timer);
}

public void Tick(long now)
{
    // 只需遍历 Key <= now 的部分
    foreach (var kv in _timerMap)
    {
        if (kv.Key > now) break; // 有序！首个超时即可停止
        foreach (var timer in kv.Value)
            timer.Fire();
    }
}
```

### 场景二：技能优先级队列

```csharp
// 技能优先级 → 技能列表，SortedDictionary 保证按优先级从小到大迭代
private SortedDictionary<int, SkillInfo> _skillPriorityMap = new();
```

### 场景三：排行榜区间查询

```csharp
// 利用 GetViewBetween 获取指定分数区间的玩家
var rankRange = _rankDict.GetViewBetween(minScore, maxScore);
```

---

## 性能特性对比

| 操作 | SortedDictionary | Dictionary | 说明 |
|------|-----------------|------------|------|
| 查找 | O(log N) | O(1) | 树查找 vs 哈希 |
| 插入 | O(log N) | O(1)摊还 | 树插入+可能旋转 |
| 删除 | O(log N) | O(1)摊还 | 同上 |
| Min/Max | O(log N) | O(N) | 沿树左/右臂下降 |
| 有序遍历 | O(N) | O(N log N) | 中序遍历 vs 排序 |
| 内存 | 3指针/元素 | 约1格/元素 | 左右子+父指针 |

当需要**频繁有序遍历**或**Min/Max查询**时，SortedDictionary 有明显优势；纯随机查找则 Dictionary 更快。

---

## 总结

ET 框架自定义的 `SortedDictionary` 在以下几个设计层面颇具工程价值：

1. **KeyValuePairComparer 策略模式**：将 Key 的排序逻辑封装为独立比较器，与红黑树解耦，支持自定义 Key 顺序。
2. **原地更新（in-place update）**：Value 更新直接修改节点，不走删除+插入，节省旋转开销。
3. **零分配视图集合**：Keys/Values 不复制数据，迭代器复用 TreeSet 迭代器，几乎零额外 GC。
4. **与 SortedSet 同根同源**：共享红黑树核心代码，一处 Bug 修复全局受益。
5. **从相同比较器字典的 O(N) 拷贝**：构造快速路径直接克隆树结构，避免重新平衡。

这种"借壳红黑树"的设计模式，是 ET 框架在保持代码精简的同时提供完整有序容器功能的典型手法，值得在自研框架中借鉴。
