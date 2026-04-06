---
title: 通用对象池的接口设计与线程安全
published: 2026-03-30
description: "深度解析 IObjectPool 接口解耦、PooledObject using 自动回收、Stack+lock 线程安全实现，以及三计数器的设计意义。"
tags: [Unity, 框架设计]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

## 为什么这样设计（第一性原理）

游戏中频繁创建销毁对象（子弹、特效、日志列表等）会产生大量 GC 压力，导致帧率抖动。对象池是最直接的解法：**预先分配对象，用完归还而不销毁，下次直接复用**。

但对象池的实现往往陷入两个极端：
- **太具体**：每种类型一个池，代码重复，无法统一管理
- **太抽象**：过度泛化导致使用复杂，开发者每次都要查文档才知道怎么用

**第一性原理的解法**：
1. 用接口 `IObjectPool<T>` 定义契约，不绑定具体实现
2. 用 `PooledObject<T>` 结合 `using` 语法，让归还操作"消失"——开发者只需写业务代码，不用记得手动 `Release`
3. 用泛型静态类（`ListPool<T>`、`DictionaryPool<T,K>` 等）提供"零配置"的常见容器池

---

## 源码解析

### 1. IObjectPool<T>：最小接口契约

```csharp
public interface IObjectPool<T> where T : class
{
    int CountInactive { get; }      // 池中待用对象数

    T Get();                        // 取出一个对象
    PooledObject<T> Get(out T v);   // 取出并返回 using 句柄
    void Release(T element);        // 归还一个对象
    void Clear();                   // 清空池
}
```

接口只有 4 个方法，极简。注意它**没有** `CountAll` 和 `CountActive`——这两个属性是实现细节，不是契约的一部分。这符合接口隔离原则：调用方只需要知道"能取、能还、能查空闲数量"，不需要知道池的内部统计。

`where T : class` 约束保证了对象可以用 `null` 表示"不存在"，`ReferenceEquals` 比较有意义。

### 2. PooledObject<T>：using 语法糖自动回收

```csharp
public struct PooledObject<T> : IDisposable where T : class
{
    private readonly T m_ToReturn;          // 要归还的对象
    private readonly IObjectPool<T> m_Pool; // 归还到哪个池

    internal PooledObject(T value, IObjectPool<T> pool)
    {
        this.m_ToReturn = value;
        this.m_Pool = pool;
    }

    void IDisposable.Dispose() => this.m_Pool.Release(this.m_ToReturn);
}
```

这是整个对象池设计中**最精妙的部分**。`PooledObject<T>` 是一个**值类型（struct）**，实现了 `IDisposable`，可以配合 `using` 语句使用：

```csharp
// ✅ 标准用法：离开 using 块自动调用 Dispose()，自动归还对象
using (ListPool<int>.Get(out List<int> list))
{
    list.Add(1);
    list.Add(2);
    // 做业务...
} // 这里自动调用 PooledObject.Dispose() → pool.Release(list)

// ✅ C# 8+ 更简洁的写法
using var _ = ListPool<int>.Get(out List<int> list);
// list 在作用域结束时自动归还
```

**为什么 PooledObject 用 struct 而不是 class？**

如果是 class，`PooledObject` 本身就会产生一次堆分配，使用对象池反而增加了 GC 压力。struct 分配在栈上，生命周期结束时自动回收，没有任何堆分配开销。

### 3. ObjectPool<T> 核心实现：Stack + lock

```csharp
public class ObjectPool<T> : IDisposable, IObjectPool<T> where T : class
{
    private readonly Stack<T> m_Stack = new();

    public T Get()
    {
        T element;
        lock (m_Stack)  // ← 线程安全
        {
            if (m_Stack.Count == 0)
            {
                element = m_CreateFunc.Invoke();
                CountAll++;  // 只在创建时递增
            }
            else
            {
                element = m_Stack.Pop();
            }
        }
        m_ActionOnGet?.Invoke(element);  // 取出回调（lock 外执行，减少锁粒度）
        return element;
    }

    public void Release(T element)
    {
        lock (m_Stack)
        {
            // 防重复归还检查
            if (m_Stack.Count > 0 && ReferenceEquals(m_Stack.Peek(), element))
                Log.Error("Internal error. Trying to destroy object that is already released to pool.");

            m_ActionOnRelease?.Invoke(element);  // 归还前的清理回调（在 lock 内执行）
            m_Stack.Push(element);
        }
    }
}
```

**为什么用 Stack 而不是 Queue？**

Stack（后进先出）能更好地利用 CPU 缓存局部性：最近用过的对象在 CPU 缓存里还是热的，再次取出时缓存命中率更高。Queue（先进先出）会让对象在池里"冷却"更久，缓存效率更低。

**lock 的粒度设计**：

- `Get()` 中：lock 只包裹对 `m_Stack` 的操作，`m_ActionOnGet` 在 lock 外执行。理由是回调可能耗时，持锁时间应尽量短。
- `Release()` 中：`m_ActionOnRelease` 在 lock 内执行。理由是 Release 通常是清理操作（如 `list.Clear()`），必须在对象归还到池之前完成。

**防重复归还检查**：

```csharp
if (m_Stack.Count > 0 && ReferenceEquals(m_Stack.Peek(), element))
    Log.Error("Internal error. Trying to destroy object that is already released to pool.");
```

用 `Peek()` 检查栈顶元素是否就是当前要归还的对象。这只能检测**连续两次归还同一对象**的情况（同一对象在 `Peek` 上），更复杂的重复归还（中间穿插了其他对象）无法检测，但能覆盖最常见的错误。

### 4. 三计数器的含义与设计

```csharp
public int CountAll { get; private set; }           // 池总共创建过的对象数
public int CountActive => CountAll - CountInactive;  // 当前被使用中的对象数
public int CountInactive                             // 池中空闲的对象数
{
    get
    {
        lock (m_Stack) { return m_Stack.Count; }
    }
}
```

三个计数器满足恒等式：**CountAll = CountActive + CountInactive**

| 计数器 | 含义 | 何时变化 |
|--------|------|---------|
| CountAll | 历史总创建数 | 仅在 `Get()` 创建新对象时 +1，`Clear()` 时归零 |
| CountInactive | 池中空闲数 | `Get()` 时 -1，`Release()` 时 +1 |
| CountActive | 使用中的数 | 派生值，不单独维护 |

**为什么 `CountAll` 不在 Release 时减少？**

因为 `Release` 是"归还"而不是"销毁"。对象还在池里，随时可以被 `Get()` 取出。`CountAll` 反映的是池管理的对象总数，只有调用 `Clear()`（真正销毁所有对象）时才应该归零。

**调试信息接口**：

```csharp
public string GetDebugInfo()
{
    return $"ListPool:{typeof(T)}\n" +
           $"Count All: {CountAll}, Count Active: {CountActive}, Count Inactive: {CountInactive}";
}
```

三计数器组合在一起，能立刻判断对象池的健康状态：
- `CountActive` 持续增大 → 有对象取出后没有归还，内存泄漏
- `CountAll` 远大于最大并发数 → 池的初始容量设置不合理，产生过多创建
- `CountInactive` 为 0 但 `CountActive` 很高 → 池枯竭，考虑预热

### 5. 泛型静态池：零配置的容器池

```csharp
public static class ListPool<T>
{
    private static readonly ObjectPool<List<T>> s_ListPool = 
        new(null, l => l?.Clear());  // 归还时自动 Clear

    public static List<T> Get() => s_ListPool.Get();
    public static PooledObject<List<T>> Get(out List<T> v) => s_ListPool.Get(out v);
    public static void Release(List<T> toRelease) => s_ListPool.Release(toRelease);
}
```

`DictionaryPool<T,K>`、`HashSetPool<T>`、`StackPool<T>`、`QueuePool<T>` 都是同样的模式。

**关键设计**：归还时的 `actionOnRelease` 传入 `l => l?.Clear()`，保证取出的容器总是空的，使用者不需要手动清理。

---

## 快速开新项目的方案/清单

### 直接可用的内置池

```csharp
// 使用 ListPool（推荐 using 写法）
using var _ = ListPool<int>.Get(out List<int> tempList);
tempList.Add(1); tempList.Add(2);
// 自动归还

// 使用 DictionaryPool
using var __ = DictionaryPool<string, int>.Get(out var dict);
dict["key"] = 1;

// 使用 HashSetPool
using var ___ = HashSetPool<long>.Get(out var idSet);
idSet.Add(entityId);
```

### 创建自定义对象池

```csharp
// 方式1：简单对象（无特殊初始化/清理逻辑）
var pool = new ObjectPool<MyData>(
    actionOnGet: null,
    actionOnRelease: data => data.Reset()  // 归还时重置状态
);

// 方式2：完整控制
var pool = new ObjectPool<MyData>(
    actionCreate: () => new MyData(),          // 自定义创建逻辑
    actionOnGet: data => data.OnGet(),         // 取出时回调
    actionOnRelease: data => data.OnRelease(), // 归还时回调
    actionOnDestroy: data => data.Destroy()    // Clear时回调
);

// 方式3：全局共享池（简单场景）
var pool = ObjectPool<MyData>.Shared;  // 无回调的零配置共享池
```

### 接入新项目步骤

- [ ] 复制 `Core/Pool/ObjectPool.cs` 到新项目（无外部依赖，独立可用）
- [ ] 临时容器操作全部改用 `ListPool<T>`/`DictionaryPool` 等静态池
- [ ] 高频实例化的业务对象（子弹、特效数据、网络包）创建专属 `ObjectPool<T>`
- [ ] 用 `using var _ = pool.Get(out T obj)` 替代手动 `Release`

### 注意事项

- ✅ 归还对象后不要再持有引用，对象可能被其他地方取出复用
- ✅ 对象的状态必须在归还时清理干净（通过 `actionOnRelease` 回调）
- ⚠️ `ObjectPool<T>` 中 `lock(m_Stack)` 支持多线程，但 Unity 主逻辑单线程时无需担心锁竞争
- ⚠️ `Shared` 静态池无任何回调，取出的对象状态未定义，使用前需手动初始化
- ⚠️ 不要在 `actionOnRelease` 回调中再次调用 `Release`，会导致递归死锁（lock 是不可重入的）
- ✅ `GetDebugInfo()` 是定位内存问题的利器，在 Debug 模式下定期打印池状态
