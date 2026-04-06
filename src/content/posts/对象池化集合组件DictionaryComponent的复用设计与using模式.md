---
title: 对象池化集合组件——DictionaryComponent 的复用设计与 using 模式
published: 2026-03-31
description: 深入解析 DictionaryComponent 的设计，理解继承原生集合类型的扩展模式、对象池复用减少 GC 的技术原理，以及如何用 using 语句优雅管理临时集合的生命周期。
tags: [Unity, ECS, 对象池, GC优化, 集合设计]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# 对象池化集合组件——DictionaryComponent 的复用设计与 using 模式

## 前言

在游戏开发中，`Dictionary`、`List`、`HashSet` 等集合容器是极其常用的数据结构。

但如果在游戏运行时频繁创建和销毁这些集合，会产生大量 GC 压力，导致帧率波动。

今天我们来分析 ECS 框架中的解决方案——以 `DictionaryComponent` 为代表的对象池化集合组件。

```csharp
public class DictionaryComponent<T, K>: Dictionary<T, K>, IDisposable
{
    public static DictionaryComponent<T, K> Create(int capacity = 0)
    {
        DictionaryComponent<T, K> dict;
        
        if (ObjectPool.Instance == null)
        {
            dict = new DictionaryComponent<T, K>();
        }
        else
        {
            dict = ObjectPool.Instance.Fetch<DictionaryComponent<T, K>>();
        }
        
        if (capacity > 0)
        {
            dict.EnsureCapacity(capacity);
        }
        
        return dict;
    }

    public void Dispose()
    {
        this.Clear();
        ObjectPool.Instance.Recycle(this);
    }
}
```

---

## 一、继承原生集合——无缝的 API 兼容

```csharp
public class DictionaryComponent<T, K>: Dictionary<T, K>, IDisposable
```

`DictionaryComponent<T, K>` 继承自 `Dictionary<T, K>`。

这意味着 `DictionaryComponent` **就是** `Dictionary`——所有 `Dictionary` 的方法（`Add`、`TryGetValue`、`ContainsKey`、LINQ 扩展等）都可以直接使用，没有任何包装层的开销：

```csharp
using var dict = DictionaryComponent<int, string>.Create();

// 完全像 Dictionary 一样使用
dict.Add(1, "one");
dict[2] = "two";
if (dict.TryGetValue(1, out var value)) { ... }
foreach (var kv in dict) { ... }
```

**与包装器（Wrapper）模式的对比**：

```csharp
// 包装器模式（常见但有额外开销）
public class DictionaryWrapper<T, K>
{
    private Dictionary<T, K> _inner = new();
    
    public void Add(T key, K value) => _inner.Add(key, value);
    // 需要手动代理所有 Dictionary 方法
}

// 继承模式（DictionaryComponent 的方式）
public class DictionaryComponent<T, K>: Dictionary<T, K>
{
    // 不需要代理任何方法，直接继承所有能力
}
```

继承模式代码更少，性能更好（无包装调用开销），使用方式与原生类型完全一致。

---

## 二、对象池集成——Create 工厂方法

```csharp
public static DictionaryComponent<T, K> Create(int capacity = 0)
{
    DictionaryComponent<T, K> dict;
    
    if (ObjectPool.Instance == null)
    {
        dict = new DictionaryComponent<T, K>();
    }
    else
    {
        dict = ObjectPool.Instance.Fetch<DictionaryComponent<T, K>>();
    }
    
    if (capacity > 0)
    {
        dict.EnsureCapacity(capacity);
    }
    
    return dict;
}
```

### 2.1 空值安全的对象池访问

```csharp
if (ObjectPool.Instance == null)
{
    dict = new DictionaryComponent<T, K>();
}
else
{
    dict = ObjectPool.Instance.Fetch<DictionaryComponent<T, K>>();
}
```

如果 `ObjectPool.Instance` 为 null（在单元测试或早期初始化阶段），就直接 `new`，不崩溃。

这是**优雅降级**：有池就用池，没池就正常创建，API 保持一致。

### 2.2 EnsureCapacity——预分配内存

```csharp
if (capacity > 0)
{
    dict.EnsureCapacity(capacity);
}
```

如果知道大概需要多少元素，可以预先分配桶的数量：

```csharp
// 知道要存 100 个元素
using var dict = DictionaryComponent<int, Player>.Create(100);
```

`EnsureCapacity` 会提前分配足够的内部数组，避免在添加元素时频繁扩容（每次扩容都会重新哈希，有 GC 分配）。

---

## 三、IDisposable + using——生命周期的优雅管理

```csharp
public void Dispose()
{
    this.Clear();
    ObjectPool.Instance.Recycle(this);
}
```

`Dispose` 做两件事：
1. `Clear()`：清空所有键值对
2. `Recycle(this)`：放回对象池，等待复用

配合 C# 的 `using` 语句，可以写出非常优雅的代码：

```csharp
// using 块——方法返回时自动 Dispose
using var dict = DictionaryComponent<int, string>.Create();

dict.Add(1, "one");
dict.Add(2, "two");
// ... 使用字典

// 方法结束时，dict.Dispose() 自动被调用，清空并放回池
```

**与手动管理的对比**：

```csharp
// 手动管理（容易忘记）
var dict = DictionaryComponent<int, string>.Create();
try
{
    // ... 使用
    dict.Dispose(); // 万一中途 return 了，这行不会执行！
}
catch
{
    dict.Dispose(); // 还要在 catch 里写一遍
}

// using 管理（自动、安全）
using var dict = DictionaryComponent<int, string>.Create();
// ... 无论 return 还是异常，Dispose 一定会被调用
```

`using` 语句（或 `using` 声明）是 C# 的"RAII"实现——资源获取即初始化，作用域结束自动释放。

---

## 四、对象池的工作原理

```
第一次 Create：
  ObjectPool.Fetch<DictionaryComponent<int,string>> 
  → 池是空的 → new DictionaryComponent<int,string>()
  → 返回新对象
  
使用中...

Dispose：
  dict.Clear()
  ObjectPool.Recycle(dict)
  → 对象放入池中

第二次 Create：
  ObjectPool.Fetch<DictionaryComponent<int,string>>
  → 池有对象 → 直接取出，不 new
  → 返回复用对象
```

**关键点**：`Clear()` 在放回池之前调用，保证从池里取出的对象是空的（"干净"的状态）。

如果不 Clear 就放回，下次取出时里面还有旧数据，会造成数据污染。

---

## 五、在框架代码中的实际使用

在 `EntityDispatcherComponentSystem.Load` 中：

```csharp
[EntitySystem]
private static void Load(this EntityDispatcherComponent self)
{
    self.Handlers.Clear();
    var types = EventSystem.Instance.GetTypes(typeof(HandlerAttribute));
    
    using var lst = ListComponent<Type>.Create(); // 使用 using 管理临时 List
    foreach (var type in types)
    {
        lst.Add(type);
    }
    EntityDispatcherComponent.LoadHandlers(lst, self.Handlers);
    // 方法返回时，lst 自动 Dispose，放回对象池
}
```

`lst` 是一个临时的 `List<Type>`，只在方法内使用。用 `ListComponent.Create()` + `using`，确保这个临时集合用完后放回对象池，不产生 GC。

---

## 六、性能分析

**传统写法的 GC 开销**：

```csharp
// 每次调用都产生一个新的 Dictionary 对象
var dict = new Dictionary<int, string>();
// ... 使用
// 方法返回，dict 变成垃圾，等待 GC 回收
```

**DictionaryComponent 的 GC 开销**：

```csharp
using var dict = DictionaryComponent<int, string>.Create();
// 从池中取出，不产生 new（GC 分配）
// ... 使用
// Dispose 放回池，不产生垃圾
```

**第一次创建后**，后续使用 `DictionaryComponent` 的 GC 开销接近于零（只有对象内部数据结构扩容时才产生分配）。

对于每帧创建数十甚至上百个临时集合的游戏逻辑，这个优化效果非常显著。

---

## 七、同族集合组件对比

框架中有一系列类似的集合组件：

| 组件 | 继承自 | 适用场景 |
|---|---|---|
| `ListComponent<T>` | `List<T>` | 有序、可重复元素 |
| `DictionaryComponent<T,K>` | `Dictionary<T,K>` | 键值对查找 |
| `StackComponent<T>` | `Stack<T>` | LIFO 临时缓存 |
| `HashSetComponent<T>` | `HashSet<T>` | 去重、快速存在性检测 |
| `EnumerableComponent<TSource,TResult>` | 实现 IEnumerable | 懒过滤+转换迭代器 |

所有集合组件遵循相同的模式：
1. 继承原生集合类型（复用 API）
2. 提供静态 `Create()` 工厂方法（从池获取）
3. 实现 `Dispose()`（清空+放回池）

---

## 八、写给初学者

`DictionaryComponent` 是一个"小而美"的设计：

**问题**：临时集合频繁创建销毁，产生 GC 压力。
**解决**：对象池化 + IDisposable + using 语句。
**手段**：继承原生集合（不失去任何功能），只添加池化管理。

这个设计很容易理解，也很容易在自己的项目中应用。

经验法则：
- 需要大量临时集合的代码（如每帧遍历、批量处理）→ 使用 `XxxComponent` + `using`
- 长期持有的集合（如实体的数据字典）→ 普通 `Dictionary<T,K>`

合理区分两种用途，GC 压力会大幅降低。
