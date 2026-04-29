---
title: ETTask异步状态机构建器AsyncETTaskMethodBuilder双泛型设计与上下文传播机制深度解析
date: 2026-04-29
tags: [Unity, ETTask, 异步编程, 状态机, C#]
categories: [Unity游戏开发, 框架原理]
description: 深入剖析ETTask框架中AsyncETTaskMethodBuilder与AsyncETTaskMethodBuilder<T>的完整实现，解析C#异步状态机的七步协议、StateMachineWrap对象池复用、IETTask上下文传播链路，以及TaskType.WithContext双模式设计。
encryptedKey: henhaoji123
---

# ETTask异步状态机构建器AsyncETTaskMethodBuilder双泛型设计与上下文传播机制深度解析

在 Unity 游戏开发中，ETTask 是一套零 GC 的自定义异步框架，它能够完全替代 `System.Threading.Tasks.Task`，同时规避 Unity 协程的诸多限制。其核心秘密藏在两个鲜为人知的结构体中：**`ETAsyncTaskMethodBuilder`** 和 **`ETAsyncTaskMethodBuilder<T>`**。本文将从 C# 编译器协议出发，逐行解析这套构建器的设计精髓。

---

## 一、C# 异步状态机的七步协议

当我们写下 `async ETTask SomeMethod()` 时，C# 编译器会把这个方法拆解为一个状态机，并寻找对应的"构建器"来驱动它。这套协议共七步，缺一不可：

| 步骤 | 方法签名 | 作用 |
|------|---------|------|
| 1 | `static TBuilder Create()` | 构建器出厂方法 |
| 2 | `TTask Task { get; }` | 对外暴露 awaitable 的任务对象 |
| 3 | `void SetException(Exception)` | 记录异常 |
| 4 | `void SetResult()` | 标记任务完成 |
| 5 | `void AwaitOnCompleted<TAwaiter, TSM>` | 注册 awaiter 回调 |
| 6 | `void AwaitUnsafeOnCompleted<TAwaiter, TSM>` | 注册非安全 awaiter 回调 |
| 7 | `void Start<TSM>(ref TSM)` | 启动状态机 |

ETTask 框架完整实现了以上七步。下面逐一解析关键细节。

---

## 二、出厂与任务属性：对象池起点

```csharp
public static ETAsyncTaskMethodBuilder Create()
{
    ETAsyncTaskMethodBuilder builder = new() { tcs = ETTask.Create(true) };
    return builder;
}

public ETTask Task => this.tcs;
```

这里有两个细节值得关注：

**1. `ETTask.Create(true)` 的 `true` 参数**

`true` 表示该 ETTask 从对象池获取。ETTask 是可复用的值类型包装器，通过对象池彻底消除 GC。这意味着每次 `async ETTask` 方法被调用时，不会有任何托管堆分配。

**2. 结构体 Builder 的直接赋值**

Builder 本身是 `struct`，由编译器在栈上分配，不产生 GC。Builder 持有 `tcs`（Task Completion Source）和 `iStateMachineWrap` 两个字段，均通过对象池管理。

---

## 三、SetResult 与 SetException：完成与回收双保险

```csharp
public void SetResult()
{
    if (this.iStateMachineWrap != null)
    {
        this.iStateMachineWrap.Recycle();
        this.iStateMachineWrap = null;
    }
    this.tcs.SetResult();
}
```

注意 **先回收 StateMachineWrap，再设置结果** 的顺序。这是有意为之：

- `iStateMachineWrap.Recycle()` 会将状态机封装对象归还到对象池
- 之后 `tcs.SetResult()` 会触发所有 awaiter 的回调（即唤醒等待该任务的协程）
- 如果顺序反了，被唤醒的协程可能重入该状态机封装，造成数据竞争

`SetException` 也遵循同样模式，确保异常情况下状态机封装也能正确归池，不发生内存泄漏。

---

## 四、StateMachineWrap：状态机封装的延迟初始化

```csharp
public void AwaitOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
    where TAwaiter : class, IETTask, INotifyCompletion
    where TStateMachine : IAsyncStateMachine
{
    this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
    awaiter.OnCompleted(this.iStateMachineWrap.MoveNext);
}
```

`StateMachineWrap<TStateMachine>` 是整套对象池设计的精华所在：

1. **延迟初始化**（`??=`）：只有遇到第一个 await 时才创建，对于无 await 的 async 方法（立即返回），完全不会分配该对象
2. **泛型静态池**：`StateMachineWrap<TStateMachine>` 按类型分池，每种状态机类型有独立的对象池，避免装箱
3. **`Fetch(ref stateMachine)` 值类型复制捕获**：将栈上的状态机结构体复制到堆上的 Wrap 对象，这是 async 方法能跨帧挂起的关键

---

## 五、AwaitUnsafeOnCompleted：上下文传播的核心

```csharp
public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
    where TAwaiter : ICriticalNotifyCompletion
    where TStateMachine : IAsyncStateMachine
{
    this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
    awaiter.UnsafeOnCompleted(this.iStateMachineWrap.MoveNext);

    if (awaiter is not IETTask task)
    {
        return;
    }

    if (this.tcs.TaskType == TaskType.WithContext)
    {
        task.SetContext(this.tcs.Context);
        return;
    }
    
    this.tcs.Context = task;
}
```

这是整个 Builder 最复杂也最精妙的部分，它实现了 **双向上下文传播**：

### 5.1 非 ETTask 的 awaiter

如果 `awaiter` 不实现 `IETTask`（比如等待一个标准 `Task` 或 Unity 的 `AsyncOperation`），则直接跳过上下文处理。这保证了与标准 C# awaitable 的兼容性。

### 5.2 `TaskType.WithContext` 模式：父传子

```csharp
if (this.tcs.TaskType == TaskType.WithContext)
{
    task.SetContext(this.tcs.Context);
    return;
}
```

当外层任务已经携带了上下文（Context）时，把这个 Context 向下传播给被 await 的内层 ETTask。这形成了 **上下文继承链**：

```
OuterTask(Context=X) await InnerTask
→ InnerTask.Context = X
→ InnerInnerTask.Context = X  // 递归传播
```

### 5.3 普通模式：子反向绑定

```csharp
this.tcs.Context = task;
```

当外层任务没有指定上下文时，把被 await 的 `task` 作为外层任务的 Context。这意味着外层任务"知道"自己当前在等待哪个子任务，支持取消传播等高级功能。

---

## 六、带返回值的泛型版本 `ETAsyncTaskMethodBuilder<T>`

带返回值的版本与无返回值版本结构几乎相同，只有两处关键差异：

```csharp
// 差异1：SetResult 携带返回值
public void SetResult(T ret)
{
    // ...
    this.tcs.SetResult(ret);
}

// 差异2：AwaitOnCompleted 约束放宽
public void AwaitOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
    where TAwaiter : INotifyCompletion  // 无 class 约束，无 IETTask 约束
    where TStateMachine : IAsyncStateMachine
```

**约束放宽的原因**：有返回值的异步方法在业务场景中更常见与标准 awaitable 混用（如等待 `Task<T>`、`UniTask<T>` 等），因此放宽约束以增强兼容性。

---

## 七、AwaiterStatus 枚举：三态状态机

配套的 `IAwaiter` 文件定义了 awaiter 的三种状态：

```csharp
public enum AwaiterStatus : byte
{
    Pending = 0,    // 尚未完成
    Succeeded = 1,  // 成功完成
    Faulted = 2,    // 发生异常
}
```

使用 `byte` 类型而非默认 `int` 的原因：

1. **节省内存**：大量 ETTask 并发时，4 字节 vs 1 字节的差距在大规模场景下显著
2. **对齐优化**：在结构体中可利用内存对齐减少 padding
3. **明确语义**：ETTask 不支持取消（对应标准 Task 的 `Canceled`），只有三态

---

## 八、TimerCoreInvokeType：与定时器的桥接

```csharp
[UniqueId(0, 100)]
public static class TimerCoreInvokeType
{
    public const int CoroutineTimeout = 1;
}
```

这个类定义了协程超时的回调类型 ID，配合 ATimer 基类使用：

```csharp
public abstract class ATimer<T> : AInvokeHandler<TimerCallback> where T : class
{
    public override void Handle(TimerCallback a)
    {
        this.Run(a.Args as T);
    }
    protected abstract void Run(T t);
}
```

`ATimer<T>` 将定时器回调与 ETTask 的超时取消机制结合，`CoroutineLock` 等系统的超时等待正是通过这一机制实现的——当协程等待超时时，`CoroutineTimeout` 触发对应的 `ATimer` 子类，进而取消等待中的 ETTask。

---

## 九、实战示例：完整异步调用链路

```csharp
// 业务层写法
public async ETTask LoadPlayerDataAsync(int playerId)
{
    // 等待网络请求（跨帧）
    PlayerData data = await NetworkManager.FetchAsync(playerId);
    // 等待资源加载
    await ResourceManager.LoadAsync("PlayerAvatar");
    // 同步逻辑
    InitPlayer(data);
}
```

底层实际发生的事：

```
1. 编译器生成 LoadPlayerDataAsync_StateMachine : IAsyncStateMachine
2. ETAsyncTaskMethodBuilder.Create() → 从池取 ETTask
3. Start() → stateMachine.MoveNext() 执行到第一个 await
4. AwaitUnsafeOnCompleted() → 创建 StateMachineWrap，传播 Context
5. NetworkManager.FetchAsync 完成 → MoveNext() 继续执行
6. 遇到第二个 await → 同上
7. InitPlayer 同步完成 → SetResult() → Wrap.Recycle() + Task 归池
```

全程零 GC（除首次 StateMachineWrap 懒创建外）。

---

## 十、总结

| 设计决策 | 目的 |
|---------|------|
| `struct` Builder | 避免 Builder 本身的堆分配 |
| `ETTask.Create(true)` | 对象池复用，零 GC |
| `StateMachineWrap` 延迟初始化 | 无 await 的 async 方法完全免费 |
| SetResult 前先 Recycle | 防止回调重入时的数据竞争 |
| 双模式上下文传播 | 支持 Context 继承与取消链路 |
| `AwaiterStatus byte` | 节省内存，明确三态语义 |

`AsyncETTaskMethodBuilder` 是 ETTask 框架零 GC 承诺的最后一道防线——它用精心设计的七步协议，将 C# 编译器生成的状态机代码与 ETTask 的对象池体系无缝衔接，让游戏开发者可以用优雅的 `async/await` 语法写出性能媲美手写协程的异步代码。