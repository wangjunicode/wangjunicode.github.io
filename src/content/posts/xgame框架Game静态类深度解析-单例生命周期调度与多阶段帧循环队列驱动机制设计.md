---
title: xgame框架Game静态类深度解析-单例生命周期调度与多阶段帧循环队列驱动机制设计
published: 2026-05-06
description: '深入剖析xgame框架核心入口Game静态类的设计原理，涵盖单例注册表、多阶段帧更新队列（Update/FixedUpdate/LateUpdate）、WaitFrameFinish异步帧结束机制、时间倍率控制与Close有序销毁流程。'
image: ''
tags: [Unity, xgame, 游戏框架, ECS, 单例, 帧循环, 设计模式]
category: '游戏开发'
draft: false
encryptedKey: henhaoji123
---

# xgame框架 Game 静态类深度解析

## 一、概述

`Game` 是 xgame 框架的**全局入口**与**核心调度中枢**。它以静态类的形式存在，管理所有单例（Singleton）的注册、生命周期调度，以及整个游戏的帧更新驱动。理解 `Game` 的内部机制，是掌握 xgame 框架运行时架构的关键。

---

## 二、全局时间与帧数

```csharp
public static FP FixedTime;       // 逻辑帧累计时间（定点数）
public static int FixedFrames;    // 已执行的逻辑帧数
public static float GameTime;     // 游戏运行总时间（秒）
public static float realtimeSinceStartup;
public static float deltaTime;
public static float gameTimeSpeedUp;  // 时间加速倍率
public static float gameDeltaTime;    // 受倍率影响的 deltaTime
```

框架将**逻辑时间**（基于定点数 `FP`，用于锁帧同步）与**显示时间**（`float`，用于表现层）分开管理，避免浮点误差影响战斗逻辑。

`FixedTime` 的累加公式：
```
FixedTime = FixedFrames × EngineDefine.fixedDeltaTime_Orignal
```

这保证了物理逻辑帧的时间严格同步，不依赖 Unity 的 `Time.fixedTime`。

---

## 三、单例注册表设计

```csharp
[StaticField]
private static readonly Dictionary<Type, ISingleton> singletonTypes = new();
[StaticField]
private static readonly Stack<ISingleton> singletons = new();
```

- `singletonTypes`：类型→实例的查找字典，防止重复注册
- `singletons`：注册顺序的栈，用于**逆序销毁**（LIFO，后注册先销毁）

这两个容器用 `[StaticField]` 标记，表明它们是需要在框架重置时被清理的静态字段。

### AddSingleton 泛型重载

```csharp
public static T AddSingleton<T>() where T: Singleton<T>, new()
{
    T singleton = new T();
    if (singleton is ISingletonAwake singletonAwake)
        singletonAwake.Awake();
    AddSingleton(singleton);
    return singleton;
}
```

泛型重载自动执行 `Awake()`，然后调用核心 `AddSingleton(ISingleton)` 完成注册与队列入队：

```csharp
public static void AddSingleton(ISingleton singleton)
{
    // 防重注册
    if (singletonTypes.ContainsKey(singletonType)) throw ...;
    
    singletonTypes.Add(singletonType, singleton);
    singletons.Push(singleton);
    singleton.Register();  // 单例自身注册（通常写入 Instance 属性）
    
    if (singleton is ISingletonUpdate)       updates.Enqueue(singleton);
    if (singleton is ISingletonFixedUpdate)  { beforeFixedUpdates/fixedUpdates/lateFixedUpdates.Enqueue(singleton); }
    if (singleton is ISingletonLateUpdate)   lateUpdates.Enqueue(singleton);
}
```

根据单例实现的接口，**自动分流**到对应的更新队列，无需手动注册。

---

## 四、多阶段帧更新队列

Game 维护 **5 条独立的环形队列**，对应 Unity 生命周期的不同阶段：

| 队列 | 接口 | 对应 Unity 事件 |
|---|---|---|
| `updates` | `ISingletonUpdate` | `Update()` |
| `beforeFixedUpdates` | `ISingletonFixedUpdate` | FixedUpdate 前置 |
| `fixedUpdates` | `ISingletonFixedUpdate` | `FixedUpdate()` |
| `lateFixedUpdates` | `ISingletonFixedUpdate` | FixedUpdate 后置 |
| `lateUpdates` | `ISingletonLateUpdate` | `LateUpdate()` |

### 环形队列的核心技巧

每次更新循环使用**快照计数 + 重入队**的模式，避免新注册的单例在当帧立即执行：

```csharp
public static void Update()
{
    int count = updates.Count;  // 快照当前数量
    while (count-- > 0)
    {
        ISingleton singleton = updates.Dequeue();
        
        if (singleton.IsDisposed()) continue;  // 跳过已销毁
        if (singleton is not ISingletonUpdate update) continue;
        
        updates.Enqueue(singleton);  // 重入队，保证循环
        try { update.Update(); }
        catch (Exception e) { Log.Error(e); }
    }
}
```

已销毁的单例会被自动过滤，**无需显式从队列移除**，设计极为简洁。

---

## 五、时间控制

```csharp
public static void Update(float deltaTime, float realtimeSinceStartup)
{
    Game.deltaTime = deltaTime;
    Game.gameDeltaTime = deltaTime * Game.gameTimeSpeedUp;  // 应用倍率
    Game.GameTime += deltaTime;
    Update();
}

public static void SetGameTimeSpeedUp(float speedUp)
{
    Game.gameTimeSpeedUp = speedUp;
}
```

`gameTimeSpeedUp` 允许在不修改 `Time.timeScale` 的情况下实现**游戏时间加速**（快进回放、调试），不影响 Unity 物理和动画层。

---

## 六、WaitFrameFinish 异步帧结束机制

```csharp
[StaticField]
private static readonly Queue<ETTask> frameFinishTask = new Queue<ETTask>();

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

这是一个**帧末同步点**机制。任何协程都可以 `await Game.WaitFrameFinish()` 挂起，等到当帧所有逻辑结束后（`FrameFinishUpdate` 被调用）才恢复执行。

典型用例：
- 等待所有实体在当帧完成初始化后再执行后续逻辑
- 在帧末批量合并网络消息再处理
- 确保 UI 更新发生在所有数据变更之后

---

## 七、有序销毁机制

```csharp
public static void Close()
{
    while (singletons.Count > 0)
    {
        ISingleton iSingleton = singletons.Pop();  // LIFO
        iSingleton.Destroy();
    }
    singletonTypes.Clear();
}
```

`Stack<ISingleton>` 保证**后注册的单例先销毁**，解决依赖关系：底层系统（如 ObjectPool、EventSystem）最后注册，最先销毁时先清理上层依赖，确保销毁安全。

---

## 八、与 Unity 主循环的接入

```
MonoBehaviour.Update()
    → Game.Update(Time.deltaTime, Time.realtimeSinceStartup)
    
MonoBehaviour.FixedUpdate()
    → Game.BeforeFixedUpdate()
    → Game.FixedUpdate()
    → Game.LateFixedUpdate()

MonoBehaviour.LateUpdate()
    → Game.LateUpdate()
    → Game.FrameFinishUpdate()  // 帧末任务
```

Game 本身不继承 MonoBehaviour，通过一个薄薄的 `GameLoop` MonoBehaviour 桥接，保持框架对 Unity 的低耦合。

---

## 九、设计模式总结

| 模式 | 体现 |
|---|---|
| 静态门面（Facade） | Game 作为单一入口聚合所有生命周期 |
| 观察者变体 | 接口分流自动注册，无需显式订阅 |
| 责任链 | Update 链→FixedUpdate 链→LateUpdate 链顺序执行 |
| 快照迭代 | `int count = queue.Count` 防止当帧新增单例影响本轮循环 |
| LIFO 销毁 | Stack 保证依赖关系逆序安全释放 |

`Game` 的设计以**极简接口**屏蔽了复杂的调度细节，开发者只需实现对应更新接口并调用 `AddSingleton`，即可无缝接入框架的帧驱动体系。
