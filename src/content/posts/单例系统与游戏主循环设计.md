---
title: 单例系统与游戏主循环设计
published: 2026-03-30
description: "深度解析泛型单例约束与多队列驱动主循环的设计原理，总结可复用的游戏框架主循环方案。"
tags: [Unity, 框架设计]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

## 为什么这样设计（第一性原理）

游戏主循环是整个引擎的心跳。面对"如何管理全局服务"和"如何驱动每帧逻辑"这两个核心问题，最朴素的答案是：**全局单例 + Unity 的 MonoBehaviour 生命周期**。但这个方案有两个隐患：

1. **重复注册无法发现**：直接用静态字段，代码量一大就很容易在不同地方各自 `new` 一个，导致旧实例被悄悄替换，Bug 难以追踪。
2. **Update 分散在各 MonoBehaviour**：每个系统各自持有 MonoBehaviour，生命周期全靠 Unity 托管，无法控制执行顺序，也无法在热重载时统一销毁和重建。

**第一性原理的解法**：把"单例注册"和"帧驱动"都收归到一个中心节点——`Game` 静态类，所有 Singleton 都由它统一管理。Singleton 本身是纯 C# 对象，不依赖 MonoBehaviour，彻底解耦于 Unity 生命周期。

---

## 源码解析

### 1. Singleton 泛型约束防止重复注册

```csharp
public abstract class Singleton<T> : ISingleton where T : Singleton<T>, new()
{
    [StaticField]
    private static T instance;

    public void Register()
    {
        if (instance != null)
        {
            throw new Exception($"singleton register twice! {typeof(T).Name}");
        }
        instance = (T)this;
    }

    public void Destroy()
    {
        if (this.isDisposed) return;
        this.isDisposed = true;
        T t = instance;
        instance = null;
        t.Dispose();
    }
}
```

**关键点解析：**

- 泛型约束 `where T : Singleton<T>, new()` 是 CRTP（奇异递归模板）模式：`T` 必须是自身的子类，且可以 `new()`。这保证了 `instance = (T)this` 的类型安全，也保证了每个子类有独立的静态 `instance` 字段。
- `Register()` 中的 `instance != null` 检查是**防双注册的护城河**。一旦重复注册立刻抛异常，而不是默默覆盖，让问题在开发期暴露。
- `[StaticField]` 注解是框架约定的标记，用于热重载时的静态字段扫描清理——这是纯 C# 单例能支持热重载的关键。
- `Destroy()` 先置空 `instance` 再调 `Dispose()`，顺序很重要：先断开引用，再释放资源，避免在 Dispose 过程中其他地方还能拿到半死不活的实例。

### 2. Game 静态类：多队列驱动主循环

```csharp
public static class Game
{
    private static readonly Queue<ISingleton> updates        = new Queue<ISingleton>();
    private static readonly Queue<ISingleton> beforeFixedUpdates = new Queue<ISingleton>();
    private static readonly Queue<ISingleton> fixedUpdates   = new Queue<ISingleton>();
    private static readonly Queue<ISingleton> lateFixedUpdates = new Queue<ISingleton>();
    private static readonly Queue<ISingleton> lateUpdates    = new Queue<ISingleton>();
    private static readonly Queue<ETTask>     frameFinishTask = new Queue<ETTask>();
}
```

`Game` 同时维护 6 条队列，对应完整的帧生命周期：

| 队列 | 时机 | 典型用途 |
|------|------|---------|
| `beforeFixedUpdates` | FixedUpdate 前 | 物理输入采集 |
| `fixedUpdates` | 固定物理步 | 物理模拟、帧同步逻辑 |
| `lateFixedUpdates` | 固定步之后 | 物理结果后处理 |
| `updates` | 每帧 Update | 逻辑驱动 |
| `lateUpdates` | LateUpdate | 相机跟随、渲染同步 |
| `frameFinishTask` | 帧末 | 异步任务的帧内同步点 |

注册时按接口自动分流：

```csharp
public static void AddSingleton(ISingleton singleton)
{
    // ... 注册到 singletonTypes / singletons ...
    singleton.Register();

    if (singleton is ISingletonUpdate)        updates.Enqueue(singleton);
    if (singleton is ISingletonFixedUpdate)
    {
        beforeFixedUpdates.Enqueue(singleton);
        fixedUpdates.Enqueue(singleton);
        lateFixedUpdates.Enqueue(singleton);
    }
    if (singleton is ISingletonLateUpdate)    lateUpdates.Enqueue(singleton);
}
```

**这是接口隔离原则的完美体现**：Singleton 只需实现它关心的接口，不需要实现的就不出现在对应队列里，零运行时开销。

### 3. Queue 轮转的"快照"技巧

这是整个主循环中**最精妙的一个细节**：

```csharp
public static void Update()
{
    int count = updates.Count;  // ① 先快照当前数量
    while (count-- > 0)         // ② 只处理快照数量的元素
    {
        ISingleton singleton = updates.Dequeue();

        if (singleton.IsDisposed()) continue;  // ③ 跳过已销毁的
        if (singleton is not ISingletonUpdate update) continue;

        updates.Enqueue(singleton);  // ④ 放回队尾，形成轮转
        try { update.Update(); }
        catch (Exception e) { Log.Error(e); }
    }
}
```

**为什么要先记录 `count` 再循环？**

如果直接用 `while (queue.Count > 0)`，那么在 Update 过程中如果某个 Singleton 的 Update 触发了新的 Singleton 注册（也加入了 `updates` 队列），当前帧就会把新注册的对象也驱动一遍——这会导致当帧内出现逻辑不一致，甚至无限循环。

先快照 `count`，只处理"本帧开始时存在的对象"，新增的对象下一帧才会被处理，**保证了帧内处理集合的确定性**。

### 4. WaitFrameFinish 帧末等待

```csharp
public static async ETTask WaitFrameFinish()
{
    ETTask task = ETTask.Create(true);
    frameFinishTask.Enqueue(task);
    await task;
}

public static void FrameFinishUpdate()
{
    while (frameFinishTask.Count > 0)
    {
        ETTask task = frameFinishTask.Dequeue();
        task.SetResult();  // 触发所有等待帧末的协程继续执行
    }
}
```

`WaitFrameFinish()` 是一个精妙的同步原语：在异步代码中调用它，当前协程会暂停，等到本帧所有逻辑都执行完毕（`FrameFinishUpdate` 被 MonoBehaviour 在帧末调用），才会被唤醒继续执行。

**典型使用场景**：某个系统需要等所有 Update 都跑完后再做汇总计算，或者需要确保某个状态变更在下一帧生效。

### 5. 销毁顺序：LIFO（后进先出）

```csharp
public static void Close()
{
    while (singletons.Count > 0)
    {
        ISingleton iSingleton = singletons.Pop();  // Stack，后注册先销毁
        iSingleton.Destroy();
    }
    singletonTypes.Clear();
}
```

注册时用 `Stack.Push`，销毁时用 `Stack.Pop`——**后注册的先销毁**。这模仿了 C++ 的 RAII 析构顺序，保证依赖关系正确：如果 B 依赖 A，B 后注册，那么 B 必然先于 A 销毁，不会出现 B 还在使用 A 但 A 已经没了的情况。

---

## 快速开新项目的方案/清单

### 最小化移植清单

复制以下文件到新项目即可使用完整的 Singleton + 主循环体系：

```
Core/Singleton/Singleton.cs          // 单例基类
Core/Singleton/Game.cs               // 主循环中心节点
Core/Singleton/ISingleton*.cs        // ISingletonUpdate/FixedUpdate/LateUpdate 接口
```

### 接入 Unity 的胶水代码

```csharp
// GameEntry.cs（挂到场景里唯一的 GameObject）
public class GameEntry : MonoBehaviour
{
    void Update()            => Game.Update(Time.deltaTime, Time.realtimeSinceStartup);
    void FixedUpdate()       { Game.BeforeFixedUpdate(); Game.FixedUpdate(); Game.LateFixedUpdate(); }
    void LateUpdate()        { Game.LateUpdate(); Game.FrameFinishUpdate(); }
    void OnDestroy()         => Game.Close();
}
```

### 新建一个 Singleton 的模板

```csharp
public class MySystem : Singleton<MySystem>, ISingletonAwake, ISingletonUpdate
{
    public void Awake()
    {
        // 初始化
    }

    public void Update()
    {
        // 每帧逻辑
    }
}

// 启动时注册
Game.AddSingleton<MySystem>();
```

### 注意事项清单

- ✅ 所有 Singleton 必须通过 `Game.AddSingleton<T>()` 注册，不要直接 `new T()`
- ✅ 需要 Update 的系统实现 `ISingletonUpdate`，需要 FixedUpdate 实现 `ISingletonFixedUpdate`
- ✅ 销毁整个游戏时调用 `Game.Close()`，不要手动 Destroy 单个 Singleton
- ✅ 热重载时所有 `[StaticField]` 标记的静态字段会被框架清空，重新调用 `Game.AddSingleton` 重建
- ⚠️  Singleton 是纯 C# 对象，不要在其中直接使用需要 MonoBehaviour 的 Unity API（改用 GameEntry 中转）
- ⚠️  `WaitFrameFinish()` 只能在异步协程中使用，确保 `FrameFinishUpdate()` 在帧末被调用
