---
title: ETTask异步状态机构建器原理与StateMachineWrap对象池优化
published: 2026-04-10
description: 深入解析 ETTask 自定义异步方法构建器（AsyncMethodBuilder）的工作机制，以及 StateMachineWrap 对象池如何消除 async/await 状态机的 GC 分配。
tags: [Unity, ETTask, 异步编程, 状态机, 对象池, GC优化]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

# ETTask 异步状态机构建器原理与 StateMachineWrap 对象池优化

C# 的 `async/await` 在底层会由编译器生成一个状态机结构体，并通过 `AsyncMethodBuilder` 管理其生命周期。原生的 `Task` 体系每次 `async` 调用都会在堆上分配对象，产生 GC 压力。ETTask 通过自定义 `AsyncMethodBuilder` + `StateMachineWrap` 对象池，从根本上消除了这部分 GC 分配。

---

## 一、C# 编译器与 AsyncMethodBuilder 的约定

当你写下：

```csharp
public async ETTask DoSomethingAsync()
{
    await Task.Delay(100);
}
```

编译器实际生成的代码大致如下：

```csharp
// 编译器生成的状态机（简化版）
[CompilerGenerated]
private struct <DoSomethingAsync>d__0 : IAsyncStateMachine
{
    public int <>1__state;
    public ETAsyncTaskMethodBuilder <>t__builder;  // 关键：使用自定义 Builder
    // ... 局部变量字段 ...

    void IAsyncStateMachine.MoveNext() { /* 状态机逻辑 */ }
    void IAsyncStateMachine.SetStateMachine(IAsyncStateMachine sm) { }
}
```

框架通过在 `ETTask` 上标注 `[AsyncMethodBuilder(typeof(ETAsyncTaskMethodBuilder))]`，让编译器使用自定义的 Builder，从而接管状态机的整个生命周期。

---

## 二、ETAsyncTaskMethodBuilder 核心实现

```csharp
public struct ETAsyncTaskMethodBuilder
{
    private IStateMachineWrap iStateMachineWrap;  // 来自对象池的状态机包装
    private ETTask tcs;                           // 对外暴露的 Task

    // 1. 静态工厂，由编译器调用
    public static ETAsyncTaskMethodBuilder Create()
    {
        return new ETAsyncTaskMethodBuilder { tcs = ETTask.Create(fromPool: true) };
    }

    // 2. 暴露给 await 方调用的 Task
    public ETTask Task => this.tcs;

    // 3. async 方法正常返回时
    public void SetResult()
    {
        this.iStateMachineWrap?.Recycle();  // 状态机包装回收到对象池
        this.iStateMachineWrap = null;
        this.tcs.SetResult();               // 唤醒等待者
    }

    // 4. await 某个 awaiter 时的核心路径
    public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
        ref TAwaiter awaiter, ref TStateMachine stateMachine)
        where TAwaiter : ICriticalNotifyCompletion
        where TStateMachine : IAsyncStateMachine
    {
        if (this.iStateMachineWrap == null)
        {
            // 首次 await：从对象池取出状态机包装，装箱状态机
            var wrap = StateMachineWrap<TStateMachine>.Create();
            wrap.SetStateMachine(stateMachine);
            this.iStateMachineWrap = wrap;
        }
        // 注册回调：awaiter 完成时调用 MoveNext
        awaiter.UnsafeOnCompleted(this.iStateMachineWrap.MoveNext);
    }
}
```

---

## 三、StateMachineWrap 的对象池设计

状态机结构体（`TStateMachine`）在首次 `await` 时必须装箱到堆上（因为需要跨 `await` 点存活）。原生 `Task` 每次都 `new`，而 ETTask 通过 `StateMachineWrap<T>` 将这个装箱对象放入对象池复用：

```csharp
public class StateMachineWrap<T> : IStateMachineWrap where T : IAsyncStateMachine
{
    // 每个 TStateMachine 类型有独立的对象池
    private static readonly Queue<StateMachineWrap<T>> pool = new Queue<StateMachineWrap<T>>();

    private T stateMachine;

    public static StateMachineWrap<T> Create()
    {
        if (pool.Count == 0)
            return new StateMachineWrap<T>();
        return pool.Dequeue();
    }

    public void SetStateMachine(T sm)
    {
        this.stateMachine = sm;
    }

    // 编译器通过此委托推进状态机
    public void MoveNext()
    {
        this.stateMachine.MoveNext();
    }

    // 状态机执行完毕后回收
    public void Recycle()
    {
        this.stateMachine = default;
        if (pool.Count < 1000)
            pool.Enqueue(this);
    }
}
```

**对象池的类型隔离：**
每种 `TStateMachine` 对应一个独立的 `Queue<StateMachineWrap<T>>`，这是因为不同 `async` 方法生成的状态机结构体大小和字段完全不同，不能共享同一个池。

---

## 四、GC 优化效果对比

| 场景 | 原生 Task | ETTask |
|------|----------|--------|
| 每次 async 调用 | 分配 Task 对象 + 状态机装箱 | 从池中取 ETTask + 复用 StateMachineWrap |
| 高频战斗逻辑（每帧 100 次 await） | ~200 次堆分配/帧 | 0 次堆分配/帧（稳定后） |
| GC 触发频率 | 高 | 极低 |

在游戏战斗场景中，技能释放、伤害计算、AI 决策等逻辑充斥大量 `await`。启用 StateMachineWrap 对象池后，GC 触发间隔从秒级延长到分钟级，消除了 GC 卡顿。

---

## 五、使用注意事项

### 5.1 await 后不要持有 ETTask 引用

```csharp
// ❌ 危险：await 完成后 task 已被回收
ETTask task = DoSomethingAsync();
await task;
task.SomeMethod();  // task 可能已经被复用给另一个协程！

// ✅ 正确：直接 await，不存引用
await DoSomethingAsync();
```

### 5.2 ETVoid 用于 fire-and-forget

```csharp
// ETVoid 不会被 await，也不走对象池
// 适用于"发出去不管结果"的场景
public async ETVoid FireAndForget()
{
    await SomeAsyncWork();
    // 异常会被全局异常处理器捕获，不会静默丢失
}
```

### 5.3 异常传播

ETTask 使用 `ExceptionDispatchInfo` 保留原始调用栈：

```csharp
public void SetException(Exception e)
{
    this.state = AwaiterStatus.Faulted;
    this.callback = ExceptionDispatchInfo.Capture(e);
    // 通知等待者，等待者在 GetResult 时会重抛异常
    (this.callback as Action)?.Invoke();
}
```

这保证了 `try/catch` 能正确捕获异步异常，调用栈不会因为池化而丢失。

---

## 六、小结

ETTask 的 `AsyncMethodBuilder` 设计是框架 GC 优化的核心环节：

1. **自定义 Builder**：通过 `[AsyncMethodBuilder]` 特性接管编译器行为
2. **ETTask 对象池**：消除每次 async 调用的 Task 分配
3. **StateMachineWrap 对象池**：消除状态机装箱的堆分配
4. **类型隔离的池**：每种状态机类型独立池，确保类型安全

三层对象池协同，使得高频异步调用的 GC 开销降至接近零，是游戏异步编程的最佳实践。
