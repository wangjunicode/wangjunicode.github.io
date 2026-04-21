---
title: 协程锁CoroutineLock系统深度解析——基于ETTask的异步互斥队列实现原理
published: 2026-04-21
description: 深入剖析ET框架Core/CoroutineLock目录下的协程锁全链路实现，从CoroutineLockComponent统一调度、CoroutineLockQueueType分类索引、CoroutineLockQueue队列排队，到WaitCoroutineLock超时兜底机制，结合源码逐层拆解异步互斥的完整工程方案。
tags: [Unity, 游戏框架, CSharp, 协程锁, ETTask, 并发]
category: 游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

## 引言

在服务端或大型游戏客户端开发中，异步并发带来了资源竞争问题。传统 `lock` 关键字无法用于 `async/await` 语境，ET 框架因此自研了一套**协程锁（CoroutineLock）**机制，基于 `ETTask` 构建了一个纯异步、可超时、池化复用的互斥队列系统。

本文将从最顶层的调度入口逐层向下，完整还原这套系统的工作原理。

---

## 整体架构一览

```
CoroutineLockComponent（单例调度器）
    └── CoroutineLockQueueType[]（按类型分组，最多100种）
            └── Dictionary<long, CoroutineLockQueue>（按 key 细分队列）
                    └── Queue<WaitCoroutineLock>（等待者队列）
                            └── CoroutineLock（锁令牌，IDisposable）
```

使用方式只需一行：
```csharp
using (await CoroutineLockComponent.Instance.Wait(CoroutineLockType.DB, entityId))
{
    // 临界区代码，同一 key 同时只有一个协程在此执行
}
```

---

## CoroutineLockComponent：单例调度中枢

```csharp
public class CoroutineLockComponent : Singleton<CoroutineLockComponent>, ISingletonUpdate
{
    private readonly List<CoroutineLockQueueType> list = new(CoroutineLockType.Max);
    private readonly Queue<(int, long, int)> nextFrameRun = new();
    // ...
}
```

**构造期初始化**：预先分配 `CoroutineLockType.Max`（100）个 `CoroutineLockQueueType` 槽位，对应不同业务类型（DB、UI、Location 等），避免运行时动态创建。

### Update 驱动：延迟到下一帧再唤醒

```csharp
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
```

**关键设计**：当一个持锁协程 `Dispose` 时，**不立即唤醒**下一个等待者，而是将通知入队 `nextFrameRun`，等下一帧 `Update` 统一处理。

这样做的原因：
1. 避免当前帧同一调用栈内的递归唤醒，防止调用栈无限深入
2. 保证同一帧内逻辑单步推进，符合帧驱动游戏的时序预期

**level == 100 预警**：若同一 key 在一帧内连续释放超过 100 次，打印 Warning，提示业务逻辑可能存在死循环风险。

---

## CoroutineLockQueueType：按类型分组管理

```csharp
public class CoroutineLockQueueType
{
    private readonly int type;
    private readonly Dictionary<long, CoroutineLockQueue> coroutineLockQueues = new();

    public async ETTask<CoroutineLock> Wait(long key, int time)
    {
        CoroutineLockQueue queue = this.Get(key) ?? this.New(key);
        return await queue.Wait(time);
    }

    public void Notify(long key, int level)
    {
        CoroutineLockQueue queue = this.Get(key);
        if (queue == null) return;

        if (queue.Count == 0)
            this.Remove(key);   // 没有等待者时回收，避免内存泄漏
        queue.Notify(level);
    }
}
```

每种锁类型（如 `CoroutineLockType.DB = 5`）对应一个 `CoroutineLockQueueType`，其内部维护一个以 `long key` 为索引的字典。

这使得**不同 key 之间完全独立**：entityId = 100 和 entityId = 200 的 DB 锁互不干扰，可并行执行；而相同 key 的请求则严格串行。

**Notify 中的自动回收**：当 `queue.Count == 0`（没有剩余等待者），立即从字典中移除该队列并调用 `Recycle()`，归还到对象池，避免空队列长期占用内存。

---

## CoroutineLockQueue：单 key 异步排队核心

```csharp
public class CoroutineLockQueue
{
    private CoroutineLock currentCoroutineLock;
    private readonly Queue<WaitCoroutineLock> queue = new();

    public async ETTask<CoroutineLock> Wait(int time)
    {
        if (this.currentCoroutineLock == null)
        {
            // 无人持锁，直接授权
            this.currentCoroutineLock = CoroutineLock.Create(type, key, 1);
            return this.currentCoroutineLock;
        }

        // 有人持锁，入队等待
        WaitCoroutineLock waitCoroutineLock = WaitCoroutineLock.Create();
        this.queue.Enqueue(waitCoroutineLock);

        if (time > 0)
        {
            long tillTime = TimeHelper.ClientFrameTime() + time;
            TimerComponent.Instance.NewOnceTimer(tillTime, TimerCoreInvokeType.CoroutineTimeout, waitCoroutineLock);
        }

        this.currentCoroutineLock = await waitCoroutineLock.Wait();
        return this.currentCoroutineLock;
    }

    public void Notify(int level)
    {
        while (this.queue.Count > 0)
        {
            WaitCoroutineLock waitCoroutineLock = queue.Dequeue();
            if (waitCoroutineLock.IsDisposed()) continue;   // 跳过已超时者

            CoroutineLock coroutineLock = CoroutineLock.Create(type, key, level);
            waitCoroutineLock.SetResult(coroutineLock);
            break;
        }
    }
}
```

### 首次进入直通

若 `currentCoroutineLock == null`，说明当前无持锁者，直接创建 `CoroutineLock` 返回，level 从 1 开始计数。

### 排队等待

若已有持锁者，创建 `WaitCoroutineLock`（本质是一个 `ETTask<CoroutineLock>` 包装），加入 FIFO 队列，然后 `await` 挂起，直到前驱释放锁。

### 超时保护

`time > 0` 时，注册一个一次性定时器，超时后调用 `WaitCoroutineLock.SetException()`，让等待协程抛出异常并退出队列，防止死锁导致协程永久挂起。

### Notify 跳过已超时者

```csharp
if (waitCoroutineLock.IsDisposed()) continue;
```

已超时的 `WaitCoroutineLock` 其 `tcs` 已被置 null（`IsDisposed() == true`），直接跳过，找到第一个仍在等待的协程激活。

---

## CoroutineLock：锁令牌——Dispose 触发释放

```csharp
public class CoroutineLock : IDisposable
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

`CoroutineLock` 实现 `IDisposable`，配合 `using` 语句实现**RAII 风格**的锁管理：

- 离开 `using` 块时自动调用 `Dispose()`
- `Dispose` 内调用 `RunNextCoroutine(level + 1)`，将唤醒下一等待者的任务推入下帧队列
- 自身字段清零后归还对象池，避免 GC 压力

`level + 1` 的意义：记录锁在当前 key 上已经传递了多少次，用于超过 100 次时的过载警告。

---

## WaitCoroutineLock：基于 ETTask 的可超时 Future

```csharp
public class WaitCoroutineLock
{
    private ETTask<CoroutineLock> tcs;

    public void SetResult(CoroutineLock coroutineLock)
    {
        var t = this.tcs;
        this.tcs = null;    // 先置 null，防止重复 SetResult
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

`WaitCoroutineLock` 是对 `ETTask<CoroutineLock>` 的轻量包装：

- `tcs != null`：处于等待状态
- `tcs == null`（`IsDisposed() == true`）：已超时或已完成

这个"置 null 再操作"的模式贯穿 ET 框架的 ETTask 使用约定，防止并发下对同一 tcs 多次 SetResult 引发的不确定行为。

### 超时回调

```csharp
[Invoke(TimerCoreInvokeType.CoroutineTimeout)]
public class WaitCoroutineLockTimer : ATimer<WaitCoroutineLock>
{
    protected override void Run(WaitCoroutineLock waitCoroutineLock)
    {
        if (waitCoroutineLock.IsDisposed()) return;
        waitCoroutineLock.SetException(new Exception("coroutine is timeout!"));
    }
}
```

通过 `TimerComponent` 的 `[Invoke]` 标注机制驱动，避免在 `Wait` 内部硬编码计时逻辑，保持关注点分离。

---

## 完整调用时序图

```
协程A调用 Wait(DB, 100)
    → CoroutineLockComponent.Wait
    → CoroutineLockQueueType[5].Wait(100, 60000)
    → CoroutineLockQueue.Wait(60000)
    → currentCoroutineLock==null，直接 Create 返回 CoroutineLockA

协程B调用 Wait(DB, 100)（此时A持锁）
    → 创建 WaitCoroutineLockB，入队
    → await tcs 挂起

协程A退出 using 块，CoroutineLockA.Dispose()
    → RunNextCoroutine(DB, 100, level=2)
    → nextFrameRun.Enqueue(...)

下一帧 Update()
    → Notify(DB, 100, 2)
    → CoroutineLockQueueType[5].Notify(100, 2)
    → CoroutineLockQueue.Notify(2)
    → WaitCoroutineLockB.SetResult(CoroutineLockB)
    → 协程B恢复执行，进入临界区
```

---

## 工程实践要点

| 要点 | 说明 |
|------|------|
| 必须用 `using` | 确保锁一定被释放，防止后续协程永久阻塞 |
| time 参数设合理值 | 默认 60000ms，高频低延迟场景可适当缩短 |
| key 设计要唯一且稳定 | 通常用 entityId、userId 等业务主键 |
| 避免嵌套同类型锁 | 同协程内对同一 type+key 重入会死锁 |
| level 超 100 要排查 | 说明某 key 下队列积压过深，可能存在逻辑 bug |

---

## 小结

ET 框架的 `CoroutineLock` 系统通过**类型索引 + key 哈希 + FIFO 队列 + 下帧延迟唤醒**四层设计，在完全异步的 `ETTask` 环境中实现了轻量、高效、可超时的互斥锁。其核心思路与 OS 的互斥量极为相似，但完全契合单线程帧驱动的游戏主循环模型，是 ET 框架并发控制的基石组件。
