---
title: 04 ETTask 异步编程框架
published: 2024-01-01
description: "04 ETTask 异步编程框架 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: ET框架
draft: false
encryptedKey: henhaoji123
---

# 04 ETTask 异步编程框架

> 面向刚入行的毕业生 · 技术架构师出品

---

## 1. 系统概述

`ETTask` 是本框架自定义的异步任务类型，功能上类似于 C# 原生的 `Task`/`Task<T>`，但专为游戏逻辑场景做了深度优化：

- **零 GC 对象池**：所有 ETTask 可从池中复用，极大减少 GC 压力
- **单线程友好**：专为主线程执行设计，无锁竞争风险
- **Context 传播**：ETTask 链上支持透传取消令牌（ETCancellationToken）
- **自定义状态机**：通过 `[AsyncMethodBuilder]` 接管 C# 编译器的 async/await 机制

**核心文件**：
- `X:\UnityProj\Assets\Scripts\Core\ETTask\ETTask.cs`
- `X:\UnityProj\Assets\Scripts\Core\ETTask\AsyncETTaskMethodBuilder.cs`
- `X:\UnityProj\Assets\Scripts\Core\ETTask\ETCancellationToken.cs`
- `X:\UnityProj\Assets\Scripts\Core\ETTask\ETTaskHelper.cs`

---

## 2. 架构设计

### 2.1 类型体系

```
IETTask（接口）
├── ETTask        [AsyncMethodBuilder(ETAsyncTaskMethodBuilder)]    ← 无返回值异步任务
├── ETTask<T>     [AsyncMethodBuilder(ETAsyncTaskMethodBuilder<T>)] ← 有返回值异步任务
└── ETVoid        ← fire-and-forget 模式（不可 await）
ETTaskCompleted   ← 预先完成的 Task，等价于 Task.CompletedTask
```

### 2.2 ETTask 状态机

```
ETTask 内部状态（AwaiterStatus）：
    Pending   → 等待中（初始状态）
    Succeeded → 已成功完成
    Faulted   → 异常终止

转换触发：
    SetResult()    → Pending → Succeeded → 触发 callback（继续执行协程）
    SetException() → Pending → Faulted   → 触发 callback（传递异常）
    GetResult()    → 如果 Succeeded，回收自身；如果 Faulted，重抛异常
```

### 2.3 对象池机制

```csharp
// ETTask 对象池（每个类型独立一个队列）
private static readonly Queue<ETTask> queue = new();

// 最多缓存 1000 个（防止内存泄漏）
if (queue.Count > 1000) return;
queue.Enqueue(this);
```

这个设计的关键约束是：**await 之后不能再持有 ETTask 引用**，因为它可能已经回收并被新的 await 使用。

### 2.4 Context 传播链

```
ETTask A  ──→  ETTask B  ──→  ETTask C (ContextTask)
  Context         Context          SetResult(context)
    │               │                    ↑
    └── 传播 ────────┘                   │
                                   GetContextAsync() 取回
```

这个机制允许在整条 async 调用链上传递任意 context 对象（如 ETCancellationToken），无需在每个方法签名中显式传递参数。

---

## 3. 核心代码展示

### 3.1 ETTask 基本结构

```csharp
// X:\UnityProj\Assets\Scripts\Core\ETTask\ETTask.cs

[AsyncMethodBuilder(typeof(ETAsyncTaskMethodBuilder))]
public class ETTask : ICriticalNotifyCompletion, IETTask
{
    // 对象池
    private static readonly Queue<ETTask> queue = new();
    private bool fromPool;

    // 状态机核心字段
    private AwaiterStatus state;  // Pending / Succeeded / Faulted
    private object callback;      // Action（继续回调）或 ExceptionDispatchInfo（异常）

    // Context 传播
    public TaskType TaskType { get; set; }  // Common / WithContext / ContextTask
    public object Context { get; set; }

    // 创建 ETTask（fromPool=true 时启用对象池）
    public static ETTask Create(bool fromPool = false)
    {
        if (!fromPool) return new ETTask();
        ETTask task;
        lock (queue)
        {
            if (!queue.TryDequeue(out task))
                return new ETTask() { fromPool = true };
        }
        return task;
    }

    // GetResult：await 完成后由编译器调用
    public void GetResult()
    {
        switch (this.state)
        {
            case AwaiterStatus.Succeeded:
                this.Recycle();  // 回收到对象池
                break;
            case AwaiterStatus.Faulted:
                ExceptionDispatchInfo c = this.callback as ExceptionDispatchInfo;
                this.callback = null;
                this.Recycle();
                c?.Throw();  // 重抛原始异常（保留调用栈）
                break;
            default:
                throw new NotSupportedException("ETTask does not allow call GetResult directly...");
        }
    }

    // SetResult：异步操作完成时调用
    public void SetResult()
    {
        if (this.state != AwaiterStatus.Pending)
            throw new InvalidOperationException("TaskT_TransitionToFinal_AlreadyCompleted");

        this.state = AwaiterStatus.Succeeded;
        Action c = this.callback as Action;
        this.callback = null;
        c?.Invoke();  // 唤醒等待的协程
    }
}
```

### 3.2 自定义方法构建器

C# 编译器在遇到 `async ETTask` 方法时，会使用 `ETAsyncTaskMethodBuilder` 来构建状态机：

```csharp
// X:\UnityProj\Assets\Scripts\Core\ETTask\AsyncETTaskMethodBuilder.cs

public struct ETAsyncTaskMethodBuilder
{
    private IStateMachineWrap iStateMachineWrap;  // 状态机包装（来自对象池）
    private ETTask tcs;                            // 对外暴露的 Task

    // 1. 静态工厂
    public static ETAsyncTaskMethodBuilder Create()
    {
        ETAsyncTaskMethodBuilder builder = new() { tcs = ETTask.Create(true) };
        return builder;
    }

    // 2. 对外暴露的 Task
    public ETTask Task => this.tcs;

    // 3. 异步方法正常返回时
    public void SetResult()
    {
        if (this.iStateMachineWrap != null)
        {
            this.iStateMachineWrap.Recycle();  // 状态机也回收到对象池
            this.iStateMachineWrap = null;
        }
        this.tcs.SetResult();
    }

    // 4. await 某个 awaiter 时（UnsafeOnCompleted 是关键路径）
    public void AwaitUnsafeOnCompleted<TAwaiter, TStateMachine>(
        ref TAwaiter awaiter, ref TStateMachine stateMachine)
        where TAwaiter : ICriticalNotifyCompletion
        where TStateMachine : IAsyncStateMachine
    {
        // 状态机按需从对象池获取（延迟分配）
        this.iStateMachineWrap ??= StateMachineWrap<TStateMachine>.Fetch(ref stateMachine);
        awaiter.UnsafeOnCompleted(this.iStateMachineWrap.MoveNext);

        // Context 传播逻辑
        if (awaiter is not IETTask task) return;
        if (this.tcs.TaskType == TaskType.WithContext)
        {
            task.SetContext(this.tcs.Context);
            return;
        }
        this.tcs.Context = task;  // 记录 await 的下游 task，形成传播链
    }
}
```

### 3.3 fire-and-forget 模式（Coroutine()）

```csharp
// 场景：启动一个异步协程，不等待其完成
someAsyncMethod().Coroutine();

// 内部实现
public void Coroutine()
{
    this.SetContext(null);   // 清除 context 链
    InnerCoroutine().Coroutine();
}

private async ETVoid InnerCoroutine()
{
    await this;  // 等待自身完成，任何异常由 ExceptionHandler 处理
}

// ETVoid：fire-and-forget 的异步任务，不能被 await
// 它通过 Coroutine() 扩展方法启动后就"放开不管"
```

### 3.4 ETCancellationToken —— 异步取消机制

```csharp
// X:\UnityProj\Assets\Scripts\Core\ETTask\ETCancellationToken.cs

public class ETCancellationToken
{
    private HashSet<Action> actions = new();

    // 注册取消回调
    public void Add(Action callback) => this.actions.Add(callback);
    public void Remove(Action callback) => this.actions?.Remove(callback);

    // 是否已被取消（actions 被置空则表示已取消）
    public bool IsDispose() => this.actions == null;

    // 取消：执行所有注册的回调
    public void Cancel()
    {
        if (this.actions == null) return;
        this.Invoke();
    }

    private void Invoke()
    {
        HashSet<Action> runActions = this.actions;
        this.actions = null;  // ← 先置空，防止重入
        foreach (Action action in runActions)
            action.Invoke();
    }
}
```

### 3.5 ETTaskHelper —— 并发辅助工具

```csharp
// X:\UnityProj\Assets\Scripts\Core\ETTask\ETTaskHelper.cs

// WaitAll：等待所有 Task 完成（类似 Task.WhenAll）
public static async ETTask WaitAll(List<ETTask> tasks)
{
    if (tasks.Count == 0) return;

    CoroutineBlocker coroutineBlocker = new CoroutineBlocker(tasks.Count);
    foreach (ETTask task in tasks)
        coroutineBlocker.RunSubCoroutineAsync(task).Coroutine();  // 并发启动

    await coroutineBlocker.WaitAsync();  // 等待全部完成
}

// WaitAny：等待任意一个 Task 完成（类似 Task.WhenAny）
public static async ETTask WaitAny(List<ETTask> tasks)
{
    if (tasks.Count == 0) return;
    CoroutineBlocker coroutineBlocker = new CoroutineBlocker(1);  // ← count=1，有一个完成即可
    foreach (ETTask task in tasks)
        coroutineBlocker.RunSubCoroutineAsync(task).Coroutine();
    await coroutineBlocker.WaitAsync();
}
```

---

## 4. async/await 在 ETTask 中的工作原理

理解这部分需要一点点 C# 编译器知识，但我来用通俗语言解释：

### 4.1 编译器做了什么

当你写：
```csharp
public async ETTask LoadData()
{
    await FetchFromServer();  // 等待网络请求
    ProcessData();            // 处理数据
}
```

编译器会把它转换成一个状态机类，大致相当于：
```csharp
// 伪代码，实际更复杂
public ETTask LoadData()
{
    var builder = ETAsyncTaskMethodBuilder.Create();  // 创建 ETTask
    var stateMachine = new LoadData_StateMachine(builder);
    stateMachine.MoveNext();  // 开始执行第一段
    return builder.Task;       // 返回 ETTask，调用方可以 await 它
}

// 状态机的 MoveNext 分段执行
void MoveNext()
{
    if (state == 0)
    {
        var awaiter = FetchFromServer().GetAwaiter();
        if (!awaiter.IsCompleted)
        {
            state = 1;
            // 注册回调：FetchFromServer 完成后继续执行
            builder.AwaitUnsafeOnCompleted(ref awaiter, ref this);
            return;  // 暂时返回，释放调用栈
        }
    }
    if (state == 1)
    {
        ProcessData();       // 第二段代码
        builder.SetResult(); // 通知 LoadData 完成
    }
}
```

### 4.2 为什么比 Unity Coroutine 好

| 对比项 | Unity Coroutine | ETTask |
|---|---|---|
| 返回值 | 不支持 | `ETTask<T>` 支持任意返回值 |
| 异常处理 | 异常会吞掉 | 异常正常传播，可 try/catch |
| 取消机制 | 需要手动 StopCoroutine | ETCancellationToken |
| 嵌套调用 | 需要 StartCoroutine 套 StartCoroutine | 直接 `await` 嵌套 |
| 性能 | 每 yield 都有 GC | 对象池复用，零 GC |
| 编译时检查 | 运行时才知道是否有误 | 编译时类型检查 |

---

## 5. 实际使用示例

### 5.1 基础异步方法

```csharp
// 异步加载配置
public async ETTask LoadConfigAsync(string configName)
{
    // await 资源加载
    var bytes = await ResourceManager.LoadAsync(configName);
    // await 完成后继续处理
    ConfigTable.Add(configName, Parse(bytes));
}
```

### 5.2 带取消令牌的异步操作

```csharp
public class PlayerMoveComponent : Entity, IAwake, IDestroy
{
    private ETCancellationToken cancelToken;

    // Awake 时启动移动协程
    public void StartMove(Vector3 target)
    {
        cancelToken?.Cancel();  // 取消上一次移动
        cancelToken = new ETCancellationToken();
        MoveToAsync(target, cancelToken).Coroutine();
    }

    private async ETTask MoveToAsync(Vector3 target, ETCancellationToken token)
    {
        while (!isArrived)
        {
            if (token.IsDispose()) return;  // 已被取消
            MoveOneStep(target);
            await TimerComponent.Instance.WaitFrameAsync(1);
        }
    }

    // Destroy 时取消所有协程
    public void OnDestroy()
    {
        cancelToken?.Cancel();
    }
}
```

### 5.3 并发等待多个异步操作

```csharp
public async ETTask InitAsync()
{
    // 并发加载，全部完成后继续
    using var tasks = ListComponent<ETTask>.Create();
    tasks.Add(LoadUIAsync());
    tasks.Add(LoadMapAsync());
    tasks.Add(LoadConfigAsync());

    await ETTaskHelper.WaitAll(tasks);  // 等待三个都完成

    // 或者等任意一个完成
    await ETTaskHelper.WaitAny(tasks);
}
```

### 5.4 Context 传播取消令牌（高级用法）

```csharp
// 将 cancellationToken 注入调用链，无需每个方法都传参
public async ETTask<bool> SomeDeepMethod()
{
    // 从 context 链中取回 token
    ETCancellationToken token = await ETTaskHelper.GetContextAsync<ETCancellationToken>();
    if (token.IsDispose()) return false;
    // ...
}
```

---

## 6. 与原版 ET 框架的差异

| 对比项 | 原版 ET | 本项目 |
|---|---|---|
| 基本机制 | 相同 | 相同 |
| TaskType | 有（Common/WithContext/ContextTask） | 相同 |
| `ExceptionHandler` | 静态字段 | 相同，用 `[StaticField]` 标记便于代码分析工具识别 |
| 状态机包装 | `StateMachineWrap<T>` 对象池 | 相同 |
| `ETVoid` | 有 | 有，fire-and-forget 模式 |
| 对象池上限 | 1000 | 相同（lock 保护） |

---

## 7. 常见问题与最佳实践

### Q1：什么时候用 `.Coroutine()` 而不是 `await`？

```csharp
// 需要"启动但不等待"时用 .Coroutine()
someAsyncMethod().Coroutine();  // fire-and-forget

// 需要等待结果时用 await
var result = await someAsyncMethod();
```

**注意**：`.Coroutine()` 不会传播异常到调用方，异常由 `ETTask.ExceptionHandler` 处理。

### Q2：对象池复用的危险操作

```csharp
// ❌ 危险：保存 ETTask 引用后继续使用
ETTask task = ETTask.Create(true);
// ... 某处 await task ...
task.SetResult();  // ← 此时 task 可能已被回收并给了别人！

// ✅ 正确：SetResult 之前先清空引用
ETTask t = this.task;
this.task = null;     // ← 先置空
t?.SetResult();       // ← 再 SetResult
```

### Q3：如何调试异步方法？

1. 在 VS/Rider 中设置断点，async 方法的断点会在 MoveNext 时命中
2. 开启 `[DebuggerHidden]` 的方法（GetResult、SetResult等）在调试时会被跳过，不影响业务断点
3. 如果异步异常被吞掉，检查 `ETTask.ExceptionHandler` 是否正确注册了日志处理

### Q4：ETTask 和 UniTask 的关系？

两者设计理念相同（自定义 AsyncMethodBuilder + 对象池），但 ETTask 是 ET 框架自带的轻量实现，而 UniTask 是功能更完整的第三方库。本项目使用 ETTask 是为了与框架深度集成（如 Context 传播机制）。

---

## 8. 总结

ETTask 是本框架异步编程的基础设施，它通过：

1. **自定义 AsyncMethodBuilder** 接管编译器的状态机生成
2. **对象池 + 状态重置** 实现零 GC 的 async/await
3. **Context 传播链** 优雅地解决取消令牌的跨层传递问题

作为新手，最重要的实践守则是：**await 之后不要再操作 ETTask 对象**，以及**在所有异步回调入口检查 `entity.IsDisposed`**。
