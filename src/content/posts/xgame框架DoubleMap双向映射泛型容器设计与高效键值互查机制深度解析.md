---
title: xgame框架DoubleMap双向映射泛型容器设计与高效键值互查机制深度解析
published: 2026-05-02
description: 深入解析 xgame/ET 框架中 DoubleMap<K,V> 双向映射容器的设计原理、双字典维护机制、互查接口实现及其在游戏开发中的实际应用场景
tags: [Unity, xgame, 数据结构, C#, 游戏框架]
category: Unity游戏框架
draft: false
encryptedKey: henhaoji123
---

## 前言

在游戏开发中，经常遇到需要**双向查找**的场景：已知 Key 查 Value，或者已知 Value 反查 Key。标准的 `Dictionary<K, V>` 只支持单向查找，如果要反向查找就必须遍历整个字典，性能较差。

xgame（基于 ET 框架）中封装了一个名为 `DoubleMap<K, V>` 的双向映射泛型容器，通过维护两个互为镜像的字典，实现了 O(1) 时间复杂度的双向查询。本文将深入解析其设计原理与实现细节。

---

## 一、核心设计：两个字典互为镜像

```csharp
public class DoubleMap<K, V>
{
    private readonly Dictionary<K, V> kv = new Dictionary<K, V>();
    private readonly Dictionary<V, K> vk = new Dictionary<V, K>();
    // ...
}
```

`DoubleMap` 内部维护两个字典：
- **`kv`**：正向字典，Key → Value
- **`vk`**：反向字典，Value → Key

这两个字典始终保持数据的一致性，任何写操作都会**同时更新两个字典**。

### 空间换时间

这是一种典型的"以空间换时间"策略：
- 内存占用翻倍（两个字典各存一份引用）
- 换取双向查询均为 O(1) 的性能

在游戏框架中，角色 ID ↔ 角色实体、技能名 ↔ 技能 ID 等双向映射关系非常常见，这种设计非常实用。

---

## 二、构造函数与容量预分配

```csharp
public DoubleMap()
{
}

public DoubleMap(int capacity)
{
    kv = new Dictionary<K, V>(capacity);
    vk = new Dictionary<V, K>(capacity);
}
```

支持带容量参数的构造函数，可以预分配字典大小，避免频繁扩容导致的性能抖动。在游戏初始化阶段，如果已知映射数据量（例如固定数量的配置表条目），推荐传入 `capacity` 参数。

---

## 三、写操作：严格的一致性校验

### 添加映射

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

`Add` 方法做了四重校验：
1. `key == null`：防止空 Key
2. `value == null`：防止空 Value
3. `kv.ContainsKey(key)`：防止重复 Key
4. `vk.ContainsKey(value)`：防止重复 Value（双向唯一性）

> ⚠️ **注意**：`DoubleMap` 要求 Key 和 Value 都必须唯一，这与普通字典只要求 Key 唯一不同。如果 Value 不唯一，反向字典就无法保证正确的反查结果。

这种严格校验虽然以"失败静默"（直接 return）的方式处理，但保证了两个字典的数据完整性。

### 按 Key 删除

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

删除时先从 `kv` 字典中找到对应的 `value`，然后同步删除 `vk` 中的反向映射，确保两个字典始终一致。

### 按 Value 删除

```csharp
public void RemoveByValue(V value)
{
    if (value == null) return;
    K key;
    if (!vk.TryGetValue(value, out key)) return;

    kv.Remove(key);
    vk.Remove(value);
}
```

对称设计，从 `vk` 反向查找 `key` 后同步清理两个字典。

---

## 四、读操作：双向 O(1) 查询

```csharp
public V GetValueByKey(K key)
{
    if (key != null && kv.ContainsKey(key))
    {
        return kv[key];
    }
    return default(V);
}

public K GetKeyByValue(V value)
{
    if (value != null && vk.ContainsKey(value))
    {
        return vk[value];
    }
    return default(K);
}
```

两个方向的查询都是对字典的直接索引，时间复杂度均为 **O(1)**。查找不到时返回对应类型的默认值（null 或 0 等）。

---

## 五、遍历与集合访问

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

public List<K> Keys => new List<K>(kv.Keys);
public List<V> Values => new List<V>(vk.Keys);
```

- `ForEach`：遍历所有映射对，以正向字典为基准
- `Keys`：返回所有 Key 的新列表副本（防止外部修改内部集合）
- `Values`：利用 `vk.Keys` 直接获取所有 Value（因为 Value 在反向字典中充当 Key）

### 为什么 Values 用 `vk.Keys` 而不是 `kv.Values`？

理论上两者等价，但 `vk.Keys` 是 `Dictionary<V, K>` 的 Key 集合，性能上与 `kv.Values` 相近。框架选择 `vk.Keys` 可能是一种风格统一，也可能是为了避免 `ICollection<V>` 的潜在歧义。

---

## 六、包含性检测

```csharp
public bool ContainsKey(K key)   => key != null && kv.ContainsKey(key);
public bool ContainsValue(V value) => value != null && vk.ContainsKey(value);

public bool Contains(K key, V value)
{
    if (key == null || value == null) return false;
    return kv.ContainsKey(key) && vk.ContainsKey(value);
}
```

`Contains(K, V)` 同时检测 Key 和 Value 是否都存在于映射中，这在校验"某个键值对是否完整存在"时非常有用，比单独检测更语义明确。

---

## 七、典型应用场景

### 场景一：角色 ID ↔ 网络连接

```csharp
private DoubleMap<long, Session> playerSessionMap = new DoubleMap<long, Session>();

// 玩家上线
playerSessionMap.Add(playerId, session);

// 根据 playerId 找到 Session
Session s = playerSessionMap.GetValueByKey(playerId);

// 根据 Session 找到 playerId（处理断线等逻辑）
long id = playerSessionMap.GetKeyByValue(session);

// 玩家下线
playerSessionMap.RemoveByKey(playerId);
```

### 场景二：枚举值 ↔ 字符串名称

```csharp
private DoubleMap<SkillType, string> skillNameMap = new DoubleMap<SkillType, string>();

skillNameMap.Add(SkillType.Fireball, "火球术");
string name = skillNameMap.GetValueByKey(SkillType.Fireball); // "火球术"
SkillType type = skillNameMap.GetKeyByValue("火球术");       // SkillType.Fireball
```

### 场景三：本地 ID ↔ 服务器 ID

在网络游戏中，客户端临时 ID 和服务器 ID 的双向映射是常见需求：

```csharp
private DoubleMap<int, long> localToServerIdMap = new DoubleMap<int, long>();

localToServerIdMap.Add(localId, serverId);
long sId = localToServerIdMap.GetValueByKey(localId);
int lId = localToServerIdMap.GetKeyByValue(serverId);
```

---

## 八、设计局限与注意事项

| 限制点 | 说明 |
|--------|------|
| Value 必须唯一 | 不支持多对一映射，若 Value 重复会静默忽略 Add |
| 不支持 null 键值 | Key 和 Value 均不能为 null |
| 无线程安全 | 多线程并发操作需要外部加锁 |
| 内存开销双倍 | 对于极大规模数据需要评估内存影响 |

---

## 九、与标准 Dictionary 的对比

| 特性 | Dictionary<K,V> | DoubleMap<K,V> |
|------|----------------|----------------|
| 正向查询（K→V） | O(1) | O(1) |
| 反向查询（V→K） | O(n) 遍历 | O(1) |
| 内存占用 | 1x | ~2x |
| Value 唯一性约束 | 无 | 有 |
| null 支持 | 可配置 | 不支持 |

---

## 总结

`DoubleMap<K, V>` 是 xgame 框架中一个精巧的实用工具类。它通过维护两个镜像字典，以可接受的内存代价换取了双向 O(1) 查询能力。其设计要点在于：

1. **写操作的严格一致性**：所有写操作同步更新两个字典
2. **双重唯一性约束**：Key 和 Value 都必须唯一
3. **防御性空值校验**：所有公开接口都进行 null 检查
4. **对称性设计**：按 Key 和按 Value 的操作完全对称

在游戏框架中，凡是需要双向查找的业务场景（ID映射、枚举对照、会话管理等），`DoubleMap` 都是比手动维护两个字典更加优雅、安全的解决方案。
