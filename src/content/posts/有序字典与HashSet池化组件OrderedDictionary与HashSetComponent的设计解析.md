---
title: 有序字典与HashSet池化组件：OrderedDictionary与HashSetComponent的设计解析
published: 2026-04-20
description: 深入解析ET框架中OrderedDictionary与HashSetComponent的设计原理，前者保证插入顺序兼顾快速查找，后者通过对象池消除HashSet频繁创建带来的GC压力，全面掌握游戏框架定制容器的工程价值。
tags: [Unity, 游戏框架, CSharp, 数据结构, 对象池]
category: 游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

## 引言

C# 标准库提供了丰富的集合类型，但在游戏框架开发中，这些"标准"容器有时并不完全满足需求：`Dictionary` 不保证插入顺序，`HashSet` 频繁创建销毁带来 GC 压力。ET 框架针对这两个痛点，分别提供了 `OrderedDictionary<TKey, TValue>` 和 `HashSetComponent<T>` 两个定制容器。本文将深入解析它们的设计思路与工程价值。

---

## OrderedDictionary\<TKey, TValue\>：插入顺序保持的字典

### 为什么需要有序字典？

标准 `Dictionary<TKey, TValue>` 的遍历顺序是不确定的（取决于哈希桶分布）。在以下场景中，我们需要字典严格按插入顺序遍历：

- **技能 Buff 的执行序列**：先加入的 Buff 先执行，顺序决定游戏逻辑
- **UI 面板层叠管理**：按打开顺序管理面板的显示/关闭
- **配置表有序覆盖**：后加载的配置项覆盖先加载的，需要知道加载顺序

C# 5.0 之前标准库没有 `OrderedDictionary` 的泛型版本（只有非泛型的 `System.Collections.Specialized.OrderedDictionary`）。ET 框架参考 `System.Web.Util` 的实现，提供了这个泛型版本。

### 源码架构

```csharp
public class OrderedDictionary<TKey, TValue> : IDictionary<TKey, TValue>
{
    private Dictionary<TKey, TValue> _dictionary;  // O(1) 查找
    private List<TKey> _keys;                       // 保持插入顺序
    private List<TValue> _values;                   // 与 _keys 并行
    ...
}
```

**三结构并行存储**是其核心设计：
- `_dictionary`：负责 O(1) 的键值查找
- `_keys` + `_values`：两个并行 `List` 记录插入顺序

### 关键操作分析

#### 插入 Add

```csharp
public void Add(TKey key, TValue value)
{
    _dictionary.Add(key, value);  // 若 key 重复，Dictionary 会抛异常
    _keys.Add(key);
    _values.Add(value);
}
```

同时维护三个结构，时间复杂度 O(1)（摊销）。

#### 索引器赋值（支持更新）

```csharp
public TValue this[TKey key]
{
    set
    {
        RemoveFromLists(key);  // 先从列表移除旧位置
        _dictionary[key] = value;
        _keys.Add(key);        // 重新插入到末尾
        _values.Add(value);
    }
}
```

**重要设计决策**：当更新已有 Key 时，该 Key 在顺序中的位置会移动到**末尾**。这与通常期望的"更新不改变顺序"有所不同，开发者需注意。

#### 删除 Remove

```csharp
private void RemoveFromLists(TKey key)
{
    int index = _keys.IndexOf(key);
    if (index != -1)
    {
        _keys.RemoveAt(index);
        _values.RemoveAt(index);
    }
}

public bool Remove(TKey key)
{
    RemoveFromLists(key);
    return _dictionary.Remove(key);
}
```

`RemoveFromLists` 需要 O(n) 线性搜索 + O(n) 的列表移位操作，是整个实现的**性能瓶颈**。

#### 有序遍历

```csharp
public IEnumerator<KeyValuePair<TKey, TValue>> GetEnumerator()
{
    int i = 0;
    foreach (TKey key in _keys)
    {
        yield return new KeyValuePair<TKey, TValue>(key, _values[i]);
        i++;
    }
}
```

遍历时按 `_keys` 列表的顺序输出，保证插入顺序。`yield return` 使其为惰性迭代，不会一次性创建所有 KV 对。

### 性能特性对比

| 操作 | Dictionary | OrderedDictionary |
|------|-----------|-------------------|
| 读取 | O(1) | O(1) |
| 插入 | O(1)摊销 | O(1)摊销 |
| 更新 | O(1) | O(n)（RemoveFromLists） |
| 删除 | O(1) | O(n)（列表移位） |
| 有序遍历 | ✗ | ✓ O(n) |

**适用场景**：读多写少、需要有序遍历、数据量不大（数百级别）的场景。不适合频繁更新/删除的高性能热路径。

### 遍历期间的修改安全

```csharp
foreach (TKey key in _keys)  // 使用 foreach 而非 for 循环
{
    yield return ...;
}
```

注释说明使用 `foreach` 而非 `for` 是为了让底层 `List` 的枚举器在遍历期间被修改时**抛出异常**，而不是静默地产生错误结果。这是一个主动的防御性设计。

---

## HashSetComponent\<T\>：池化的 HashSet 容器

### 源码

```csharp
public class HashSetComponent<T> : HashSet<T>, IDisposable
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

### 设计模式：继承 + 对象池

`HashSetComponent<T>` 直接继承 `HashSet<T>`，这意味着它拥有 `HashSet` 的全部能力（Add、Remove、Contains、UnionWith 等），不需要任何适配层。

**对象池集成**：与 ET 框架中其他集合组件（`ListComponent`、`StackComponent` 等）完全一致的模式：

```csharp
// 获取（优先从池中复用）
var set = HashSetComponent<int>.Create();

// 使用（完整的 HashSet API）
set.Add(100);
set.Add(200);
if (set.Contains(100)) { ... }

// 归还（自动 Clear + 回池）
set.Dispose();
```

### 为什么不直接 new HashSet\<T\>？

在游戏逻辑的每帧更新中，频繁创建和销毁集合对象会产生大量 GC 压力：

```csharp
// ❌ 每帧分配，产生 GC
void Update()
{
    var targets = new HashSet<Entity>();  // 堆分配
    FindTargetsInRange(targets);
    ProcessTargets(targets);
    // targets 离开作用域，等待 GC
}

// ✅ 池化复用，零 GC
void Update()
{
    var targets = HashSetComponent<Entity>.Create();  // 从池中取
    FindTargetsInRange(targets);
    ProcessTargets(targets);
    targets.Dispose();  // 清空并还池
}
```

使用 `Dispose` 模式配合 `using` 语句，代码更安全：

```csharp
using (var targets = HashSetComponent<Entity>.Create())
{
    FindTargetsInRange(targets);
    ProcessTargets(targets);
}  // 自动 Dispose
```

### Clear 时机的重要性

`Dispose()` 中先 `Clear()` 再 `Recycle()` 是关键——如果不清空就还池，下次 `Create()` 取出时仍包含上次的数据，导致逻辑错误。`Clear()` 不释放内部数组，只重置 `Count`，避免了内存重新分配。

### HashSet vs List vs Dictionary 的选型

| 场景 | 推荐容器 |
|------|---------|
| 快速判断元素是否存在 | HashSetComponent |
| 有序遍历、索引访问 | ListComponent |
| 键值映射 | DictionaryComponent |
| 技能目标去重 | HashSetComponent |
| Buff 排序优先级 | ListComponent（配合排序） |

---

## 与框架其他集合组件的对比

ET 框架 `Core` 目录下有一整套池化集合族：

```
DictionaryComponent<TKey, TValue>  -> Dictionary + Pool
ListComponent<T>                   -> List + Pool
StackComponent<T>                  -> Stack + Pool
HashSetComponent<T>                -> HashSet + Pool
```

它们遵循**统一的模式**：
1. 继承标准集合类
2. `Create()` 从对象池获取
3. `Dispose()` 清空并归还

这种设计的优势是：
- **一致的使用方式**：开发者只需记住一套 `Create/Dispose` 模式
- **最小化学习成本**：底层仍是标准集合 API，无需额外文档
- **可插拔**：需要性能时切换到池化版，不需要时直接 new 标准版

---

## 实战案例：技能 AOE 目标查重

```csharp
// AOE 技能：找到范围内所有唯一目标
public async ETTask<List<Unit>> FindAoeTargets(Unit caster, float radius)
{
    // 池化 HashSet 去重，避免同一目标被多次命中
    using var hitSet = HashSetComponent<long>.Create();
    using var result = ListComponent<Unit>.Create();
    
    // 获取范围内所有碰撞体（可能有重复）
    var colliders = Physics.OverlapSphere(caster.Position, radius);
    
    foreach (var col in colliders)
    {
        var unit = col.GetComponent<UnitView>()?.Unit;
        if (unit == null) continue;
        
        // HashSet O(1) 去重
        if (hitSet.Add(unit.Id))
        {
            result.Add(unit);
        }
    }
    
    return result.ToList();  // 返回前转为普通 List
}
// using 块结束，hitSet 和 result 自动还池
```

---

## 总结

| 容器 | 解决的问题 | 核心权衡 |
|------|-----------|---------|
| `OrderedDictionary<K,V>` | 标准 Dictionary 不保证顺序 | 增加了 O(n) 删除开销，换取有序遍历 |
| `HashSetComponent<T>` | HashSet 频繁创建产生 GC | 引入对象池，以代码复杂度换取运行时性能 |

ET 框架的这两个定制容器体现了"在标准库基础上精准扩展"的设计哲学：不重新发明轮子，而是针对游戏开发的特定痛点（顺序需求、GC 压力）做最小化改造。这种渐进式扩展的方式，保持了代码的可理解性，同时解决了实际问题。
