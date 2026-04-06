---
title: 深入理解 Unity 异步任务核心原理与实现
published: 2026-03-31
description: 从零剖析 Unity 项目中自定义异步任务类的设计思路、对象池机制和状态机驱动流程，帮助新手彻底搞懂 async/await 背后发生了什么。
tags: [Unity, 异步编程, 性能优化]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

## 为什么要自己实现异步任务？

刚入行的同学可能会问：Unity 本身有协程（Coroutine），C# 也有 `Task`，为什么还要自己写一套异步任务系统？

答案来自于实际项目中遇到的三个痛点：

1. **Unity 协程无法跨帧返回值**：`yield return` 只能返回 `null`，想传数据需要额外变量，代码极不直观。
2. **C# 原生 Task 携带大量开销**：`System.Threading.Tasks.Task` 为多线程场景设计，每次创建都会在堆上分配，并关联线程池调度器，在单线程游戏主循环里这是浪费。
3. **异常处理不友好**：协程中的异常会被 Unity 吞掉，无法以统一方式捕获。

正是基于这些考量，游戏框架自研了一套轻量级异步任务系统，它的名字叫 **ETTask**。

---

## ETTask 的设计哲学：第一性原理

让我们从最基础的问题出发：**C# 的 `async/await` 到底是什么？**

`async/await` 本质上是编译器的语法糖。当你写下：

```csharp
public async ETTask LoadCharacterAsync(string path)
{
    var prefab = await ResManager.LoadAsync<GameObject>(path);
    Instantiate(prefab);
}
```

编译器会把这段代码翻译成一个**状态机类**，大概长这样：

```csharp
// 编译器自动生成（伪代码）
private struct LoadCharacterAsync_StateMachine : IAsyncStateMachine
{
    public int state;          // 当前状态
    public ETAsyncTaskMethodBuilder builder;  // 方法构建器
    public string path;
    private GameObject prefab;

    public void MoveNext()
    {
        switch (state)
        {
            case 0:
                state = 1;
                var awaiter = ResManager.LoadAsync<GameObject>(path).GetAwaiter();
                if (!awaiter.IsCompleted)
                {
                    builder.AwaitUnsafeOnCompleted(ref awaiter, ref this);
                    return; // 挂起，等待回调
                }
                goto case 1;
            case 1:
                prefab = awaiter.GetResult();
                Instantiate(prefab);
                builder.SetResult();
                break;
        }
    }
}
```

状态机每次 `MoveNext()` 前进一步，遇到 `await` 未完成时就"挂起"（即 `return`），等异步操作完成后通过回调再次触发 `MoveNext()`。

**关键认知**：`await` 不阻塞线程，它只是注册了一个"完成后调我"的回调。

---

## ETTask 的核心结构

打开 `ETTask.cs`，可以看到 ETTask 同时实现了三个接口：

```csharp
[AsyncMethodBuilder(typeof(ETAsyncTaskMethodBuilder))]
public class ETTask : ICriticalNotifyCompletion, IETTask
```

- **`ICriticalNotifyCompletion`**：告诉编译器这个类可以被 `await`，必须实现 `OnCompleted` / `UnsafeOnCompleted`。
- **`IETTask`**：框架自定义接口，用于传递上下文（Context）。
- **`[AsyncMethodBuilder(...)]`** 特性：告诉编译器，当方法返回值为 `ETTask` 时，使用 `ETAsyncTaskMethodBuilder` 来构建状态机。

ETTask 内部的状态很简洁：

```csharp
private bool fromPool;           // 是否来自对象池
private AwaiterStatus state;     // Pending / Succeeded / Faulted
private object callback;         // Action（成功回调）或 ExceptionDispatchInfo（异常）
```

只有 **三个字段**。这就是它轻量的秘密。

---

## 对象池机制：杜绝 GC 的关键

游戏运行时频繁创建销毁对象会触发 GC（垃圾回收），导致掉帧。ETTask 通过**对象池**复用实例：

```csharp
[StaticField]
private static readonly Queue<ETTask> queue = new();

public static ETTask Create(bool fromPool = false)
{
    if (!fromPool)
    {
        return new ETTask();  // 不用池，直接 new
    }
    
    ETTask task;
    lock (queue)
    {
        if (!queue.TryDequeue(out task))
        {
            return new ETTask() { fromPool = true };  // 池空，new 一个并标记
        }
    }
    return task;  // 从池中取出
}
```

用完之后 `GetResult()` 会调用 `Recycle()` 把它放回池：

```csharp
private void Recycle()
{
    if (!this.fromPool) return;  // 非池对象，不回收
    
    // 清空状态
    this.state = AwaiterStatus.Pending;
    this.callback = null;
    this.Context = null;
    this.TaskType = TaskType.Common;
    
    lock (queue)
    {
        if (queue.Count > 1000) return;  // 防止池无限膨胀
        queue.Enqueue(this);
    }
}
```

注意池的容量上限是 **1000**，超出时直接丢弃让 GC 回收。这是一个经验值，避免内存占用过大。

> **注意事项**：如果你用 `ETTask.Create(true)` 开启了池，`await` 之后**绝对不能再持有这个 task 的引用**，因为它可能已经被回收并分配给了别人！

---

## 完整的生命周期

让我们追踪一个 ETTask 从创建到完成的完整路径：

### 步骤一：创建

```csharp
// 在 ResManager 中
ETTask task = ETTask.Create(true);  // 从池中取出，state = Pending
```

### 步骤二：挂起（注册回调）

当 `await task` 且 task 未完成时，编译器调用：

```csharp
public void UnsafeOnCompleted(Action action)
{
    if (this.state != AwaiterStatus.Pending)
    {
        action?.Invoke();  // 已完成，立即执行
        return;
    }
    this.callback = action;  // 未完成，存储回调
}
```

这里的 `action` 就是状态机的 `MoveNext`。

### 步骤三：完成（触发回调）

资源加载完毕后调用：

```csharp
public void SetResult()
{
    this.state = AwaiterStatus.Succeeded;
    Action c = this.callback as Action;
    this.callback = null;
    c?.Invoke();  // 调用 MoveNext，状态机继续执行
}
```

### 步骤四：获取结果并回收

状态机调用 `GetResult()`：

```csharp
public void GetResult()
{
    switch (this.state)
    {
        case AwaiterStatus.Succeeded:
            this.Recycle();  // 放回池
            break;
        case AwaiterStatus.Faulted:
            ExceptionDispatchInfo c = this.callback as ExceptionDispatchInfo;
            this.callback = null;
            this.Recycle();
            c?.Throw();  // 重新抛出异常（保留原始堆栈）
            break;
    }
}
```

---

## 泛型版本 ETTask\<T\>

当需要异步操作返回值时，使用 `ETTask<T>`：

```csharp
public async ETTask<int> CalculateScoreAsync()
{
    await SomeAsyncOperation();
    return 100;
}

// 调用
int score = await CalculateScoreAsync();
```

`ETTask<T>` 比 `ETTask` 多了一个 `value` 字段存储结果：

```csharp
private T value;

public void SetResult(T result)
{
    this.state = AwaiterStatus.Succeeded;
    this.value = result;  // 存储返回值
    Action c = this.callback as Action;
    this.callback = null;
    c?.Invoke();
}

public T GetResult()
{
    switch (this.state)
    {
        case AwaiterStatus.Succeeded:
            T v = this.value;
            this.Recycle();
            return v;  // 返回后立即回收
        // ...
    }
}
```

---

## Context 传递机制

ETTask 有一个特别的设计：**Context 链**。每个 ETTask 持有 `Context` 对象和 `TaskType` 标记。

```csharp
public enum TaskType : byte
{
    Common,       // 普通任务
    WithContext,  // 主动设置了 Context
    ContextTask,  // 专门用于读取 Context 的任务
}

public TaskType TaskType { get; set; }
public object Context { get; set; }
```

这套机制允许在整个异步调用链中传递上下文（比如当前角色、场景对象等），而无需在每个方法签名里传参数。

你可以这样使用：

```csharp
// 在某个异步方法里注入上下文
await someTask.WithContext(myCharacter);

// 在深层方法里取出上下文
var character = await ETTaskHelper.GetContextAsync<Character>();
```

---

## 完整的 `CompletedTask` 优化

对于已知立即完成的操作，框架提供了一个单例：

```csharp
[StaticField]
private static ETTask completedTask;

public static ETTask CompletedTask
{
    get
    {
        return completedTask ??= new ETTask() { state = AwaiterStatus.Succeeded };
    }
}
```

当你写：
```csharp
public async ETTask DoNothingAsync()
{
    // 什么都不做
}
```

编译器检测到没有真正的异步点，会直接使用 `CompletedTask`，避免任何分配。

---

## 与 C# Task 的对比

| 特性 | System.Task | ETTask |
|------|------------|--------|
| 内存分配 | 每次 new 分配堆内存 | 对象池复用，零额外分配 |
| 线程调度 | 关联线程池 SynchronizationContext | 无线程切换，在主线程运行 |
| 取消支持 | CancellationToken | ETCancellationToken（更轻量） |
| 多任务等待 | Task.WhenAll / WhenAny | ETTaskHelper.WaitAll / WaitAny |
| 适用场景 | 多线程/IO 密集 | 游戏主循环单线程异步 |

---

## 常见错误与规避

**错误一：await 后继续操作 task 对象**

```csharp
// ❌ 错误！task 可能已被回收
var task = ETTask.Create(true);
await task;
task.SetResult(); // 此时 task 可能是别人的了！

// ✅ 正确：先存引用，置空后操作
var tcs = ETTask.Create(true);
var temp = tcs;
tcs = null;  // 置空，防止重复操作
temp.SetResult();
```

**错误二：同一 task 多次 SetResult**

```csharp
// ❌ 会抛 InvalidOperationException
task.SetResult();
task.SetResult(); // 第二次会抛异常
```

**错误三：忘记 await**

```csharp
// ❌ 不等待，异常会被吞掉
LoadAsync();   // 没有 await，也没有 .Coroutine()

// ✅ 正确：如果不想 await，用 Coroutine() 启动
LoadAsync().Coroutine();
```

---

## 总结

ETTask 的设计体现了「**最小可行原则**」：

1. 用**状态机**实现非阻塞异步，不切换线程
2. 用**对象池**消除 GC 压力
3. 用**三个字段**（state、callback、fromPool）完成全部功能
4. 通过 `[AsyncMethodBuilder]` 特性无缝接入 C# 编译器的 async/await 语法

对于新手来说，最重要的心智模型是：**`await` 只是"注册回调后挂起，完成后继续"**，和协程的 `yield return` 在本质上一样，只是更优雅、更安全、有返回值。

下一篇我们会深入 `ETCancellationToken`，看看如何正确取消一个异步操作。
