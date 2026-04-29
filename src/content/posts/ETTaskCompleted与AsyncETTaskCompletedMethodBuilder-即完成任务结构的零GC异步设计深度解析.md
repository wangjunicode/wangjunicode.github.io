---
title: ETTaskCompleted与AsyncETTaskCompletedMethodBuilder-即完成任务结构的零GC异步设计深度解析
published: 2026-04-29
description: 深入剖析xgame框架中ETTaskCompleted结构体与AsyncETTaskCompletedMethodBuilder的设计原理，分析"始终已完成"的即完成任务模式如何实现零分配、同步直通的轻量级异步契约，揭示C#自定义异步方法构建器的工程价值。
tags: [Unity, xgame, ETTask, 异步编程, CSharp, 游戏框架]
category: 游戏框架
draft: false
encryptedKey: henhaoji123
---

## 前言

在 xgame 框架的异步体系中，绝大多数任务需要经历"挂起 → 恢复"的完整生命周期。然而有一类特殊任务：**它创建出来就已经完成了**。这类任务用于表达"立即可用的结果"——不需要等待、不需要状态机切换、不产生任何堆分配。

`ETTaskCompleted` 结构体与其配套的 `AsyncETTaskCompletedMethodBuilder` 正是为此而生。本文将从源码出发，深度剖析这套"即完成任务"设计的底层原理与工程价值。

---

## 一、ETTaskCompleted 的核心结构

```csharp
[AsyncMethodBuilder(typeof(AsyncETTaskCompletedMethodBuilder))]
public struct ETTaskCompleted : ICriticalNotifyCompletion
{
    public ETTaskCompleted GetAwaiter() => this;

    public bool IsCompleted => true;

    public void GetResult() { }

    public void OnCompleted(Action continuation) { }

    public void UnsafeOnCompleted(Action continuation) { }
}
```

### 1.1 自身即 Awaiter

`GetAwaiter()` 返回 `this`，说明 `ETTaskCompleted` 本身就是 Awaiter。这是一种常见的"自等待"设计，省去了包装一层独立 Awaiter 的开销。

### 1.2 IsCompleted 恒为 true

```csharp
public bool IsCompleted => true;
```

这是整个设计的核心。当 C# 状态机对一个可等待对象执行 `await` 时，首先检查 `IsCompleted`：

- 若为 `true`：**同步直通**，不挂起状态机，直接继续执行
- 若为 `false`：注册 `OnCompleted` 回调，挂起当前协程

`ETTaskCompleted` 的 `IsCompleted` 始终为 `true`，因此 `await ETTaskCompleted` **永远不会挂起**，等同于一条普通语句。

### 1.3 OnCompleted 与 UnsafeOnCompleted 为空实现

由于 `IsCompleted` 恒真，C# 状态机永远不会调用 `OnCompleted` 或 `UnsafeOnCompleted`，因此这两个方法可以安全地留空，不需要任何逻辑。

### 1.4 GetResult 为空

`GetResult()` 是无返回值的，代表这个任务没有结果数据需要传递——它只是一个"已完成的信号"。

---

## 二、AsyncETTaskCompletedMethodBuilder 构建器解析

`ETTaskCompleted` 通过 `[AsyncMethodBuilder(typeof(AsyncETTaskCompletedMethodBuilder))]` 特性，将自身的异步方法构建器绑定为 `AsyncETTaskCompletedMethodBuilder`。

这意味着，当你用 `async` 关键字修饰一个返回 `ETTaskCompleted` 的方法时，编译器会使用这个自定义构建器来生成状态机。

```csharp
public struct AsyncETTaskCompletedMethodBuilder
{
    public static AsyncETTaskCompletedMethodBuilder Create()
    {
        return new AsyncETTaskCompletedMethodBuilder();
    }

    public ETTaskCompleted Task => default;

    public void SetException(Exception e)
    {
        ETTask.ExceptionHandler.Invoke(e);
    }

    public void SetResult() { /* do nothing */ }

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

### 2.1 Task 属性返回 default

```csharp
public ETTaskCompleted Task => default;
```

`Task` 属性就是构建器暴露给外部的"任务对象"。这里返回 `default(ETTaskCompleted)` —— 一个栈上的零初始化结构体，**没有任何堆分配**。

### 2.2 SetResult 为空

由于 `ETTaskCompleted` 是无结果的"信号型"任务，`SetResult` 无需存储任何数据，直接留空。

### 2.3 SetException 委托给全局异常处理

```csharp
public void SetException(Exception e)
{
    ETTask.ExceptionHandler.Invoke(e);
}
```

如果 `async ETTaskCompleted` 方法内部抛出异常，会走到这里，统一交给框架的全局异常处理器处理，而不是吞掉。这保证了即便是"即完成"的轻量任务，也有完整的异常可见性。

### 2.4 Start 直接调用 MoveNext

```csharp
public void Start<TStateMachine>(ref TStateMachine stateMachine)
    where TStateMachine : IAsyncStateMachine
{
    stateMachine.MoveNext();
}
```

`Start` 方法由编译器在方法入口调用，用于启动状态机。这里直接同步调用 `MoveNext()`，没有任何额外调度，保持了同步执行的特性。

---

## 三、为什么需要"即完成任务"？

### 3.1 接口统一性

在框架设计中，某些接口的方法签名需要是异步的：

```csharp
public interface ISomeSystem
{
    ETTaskCompleted Initialize();
}
```

即使某个实现完全是同步逻辑，也必须遵循接口签名。`ETTaskCompleted` 让同步实现无缝接入异步接口，而不引入不必要的 `ETTask` 开销。

### 3.2 零GC优势

与普通 `ETTask` 相比：

| 特性 | ETTask | ETTaskCompleted |
|------|--------|-----------------|
| 堆分配 | 有（对象池复用） | 无（纯栈结构） |
| 状态机挂起 | 可能挂起 | 永不挂起 |
| 适用场景 | 异步等待 | 同步直通 |
| 结果类型 | 有/无 | 无 |

对于高频调用的同步路径，使用 `ETTaskCompleted` 替代 `ETTask` 可以彻底消除对象池的 Acquire/Release 开销。

### 3.3 编译器状态机优化

由于 `IsCompleted` 恒真，编译器在某些情况下可以直接优化掉状态机的挂起分支，生成更简洁的 IL 代码。

---

## 四、使用示例

### 4.1 同步实现异步接口

```csharp
public class PlayerSystem : IStartSystem
{
    // 接口要求返回 ETTaskCompleted，但实现是纯同步的
    public async ETTaskCompleted Start(PlayerEntity player)
    {
        player.Init();
        player.LoadConfig();
        // 不需要 await 任何东西，直接返回
    }
}
```

### 4.2 作为异步方法的"快速返回路径"

```csharp
public async ETTask LoadResource(string path)
{
    if (_cache.ContainsKey(path))
    {
        // 已缓存，立即返回，不走异步加载
        await ETTaskCompleted.default; // 等价于同步执行
        return;
    }

    // 走真正的异步加载
    await AssetLoader.LoadAsync(path);
}
```

### 4.3 空操作系统钩子

```csharp
// 某个组件不需要 Destroy 逻辑，但系统接口要求实现
public async ETTaskCompleted Destroy(SomeComponent self)
{
    // 空实现，编译器会生成最轻量的状态机
}
```

---

## 五、与 ETVoid 的对比

xgame 框架中另有一个 `ETVoid` 类型，也是"无结果"的异步类型，但两者用途不同：

| 对比维度 | ETTaskCompleted | ETVoid |
|---------|-----------------|--------|
| 语义 | 同步直通、已完成 | 即发即忘（fire-and-forget） |
| await 行为 | 不挂起 | 不可被 await（无 GetAwaiter） |
| 使用场景 | 实现异步接口的同步版本 | 启动后台任务不等待结果 |
| 异常处理 | 全局异常处理器 | 全局异常处理器 |

---

## 六、C# 自定义异步方法构建器规范

`AsyncETTaskCompletedMethodBuilder` 遵循 C# 自定义异步方法构建器的标准规范，需实现以下方法：

1. **静态 `Create()`**：工厂方法，编译器调用创建构建器实例
2. **`Task` 属性**：返回任务对象，供调用方 await
3. **`Start<TStateMachine>()`**：启动状态机
4. **`SetResult()`**：设置成功结果
5. **`SetException()`**：设置异常
6. **`AwaitOnCompleted<>()` / `AwaitUnsafeOnCompleted<>()`**：处理内部 await 挂起
7. **`SetStateMachine()`**：绑定状态机引用（通常留空）

这套规范让框架完全掌控异步执行模型，既可以接入 xgame 的 ECS 调度体系，又能规避 `Task<T>` 带来的运行时开销。

---

## 七、总结

`ETTaskCompleted` 是 xgame 异步体系中一颗"隐形的螺丝钉"——体积最小、功能最简，却承担着重要的结构性职责：

1. **统一接口**：让同步实现能以零成本满足异步方法签名的要求
2. **零分配**：纯栈结构，无对象池、无堆内存
3. **同步直通**：`IsCompleted` 恒真，await 时不产生任何挂起开销
4. **完整异常链**：虽然轻量，但异常处理路径完整

理解这个设计，有助于我们在自研框架中精确区分"需要真正异步等待的任务"与"同步逻辑包装为异步接口的伪任务"，在正确的场景使用正确的工具。
