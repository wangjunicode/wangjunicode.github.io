---
title: 协程锁队列与等待机制：CoroutineLockQueue的完整实现解析
published: 2026-04-07
tags: [Unity, 异步编程, 协程锁, ECS, 并发安全]
category: 游戏框架
draft: false
encryptedKey: henhaoji123
---

# 协程锁队列与等待机制：CoroutineLockQueue的完整实现解析

## 前言

在 ET/VGame 框架的异步体系里，`CoroutineLockComponent` 是解决"同一逻辑资源被多个协程并发访问"问题的核心组件。  
上层开发者只需 `await CoroutineLockComponent.Instance.Wait(type, key)` 便能优雅地串行化一段异步代码，但这背后涉及三个协同工作的类：

- `CoroutineLockQueue` —— 按 key 管理的等待队列
- `WaitCoroutineLock` —— 单个等待节点，持有 ETTask 的 TCS
- `CoroutineLock` —— 锁的句柄，Dispose 时自动释放并唤醒下一个等待者

本文将深入源码，从数据结构到超时机制逐一拆解。

---

## 一、CoroutineLockQueueType：按 type 分桶

`CoroutineLockComponent` 内部维护了一个 `List<CoroutineLockQueueType>`，长度等于 `CoroutineLockType.Max`。  
每个 `CoroutineLockQueueType` 负责管理同一 `type` 下的所有 key，本质上是一个 `Dictionary<long, CoroutineLockQueue>`。

```csharp
// 按 key 取到对应的 CoroutineLockQueue
public async ETTask<CoroutineLock> Wait(long key, int time)
{
    if (!queues.TryGetValue(key, out var queue))
    {
        queue = CoroutineLockQueue.Create(type, key);
        queues[key] = queue;
    }
    return await queue.Wait(time);
}
```

分桶的意义在于：**不同 type 的锁完全隔离，相同 type 下按 key 串行**。  
例如背包操作是 `type=Inventory`，数据库操作是 `type=DB`，两者之间不会产生任何竞争。

---

## 二、CoroutineLockQueue：单 key 等待队列

```csharp
public class CoroutineLockQueue
{
    private int type;
    private long key;
    private CoroutineLock currentCoroutineLock;          // 当前持有锁的协程句柄
    private readonly Queue<WaitCoroutineLock> queue = new(); // 等待队列
    
    public async ETTask<CoroutineLock> Wait(int time)
    {
        // 无人持锁 → 直接返回新锁
        if (this.currentCoroutineLock == null)
        {
            this.currentCoroutineLock = CoroutineLock.Create(type, key, 1);
            return this.currentCoroutineLock;
        }

        // 已有人持锁 → 排队
        WaitCoroutineLock waitCoroutineLock = WaitCoroutineLock.Create();
        this.queue.Enqueue(waitCoroutineLock);
        
        // 设置超时定时器
        if (time > 0)
        {
            long tillTime = TimeHelper.ClientFrameTime() + time;
            TimerComponent.Instance.NewOnceTimer(tillTime, TimerCoreInvokeType.CoroutineTimeout, waitCoroutineLock);
        }
        
        // 挂起协程，等待被唤醒
        this.currentCoroutineLock = await waitCoroutineLock.Wait();
        return this.currentCoroutineLock;
    }
}
```

### 核心流程

```
第一个请求者                  第二个请求者                第三个请求者
     │                           │                          │
     ▼                           ▼                          ▼
currentLock = null?          currentLock ≠ null          currentLock ≠ null
     │ Yes                        │                          │
     ▼                            ▼                          ▼
直接拿锁，返回               创建 WaitCoroutineLock        创建 WaitCoroutineLock
currentLock = LockA          入队，await 挂起              入队，await 挂起
                              (queue=[W2])                  (queue=[W2,W3])
```

当第一个请求者 `Dispose(LockA)` 时，触发 `RunNextCoroutine` → 下一帧 `Notify`，唤醒 W2，W2 拿到新锁继续执行。

---

## 三、WaitCoroutineLock：TCS 包装器

`WaitCoroutineLock` 是一个极简的 TaskCompletionSource 包装：

```csharp
public class WaitCoroutineLock
{
    private ETTask<CoroutineLock> tcs;

    public static WaitCoroutineLock Create()
    {
        var w = new WaitCoroutineLock();
        w.tcs = ETTask<CoroutineLock>.Create(true); // true = 从对象池获取
        return w;
    }

    public void SetResult(CoroutineLock coroutineLock)
    {
        var t = this.tcs;
        this.tcs = null; // 先置 null，防止重复 SetResult
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

**tcs 置 null 即代表 Disposed**，这是一个高效且线程安全的判空技巧。  
当超时定时器触发时，先检查 `IsDisposed()`，若已 Disposed 则跳过，避免双重触发。

---

## 四、超时机制：WaitCoroutineLockTimer

```csharp
[Invoke(TimerCoreInvokeType.CoroutineTimeout)]
public class WaitCoroutineLockTimer : ATimer<WaitCoroutineLock>
{
    protected override void Run(WaitCoroutineLock waitCoroutineLock)
    {
        if (waitCoroutineLock.IsDisposed())
            return; // 已正常获取锁，定时器作废
        
        waitCoroutineLock.SetException(new Exception("coroutine is timeout!"));
    }
}
```

超时后，`SetException` 会让 `await waitCoroutineLock.Wait()` 抛出异常，协程的调用方捕获到 `Exception` 后可做降级处理（如放弃本次操作或重试）。

但此时 `WaitCoroutineLock` 已被 Dispose，队列里依然有它的引用。  
`Notify` 方法专门处理这种情况：

```csharp
public void Notify(int level)
{
    while (this.queue.Count > 0)
    {
        WaitCoroutineLock waitCoroutineLock = queue.Dequeue();
        
        if (waitCoroutineLock.IsDisposed()) // 已超时，跳过
            continue;
        
        CoroutineLock coroutineLock = CoroutineLock.Create(type, key, level);
        waitCoroutineLock.SetResult(coroutineLock);
        break; // 只唤醒一个
    }
}
```

超时的等待者会被自动跳过，直到找到一个还活着的等待者为止。

---

## 五、CoroutineLock：锁句柄的释放链路

```csharp
public class CoroutineLock : IDisposable
{
    private int type;
    private long key;
    private int level; // 锁的传递层级，用于检测异常嵌套

    public void Dispose()
    {
        // 通知下一帧运行队列里的下一个
        CoroutineLockComponent.Instance.RunNextCoroutine(this.type, this.key, this.level + 1);

        // 清零并回收到对象池
        this.type = CoroutineLockType.None;
        this.key = 0;
        this.level = 0;
        ObjectPool.Instance.Recycle(this);
    }
}
```

`level + 1` 的递增是一个调试辅助手段。  
`CoroutineLockComponent.Update` 会检测：

```csharp
if (level == 100)
    Log.Warning($"too much coroutine level: {coroutineLockType} {key}");
```

如果同一个 key 在一帧内被唤醒了 100 次，说明可能存在逻辑 bug（如某处不断重入锁而不是排队）。

---

## 六、下一帧执行的设计理由

`CoroutineLock.Dispose` 并不直接调用 `Notify`，而是先将 `(type, key, level)` 放入 `nextFrameRun` 队列，在下一帧的 `Update` 里统一处理：

```csharp
public void Update()
{
    while (this.nextFrameRun.Count > 0)
    {
        (int coroutineLockType, long key, int count) = this.nextFrameRun.Dequeue();
        this.Notify(coroutineLockType, key, count);
    }
}
```

**为什么不立即唤醒？**

1. **避免调用栈过深**：如果在锁的持有者的 `Dispose` 调用栈中立即唤醒下一个等待者，而那个等待者又立即运行完并再次 Dispose，就会形成递归调用，可能溢出。

2. **帧一致性**：将唤醒推迟到下一帧，保证本帧内所有的状态变更都已提交，下一帧的逻辑以干净的状态开始。

3. **可观测性**：`nextFrameRun` 队列的长度可以作为监控指标，用于检测协程竞争是否过于激烈。

---

## 七、完整使用示例

```csharp
// 正确用法：using 语法保证锁一定被释放
public async ETTask HandleInventoryAdd(long playerId, ItemData item)
{
    using (await CoroutineLockComponent.Instance.Wait(CoroutineLockType.Inventory, playerId))
    {
        // 临界区：此时没有其他协程能同时操作该玩家的背包
        var inventory = GetInventory(playerId);
        inventory.AddItem(item);
        await SaveInventoryAsync(inventory);
    } 
    // Dispose 在这里被隐式调用，下一帧唤醒队列中下一个等待者
}
```

---

## 八、设计总结

| 组件 | 职责 | 关键实现 |
|------|------|---------|
| `CoroutineLockComponent` | 全局入口，按 type 分桶 | `List<CoroutineLockQueueType>` |
| `CoroutineLockQueueType` | 同一 type 下按 key 管理 | `Dictionary<long, Queue>` |
| `CoroutineLockQueue` | 单 key 的等待队列 | `Queue<WaitCoroutineLock>` |
| `WaitCoroutineLock` | 单个等待节点 | ETTask TCS 包装 |
| `CoroutineLock` | 锁句柄 | Dispose → 唤醒下一个 |

协程锁的设计精妙之处在于：**它没有使用任何操作系统级的锁原语（Mutex、Monitor），完全依赖单线程的 async/await 状态机实现了逻辑上的互斥**。这在 Unity 的单线程主循环模型下既高效又安全，是 ECS 框架异步并发安全的基石。
