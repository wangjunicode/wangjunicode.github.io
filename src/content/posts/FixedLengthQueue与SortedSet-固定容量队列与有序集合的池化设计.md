---
title: FixedLengthQueue 与 SortedSet：固定容量队列与有序集合的池化设计
published: 2026-04-17
description: 深入解析游戏框架中 FixedLengthQueue<T>（定长队列，超出自动淘汰）与 SortedSet<T>（基于 ObjectPool 的对象池化有序集合）的设计思路及典型使用场景。
tags: [CSharp, 游戏框架, 数据结构, 队列, 对象池, SortedSet]
category: Unity游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

# FixedLengthQueue 与 SortedSet：固定容量队列与有序集合的池化设计

游戏框架的 Core 层有两个看起来不起眼但极为实用的数据结构：`FixedLengthQueue<T>` 和 `SortedSet<T>`。一个解决"滚动窗口"问题，一个解决"有序集合复用"问题，合在一起聊更有意思。

---

## FixedLengthQueue：永不溢出的定长队列

### 问题背景

游戏中有大量需要保留"最近 N 条"的场景：

- 战斗日志只保留最近 100 条
- 技能释放历史记录最近 20 次
- 网络延迟采样窗口保留最近 30 帧

如果用普通 `Queue<T>`，需要在每次 Enqueue 之前手动检查 Count，超出了还要 Dequeue 丢弃，逻辑分散在各处。`FixedLengthQueue<T>` 把这个模式封装成了一个内聚的容器。

### 源码解析

```csharp
public class FixedLengthQueue<T> : Queue<T>
{
    private readonly int _length = 1;

    public FixedLengthQueue(int length) : base(length)
    {
        this._length = length;
    }

    public virtual void Enqueue(T item)
    {
        if (base.Count >= _length)
        {
            var t = base.Dequeue();
            OnDrop(t);
        }
        base.Enqueue(item);
    }

    protected virtual void OnDrop(T item)
    {
        // 子类可以重写，处理被淘汰的元素
    }

    public bool IsEmpty => base.Count == 0;
}
```

**继承而不是组合**：`FixedLengthQueue<T>` 直接继承 `Queue<T>`，这意味着它拥有所有原生队列的方法（Peek、Dequeue、Contains 等），只重写了 `Enqueue` 来注入容量控制逻辑。

**OnDrop 钩子**：当旧元素被淘汰时，`OnDrop(T item)` 会被调用。默认是空实现，但子类可以重写，比如：

```csharp
public class BattleLogQueue : FixedLengthQueue<BattleLog>
{
    public BattleLogQueue() : base(100) { }

    protected override void OnDrop(BattleLog log)
    {
        // 被淘汰的日志归还到对象池
        ObjectPool.Instance.Recycle(log);
    }
}
```

这是一个漂亮的设计：**容器自己管理元素的生命周期**，外部调用方只管往里 Enqueue，不用关心旧数据的处理。

### 注意：new 修饰符的隐患

```csharp
public virtual void Enqueue(T item)  // virtual，可以被重写
```

但 `Queue<T>.Enqueue` 在 .NET 中是**非虚方法**，`FixedLengthQueue` 的 `Enqueue` 实际上是用 `new` 隐藏而非 `override` 覆盖。

这意味着：

```csharp
FixedLengthQueue<int> flq = new FixedLengthQueue<int>(3);
flq.Enqueue(1); // ✅ 走定长逻辑

Queue<int> q = flq; // 当作基类引用
q.Enqueue(1); // ⚠️ 绕过了容量控制！走的是 Queue<T>.Enqueue
```

所以在使用时，**始终用 `FixedLengthQueue<T>` 类型持有引用**，不要向上转型成 `Queue<T>`。

### 典型使用场景

```csharp
// 网络延迟采样，保留最近 30 帧的 RTT
var rttWindow = new FixedLengthQueue<float>(30);

void OnFrameReceived(float rtt)
{
    rttWindow.Enqueue(rtt);
}

float GetAverageRtt()
{
    if (rttWindow.IsEmpty) return 0f;
    return rttWindow.Average(); // 继承了 Queue<T>，可以用 LINQ
}
```

```csharp
// 战斗连击检测，记录最近 5 次攻击时间戳
var attackTimes = new FixedLengthQueue<float>(5);

void OnAttack()
{
    attackTimes.Enqueue(Time.time);
    if (IsCombo()) TriggerComboEffect();
}
```

---

## SortedSet：对象池化的有序集合

### 源码解析

```csharp
public class SortedSet<T> : System.Collections.Generic.SortedSet<T>, IDisposable
{
    public static SortedSet<T> Create()
    {
        return ObjectPool.Instance.Fetch(typeof(SortedSet<T>)) as SortedSet<T>;
    }

    public void Dispose()
    {
        this.Clear();
        ObjectPool.Instance.Recycle(this);
    }
}
```

这个设计模式和 `HashSetComponent<T>` 如出一辙——**对标准集合类型加一层对象池包装**。框架中还有类似的：

| 类型 | 基类 | 用途 |
|------|------|------|
| `HashSetComponent<T>` | `HashSet<T>` | 池化哈希集合 |
| `SortedSet<T>` | `System.SortedSet<T>` | 池化有序集合 |
| `ListComponent<T>` | `List<T>` | 池化列表 |
| `DictionaryComponent<K,V>` | `Dictionary<K,V>` | 池化字典 |

**一致的约定**：所有这些组件都遵循相同的模式：
- `Create()` — 从对象池取出（或新建）
- `Dispose()` — 清空并归还到对象池

使用时配合 `using` 语句，确保用完后自动归还：

```csharp
using var sortedSet = SortedSet<int>.Create();
sortedSet.Add(5);
sortedSet.Add(2);
sortedSet.Add(8);
// foreach 遍历时已经是有序的：2, 5, 8
foreach (var v in sortedSet)
{
    ProcessInOrder(v);
}
// using 块结束，自动 Dispose，归还到对象池
```

### SortedSet 的优势：自动排序 + 去重

`SortedSet<T>` 和 `List<T>` 的区别：

```csharp
// List 需要手动排序
var list = new List<int> { 5, 2, 8, 2 };
list.Sort(); // [2, 2, 5, 8] — 保留重复

// SortedSet 插入时自动排序，且去重
var set = new SortedSet<int> { 5, 2, 8, 2 };
// 结果：[2, 5, 8] — 自动排序且去重
```

### 游戏中的典型应用

**技能优先级排序**：

```csharp
// 用优先级做 Key，自动按优先级排序
var skillPriorities = SortedSet<int>.Create();
skillPriorities.Add(skill.Priority);

// 取最高优先级
int highestPriority = skillPriorities.Max;
```

**行动顺序管理**（回合制游戏）：

```csharp
// 按速度值排序所有参战单位
using var actionOrder = SortedSet<(int speed, long entityId)>.Create();
foreach (var unit in battleUnits)
{
    actionOrder.Add((unit.Speed, unit.Id));
}
// 遍历时自动从低速到高速（或用 Reverse() 从高到低）
```

**去重计分板**：

```csharp
// 记录本局游戏中出现过的伤害值（去重）
using var damageValues = SortedSet<int>.Create();
damageValues.Add(damage);
// Min 最小伤害，Max 最大伤害
```

---

## 对象池模式的深层意义

这两个类放在一起看，体现了框架的一个核心理念：**集合对象的生命周期应该被显式管理**。

游戏中集合的使用往往是短暂的——一帧内临时收集数据、一次技能释放收集目标、一次 UI 刷新收集需要更新的元素。如果每次都 `new`，GC 压力极大；如果用对象池，就能做到零 GC 分配。

`FixedLengthQueue` 和 `SortedSet` 代表了两种不同的封装策略：

- `FixedLengthQueue`：**行为封装**——改变了容器的语义（容量上限 + 淘汰钩子）
- `SortedSet`：**生命周期封装**——不改变语义，只添加池化能力

这两种策略分别解决了"如何用"和"何时释放"的问题，是游戏框架工具类设计的两种典型范式。

---

## 小结

| 特性 | FixedLengthQueue<T> | SortedSet<T> |
|------|---------------------|--------------|
| 核心价值 | 滚动窗口，自动淘汰旧数据 | 插入时自动排序 + 去重 |
| 内存策略 | 固定上限，不扩容 | 对象池复用，零 GC |
| 扩展点 | OnDrop 钩子 | 标准 SortedSet API |
| 使用场景 | 日志、采样窗口、历史记录 | 优先级队列、行动顺序 |

两者都是"把一个常见模式封装成一个有意图的类型"的典范。代码量不多，但每次使用时节省的心智负担是真实的。
