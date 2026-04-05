---
title: 游戏世界的操控台——Game 静态类的全局调度设计
published: 2026-03-31
description: 全面解析 Game 静态类的设计哲学，理解单例生命周期管理、多阶段帧循环驱动、时间系统集成、帧末尾任务队列以及 WaitFrameFinish 异步等待机制。
tags: [Unity, ECS, 游戏架构, 时间系统, 异步编程]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 游戏世界的操控台——Game 静态类的全局调度设计

## 前言

在一个 ECS 框架中，谁来驱动整个游戏的运转？谁来管理所有的全局服务？谁来控制游戏时间？

`Game` 静态类承担了这些职责——它是整个框架的"操控台"，是游戏逻辑的最外层驱动者。

---

## 一、Game 类的数据全览

```csharp
public static class Game
{
    // 逻辑时间
    public static FP FixedTime;          // 当前逻辑帧时间（定点数）
    public static int FixedFrames;       // 当前逻辑帧数
    public static float GameTime;        // 当前游戏时间（浮点数）
    
    // 单例管理
    [StaticField] private static readonly Dictionary<Type, ISingleton> singletonTypes;
    [StaticField] private static readonly Stack<ISingleton> singletons;
    
    // 更新队列
    [StaticField] private static readonly Queue<ISingleton> updates;
    [StaticField] private static readonly Queue<ISingleton> beforeFixedUpdates;
    [StaticField] private static readonly Queue<ISingleton> fixedUpdates;
    [StaticField] private static readonly Queue<ISingleton> lateFixedUpdates;
    [StaticField] private static readonly Queue<ISingleton> lateUpdates;
    
    // 帧末尾任务
    [StaticField] private static readonly Queue<ETTask> frameFinishTask;
    
    // 运行时参数
    public static float realtimeSinceStartup;
    public static float deltaTime;
    public static float gameTimeSpeedUp;   // 游戏时间倍速
    public static float gameDeltaTime;
}
```

### 1.1 双时间体系

```csharp
public static FP FixedTime;    // 定点数时间，用于帧同步逻辑
public static float GameTime;   // 浮点数时间，用于表现层
```

游戏维护两套时间：

- **FixedTime**（定点数）：由物理帧驱动，用于所有需要帧同步的逻辑计算
- **GameTime**（浮点数）：由渲染帧驱动，用于表现层（UI、动画、特效）

两套时间存在于同一个世界，分别服务不同的需求。

### 1.2 gameTimeSpeedUp——游戏倍速

```csharp
public static float gameTimeSpeedUp;
public static float gameDeltaTime;

// 更新时计算
Game.gameDeltaTime = deltaTime * Game.gameTimeSpeedUp;
```

`gameDeltaTime = deltaTime * speedUp` 实现游戏加速（1.5x、2x、3x 速度）。

这是策略游戏、跳过战斗场景等功能的技术基础。

---

## 二、AddSingleton——统一的单例注册入口

```csharp
public static T AddSingleton<T>() where T: Singleton<T>, new()
{
    T singleton = new T();
    if (singleton is ISingletonAwake singletonAwake)
    {
        singletonAwake.Awake();
    }
    AddSingleton(singleton);
    return singleton;
}

public static void AddSingleton(ISingleton singleton)
{
    Type singletonType = singleton.GetType();
    if (singletonTypes.ContainsKey(singletonType))
    {
        throw new Exception($"already exist singleton: {singletonType.Name}");
    }

    singletonTypes.Add(singletonType, singleton);
    singletons.Push(singleton); // 入栈，保证 LIFO 销毁顺序
    
    singleton.Register(); // 设置单例的全局实例引用
    
    // 按接口分流到不同更新队列
    if (singleton is ISingletonUpdate)      updates.Enqueue(singleton);
    if (singleton is ISingletonFixedUpdate)
    {
        beforeFixedUpdates.Enqueue(singleton);
        fixedUpdates.Enqueue(singleton);
        lateFixedUpdates.Enqueue(singleton);
    }
    if (singleton is ISingletonLateUpdate)  lateUpdates.Enqueue(singleton);
}
```

**两个重载的设计**：

- `AddSingleton<T>()`：泛型版本，自动 `new T()`，自动调用 Awake
- `AddSingleton(ISingleton)`：通用版本，接受已创建的单例实例

这样既支持简便的无参创建，也支持需要特殊构造逻辑的单例。

---

## 三、WaitFrameFinish——帧末尾的异步等待

```csharp
[StaticField] private static readonly Queue<ETTask> frameFinishTask = new Queue<ETTask>();

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
        task.SetResult(); // 触发所有等待的任务
    }
}
```

`WaitFrameFinish()` 是一个非常有用的工具：它让你能在协程/异步代码中等待"当前帧结束"。

**使用场景**：

```csharp
async ETTask DoSomethingNextFrame()
{
    // 当前帧执行某些操作...
    Log.Info("当前帧开始");
    
    // 等待当前帧结束（下一帧开始时继续）
    await Game.WaitFrameFinish();
    
    // 下一帧执行
    Log.Info("下一帧开始");
}
```

**工作原理**：

1. `WaitFrameFinish()` 创建一个未完成的 `ETTask`，加入队列，然后 `await` 它
2. 调用方在这里暂停
3. 帧末尾调用 `FrameFinishUpdate()`，取出所有队列中的 Task，调用 `SetResult()` 完成它们
4. 所有等待这些 Task 的协程被唤醒，继续执行

**经典用途**：

```csharp
// 等待 UI 刷新完成后截图
async ETTask TakeScreenshot()
{
    await Game.WaitFrameFinish(); // 确保当前帧的 UI 渲染完成
    // 截图
    Texture2D screenshot = ...;
}

// 一个操作需要在所有逻辑更新后执行
async ETTask EndOfFrameCleanup()
{
    await Game.WaitFrameFinish();
    // 清理本帧产生的临时数据
}
```

---

## 四、Update 的时间参数更新

```csharp
public static void Update(float deltaTime, float realtimeSinceStartup)
{
    Game.realtimeSinceStartup = realtimeSinceStartup;
    Game.deltaTime = deltaTime;
    Game.gameDeltaTime = deltaTime * Game.gameTimeSpeedUp;
    Game.GameTime += deltaTime;
    Update(); // 调用实际的无参 Update
}
```

外部（Unity MonoBehaviour）每帧调用这个方法，传入 Unity 的 `deltaTime` 和 `realtimeSinceStartup`。

Game 存储这些值，供所有需要时间信息的地方访问，避免重复调用 Unity 的 `Time.deltaTime`（虽然开销很小，但统一入口更好维护）。

**为什么要区分 `deltaTime` 和 `gameDeltaTime`？**

- `deltaTime`：真实的帧间隔时间
- `gameDeltaTime`：考虑了游戏倍速的帧间隔

UI 动画、音效等不需要受倍速影响的系统用 `deltaTime`，游戏逻辑（敌人移动、技能 CD）用 `gameDeltaTime`（或 `EngineDefine.deltaTime` 这个封装）。

---

## 五、Close——安全的关闭序列

```csharp
public static void Close()
{
    // 以注册的逆序销毁所有单例
    while (singletons.Count > 0)
    {
        ISingleton iSingleton = singletons.Pop();
        iSingleton.Destroy();
    }
    singletonTypes.Clear();
}
```

`singletons` 是一个 Stack，`Close()` 用 `Pop()` 逐个弹出并销毁——LIFO 顺序，保证依赖关系正确。

游戏关闭时调用 `Game.Close()` 一行代码，所有单例按正确顺序销毁。

---

## 六、[StaticField] 的批量标记

注意所有可变静态字段都标记了 `[StaticField]`：

```csharp
[StaticField] private static readonly Dictionary<Type, ISingleton> singletonTypes;
[StaticField] private static readonly Stack<ISingleton> singletons;
[StaticField] private static readonly Queue<ISingleton> updates;
// ...
```

这些字段需要在热更新或测试重置时清空。由于 `readonly`，对象引用不变，但可以调用 `Clear()` 清空内容。

热更新系统扫描 `[StaticField]` 标记，知道哪些静态字段需要特殊处理。

---

## 七、设计总结

`Game` 类展示了一个优秀的全局调度系统应有的特性：

| 特性 | 实现 |
|---|---|
| 统一入口 | 所有单例通过 Game.AddSingleton 注册 |
| 自动调度 | 接口检测自动分流到正确队列 |
| 安全销毁 | LIFO 顺序，Stack 保证依赖逆序 |
| 时间管理 | 双时间体系（定点数/浮点数），倍速支持 |
| 异步支持 | WaitFrameFinish 帧末尾等待 |
| 热更新友好 | [StaticField] 标记可清理的静态字段 |
| 异常隔离 | try-catch 防止单例 Bug 影响其他系统 |

---

## 写给初学者

`Game` 类看起来很简单——就是几个队列和循环。但它的设计经过了深思熟虑：

- 为什么用 Stack 而不是 List 来存储单例？（逆序销毁）
- 为什么用 Queue 而不是 List 来存储更新列表？（先入先执行的公平调度）
- 为什么要单独记录 `gameDeltaTime`？（支持倍速）
- 为什么需要 `WaitFrameFinish`？（帧内有序的异步等待）

每个设计细节背后都有具体的需求驱动。理解"为什么这样设计"比"它是什么"更重要。
