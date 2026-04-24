---
title: WaitCoroutineLock协程锁等待节点ETTask桥接与超时定时器的完整设计解析
published: 2026-04-24
description: 深入解析 ET 框架中 WaitCoroutineLock 的设计原理，包括 ETTask 桥接模式、ATimer 超时检测机制、IsDisposed 防重入逻辑，以及与 CoroutineLockComponent 的协作流程。
tags: [Unity, ECS, ETTask, 协程锁, 定时器, 异步编程]
category: 游戏框架
encryptedKey: henhaoji123
draft: false
---

## 引言

在 ET 框架的协程锁体系中，`CoroutineLock` 负责持有与释放，`CoroutineLockQueue` 负责排队调度，而真正把"等待排队"这件事接入异步管道的枢纽，是 **`WaitCoroutineLock`**。

它只有几十行代码，却完成了三件关键事情：

1. 把一次"锁等待"包装成一个可 `await` 的 `ETTask<CoroutineLock>`
2. 超时后通过 `ATimer` 机制注入异常，打断等待
3. 通过 `IsDisposed` 防止双重触发

本文逐行拆解这三层设计。

---

## 源码全文

```csharp
[Invoke(TimerCoreInvokeType.CoroutineTimeout)]
public class WaitCoroutineLockTimer: ATimer<WaitCoroutineLock>
{
    protected override void Run(WaitCoroutineLock waitCoroutineLock)
    {
        if (waitCoroutineLock.IsDisposed())
        {
            return;
        }
        waitCoroutineLock.SetException(new Exception("coroutine is timeout!"));
    }
}

public class WaitCoroutineLock
{
    public static WaitCoroutineLock Create()
    {
        WaitCoroutineLock waitCoroutineLock = new WaitCoroutineLock();
        waitCoroutineLock.tcs = ETTask<CoroutineLock>.Create(true);
        return waitCoroutineLock;
    }

    private ETTask<CoroutineLock> tcs;

    public void SetResult(CoroutineLock coroutineLock)
    {
        if (this.tcs == null)
            throw new NullReferenceException("SetResult tcs is null");
        var t = this.tcs;
        this.tcs = null;
        t.SetResult(coroutineLock);
    }

    public void SetException(Exception exception)
    {
        if (this.tcs == null)
            throw new NullReferenceException("SetException tcs is null");
        var t = this.tcs;
        this.tcs = null;
        t.SetException(exception);
    }

    public bool IsDisposed()
    {
        return this.tcs == null;
    }

    public async ETTask<CoroutineLock> Wait()
    {
        return await this.tcs;
    }
}
```

---

## 一、为什么需要 WaitCoroutineLock？

`CoroutineLockQueue` 在队列非空时，会把新来的等待者追加到内部队列，并**挂起**调用方。挂起的本质是：把调用方的续体（continuation）存起来，后续在适当时机恢复。

ET 框架使用 `ETTask<T>` 作为异步载体，`ETTask<T>` 本身支持手动完成（`SetResult`/`SetException`），因此只需要：

- 为每次"入队等待"创建一个 `WaitCoroutineLock` 实例
- 把 `tcs`（内部的 `ETTask<CoroutineLock>`）交给调用方 `await`
- 当前一个锁释放时，调用 `SetResult` 传入新的 `CoroutineLock`，续体恢复执行

这是典型的 **TaskCompletionSource 模式** 在自研异步框架中的应用。

---

## 二、ETTask 的桥接细节

### `Create` 工厂方法

```csharp
public static WaitCoroutineLock Create()
{
    WaitCoroutineLock waitCoroutineLock = new WaitCoroutineLock();
    waitCoroutineLock.tcs = ETTask<CoroutineLock>.Create(true);
    return waitCoroutineLock;
}
```

`ETTask<T>.Create(true)` 中的 `true` 表示**开启对象池复用**。  
这意味着 `tcs` 完成后会被归还对象池，避免每次等待都产生新的 GC 分配。

### `Wait()` 方法

```csharp
public async ETTask<CoroutineLock> Wait()
{
    return await this.tcs;
}
```

调用方写法：

```csharp
using CoroutineLock coroutineLock = await coroutineLockComponent.Wait(CoroutineLockType.Bag, bagId);
```

`coroutineLockComponent.Wait` 内部会创建 `WaitCoroutineLock`，调用其 `Wait()` 方法，然后将实例存入等待队列。当队列头部的锁释放时，调用 `SetResult`，此处的 `await` 即恢复执行。

### `SetResult` 的"先置空再触发"惯用法

```csharp
public void SetResult(CoroutineLock coroutineLock)
{
    var t = this.tcs;
    this.tcs = null;      // ① 先将字段置空
    t.SetResult(coroutineLock); // ② 再触发续体
}
```

顺序非常关键：续体恢复后可能在当前帧内再次调用 `SetResult`/`SetException`（如递归场景），若先触发再置空，就可能出现重复调用 `tcs` 的问题。"先置空"是防止重入的标准做法。

---

## 三、超时机制：ATimer 的角色

### ATimer 基类

```csharp
public abstract class ATimer<T>: AInvokeHandler<TimerCallback> where T: class
{
    public override void Handle(TimerCallback a)
    {
        this.Run(a.Args as T);
    }
    protected abstract void Run(T t);
}
```

`ATimer<T>` 继承自 `AInvokeHandler<TimerCallback>`，这意味着它是一个**可被 TimerComponent 驱动**的回调处理器。框架在计时触发时，调用 `Handle(TimerCallback)`，参数 `Args` 就是注册时传入的数据对象。

### WaitCoroutineLockTimer

```csharp
[Invoke(TimerCoreInvokeType.CoroutineTimeout)]
public class WaitCoroutineLockTimer: ATimer<WaitCoroutineLock>
{
    protected override void Run(WaitCoroutineLock waitCoroutineLock)
    {
        if (waitCoroutineLock.IsDisposed())
            return;
        waitCoroutineLock.SetException(new Exception("coroutine is timeout!"));
    }
}
```

`[Invoke(TimerCoreInvokeType.CoroutineTimeout)]` 将此类注册到定时器类型 `CoroutineTimeout` 下。

当 `CoroutineLockComponent.Wait` 被调用时，如果传入了超时时间（毫秒），框架会同时启动一个 `CoroutineTimeout` 定时器，计时到期后回调 `WaitCoroutineLockTimer.Run`。

**防止双重触发**：

```csharp
if (waitCoroutineLock.IsDisposed()) return;
```

`IsDisposed()` 检查 `tcs == null`。如果锁在超时触发前就已经正常 `SetResult`，`tcs` 已经被置空，`IsDisposed()` 返回 `true`，定时器回调直接跳过，不会抛出异常。

这保证了"正常完成"和"超时取消"只有一个会生效，互斥且安全。

---

## 四、完整时序图

```
调用方                CoroutineLockComponent       WaitCoroutineLock      TimerComponent
  │                          │                            │                     │
  ├─── Wait(type, id, timeout) ──►                        │                     │
  │                    创建 WaitCoroutineLock              │                     │
  │                          ├─── Create() ──────────────►│                     │
  │                          │                     tcs = ETTask.Create()        │
  │                    入队, 启动超时定时器                  │                     │
  │                          ├──────────────────────────────────────────────────►│
  │                          │                            │            注册 CoroutineTimeout
  │◄── await Wait() ─────────┤◄─── Wait() ───────────────┤             after timeout ms
  │ (挂起)                                                │                     │
  │                  上一个锁释放                          │                     │
  │                          ├─── SetResult(lock) ────────►                     │
  │                    tcs=null, t.SetResult              │                     │
  │◄── 续体恢复，持有 lock ────┤                            │                     │
  │                          │                            │                     │
  │                          │                            │◄─ (若超时前已完成，IsDisposed=true，跳过)
```

---

## 五、设计亮点总结

| 设计点 | 说明 |
|--------|------|
| **ETTask 桥接** | 利用 `ETTask<T>` 的手动完成能力，将"等待排队"变为可 `await` 的异步点 |
| **对象池复用** | `ETTask.Create(true)` 开启池化，减少 GC |
| **先置空再触发** | 防止续体恢复后重入导致 `tcs` 被二次调用 |
| **ATimer 超时** | 通过类型化定时器驱动超时逻辑，与主异步流解耦 |
| **IsDisposed 互斥** | 正常完成与超时触发通过 `tcs == null` 实现互斥 |

---

## 六、实际使用示例

```csharp
// 加锁，超时 3000ms
using CoroutineLock coroutineLock = 
    await Game.Root.Scene.GetComponent<CoroutineLockComponent>()
              .Wait(CoroutineLockType.Bag, playerId, 3000);

// 临界区代码
await ModifyBag(playerId);

// using 块结束自动释放锁（调用 CoroutineLock.Dispose）
```

若 3 秒内未获取到锁，`WaitCoroutineLockTimer` 触发，`SetException` 将 `ETTask` 置为异常状态，`await` 处抛出 `"coroutine is timeout!"` 异常，调用方需自行捕获处理。

---

## 结语

`WaitCoroutineLock` 是协程锁体系的"接入层"——它把调度逻辑（谁排队、谁触发）与异步通信（怎么挂起、怎么恢复）彻底解耦。配合 `ATimer` 超时机制，整个协程锁系统在没有一行 C# 内置 `lock` 的情况下，实现了异步安全的互斥访问与超时保护。理解这个小类，是理解 ET 异步调度的最后一块拼图。
