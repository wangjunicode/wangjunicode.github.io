---
title: 事件类型注册表与有序字典——EventMap 和自定义 SortedDictionary 解析
published: 2026-03-31
description: 解析游戏脚本事件类型注册表 EventMap 的懒加载反射设计，以及自定义 SortedDictionary 基于红黑树的有序键值对实现，理解两种数据结构在游戏框架中的不同适用场景。
tags: [Unity, ECS, 反射, 数据结构, 红黑树]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 事件类型注册表与有序字典——EventMap 和自定义 SortedDictionary 解析

## 前言

游戏框架中有两类重要的数据结构需求：

1. **运行时类型查找**：游戏脚本系统需要知道有哪些事件类型
2. **有序键值对存储**：某些场景需要按键有序存储数据（如定时器按帧排序）

今天我们来分析满足这两种需求的实现：`EventMap` 和自定义 `SortedDictionary`。

---

## 一、EventMap——脚本事件类型的注册表

```csharp
public class EventMap
{
    private static Dictionary<string, Type> s_eventDict;
    private static List<Type> s_eventTypeList;
    private static Dictionary<Type, string> s_eventNameDict;

    public static List<Type> GetEventTypes()
    {
        if (s_eventDict == null)
        {
            s_eventDict = new();
            var types = Framework.ReflectUtil.GetTypes();
            foreach (var type in types)
            {
                if (typeof(IScriptEventArg).IsAssignableFrom(type))
                {
                    s_eventDict.Add(type.Name, type);
                }
            }
            s_eventTypeList = s_eventDict.Values.ToList();
        }
        return s_eventTypeList;
    }
```

### 1.1 懒加载的类型扫描

```csharp
if (s_eventDict == null)
{
    s_eventDict = new();
    var types = Framework.ReflectUtil.GetTypes();
    // ...
}
```

第一次调用 `GetEventTypes()` 时，通过反射扫描所有程序集，找出所有实现了 `IScriptEventArg` 的类型。

**为什么用懒加载？**

反射扫描是耗时操作（需要遍历所有程序集的所有类型）。懒加载将这个开销推迟到真正需要时（通常是游戏启动后玩家进入主界面，不影响启动时的体验）。

### 1.2 三个不同维度的索引

```csharp
private static Dictionary<string, Type> s_eventDict;     // 名字 → 类型
private static List<Type> s_eventTypeList;                // 类型列表（顺序访问）
private static Dictionary<Type, string> s_eventNameDict;  // 类型 → 名字
```

三种不同的查询需求：

1. **`GetEventTypes()`**：获取所有事件类型列表（用于 Handler 注册，如 `EntityDispatcherComponent.LoadHandlers`）
2. **`GetEventType(string name)`**：通过名字字符串找类型（用于序列化/反序列化：从存档的字符串还原类型）
3. **`GetEventName(Type type)`**：通过类型找名字（用于序列化：将类型转换为字符串存储）

### 1.3 GetEventName 的双重字典

```csharp
public static string GetEventName(Type type)
{
    if (s_eventNameDict == null)
    {
        s_eventNameDict = new();
    }
    if (s_eventNameDict.ContainsKey(type))
    {
        return s_eventNameDict[type];
    }
    s_eventNameDict.Add(type, type.Name);
    return s_eventNameDict[type];
}
```

注意这里也有缓存：`type.Name` 本身是一个字符串属性访问，不需要缓存。但通过 `s_eventNameDict` 缓存，可以：
1. 避免每次都访问 `type.Name`（虽然开销很小）
2. 允许未来扩展（如"为某个类型设置自定义名称"）

---

## 二、SortedDictionary——基于红黑树的有序字典

ECS 框架中实现了自定义的 `SortedDictionary<TKey, TValue>`，底层使用红黑树（`TreeSet<T>`）。

```csharp
public class SortedDictionary<TKey, TValue> : IDictionary<TKey, TValue>, ...
{
    private readonly TreeSet<KeyValuePair<TKey, TValue>> _set;

    public SortedDictionary() : this((IComparer<TKey>)null) { }
    
    public SortedDictionary(IComparer<TKey> comparer)
    {
        _set = new TreeSet<KeyValuePair<TKey, TValue>>(new KeyValuePairComparer(comparer));
    }
}
```

### 2.1 为什么需要自定义 SortedDictionary？

.NET 标准库已经有 `System.Collections.Generic.SortedDictionary<TKey, TValue>`，为什么要自己实现一个？

原因可能有以下几点：

1. **序列化兼容性**：代码中有 `[Serializable]` 和 `TreeSet`（注释说"为了二进制序列化的向后兼容性"）
2. **特殊比较器需求**：`KeyValuePairComparer` 允许自定义键的比较逻辑
3. **服务端兼容**：确保在服务端（非 Unity 环境）下也能正确运行，不依赖 Unity 特有的版本

### 2.2 红黑树的核心优势

红黑树是一种自平衡的二叉搜索树，所有操作（查找、插入、删除）都保证 O(log n) 时间复杂度：

| 操作 | 普通字典 (Hash) | SortedDictionary (红黑树) |
|---|---|---|
| 查找 | O(1) 平均 | O(log n) |
| 插入 | O(1) 平均 | O(log n) |
| 删除 | O(1) 平均 | O(log n) |
| **有序遍历** | **O(n log n)（需先排序）** | **O(n)（直接有序）** |
| 范围查询 | 不支持 | 支持 |

**SortedDictionary 的核心价值**：键始终有序，遍历时自然得到有序结果，支持高效的范围查询。

### 2.3 在定时器中的应用

回顾 `LogicTimerComponent`：

```csharp
private readonly MultiMap<long, long> TimeId = new();
```

这里用的是 `MultiMap`（可能基于 `SortedDictionary`），键是帧数（long），值是定时器ID列表。

由于键有序，可以高效地找到所有"已到期"的定时器：

```csharp
foreach (KeyValuePair<long, List<long>> kv in this.TimeId)
{
    long k = kv.Key;
    if (k > frameNow)
    {
        this.minTime = k; // 第一个大于当前帧的键，就是最早的未到期定时器
        break;
    }
    this.timeOutTime.Enqueue(k); // 所有小于等于当前帧的键都是到期的
}
```

如果用普通 `Dictionary`，这段逻辑就需要 O(n) 遍历所有定时器，然后过滤。有序字典让这个操作更高效。

### 2.4 TreeSet——禁止重复的有序集合

```csharp
public sealed class TreeSet<T> : SortedSet<T>
{
    internal override bool AddIfNotPresent(T item)
    {
        bool ret = base.AddIfNotPresent(item);
        if (!ret)
        {
            throw new ArgumentException($"SR.Argument_AddingDuplicate, {item}");
        }
        return ret;
    }
}
```

`TreeSet` 继承 `SortedSet`，但覆写了 `AddIfNotPresent`——**不允许重复元素，遇到重复直接抛异常**。

普通 `SortedSet` 遇到重复元素只是返回 `false`（静默失败）。`TreeSet` 改为抛异常（快速失败）。

这与 `SortedDictionary` 的语义一致：字典不允许重复键。

---

## 三、两者的对比

| | EventMap | SortedDictionary |
|---|---|---|
| 核心功能 | 类型注册表（字符串↔类型互转） | 有序键值对存储 |
| 底层结构 | 哈希字典 + 列表 | 红黑树 |
| 键查找 | O(1) | O(log n) |
| 有序遍历 | 不支持 | O(n) |
| 适用场景 | 脚本事件系统 | 定时器调度、优先队列 |

---

## 四、写给初学者

**EventMap 的启示**：当你需要"在运行时根据字符串找到类型"时，反射+缓存字典是标准解法。这在序列化、插件系统、脚本系统中非常常见。

**SortedDictionary 的启示**：数据结构的选择影响性能。如果你的数据需要有序访问、范围查询，红黑树（SortedDictionary/SortedSet）比哈希表更合适。如果只需要随机访问，哈希表（Dictionary/HashSet）更快。

理解每种数据结构的时间复杂度，在正确的场景选择正确的数据结构，是高效编程的基础。
