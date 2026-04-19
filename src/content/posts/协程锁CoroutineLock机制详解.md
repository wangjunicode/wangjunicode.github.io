---
title: 07 协程锁 CoroutineLock 机制详解
published: 2024-01-01
description: "07 协程锁 CoroutineLock 机制详解 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 07 协程锁 CoroutineLock 机制详解

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

在异步编程中，经常会遇到"并发安全"问题：多个协程同时对同一资源进行操作时，如果没有保护机制，就会产生数据竞争（Data Race）。

在传统多线程编程中，我们使用 `lock`、`Mutex`、`Semaphore` 等机制。但本框架是**单线程**的异步模型（所有协程都在主线程上按序执行），不存在真正的线程并发，却存在**逻辑并发**——多个 `async ETTask` 协程在 `await` 处交错执行，可能产生同样的竞争问题。

**CoroutineLock（协程锁）** 正是为解决这个问题而设计的：它保证同一时刻，只有一个协程能持有某把"锁"，其他协程必须排队等待。

### 典型应用场景

- 玩家背包操作（同时有两个网络请求要修改背包，必须串行处理）
- 数据库写入（同一 Entity 的多个异步写入请求需要排队）
- 定时器回调（同一 key 的多个定时器触发时需要串行执行）

---

## 2. 架构设计

### 2.1 核心组件关系

```
CoroutineLockComponent（单例，管理所有锁）
  └── list: List<CoroutineLockQueueType>   ← 按 type 分组（最多 CoroutineLockType.Max 种）
       └── CoroutineLockQueueType（某类型的所有锁）
            └── lockQueues: Dictionary<long, CoroutineLockQueue>  ← 按 key 分组
                 └── CoroutineLockQueue（某 key 下的等待队列）
                      ├── currentCoroutineLock: CoroutineLock   ← 当前持有锁的协程
                      └── queue: Queue<WaitCoroutineLock>       ← 等待中的协程列表

CoroutineLock（锁令牌，IDisposable）
  ├── type: int    ← 锁类型
  ├── key: long    ← 锁键值
  └── level: int   ← 当前层级（每次 Dispose 时 level+1，传给下一个等待者）
```

### 2.2 加锁/解锁流程

```
协程 A                         CoroutineLockQueue
  │
  ├─ await CoroutineLockComponent.Wait(type, key)
  │         ↓
  │   currentCoroutineLock == null?
  │         ├─ 是：直接创建 CoroutineLock，返回给 A（A 立即持有锁）
  │         └─ 否：创建 WaitCoroutineLock，入 queue，A 在此暂停 ────────────────┐
  │                                                                               │
  │   协程 A 持有锁，执行业务逻辑...                                              │
  │                                                                               │
  ├─ coroutineLock.Dispose()                                                      │
  │         ↓                                                                     │
  │   CoroutineLockComponent.RunNextCoroutine(type, key, level+1)                │
  │         ↓（在下一帧 Update 中）                                              │
  │   CoroutineLockQueue.Notify(level)                                           │
  │         ↓                                                                     │
  │   从 queue 取出下一个 WaitCoroutineLock，SetResult → 唤醒等待的协程 ────────┘
  │
  └─ 等待中的协程 B 被唤醒，获得锁，继续执行
```

### 2.3 为什么要"下一帧"才通知？

```csharp
// CoroutineLockComponent.cs
public void RunNextCoroutine(int coroutineLockType, long key, int level)
{
    // 注意：不是立即 Notify，而是加入 nextFrameRun 队列，下帧处理
    this.nextFrameRun.Enqueue((coroutineLockType, key, level));
}

public void Update()
{
    while (this.nextFrameRun.Count > 0)
    {
        (int type, long key, int count) = this.nextFrameRun.Dequeue();
        this.Notify(type, key, count);
    }
}
```

**原因**：如果在 `Dispose` 时立即唤醒下一个等待者，就会在当前协程的调用栈中继续执行下一个协程，形成深度递归，可能导致栈溢出。延迟到下一帧可以：
1. 展平调用栈，防止栈溢出
2. 给当前帧的其他系统一个执行机会
3. 保证锁的释放和获取之间有明确的帧边界

---

## 3. 核心代码展示

### 3.1 CoroutineLock —— 锁令牌

```csharp
// X:\UnityProj\Assets\Scripts\Core\CoroutineLock\CoroutineLock.cs

public class CoroutineLock : IDisposable
{
    private int type;
    private long key;
    private int level;  // 记录锁的当前层级（第几次被持有）

    // 从对象池创建（减少 GC）
    public static CoroutineLock Create(int type, long k, int count)
    {
        CoroutineLock coroutineLock = ObjectPool.Instance.Fetch<CoroutineLock>();
        coroutineLock.type = type;
        coroutineLock.key = k;
        coroutineLock.level = count;
        return coroutineLock;
    }

    // 释放锁：通知下一个等待者
    public void Dispose()
    {
        // 通知 CoroutineLockComponent：下一帧唤醒 (type, key) 的下一个等待者
        CoroutineLockComponent.Instance.RunNextCoroutine(this.type, this.key, this.level + 1);

        // 重置状态，放回对象池
        this.type = CoroutineLockType.None;
        this.key = 0;
        this.level = 0;
        ObjectPool.Instance.Recycle(this);
    }
}
```

### 3.2 CoroutineLockQueue —— 等待队列

```csharp
// X:\UnityProj\Assets\Scripts\Core\CoroutineLock\CoroutineLockQueue.cs

public class CoroutineLockQueue
{
    private int type;
    private long key;
    private CoroutineLock currentCoroutineLock;
    private readonly Queue<WaitCoroutineLock> queue = new();

    // 等待获取锁
    public async ETTask<CoroutineLock> Wait(int time)
    {
        if (this.currentCoroutineLock == null)
        {
            // 队列空闲：立即分配锁，返回
            this.currentCoroutineLock = CoroutineLock.Create(type, key, 1);
            return this.currentCoroutineLock;
        }

        // 已有协程持锁：创建等待令牌，入队，协程在此挂起
        WaitCoroutineLock waitCoroutineLock = WaitCoroutineLock.Create();
        this.queue.Enqueue(waitCoroutineLock);

        // 超时保护：time 毫秒后自动超时（默认 60 秒）
        if (time > 0)
        {
            long tillTime = TimeHelper.ClientFrameTime() + time;
            TimerComponent.Instance.NewOnceTimer(tillTime,
                TimerCoreInvokeType.CoroutineTimeout, waitCoroutineLock);
        }

        // await：协程在此暂停，等待 Notify 唤醒
        this.currentCoroutineLock = await waitCoroutineLock.Wait();
        return this.currentCoroutineLock;
    }

    // 唤醒下一个等待者
    public void Notify(int level)
    {
        // 跳过已超时（IsDisposed）的等待者
        while (this.queue.Count > 0)
        {
            WaitCoroutineLock waitCoroutineLock = queue.Dequeue();
            if (waitCoroutineLock.IsDisposed()) continue;

            // 创建新的锁令牌，传给等待者
            CoroutineLock coroutineLock = CoroutineLock.Create(type, key, level);
            waitCoroutineLock.SetResult(coroutineLock);  // 唤醒等待的协程
            break;
        }
    }
}
```

### 3.3 CoroutineLockComponent —— 全局管理器

```csharp
// X:\UnityProj\Assets\Scripts\Core\CoroutineLock\CoroutineLockComponent.cs

public class CoroutineLockComponent : Singleton<CoroutineLockComponent>, ISingletonUpdate
{
    private readonly List<CoroutineLockQueueType> list;
    private readonly Queue<(int, long, int)> nextFrameRun = new();

    public CoroutineLockComponent()
    {
        // 为每种锁类型预创建 CoroutineLockQueueType
        for (int i = 0; i < CoroutineLockType.Max; ++i)
            list.Add(new CoroutineLockQueueType(i));
    }

    // 每帧处理上一帧积累的"下一个协程"通知
    public void Update()
    {
        while (this.nextFrameRun.Count > 0)
        {
            (int coroutineLockType, long key, int count) = this.nextFrameRun.Dequeue();
            this.Notify(coroutineLockType, key, count);
        }
    }

    // 加锁入口：等待获取 (type, key) 对应的锁
    public async ETTask<CoroutineLock> Wait(int coroutineLockType, long key, int time = 60000)
    {
        CoroutineLockQueueType coroutineLockQueueType = this.list[coroutineLockType];
        return await coroutineLockQueueType.Wait(key, time);
    }

    // 解锁时调用：延迟到下一帧通知
    public void RunNextCoroutine(int coroutineLockType, long key, int level)
    {
        if (level == 100)
            Log.Warning($"too much coroutine level: {coroutineLockType} {key}");
        this.nextFrameRun.Enqueue((coroutineLockType, key, level));
    }
}
```

---

## 4. 使用方式详解

### 4.1 基础用法

```csharp
// 定义锁类型常量（在 CoroutineLockType.cs 中）
public static class CoroutineLockType
{
    public const int None = 0;
    public const int Bag = 1;        // 背包操作锁
    public const int Database = 2;   // 数据库操作锁
    // ... 其他类型
    public const int Max = 100;
}

// 使用协程锁保护异步操作
public async ETTask AddItemAsync(PlayerEntity player, int itemId, int count)
{
    // 1. 获取锁（以玩家 Id 作为 key，同一玩家的操作串行化）
    using CoroutineLock coroutineLock =
        await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Bag, player.Id);

    // 2. 持锁期间执行背包操作（安全区域）
    BagComponent bag = player.GetComponent<BagComponent>();
    if (bag.HasItem(itemId))
    {
        bag.AddItem(itemId, count);
        await bag.SaveToDB();  // 即使这里有 await，锁也不会被其他协程抢走
    }

    // 3. using 块结束，coroutineLock.Dispose() 自动调用，释放锁
}
```

### 4.2 嵌套锁（同一 key 的嵌套）

```csharp
// 协程 A 持有锁，在 A 内部可以再次获取同一把锁（会排到自己后面）
// 注意：这不是可重入锁！A 内部 Wait 会死锁，除非先 Dispose 外层锁

// ✅ 正确：不在持锁状态下再次 Wait 同一 key
public async ETTask ProcessAsync(long entityId)
{
    using var lockA = await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Bag, entityId);
    await DoWork();
    // lockA Dispose，下一个协程才能获得锁
}

// ❌ 错误：嵌套等待同一 key（死锁！）
public async ETTask BadProcessAsync(long entityId)
{
    using var lockA = await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Bag, entityId);
    // lockA 持有锁，下面再等同一 key 会死锁（因为 A 自己就在等）
    using var lockB = await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Bag, entityId);
}
```

### 4.3 超时处理

```csharp
// 等待最多 5 秒，超时后抛出异常
try
{
    using var lock = await CoroutineLockComponent.Instance.Wait(
        CoroutineLockType.Database, entityId, time: 5000);

    await SaveData();
}
catch (Exception e)
{
    Log.Error($"获取锁超时: {e}");
}
```

---

## 5. level 机制的作用

`CoroutineLock` 中的 `level` 字段记录了锁被传递的次数：

```
level 1 → 协程 A 持有锁
  A.Dispose() → RunNextCoroutine(type, key, level=2)
level 2 → 协程 B 持有锁
  B.Dispose() → RunNextCoroutine(type, key, level=3)
level 3 → 协程 C 持有锁
  ...
```

当 level 超过 100 时，框架会打印 Warning：
```csharp
if (level == 100)
    Log.Warning($"too much coroutine level: {coroutineLockType} {key}");
```

这是一个**性能预警**：同一帧内有 100+ 个协程串行等待同一把锁，说明该业务逻辑可能存在性能瓶颈。

---

## 6. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| 基本机制 | 相同 | 相同 |
| 超时机制 | 有 | 相同 |
| 对象池 | CoroutineLock 来自对象池 | 相同 |
| level 警告阈值 | 100 | 相同 |
| CoroutineLockType | 框架预定义 | 根据项目需求扩展 |
| 下一帧通知 | 相同 | 相同 |

---

## 7. 常见问题与最佳实践

### Q1：协程锁和线程锁（lock）的区别？

```
线程锁（lock）：
  - 阻塞线程，其他线程在 lock 块外真正等待
  - 适合多线程环境
  - 持锁期间不能 await（会死锁！）

协程锁（CoroutineLock）：
  - 不阻塞线程，只是让协程在逻辑上暂停
  - 单线程模型，无真实并发
  - 持锁期间可以 await（这正是设计目的）
```

### Q2：为什么不能在同一 key 上嵌套 Wait？

因为协程锁是**非重入**的（Non-Reentrant）。外层协程持有锁的状态下，内层 Wait 同一 key 会无限等待——因为只有外层释放锁，内层才能获得，但外层在等内层完成，形成死锁。

### Q3：如何选择 key 的值？

`key` 决定了"哪些操作需要互斥"。通常选择**业务实体的唯一 ID**：

```csharp
// 同一玩家的背包操作互斥，不同玩家可以并行
await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Bag, player.Id);

// 同一房间的战斗事件互斥
await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Battle, room.Id);
```

### Q4：using 和 try/finally 哪个更好？

```csharp
// ✅ 推荐：using 语句，简洁且保证释放
using var lock = await CoroutineLockComponent.Instance.Wait(type, key);
await DoWork();
// lock.Dispose() 自动调用

// ⚠️ 不推荐：手动管理，容易忘记释放
CoroutineLock lock = null;
try
{
    lock = await CoroutineLockComponent.Instance.Wait(type, key);
    await DoWork();
}
finally
{
    lock?.Dispose();  // 必须写 finally，否则异常时锁不会释放
}
```

---

## 8. 总结

CoroutineLock 是单线程异步模型下的"互斥锁"：

- 通过 `Queue<WaitCoroutineLock>` 实现公平排队（FIFO）
- 通过"延迟到下一帧通知"避免调用栈递归
- 通过超时机制防止死锁
- 通过 `IDisposable + using` 保证锁一定被释放

理解了 CoroutineLock，你就掌握了异步场景下保护共享资源的正确姿势。
