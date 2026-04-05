---
title: 从零构建 Unity 异步任务框架：设计总结与工程实践
published: 2026-03-31
description: 以技术架构师视角，系统梳理 ETTask 异步框架的完整设计体系，形成可复用的异步编程工程知识地图。
tags: [Unity, 异步编程, 框架设计, 工程实践]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 系列回顾：我们学了什么？

在这个系列的前 9 篇中，我们逐一深入了 ETTask 框架的每个关键文件：

1. **ETTask.cs**：异步任务核心——状态机 + 对象池 + 三字段设计
2. **ETCancellationToken.cs**：取消机制——回调集合 + 置空即取消
3. **ETTaskHelper.cs**：并发工具——WaitAll/WaitAny/GetContextAsync
4. **ETVoid.cs + ETTaskCompleted.cs**：特殊类型——即发即忘和立即完成
5. **AsyncETTaskMethodBuilder.cs**：方法构建器——七步协议
6. **AsyncETTaskCompletedMethodBuilder.cs + AsyncETVoidMethodBuilder.cs**：轻量构建器对比
7. **IAwaiter.cs + StateMachineWrap.cs**：状态枚举和零 GC 技巧
8. **ETTask vs UniTask**：框架设计哲学对比

现在，让我们把这些碎片拼成完整的图景。

---

## ETTask 的完整架构图

```
┌─────────────────────────────────────────────────────────────────┐
│                         业务代码层                                │
│   public async ETTask LoadGameAsync() { ... }                   │
│   public async ETTask<int> CalculateAsync() { ... }             │
└───────────────────────────┬─────────────────────────────────────┘
                            │ async/await 语法
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       C# 编译器生成层                              │
│   <LoadGameAsync>d__1 (状态机 struct)                           │
│   MoveNext() { ... }                                            │
└───────────────────────────┬─────────────────────────────────────┘
                            │ 委托给
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                      MethodBuilder 层                            │
│   ┌──────────────────────────────────────────────────┐          │
│   │ ETAsyncTaskMethodBuilder                         │          │
│   │   Create()       → ETTask.Create(true) [对象池]  │          │
│   │   Start()        → stateMachine.MoveNext()      │          │
│   │   AwaitOnComp()  → StateMachineWrap + 回调注册   │          │
│   │   SetResult()    → tcs.SetResult() + 回收包装   │          │
│   └──────────────────────────────────────────────────┘          │
└───────────────────────────┬─────────────────────────────────────┘
                            │ 操作
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                       核心任务对象层                               │
│   ┌─────────────────────────────────┐                           │
│   │ ETTask (class, 对象池)           │                           │
│   │   state: AwaiterStatus          │                           │
│   │   callback: Action/Exception    │                           │
│   │   Context: object               │ ← Context 链              │
│   │   TaskType: Common/WithContext  │                           │
│   └─────────────────────────────────┘                           │
│                                                                 │
│   ┌────────────────────────┐  ┌──────────────────────────────┐  │
│   │ ETVoid (struct)        │  │ ETTaskCompleted (struct)     │  │
│   │   IsCompleted = true   │  │   IsCompleted = true         │  │
│   │   fire-and-forget 用   │  │   立即完成场景用               │  │
│   └────────────────────────┘  └──────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────────┘
                            │ 配套工具
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                         工具层                                    │
│   ETCancellationToken    WaitAll    WaitAny    GetContextAsync   │
│   StateMachineWrap<T>    AwaiterStatus                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 六大核心设计原则

### 原则一：最小接口

ETTask 只实现 `ICriticalNotifyCompletion` 和自定义的 `IETTask`，不实现 `IDisposable`、`IAwaitable<>` 等 C# 标准接口。保持最小接口意味着更少的约束、更大的自由度。

### 原则二：对象池无处不在

```
ETTask         → Queue<ETTask> (容量 1000)
ETTask<T>      → Queue<ETTask<T>> (容量 1000)
StateMachineWrap<T> → Queue<StateMachineWrap<T>> (容量 100)
```

这三层对象池覆盖了一次异步调用的所有分配点，实现热路径零 GC。

### 原则三：状态机不离开主线程

所有状态机的 `MoveNext()` 都在游戏主线程被调用，没有任何 `SynchronizationContext` 切换逻辑。这消除了线程安全问题，也消除了线程切换开销。

### 原则四：异常不静默

无论是 `ETTask`、`ETVoid` 还是 `ETTaskCompleted`，异常都不会被吞掉——要么传播给 `await` 调用者，要么通过 `ETTask.ExceptionHandler` 全局处理。这避免了调试时最令人头疼的"静默异常"。

### 原则五：三字段即完整任务状态

```csharp
private AwaiterStatus state;    // 任务状态（1字节）
private object callback;        // 回调或异常信息
private bool fromPool;          // 是否来自对象池
```

整个任务状态用三个字段描述，没有多余的状态追踪。这使得对象足够轻量，可以在池中大量缓存。

### 原则六：Context 作为隐式参数

Context 链允许在不修改函数签名的情况下传递"当前实体"信息，这在 ECS 架构中特别有价值——Entity 可以在整个异步调用栈中隐式传递。

---

## 常见错误清单

经过系列文章的学习，总结一份"新手雷区"清单：

### ❌ 错误一：await 后继续操作对象池 Task

```csharp
var task = ETTask.Create(true);
RegisterCallback(task);   // 存了引用
await task;               // task 在 GetResult 里被回收了
task.TaskType = ...;      // ❌ 操作的可能是别人的 task！
```

**正确做法**：使用后立即置空引用。

### ❌ 错误二：不检查取消直接返回

```csharp
public async ETTask ProcessAsync(ETCancellationToken token)
{
    await HeavyWorkAsync();
    // ❌ 忘记检查取消
    await MoreWorkAsync();
    // ❌ 忘记检查取消
    ApplyResult();  // 此时对象可能已销毁！
}
```

**正确做法**：每个 await 后检查一次。

### ❌ 错误三：同一 Task 多次 SetResult

```csharp
var task = ETTask.Create(true);
task.SetResult();  // ✅
task.SetResult();  // ❌ InvalidOperationException
```

**正确做法**：SetResult 前将引用置空。

### ❌ 错误四：在 fire-and-forget 中期待异常传播

```csharp
try
{
    someTask.Coroutine();   // ❌ 这里的异常不会被 catch
}
catch (Exception e)
{
    Debug.Log(e);
}

// ✅ 正确：await 后才能 catch
try
{
    await someTask;
}
catch (Exception e)
{
    Debug.Log(e);
}
```

### ❌ 错误五：在不适合的地方用 ETVoid 方法

```csharp
// ❌ 在框架外的业务代码中定义 ETVoid 方法
public async ETVoid DoImportantWork()
{
    // 调用者无法等待这个方法，无法知道何时完成
}

// ✅ 使用 ETTask，让调用者可以 await
public async ETTask DoImportantWork()
{
    // 如果不想等，调用者用 .Coroutine()
}
```

---

## 实战项目：一个完整的资源加载管理器

把所有知识综合起来，实现一个迷你资源加载管理器：

```csharp
public class ResourceManager
{
    private Dictionary<string, byte[]> _cache = new();
    
    // 主要加载入口
    public async ETTask<T> LoadAsync<T>(string path, ETCancellationToken cancelToken = null) 
        where T : UnityEngine.Object
    {
        // 1. 检查缓存（同步快路径）
        if (_cache.TryGetValue(path, out var cached))
        {
            return cached as T;
        }
        
        if (cancelToken.IsCancel()) return null;
        
        // 2. 真正的异步加载
        var handle = Addressables.LoadAssetAsync<T>(path);
        await handle;  // ETTask 通过扩展方法 await AsyncOperationHandle
        
        if (cancelToken.IsCancel())
        {
            Addressables.Release(handle);
            return null;
        }
        
        // 3. 存入缓存
        var result = handle.Result;
        // _cache[path] = result 的序列化版本...
        
        return result;
    }
    
    // 并发批量加载
    public async ETTask PreloadAsync(string[] paths, 
        Action<float> onProgress, 
        ETCancellationToken cancelToken)
    {
        int loaded = 0;
        int total = paths.Length;
        
        // 分批加载（每批 5 个并发）
        for (int i = 0; i < total; i += 5)
        {
            if (cancelToken.IsCancel()) return;
            
            var batch = paths.Skip(i).Take(5).ToArray();
            var batchTasks = batch.Select(p => LoadAsync<UnityEngine.Object>(p, cancelToken)).ToArray();
            
            await ETTaskHelper.WaitAll(batchTasks.Cast<ETTask>().ToList());
            
            loaded = Math.Min(loaded + batch.Length, total);
            onProgress?.Invoke((float)loaded / total);
        }
    }
}

// 使用示例
public class GameLoader : MonoBehaviour
{
    private ETCancellationToken _loadToken;
    
    private async void Start()
    {
        _loadToken = new ETCancellationToken();
        
        var rm = new ResourceManager();
        
        // 加载进度条
        await rm.PreloadAsync(
            new[] { "UI/MainMenu", "UI/LoadingScreen", "Characters/Hero" },
            progress => LoadingUI.SetProgress(progress),
            _loadToken
        );
        
        if (_loadToken.IsCancel()) return;
        
        // 加载完成，进入游戏
        SceneManager.LoadSceneAsync("MainScene").GetAwaiter();
    }
    
    private void OnDestroy()
    {
        _loadToken?.Cancel();
    }
}
```

---

## 给团队新人的学习路线图

**第一周：掌握使用**
- 能正确使用 `async ETTask` 和 `await`
- 知道什么时候用 `.Coroutine()`
- 养成 await 后检查 `IsCancel()` 的习惯

**第二周：理解原理**
- 阅读 ETTask.cs 全文
- 在 IDE 中单步调试一个 await 语句，观察状态机的 MoveNext 调用
- 理解对象池的 Create/Recycle 时机

**第三周：掌握并发**
- 用 WaitAll 实现多资源并行加载
- 用 WaitAny 实现超时机制
- 用 ETCancellationToken 实现场景切换时的操作取消

**第四周：贡献框架**
- 尝试为框架添加 `WaitUntil` 方法
- 理解 MethodBuilder 的七步协议
- 能够解释 StateMachineWrap 为什么必要

---

## 框架设计的第一性原理回顾

**问题**：游戏主循环中的非阻塞异步操作，需要什么？

1. **语法友好**：能用 `async/await`，而不是回调地狱 → `[AsyncMethodBuilder]` 接入编译器
2. **零 GC**：高频调用不能有堆分配 → 对象池（ETTask + StateMachineWrap）
3. **无线程切换**：主线程操作 Unity 对象 → 回调直接在主线程执行
4. **异常安全**：不静默吞掉异常 → ExceptionDispatchInfo + ExceptionHandler
5. **取消支持**：操作可以被中止 → ETCancellationToken
6. **上下文传播**：不改函数签名传递实体 → Context 链

每一个设计决定都直接对应一个明确的需求。这就是**第一性原理**驱动的框架设计。

---

## 结语

ETTask 是一个小而美的工程作品。500 行代码，解决了 Unity 游戏开发中异步编程最核心的问题，没有一行多余的代码。

对于刚入行的新手，学习这套框架不只是学一个工具——更是学习一种思维方式：**从需求出发，用最简单的方案解决问题，拒绝过度设计**。

这比学会任何具体的 API 都更有价值。
