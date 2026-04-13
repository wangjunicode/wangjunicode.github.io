---
title: 游戏框架并发协程工具集ETTaskHelper与即完成任务结构设计解析
published: 2026-04-05
description: 深度解析 ETTaskHelper 工具类提供的并发控制原语（WhenAll、WhenAny、Delay 等）以及即完成任务（ETTaskCompleted）的设计动机与实现细节。
tags: [Unity, ETTask, 异步编程, 并发控制, 协程, 工具类]
category: 框架底层
draft: false
encryptedKey: henhaoji123
---

# 游戏框架并发协程工具集 ETTaskHelper 与即完成任务结构设计解析

游戏逻辑中充满并发场景：等待多个资源同时加载完成、等待任意一个条件满足就继续、带超时的异步操作……ETTaskHelper 为这些场景提供了一套简洁的并发控制原语。与此同时，`ETTaskCompleted` 作为"即完成任务"的轻量结构，消除了大量不必要的状态机分配。本文深入解析二者的设计。

---

## 一、ETTaskHelper 核心工具方法

### 1.1 WhenAll —— 等待所有任务完成

```csharp
// 等待所有 ETTask 全部完成后继续
public static async ETTask WhenAll(params ETTask[] tasks)
{
    if (tasks.Length == 0) return;

    int remaining = tasks.Length;
    ETTask tcs = ETTask.Create(fromPool: true);

    foreach (var task in tasks)
    {
        RunTask(task).Coroutine();  // fire-and-forget 方式启动
    }
    await tcs;

    async ETTask RunTask(ETTask t)
    {
        await t;
        if (Interlocked.Decrement(ref remaining) == 0)
            tcs.SetResult();  // 全部完成，唤醒等待者
    }
}

// 带返回值版本
public static async ETTask<T[]> WhenAll<T>(params ETTask<T>[] tasks)
{
    T[] results = new T[tasks.Length];
    int remaining = tasks.Length;
    ETTask tcs = ETTask.Create(fromPool: true);

    for (int i = 0; i < tasks.Length; i++)
    {
        int idx = i;
        RunTask(tasks[idx], idx).Coroutine();
    }
    await tcs;
    return results;

    async ETTask RunTask(ETTask<T> t, int index)
    {
        results[index] = await t;
        if (Interlocked.Decrement(ref remaining) == 0)
            tcs.SetResult();
    }
}
```

**使用示例：**

```csharp
// 并行加载三个资源，全部完成后继续
await ETTaskHelper.WhenAll(
    AssetLoader.LoadAsync("prefab_player"),
    AssetLoader.LoadAsync("prefab_enemy"),
    ConfigManager.LoadAsync("battle_config")
);
// 三个资源都加载完毕，开始初始化战斗场景
InitBattle();
```

### 1.2 WhenAny —— 等待任意一个任务完成

```csharp
// 返回第一个完成的任务的索引
public static async ETTask<int> WhenAny(params ETTask[] tasks)
{
    ETTask<int> tcs = ETTask<int>.Create(fromPool: true);

    for (int i = 0; i < tasks.Length; i++)
    {
        int idx = i;
        RunTask(tasks[idx], idx).Coroutine();
    }
    return await tcs;

    async ETTask RunTask(ETTask t, int index)
    {
        await t;
        // 第一个完成的才能 SetResult（后续完成的被忽略）
        if (tcs.GetAwaiter().IsCompleted) return;
        tcs.SetResult(index);
    }
}
```

**使用示例：**

```csharp
// 超时竞争模式：操作完成或超时，取先发生的
int winner = await ETTaskHelper.WhenAny(
    DoOperationAsync(),                                 // 任务 0
    TimerComponent.Instance.WaitAsync(5000)             // 任务 1（5秒超时）
);

if (winner == 1)
    Log.Warning("操作超时！");
```

### 1.3 Delay —— 基于定时器的延迟

```csharp
// 等待指定毫秒数
public static ETTask Delay(int milliseconds, ETCancellationToken token = null)
{
    return TimerComponent.Instance.WaitAsync(milliseconds, token);
}

// 等待指定帧数
public static ETTask DelayFrame(int frameCount, ETCancellationToken token = null)
{
    return TimerComponent.Instance.WaitFrameAsync(frameCount, token);
}
```

**使用示例：**

```csharp
// 技能冷却：等待 2 秒后恢复可用
async ETTask SkillCooldown(SkillComponent skill, ETCancellationToken token)
{
    skill.IsCoolingDown = true;
    await ETTaskHelper.Delay(2000, token);
    if (!token.IsCancel())
        skill.IsCoolingDown = false;
}
```

### 1.4 SwitchToMainThread / SwitchToThreadPool

```csharp
// 切换到主线程执行（用于从子线程回到主线程）
public static async ETTask SwitchToMainThread()
{
    // 通过 SynchronizationContext.Post 回调到主线程
    await new MainThreadAwaiter();
}

// 切换到线程池执行（用于耗时操作）
public static async ETTask SwitchToThreadPool()
{
    await Task.Yield();  // 挂起到线程池
}

// 典型使用模式
async ETTask LoadAndProcess(string path)
{
    await ETTaskHelper.SwitchToThreadPool();
    byte[] data = File.ReadAllBytes(path);    // 子线程 IO

    await ETTaskHelper.SwitchToMainThread();
    ProcessData(data);                        // 主线程处理
}
```

---

## 二、ETTaskCompleted —— 即完成任务

### 2.1 设计动机

在某些场景下，函数签名要求返回 `ETTask`，但函数体本身是同步完成的：

```csharp
// 接口要求异步，但实现可以同步完成
public interface ILoader
{
    ETTask LoadAsync(string key);
}

// 已缓存的情况：同步完成，无需异步
public class CachedLoader : ILoader
{
    public ETTask LoadAsync(string key)
    {
        if (cache.Contains(key))
            return ETTask.CompletedTask;  // 使用即完成任务，零分配
        return DoLoadAsync(key);
    }
}
```

如果这里返回 `async ETTask` 并立即 `return`，编译器仍然会生成状态机并分配对象。`ETTaskCompleted` 直接规避了这个问题。

### 2.2 实现原理

```csharp
// 轻量值类型，不产生堆分配
public readonly struct ETTaskCompleted : ICriticalNotifyCompletion
{
    // IsCompleted 始终为 true，await 不会真正挂起
    public bool IsCompleted => true;

    // GetAwaiter 返回自身（struct，栈分配）
    public ETTaskCompleted GetAwaiter() => this;

    // 因为 IsCompleted=true，continuation 不会被存储，直接调用
    public void OnCompleted(Action continuation) => continuation();
    public void UnsafeOnCompleted(Action continuation) => continuation();

    // GetResult 什么都不做
    public void GetResult() { }
}

// 全局单例（避免重复创建 struct）
public static class ETTask
{
    public static ETTaskCompleted CompletedTask => new ETTaskCompleted();
}
```

**关键点：** `IsCompleted = true` 让 `await` 的 continuation 立即同步执行，不会进入任何队列。这是"零开销 await"的实现基础。

### 2.3 对比普通 ETTask

```
await ETTask.CompletedTask：
  IsCompleted = true → 直接执行 continuation → 零延迟，零分配

await ETTask.Create()：
  IsCompleted = false → 注册 callback → 等待 SetResult → 唤醒 continuation
```

---

## 三、协程启动辅助 —— Coroutine() 扩展

```csharp
// fire-and-forget 启动协程，自动捕获异常
public static void Coroutine(this ETTask task)
{
    task.GetAwaiter().OnCompleted(() => { });  // 注册空回调，防止异常丢失
}

// 带异常处理的版本
public static void Coroutine(this ETTask task, Action<Exception> onError)
{
    InnerCoroutine(task, onError).Coroutine();

    async ETTask InnerCoroutine(ETTask t, Action<Exception> handler)
    {
        try { await t; }
        catch (Exception e) { handler(e); }
    }
}
```

**使用场景：**

```csharp
// ❌ 直接调用 async ETTask 方法，返回值被忽略，异常静默丢失
StartBattleAsync();

// ✅ 使用 .Coroutine() 明确启动，异常会被全局日志捕获
StartBattleAsync().Coroutine();

// ✅ 或带自定义错误处理
StartBattleAsync().Coroutine(e => ShowErrorDialog(e.Message));
```

---

## 四、常用组合模式

### 4.1 带取消的超时等待

```csharp
public static async ETTask<bool> WaitWithTimeout(ETTask task, int timeoutMs)
{
    var cts = new ETCancellationToken();
    var timeout = ETTaskHelper.Delay(timeoutMs, cts);

    int result = await ETTaskHelper.WhenAny(task, timeout);

    if (result == 0)
    {
        cts.Cancel();  // 取消定时器
        return true;   // 任务完成
    }
    return false;      // 超时
}
```

### 4.2 顺序执行多个异步步骤

```csharp
// 游戏启动流程
async ETTask GameStartup()
{
    await InitSDK();           // 步骤1：初始化 SDK
    await LoginAsync();        // 步骤2：登录（等步骤1完成）
    await LoadUserData();      // 步骤3：加载数据（等步骤2完成）
    await ETTaskHelper.WhenAll(
        LoadUIAsync(),         // 步骤4a：并行加载 UI
        PreloadAssetsAsync(),  // 步骤4b：并行预加载资源
        LoadConfigAsync()      // 步骤4c：并行加载配置
    );
    EnterMainScene();          // 步骤5：进入主场景
}
```

---

## 五、小结

ETTaskHelper 和 ETTaskCompleted 共同构成了游戏异步编程的工具箱：

1. **WhenAll**：并行等待，减少串行等待的总耗时
2. **WhenAny**：竞争等待，实现超时、取消等模式
3. **Delay/DelayFrame**：基于游戏定时器的精确延迟
4. **SwitchToMainThread/ThreadPool**：显式线程切换，保证执行上下文
5. **ETTaskCompleted**：同步接口的零开销实现，消除不必要的状态机分配
6. **.Coroutine()**：安全的 fire-and-forget 模式，避免异常静默丢失

掌握这些工具，能让游戏异步逻辑的代码既直观易读，又保持极低的 GC 开销。
