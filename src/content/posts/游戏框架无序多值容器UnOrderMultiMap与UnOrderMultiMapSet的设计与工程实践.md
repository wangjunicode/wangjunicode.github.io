---
title: 游戏框架无序多值容器UnOrderMultiMap与UnOrderMultiMapSet的设计与工程实践
published: 2026-04-14
description: 深度解析游戏框架中 UnOrderMultiMap 和 UnOrderMultiMapSet 两个无序多值映射容器的源码设计，对比有序与无序容器的适用场景，探讨一键多值存储、安全增删、自动清理空 Key 等工程技巧在游戏开发中的实际应用。
tags: [Unity, 数据结构, 容器设计, 多值映射, 游戏框架, CSharp]
category: 游戏框架源码解析
draft: false
encryptedKey: henhaoji123
---

## 前言

在游戏开发中，**一个 Key 对应多个 Value** 的场景随处可见：一个技能 ID 对应多个 Buff 实例、一个事件类型对应多个监听者、一个场景 ID 对应多个激活实体……

C# 标准库没有原生的多值字典，通常需要用 `Dictionary<K, List<V>>` 或 `Dictionary<K, HashSet<V>>` 自行封装。本篇从框架源码 `UnOrderMultiMap.cs` 和 `UnOrderMultiMapSet.cs` 出发，看看这两个容器是如何解决这类问题的。

---

## 一、两个容器的定位对比

| 特性 | `UnOrderMultiMap<T, K>` | `UnOrderMultiMapSet<T, K>` |
|------|------------------------|--------------------------|
| 底层值容器 | `List<K>`（有序，允许重复） | `HashSet<K>`（无序，自动去重） |
| 同一 Key 下 Value 重复 | ✅ 允许 | ❌ 自动去重 |
| 插入顺序 | 保留插入顺序 | 不保证顺序 |
| 适用场景 | 伤害事件、帧同步命令队列 | 监听者注册、状态标签集合 |
| Count 语义 | 各 Key 的 List.Count 之和 | 各 Key 的 HashSet.Count 之和 |

两者都继承自 `Dictionary<T, 值容器>`，复用了 Dictionary 的哈希查找能力（O(1) 平均复杂度），区别只在于"同一 Key 下的值如何组织"。

---

## 二、UnOrderMultiMap 源码解析

### 2.1 核心增删操作

```csharp
public class UnOrderMultiMap<T, K>: Dictionary<T, List<K>>
{
    public void Add(T t, K k)
    {
        List<K> list;
        this.TryGetValue(t, out list);
        if (list == null)
        {
            list = new List<K>();
            base[t] = list;
        }
        list.Add(k);
    }

    public bool Remove(T t, K k)
    {
        List<K> list;
        this.TryGetValue(t, out list);
        if (list == null)    return false;
        if (!list.Remove(k)) return false;
        
        if (list.Count == 0)
            this.Remove(t);   // 🔑 自动清理空 Key
        return true;
    }
}
```

**亮点：自动清理空 Key**

当某个 Key 下的最后一个 Value 被删除后，`Remove` 方法会自动将这个 Key 也从字典中移除。这个设计避免了"僵尸 Key 积累"问题——如果不清理，字典会随着游戏运行不断增大，导致遍历性能下降和内存浪费。

```csharp
// 假设 key=EventType.PlayerDead 下只剩一个监听者
map.Remove(EventType.PlayerDead, lastListener);
// 此时 map 中已不存在 EventType.PlayerDead 这个 key
// map.ContainsKey(EventType.PlayerDead) == false ✅
```

### 2.2 安全的索引器重写

```csharp
// ⚠️ 注意：重写了父类 Dictionary 的 this[T t] 索引器
public new List<K> this[T t]
{
    get
    {
        List<K> list;
        this.TryGetValue(t, out list);
        return list;  // Key 不存在时返回 null，而非抛异常
    }
}
```

标准 `Dictionary<K, V>` 的 `[]` 运算符在 Key 不存在时会抛 `KeyNotFoundException`。这里重写为**返回 null**，避免了高频访问时的异常开销，但调用方需要进行 null 检查：

```csharp
var list = map[someKey];
if (list != null)
{
    foreach (var item in list)
        // 处理...
}
```

### 2.3 GetAll vs this[T t] 的语义差异

```csharp
// 返回内部 List 的引用（直接修改会影响容器内部状态）
public new List<K> this[T t] { ... }

// 返回 copy，调用方持有独立数组，不影响容器
public K[] GetAll(T t)
{
    List<K> list;
    this.TryGetValue(t, out list);
    if (list == null) return Array.Empty<K>();
    return list.ToArray();  // 每次都 copy
}
```

**何时用哪个：**

| 场景 | 推荐方法 |
|------|---------|
| 只读遍历，不会修改容器 | `this[t]` —— 零分配，性能好 |
| 遍历过程中可能触发增删 | `GetAll(t)` —— 安全快照，避免 InvalidOperationException |
| 需要传给外部持有引用 | `GetAll(t)` —— 外部修改不影响容器 |

---

## 三、UnOrderMultiMapSet 源码解析

### 3.1 用 HashSet 实现天然去重

```csharp
public class UnOrderMultiMapSet<T, K>: Dictionary<T, HashSet<K>>
{
    public void Add(T t, K k)
    {
        HashSet<K> set;
        this.TryGetValue(t, out set);
        if (set == null)
        {
            set = new HashSet<K>();
            base[t] = set;
        }
        set.Add(k);  // HashSet.Add 对重复值静默忽略
    }
    
    public bool Remove(T t, K k)
    {
        // ... 同样有自动清理空 Key 的逻辑
        if (set.Count == 0)
            this.Remove(t);
        return true;
    }
}
```

`HashSet.Add` 的特性：若元素已存在，直接返回 false 且不抛异常。这使得 `UnOrderMultiMapSet` 天然支持**幂等注册**——同一个监听者注册两次只会保留一份，完全不需要调用方做额外检查。

### 3.2 重写 Count 属性

```csharp
public new int Count
{
    get
    {
        int count = 0;
        foreach (KeyValuePair<T, HashSet<K>> kv in this)
            count += kv.Value.Count;
        return count;
    }
}
```

父类 `Dictionary.Count` 返回的是 Key 的数量，但对于多值字典，更有意义的是**所有 Value 的总数量**。这里重写了 `Count`，返回所有 HashSet 中元素的总和。

> ⚠️ 注意：这个 `Count` 是 O(N) 复杂度（N 为 Key 数），不应在每帧高频调用。如果需要跟踪总数，建议在外部维护一个计数器，Add/Remove 时同步更新。

### 3.3 GetDictionary 暴露底层

```csharp
public Dictionary<T, HashSet<K>> GetDictionary()
{
    return this;
}
```

这个方法的存在有些微妙——`UnOrderMultiMapSet` 本身就是 `Dictionary<T, HashSet<K>>`，返回 `this` 的转型。它的实际用途是**在需要具体类型 `Dictionary` 而非 `UnOrderMultiMapSet` 引用时提供类型转换**，避免 new keyword shadow 带来的方法解析歧义。

---

## 四、与 HashSetComponent 的组合使用

框架中还有一个配套的 `HashSetComponent<T>`：

```csharp
public class HashSetComponent<T>: HashSet<T>, IDisposable
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

`HashSetComponent` 继承自 `HashSet<T>` 并接入了对象池，通过 `using` 语句可以实现零 GC 的临时 Set 操作：

```csharp
// 在 UnOrderMultiMapSet 遍历时需要临时 Set，用 HashSetComponent 避免 GC
using (var tempSet = HashSetComponent<int>.Create())
{
    foreach (var k in multiMapSet[key])
        tempSet.Add(k);
    // 处理 tempSet...
}   // Dispose() 自动归还对象池
```

---

## 五、实际游戏应用场景

### 5.1 事件系统（UnOrderMultiMapSet 典型场景）

```csharp
// 事件监听者注册表：同一事件类型可有多个监听者，同一监听者不重复注册
private UnOrderMultiMapSet<int, Action<EventArgs>> eventListeners 
    = new UnOrderMultiMapSet<int, Action<EventArgs>>();

public void Subscribe(int eventType, Action<EventArgs> listener)
{
    eventListeners.Add(eventType, listener);
    // 重复订阅自动去重，无需检查
}

public void Dispatch(int eventType, EventArgs args)
{
    var listeners = eventListeners[eventType];
    if (listeners == null) return;
    
    // 注意：若 Dispatch 过程中可能触发 Unsubscribe，需要先 copy
    foreach (var listener in listeners.ToArray())
        listener.Invoke(args);
}
```

### 5.2 帧同步命令缓冲（UnOrderMultiMap 典型场景）

```csharp
// 帧命令缓冲：同一帧可有多条命令，命令允许重复（不同玩家的相同操作）
private UnOrderMultiMap<int, FrameCommand> frameCommands 
    = new UnOrderMultiMap<int, FrameCommand>();

public void AddCommand(int frameId, FrameCommand cmd)
{
    frameCommands.Add(frameId, cmd);
}

public FrameCommand[] ConsumeFrame(int frameId)
{
    var cmds = frameCommands.GetAll(frameId);  // 快照避免并发问题
    frameCommands.Remove(frameId);             // 消费后清除整个 Key
    return cmds;
}
```

### 5.3 AOI 兴趣区域管理

```csharp
// 格子 → 实体集合，同一格子不重复存储同一实体
private UnOrderMultiMapSet<Vector2Int, int> gridEntities 
    = new UnOrderMultiMapSet<Vector2Int, int>();

public void EnterGrid(Vector2Int grid, int entityId)
{
    gridEntities.Add(grid, entityId);
}

public void LeaveGrid(Vector2Int grid, int entityId)
{
    gridEntities.Remove(grid, entityId);
    // 格子内最后一个实体离开后，格子 Key 自动清理
}
```

---

## 六、性能注意事项

### 6.1 避免在热路径中创建 List/HashSet

`Add` 方法在 Key 首次出现时会 `new List<K>()` 或 `new HashSet<K>()`，产生 GC。对于高频增删的场景，建议预热：

```csharp
// 预热：预先为已知 Key 创建空容器
foreach (var key in knownKeys)
    map.Add(key, default(K));  // 先建立 Key → 空容器映射
map.Remove(key, default(K));   // 然后移除哨兵值，保留空容器
```

或者改用支持对象池的自定义容器（框架中 `ListComponent<T>` + `UnOrderMultiMap` 的组合）。

### 6.2 Contains 的时间复杂度

| 容器 | Contains(t, k) 复杂度 |
|------|----------------------|
| `UnOrderMultiMap` | O(1) 找 Key + O(N) 在 List 中线性搜索 |
| `UnOrderMultiMapSet` | O(1) 找 Key + O(1) HashSet 查找 |

当 Value 数量较多时（>10），`UnOrderMultiMapSet` 的 `Contains` 明显优于 `UnOrderMultiMap`。

---

## 七、总结

| 设计要点 | 具体体现 |
|---------|---------|
| 自动清理空 Key | Remove 最后一个 Value 时同步删除 Key，防止字典膨胀 |
| 安全索引器 | Key 不存在时返回 null 而非抛异常 |
| 快照 vs 引用 | GetAll 返回 copy，this[] 返回引用，调用方按需选择 |
| 幂等注册 | UnOrderMultiMapSet 利用 HashSet 特性天然支持 |
| Count 语义重定义 | 返回所有 Value 总数而非 Key 数，更符合多值容器直觉 |

`UnOrderMultiMap` 和 `UnOrderMultiMapSet` 是游戏框架工具库中使用频率极高的两个容器，理解它们的设计细节——特别是**自动 Key 清理**和**索引器语义差异**——是写出健壮游戏框架代码的基础之一。
