---
title: 确定性字典：为帧同步游戏设计的有序集合容器
published: 2026-03-31
description: 深入解析结合 List 和 Dictionary 实现确定性遍历顺序的复合集合，理解帧同步游戏中为什么集合的遍历顺序至关重要。
tags: [Unity, 数据结构, 帧同步, 集合设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么普通字典会导致帧同步 Bug？

帧同步游戏（比如 RTS、MOBA）有一个铁律：**所有客户端必须在相同帧执行完全相同的操作，产生完全相同的结果**。

`Dictionary<TKey, TValue>` 是 C# 中最常用的集合，但它有一个致命问题：**遍历顺序不确定**。

```csharp
var dict = new Dictionary<string, int>
{
    ["hero"] = 1,
    ["enemy"] = 2,
    ["npc"] = 3
};

// 在不同 .NET 版本、不同平台，foreach 的顺序可能不同！
foreach (var kv in dict)
{
    // 顺序：hero→enemy→npc? 还是 enemy→hero→npc?
    ApplyEffect(kv.Key, kv.Value);
}
```

假设 A 客户端遍历顺序是 `hero, enemy, npc`，B 客户端是 `enemy, hero, npc`，而 `ApplyEffect` 会修改游戏状态——两台机器执行后的结果就不同了，帧同步出现 desync。

`DeterministicDictionary` 就是为解决这个问题而生的。

---

## DeterministicDictionary 的设计

### 核心结构

```csharp
public sealed class DeterministicDictionary<TKey, TValue>
    : IEnumerable<KeyValuePair<TKey, TValue>>
{
    private readonly List<TKey> _orderedKeys;         // 维护插入顺序
    private readonly Dictionary<TKey, TValue> _map;  // 提供 O(1) 查找

    public DeterministicDictionary(int capacity = 128)
    {
        _orderedKeys = new List<TKey>(capacity);
        _map = new Dictionary<TKey, TValue>(capacity);
    }
```

**复合结构**：
- `_map`：负责 O(1) 的键值查找（字典的优势）
- `_orderedKeys`：维护键的插入顺序（列表的优势）

代价是额外的内存（List + Dictionary 各一份）和 O(n) 的删除操作，但换来了**完全确定的遍历顺序**。

---

### 添加操作：O(1) amortized

```csharp
public void Add(TKey key, TValue value)
{
    if (_map.ContainsKey(key))
        throw new ArgumentException($"Duplicate key: {key}");

    _map.Add(key, value);          // 字典中添加
    _orderedKeys.Add(key);          // 保持顺序
    _version++;
}
```

添加操作同时维护两个集合，`_version++` 用于检测并发修改（迭代器版本验证）。

---

### 删除操作：O(n)

```csharp
public bool Remove(TKey key)
{
    if (!_map.Remove(key))
        return false;
    
    for (int i = 0; i < _orderedKeys.Count; i++)
    {
        if (EqualityComparer<TKey>.Default.Equals(_orderedKeys[i], key))
        {
            _orderedKeys.RemoveAt(i);  // 从列表中删除：O(n)
            break;
        }
    }
    
    _version++;
    return true;
}
```

删除操作需要在 `_orderedKeys` 中线性查找，复杂度是 O(n)。这是这个数据结构的**主要代价**。

在帧同步场景中，通常元素数量有限（游戏中的单位、技能等通常不超过几百个），O(n) 删除是可接受的。

---

### 迭代器：版本检测防止无效遍历

```csharp
public struct Enumerator : IEnumerator<KeyValuePair<TKey, TValue>>
{
    private readonly DeterministicDictionary<TKey, TValue> _dict;
    private readonly int _version;  // 记录开始遍历时的版本号
    private int _index;

    internal Enumerator(DeterministicDictionary<TKey, TValue> dict)
    {
        _dict = dict;
        _version = dict._version;  // 快照版本
        _index = -1;
    }

    public bool MoveNext()
    {
        // 如果集合在遍历过程中被修改，抛出异常
        if (_version != _dict._version)
            throw new InvalidOperationException("Collection was modified during enumeration");

        _index++;
        return _index < _dict._orderedKeys.Count;
    }

    public KeyValuePair<TKey, TValue> Current
    {
        get
        {
            var key = _dict._orderedKeys[_index];  // 按顺序取键
            return new KeyValuePair<TKey, TValue>(key, _dict._map[key]);
        }
    }
}
```

遍历顺序严格按照 `_orderedKeys` 的顺序，与键的哈希值、插入的内部细节无关。

迭代器是 `struct`（值类型），避免了堆分配——这是 C# 集合迭代器的标准优化技巧，`List<T>` 的迭代器也是如此。

---

## 版本控制机制的重要性

`_version` 字段在每次修改（Add、Remove、Clear）时递增，迭代器在 `MoveNext` 时检查版本是否变化：

```csharp
// ❌ 这会抛出 InvalidOperationException
foreach (var kv in deterministicDict)
{
    if (kv.Value < 0)
        deterministicDict.Remove(kv.Key);  // 遍历过程中修改！
}

// ✅ 正确做法：先收集要删除的键
var toRemove = new List<TKey>();
foreach (var kv in deterministicDict)
{
    if (kv.Value < 0)
        toRemove.Add(kv.Key);
}
foreach (var key in toRemove)
{
    deterministicDict.Remove(key);
}
```

这与 C# 标准集合的行为一致，避免了"遍历过程中删除导致跳过元素"的经典 Bug。

---

## Values 集合：按序访问值

```csharp
public ValueCollection Values => new ValueCollection(this);

public readonly struct ValueCollection : IEnumerable<TValue>
{
    private readonly DeterministicDictionary<TKey, TValue> _dict;

    public ValueEnumerator GetEnumerator()
        => new ValueEnumerator(_dict);
}

public struct ValueEnumerator : IEnumerator<TValue>
{
    // 按 _orderedKeys 顺序返回值
    public TValue Current
        => _dict._map[_dict._orderedKeys[_index]];
}
```

`Values` 返回一个轻量的 `ValueCollection` 结构体，不分配堆内存。遍历值时同样保证顺序确定。

---

## 性能特性对比

| 操作 | DeterministicDictionary | Dictionary | LinkedList + Dictionary |
|------|------------------------|-----------|------------------------|
| 添加 | O(1) amortized | O(1) amortized | O(1) |
| 删除 | O(n) | O(1) | O(1) 删 list节点 + O(1) 删map |
| 查找 | O(1) | O(1) | O(1) |
| 遍历 | O(n)，顺序确定 | O(n)，顺序不定 | O(n)，顺序确定 |
| 内存 | 约 2x | 1x | 约 2.5x |

**为什么不用 LinkedList + Dictionary？**

`LinkedList` 也能维护插入顺序，且删除是 O(1)。但 `LinkedList` 是基于节点的结构，每个节点是堆分配对象，遍历时内存访问局部性差（缓存友好性低）。

`DeterministicDictionary` 内部的 `List<TKey>` 是连续内存，遍历时 CPU 缓存命中率高，实际性能往往优于理论分析。

---

## 实战：帧同步中的应用

```csharp
// 帧同步中的单位管理器
public class UnitManager
{
    // 使用 DeterministicDictionary 保证每帧遍历顺序一致
    private DeterministicDictionary<int, Unit> _units = new(capacity: 256);
    
    public void AddUnit(int unitId, Unit unit)
    {
        _units.Add(unitId, unit);
    }
    
    public void RemoveUnit(int unitId)
    {
        _units.Remove(unitId);
    }
    
    // 每帧更新：顺序完全确定
    public void Update(int deltaTime)
    {
        foreach (var kv in _units)
        {
            kv.Value.Update(deltaTime);
        }
    }
    
    // 处理技能效果：遍历顺序影响技能命中优先级
    public void ApplyAOEDamage(Vector3 center, float radius, int damage)
    {
        // 两台客户端必须按相同顺序处理，否则 HP 结算不同
        foreach (var unit in _units.Values)
        {
            if (Vector3.Distance(unit.Position, center) <= radius)
            {
                unit.TakeDamage(damage);
            }
        }
    }
}
```

---

## 何时不应该用 DeterministicDictionary？

并非所有场景都需要确定性字典：

1. **单机游戏**：没有帧同步需求，普通 `Dictionary` 更快
2. **纯查找不遍历**：如果只做键值查找，不遍历，普通 `Dictionary` 完全够用
3. **删除频繁**：如果频繁删除，O(n) 的删除成本不可接受，考虑 `SortedDictionary`（按键排序，O(log n) 操作）

```csharp
// ✅ 帧同步游戏中，遍历影响逻辑结果的集合
var units = new DeterministicDictionary<int, Unit>();

// ❌ 不需要确定顺序的场景，用普通字典
var assetCache = new Dictionary<string, Object>();  // 查找操作，顺序无关
```

---

## 总结

`DeterministicDictionary` 是一个经典的**空间换时间、功能换性能**的工程取舍：

- **代价**：约 2 倍内存，O(n) 删除
- **收益**：完全确定的遍历顺序，杜绝帧同步 desync

它的实现展示了三个重要工程原则：

1. **单一职责**：`_map` 负责查找，`_orderedKeys` 负责顺序，职责清晰
2. **版本保护**：`_version` 检测并发修改，防止迭代器失效 Bug
3. **值类型迭代器**：struct Enumerator 避免堆分配，遵循 C# 集合最佳实践

理解了为什么帧同步需要确定性，你就理解了一类重要的游戏开发约束，这是分布式系统思维在游戏领域的具体体现。
