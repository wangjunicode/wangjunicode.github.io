---
title: 单例更新接口体系——ISingletonUpdate、FixedUpdate 和 LateUpdate 的职责划分
published: 2026-03-31
description: 解析三个单例更新接口的设计，理解 ISingletonFixedUpdate 的三阶段更新流程，以及 Game 类如何通过接口检测自动调度所有单例的帧更新。
tags: [Unity, ECS, 单例, 更新循环, 接口设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 单例更新接口体系——ISingletonUpdate、FixedUpdate 和 LateUpdate 的职责划分

## 前言

ECS 框架中的单例（Singleton）不只是"全局唯一的对象"，它们还需要参与游戏的帧循环——每帧更新状态、处理逻辑、进行物理计算。

三个更新接口 `ISingletonUpdate`、`ISingletonFixedUpdate`、`ISingletonLateUpdate` 就是为此而设计的。

---

## 一、三个更新接口的定义

```csharp
// 普通帧更新
public interface ISingletonUpdate
{
    void Update();
}

// 固定帧更新（物理帧）
public interface ISingletonFixedUpdate
{
    void BeforeFixedUpdate(); // 物理帧之前
    void FixedUpdate();       // 物理帧中
    void LateFixedUpdate();   // 物理帧之后
}

// 延后帧更新
public interface ISingletonLateUpdate
{
    void LateUpdate();
}
```

### 1.1 ISingletonFixedUpdate 的三阶段设计

注意 `ISingletonFixedUpdate` 定义了三个方法，而不是一个：

- `BeforeFixedUpdate()`：物理帧开始前
- `FixedUpdate()`：物理帧主体
- `LateFixedUpdate()`：物理帧结束后

**为什么需要三个阶段？**

以 `LogicTimerComponent` 的使用为例：

```csharp
// TimeInfo 实现 ISingletonFixedUpdate
public void BeforeFixedUpdate()
{
    Update(); // 在物理帧开始前更新帧时间快照
}
```

```csharp
// LogicTimerComponent 实现 ISingletonFixedUpdate
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
    {
        Update(); // 在时间快照更新后，处理定时器
    }
}
```

执行顺序：
1. `TimeInfo.BeforeFixedUpdate()` → 更新 `FrameTime`
2. `LogicTimerComponent.BeforeFixedUpdate()` → 使用已更新的 `FrameTime` 处理定时器
3. `EventSystem.FixedUpdate()` → 处理所有实体的物理帧逻辑

这种顺序依赖通过注册顺序来保证（先注册的先执行）。

---

## 二、Game 中的自动调度机制

```csharp
public static void AddSingleton(ISingleton singleton)
{
    // ... 注册到字典和栈
    
    if (singleton is ISingletonUpdate)
    {
        updates.Enqueue(singleton);
    }
    
    if (singleton is ISingletonFixedUpdate)
    {
        beforeFixedUpdates.Enqueue(singleton);
        fixedUpdates.Enqueue(singleton);
        lateFixedUpdates.Enqueue(singleton);
    }
    
    if (singleton is ISingletonLateUpdate)
    {
        lateUpdates.Enqueue(singleton);
    }
}
```

注册单例时，框架自动检测它实现了哪些接口，分别加入对应的更新队列。

**这是编程中的"鸭子类型"思想**：不是说"你必须是 X 类型"，而是说"只要你能做 Y 这件事（实现接口），就进入 Y 的队列"。

单例自己决定参与哪些更新阶段，框架不需要知道具体类型——只需要检查接口。

### 2.1 四个独立队列

```csharp
private static readonly Queue<ISingleton> updates = new Queue<ISingleton>();
private static readonly Queue<ISingleton> beforeFixedUpdates = new Queue<ISingleton>();
private static readonly Queue<ISingleton> fixedUpdates = new Queue<ISingleton>();
private static readonly Queue<ISingleton> lateFixedUpdates = new Queue<ISingleton>();
private static readonly Queue<ISingleton> lateUpdates = new Queue<ISingleton>();
```

一个实现了 `ISingletonFixedUpdate` 的单例会被加入三个队列（beforeFixed, fixed, lateFixed）。

这意味着执行顺序完全分离——不同阶段的单例可以以不同顺序执行（虽然注册顺序通常保持一致）。

---

## 三、更新方法的实现模式

```csharp
public static void Update()
{
    int count = updates.Count;
    while (count-- > 0)
    {
        ISingleton singleton = updates.Dequeue();

        if (singleton.IsDisposed())
        {
            continue; // 跳过已销毁的单例（不重新入队）
        }

        if (singleton is not ISingletonUpdate update)
        {
            continue;
        }
        
        updates.Enqueue(singleton); // 重新入队，下帧继续执行
        
        try
        {
            update.Update();
        }
        catch (Exception e)
        {
            Log.Error(e);
        }
    }
}
```

这个模式与 `EventSystem` 中的实体更新完全一致：
1. 先锁定 count，本帧只处理已有的单例
2. 跳过已销毁的（不重新入队，自然从队列中消失）
3. 重新入队，保持持续更新
4. try-catch 异常隔离

### 3.1 已销毁单例的自然淘汰

```csharp
if (singleton.IsDisposed())
{
    continue; // 不 Enqueue，自然从队列中消失
}
```

当单例被销毁时，不需要从队列中主动移除——下次轮到它时，检测到 `IsDisposed()` 就跳过，且不重新入队。下下次，它就不在队列里了。

这比维护"需要移除的列表"然后主动删除更简单，避免了"在遍历中修改集合"的问题。

---

## 四、BeforeFixedUpdate 的特殊逻辑

```csharp
public static void BeforeFixedUpdate()
{
    FixedFrames++;
    FixedTime = FixedFrames * EngineDefine.fixedDeltaTime_Orignal;
    
    int count = beforeFixedUpdates.Count;
    while (count-- > 0)
    {
        // ... 调用所有 singleton.BeforeFixedUpdate()
    }
}
```

注意 `BeforeFixedUpdate` 开头做了两件事：
1. 递增全局帧计数 `FixedFrames`
2. 计算当前逻辑时间 `FixedTime = FixedFrames * fixedDeltaTime`

这是**游戏时间的主驱动**：每次 `BeforeFixedUpdate` 被调用，逻辑时间前进一帧。

`FixedTime` 是用定点数（`FP`）计算的，配合 `fixedDeltaTime_Orignal`（也是定点数），确保帧同步场景下的精确时间计算。

---

## 五、实际使用——为单例添加更新能力

```csharp
// 只需要 Update 的单例（如 UI 动画管理器）
public class UIAnimationManager: Singleton<UIAnimationManager>, ISingletonUpdate
{
    private List<UIAnimation> runningAnimations = new();
    
    public void Update()
    {
        for (int i = runningAnimations.Count - 1; i >= 0; i--)
        {
            if (runningAnimations[i].Tick(Game.deltaTime))
            {
                runningAnimations.RemoveAt(i); // 动画完成，移除
            }
        }
    }
}

// 需要 FixedUpdate 的单例（如物理逻辑管理器）
public class PhysicsManager: Singleton<PhysicsManager>, ISingletonFixedUpdate
{
    public void BeforeFixedUpdate()
    {
        // 收集输入
    }
    
    public void FixedUpdate()
    {
        // 执行物理模拟
    }
    
    public void LateFixedUpdate()
    {
        // 同步物理结果到渲染
    }
}

// 注册时自动加入相应队列
Game.AddSingleton<UIAnimationManager>(); // 自动加入 updates 队列
Game.AddSingleton<PhysicsManager>();     // 自动加入三个 fixedUpdate 队列
```

---

## 六、单例更新 vs 实体更新的对比

| 特性 | 单例更新 | 实体更新 |
|---|---|---|
| 注册方式 | 实现接口自动加入队列 | 实现接口+注册到 EventSystem |
| 数量 | 少（框架级服务） | 多（游戏对象） |
| 生命周期 | 进程级别，通常不销毁 | 游戏逻辑级别，频繁创建销毁 |
| 管理者 | Game 静态类 | EventSystem 单例 |
| 调用方式 | 直接接口调用 | 通过 typeSystems 查找系统 |

---

## 七、设计总结

单例更新接口体系的精妙之处：

1. **零配置自动注册**：实现接口就会被调度，不需要手动注册
2. **三阶段物理更新**：BeforeFixed/Fixed/LateFixed 精确控制执行顺序
3. **自然淘汰机制**：销毁的单例自动从队列中消失，无需手动清理
4. **异常隔离**：单个单例的 Bug 不影响其他单例的更新
5. **顺序保证**：注册顺序决定执行顺序，满足依赖要求

这套设计将"框架管理者"（Game 类）与"具体逻辑"（各单例）完全解耦——Game 类不需要知道任何具体单例，只需要管理接口。
