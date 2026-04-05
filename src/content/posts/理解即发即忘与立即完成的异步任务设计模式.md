---
title: 理解"即发即忘"与"立即完成"的异步任务设计模式
published: 2026-03-31
description: 深入解析 ETVoid 和 ETTaskCompleted 两种特殊异步类型的设计动机与使用场景，彻底搞清楚什么时候用、为什么这样设计。
tags: [Unity, 异步编程, 设计模式]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 两个"特殊"的异步类型

在学习 ETTask 框架时，除了 `ETTask` 和 `ETTask<T>`，你会发现还有两个结构体：`ETVoid` 和 `ETTaskCompleted`。

它们看起来像是简化版的异步类型，但为什么要单独设计它们？什么场景下使用？这篇文章来彻底说清楚。

---

## ETVoid：即发即忘的异步调用

### 问题的起源

在游戏中，有大量的"触发后不关心结果"的异步操作，比如：

```csharp
// 播放音效（不需要等它结束）
PlaySoundAsync("hit_sound");

// 显示伤害飘字（不需要等它消失）
ShowDamageTextAsync(damage, position);

// 发送埋点日志（完全不关心）
SendAnalyticsAsync("player_died");
```

如果用 `ETTask`：

```csharp
public async ETTask PlaySoundAsync(string name) { ... }

// 调用时
PlaySoundAsync("hit_sound");  // ❌ 编译器警告：未 await 的 Task
await PlaySoundAsync("hit_sound");  // ✅ 但我不想等！
```

如果不 `await`，编译器会产生 `CS4014` 警告，而且异步方法内部的异常会被静默吞掉。

如果用 `.Coroutine()` 扩展方法：

```csharp
PlaySoundAsync("hit_sound").Coroutine();  // ✅ 明确"我知道自己在 fire-and-forget"
```

这已经是 ETTask 框架的推荐做法了。但 ETVoid 提供了另一种选择：

### ETVoid 的设计

```csharp
[AsyncMethodBuilder(typeof(AsyncETVoidMethodBuilder))]
internal struct ETVoid : ICriticalNotifyCompletion
{
    [DebuggerHidden]
    public void Coroutine() { }  // 空实现！

    [DebuggerHidden]
    public bool IsCompleted => true;  // 永远是已完成！

    [DebuggerHidden]
    public void OnCompleted(Action continuation) { }

    [DebuggerHidden]
    public void UnsafeOnCompleted(Action continuation) { }
}
```

`ETVoid` 是一个**返回值立即表示完成、但实际工作在后台继续**的异步类型。

当方法返回类型是 `ETVoid` 时，调用者不需要也不能 `await` 它（因为 `ETVoid` 没有公开 `GetAwaiter()` 方法），只需要调用 `.Coroutine()` 启动它。

### 实际使用

```csharp
// 框架内部方法
[DebuggerHidden]
private async ETVoid InnerCoroutine()
{
    await this;
}

[DebuggerHidden]
public void Coroutine()
{
    this.SetContext(null);
    InnerCoroutine().Coroutine();  // ETVoid.Coroutine() 是空实现，不做任何事
}
```

`ETTask.Coroutine()` 的本质是：把任务包装成 `ETVoid`，然后调用 `.Coroutine()`（空方法），这只是一种**明确表意**的方式——"我知道这是 fire-and-forget"。

### ETVoid 与 .Coroutine() 的对比

| 特性 | `async ETVoid` 方法 | `async ETTask` + `.Coroutine()` |
|------|--------------------|---------------------------------|
| 调用方是否会被编译器警告 | 不警告 | 不加 await 会警告 |
| 是否可以被外部 await | 不行（internal） | 可以 |
| 异常处理 | 通过 ExceptionHandler | 通过 ExceptionHandler |
| 推荐使用 | 框架内部 | 业务代码 |

**结论**：业务代码中推荐 `async ETTask` + `.Coroutine()`，更灵活。`ETVoid` 主要是框架内部用的。

---

## ETVoid 的方法构建器

`ETVoid` 对应的 `AsyncETVoidMethodBuilder` 比 `ETAsyncTaskMethodBuilder` 简单很多：

```csharp
public struct AsyncETVoidMethodBuilder
{
    public static AsyncETVoidMethodBuilder Create()
    {
        return new AsyncETVoidMethodBuilder();
    }

    public void SetException(Exception exception)
    {
        ETTask.ExceptionHandler?.Invoke(exception);  // 异常直接交给全局处理器
    }

    public void SetResult() { }  // 什么都不做

    public ETVoid Task => default;  // 立即返回默认值（IsCompleted = true）

    // AwaitUnsafeOnCompleted 等实现类似 ETAsyncTaskMethodBuilder
    // ...
}
```

关键点：`SetResult()` 是空实现——这个方法"完成"了，但没有人关心结果。异常则通过 `ETTask.ExceptionHandler` 全局处理，不会被吞掉。

---

## ETTaskCompleted：立即完成的占位符

### 场景：条件性异步

有时候，一个方法在某些条件下是异步的（需要等待），在另一些条件下可以立即完成：

```csharp
public async ETTask LoadDataAsync(string path)
{
    // 如果缓存中有，立即返回
    if (AssetCache.HasCachedAsset(path))
    {
        return;  // 立即返回，但编译器仍然认为这是异步方法
    }
    
    // 缓存中没有，真正加载
    await ResourceManager.LoadFromDiskAsync(path);
}
```

编译器会把这个方法翻译成状态机，即使"立即返回"这个路径也涉及状态机初始化。

`ETTaskCompleted` 提供了一种更优化的写法：

```csharp
[AsyncMethodBuilder(typeof(AsyncETTaskCompletedMethodBuilder))]
public struct ETTaskCompleted : ICriticalNotifyCompletion
{
    [DebuggerHidden]
    public ETTaskCompleted GetAwaiter() { return this; }

    [DebuggerHidden]
    public bool IsCompleted => true;  // 永远是完成状态

    [DebuggerHidden]
    public void GetResult() { }  // 空实现

    [DebuggerHidden]
    public void OnCompleted(Action continuation) { }

    [DebuggerHidden]
    public void UnsafeOnCompleted(Action continuation) { }
}
```

当你 `await` 一个 `ETTaskCompleted`：

```csharp
await new ETTaskCompleted();
```

由于 `IsCompleted` 永远是 `true`，编译器生成的代码会检查这个值，发现"已完成"，直接调用 `GetResult()` 跳过等待，等效于同步执行。

**不会产生任何挂起，不会注册任何回调，不会有任何分配。**

### 实际应用

`ETTaskCompleted` 的典型用法是作为一个"零开销的已完成任务"返回值：

```csharp
// 这个接口方法可能同步完成也可能异步完成
public interface IDataLoader
{
    ETTask LoadAsync(string path);
}

// 内存缓存版本：同步完成
public class MemoryCacheLoader : IDataLoader
{
    public async ETTask LoadAsync(string path)
    {
        // 直接从内存读，立即完成
        var data = _cache[path];
        ProcessData(data);
        // 函数返回，使用 AsyncETTaskCompletedMethodBuilder 构建，零开销
    }
}

// 磁盘版本：真正异步
public class DiskLoader : IDataLoader
{
    public async ETTask LoadAsync(string path)
    {
        var bytes = await File.ReadAllBytesAsync(path);
        ProcessData(bytes);
    }
}
```

### ETTaskCompleted 与 ETTask.CompletedTask 的区别

你可能注意到 `ETTask` 也有一个 `CompletedTask` 静态属性：

```csharp
public static ETTask CompletedTask
{
    get { return completedTask ??= new ETTask() { state = AwaiterStatus.Succeeded }; }
}
```

区别：

| | `ETTask.CompletedTask` | `await new ETTaskCompleted()` |
|--|----------------------|------------------------------|
| 类型 | `ETTask`（类，堆对象） | `ETTaskCompleted`（结构体，栈上） |
| 内存 | 单例，不额外分配 | 零分配（值类型） |
| 适用场景 | 返回 `ETTask` 类型时 | 方法体内直接 `await` |
| 对象复用 | 使用同一个单例 | 每次都是新值类型（但零开销） |

两者都是"立即完成"的，但使用场景不同：

```csharp
// 用 CompletedTask：方法需要返回 ETTask 对象
public ETTask DoNothing()
{
    return ETTask.CompletedTask;
}

// 用 ETTaskCompleted：方法是 async 的，但某个分支立即完成
public async ETTask MaybeAsync(bool needAsync)
{
    if (!needAsync)
    {
        await new ETTaskCompleted();  // 立即完成的 await
        return;
    }
    await SomeRealAsyncWork();
}
```

---

## 背后的方法构建器对比

三种 `async` 方法，三种 MethodBuilder：

```
async ETTask   → ETAsyncTaskMethodBuilder
                 - 创建 ETTask（从池中获取）
                 - 状态机包装在 StateMachineWrap 中
                 - 支持 Context 传播

async ETVoid   → AsyncETVoidMethodBuilder  
                 - 不创建任何任务对象
                 - 异常直接转发给全局 ExceptionHandler
                 - SetResult 是空实现

async ETTaskCompleted → AsyncETTaskCompletedMethodBuilder
                 - 最轻量，几乎什么都不做
                 - SetResult 和 SetException 极简
```

它们的存在体现了**按需设计**的思想：不同场景用不同工具，而不是用一个万能的重型工具包揽所有情况。

---

## 总结与使用指南

```
需要等待结果？
├─ 有返回值 → async ETTask<T>
└─ 无返回值 → async ETTask

不需要等待结果（fire-and-forget）？
└─ async ETTask + .Coroutine() 调用

内部框架中不需要外部 await？
└─ async ETVoid

方法内某个分支可以立即完成？
└─ await new ETTaskCompleted() 或 return ETTask.CompletedTask
```

掌握了这四种类型的选择逻辑，你就能在每个异步场景中做出最优的选择，既保证代码的正确性，又最大化运行时性能。
