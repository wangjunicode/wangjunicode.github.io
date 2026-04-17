---
title: 双向字典 DoubleMap：键值互查与双索引容器的工程实践
published: 2026-04-17
description: 深入解析游戏框架中 DoubleMap<K,V> 的设计思路，探讨如何用两张 Dictionary 实现 O(1) 的双向查找，以及在游戏系统中 ID↔对象、枚举↔字符串等典型应用场景。
tags: [CSharp, 游戏框架, 数据结构, DoubleMap, 双向映射]
category: Unity游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

# 双向字典 DoubleMap：键值互查与双索引容器的工程实践

## 背景：为什么需要双向查找？

游戏开发中有大量"双向绑定"的需求：

- 通过 `entityId` 找到对应的 `GameObject`，也需要通过 `GameObject` 反查 `entityId`
- 通过枚举值找字符串描述，也需要通过字符串反向解析枚举
- 网络连接中，通过 `sessionId` 找 `userId`，也需要通过 `userId` 找 `sessionId`

传统方案是维护两个独立的 `Dictionary`，但这带来同步问题——增删时必须同时操作两张表，稍不注意就数据不一致。`DoubleMap<K, V>` 将这个模式封装成一个统一的双向容器，从根源上解决问题。

---

## 源码解析

```csharp
public class DoubleMap<K, V>
{
    private readonly Dictionary<K, V> kv = new Dictionary<K, V>();
    private readonly Dictionary<V, K> vk = new Dictionary<V, K>();
    // ...
}
```

核心就是两张字典：
- `kv`：正向映射，Key → Value
- `vk`：反向映射，Value → Key

**这两张表始终保持镜像一致性**，这是 DoubleMap 最核心的不变式。

### 构造函数：预分配容量

```csharp
public DoubleMap(int capacity)
{
    kv = new Dictionary<K, V>(capacity);
    vk = new Dictionary<V, K>(capacity);
}
```

支持传入初始容量，避免运行时频繁扩容。游戏中如果能预估映射规模（如角色上限 100），提前指定容量是个好习惯。

### Add：防止脏数据入库

```csharp
public void Add(K key, V value)
{
    if (key == null || value == null || kv.ContainsKey(key) || vk.ContainsKey(value))
    {
        return;
    }
    kv.Add(key, value);
    vk.Add(value, key);
}
```

这里有四个守卫条件：
1. `key == null` — 防止 null 键
2. `value == null` — 防止 null 值（因为 value 要作为反向的 key）
3. `kv.ContainsKey(key)` — 防止 key 重复
4. `vk.ContainsKey(value)` — 防止 value 重复（双向映射要求 value 也是唯一的）

**注意第 4 点**：这意味着 DoubleMap 是一个**一对一双射**（bijection），不支持一对多。如果两个不同的 key 要映射到同一个 value，Add 会静默失败。这是有意为之的设计约束。

### 双向查找：O(1) 的代价

```csharp
public V GetValueByKey(K key)
{
    if (key != null && kv.ContainsKey(key))
        return kv[key];
    return default(V);
}

public K GetKeyByValue(V value)
{
    if (value != null && vk.ContainsKey(value))
        return vk[value];
    return default(K);
}
```

两个方向都是 O(1) 哈希查找，这是相比"遍历 + 反查"方案最大的性能优势。

### Remove：原子删除，保证一致性

```csharp
public void RemoveByKey(K key)
{
    if (key == null) return;
    V value;
    if (!kv.TryGetValue(key, out value)) return;

    kv.Remove(key);
    vk.Remove(value);
}
```

删除时先通过 key 找到对应的 value，再同时清理两张表。这保证了两张字典始终处于一致状态，不会出现"正向有、反向没有"的孤悬记录。

### ForEach：安全遍历

```csharp
public void ForEach(Action<K, V> action)
{
    if (action == null) return;
    Dictionary<K, V>.KeyCollection keys = kv.Keys;
    foreach (K key in keys)
    {
        action(key, kv[key]);
    }
}
```

只遍历 `kv` 一张表就够了，不需要遍历两张。遍历时如果需要修改容器，应该先收集 key 到临时列表再操作，避免 "collection was modified" 异常。

---

## 典型应用场景

### 场景 1：Entity ID ↔ GameObject

```csharp
public class EntityObjectMap
{
    private readonly DoubleMap<long, GameObject> map = new DoubleMap<long, GameObject>();

    public void Register(long entityId, GameObject go)
    {
        map.Add(entityId, go);
    }

    public GameObject GetGo(long entityId) => map.GetValueByKey(entityId);
    public long GetEntityId(GameObject go) => map.GetKeyByValue(go);

    public void Unregister(long entityId) => map.RemoveByKey(entityId);
}
```

当战斗系统需要"通过 GameObject 的点击事件反查对应的实体 ID"时，这个映射极为方便。

### 场景 2：枚举 ↔ 字符串

```csharp
var stateMap = new DoubleMap<BattleState, string>();
stateMap.Add(BattleState.Idle,    "idle");
stateMap.Add(BattleState.Attack,  "attack");
stateMap.Add(BattleState.Dead,    "dead");

// 序列化：枚举 → 字符串
string stateName = stateMap.GetValueByKey(BattleState.Attack); // "attack"

// 反序列化：字符串 → 枚举
BattleState state = stateMap.GetKeyByValue("dead"); // BattleState.Dead
```

比手写 `switch-case` 或维护两个 `Dictionary` 优雅得多。

### 场景 3：网络会话 Session ↔ 玩家 ID

```csharp
// sessionId → playerId，也支持 playerId → sessionId
var sessionMap = new DoubleMap<int, long>(256);
sessionMap.Add(connId, playerId);

// 收到消息时，通过连接 ID 找玩家
long pid = sessionMap.GetValueByKey(connId);

// 推送消息时，通过玩家 ID 找连接
int conn = sessionMap.GetKeyByValue(targetPlayerId);
```

---

## 使用注意事项

### 1. Value 必须可以作为 Dictionary Key

`V` 类型会被用作反向字典的 Key，因此需要正确实现 `GetHashCode()` 和 `Equals()`。对于 GameObject、Entity 等引用类型，默认的引用相等性通常没问题；但如果用结构体或自定义类型作为 Value，需要确保哈希逻辑正确。

### 2. 严格一对一，不支持多值

DoubleMap 是**双射**，不是多映射。如果你的业务需要一个 Key 对应多个 Value，应该用 `MultiMap` 或其他数据结构。

### 3. null 值无法存储

源码中对 null 的防御意味着 DoubleMap 不支持存储 null 值。如果业务上需要"未绑定"的状态，应该用 `Nullable<V>` 包装，或者在外层维护一个独立的状态标记。

### 4. 线程安全

标准 DoubleMap 不是线程安全的。在多线程场景（如 ET 框架的网络线程与逻辑线程）下，需要加锁或使用 `ConcurrentDictionary` 版本。

---

## 与标准 Dictionary 的对比

| 特性 | Dictionary<K,V> | DoubleMap<K,V> |
|------|-----------------|----------------|
| 正向查找 K→V | O(1) | O(1) |
| 反向查找 V→K | O(n) 遍历 | O(1) |
| 内存占用 | 1x | ~2x |
| 是否支持 null | 可配置 | 不支持 |
| 是否一对多 | 支持 | 不支持 |

以 2 倍内存为代价，换来双向 O(1) 查找能力。在需要频繁反向查找的场景下，这个交换非常划算。

---

## 小结

`DoubleMap<K, V>` 是一个小而精的工具类，设计上非常克制：

- **只做一件事**：维护两个方向的一对一映射
- **守卫条件严格**：Add 时四重检查，保证不变式永远成立
- **删除原子**：Remove 时同步清理两张表，不留孤悬数据

在游戏框架中，凡是出现"我需要从两个方向互相查找"的场景，`DoubleMap` 都是第一选择。用它，比自己维护两张 `Dictionary` 更安全、更清晰。
