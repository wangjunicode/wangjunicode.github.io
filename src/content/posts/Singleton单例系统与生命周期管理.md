---
title: 05 Singleton 单例系统与生命周期管理
published: 2024-01-01
description: "05 Singleton 单例系统与生命周期管理 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 05 Singleton 单例系统与生命周期管理

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

单例模式（Singleton Pattern）是游戏开发中最常用的设计模式之一，用于确保某个类在整个程序运行期间只有一个实例，并提供全局访问入口。

本框架的单例系统由三个层次组成：

1. **`Singleton<T>`** —— 基础单例抽象类，管理实例生命周期
2. **`ISingleton` 接口族** —— 定义单例可参与的生命周期钩子（Update、FixedUpdate、LateUpdate、Awake）
3. **`Game` 静态类** —— 单例的注册中心和驱动引擎，统一管理所有单例的帧更新

相比传统的懒汉式单例（`private static T _instance`），本框架的单例系统支持**有序销毁**、**生命周期钩子注入**，以及**明确的创建时序控制**。

**核心文件**：
- `X:\UnityProj\Assets\Scripts\Core\Singleton\Singleton.cs`
- `X:\UnityProj\Assets\Scripts\Core\Singleton\Game.cs`
- `X:\UnityProj\Assets\Scripts\Core\Singleton\ISingletonUpdate.cs` 等接口文件

---

## 2. 架构设计

### 2.1 单例体系结构

```
ISingleton（接口）
  ├── Register()     ← 注册时调用，设置静态 Instance
  ├── Destroy()      ← 销毁时调用，清除 Instance
  └── IsDisposed()   ← 判断是否已被销毁

Singleton<T>（抽象基类，实现 ISingleton）
  ├── static T Instance   ← 全局访问入口
  └── virtual Dispose()   ← 子类可重写，释放资源

生命周期接口（可选实现，实现后自动参与对应帧更新）：
  ISingletonAwake        → Awake()         创建时调用一次
  ISingletonUpdate       → Update()        每帧调用
  ISingletonLateUpdate   → LateUpdate()    每帧 Late 阶段
  ISingletonFixedUpdate  → BeforeFixedUpdate() + FixedUpdate() + LateFixedUpdate()
```

### 2.2 Game 的单例管理结构

```
Game（静态类）
├── singletonTypes: Dictionary<Type, ISingleton>   ← 类型 → 单例实例
├── singletons: Stack<ISingleton>                  ← 压栈顺序，Close() 时反序销毁
│
├── updates: Queue<ISingleton>                     ← 实现 ISingletonUpdate 的单例
├── beforeFixedUpdates: Queue<ISingleton>          ← 实现 ISingletonFixedUpdate 的单例
├── fixedUpdates: Queue<ISingleton>                ← 同上
├── lateFixedUpdates: Queue<ISingleton>            ← 同上
├── lateUpdates: Queue<ISingleton>                 ← 实现 ISingletonLateUpdate 的单例
└── frameFinishTask: Queue<ETTask>                 ← 帧结束等待队列
```

### 2.3 单例的有序销毁

```
Game.AddSingleton(A)  → singletons: [A]
Game.AddSingleton(B)  → singletons: [A, B]
Game.AddSingleton(C)  → singletons: [A, B, C]

Game.Close()
  → Pop C → C.Destroy()
  → Pop B → B.Destroy()
  → Pop A → A.Destroy()   ← 后注册的先销毁（LIFO）
```

这保证了"被依赖的单例最后销毁"，避免销毁顺序引发的空引用异常。

---

## 3. 核心代码展示

### 3.1 Singleton<T> 基础实现

```csharp
// X:\UnityProj\Assets\Scripts\Core\Singleton\Singleton.cs

public interface ISingleton : IDisposable
{
    void Register();
    void Destroy();
    bool IsDisposed();
}

public abstract class Singleton<T> : ISingleton where T : Singleton<T>, new()
{
    private bool isDisposed;

    [StaticField]  // 静态字段标记，便于代码分析工具识别
    private static T instance;

    // 全局访问入口
    public static T Instance => instance;

    // Register：由 Game.AddSingleton 调用，设置静态 Instance
    public void Register()
    {
        if (instance != null)
            throw new Exception($"singleton register twice! {typeof(T).Name}");
        instance = (T)this;
    }

    // Destroy：Game.Close() 时按 LIFO 顺序调用
    public void Destroy()
    {
        if (this.isDisposed) return;
        this.isDisposed = true;

        T t = instance;
        instance = null;  // 先清空静态引用，防止在 Dispose 中被再次访问
        t.Dispose();
    }

    public bool IsDisposed() => this.isDisposed;

    // 子类重写 Dispose 释放资源
    public virtual void Dispose() { }
}
```

### 3.2 Game.AddSingleton —— 单例注册

```csharp
// X:\UnityProj\Assets\Scripts\Core\Singleton\Game.cs

public static T AddSingleton<T>() where T : Singleton<T>, new()
{
    T singleton = new T();

    // 如果实现了 ISingletonAwake，立即调用 Awake
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
    singletons.Push(singleton);  // 压栈，保证 LIFO 销毁顺序

    singleton.Register();  // 设置静态 Instance

    // 根据实现的接口，加入对应的更新队列
    if (singleton is ISingletonUpdate)
        updates.Enqueue(singleton);

    if (singleton is ISingletonFixedUpdate)
    {
        beforeFixedUpdates.Enqueue(singleton);
        fixedUpdates.Enqueue(singleton);
        lateFixedUpdates.Enqueue(singleton);
    }

    if (singleton is ISingletonLateUpdate)
        lateUpdates.Enqueue(singleton);
}
```

### 3.3 Game.Update —— 帧驱动

```csharp
public static void Update()
{
    int count = updates.Count;  // 快照，防止本帧新增的单例立即被调用
    while (count-- > 0)
    {
        ISingleton singleton = updates.Dequeue();

        if (singleton.IsDisposed()) continue;  // 已销毁的跳过
        if (singleton is not ISingletonUpdate update) continue;

        updates.Enqueue(singleton);  // 重新入队，下帧继续

        try { update.Update(); }
        catch (Exception e) { Log.Error(e); }
    }
}

// 携带 deltaTime 的外部调用版本（Unity 的 Update 调用此方法）
public static void Update(float deltaTime, float realtimeSinceStartup)
{
    Game.realtimeSinceStartup = realtimeSinceStartup;
    Game.deltaTime = deltaTime;
    Game.gameDeltaTime = deltaTime * Game.gameTimeSpeedUp;
    Game.GameTime += deltaTime;
    Update();
}
```

### 3.4 WaitFrameFinish —— 帧末等待

```csharp
// 等待当前帧结束（在 FrameFinishUpdate 时所有等待的 Task 被唤醒）
public static async ETTask WaitFrameFinish()
{
    ETTask task = ETTask.Create(true);
    frameFinishTask.Enqueue(task);
    await task;
}

// 每帧末尾调用（通常在 Unity 的 LateUpdate 之后）
public static void FrameFinishUpdate()
{
    while (frameFinishTask.Count > 0)
    {
        ETTask task = frameFinishTask.Dequeue();
        task.SetResult();  // 唤醒所有等待帧末的协程
    }
}
```

### 3.5 Game.Close —— 有序销毁

```csharp
public static void Close()
{
    // Stack 是 LIFO（后进先出），后注册的单例先销毁
    while (singletons.Count > 0)
    {
        ISingleton iSingleton = singletons.Pop();
        iSingleton.Destroy();
    }
    singletonTypes.Clear();
}
```

### 3.6 生命周期接口定义

```csharp
// ISingletonUpdate.cs
public interface ISingletonUpdate
{
    void Update();
}

// ISingletonFixedUpdate.cs（完整物理帧生命周期）
public interface ISingletonFixedUpdate
{
    void BeforeFixedUpdate();
    void FixedUpdate();
    void LateFixedUpdate();
}

// ISingletonLateUpdate.cs
public interface ISingletonLateUpdate
{
    void LateUpdate();
}

// ISingletonAwake.cs
public interface ISingletonAwake
{
    void Awake();
}
```

---

## 4. 完整的单例实现示例

### 4.1 仅需全局访问（无帧更新）

```csharp
// 最简单的单例：全局配置管理器
public class ConfigManager : Singleton<ConfigManager>
{
    private Dictionary<int, ItemConfig> itemConfigs = new();

    public override void Dispose()
    {
        itemConfigs.Clear();
        Log.Info("ConfigManager disposed");
    }

    public ItemConfig GetItemConfig(int id)
    {
        itemConfigs.TryGetValue(id, out var config);
        return config;
    }
}

// 注册（在游戏初始化时）
Game.AddSingleton<ConfigManager>();

// 访问
var config = ConfigManager.Instance.GetItemConfig(101);
```

### 4.2 需要每帧更新的单例

```csharp
// 定时器管理器：需要每帧检查到期的定时器
public class TimerComponent : Singleton<TimerComponent>, ISingletonUpdate
{
    private readonly MultiMap<long, long> timerMap = new();  // 到期时间 → timerIds

    public void Update()
    {
        long now = TimeHelper.ClientFrameTime();
        // 处理所有到期的定时器
        while (timerMap.Count > 0 && timerMap.First().Key <= now)
        {
            // ...
        }
    }

    public override void Dispose()
    {
        timerMap.Clear();
    }
}

// 注册
Game.AddSingleton<TimerComponent>();
```

### 4.3 需要 Awake 初始化的单例

```csharp
public class NetworkManager : Singleton<NetworkManager>, ISingletonAwake, ISingletonUpdate
{
    private TcpClient client;

    public void Awake()
    {
        // 在 Register 之前就会被调用，安全初始化
        client = new TcpClient();
        Log.Info("NetworkManager awake");
    }

    public void Update()
    {
        client?.ProcessReceivedData();
    }

    public override void Dispose()
    {
        client?.Close();
        client = null;
    }
}
```

---

## 5. 框架单例的初始化顺序

游戏启动时，单例应按照依赖顺序注册：

```csharp
// 典型的游戏启动初始化（GameEntry.cs 或类似入口）
void Start()
{
    // 1. 基础工具层（无依赖）
    Game.AddSingleton<ObjectPool>();
    Game.AddSingleton<IdGenerater>();

    // 2. 核心框架层（依赖对象池和 ID 生成器）
    Game.AddSingleton<EventSystem>();

    // 3. ECS 根节点（依赖 EventSystem 和 IdGenerater）
    Game.AddSingleton<Root>();

    // 4. 协程锁（依赖 ObjectPool）
    Game.AddSingleton<CoroutineLockComponent>();

    // 5. 业务层单例（依赖上述所有）
    Game.AddSingleton<TimerComponent>();
    Game.AddSingleton<ConfigManager>();
    // ...

    // 销毁顺序将与注册顺序相反
}
```

---

## 6. Game 类中的时间管理

`Game` 还承担了游戏时间管理的职责，提供统一的时间参数供所有系统使用：

```csharp
public static float realtimeSinceStartup;  // 真实时间（不受暂停影响）
public static float deltaTime;              // 帧间时间
public static float gameTimeSpeedUp;        // 游戏时间加速倍率（测试用）
public static float gameDeltaTime;          // 加速后的帧间时间（= deltaTime × speedUp）
public static float GameTime;               // 累计游戏时间

// 物理帧计数
public static FP FixedTime;     // TrueSync 物理时间（TrueSync 框架使用）
public static int FixedFrames;  // 物理帧计数
```

---

## 7. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| 单例接口 | 相同 | 相同 |
| 销毁顺序 | LIFO（栈） | 相同 |
| `ISingletonFixedUpdate` | 无（服务端不需要） | 新增，支持三阶段物理帧 |
| `WaitFrameFinish` | 有 | 相同 |
| 时间管理 | 单独 TimeInfo 单例 | Game 类直接持有时间字段 |
| `gameTimeSpeedUp` | 无 | 新增，支持游戏时间加速（UI 测试用） |
| TrueSync 物理集成 | 无 | 新增 `FixedTime`/`FixedFrames`（TrueSync 物理同步） |

---

## 8. 常见问题与最佳实践

### Q1：为什么不用传统的 `static T _instance` 懒汉式单例？

传统单例缺乏销毁时序控制。当多个单例相互依赖时，随机的销毁顺序会导致崩溃。本框架通过 Stack 保证 LIFO 销毁，彻底解决了这个问题。

### Q2：可以在单例的 Update 中访问其他单例吗？

可以，只要被访问的单例没有被销毁。但要注意，如果两个单例在 Update 中互相读写数据，可能会因为执行顺序不确定而产生 Bug。建议通过 `Publish` 事件或明确的调用顺序来解耦。

### Q3：单例可以被 GC 回收吗？

不会。`Game.singletonTypes` 和 `Game.singletons` 持有对所有单例的强引用，直到 `Game.Close()` 被调用。

### Q4：如何在编辑器模式下重置单例？

```csharp
// Unity 编辑器模式下退出 Play 时，静态字段不会自动清除
// 建议在 OnApplicationQuit 或 [RuntimeInitializeOnLoadMethod] 中调用
private void OnApplicationQuit()
{
    Game.Close();
}
```

### Q5：单例 vs Entity 的选择标准

| 使用单例 | 使用 Entity |
|---|---|
| 全局唯一，生命周期与程序同步 | 有父子层级关系 |
| 无需序列化 | 需要持久化/序列化 |
| 纯逻辑管理器（无数据实体意义） | 有明确的业务身份（玩家、道具） |
| 例：EventSystem、TimerComponent | 例：PlayerEntity、ItemEntity |

---

## 9. 总结

Singleton 系统的三层设计（接口 + 抽象基类 + Game 调度器）解决了传统单例的核心痛点：

1. **创建时序可控**：显式调用 `AddSingleton`，依赖顺序一目了然
2. **销毁时序安全**：LIFO 栈保证被依赖者最后销毁
3. **生命周期注入**：实现接口即自动参与帧更新，零样板代码
4. **异常隔离**：每个单例的 Update 异常被捕获后记录日志，不影响其他单例
