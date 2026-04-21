---
title: Game单例管理器设计解析——ET框架的生命周期调度中枢与帧驱动架构
published: 2026-04-21
description: 深入分析ET框架Core/Singleton目录下Game静态类与Singleton基类的完整实现，涵盖单例注册与销毁、Update/FixedUpdate/LateUpdate多轨驱动、帧结束任务队列以及游戏时间加速设计，揭示ECS引擎层生命周期调度的工程精髓。
tags: [Unity, 游戏框架, CSharp, 单例, ECS, 生命周期]
category: 游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

## 引言

在 ET 框架中，`Game` 类承担着整个引擎层所有单例系统的**注册、驱动和销毁**工作，是连接 Unity 主循环与游戏逻辑层的核心枢纽。本文结合 `Game.cs` 与 `Singleton.cs` 源码，逐一解析每个设计决策背后的工程考量。

---

## Singleton 基类：极简的类型安全单例

```csharp
public abstract class Singleton<T> : ISingleton where T : Singleton<T>, new()
{
    private bool isDisposed;
    [StaticField]
    private static T instance;

    public static T Instance => instance;

    public void Register()
    {
        if (instance != null)
            throw new Exception($"singleton register twice! {typeof(T).Name}");
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

    public bool IsDisposed() => this.isDisposed;
    public virtual void Dispose() { }
}
```

### 设计要点

**泛型自约束（CRTP 风格）**：`T : Singleton<T>, new()` 保证静态字段 `instance` 的类型与子类完全一致，无需强制转型即可通过 `T.Instance` 访问，编译期类型安全。

**`[StaticField]` 标注**：ET 框架的代码分析器会扫描此特性，确保静态字段在框架关闭时被正确清理，防止跨场景/热重载时的状态残留。

**先清后析**：`Destroy()` 中先将 `instance = null`，再调用 `t.Dispose()`，保证在 `Dispose` 回调中若有代码访问 `Instance` 会得到 null 而不是正在销毁中的对象，避免悬空引用。

---

## Game 类：多轨帧驱动调度器

### 单例注册流程

```csharp
public static T AddSingleton<T>() where T : Singleton<T>, new()
{
    T singleton = new T();
    if (singleton is ISingletonAwake singletonAwake)
        singletonAwake.Awake();
    AddSingleton(singleton);
    return singleton;
}

public static void AddSingleton(ISingleton singleton)
{
    Type singletonType = singleton.GetType();
    if (singletonTypes.ContainsKey(singletonType))
        throw new Exception($"already exist singleton: {singletonType.Name}");

    singletonTypes.Add(singletonType, singleton);
    singletons.Push(singleton);
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

注册时自动检测单例实现了哪些生命周期接口，将其分别推入对应驱动队列，实现**按需参与帧循环**，未实现接口的单例零开销。

`singletons` 使用 `Stack`（后进先出），保证 `Close()` 时按**注册逆序**销毁，这与 C++ 对象析构顺序一致，确保有依赖关系的单例能安全卸载。

---

### 五条驱动轨道

| 队列 | 触发时机 | 对应接口 |
|------|----------|----------|
| `updates` | 每帧 `Update` | `ISingletonUpdate` |
| `beforeFixedUpdates` | 物理帧前 | `ISingletonFixedUpdate.BeforeFixedUpdate` |
| `fixedUpdates` | 物理帧中 | `ISingletonFixedUpdate.FixedUpdate` |
| `lateFixedUpdates` | 物理帧后 | `ISingletonFixedUpdate.LateFixedUpdate` |
| `lateUpdates` | 每帧 `LateUpdate` | `ISingletonLateUpdate` |

### 环形队列驱动模式

```csharp
public static void Update()
{
    int count = updates.Count;
    while (count-- > 0)
    {
        ISingleton singleton = updates.Dequeue();
        if (singleton.IsDisposed()) continue;
        if (singleton is not ISingletonUpdate update) continue;

        updates.Enqueue(singleton);    // 重新入队
        try { update.Update(); }
        catch (Exception e) { Log.Error(e); }
    }
}
```

**快照 count 再循环**：先记录当前 `Count`，循环时只处理这批，避免在 `Update` 回调中新加入的单例在当帧被多次执行。

**先入队再执行**：`updates.Enqueue(singleton)` 先于 `update.Update()`，即便 `Update` 内部抛异常，该单例仍留在队列中，不会因异常导致下帧漏调。

**异常隔离**：`try/catch` 包裹每个 `Update` 调用，单个单例异常不影响其他系统继续执行。

---

### FixedUpdate 三段式

```csharp
public static void BeforeFixedUpdate()
{
    FixedFrames++;
    FixedTime = FixedFrames * EngineDefine.fixedDeltaTime_Orignal;
    // 驱动 beforeFixedUpdates 队列...
}

public static void FixedUpdate() { /* 驱动 fixedUpdates */ }
public static void LateFixedUpdate() { /* 驱动 lateFixedUpdates */ }
```

物理帧被拆分为 `BeforeFixedUpdate → FixedUpdate → LateFixedUpdate` 三个阶段，配合帧同步系统使用：

- `BeforeFixedUpdate`：自增 `FixedFrames`，更新 `FixedTime`（定点数帧时间），供全局查询
- `FixedUpdate`：执行物理/逻辑运算
- `LateFixedUpdate`：状态广播、数据刷新

`FixedTime = FixedFrames * EngineDefine.fixedDeltaTime_Orignal` 使用乘法而非累加，彻底规避浮点精度漂移，保证帧同步场景下所有客户端的时间完全一致。

---

### 游戏时间加速

```csharp
public static float gameTimeSpeedUp;
public static float gameDeltaTime;

public static void Update(float deltaTime, float realtimeSinceStartup)
{
    Game.deltaTime = deltaTime;
    Game.gameDeltaTime = deltaTime * Game.gameTimeSpeedUp;
    Game.GameTime += deltaTime;
    Update();
}

public static void SetGameTimeSpeedUp(float speedUp)
{
    Game.gameTimeSpeedUp = speedUp;
}
```

`gameDeltaTime = deltaTime * gameTimeSpeedUp` 允许业务逻辑层订阅"加速后的 deltaTime"，用于慢动作、快进等时间操控效果，而 `deltaTime`（真实时间）仍保留供需要绝对时间的系统使用。

---

### 帧结束任务队列

```csharp
[StaticField]
private static readonly Queue<ETTask> frameFinishTask = new();

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
        task.SetResult();
    }
}
```

`WaitFrameFinish()` 让协程挂起，直到当前帧所有 Update/LateUpdate 执行完毕后才继续。典型使用场景：

- 等待所有系统本帧状态同步完成后再做汇总计算
- 动画/特效在帧末提交，避免与逻辑更新穿插

---

### Close：逆序安全销毁

```csharp
public static void Close()
{
    while (singletons.Count > 0)
    {
        ISingleton iSingleton = singletons.Pop();
        iSingleton.Destroy();
    }
    singletonTypes.Clear();
}
```

利用 `Stack` 的 LIFO 特性，后注册的单例先销毁，天然处理依赖关系：依赖其他单例的系统通常后初始化，析构时应先卸载，避免访问已销毁的依赖。

---

## 单例接口一览

```csharp
public interface ISingleton : IDisposable
{
    void Register();
    void Destroy();
    bool IsDisposed();
}

public interface ISingletonAwake       { void Awake(); }
public interface ISingletonUpdate      { void Update(); }
public interface ISingletonLateUpdate  { void LateUpdate(); }
public interface ISingletonFixedUpdate
{
    void BeforeFixedUpdate();
    void FixedUpdate();
    void LateFixedUpdate();
}
```

接口驱动设计使单例只需实现所需生命周期钩子，`Game` 通过接口检测自动分发，新增系统无需修改 `Game` 类本身。

---

## 小结

`Game` + `Singleton<T>` 的组合构成了 ET 框架最底层的运行时基础设施：

- **Stack 注册 + 逆序销毁**解决依赖拓扑问题
- **接口检测 + 多队列分发**实现零侵入的生命周期扩展
- **快照 count 环形驱动**防止帧内并发注册引发的多执行问题
- **gameDeltaTime 加速因子**为时间操控提供统一抽象
- **WaitFrameFinish**让异步协程与帧循环精确同步

理解这套机制，是阅读 ET 框架任何上层业务代码的前提。
