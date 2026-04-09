---
title: ETTask核心实现原理与对象池复用机制深度剖析
published: 2026-04-09
description: 从源码角度全面解析 ETTask 与 ETTask<T> 的设计原理：TaskType 上下文链传递、对象池 Queue<ETTask> 复用策略、AwaiterStatus 三态状态机、SetResult/SetException 回调分发机制，以及 IETTask 接口在上下文透传中的核心作用。
tags: [Unity, ETTask, 异步编程, 对象池, 框架底层, ECS]
category: 框架底层
encryptedKey:henhaoji123
---

## 前言

在游戏框架的异步系统中，`ETTask` 是整个协程体系的核心载体。不同于 C# 标准库的 `Task`，`ETTask` 是一个完全自研的、面向游戏运行时特性深度优化的任务类型。它既是 `await` 的目标对象（Awaiter），也是 `async` 方法的返回类型（通过自定义 `AsyncMethodBuilder`），还承担了上下文（Context）在协程链路上的透传职责。

本文基于 `ETTask.cs` 中 429 行源码，从以下四个维度展开分析：

1. `IETTask` 接口与 `TaskType` 枚举的设计目的
2. `ETTask` / `ETTask<T>` 对象池的实现细节与注意事项
3. 三态状态机（Pending / Succeeded / Faulted）与回调分发
4. Context 上下文在协程链中的传播算法

---

## 一、IETTask 接口与 TaskType 枚举

### 接口定义

```csharp
public interface IETTask
{
    public TaskType TaskType { get; set; }
    public object Context { get; set; }
}
```

`IETTask` 只有两个属性，却是整个上下文传播机制的关键契约：

| 属性 | 类型 | 作用 |
|------|------|------|
| `TaskType` | `TaskType` | 标识当前节点在链路中的角色 |
| `Context` | `object` | 承载上下文（取消令牌、作用域对象等） |

### TaskType 枚举

```csharp
public enum TaskType : byte
{
    Common,      // 普通任务，Context 可随意穿越
    WithContext, // 调用方主动注入了上下文，传播到此为止
    ContextTask, // 特殊的 ETTask<object>，专门用于异步获取上下文
}
```

这三个值与 `SetContext` 扩展方法配合，构成了一套**单链表向下传播、遇到标记节点停止**的上下文路由机制（详见第四节）。

---

## 二、ETTask 对象池机制

### 为什么需要对象池？

游戏每帧可能产生数以千计的短暂协程（等待网络响应、等待定时器、等待某个组件 Awake），如果每次 `Create` 都在堆上分配新对象，GC 压力将非常显著。对象池把"分配 + 回收"变成了"队列入队 + 出队"，大幅降低 GC 频率。

### 源码实现

```csharp
[StaticField]
private static readonly Queue<ETTask> queue = new();

public static ETTask Create(bool fromPool = false)
{
    if (!fromPool)
    {
        return new ETTask();
    }
    ETTask task;
    lock (queue)
    {
        if (!queue.TryDequeue(out task))
        {
            return new ETTask() { fromPool = true };
        }
    }
    return task;
}

private void Recycle()
{
    if (!this.fromPool) return;
    
    this.state = AwaiterStatus.Pending;
    this.callback = null;
    this.Context = null;
    this.TaskType = TaskType.Common;
    lock (queue)
    {
        if (queue.Count > 1000)
        {
            return; // 池满了，直接丢弃，让 GC 回收
        }
        queue.Enqueue(this);
    }
}
```

### 关键设计细节

**① `fromPool` 标志**

`fromPool` 是 `private bool`，只有通过 `Create(fromPool: true)` 创建的对象才会在 `GetResult` 时触发 `Recycle`。这是"选择性池化"的体现——调用方自己决定这个任务是否参与对象池生命周期。

**② 队列上限 1000**

```csharp
if (queue.Count > 1000)
{
    return;
}
```

防止极端情况下（大量任务快速完成）队列无限增长，耗尽内存。超过上限的回收对象直接被 GC 管理，不会影响正常运行。

**③ `lock (queue)` 线程安全**

`Queue<T>` 不是线程安全的，所有入队/出队操作都用 `lock(queue)` 包裹。游戏框架通常运行在主线程，但 `ETTask` 支持在后台线程等待，所以锁是必要的。

**④ 池中的重置顺序**

`Recycle` 中的重置非常完整：
- `state` → 回到 `Pending`
- `callback` → 清空（防止上一轮回调被下一轮调用）
- `Context` → 清空
- `TaskType` → 回到 `Common`

任何一项遗漏都会导致跨周期的数据污染。

**⑤ 关于 `CompletedTask` 单例**

```csharp
[StaticField]
public static ETTask CompletedTask
{
    get { return completedTask ??= new ETTask() { state = AwaiterStatus.Succeeded }; }
}
```

对于不需要等待的同步完成场景（如已经完成的操作），直接返回这个共享的 `Succeeded` 对象，连池都不用进。

---

## 三、三态状态机与回调分发

### AwaiterStatus 三态

```csharp
// 来自 IAwaiter.cs
public enum AwaiterStatus : byte
{
    Pending,    // 挂起中，等待结果
    Succeeded,  // 成功完成
    Faulted,    // 异常完成
}
```

`ETTask` 内部用一个 `private AwaiterStatus state` 字段维护当前状态，初始为 `Pending`。

### SetResult 成功路径

```csharp
public void SetResult()
{
    if (this.state != AwaiterStatus.Pending)
    {
        throw new InvalidOperationException("TaskT_TransitionToFinal_AlreadyCompleted");
    }
    this.state = AwaiterStatus.Succeeded;
    Action c = this.callback as Action;
    this.callback = null;  // 先置空
    c?.Invoke();           // 再调用
}
```

**先将 `callback` 置空再调用**是防重入的经典手法：如果 `c.Invoke()` 过程中又触发了对同一个 ETTask 的 `SetResult`，此时 `callback` 已经是 `null`，不会二次执行。

### SetException 异常路径

```csharp
public void SetException(Exception e)
{
    if (this.state != AwaiterStatus.Pending)
    {
        throw new InvalidOperationException("TaskT_TransitionToFinal_AlreadyCompleted");
    }
    this.state = AwaiterStatus.Faulted;
    Action c = this.callback as Action;
    this.callback = ExceptionDispatchInfo.Capture(e);  // 替换为异常信息
    c?.Invoke();
}
```

注意这里 `callback` 字段被复用为两种用途：
- 任务 `Pending` 时，存放的是 `Action`（状态机的 `MoveNext`）
- 任务 `Faulted` 后，存放的是 `ExceptionDispatchInfo`

`ExceptionDispatchInfo.Capture(e)` 保留了原始异常的堆栈信息，在 `GetResult` 时调用 `.Throw()` 重新抛出，让异常看起来像是从 `await` 点发生的，而不是从深层异步代码中冒出来的。

### GetResult 消费路径

```csharp
public void GetResult()
{
    switch (this.state)
    {
        case AwaiterStatus.Succeeded:
            this.Recycle();  // 成功则回收
            break;
        case AwaiterStatus.Faulted:
            ExceptionDispatchInfo c = this.callback as ExceptionDispatchInfo;
            this.callback = null;
            this.Recycle();  // 先回收...
            c?.Throw();      // ...再抛出（异常会携带原始堆栈）
            break;
        default:
            throw new NotSupportedException("ETTask does not allow call GetResult directly when task not completed.");
    }
}
```

`GetResult` 是编译器生成的 `await` 代码的最终调用点。对于 `Faulted` 状态，先回收（把任务放回池中）再抛出异常，这样即使异常被 catch 住，也不会造成内存泄漏。

---

## 四、Context 上下文透传算法

### 设计动机

游戏框架中有一类常见需求：**把 Entity 实体（或取消令牌）透明地传递给整个协程调用链**，不需要每个 `async` 方法都手动添加参数。这就是 `Context` 机制的价值。

### IETTaskExtension.SetContext 核心算法

```csharp
internal static void SetContext(this IETTask task, object context)
{
    while (true)
    {
        if (task.TaskType == TaskType.ContextTask)
        {
            // 遇到 ContextTask（ETTaskHelper.GetContextAsync 内部创建），
            // 直接 SetResult(context)，让 await 返回 context 对象
            ((ETTask<object>)task).SetResult(context);
            break;
        }

        // 普通节点：记录当前 context，同时把原有 Context 作为子节点向下传递
        task.TaskType = TaskType.WithContext;
        object child = task.Context;   // 原来的子任务
        task.Context = context;        // 写入上下文
        task = child as IETTask;       // 继续向下
        if (task == null) break;       // 链条到头了
        
        // 遇到已经注入过 context 的节点，停止（不覆盖更内层的 WithContext）
        if (task.TaskType == TaskType.WithContext) break;
    }
}
```

### 链式传播示意图

```
[外层 ETTask]  TaskType=WithContext, Context=<CancellationToken>
       ↓ (Context 字段作为 child 链接)
[中层 ETTask]  TaskType=WithContext, Context=<CancellationToken>
       ↓
[内层 ETTaskHelper.GetContextAsync 内部的 ETTask<object>]
       TaskType=ContextTask → SetResult(<CancellationToken>)
       → await 返回值就是传入的 context
```

### 使用模式

```csharp
// 外层发起调用，注入 cancellationToken 作为上下文
async ETTask DoSomethingAsync(ETCancellationToken token)
{
    await someTask.WithContext(token);
}

// 内层消费上下文，不需要 token 参数
async ETTask InnerAsync()
{
    // 等待上下文从链路中流下来
    ETCancellationToken token = await ETTaskHelper.GetContextAsync<ETCancellationToken>();
    if (token.IsCancel()) return;
    // ...
}
```

### NewContext 换上下文

```csharp
public async ETTask NewContext(object context)
{
    this.SetContext(context);
    await this;
}
```

`NewContext` 允许在 `await` 某个任务的同时，**替换**掉注入的上下文。适用于需要在协程中间切换作用域的场景（例如进入新的 Entity 作用域）。

### Coroutine 与 WithContext 的区别

```csharp
// 无上下文，fire-and-forget
public void Coroutine()
{
    this.SetContext(null);   // 注入 null，清空下游 context
    InnerCoroutine().Coroutine();
}

// 有上下文，fire-and-forget
public void WithContext(object context)
{
    this.SetContext(context);
    InnerCoroutine().Coroutine();
}
```

两者都是"即发即忘"（不等待结果），区别在于是否传递上下文。调用 `.Coroutine()` 后，返回值被丢弃，异常会通过 `ETTask.ExceptionHandler` 静态委托分发。

---

## 五、ETTask<T>：带返回值的泛型版本

`ETTask<T>` 与 `ETTask` 结构几乎相同，主要差异在 `GetResult` 和 `SetResult`：

```csharp
public T GetResult()
{
    switch (this.state)
    {
        case AwaiterStatus.Succeeded:
            T v = this.value;  // 先取出值
            this.Recycle();     // 再回收
            return v;
        case AwaiterStatus.Faulted:
            // 同 ETTask，先回收再抛出
            ...
    }
}

public void SetResult(T result)
{
    // 同 ETTask，额外存储 this.value = result
    this.state = AwaiterStatus.Succeeded;
    this.value = result;
    Action c = this.callback as Action;
    this.callback = null;
    c?.Invoke();
}
```

**注意**：`Recycle` 时会 `this.value = default`，确保对象还给池后不持有引用，防止 GC 无法回收 `T` 类型的对象。

---

## 六、完整生命周期流程图

```
调用方：
  ETTask task = ETTask.Create(fromPool: true)
                          │
                          ▼
                  state = Pending
                  callback = null
                          │
    await task ──────────▶│ 状态机调用 UnsafeOnCompleted(MoveNext)
                          │ callback = MoveNext Action
                          │
    某处调用：
    task.SetResult()  ───▶│ state = Succeeded
                          │ 取出 callback（MoveNext）
                          │ callback = null（防重入）
                          │ MoveNext()
                          │
    编译器生成的代码：
    GetResult()  ─────────▶│ state == Succeeded → Recycle()
                            │ 重置字段，入队 queue
                            │
                    ┌───────┴─────────┐
                    │ 下次 Create(true) │
                    │ TryDequeue 复用  │
                    └──────────────────┘
```

---

## 七、工程使用建议

### ✅ 正确的对象池使用姿势

```csharp
// 1. 创建时明确标记 fromPool=true
ETTask<int> tcs = ETTask<int>.Create(fromPool: true);

// 2. 在 await 之前保存引用，await 之后不再操作 tcs！
int result = await tcs;
// ❌ 下面这行是危险的，tcs 可能已被其他协程复用
// tcs.SetResult(xxx); 

// 3. SetResult 前将外部引用置空
private ETTask<int> _waitTask;
async ETTask WaitForResult()
{
    _waitTask = ETTask<int>.Create(fromPool: true);
    int val = await _waitTask;
    // _waitTask 已被 Recycle，勿再访问
}
void OnResultReady(int val)
{
    ETTask<int> t = _waitTask;
    _waitTask = null;   // 先置空外部引用
    t?.SetResult(val);  // 再 SetResult
}
```

### ❌ 常见错误

```csharp
// 错误1：await 之后继续操作 task
ETTask task = ETTask.Create(true);
await task;
task.SetResult(); // 危险！task 已被回收并可能分配给别人

// 错误2：多次 SetResult 同一个 task
task.SetResult(); // OK
task.SetResult(); // 抛 InvalidOperationException

// 错误3：不用 fromPool 创建的 task 调用 Recycle
// → Recycle 内部会检查 fromPool，所以实际上只是空操作，但逻辑意图混乱
```

---

## 八、与 C# Task 的对比

| 特性 | C# Task | ETTask |
|------|---------|--------|
| 分配位置 | 堆（GC 管理） | 可选对象池（减少 GC） |
| 返回值版本 | `Task<T>` | `ETTask<T>` |
| 即发即忘 | `Task.Run` + 不 await | `.Coroutine()` |
| 上下文传递 | `AsyncLocal<T>` | `Context` 字段 + `SetContext` 链 |
| 异常处理 | `AggregateException` | `ExceptionDispatchInfo`（保留堆栈） |
| 多任务等待 | `Task.WhenAll/WhenAny` | `ETTaskHelper.WaitAll/WaitAny` |
| 线程切换 | `ConfigureAwait(false)` | 天然单线程，无需配置 |

---

## 总结

`ETTask` 是游戏框架异步体系的基石。它通过以下几个核心设计达到了高性能与高可用性的平衡：

1. **对象池（Queue + lock + 上限 1000）**：显著降低高频协程场景的 GC 压力
2. **三态状态机（Pending/Succeeded/Faulted）+ callback 复用**：最小化字段数量，单个对象体积极小
3. **ExceptionDispatchInfo**：保留异常堆栈，调试体验与标准 Task 一致
4. **IETTask + TaskType + Context**：零参数透传上下文，让深层协程无感知地获取 Entity/CancellationToken
5. **CompletedTask 单例**：同步完成场景零分配

对于刚接触 ET 框架的开发者，最重要的一条原则是：**开启 `fromPool` 后，`await` 就是所有权转移的边界，之后不要再碰那个引用**。
