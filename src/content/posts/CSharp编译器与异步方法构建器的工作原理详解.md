---
title: C# 编译器与异步方法构建器的工作原理详解
published: 2026-03-31
description: 深入剖析 AsyncMethodBuilder 的七步协议，揭开 async/await 语法糖背后编译器与运行时协作的神秘面纱。
tags: [Unity, 异步编程, C# 编译器原理]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

## 编译器是如何实现 async/await 的？

很多同学用了好几年的 `async/await`，却从来没想过一个问题：**编译器怎么知道该把 `async` 方法编译成什么样的代码？**

答案是：编译器遵从一套**七步协议**，由方法构建器（`MethodBuilder`）来"告诉"编译器如何处理异步方法的各个环节。

这套机制完全由 C# 规范定义，任何人都可以自定义自己的 `MethodBuilder`——这正是 ETTask 框架能够无缝支持 `async/await` 语法的基础。

---

## 七步协议一览

`[AsyncMethodBuilder(typeof(ETAsyncTaskMethodBuilder))]` 这个特性告诉编译器：当方法返回 `ETTask` 时，使用 `ETAsyncTaskMethodBuilder` 来构建它。

构建器必须实现以下七个方法（按编译器调用顺序）：

```csharp
public struct ETAsyncTaskMethodBuilder
{
    // 1. 静态工厂方法：编译器首先调用它创建构建器
    public static ETAsyncTaskMethodBuilder Create() { ... }

    // 2. 任务属性：调用者 await 的就是这个对象
    public ETTask Task { get; }

    // 3. 设置异常：async 方法抛异常时调用
    public void SetException(Exception exception) { ... }

    // 4. 设置结果：async 方法正常结束时调用
    public void SetResult() { ... }

    // 5. 同步等待接口的 OnCompleted：awaiter 实现 INotifyCompletion 时
    public void AwaitOnCompleted<TAwaiter, TStateMachine>(...) { ... }

    // 6. 非安全等待接口的 OnCompleted：awaiter 实现 ICriticalNotifyCompletion 时（更快）
    public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(...) { ... }

    // 7. 启动状态机（首次 MoveNext）
    public void Start<TStateMachine>(ref TStateMachine stateMachine) { ... }

    // 8. 设置状态机（通常空实现，历史遗留）
    public void SetStateMachine(IAsyncStateMachine stateMachine) { ... }
}
```

---

## 编译器生成代码的全流程

让我们跟踪一个简单例子，看编译器的每一步：

```csharp
public async ETTask ExampleAsync()
{
    await SomeTask();
    Debug.Log("完成");
}
```

### 第一步：调用 `Create()` 创建构建器

```csharp
public static ETAsyncTaskMethodBuilder Create()
{
    ETAsyncTaskMethodBuilder builder = new() 
    { 
        tcs = ETTask.Create(true)  // 从对象池获取一个 ETTask
    };
    return builder;
}
```

编译器把方法体翻译成状态机，在状态机初始化时立即调用 `Create()`，分配好任务对象。

### 第二步：获取 `Task` 属性

```csharp
public ETTask Task => this.tcs;
```

这个 `tcs` 就是方法返回给调用者的对象。调用者 `await ExampleAsync()` 时，就是在等这个 `tcs`。

### 第三步：调用 `Start()` 启动状态机

```csharp
public void Start<TStateMachine>(ref TStateMachine stateMachine) 
    where TStateMachine : IAsyncStateMachine
{
    stateMachine.MoveNext();  // 直接调用！无任何延迟
}
```

这是很多人没意识到的关键点：**`Start()` 在方法被调用时同步执行 `MoveNext()`，状态机立即开始运行，直到遇到第一个真正的异步等待点。**

换言之，如果 `async` 方法中没有任何真正的异步点（`await` 的目标 `IsCompleted == true`），整个方法会**同步完成**。

### 第四步：遇到 await，调用 `AwaitUnsafeOnCompleted()`

当状态机执行到 `await SomeTask()` 时（假设 SomeTask 未完成），编译器生成的代码会调用：

```csharp
public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, 
    ref TStateMachine stateMachine) 
    where TAwaiter : ICriticalNotifyCompletion 
    where TStateMachine : IAsyncStateMachine
{
    // 把状态机包装进对象池中（StateMachineWrap）
    this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
    
    // 注册回调：awaiter 完成时，调用 MoveNext
    awaiter.UnsafeOnCompleted(this.iStateMachineWrap.MoveNext);

    // 处理 Context 传播
    if (awaiter is not IETTask task) return;
    
    if (this.tcs.TaskType == TaskType.WithContext)
    {
        task.SetContext(this.tcs.Context);
        return;
    }
    
    this.tcs.Context = task;  // 把 awaiter 链接到 Context 链
}
```

这一步做了三件事：
1. 把状态机放入对象池（避免装箱开销）
2. 告诉 awaiter："你完成时，调用我这个函数"
3. 维护 Context 传播链

### 第五步：状态机被唤醒，继续执行

当 `SomeTask()` 完成时，调用了注册的 `MoveNext` 回调，状态机继续执行到 `Debug.Log("完成")`。

### 第六步：方法结束，调用 `SetResult()`

```csharp
public void SetResult()
{
    if (this.iStateMachineWrap != null)
    {
        this.iStateMachineWrap.Recycle();  // 状态机包装对象回收
        this.iStateMachineWrap = null;
    }
    this.tcs.SetResult();  // 通知等待者完成
}
```

`tcs.SetResult()` 触发所有在等待这个 ETTask 的回调（也就是调用者的状态机 `MoveNext`）。

### 第七步：异常情况，调用 `SetException()`

```csharp
public void SetException(Exception exception)
{
    if (this.iStateMachineWrap != null)
    {
        this.iStateMachineWrap.Recycle();
        this.iStateMachineWrap = null;
    }
    this.tcs.SetException(exception);  // 把异常存储在 ETTask 中
}
```

---

## StateMachineWrap 的优化作用

注意 `AwaitUnsafeOnCompleted` 中有这样一行：

```csharp
this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
```

`StateMachineWrap` 是对状态机的**对象池包装**。

**为什么需要它？**

C# 编译器生成的状态机默认是**值类型（struct）**。当需要注册回调时，需要把 `stateMachine.MoveNext` 包装成一个 `Action` 委托，这就需要把 struct 装箱（boxing）到堆上——产生 GC。

`StateMachineWrap<T>` 把状态机**提前移动到堆上**，并从对象池中获取，避免了每次都装箱。

```csharp
public class StateMachineWrap<T> : IStateMachineWrap where T : IAsyncStateMachine
{
    private static readonly Queue<StateMachineWrap<T>> pool = new();
    
    private T stateMachine;

    public static StateMachineWrap<T> Fetch(ref T stateMachine)
    {
        StateMachineWrap<T> wrap;
        if (!pool.TryDequeue(out wrap))
        {
            wrap = new StateMachineWrap<T>();
        }
        wrap.stateMachine = stateMachine;  // 复制值类型状态机到堆上的包装对象
        return wrap;
    }
    
    public void MoveNext()
    {
        this.stateMachine.MoveNext();  // 委托给内部的状态机
    }
    
    public void Recycle()
    {
        this.stateMachine = default;
        pool.Enqueue(this);  // 回收
    }
}
```

这是整个 ETTask 框架零 GC 设计的核心之一：对象池 + StateMachineWrap 的组合。

---

## 泛型版本：ETAsyncTaskMethodBuilder\<T\>

带返回值的 `async ETTask<T>` 方法使用 `ETAsyncTaskMethodBuilder<T>`，和无返回值版本几乎相同，只是 `SetResult` 接受一个参数：

```csharp
public void SetResult(T ret)
{
    if (this.iStateMachineWrap != null)
    {
        this.iStateMachineWrap.Recycle();
        this.iStateMachineWrap = null;
    }
    this.tcs.SetResult(ret);  // 把结果值存进 ETTask<T>
}
```

调用者通过 `await` 获取这个返回值：

```csharp
// 调用者
int result = await SomeCalculationAsync();

// 内部等效于
var awaiter = SomeCalculationAsync().GetAwaiter();
// awaiter.IsCompleted == false → 注册回调
// 完成后：
int result = awaiter.GetResult();  // 从 ETTask<int>.value 取出
```

---

## 一个实验：理解同步 vs 异步

理解了 `Start()` 直接调用 `MoveNext()` 的行为后，我们来做一个实验：

```csharp
public async ETTask PrintOrderAsync()
{
    Debug.Log("A");
    await ETTask.CompletedTask;  // 已完成的任务
    Debug.Log("B");
    await SomeRealAsyncWork();   // 真正的异步
    Debug.Log("C");
}

Debug.Log("Before");
PrintOrderAsync().Coroutine();
Debug.Log("After");
```

输出结果是：

```
Before
A          ← Start() 同步执行了 MoveNext()，直到遇到真正的异步
B          ← CompletedTask.IsCompleted == true，不挂起，继续执行
After      ← SomeRealAsyncWork 挂起了，控制权返回调用者
C          ← 异步完成后，在之后的某帧执行
```

这说明 **`await` 不一定是异步的**——如果被等待的对象已经完成（`IsCompleted == true`），编译器生成的代码会直接跳过回调注册，同步执行后续代码。

---

## 与 C# 官方 TaskMethodBuilder 的对比

| 特性 | AsyncTaskMethodBuilder | ETAsyncTaskMethodBuilder |
|------|----------------------|--------------------------|
| 任务对象 | 堆分配 Task | 对象池 ETTask |
| 状态机处理 | 装箱到堆 | StateMachineWrap 对象池 |
| 上下文传播 | ExecutionContext（线程相关） | ETTask.Context（游戏对象） |
| 线程切换 | 可能切换到线程池 | 始终在主线程 |
| 异常处理 | AggregateException | ExceptionDispatchInfo（保留堆栈） |

---

## 总结

`ETAsyncTaskMethodBuilder` 是一个完美的工程案例，展示了如何：

1. **利用编译器扩展点**：通过 `[AsyncMethodBuilder]` 特性接入 C# 标准 async 机制
2. **消灭 GC**：对象池（ETTask）+ StateMachineWrap 双重复用
3. **传播上下文**：在 `AwaitUnsafeOnCompleted` 中维护 Context 链
4. **保持简单**：`Start()` 就是 `stateMachine.MoveNext()`，没有任何多余逻辑

理解这七步协议，你就掌握了 C# 异步机制的"底层密码"。无论是阅读框架代码、排查异步 Bug，还是自己设计异步系统，都会如鱼得水。
