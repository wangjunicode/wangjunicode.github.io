---
title: ETVoid即发即忘协程模式与AsyncETVoidMethodBuilder轻量构建器深度解析
date: 2026-04-24
tags: [Unity, ETTask, 异步编程, 协程, CSharp]
categories: [游戏开发, 框架设计]
description: 深度解析ET框架中ETVoid类型与AsyncETVoidMethodBuilder的设计原理，阐明"即发即忘"协程模式的使用场景、内存优化策略与安全边界。
encryptedKey: henhaoji123
---

# ETVoid 即发即忘协程模式与 AsyncETVoidMethodBuilder 轻量构建器深度解析

## 前言

在 ET 框架的异步体系里，大多数讨论都集中在 `ETTask` 和 `ETTask<T>` 上——它们是可等待的、有返回值的异步任务。然而框架里还隐藏着一个低调却极其重要的类型：`ETVoid`。

`ETVoid` 代表一种**即发即忘（fire-and-forget）**协程模式。理解它的设计，不仅能帮你写出更高效的异步代码，更能让你深刻体会到 ET 框架在内存分配上的极致克制。

---

## 一、为什么需要 ETVoid

### 1.1 await 的代价

当你写下 `await someTask`，编译器会生成一个状态机类。这个状态机需要：

- 一个 `IAsyncStateMachine` 的实现类（在 Release 模式下为 struct，但包装后仍有装箱）
- 一个对应的 **MethodBuilder**，负责创建 task、连接 awaiter 回调
- 对 `ETTask` 的持有引用（潜在的堆分配）

对于**不需要返回值、也不需要被等待**的协程，使用完整的 `ETTask` 构建器是一种浪费。

### 1.2 ETVoid 的定位

```csharp
[AsyncMethodBuilder(typeof(AsyncETVoidMethodBuilder))]
internal struct ETVoid : ICriticalNotifyCompletion
{
    public void Coroutine() { }
    public bool IsCompleted => true;
    public void OnCompleted(Action continuation) { }
    public void UnsafeOnCompleted(Action continuation) { }
}
```

`ETVoid` 是一个**纯 struct**，没有任何堆分配。它的 `IsCompleted` 永远返回 `true`，这意味着它**不支持被 await**——编译器会直接跳过等待逻辑。

启动一个 `ETVoid` 协程的方式很特别：

```csharp
SomeAsyncVoidMethod().Coroutine();
```

`Coroutine()` 方法是一个空方法，什么都不做。调用它的唯一目的是**告诉编译器这个返回值已被"处理"**，消除"未使用返回值"的警告。

---

## 二、AsyncETVoidMethodBuilder 的实现剖析

```csharp
internal struct AsyncETVoidMethodBuilder
{
    private IStateMachineWrap iStateMachineWrap;

    public static AsyncETVoidMethodBuilder Create()
    {
        return new();
    }

    public ETVoid Task => default;
    // ...
}
```

### 2.1 无 TCS 设计

与 `ETAsyncTaskMethodBuilder` 不同，`AsyncETVoidMethodBuilder` **没有 `tcs` 字段**。  
这是最核心的差别：

| 构建器 | 持有 TCS | 目的 |
|--------|----------|------|
| `ETAsyncTaskMethodBuilder` | ✅ `ETTask tcs` | 支持被 await，传递结果 |
| `AsyncETVoidMethodBuilder` | ❌ 无 | 纯执行，不传递结果 |

没有 TCS 就意味着：
- 少一次 `ETTask` 的池分配
- 少一条回调链注册
- 整体内存压力更低

### 2.2 StateMachineWrap 的复用

虽然没有 TCS，但 `AsyncETVoidMethodBuilder` 同样使用了 `StateMachineWrap` 对象池：

```csharp
public void AwaitOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
    where TAwaiter : IETTask, INotifyCompletion
    where TStateMachine : IAsyncStateMachine
{
    this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
    awaiter.OnCompleted(this.iStateMachineWrap.MoveNext);
}
```

`StateMachineWrap<T>` 是一个泛型对象池，它把状态机的 `MoveNext` 调用封装成一个 `Action`，避免了每次 await 都 new 一个 lambda 造成的 GC 压力。

### 2.3 异常处理的差异

```csharp
public void SetException(Exception e)
{
    if (this.iStateMachineWrap != null)
    {
        this.iStateMachineWrap.Recycle();
        this.iStateMachineWrap = null;
    }
    ETTask.ExceptionHandler?.Invoke(e);
}
```

由于没有调用者可以 try-catch，`ETVoid` 协程的异常通过全局 `ETTask.ExceptionHandler` 处理，而不是像 `ETTask` 那样存储在 task 对象里等待 `GetResult` 时抛出。

---

## 三、ETVoid 的正确使用场景

### 3.1 适合使用 ETVoid 的场景

```csharp
// ✅ 场景1：事件响应，无需等待结果
private void OnButtonClick()
{
    LoadDataAsync().Coroutine();
}

private async ETVoid LoadDataAsync()
{
    await TimerComponent.Instance.WaitAsync(100);
    RefreshUI();
}
```

```csharp
// ✅ 场景2：启动后台任务
private void StartHeartbeat()
{
    HeartbeatLoop().Coroutine();
}

private async ETVoid HeartbeatLoop()
{
    while (!this.IsDisposed)
    {
        await TimerComponent.Instance.WaitAsync(5000);
        SendHeartbeat();
    }
}
```

### 3.2 不适合使用 ETVoid 的场景

```csharp
// ❌ 错误：需要等待结果时不能用 ETVoid
private async ETTask<bool> LoadScene()
{
    // 必须知道加载完成才能继续
    await SomeLoadTask();
    return true;
}

// ❌ 错误：需要取消/超时控制
// ETVoid 没有 ETCancellationToken 传递机制
```

---

## 四、ETVoid vs async void 的根本区别

C# 原生 `async void` 有一个著名的陷阱：**异常会导致程序崩溃**，因为异常被投递到 `SynchronizationContext` 而非调用者。

ET 框架的 `ETVoid` 解决了这个问题：

| 特性 | `async void` | `ETVoid` |
|------|-------------|---------|
| 异常处理 | 投递到 SynchronizationContext，可能崩溃 | 通过 `ETTask.ExceptionHandler` 统一处理 |
| 内存分配 | 标准 Task 分配 | 零 TCS 分配 + StateMachineWrap 池 |
| 可等待性 | 不可等待 | 不可等待 |
| 调用方式 | 直接调用 | `.Coroutine()` 显式启动 |
| 适用框架 | 通用 C# | ET 框架专属 |

---

## 五、AwaiterStatus 与 ETVoid 的关系

`ETVoid` 的 `IsCompleted` 永远为 `true`，这与 `AwaiterStatus.Succeeded` 状态对应：

```csharp
public enum AwaiterStatus : byte
{
    Pending = 0,    // 未完成
    Succeeded = 1,  // 成功完成
    Faulted = 2,    // 异常
}
```

`ETVoid` 没有 Pending 状态——它不需要等待，启动即"完成"（从调用者视角）。  
真正的异步工作在内部自行推进，调用者不感知其状态。

---

## 六、性能对比实验

以下是对 1000 次协程启动的内存分配对比（概念示意）：

```
ETTask（fromPool=true）：
  - ETTask 对象：从队列取出，0 新分配
  - StateMachineWrap：从队列取出，0 新分配
  - 总 GC：接近 0（稳态下）

ETVoid：
  - 无 TCS：0 分配
  - StateMachineWrap：从队列取出，0 新分配
  - 总 GC：比 ETTask 更少（少一次队列操作）

async void（对比基准）：
  - Task 对象：new 分配
  - StateMachine：装箱分配
  - 总 GC：每次约 64~128 字节
```

在高频事件（如每帧触发的 UI 动画、网络心跳）场景下，这个差距会累积成可观的 GC 压力。

---

## 七、设计哲学总结

ET 框架的 `ETVoid` 体现了一种清晰的设计哲学：

> **不需要的东西，就不要提供。**

不需要等待结果 → 不提供 TCS  
不需要返回值 → 返回 `ETVoid`（struct，零堆分配）  
不需要外部处理异常 → 通过全局 handler 托底  
不需要取消 → 不提供 CancellationToken 传递接口

这种"按需提供"的最小化设计，配合对象池，使得 ET 框架能在高频、低延迟的游戏战斗逻辑中稳定运行，而不被 GC 拖累。

---

## 结语

`ETVoid` 看似简单，却是 ET 框架异步体系完整性的重要一环。它填补了"我只是想启动一个协程，不关心结果"这一场景的最优解。

理解了 `ETVoid` 和 `AsyncETVoidMethodBuilder`，你就能在合适的场景做出正确的类型选择，在游戏开发中写出既安全又高效的异步代码。
