---
title: 游戏框架CoroutineLock协程锁系统完整解析-分类队列与跨帧调度机制深度剖析
published: 2026-04-28
description: 深入解析xgame框架中的协程锁（CoroutineLock）系统，涵盖锁的创建与释放、CoroutineLockQueue的等待通知机制、CoroutineLockComponent的跨帧调度设计，以及超时保护和对象池优化。
tags: [Unity, xgame, ECS, ETTask, 协程锁, 并发控制]
category: xgame框架
draft: false
encryptedKey: henhaoji123
---

## 前言

在多协程并发访问共享资源时，无锁设计很容易引发数据竞争。xgame 框架提供了一套完整的 **CoroutineLock 协程锁系统**，通过异步等待队列实现"逻辑上的串行访问"，而不会阻塞主线程。本文从源码角度全面解析这套系统的设计细节。

---

## 系统整体架构

协程锁系统由以下五个核心类组成：

```
CoroutineLockComponent（单例，驱动跨帧调度）
    └─ CoroutineLockQueueType × N（按锁类型分组）
           └─ CoroutineLockQueue（按 key 分组）
                  └─ WaitCoroutineLock（等待节点，挂起协程）
                         └─ CoroutineLock（锁令牌，Dispose 时释放）
```

---

## CoroutineLockType：锁类型枚举

```csharp
public static class CoroutineLockType
{
    public const int None = 0;
    public const int Location = 1;          // location进程
    public const int ActorLocationSender = 2;
    public const int Mailbox = 3;
    public const int UnitId = 4;
    public const int DB = 5;
    public const int Resources = 6;
    public const int ResourcesLoader = 7;
    public const int UI = 10;
    public const int DNS = 11;
    public const int ZoneLogin = 12;
    public const int Max = 100;             // 最大类型数
}
```

锁类型的作用是将不同业务域的锁**隔离管理**，避免跨业务互相干扰。`Max = 100` 定义了系统最多支持的锁类型数量，`CoroutineLockComponent` 初始化时会预分配 100 个 `CoroutineLockQueueType`。

---

## CoroutineLock：锁令牌（IDisposable）

```csharp
public class CoroutineLock: IDisposable
{
    private int type;
    private long key;
    private int level;
    
    public static CoroutineLock Create(int type, long k, int count)
    {
        CoroutineLock coroutineLock = ObjectPool.Instance.Fetch<CoroutineLock>();
        coroutineLock.type = type;
        coroutineLock.key = k;
        coroutineLock.level = count;
        return coroutineLock;
    }
    
    public void Dispose()
    {
        CoroutineLockComponent.Instance.RunNextCoroutine(this.type, this.key, this.level + 1);
        
        this.type = CoroutineLockType.None;
        this.key = 0;
        this.level = 0;
        
        ObjectPool.Instance.Recycle(this);
    }
}
```

### 核心字段

| 字段 | 含义 |
|------|------|
| `type` | 锁类型（来自 CoroutineLockType） |
| `key` | 锁的具体 key（同类型下区分不同资源） |
| `level` | 当前持有层级（每次传递 +1） |

### Dispose 流程

`Dispose()` 并不立即唤醒下一个等待者，而是调用 `RunNextCoroutine` **将通知入队**，由 `CoroutineLockComponent.Update` 在下一帧统一处理。

这是**跨帧调度**的关键所在：避免在同一帧内无限递归地释放→获取→释放。

---

## CoroutineLockQueue：单 key 等待队列

```csharp
public class CoroutineLockQueue
{
    private CoroutineLock currentCoroutineLock;
    private readonly Queue<WaitCoroutineLock> queue = new Queue<WaitCoroutineLock>();

    public async ETTask<CoroutineLock> Wait(int time)
    {
        // 无人持有，直接创建并返回
        if (this.currentCoroutineLock == null)
        {
            this.currentCoroutineLock = CoroutineLock.Create(type, key, 1);
            return this.currentCoroutineLock;
        }

        // 有人持有，创建等待节点并入队
        WaitCoroutineLock waitCoroutineLock = WaitCoroutineLock.Create();
        this.queue.Enqueue(waitCoroutineLock);
        
        // 设置超时保护
        if (time > 0)
        {
            long tillTime = TimeHelper.ClientFrameTime() + time;
            TimerComponent.Instance.NewOnceTimer(tillTime, TimerCoreInvokeType.CoroutineTimeout, waitCoroutineLock);
        }
        
        // 挂起协程，等待 SetResult
        this.currentCoroutineLock = await waitCoroutineLock.Wait();
        return this.currentCoroutineLock;
    }

    public void Notify(int level)
    {
        // 跳过已超时（已 Dispose）的节点
        while (this.queue.Count > 0)
        {
            WaitCoroutineLock waitCoroutineLock = queue.Dequeue();
            if (waitCoroutineLock.IsDisposed())
                continue;

            CoroutineLock coroutineLock = CoroutineLock.Create(type, key, level);
            waitCoroutineLock.SetResult(coroutineLock);
            break;
        }
    }
}
```

### 等待流程图

```
协程 A 调用 Wait()
    ├─ currentCoroutineLock == null → 立即获得锁，返回
    └─ currentCoroutineLock != null → 
           创建 WaitCoroutineLock 入队
           启动超时计时器
           await tcs → 挂起

协程 A Dispose() →
    RunNextCoroutine 入队
    → 下帧 Update() 调用 Notify()
    → 协程 B 的 WaitCoroutineLock.SetResult()
    → 协程 B 恢复执行
```

---

## WaitCoroutineLock：等待节点

```csharp
public class WaitCoroutineLock
{
    private ETTask<CoroutineLock> tcs;

    public void SetResult(CoroutineLock coroutineLock)
    {
        var t = this.tcs;
        this.tcs = null;        // 清空，标记已处理
        t.SetResult(coroutineLock);
    }

    public void SetException(Exception exception)
    {
        var t = this.tcs;
        this.tcs = null;
        t.SetException(exception);
    }

    public bool IsDisposed() => this.tcs == null;

    public async ETTask<CoroutineLock> Wait() => await this.tcs;
}
```

`IsDisposed()` 通过判断 `tcs == null` 来检测节点是否已被超时处理。超时时，`WaitCoroutineLockTimer` 会调用 `SetException`，将 tcs 置空；`Notify` 跳过这种节点，保证队列不堵塞。

---

## CoroutineLockComponent：核心调度中枢

```csharp
public class CoroutineLockComponent: Singleton<CoroutineLockComponent>, ISingletonUpdate
{
    private readonly List<CoroutineLockQueueType> list = new List<CoroutineLockQueueType>(CoroutineLockType.Max);
    private readonly Queue<(int, long, int)> nextFrameRun = new Queue<(int, long, int)>();

    public void Update()
    {
        while (this.nextFrameRun.Count > 0)
        {
            (int coroutineLockType, long key, int count) = this.nextFrameRun.Dequeue();
            this.Notify(coroutineLockType, key, count);
        }
    }

    public void RunNextCoroutine(int coroutineLockType, long key, int level)
    {
        if (level == 100)
            Log.Warning($"too much coroutine level: {coroutineLockType} {key}");

        this.nextFrameRun.Enqueue((coroutineLockType, key, level));
    }

    public async ETTask<CoroutineLock> Wait(int coroutineLockType, long key, int time = 60000)
    {
        CoroutineLockQueueType coroutineLockQueueType = this.list[coroutineLockType];
        return await coroutineLockQueueType.Wait(key, time);
    }
}
```

### 跨帧设计的价值

- **防止同帧递归爆栈**：如果 Dispose 立即触发 Notify，而 Notify 又立即唤醒下一个协程去 Dispose，可能产生无边界的同帧调用链。
- **Update 中的 while 循环**：注释中说明"循环过程中会有对象继续加入队列"，所以用 while 而非 foreach，处理同帧产生的新通知。
- **level 监控**：当同一 key 在同一帧被传递超过 100 次时，打印 Warning，便于发现过度竞争的热点资源。

---

## CoroutineLockQueueType：类型级分组

```csharp
public class CoroutineLockQueueType
{
    private readonly Dictionary<long, CoroutineLockQueue> coroutineLockQueues;

    public async ETTask<CoroutineLock> Wait(long key, int time)
    {
        CoroutineLockQueue queue = this.Get(key) ?? this.New(key);
        return await queue.Wait(time);
    }

    public void Notify(long key, int level)
    {
        CoroutineLockQueue queue = this.Get(key);
        if (queue == null) return;
        
        // 队列为空说明没有等待者，可以直接回收队列对象
        if (queue.Count == 0)
            this.Remove(key);   // 同时回收 CoroutineLockQueue 到对象池

        queue.Notify(level);
    }
}
```

**按需创建，用完回收**：当 `Count == 0` 时从字典中移除并回收队列对象，避免长期积累大量空队列。

---

## 实际使用示例

```csharp
// 对同一个 UnitId 加锁，防止并发修改
using CoroutineLock coroutineLock = 
    await CoroutineLockComponent.Instance.Wait(CoroutineLockType.UnitId, unitId);

// 在锁保护区域内安全操作
await DoSomethingAsync(unitId);

// using 块结束，自动 Dispose → 释放锁给下一个等待者
```

---

## 超时保护机制

```csharp
[Invoke(TimerCoreInvokeType.CoroutineTimeout)]
public class WaitCoroutineLockTimer: ATimer<WaitCoroutineLock>
{
    protected override void Run(WaitCoroutineLock waitCoroutineLock)
    {
        if (waitCoroutineLock.IsDisposed()) return;
        waitCoroutineLock.SetException(new Exception("coroutine is timeout!"));
    }
}
```

默认超时时间 `60000ms`（60秒），超时后抛出异常，上层协程需通过 `try/catch` 处理，防止锁被永久持有导致队列死锁。

---

## 总结

xgame 的 CoroutineLock 系统有以下设计亮点：

1. **异步队列实现串行**：不阻塞主线程，完全基于 ETTask 异步等待
2. **跨帧延迟通知**：通过 `nextFrameRun` 队列将锁释放推迟到下帧 Update，避免同帧递归
3. **超时保护**：每个等待节点都有超时计时器，防止死锁
4. **对象池复用**：CoroutineLock、CoroutineLockQueue、WaitCoroutineLock 全部走对象池
5. **类型+key 双维度隔离**：不同业务域互不干扰，同域内按资源 key 细粒度加锁
