---
title: 游戏框架Game静态类WaitFrameFinish帧末异步等待机制深度解析
published: 2026-04-26
description: 深入解析ET/ECS框架中Game静态类的WaitFrameFinish与FrameFinishUpdate机制，分析帧末ETTask队列的设计原理、使用场景与执行时序，揭示在单帧多操作场景中如何用异步等待实现精准的帧边界同步。
tags: [Unity, ECS, 游戏框架, C#, 异步编程]
category: 技术
draft: false
encryptedKey: henhaoji123
---

## 前言

在 ET/ECS 框架的主循环设计中，`Game` 静态类不仅承载了单例注册与帧驱动调度，还内嵌了一套鲜为人注意的**帧末等待机制**——`WaitFrameFinish`。它允许任意异步协程精准地"挂起到当前帧结束后再继续"，在处理帧内多阶段逻辑、动画同步、延迟清理等场景中极为实用。本文从源码出发，完整剖析这套机制的设计原理与工程应用。

---

## 一、核心数据结构

```csharp
[StaticField]
private static readonly Queue<ETTask> frameFinishTask = new Queue<ETTask>();
```

`frameFinishTask` 是一个 `ETTask` 的 FIFO 队列，所有调用 `WaitFrameFinish()` 的协程都会把自己持有的 `ETTask` 入队，然后挂起等待。

---

## 二、等待入口：WaitFrameFinish

```csharp
public static async ETTask WaitFrameFinish()
{
    ETTask task = ETTask.Create(true);
    frameFinishTask.Enqueue(task);
    await task;
}
```

**逐行解析：**

| 代码 | 作用 |
|------|------|
| `ETTask.Create(true)` | 从对象池创建一个未完成的 ETTask，参数 `true` 表示归还时自动回池 |
| `frameFinishTask.Enqueue(task)` | 将任务放入帧末队列，等待主循环在本帧结束时驱动 |
| `await task` | 协程在此挂起，直到该 task 被 `SetResult()` 唤醒 |

这是一个典型的**"创建占位任务 → 入队 → 挂起等待外部触发"**模式，与 .NET 中 `TaskCompletionSource` 的思路完全一致，但基于框架自有的零GC ETTask 实现。

---

## 三、触发时机：FrameFinishUpdate

```csharp
public static void FrameFinishUpdate()
{
    while (frameFinishTask.Count > 0)
    {
        ETTask task = frameFinishTask.Dequeue();
        task.SetResult();
    }
}
```

`FrameFinishUpdate()` 在每帧的**最末尾**被调用（通常在 `LateUpdate` 之后），它依次将所有入队的 ETTask 完成（`SetResult()`），从而唤醒所有等待帧末的协程继续执行。

**关键特性：**
- **顺序唤醒**：FIFO 队列保证入队顺序即唤醒顺序，行为确定
- **批量执行**：一帧内所有等待者在同一 `FrameFinishUpdate` 调用中被集体唤醒
- **无限制数量**：任意多个协程可同时等待帧末，没有并发数量上限

---

## 四、与帧驱动流水线的时序关系

`Game` 静态类的帧驱动调用顺序如下：

```
MonoBehaviour.Update()
    └─ Game.Update()          ← 所有 ISingletonUpdate 系统
    
MonoBehaviour.FixedUpdate()
    └─ Game.BeforeFixedUpdate() ← 物理前置准备
    └─ Game.FixedUpdate()       ← 物理帧主逻辑
    └─ Game.LateFixedUpdate()   ← 物理帧后处理
    
MonoBehaviour.LateUpdate()
    └─ Game.LateUpdate()       ← 所有 ISingletonLateUpdate 系统
    └─ Game.FrameFinishUpdate() ← 帧末任务批量唤醒  ★
```

`FrameFinishUpdate` 处于整帧调度的最后一步，确保所有系统（Update、FixedUpdate、LateUpdate）都执行完毕后，才统一唤醒等待者。

---

## 五、典型使用场景

### 场景一：等待本帧所有状态更新完成后再读取数据

```csharp
public async ETTask RefreshUI()
{
    // 触发数据更新（异步，可能在 Update 中生效）
    RequestDataUpdate();
    
    // 等待本帧所有 Update 完成
    await Game.WaitFrameFinish();
    
    // 此时所有单例 Update 已执行完毕，数据已是最新状态
    RenderUI(GetLatestData());
}
```

### 场景二：帧内防重入保护

某些逻辑希望在同一帧内只被处理一次，第二次调用直接等到下帧：

```csharp
private bool processedThisFrame = false;

public async ETTask ProcessOnce()
{
    if (processedThisFrame) 
    {
        await Game.WaitFrameFinish(); // 等待帧末，下帧重置
        processedThisFrame = false;
        return;
    }
    
    processedThisFrame = true;
    DoProcess();
    
    await Game.WaitFrameFinish();
    processedThisFrame = false; // 帧末重置标记
}
```

### 场景三：动画与逻辑的帧边界同步

```csharp
public async ETTask PlayEffectAfterLogic()
{
    // 先执行逻辑计算
    CalculateDamage();
    
    // 等帧末，确保所有受击逻辑在本帧完成
    await Game.WaitFrameFinish();
    
    // 下一帧开始时触发特效，视觉上更顺滑
    PlayHitEffect();
}
```

### 场景四：批量销毁对象的延迟清理

避免在当前帧迭代中途销毁正在遍历的对象：

```csharp
public async ETTask DestroyPendingEntities()
{
    foreach (var entity in pendingDestroyList)
    {
        entity.MarkForDestroy();
    }
    
    // 等本帧所有系统执行完毕
    await Game.WaitFrameFinish();
    
    // 帧末安全销毁
    foreach (var entity in pendingDestroyList)
    {
        entity.Destroy();
    }
    pendingDestroyList.Clear();
}
```

---

## 六、与 ETTask.NextFrame 的区别

框架中另有 `ETTask.NextFrame()` 等类似工具，二者区别如下：

| 特性 | `WaitFrameFinish` | `ETTask.NextFrame` |
|------|------------------|-------------------|
| 唤醒时机 | 当前帧的最末尾（LateUpdate后）| 下一帧的 Update 开始前 |
| 等待跨度 | 在同一帧内完成（帧末） | 跨越到下一帧 |
| 适用场景 | 帧内屏障同步 | 延迟到下帧执行 |
| GC 压力 | 零（ETTask 对象池） | 零（同样对象池） |

`WaitFrameFinish` 的核心价值在于：它是**帧内屏障（intra-frame barrier）**，而非帧间延迟。

---

## 七、设计亮点总结

1. **极简实现**：仅用一个 `Queue<ETTask>` 和两个方法，实现了生产消费级的帧末同步
2. **零GC**：`ETTask.Create(true)` 利用对象池，入队和唤醒全程无堆分配
3. **与主循环解耦**：`WaitFrameFinish` 可在任意单例、组件、系统中调用，不依赖具体 MonoBehaviour
4. **多协程并发友好**：多个协程同时等待，在同一 `FrameFinishUpdate` 中集体唤醒，无竞态风险

---

## 八、实现类似机制的注意事项

如果你在自己的框架中实现类似机制，需要注意：

- **必须保证 `FrameFinishUpdate` 只调用一次/帧**，否则等待者会被提前唤醒
- **不要在 `FrameFinishUpdate` 内部调用 `WaitFrameFinish`**，否则新入队的任务也会在同帧被唤醒，产生死循环风险（当前实现用 `while(Count > 0)` 遍历，会处理循环中途入队的新任务）
- **线程安全**：`frameFinishTask` 仅在主线程访问，无需加锁

---

## 总结

`Game.WaitFrameFinish` 是 ET/ECS 框架主循环设计中的一颗"隐藏宝石"：用最简洁的队列实现，提供了协程级别的帧边界同步能力。理解它的时序位置（LateUpdate 之后的帧末），掌握它与 `NextFrame` 的本质区别（帧内屏障 vs 帧间延迟），是写出时序正确、高效的游戏框架逻辑的重要基础。

在战斗系统、UI 刷新、资源延迟销毁等场景中，合理使用帧末等待可以大幅提升逻辑的健壮性和可维护性。
