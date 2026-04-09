---
title: 游戏框架并发协程工具集ETTaskHelper与即完成任务结构设计解析
published: 2026-04-09
description: 深度解析 ETTaskHelper 工具类的 WaitAll、WaitAny、GetContextAsync 设计，以及 ETTaskCompleted、ETVoid、AsyncETTaskCompletedMethodBuilder 三个即完成结构体的使用场景与协程体系分工，完整覆盖 ETTask 系列的全部辅助设施。
tags: [Unity, ETTask, 异步编程, 协程, 框架底层, ECS]
category: 框架底层
encryptedKey:henhaoji123
---

## 前言

上一篇文章深入剖析了 `ETTask` 与 `ETTask<T>` 的对象池和状态机原理。本篇继续聚焦 ETTask 体系的辅助设施层，包含：

- `ETTaskHelper`：并发协程工具（`WaitAll`、`WaitAny`、`GetContextAsync`）
- `ETTaskCompleted`：永远已完成的同步 Awaiter
- `ETVoid`：即发即忘协程的返回类型
- `AsyncETTaskCompletedMethodBuilder`：`ETTaskCompleted` 专属的 MethodBuilder

这四个文件共同构成了 ETTask 体系的"周边设施"，理解它们能帮助开发者写出更简洁、更高效的异步代码。

---

## 一、ETTaskHelper 工具类

### 1.1 GetContextAsync：从协程链中取出上下文

```csharp
public static async ETTask<T> GetContextAsync<T>() where T : class
{
    ETTask<object> tcs = ETTask<object>.Create(true);
    tcs.TaskType = TaskType.ContextTask;
    object ret = await tcs;
    if (ret == null) return null;
    return (T)ret;
}
```

这是整个 Context 传播机制的消费端。

**工作原理分步解析：**

① 创建一个 `ETTask<object>`，并将其 `TaskType` 设为 `ContextTask`

② `await tcs` 挂起当前状态机，将 tcs 存入调用链

③ 当外层调用 `.WithContext(token)` 时，`SetContext` 算法沿链路向下遍历，直到遇到 `ContextTask` 类型的节点

④ 找到 tcs 后，调用 `tcs.SetResult(context)`，将上下文对象作为返回值传入

⑤ `await tcs` 恢复执行，`ret` 就是上下文对象

⑥ 强制转型为泛型 `T` 返回

**使用场景对比：**

```csharp
// 传统做法：每层函数都要传递参数
async ETTask Level1Async(ETCancellationToken token) => await Level2Async(token);
async ETTask Level2Async(ETCancellationToken token) => await Level3Async(token);
async ETTask Level3Async(ETCancellationToken token)
{
    if (token.IsCancel()) return;
    // ...
}

// ET Context 做法：只在发起层注入，消费层直接取
async ETTask Level1Async(ETCancellationToken token)
{
    await Level2Async().WithContext(token);
}
async ETTask Level2Async() => await Level3Async(); // 透明传递
async ETTask Level3Async()
{
    var token = await ETTaskHelper.GetContextAsync<ETCancellationToken>();
    if (token.IsCancel()) return;
    // ...
}
```

ET Context 方案在层级深的调用链中大幅减少样板代码，代价是调用链多一次 `ETTask<object>` 创建。

---

### 1.2 CoroutineBlocker：内部并发控制器

`WaitAll` 和 `WaitAny` 都依赖一个私有内部类 `CoroutineBlocker`：

```csharp
private class CoroutineBlocker
{
    private int count;         // 还剩几个子协程未完成
    private ETTask tcs;        // 等待所有子协程完成的 Task

    public CoroutineBlocker(int count)
    {
        this.count = count;
    }

    public async ETTask RunSubCoroutineAsync(ETTask task)
    {
        try
        {
            await task;
        }
        finally
        {
            --this.count;
            if (this.count <= 0 && this.tcs != null)
            {
                ETTask t = this.tcs;
                this.tcs = null;   // 防重入：先置空
                t.SetResult();     // 通知等待者
            }
        }
    }

    public async ETTask WaitAsync()
    {
        if (this.count <= 0) return;  // 已经全部完成，立即返回
        this.tcs = ETTask.Create(true);
        await tcs;
    }
}
```

**关键设计点：**

- `count` 是普通 int，不需要 `Interlocked`，因为所有操作都在同一帧（主线程）驱动
- `finally` 块确保即使子协程异常，计数也会减少（防死锁）
- `this.tcs = null` 在 `SetResult()` 之前执行，防止 WaitAsync 被重复唤醒

---

### 1.3 WaitAny：任意一个完成即继续

```csharp
public static async ETTask WaitAny(List<ETTask> tasks)
{
    if (tasks.Count == 0) return;

    CoroutineBlocker coroutineBlocker = new CoroutineBlocker(1); // count=1，第一个完成就触发

    foreach (ETTask task in tasks)
    {
        coroutineBlocker.RunSubCoroutineAsync(task).Coroutine();
    }

    await coroutineBlocker.WaitAsync();
}
```

`WaitAny` 创建 `CoroutineBlocker(1)`，即只要任何一个子协程完成（`count` 从正数降到 ≤ 0），就唤醒等待者。

**流程示意：**

```
tasks = [A, B, C]
CoroutineBlocker(count=1)

并发启动：RunSubCoroutineAsync(A).Coroutine()
         RunSubCoroutineAsync(B).Coroutine()
         RunSubCoroutineAsync(C).Coroutine()

await WaitAsync() → 挂起

假设 B 先完成：
  B 的 finally → --count (1→0) → tcs.SetResult()
  → WaitAsync() 恢复
  → WaitAny 返回

A、C 继续运行（不会被取消！这是 WaitAny 与 CancellationToken 的区别）
```

> ⚠️ 注意：`WaitAny` 并**不会取消**其他仍在运行的协程。如果需要取消，需要外层结合 `ETCancellationToken` 使用。

---

### 1.4 WaitAll：全部完成才继续

```csharp
public static async ETTask WaitAll(ETTask[] tasks)
{
    if (tasks.Length == 0) return;

    CoroutineBlocker coroutineBlocker = new CoroutineBlocker(tasks.Length); // count=任务数量

    foreach (ETTask task in tasks)
    {
        coroutineBlocker.RunSubCoroutineAsync(task).Coroutine();
    }

    await coroutineBlocker.WaitAsync();
}
```

`WaitAll` 创建 `CoroutineBlocker(tasks.Length)`，所有任务都完成后 `count` 降到 0，等待者才被唤醒。

**与 Task.WhenAll 对比：**

| 特性 | `Task.WhenAll` | `ETTaskHelper.WaitAll` |
|------|----------------|------------------------|
| 异常处理 | 收集所有异常，抛 AggregateException | 最先完成的异常会抛出（通过 finally 的 SetResult，不传递异常） |
| 返回值 | `T[]` 结果数组 | void（不收集结果） |
| 内存分配 | Task 框架内部分配 | CoroutineBlocker + ETTask（可池化）|
| 取消支持 | CancellationToken | 需外部 ETCancellationToken |

> ⚠️ `ETTaskHelper.WaitAll` 不聚合异常：如果某个子任务抛异常，`finally` 仍会 `--count`，但 `RunSubCoroutineAsync` 自身不会向外传播异常（异常会通过 `.Coroutine()` 的 fire-and-forget 路径交给 `ETTask.ExceptionHandler` 处理）。

---

### 1.5 ETCancellationToken 扩展方法

```csharp
public static bool IsCancel(this ETCancellationToken self)
{
    if (self == null) return false;
    return self.IsDispose();
}
```

这是对 `ETCancellationToken` 的空安全包装。游戏代码中经常出现 `token` 为 `null` 的情况（调用方没有取消需求），通过这个扩展方法统一判断，避免到处写 `token != null && token.IsDispose()`。

---

## 二、ETTaskCompleted：永远已完成的 Awaiter

```csharp
[AsyncMethodBuilder(typeof(AsyncETTaskCompletedMethodBuilder))]
public struct ETTaskCompleted : ICriticalNotifyCompletion
{
    public ETTaskCompleted GetAwaiter() => this;
    public bool IsCompleted => true;  // 永远是 true！
    public void GetResult() { }       // 什么都不做
    public void OnCompleted(Action continuation) { }
    public void UnsafeOnCompleted(Action continuation) { }
}
```

### 设计目的

`ETTaskCompleted` 是一个**值类型**（struct），`IsCompleted` 永远返回 `true`，`GetResult` 是空方法。

当编译器看到 `await someETTaskCompleted` 时，会先检查 `IsCompleted`，发现是 `true`，就**直接内联调用 `GetResult()`** 而不挂起状态机。这意味着 `await ETTaskCompleted` 实际上是零开销的同步操作。

### 适用场景

```csharp
// 场景1：实现一个同步完成的"等待"（占位用）
public async ETTaskCompleted LoadSync()
{
    // 所有工作都是同步的，但接口要求返回 ETTask 系列
    DoSomeWork();
    return default;  // 返回默认的 ETTaskCompleted
}

// 场景2：某些框架基础设施需要"可 await 但立即返回"的对象
await new ETTaskCompleted();  // 不会挂起，直接过
```

### 与 ETTask.CompletedTask 的区别

| | `ETTask.CompletedTask` | `ETTaskCompleted` |
|---|---|---|
| 类型 | 引用类型（class） | 值类型（struct）|
| 分配 | 单例（一次分配） | 栈上（零堆分配）|
| 适用返回类型 | `async ETTask` 方法 | `async ETTaskCompleted` 方法 |

---

## 三、ETVoid：即发即忘协程的返回类型

```csharp
[AsyncMethodBuilder(typeof(AsyncETVoidMethodBuilder))]
internal struct ETVoid : ICriticalNotifyCompletion
{
    public void Coroutine() { }        // 接收者调用此方法"启动"协程（实际已启动）
    public bool IsCompleted => true;
    public void OnCompleted(Action continuation) { }
    public void UnsafeOnCompleted(Action continuation) { }
}
```

### 设计目的

`ETVoid` 是 ET 框架中**即发即忘协程**（fire-and-forget）的返回类型，类似于 `async void`，但更加受控。

`async void` 的问题：
1. 异常会直接抛到 `SynchronizationContext`，难以捕获
2. 无法被 `await`，调用方完全不知道任务状态

`ETVoid` 的解决方案：
1. 异常通过 `AsyncETVoidMethodBuilder.SetException` 转发到 `ETTask.ExceptionHandler`，可以统一处理
2. 通过 `.Coroutine()` 方法"标记"调用意图，代码可读性更好

### 使用模式

```csharp
// 内部协程包装
private async ETVoid InnerCoroutine()
{
    await this;  // this 是 ETTask
}

// 外部调用
public void Coroutine()
{
    this.SetContext(null);
    InnerCoroutine().Coroutine();  // 返回 ETVoid，调用 .Coroutine() 表示"我知道这是 fire-and-forget"
}
```

`.Coroutine()` 方法本身是空实现，调用它的意义纯粹是**语义标记**：告诉读代码的人"这里我主动选择了不等待这个协程"。

### 对比 async void

```csharp
// ❌ async void：异常会崩溃进程（Unity 环境下可能更糟）
async void BadFireAndForget()
{
    await Task.Delay(1000);
    throw new Exception("糟了");  // 难以捕获
}

// ✅ ETVoid：异常由 ETTask.ExceptionHandler 统一处理
async ETVoid GoodFireAndForget()
{
    await TimerHelper.WaitAsync(1000);
    throw new Exception("被 ExceptionHandler 捕获并记录");
}
GoodFireAndForget().Coroutine();
```

---

## 四、AsyncETTaskCompletedMethodBuilder：同步方法的构建器

```csharp
public struct AsyncETTaskCompletedMethodBuilder
{
    public static AsyncETTaskCompletedMethodBuilder Create() => new();
    
    public ETTaskCompleted Task => default;  // 值类型，直接 default 就行
    
    public void SetException(Exception e)
    {
        ETTask.ExceptionHandler.Invoke(e);   // 统一异常入口
    }
    
    public void SetResult() { }  // 什么都不做，因为 ETTaskCompleted 永远完成
    
    public void AwaitOnCompleted<TAwaiter, TStateMachine>(
        ref TAwaiter awaiter, ref TStateMachine stateMachine)
        where TAwaiter : INotifyCompletion
        where TStateMachine : IAsyncStateMachine
    {
        awaiter.OnCompleted(stateMachine.MoveNext);
    }
    
    public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
        ref TAwaiter awaiter, ref TStateMachine stateMachine)
        where TAwaiter : ICriticalNotifyCompletion
        where TStateMachine : IAsyncStateMachine
    {
        awaiter.UnsafeOnCompleted(stateMachine.MoveNext);
    }
    
    public void Start<TStateMachine>(ref TStateMachine stateMachine)
        where TStateMachine : IAsyncStateMachine
    {
        stateMachine.MoveNext();
    }
    
    public void SetStateMachine(IAsyncStateMachine stateMachine) { }
}
```

### 与其他 MethodBuilder 对比

| 方法 | `AsyncETTaskCompletedMethodBuilder` | `ETAsyncTaskMethodBuilder` |
|------|-------------------------------------|----------------------------|
| `Task` 属性 | `ETTaskCompleted`（struct，零分配）| `ETTask`（class，堆分配）|
| `SetResult` | 空操作 | 调用 `tcs.SetResult()` |
| `SetException` | 转发到 `ExceptionHandler` | 调用 `tcs.SetException()` |
| 适用返回类型 | `async ETTaskCompleted` | `async ETTask` |
| 使用场景 | 同步包装，测试 stub | 正常异步方法 |

`AsyncETTaskCompletedMethodBuilder.SetException` 的处理值得注意：它不像普通 Builder 那样存储异常等待 `GetResult` 取出，而是**立即调用 `ETTask.ExceptionHandler`**。这是因为 `ETTaskCompleted` 的 `GetResult` 是空方法，无法传递异常，所以只能选择同步回调。

---

## 五、四个类型的协作关系总览

```
ETTask 体系层次结构
│
├── [核心任务类型]
│   ├── ETTask          → async ETTask 方法的返回类型，最常用
│   └── ETTask<T>       → async ETTask<T> 方法的返回类型，带返回值
│
├── [辅助任务类型]
│   ├── ETTaskCompleted → 永远已完成的同步 Awaiter（struct，零分配）
│   └── ETVoid          → fire-and-forget 协程（替代 async void）
│
├── [MethodBuilder]
│   ├── ETAsyncTaskMethodBuilder    → 驱动 async ETTask 状态机
│   ├── ETAsyncTaskMethodBuilder<T> → 驱动 async ETTask<T> 状态机
│   ├── AsyncETTaskCompletedMethodBuilder → 驱动 async ETTaskCompleted
│   └── AsyncETVoidMethodBuilder    → 驱动 async ETVoid
│
└── [工具类]
    └── ETTaskHelper
        ├── GetContextAsync<T>()    → 从链路取上下文
        ├── WaitAll(tasks)          → 等所有完成
        ├── WaitAny(tasks)          → 等任意一个完成
        └── IsCancel(token)         → 空安全的取消检查
```

---

## 六、实际游戏代码中的常见模式

### 模式一：带超时的操作

```csharp
async ETTask WaitWithTimeoutAsync(ETTask task, long timeoutMs, ETCancellationToken token = null)
{
    ETTask timeoutTask = TimerHelper.WaitAsync(timeoutMs, token);
    await ETTaskHelper.WaitAny(new[] { task, timeoutTask });
    // 到这里：要么 task 完成，要么超时
}
```

### 模式二：并行加载多个资源

```csharp
async ETTask LoadMultipleAssetsAsync(string[] paths)
{
    ETTask[] loadTasks = new ETTask[paths.Length];
    for (int i = 0; i < paths.Length; i++)
    {
        loadTasks[i] = LoadAssetAsync(paths[i]);
    }
    await ETTaskHelper.WaitAll(loadTasks);
    // 所有资源加载完成
}
```

### 模式三：上下文透传链

```csharp
// 战斗系统：Entity 生命周期绑定的协程取消
async ETTask RunBattleLogicAsync()
{
    ETCancellationToken token = this.GetCancellationToken();
    await DoAttackSequenceAsync().WithContext(token); // 注入上下文
}

async ETTask DoAttackSequenceAsync()
{
    await DoPreAttackAsync();
    await DoMainAttackAsync();
    await DoPostAttackAsync();
}

async ETTask DoMainAttackAsync()
{
    // 不需要参数，直接从链路取
    var token = await ETTaskHelper.GetContextAsync<ETCancellationToken>();
    if (token.IsCancel()) return;
    
    await PlayAnimationAsync("attack");
    await SpawnProjectileAsync();
}
```

---

## 总结

`ETTaskHelper`、`ETTaskCompleted`、`ETVoid`、`AsyncETTaskCompletedMethodBuilder` 四个类型共同构成了 ETTask 体系的完整工具层：

1. **`ETTaskHelper.WaitAll/WaitAny`** 通过 `CoroutineBlocker` 的计数器机制，用最小的代码实现了并发协程等待
2. **`ETTaskHelper.GetContextAsync`** 是 Context 传播机制的消费端，让深层协程无感知地获取上下文
3. **`ETTaskCompleted`** 作为 struct 实现了零堆分配的即完成 Awaiter，适合同步场景
4. **`ETVoid`** 用 `.Coroutine()` 语义标记替代危险的 `async void`，配合 `ExceptionHandler` 实现可控的即发即忘
5. **`AsyncETTaskCompletedMethodBuilder`** 直接将异常转发到全局 Handler，契合 ETTaskCompleted 的同步语义

理解这些辅助设施，能帮助你写出更惯用、更安全的 ET 框架异步代码，避免常见的协程泄漏和异常吞没问题。
