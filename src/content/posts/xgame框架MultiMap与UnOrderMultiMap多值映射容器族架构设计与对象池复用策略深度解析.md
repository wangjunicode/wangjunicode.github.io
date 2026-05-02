---
title: xgame框架MultiMap与UnOrderMultiMap多值映射容器族架构设计与对象池复用策略深度解析
published: 2026-05-02
description: 深入解析 xgame/ET 框架中 MultiMap、UnOrderMultiMap、UnOrderMultiMapSet 三种多值映射容器的设计差异、List对象池复用机制、排序策略选择及游戏开发中的典型应用
tags: [Unity, xgame, 数据结构, C#, 游戏框架, 对象池]
category: Unity游戏框架
draft: false
encryptedKey: henhaoji123
---

## 前言

在游戏开发中，一个 Key 对应多个 Value 的"一对多"映射是高频需求——比如一个技能 ID 对应多个挂载特效、一个事件类型对应多个监听器、一个场景对应多个实体。

标准的 `Dictionary<K, List<V>>` 虽然能实现此功能，但存在以下问题：
1. 每次新增 Key 都要 `new List<V>()`，GC 压力大
2. Key 删除后其 List 直接丢弃，无法复用
3. 代码重复且容易出 Bug（忘记处理空 List）

xgame 框架提供了三种多值映射容器，各有侧重，从根本上解决上述问题：
- **`MultiMap<T, K>`**：有序多值映射 + List 对象池
- **`UnOrderMultiMap<T, K>`**：无序多值映射（轻量版）
- **`UnOrderMultiMapSet<T, K>`**：无序多值映射（Value 自动去重）

---

## 一、MultiMap：有序多值映射 + 对象池

### 继承结构

```csharp
public class MultiMap<T, K> : SortedDictionary<T, List<K>>
```

`MultiMap` 继承自 `SortedDictionary`，意味着：
- 所有的 Key 会**按照自然顺序排序**（或自定义 Comparer）
- 遍历时 Key 有序
- 适合需要按序处理的场景（如优先级队列、时序事件等）

### List 对象池设计

```csharp
private readonly int maxPoolCount;
private readonly Queue<List<K>> pool;

public MultiMap(int maxPoolCount = 0)
{
    this.maxPoolCount = maxPoolCount;
    this.pool = new Queue<List<K>>(maxPoolCount);
}

private List<K> FetchList()
{
    if (this.pool.Count > 0) return this.pool.Dequeue();
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

这是 `MultiMap` 最核心的设计——**内置 List 对象池**：

| 操作 | 行为 |
|------|------|
| 需要新 List | 先从 pool 取，没有才 new |
| 移除 Key | 对应 List 回收到 pool（清空但不销毁） |
| Pool 满时 | 多余的 List 直接丢弃（GC 回收）|

`pool` 使用 `Queue<List<K>>` 实现，FIFO 取用，防止 List 被复用时的初始化开销：

```csharp
private List<K> FetchList()
{
    if (this.pool.Count > 0) return this.pool.Dequeue();
    return new List<K>(10);  // 预分配10个槽位
}
```

新建 List 时预分配 10 个槽，减少小批量添加时的扩容次数。

### 添加与删除

```csharp
public void Add(T t, K k)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list == null)
    {
        list = this.FetchList();  // 从池中获取
        this.Add(t, list);
    }
    list.Add(k);
}

public new bool Remove(T t)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list == null) return false;
    this.Recycle(list);  // 回收到池
    return base.Remove(t);
}
```

`Remove` 方法使用 `new` 关键字覆盖基类的 `Remove`，确保删除 Key 时触发 List 回收逻辑。

### 单值删除

```csharp
public bool Remove(T t, K k)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list == null) return false;
    if (!list.Remove(k)) return false;
    if (list.Count == 0)
    {
        this.Remove(t);  // 自动清理空 Key（会触发 List 回收）
    }
    return true;
}
```

从某个 Key 的 Value 列表中移除单个 Value，如果列表变空则自动清理整个 Key 条目（并回收 List）。这种自动清理避免了"僵尸 Key"问题。

### 读取接口设计

```csharp
// 返回内部 List 引用（高性能，但外部不应修改）
public new List<K> this[T t]
{
    get
    {
        this.TryGetValue(t, out List<K> list);
        return list ?? Empty;
    }
}

// 返回 List 的数组副本（安全，外部可随意操作）
public K[] GetAll(T t)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list == null) return Array.Empty<K>();
    return list.ToArray();
}

// 获取第一个值
public K GetOne(T t)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list != null && list.Count > 0) return list[0];
    return default;
}
```

三种读取方式各有用途：
- `this[T t]`：返回内部 List（用于只读遍历，零 GC）
- `GetAll(T t)`：返回数组副本（用于需要修改的场景）
- `GetOne(T t)`：快速获取首个值（用于单值场景的快捷访问）

**Empty 哨兵值**：

```csharp
private readonly List<K> Empty = new();
```

当 Key 不存在时，索引器返回这个共享的空 List，而不是 null。调用方可以直接 foreach 而不用判空，代码更安全简洁。

---

## 二、UnOrderMultiMap：轻量无序多值映射

```csharp
public class UnOrderMultiMap<T, K> : Dictionary<T, List<K>>
```

继承自普通 `Dictionary`，无排序开销，适合不需要 Key 有序的场景。

相比 `MultiMap` 的主要差异：

| 特性 | MultiMap | UnOrderMultiMap |
|------|----------|-----------------|
| 基类 | SortedDictionary | Dictionary |
| Key 排序 | 有序 | 无序 |
| List 对象池 | ✅ 有 | ❌ 无 |
| 性能 | Add/Remove O(log n) | Add/Remove O(1) 均摊 |
| 适用场景 | 有序事件、优先处理 | 普通多值映射 |

```csharp
public void Add(T t, K k)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list == null)
    {
        list = new List<K>();  // 直接 new，无池化
        base[t] = list;
    }
    list.Add(k);
}
```

`UnOrderMultiMap` 没有对象池，每次创建新 Key 时直接 `new List<K>()`。适用于：
- Key 数量稳定、不频繁增删的场景
- 性能要求极高、需要 O(1) 查找的场景
- 不关心 Key 顺序的业务逻辑

---

## 三、UnOrderMultiMapSet：值自动去重的多值映射

```csharp
public class UnOrderMultiMapSet<T, K> : Dictionary<T, HashSet<K>>
```

Value 容器从 `List` 换成了 `HashSet`，核心特性是**Value 自动去重**。

```csharp
public void Add(T t, K k)
{
    HashSet<K> set;
    this.TryGetValue(t, out set);
    if (set == null)
    {
        set = new HashSet<K>();
        base[t] = set;
    }
    set.Add(k);  // HashSet 自动去重，重复元素忽略
}
```

### 重写的 Count 属性

```csharp
public new int Count
{
    get
    {
        int count = 0;
        foreach (KeyValuePair<T, HashSet<K>> kv in this)
        {
            count += kv.Value.Count;
        }
        return count;
    }
}
```

`Count` 属性被重写，返回的是**所有值的总数量**，而不是 Key 的数量。这与普通字典的语义不同，需要注意。

### 适用场景

- 订阅-发布系统中，防止同一个监听器重复注册
- 标签系统中，一个实体对应多个不重复的标签
- 权限系统中，一个角色对应多个不重复的权限

---

## 四、三种容器横向对比

```
需要一个Key对应多个Value的映射
           │
           ├── Value 需要去重？
           │       └── 是 → UnOrderMultiMapSet<T, K>
           │
           ├── Key 需要排序？
           │       └── 是 → MultiMap<T, K>（有对象池加持）
           │
           └── 否（普通无序多值）
                   └── UnOrderMultiMap<T, K>
```

| 特性 | MultiMap | UnOrderMultiMap | UnOrderMultiMapSet |
|------|----------|-----------------|--------------------|
| 基类 | SortedDictionary | Dictionary | Dictionary |
| Value 容器 | List | List | HashSet |
| Key 排序 | ✅ 有序 | ❌ 无序 | ❌ 无序 |
| Value 去重 | ❌ 允许重复 | ❌ 允许重复 | ✅ 自动去重 |
| 对象池 | ✅ List 复用 | ❌ 无 | ❌ 无 |
| 查询 Value | O(log n) + O(1) | O(1) | O(1) |
| Count 语义 | Key 数量 | Key 数量 | 所有 Value 总数 |

---

## 五、实际应用示例

### 1. 用 MultiMap 实现优先级事件队列

```csharp
// Key 为优先级（int，自动排序），Value 为事件列表
private MultiMap<int, IEvent> priorityEventQueue = new MultiMap<int, IEvent>(32);

// 添加事件（优先级越小越先处理）
priorityEventQueue.Add(0, new CriticalEvent());
priorityEventQueue.Add(5, new NormalEvent());
priorityEventQueue.Add(10, new LowPriorityEvent());

// 按优先级顺序处理（SortedDictionary 保证有序遍历）
foreach (var pair in priorityEventQueue)
{
    foreach (var evt in pair.Value)
    {
        evt.Execute();
    }
}
```

### 2. 用 UnOrderMultiMap 实现组件系统

```csharp
// Key 为组件类型，Value 为持有该组件的实体列表
private UnOrderMultiMap<Type, Entity> componentEntityMap = new UnOrderMultiMap<Type, Entity>();

// 实体添加组件时注册
componentEntityMap.Add(typeof(HpComponent), entity);

// 查询所有拥有某组件的实体
List<Entity> entities = componentEntityMap[typeof(HpComponent)];
```

### 3. 用 UnOrderMultiMapSet 实现事件系统防重注册

```csharp
// Key 为事件类型，Value 为监听器集合（自动去重）
private UnOrderMultiMapSet<string, Action<IEventArgs>> listeners 
    = new UnOrderMultiMapSet<string, Action<IEventArgs>>();

// 重复注册同一监听器不会产生副作用
listeners.Add("OnPlayerDead", OnPlayerDeadHandler);
listeners.Add("OnPlayerDead", OnPlayerDeadHandler);  // 被自动去重

// 获取监听器数量（返回所有 Value 总数）
int totalListeners = listeners.Count;
```

---

## 六、对象池的 GC 优化效果

以每帧 1000 次 Add/Remove 的高频场景为例：

**无对象池（UnOrderMultiMap）：**
- 每次新增 Key 创建新 List → 每帧约 N 次 GC Alloc
- Key 移除后 List 进入 GC 队列 → 周期性 GC 停顿

**有对象池（MultiMap）：**
- List 复用，稳定后每帧 GC Alloc 趋近于 0
- 池大小上限可配置，防止内存无限增长

这对于游戏运行时（尤其是战斗逻辑高频更新阶段）有显著的稳定性提升。

---

## 总结

xgame 框架的多值映射容器族体现了以下设计哲学：

1. **按需选择**：三种容器针对不同场景，不过度设计
2. **零 GC 意识**：`MultiMap` 的 List 池化是游戏框架对 GC 压力的主动管理
3. **安全性优先**：自动清理空 Key、空 List 返回哨兵值、防止 null 操作
4. **继承而非组合**：直接继承 Dictionary 系列，保留原有接口的同时扩展能力

在实际项目中，根据 Key 是否需要排序、Value 是否需要去重、操作是否高频这三个维度来选择合适的容器，可以在简化代码的同时获得最优性能。
