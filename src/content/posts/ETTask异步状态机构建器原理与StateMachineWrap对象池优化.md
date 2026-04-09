---
title: ETTask异步状态机构建器原理与StateMachineWrap对象池优化
published: 2026-04-09
description: 深入解析ET框架中ETAsyncTaskMethodBuilder和StateMachineWrap的设计原理，揭示async/await背后的状态机机制、对象池复用策略、Context链传递以及ETVoid的即发即忘模式。
tags: [Unity, ET框架, ETTask, 异步, AsyncMethodBuilder, 状态机, 对象池]
category: 框架底层
draft: false
encryptedKey:henhaoji123
---

# ETTask 异步状态机构建器原理与 StateMachineWrap 对象池优化

C# 的 `async/await` 背后是一套复杂的状态机转换机制，而 ET 框架通过自定义 `AsyncMethodBuilder` 将这套机制与 ETTask 深度融合，并在其上叠加了对象池优化和 Context 传递能力。本文将结合源码，带你彻底理解 `StateMachineWrap`、`ETAsyncTaskMethodBuilder` 以及 `AsyncETVoidMethodBuilder` 的设计精妙之处。

---

## 一、async/await 的底层机制简介

当你写下：

```csharp
public async ETTask DoSomethingAsync()
{
    await TimerComponent.Instance.WaitAsync(1000);
    Debug.Log("1秒后执行");
}
```

C# 编译器并不是真的"暂停"了代码，而是将整个方法**改写成一个状态机类**（`IAsyncStateMachine`），并生成一个对应的 **AsyncMethodBuilder**。

状态机的工作流程：
1. 调用 `builder.Start()` → 状态机首次运行到第一个 `await`
2. 遇到 `await` → 将"恢复继续执行"的委托注册到被等待对象
3. 被等待对象完成 → 回调委托 → 状态机继续 `MoveNext()`
4. 状态机执行到末尾 → 调用 `builder.SetResult()`

自定义 `AsyncMethodBuilder` 允许框架控制这整个过程——包括如何分配状态机、如何存储等待回调，以及如何处理完成后的结果。

---

## 二、StateMachineWrap：状态机的对象池包装器

### 2.1 为什么需要包装状态机？

原始的状态机（`IAsyncStateMachine`）是一个结构体（struct），每次 `await` 都可能产生装箱（boxing）开销。更关键的是，我们需要将"继续执行"封装成一个 `Action` 委托，而直接对结构体方法创建委托会产生大量堆分配。

`StateMachineWrap<T>` 解决了这个问题：

```csharp
public class StateMachineWrap<T>: IStateMachineWrap where T: IAsyncStateMachine
{
    [StaticField]
    private static readonly Queue<StateMachineWrap<T>> queue = new();

    private readonly Action moveNext;
    public Action MoveNext => this.moveNext;

    private T StateMachine;

    private StateMachineWrap()
    {
        this.moveNext = this.Run;  // 一次性创建 Action，复用对象时不再分配
    }

    private void Run()
    {
        this.StateMachine.MoveNext();
    }
}
```

关键设计：
- **`moveNext` 委托在构造时创建一次**，对象复用时不产生额外的委托分配
- **对象池（Queue）**：用 `Queue<StateMachineWrap<T>>` 缓存可复用实例，`[StaticField]` 注解告诉 ET 的 Analyzer 这是静态字段，需要注意跨场景状态清理

### 2.2 Fetch：从池中获取或新建

```csharp
public static StateMachineWrap<T> Fetch(ref T stateMachine)
{
    StateMachineWrap<T> stateMachineWrap;
    lock (queue)
    {
        if (!queue.TryDequeue(out stateMachineWrap))
        {
            stateMachineWrap = new StateMachineWrap<T>();
        }
    }
    stateMachineWrap.StateMachine = stateMachine;
    return stateMachineWrap;
}
```

注意 `lock (queue)`——虽然游戏主逻辑通常单线程，但 ETTask 的完成可能发生在网络线程或 I/O 线程，对象池的并发访问需要保护。

### 2.3 Recycle：归还到池中

```csharp
public void Recycle()
{
    lock (queue)
    {
        if (queue.Count > 100)
        {
            return;  // 池已满，直接丢弃（允许 GC 回收）
        }
        this.StateMachine = default;  // 清空状态机引用，防止内存泄漏
        queue.Enqueue(this);
    }
}
```

上限 100 个是一个经验值。对象池不能无限增长——当队列超过阈值，多余的对象不再归还，交给 GC 处理，避免内存持续增长。

---

## 三、ETAsyncTaskMethodBuilder：ETTask 的构建器

### 3.1 构建器的 8 个契约方法

`AsyncMethodBuilder` 必须实现以下接口（按规范命名）：

| 方法 | 职责 |
|------|------|
| `Create()` | 静态工厂，创建 builder + 关联的 ETTask |
| `Task` 属性 | 返回关联的异步任务（给调用方 await） |
| `SetException(e)` | 异步方法抛异常时调用 |
| `SetResult()` | 异步方法正常完成时调用 |
| `AwaitOnCompleted()` | 等待实现了 `INotifyCompletion` 的对象 |
| `AwaitUnsafeOnCompleted()` | 等待实现了 `ICriticalNotifyCompletion` 的对象（不走 ExecutionContext 传递） |
| `Start()` | 启动状态机 |
| `SetStateMachine()` | 框架调用，ET 中空实现 |

### 3.2 Create：任务创建

```csharp
public static ETAsyncTaskMethodBuilder Create()
{
    ETAsyncTaskMethodBuilder builder = new() { tcs = ETTask.Create(true) };
    return builder;
}
```

`ETTask.Create(true)` 中的 `true` 表示从**对象池**创建 ETTask。这里存在一个重要约定（源码注释有特别警告）：

> **开启池后，await 之后不能再操作 ETTask，否则可能操作到再次从池中分配出来的 ETTask，产生灾难性的后果。**

### 3.3 AwaitOnCompleted vs AwaitUnsafeOnCompleted

```csharp
// 安全版本：用于实现了 INotifyCompletion 的 awaiter
public void AwaitOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
    where TAwaiter : class, IETTask, INotifyCompletion
    where TStateMachine : IAsyncStateMachine
{
    this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
    awaiter.OnCompleted(this.iStateMachineWrap.MoveNext);
}
```

```csharp
// 非安全版本：跳过 ExecutionContext，性能更好
public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
    where TAwaiter : ICriticalNotifyCompletion
    where TStateMachine : IAsyncStateMachine
{
    this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
    awaiter.UnsafeOnCompleted(this.iStateMachineWrap.MoveNext);

    // Context 传递逻辑（见下文）
    if (awaiter is not IETTask task) { return; }
    if (this.tcs.TaskType == TaskType.WithContext)
    {
        task.SetContext(this.tcs.Context);
        return;
    }
    this.tcs.Context = task;
}
```

`??=` 操作符确保 `iStateMachineWrap` 只创建一次——一个异步方法可能有多个 `await`，但只需要一个 wrap 对象。

### 3.4 Context 链传递机制

这是 ET 框架 ETTask 的高级特性，用于传递 `ETCancellationToken` 或其他上下文对象：

```csharp
if (this.tcs.TaskType == TaskType.WithContext)
{
    task.SetContext(this.tcs.Context);
    return;
}
this.tcs.Context = task;
```

**TaskType** 有三种：
- `Common`：普通任务，无上下文
- `WithContext`：已经有上下文（如取消令牌），需要传递给下一层
- `ContextTask`：专门用来携带上下文的任务容器

通过这个机制，外层的取消令牌可以**自动透传**到最深层的 `await`，而不需要每层手动传参——这是 ET 框架一个非常优雅的设计。

### 3.5 SetResult 与 SetException 中的清理

```csharp
public void SetResult()
{
    if (this.iStateMachineWrap != null)
    {
        this.iStateMachineWrap.Recycle(); // 归还状态机包装器到对象池
        this.iStateMachineWrap = null;
    }
    this.tcs.SetResult();
}
```

无论正常完成还是异常，都会先将 `StateMachineWrap` 归还到对象池。这形成了一个完整的资源管理闭环：
- `Fetch` 时从池中取
- `SetResult/SetException` 时归还

---

## 四、AsyncETVoidMethodBuilder：即发即忘的 ETVoid

ET 框架除了 `ETTask`，还有一个特殊类型 `ETVoid`，专门用于"不需要 await 等待结果"的异步操作：

```csharp
[DebuggerHidden]
public void Coroutine()
{
    // 调用即发射，不返回任何可等待对象
}
```

对应的 Builder：

```csharp
internal struct AsyncETVoidMethodBuilder
{
    // Task 属性返回 default（即 ETVoid 的默认值）
    public ETVoid Task => default;

    public void SetException(Exception e)
    {
        if (this.iStateMachineWrap != null)
        {
            this.iStateMachineWrap.Recycle();
            this.iStateMachineWrap = null;
        }
        ETTask.ExceptionHandler?.Invoke(e);  // 只上报，不传播
    }
}
```

**ETVoid 与 ETTask 的关键区别：**

| 特性 | ETTask | ETVoid（async ETVoid） |
|------|--------|------------------------|
| 可被 await | ✅ | ❌ |
| 异常处理 | 通过 try/catch 或 `.NoContext()` | 通过全局 ExceptionHandler |
| 用途 | 需要等待结果 | 即发即忘的后台逻辑 |
| 对象池 | 有（ETTask.Create(true)） | 无（ETVoid 是 struct，零分配） |

典型用法：

```csharp
// 启动一个不需要等待的 AI 循环
this.RunAILoopAsync().Coroutine(); // ETVoid 版本，不等待

// 启动一个需要等待完成的初始化流程
await this.InitializeAsync(); // ETTask 版本，等待完成
```

---

## 五、完整异步执行链路图

以一个简单的 `await TimerComponent.Instance.WaitAsync(1000)` 为例：

```
async ETTask DoWork()
    │
    ├─ 编译器生成 DoWorkStateMachine : IAsyncStateMachine
    │
    ├─ ETAsyncTaskMethodBuilder.Create()
    │    └─ 创建 ETTask（从对象池）
    │
    ├─ builder.Start(ref stateMachine)
    │    └─ stateMachine.MoveNext() → 执行到第一个 await
    │
    ├─ 遇到 await TimerTask
    │    └─ builder.AwaitUnsafeOnCompleted(ref timerAwaiter, ref stateMachine)
    │         ├─ StateMachineWrap.Fetch(ref stateMachine) → 从池中取 Wrap
    │         ├─ timerAwaiter.UnsafeOnCompleted(wrap.MoveNext)
    │         └─ Context 传递（如果有 CancellationToken）
    │
    ├─ [1000ms 后，定时器触发]
    │    └─ wrap.MoveNext() → stateMachine.MoveNext() → 继续执行
    │
    └─ 方法执行完毕
         └─ builder.SetResult()
              ├─ wrap.Recycle() → 归还对象池
              └─ tcs.SetResult() → 通知等待方
```

---

## 六、性能影响分析

通过对象池优化，ETTask 的主要内存分配被大幅降低：

| 场景 | 无优化 | 有 StateMachineWrap 对象池 |
|------|--------|---------------------------|
| 每次 await 创建 Action | 每次 ~48 bytes | 第一次后复用，0 bytes |
| 状态机 wrap 对象 | 每次新建 | 复用，GC 压力降低 90%+ |
| ETTask 自身 | 每次新建 | fromPool=true 时复用 |

在帧率敏感的游戏场景中（如战斗中每帧触发大量异步技能逻辑），这种优化直接体现为 GC 频率的降低，减少帧率卡顿。

---

## 七、小结

`StateMachineWrap` 和 `ETAsyncTaskMethodBuilder` 共同构成了 ET 框架异步体系的"引擎核心"：

1. **StateMachineWrap**：将状态机的 `MoveNext` 委托封装为可复用对象，配合对象池大幅减少异步代码的 GC 压力
2. **ETAsyncTaskMethodBuilder**：实现了 C# AsyncMethodBuilder 协议，接管了 async 关键字背后的完整生命周期
3. **Context 传递**：通过 `IETTask` 接口和 `TaskType` 枚举，实现了 `CancellationToken` 的自动透传，无需每层手动传参
4. **AsyncETVoidMethodBuilder**：为"即发即忘"场景提供零等待、零返回值的异步方法支持

理解这套机制，不仅帮助你写出更安全的异步代码，也让你在分析性能问题时能精确定位 GC 热点——绝大多数游戏异步性能问题，都能追溯到 Builder 层的不当使用。
