---
title: MultiMap 有序多值映射容器：内置池化设计的泛型多键字典
encryptedKey: henhaoji123
tags:
  - Unity
  - C#
  - 数据结构
  - 游戏框架
  - 性能优化
categories:
  - 游戏开发
  - 框架源码
published: 2026-04-22
description: 深度解析 ET 框架中 MultiMap 的源码实现，探讨有序多值映射容器如何通过内置对象池消除 GC 分配，以及一键多多值的数据结构如何在事件系统、技能索引等场景中发挥核心作用。
---

## 前言

在游戏框架的数据结构设计中，"一个 key 对应多个 value" 的需求极为常见：一个事件类型对应多个订阅者、一个 Entity 对应多个组件类型、一个技能 Tag 映射多个技能实例……

标准库里的 `Dictionary<T, List<K>>` 可以做到，但它有一个隐患：每次移除 key 时，List 对象就被遗弃，产生 GC。ET 框架的 `MultiMap<T, K>` 通过内置对象池彻底解决了这个问题。

---

## 源码全览

```csharp
public class MultiMap<T, K> : SortedDictionary<T, List<K>>
{
    private readonly List<K> Empty = new();
    private readonly int maxPoolCount;
    private readonly Queue<List<K>> pool;

    public MultiMap(int maxPoolCount = 0)
    {
        this.maxPoolCount = maxPoolCount;
        this.pool = new Queue<List<K>>(maxPoolCount);
    }
    // ...
}
```

**继承自 `SortedDictionary<T, List<K>>`**，这意味着 key 始终保持有序——这对需要按优先级遍历事件的场景尤为重要。

---

## 核心设计：内置 List 对象池

### 池化机制

```csharp
private List<K> FetchList()
{
    if (this.pool.Count > 0)
        return this.pool.Dequeue();
    return new List<K>(10);
}

private void Recycle(List<K> list)
{
    if (list == null) return;
    if (this.pool.Count == this.maxPoolCount) return;
    list.Clear();
    this.pool.Enqueue(list);
}
```

- **FetchList**：优先从池中取，池空时才 new，初始容量设为 10 避免小列表频繁扩容
- **Recycle**：回收时先 Clear（归零但不释放内存），再入队；当池满时直接丢弃（防止无限增长）
- **maxPoolCount = 0** 时池容量为零，退化为无池化模式，适合低频场景

### 添加值

```csharp
public void Add(T t, K k)
{
    this.TryGetValue(t, out List<K> list);
    if (list == null)
    {
        list = this.FetchList();  // 从池中取
        this.Add(t, list);
    }
    list.Add(k);
}
```

首次添加某个 key 时从池中获取 List，之后直接向 List 追加——零额外分配。

### 移除值

```csharp
public bool Remove(T t, K k)
{
    this.TryGetValue(t, out List<K> list);
    if (list == null) return false;
    if (!list.Remove(k)) return false;
    if (list.Count == 0)
        this.Remove(t);       // 触发下面的 Remove(T t)
    return true;
}

public new bool Remove(T t)
{
    this.TryGetValue(t, out List<K> list);
    if (list == null) return false;
    this.Recycle(list);       // 回收 List 到池
    return base.Remove(t);
}
```

当 List 为空时，自动将 key 从字典中移除，同时将 List 回收复用，**无 GC 产生**。

---

## 安全访问设计

### 空安全索引器

```csharp
public new List<K> this[T t]
{
    get
    {
        this.TryGetValue(t, out List<K> list);
        return list ?? Empty;  // 不存在时返回空列表而非 null
    }
}
```

返回共享的 `Empty`（只读空列表），调用方无需判空直接 foreach，避免 NullReferenceException。

### GetAll：安全拷贝

```csharp
public K[] GetAll(T t)
{
    this.TryGetValue(t, out List<K> list);
    if (list == null) return Array.Empty<K>();
    return list.ToArray();
}
```

返回 **数组快照**，适合需要在遍历时修改 MultiMap 的场景（如事件派发中取消订阅）。

### GetOne：首元素快捷访问

```csharp
public K GetOne(T t)
{
    this.TryGetValue(t, out List<K> list);
    if (list != null && list.Count > 0)
        return list[0];
    return default;
}
```

---

## MultiMap 在事件系统中的应用

ET 框架的 EventSystem 内部大量使用 MultiMap 存储系统类型到实现类的映射：

```csharp
// 伪代码示意
private readonly MultiMap<Type, IUpdateSystem> updateSystems = new(128);

// 注册
updateSystems.Add(typeof(MovementComponent), new MovementUpdateSystem());

// 派发 - 直接遍历内部 List，不产生额外分配
foreach (IUpdateSystem system in updateSystems[entityType])
{
    system.Run(entity);
}
```

**内置有序性**保证了相同类型的多个系统按注册顺序依次执行，行为可预测。

---

## 与 UnOrderMultiMap 的对比

| 特性 | MultiMap | UnOrderMultiMap |
|------|----------|-----------------|
| 底层结构 | SortedDictionary（红黑树） | Dictionary（哈希表） |
| Key 有序 | ✅ 自然排序 | ❌ 无序 |
| 查找复杂度 | O(log n) | O(1) |
| 适用场景 | 需要按 key 排序遍历 | 高频随机访问 |
| 内存开销 | 较高（树节点） | 较低 |

**选择策略**：
- 事件优先级队列、技能 Tag 分组 → `MultiMap`（有序）
- 组件类型索引、UI 面板注册 → `UnOrderMultiMap`（速度）

---

## 完整使用示例

```csharp
// 创建一个最多池化 32 个 List 的 MultiMap
var skillMap = new MultiMap<int, long>(32);

// 添加技能实例
skillMap.Add(SkillTag.Attack, skillEntityId1);
skillMap.Add(SkillTag.Attack, skillEntityId2);
skillMap.Add(SkillTag.Buff, buffEntityId1);

// 遍历某类技能（返回内部 List，零分配）
foreach (long id in skillMap[SkillTag.Attack])
{
    // 处理技能
}

// 获取快照（遍历时安全移除）
long[] allAttack = skillMap.GetAll(SkillTag.Attack);
foreach (long id in allAttack)
{
    if (ShouldRemove(id))
        skillMap.Remove(SkillTag.Attack, id);  // List 空时自动回收
}

// 查询是否包含某值
bool has = skillMap.Contains(SkillTag.Attack, skillEntityId1);
```

---

## 设计亮点总结

1. **继承 SortedDictionary 而非 Dictionary**：天然有序，适合按 key 权重排序的场景
2. **内置 List 对象池**：通过 `maxPoolCount` 控制上限，兼顾复用率与内存安全
3. **空安全索引器**：返回 `Empty` 而非 null，消除调用方的防御判空代码
4. **双重移除语义**：`Remove(T, K)` 精确移除单值；`Remove(T)` 移除整个 key 并回收 List
5. **GetAll 拷贝语义**：为迭代过程中修改提供快照保障

---

## 小结

`MultiMap` 看似是对 `SortedDictionary<T, List<K>>` 的简单封装，但通过内置对象池和精心设计的安全访问接口，它将 **零 GC** 的多值映射能力封装成了开箱即用的工具类。在事件系统、技能索引、组件分组等高频场景中，这种设计让框架底层的内存分配降到最低，是游戏框架容器库中的精品设计。
