---
title: ETTask核心实现原理与对象池复用机制深度剖析
published: 2026-04-09
description: 从源码层面深入解析 ETTask 的内部状态机、对象池复用机制、SetResult/GetResult 流程以及与 C# 原生 Task 的本质差异。
tags: [Unity, ETTask, 异步编程, 对象池, GC优化, 源码分析]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

# ETTask 核心实现原理与对象池复用机制深度剖析

`ETTask` 是本框架自研的异步任务类型，在功能上对标 C# 原生 `Task`，但针对游戏主线程单线程环境做了深度优化：零 GC 分配、无锁设计、对象池复用。本文从源码出发，完整拆解 ETTask 的运行原理。

---

## 一、为什么不用原生 Task

原生 `Task` 在游戏场景中存在以下问题：

| 问题 | 影响 |
|------|------|
| 每次 `async` 方法调用都 new Task | 高频战斗逻辑产生大量 GC |
| Task 默认在线程池执行 | 游戏逻辑必须回主线程，需要额外同步 |
| 状态机装箱无法复用 | 每次 await 都有堆分配 |
| 异常静默丢失风险 | fire-and-forget 场景异常不可见 |

ETTask 针对以上痛点一一解决。

---

## 二、ETTask 的类型体系

```
IETTask（接口）
├── ETTask        ← 无返回值异步任务，等价于 Task
├── ETTask<T>     ← 有返回值异步任务，等价于 Task<T>
└── ETVoid        ← fire-and-forget，不可被 await

ETTaskCompleted   ← 预先完成的 Task，等价于 Task.CompletedTask
```

`ETTask` 和 `ETTask<T>` 都通过 `[AsyncMethodBuilder]` 特性绑定了自定义构建器，让编译器使用框架的对象池机制。

---

## 三、内部状态机

### 3.1 AwaiterStatus 状态枚举

```csharp
public enum AwaiterStatus
{
    Pending   = 0,  // 等待中（初始状态）
    Succeeded = 1,  // 已成功完成
    Faulted   = 2,  // 异常终止
}
```

### 3.2 核心字段

```csharp
[AsyncMethodBuilder(typeof(ETAsyncTaskMethodBuilder))]
public class ETTask : ICriticalNotifyCompletion, IETTask
{
    private static readonly Queue<ETTask> queue = new Queue<ETTask>();
    private bool fromPool;

    private AwaiterStatus state;  // 当前状态
    private object callback;      // Action（继续回调）或 ExceptionDispatchInfo（异常信息）

    // Context 传播（用于 ETCancellationToken 等跨 await 传递上下文）
    public TaskType TaskType { get; set; }
    public object Context { get; set; }
}
```

### 3.3 状态转换图

```
创建 → Pending
            │
            ├── SetResult()     → Succeeded → 触发 callback（MoveNext）→ GetResult() → 回收到池
            │
            └── SetException()  → Faulted   → 触发 callback（MoveNext）→ GetResult() → 重抛异常 → 回收到池
```

---

## 四、对象池机制

### 4.1 创建（从池中取）

```csharp
public static ETTask Create(bool fromPool = false)
{
    if (!fromPool)
        return new ETTask();

    ETTask task;
    lock (queue)
    {
        if (!queue.TryDequeue(out task))
            return new ETTask() { fromPool = true };
    }
    task.Reset();
    return task;
}

private void Reset()
{
    this.state    = AwaiterStatus.Pending;
    this.callback = null;
    this.TaskType = TaskType.Common;
    this.Context  = null;
}
```

### 4.2 回收（归还到池）

```csharp
private void Recycle()
{
    if (!this.fromPool) return;

    this.Reset();
    lock (queue)
    {
        if (queue.Count > 1000) return;  // 池满则丢弃，让 GC 回收
        queue.Enqueue(this);
    }
}
```

**关键约束**：`Recycle` 只在 `GetResult` 内部调用，即 await 完成时自动触发，外部不应手动调用。

---

## 五、SetResult 与 GetResult 流程

### 5.1 SetResult —— 异步操作完成

```csharp
public void SetResult()
{
    if (this.state != AwaiterStatus.Pending)
        throw new InvalidOperationException("ETTask already completed.");

    this.state = AwaiterStatus.Succeeded;

    // 通知等待者继续执行
    Action c = this.callback as Action;
    this.callback = null;
    c?.Invoke();  // 触发状态机的 MoveNext
}
```

### 5.2 GetResult —— await 完成后由编译器调用

```csharp
public void GetResult()
{
    switch (this.state)
    {
        case AwaiterStatus.Succeeded:
            this.Recycle();  // 成功完成，回收到对象池
            return;

        case AwaiterStatus.Faulted:
            var edi = this.callback as ExceptionDispatchInfo;
            this.callback = null;
            this.Recycle();
            edi?.Throw();    // 重抛原始异常，保留完整调用栈
            return;

        default:
            throw new NotSupportedException(
                "ETTask does not allow calling GetResult directly when Pending.");
    }
}
```

### 5.3 OnCompleted —— 注册等待回调

```csharp
public void OnCompleted(Action continuation)
    => this.UnsafeOnCompleted(continuation);

public void UnsafeOnCompleted(Action continuation)
{
    if (this.state != AwaiterStatus.Pending)
    {
        // 已经完成，直接执行（同步完成快路径）
        continuation();
        return;
    }
    this.callback = continuation;
}
```

当 `ETTask` 在注册回调之前就已经 `SetResult`（同步完成），会直接调用 `continuation`，避免一次调度延迟，这是游戏逻辑中"立即完成的 await"的快路径优化。

---

## 六、Context 传播机制

ETTask 支持在整条 async 调用链上传递任意 context，无需在每个方法签名中显式传参：

```csharp
// 发起端：设置 context
ETTask contextTask = ETTask.GetContextAsync(cancellationToken);
await contextTask;

// 任意深度的被调用方：取回 context
ETCancellationToken token = await ETTask.GetContext<ETCancellationToken>();
if (token.IsCancel()) return;
```

内部通过 `TaskType.WithContext` 和 `TaskType.ContextTask` 两种特殊任务类型，在 awaiter 的 `OnCompleted` 中将 context 注入调用链，接收方通过匹配 `TaskType.ContextTask` 取回。

---

## 七、与原生 Task 的本质差异

| 维度 | 原生 Task | ETTask |
|------|----------|--------|
| 对象分配 | 每次 async 都 new Task | 对象池复用，稳定后零分配 |
| 执行线程 | 线程池（默认） | 主线程（无需 ConfigureAwait） |
| 异常传播 | 未 await 的异常可能丢失 | ETVoid 有全局异常处理 |
| 取消令牌 | CancellationToken 显式传参 | ETCancellationToken 隐式传播 |
| 完成通知 | TaskCompletionSource | 内置 SetResult/SetException |
| GC 压力 | 高 | 极低 |

---

## 八、常见使用模式

### 8.1 等待外部事件完成

```csharp
public class AsyncHandler
{
    private ETTask task = ETTask.Create(fromPool: true);

    // 外部完成时调用
    public void Complete() => task.SetResult();

    // 内部 await
    public ETTask WaitAsync() => task;
}

// 使用：
var handler = new AsyncHandler();
await handler.WaitAsync();  // 挂起，等待 Complete() 被调用
```

### 8.2 超时取消

```csharp
public static async ETTask TimeoutAsync(this ETTask task, int milliseconds)
{
    ETCancellationToken token = new ETCancellationToken();
    var timeoutTask = TimerComponent.Instance.WaitAsync(milliseconds, token);

    int result = await ETTask.WhenAny(task, timeoutTask);
    if (result == 1)
    {
        token.Cancel();
        throw new TimeoutException("Operation timed out.");
    }
    token.Cancel();  // 取消计时器
}
```

### 8.3 并行等待

```csharp
// 等待多个异步任务同时完成
await ETTask.WhenAll(
    LoadResourceAsync("prefab_a"),
    LoadResourceAsync("prefab_b"),
    LoadResourceAsync("prefab_c")
);
```

---

## 九、小结

ETTask 的核心设计哲学是"**为游戏主线程量身定制的零 GC 异步**"：

1. **对象池**：ETTask 和 StateMachineWrap 都从池中取用，稳定后 async/await 零堆分配
2. **同步完成快路径**：SetResult 在 OnCompleted 注册前完成时直接同步执行，无调度延迟
3. **异常安全**：ExceptionDispatchInfo 保留调用栈，ETVoid 有兜底处理
4. **Context 传播**：免去在每层方法中显式传递 CancellationToken 的繁琐

理解这些机制，是读懂框架中大量 `async ETTask` 代码的基础，也是调试异步 Bug 的核心工具。
