---
title: 从 AwaiterStatus 枚举到状态机包装器的零 GC 优化之路
published: 2026-03-31
description: 深入解析 AwaiterStatus 三状态设计和 StateMachineWrap 对象池，理解 Unity 异步框架如何通过对象池消灭装箱带来的 GC 压力。
tags: [Unity, 异步编程, GC优化, 性能]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 三种状态，定义了一切

打开 `IAwaiter.cs`，内容出乎意料地简单：

```csharp
public enum AwaiterStatus : byte
{
    Pending = 0,     // 等待中
    Succeeded = 1,   // 成功完成
    Faulted = 2,     // 异常结束
}
```

仅仅三个状态，一个 `byte` 类型（只占1字节），却定义了整个异步任务的生命周期。

你可能会问：为什么没有 `Cancelled`（已取消）状态？

这是一个**刻意的设计选择**：在 ETTask 框架中，"取消"不是任务的状态，而是一个**外部行为**。取消令牌（`ETCancellationToken`）触发回调，让异步方法主动检查并提前 `return`，任务本身仍然以 `Succeeded` 状态完成。

这和 `System.Threading.Tasks.TaskStatus` 的 11 种状态形成了鲜明对比：

```
TaskStatus（C# 标准）：
Created, WaitingForActivation, WaitingToRun, Running,
WaitingForChildrenToComplete, RanToCompletion, Canceled, Faulted...

AwaiterStatus（ETTask）：
Pending, Succeeded, Faulted
```

三种状态足以覆盖所有游戏异步场景，没有多余的复杂度。

---

## `byte` 类型的深意

```csharp
public enum AwaiterStatus : byte
```

用 `byte` 而不是默认的 `int` 来定义枚举，节省了 3 字节。

在 ETTask 中，每个 `ETTask` 对象都有一个 `AwaiterStatus state` 字段：

```csharp
private AwaiterStatus state;
```

当游戏场景中同时有 1000 个 ETTask 实例时：
- `int` 版本：4000 字节
- `byte` 版本：1000 字节

差距看起来不大，但在内存敏感的游戏环境中，每一字节都值得珍惜。更重要的是，这体现了框架设计者的**精益意识**：能省则省，不留多余。

---

## 状态机的 GC 陷阱

现在来到这篇文章的核心：`StateMachineWrap`。

要理解它为什么必要，先要理解一个 C# 装箱（Boxing）的陷阱。

### 装箱是 GC 的元凶

C# 的 `async/await` 方法，编译器会把方法体翻译成一个**结构体（struct）**类型的状态机：

```csharp
// 你写的代码
public async ETTask LoadAsync(string path)
{
    var data = await ReadFileAsync(path);
    Process(data);
}

// 编译器生成（伪代码）
private struct <LoadAsync>d__1 : IAsyncStateMachine
{
    public int <>1__state;
    public ETAsyncTaskMethodBuilder <>t__builder;
    public string path;
    // 其他局部变量...
    
    public void MoveNext() { ... }
}
```

这个状态机是 **struct**（值类型），存在于栈上，非常轻量。

**但问题来了**：当状态机被挂起（`await` 一个未完成的任务），需要注册 `MoveNext` 为回调时：

```csharp
// 这里需要把 stateMachine.MoveNext 变成一个 Action（委托）
awaiter.UnsafeOnCompleted(stateMachine.MoveNext);
```

把 `struct` 的实例方法转换成委托，必须先把 `struct` **装箱**到堆上！这就产生了 GC 分配。

### StateMachineWrap 如何解决问题

`StateMachineWrap<T>` 把状态机"提前搬到堆上"，并通过对象池复用：

```csharp
public class StateMachineWrap<T> : IStateMachineWrap 
    where T : IAsyncStateMachine
{
    [StaticField]
    private static readonly Queue<StateMachineWrap<T>> queue = new();

    // 对象池获取
    public static StateMachineWrap<T> Fetch(ref T stateMachine)
    {
        StateMachineWrap<T> stateMachineWrap;
        lock (queue)
        {
            if (!queue.TryDequeue(out stateMachineWrap))
            {
                stateMachineWrap = new StateMachineWrap<T>();  // 池空时 new
            }
        }
        stateMachineWrap.StateMachine = stateMachine;  // 复制值类型状态机到堆上
        return stateMachineWrap;
    }
    
    public void Recycle()
    {
        lock (queue)
        {
            if (queue.Count > 100)  // 最多缓存 100 个
            {
                return;
            }
            this.StateMachine = default;  // 清空状态机引用，防止内存泄漏
            queue.Enqueue(this);
        }
    }
    
    private readonly Action moveNext;  // 预先创建好的委托，不会再分配

    public Action MoveNext => this.moveNext;

    private T StateMachine;

    private StateMachineWrap()
    {
        this.moveNext = this.Run;  // 在构造时创建委托，对象池复用时不再重新创建
    }

    private void Run()
    {
        this.StateMachine.MoveNext();  // 委托给内部状态机
    }
}
```

**关键细节**：委托 `moveNext = this.Run` 是在**构造函数**中创建的，而不是每次 `Fetch` 时。所以对象池中的每个 `StateMachineWrap` 实例都有一个固定的 `Action` 委托，复用时不产生新委托分配。

---

## Fetch 的工作流程

```
调用 Fetch(ref stateMachine)
    │
    ├─ 从对象池取出 StateMachineWrap
    │    └─ 池空 → new StateMachineWrap()
    │              └─ 构造函数中创建 this.moveNext = this.Run
    │
    ├─ stateMachineWrap.StateMachine = stateMachine
    │    └─ 把 struct 值类型复制到 StateMachineWrap 的堆对象中
    │
    └─ 返回 stateMachineWrap
```

现在 `stateMachineWrap.MoveNext`（即 `this.Run`）可以安全地作为委托传递，不会有额外装箱。

---

## Recycle 的关键：清空状态机

```csharp
public void Recycle()
{
    this.StateMachine = default;  // ← 这一行非常重要！
    queue.Enqueue(this);
}
```

为什么要 `StateMachine = default`？

状态机中可能持有对游戏对象的引用（比如 `GameObject`、`Component` 等）。如果不清空，这些引用会阻止 GC 回收那些对象，造成**内存泄漏**。

清空后，这些引用断开，GC 可以正常工作。

---

## 三种 MethodBuilder 的 StateMachineWrap 使用对比

| MethodBuilder | 使用 StateMachineWrap | 说明 |
|---------------|----------------------|------|
| ETAsyncTaskMethodBuilder | ✅ 是 | 完整优化，对象池 |
| AsyncETVoidMethodBuilder | ✅ 是 | 完整优化，对象池 |
| AsyncETTaskCompletedMethodBuilder | ❌ 否 | 直接装箱 |

`AsyncETTaskCompletedMethodBuilder` 没有使用对象池：

```csharp
// AsyncETTaskCompletedMethodBuilder 的实现（简化版）
public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
    ref TAwaiter awaiter, ref TStateMachine stateMachine)
{
    awaiter.UnsafeOnCompleted(stateMachine.MoveNext);  // ← 直接装箱！
}
```

这是一个**合理的妥协**：`ETTaskCompleted` 主要用于"立即完成"的场景，通常不会真正执行到 `AwaitUnsafeOnCompleted`（因为 awaiter.IsCompleted 是 true）。万一需要真正等待的场景极少，性能影响可接受。

---

## 队列容量：100 vs 1000

注意两个对象池容量的差异：

```csharp
// ETTask 的对象池
if (queue.Count > 1000) return;

// StateMachineWrap 的对象池
if (queue.Count > 100) return;
```

ETTask 池容量（1000）更大，因为 ETTask 对象本身极小（几十字节），可以多缓存一些。

StateMachineWrap 池容量（100）较小，因为：
1. `StateMachineWrap<T>` 是泛型类，每种 `T` 都有独立的池
2. 游戏中并发的相同类型状态机数量有限
3. `StateMachineWrap` 内部持有状态机副本，占用内存较多

---

## 验证：如何确认没有 GC？

在 Unity 中可以用以下方式验证 ETTask 是否真的零 GC：

```csharp
// 在一帧内多次创建 ETTask，观察 GC
void Update()
{
    // 开始 GC 追踪
    long gcBefore = GC.GetTotalMemory(false);
    
    for (int i = 0; i < 100; i++)
    {
        RunSomeETTask().Coroutine();
    }
    
    long gcAfter = GC.GetTotalMemory(false);
    
    if (gcAfter > gcBefore)
    {
        Debug.Log($"产生了 {gcAfter - gcBefore} 字节的 GC 分配");
    }
    else
    {
        Debug.Log("零 GC！");
    }
}

private async ETTask RunSomeETTask()
{
    await ETTask.CompletedTask;  // 立即完成的任务
}
```

热身几次（预热对象池）后，理论上应该看到零 GC 分配。

---

## 总结

`AwaiterStatus` 和 `StateMachineWrap` 是 ETTask 框架中两个看似简单却精心设计的组件：

**`AwaiterStatus`**：
- 用三种状态（Pending/Succeeded/Faulted）覆盖全部场景
- 用 `byte` 类型节省内存
- 不含 Cancelled 状态，将取消逻辑外置到 CancellationToken

**`StateMachineWrap<T>`**：
- 解决 async 状态机装箱问题
- 对象池容量 100，按类型独立管理
- 构造时预创建委托，复用时零分配
- Recycle 时清空状态机引用，防止内存泄漏

这两个文件合在一起，是 ETTask 框架"零 GC"承诺的技术底座。每次 `async ETTask` 方法被调用和等待，背后都是这套机制在默默保证性能。
