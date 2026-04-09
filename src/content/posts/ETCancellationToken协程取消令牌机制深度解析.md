---
title: ETCancellationToken协程取消令牌机制深度解析
published: 2026-04-09
description: 深入剖析ET框架中ETCancellationToken的设计原理与实现，讲解协程生命周期的安全取消、回调注册与销毁、空引用陷阱，以及在游戏业务中的应用场景。
tags: [Unity, ET框架, 协程, 异步, CancellationToken, ECS]
category: 框架底层
draft: false
encryptedKey:henhaoji123
---

# ETCancellationToken 协程取消令牌机制深度解析

在游戏开发中，异步逻辑无处不在——加载资源、等待网络响应、延时触发技能效果。这些操作如果得不到妥善的取消管理，就会产生**协程泄漏**，轻则内存增长，重则逻辑乱序导致游戏崩溃。ET 框架通过 `ETCancellationToken` 提供了一套简洁却健壮的协程取消机制。本文将从源码层面完整解析其设计思路与实战应用。

---

## 一、为什么需要取消令牌？

先看一个没有取消机制时的典型问题：

```csharp
// 玩家点击NPC，触发一段过场动画 + 延迟显示对话框
async ETTask ShowDialogAfterCutscene(int npcId)
{
    await TimerComponent.Instance.WaitAsync(3000); // 等待3秒过场动画
    UIDialogComponent.Instance.Show(npcId);        // 显示对话框
}
```

如果玩家在过场动画期间切换了场景，`UIDialogComponent` 可能已经被销毁，此时调用 `Show` 就会抛出空引用异常或者在错误的 Scene 上产生对话框。

传统 Unity 协程可以通过 `StopCoroutine` 解决，但在 ET 的 ETTask 体系下，我们需要一个更精细的机制——**取消令牌（CancellationToken）**。

---

## 二、ETCancellationToken 源码全解

### 2.1 核心数据结构

```csharp
public class ETCancellationToken
{
    private HashSet<Action> actions = new();
    // ...
}
```

`ETCancellationToken` 的核心是一个 `HashSet<Action>`，存储所有注册了"取消时执行"的回调函数。

为什么用 `HashSet` 而不是 `List`？
- **去重语义**：同一个回调不应该被执行两次，HashSet 天然保证幂等性
- **O(1) 的删除**：可以快速通过 `Remove(callback)` 按引用移除特定的回调

### 2.2 生命周期状态判断

```csharp
public bool IsDispose()
{
    return this.actions == null;
}
```

这是一个极其简洁的状态检测手段：当 `actions` 字段被设置为 `null`，代表该 Token 已经被取消并释放。这样做有两个优势：
1. **无需额外的布尔标志**：直接利用引用是否为空判断状态
2. **内存回收辅助**：取消后 HashSet 引用为 null，GC 可以回收之前注册的 Action 引用

### 2.3 注册与注销回调

```csharp
public void Add(Action callback)
{
    // 如果action是null，绝对不能添加,要抛异常，说明有协程泄漏
    this.actions.Add(callback);
}

public void Remove(Action callback)
{
    this.actions?.Remove(callback);
}
```

**Add 的注意点：**
- 注释特别强调：如果调用方传入了 `null`，说明有协程泄漏——某个 ETTask 在没有正确管理生命周期的情况下丢失了回调引用。这是一个防御性设计，暴露问题而非吞掉异常。

**Remove 的注意点：**
- 使用了空条件运算符 `?.`：如果 Token 已经被取消（`actions == null`），Remove 调用会安全地返回 null 而不是抛出 NullReferenceException。
- 这种设计允许在取消后"幂等地"注销回调，不会崩溃。

### 2.4 取消流程

```csharp
public void Cancel()
{
    if (this.actions == null)
    {
        return;
    }
    this.Invoke();
}

private void Invoke()
{
    HashSet<Action> runActions = this.actions;
    this.actions = null;           // 先置 null，再执行
    try
    {
        foreach (Action action in runActions)
        {
            action.Invoke();
        }
    }
    catch (Exception e)
    {
        ETTask.ExceptionHandler.Invoke(e);
    }
}
```

取消流程有几个精妙之处值得逐行分析：

#### 防止重复取消

```csharp
if (this.actions == null)
{
    return;
}
```

取消操作本身是幂等的。如果已经取消过（`actions == null`），直接返回。

#### 先置 null 再迭代（关键！）

```csharp
HashSet<Action> runActions = this.actions;
this.actions = null;   // 先置 null
```

这一行看似简单，实则防范了一个危险的重入场景：

假设某个回调 `action` 在执行时，间接再次调用了 `Cancel()`，如果不先置 null，就会产生无限递归或双重执行。先将 `actions` 设为 `null`，后续任何对 `Cancel()` 的重入调用都会被第一行的 `if` 拦截。

#### 异常处理集中上报

```csharp
catch (Exception e)
{
    ETTask.ExceptionHandler.Invoke(e);
}
```

不让异常在回调链中传播——一个回调抛异常不应该阻止后续回调的执行（虽然目前的实现一旦抛异常就会中断后续 Action，这是潜在改进点）。通过 `ETTask.ExceptionHandler` 统一上报，符合 ET 框架的日志集中处理策略。

---

## 三、ETCancellationToken 在 ETTask 体系中的位置

ETCancellationToken 与 ETTask 的集成通常通过 `ETTaskHelper` 中的扩展方法实现，典型模式如下：

```csharp
// 等待一定时间，支持取消
public static async ETTask WaitAsync(long time, ETCancellationToken cancellationToken = null)
{
    // 创建一个 ETTask
    ETTask tcs = ETTask.Create(true);

    // 注册定时器回调
    long timerId = TimerComponent.Instance.NewOnceTimer(
        TimeHelper.ClientNow() + time,
        TimerCoreInvokeType.ETTaskTimer,
        tcs
    );

    // 注册取消回调
    Action cancelAction = () =>
    {
        TimerComponent.Instance.Remove(ref timerId); // 取消定时器
        tcs.SetResult();                              // 立即完成任务
    };

    cancellationToken?.Add(cancelAction);

    try
    {
        await tcs;
    }
    finally
    {
        cancellationToken?.Remove(cancelAction); // 正常完成时注销
    }
}
```

通过这个模式，ETTask 的等待可以被外部 Token 随时中断。

---

## 四、实战场景：Entity 生命周期绑定

最常见的用法是将 Token 绑定到 Entity 的生命周期：

```csharp
public class PlayerComponent : Entity, IAwake, IDestroy
{
    public ETCancellationToken CancelToken { get; private set; }

    public void Awake()
    {
        CancelToken = new ETCancellationToken();
        this.StartAILoop().Coroutine();
    }

    public void Destroy()
    {
        CancelToken.Cancel(); // 销毁时取消所有异步操作
    }

    private async ETTask StartAILoop()
    {
        while (true)
        {
            // 每帧 AI 决策，支持取消
            await TimerComponent.Instance.WaitFrameAsync(this.CancelToken);
            if (this.IsDisposed) return;
            
            this.RunAIDecision();
        }
    }
}
```

当玩家离开场景，`Destroy()` 被调用，`CancelToken.Cancel()` 触发所有注册的取消回调，`WaitFrameAsync` 立即返回，`IsDisposed` 检查进一步保护后续逻辑。

---

## 五、多级 Token 与 Token 传递

在复杂的嵌套异步场景中，可以通过注册链式取消实现"父取消子"的效果：

```csharp
// 父 Token（场景级别）
ETCancellationToken sceneToken = new ETCancellationToken();

// 子 Token（单个功能级别）
ETCancellationToken featureToken = new ETCancellationToken();

// 当场景取消时，同步取消子功能
sceneToken.Add(featureToken.Cancel);

// 当子功能提前完成时，从父 Token 注销
// （避免内存泄漏——父 Token 一直持有 featureToken.Cancel 的引用）
featureToken.Add(() => sceneToken.Remove(featureToken.Cancel));
```

这种链式注册需要注意 **反向注销**，否则父 Token 会持有已完成的子 Token 回调引用，形成内存泄漏。

---

## 六、常见陷阱与最佳实践

### 陷阱一：Add null 导致的崩溃

```csharp
Action cancelAction = null;
cancellationToken.Add(cancelAction); // ❌ 直接抛 NullReferenceException
```

ETCancellationToken 不保护 null 的 Add。这是故意的——传入 null 说明业务代码有 bug（通常是闭包捕获失败），应当暴露。

### 陷阱二：Cancel 后继续 Add

```csharp
token.Cancel();
token.Add(someAction); // ❌ actions 已经为 null，直接 NullReferenceException
```

取消后的 Token 已经不可用，不应该再调用 Add。如果业务中存在这种情况，需在 Add 前检查 `!token.IsDispose()`。

### 陷阱三：忘记 Remove 导致内存泄漏

```csharp
// ❌ 没有在正常完成时 Remove
ETCancellationToken token = ...;
Action cancelAction = () => { /* cleanup */ };
token.Add(cancelAction);

await SomeOperationAsync();
// 操作完成后，cancelAction 仍在 token 的 HashSet 中
// 只要 token 不被 Cancel，这个 Action 就不会释放
```

正确做法是在 `finally` 块中调用 `Remove`，确保无论成功/异常/取消都能注销。

### 最佳实践总结

| 场景 | 推荐做法 |
|------|----------|
| Entity 级取消 | 在 `Awake` 创建 Token，在 `Destroy` 调用 `Cancel` |
| 等待超时 | 传入 Token，配合 `WaitAsync` 使用 |
| 嵌套取消 | 父 Token `Add(子Token.Cancel)`，子完成后 `Remove` |
| 多操作同时取消 | 同一个 Token 注册多个回调，一次 Cancel 全部触发 |

---

## 七、与 .NET 标准 CancellationToken 的对比

| 特性 | ETCancellationToken | System.CancellationToken |
|------|---------------------|--------------------------|
| 对象池支持 | ❌ 每次 new | ✅ CancellationTokenSource 可重用 |
| 线程安全 | ⚠️ 无锁，单线程设计 | ✅ 线程安全 |
| 回调数量 | 无上限（HashSet） | 有内部限制 |
| 泄漏检测 | ✅ Add(null) 抛异常 | ❌ 静默忽略 |
| 取消后 Add | ❌ 抛 NullRef | ✅ 静默不添加 |
| 链式取消 | 手动注册 | `CreateLinkedTokenSource` |

ET 框架的设计选择了**更激进的崩溃保护**而非宽容策略，目的是在开发期尽早暴露错误。

---

## 八、小结

`ETCancellationToken` 是 ET 框架异步体系中的重要一环：

1. **HashSet<Action> 核心**：通过回调集合管理取消逻辑，支持多协程同时取消
2. **null 即已取消**：用引用状态代替布尔标志，设计简洁
3. **先置 null 后迭代**：防范重入取消的关键防御手段
4. **与 Entity 生命周期绑定**：是 ECS 架构下异步安全的标准模式
5. **主动暴露 null 错误**：选择崩溃而非沉默，帮助开发者快速定位协程泄漏

对于初入游戏开发的同学，记住一句话：**所有绑定到 Entity 的异步操作，都要传入并响应 CancellationToken，否则对象销毁后仍在运行的协程是你调试噩梦的来源。**
