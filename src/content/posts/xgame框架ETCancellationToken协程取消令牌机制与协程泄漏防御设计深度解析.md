---
title: xgame框架ETCancellationToken协程取消令牌机制与协程泄漏防御设计深度解析
published: 2026-05-02
description: 深入解析xgame框架ETCancellationToken的核心设计：HashSet回调注册、一次性触发语义、null哨兵防止重复取消、协程泄漏检测约束，以及在异步等待场景中的完整使用模式。
tags: [Unity, xgame框架, 异步编程, 协程取消, ETTask, C#]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

在异步编程中，**任务取消（Cancellation）** 是一个极其重要却常被忽视的机制。xgame 框架提供了 `ETCancellationToken`，它并不依赖 .NET 标准库的 `CancellationToken`，而是从零设计了一套更贴合游戏逻辑的轻量取消机制。

本文将深入解析 `ETCancellationToken` 的每一个设计决策，包括它如何检测协程泄漏、如何防止重复取消、以及在哪些典型场景下应当使用它。

---

## 核心源码

```csharp
namespace ET
{
    public class ETCancellationToken
    {
        private HashSet<Action> actions = new();

        public void Add(Action callback)
        {
            // 如果action是null，绝对不能添加，要抛异常，说明有协程泄漏
            this.actions.Add(callback);
        }
        
        public void Remove(Action callback)
        {
            this.actions?.Remove(callback);
        }

        public bool IsDispose()
        {
            return this.actions == null;
        }

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
            this.actions = null;
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
    }
}
```

---

## 一、数据结构选型：为何用 HashSet 而非 List？

```csharp
private HashSet<Action> actions = new();
```

取消令牌的核心数据结构是 `HashSet<Action>`，这里有两重考量：

### 1. 天然去重，防止重复注册

假设某段代码误操作对同一个回调调用了两次 `Add`：

```csharp
token.Add(myCallback);
token.Add(myCallback); // 第二次 Add，如果是 List 会执行两次！
```

使用 `HashSet` 时，第二次 `Add` 会被自动忽略，避免取消时同一回调被执行多次导致逻辑错误。

### 2. O(1) 的 Remove 操作

当一个挂起的 `ETTask` 正常完成时，它需要从取消令牌中**注销自己的回调**（否则取消时会调用一个已完成任务的回调，可能造成异常）。`HashSet.Remove` 的平均时间复杂度是 O(1)，比 `List.Remove` 的 O(n) 性能更优。

在帧循环中可能存在大量并发异步等待，高效的注销操作直接影响性能。

---

## 二、Add 中隐藏的协程泄漏检测

```csharp
public void Add(Action callback)
{
    // 如果action是null，绝对不能添加，要抛异常，说明有协程泄漏
    this.actions.Add(callback);
}
```

注释说"如果 action 是 null，要抛异常，说明有协程泄漏"，但代码中并没有显式的 null 检查。这是为什么？

**答案在 `HashSet.Add` 的行为上**：`HashSet<Action>` 不允许添加 `null` 值（会抛出 `ArgumentNullException`）。框架**利用了集合的内置约束**来实现泄漏检测，而不是自己写 if-null 判断。

### 什么情况下 callback 会是 null？

在 `AsyncETTaskMethodBuilder` 中，当一个 `ETTask` 的完成回调（`MoveNext` 委托）因为状态机已被提前销毁而变为 null 时，`Add(null)` 就会触发异常。这种情况正是协程泄漏的典型表现——**父对象已销毁，但子协程还在尝试挂载取消回调**。

这种设计将"隐式的内存泄漏"转化为"显式的运行时异常"，极大地降低了调试难度。

---

## 三、Remove 的安全设计：可空操作符

```csharp
public void Remove(Action callback)
{
    this.actions?.Remove(callback);
}
```

注意这里使用了 `?.`（可空条件操作符）。

`this.actions` 何时为 null？在 `Invoke()` 被调用后，`this.actions` 会被置为 null（下一节会详细分析）。如果某个已挂起的 `ETTask` 在 `Cancel()` 触发后，仍然在回调中尝试调用 `Remove`（例如 ETTask 完成的回调链中），用 `?.` 可以安全跳过，不会抛出 NullReferenceException。

这是防御性编程的体现：**取消流程不应该因为"重复清理"而崩溃**。

---

## 四、IsDispose：以 null 作为已触发的哨兵值

```csharp
public bool IsDispose()
{
    return this.actions == null;
}
```

`IsDispose()` 实际上检测的是"这个 CancellationToken 是否已经被触发过"。框架选择用 **null 作为哨兵值**来表示"已取消"状态，而不是单独维护一个 bool 字段。

这个设计节省了内存（少一个字段），并与 `Invoke()` 中的置 null 操作形成天然的状态联动。

### 使用示例

```csharp
// 等待操作前检查令牌是否已经被取消
if (!cancellationToken.IsDispose())
{
    await SomeAsyncOperation(cancellationToken);
}
```

---

## 五、Cancel 的幂等性保障

```csharp
public void Cancel()
{
    if (this.actions == null)
    {
        return;
    }
    this.Invoke();
}
```

`Cancel()` 是**幂等的**：第一次调用会触发所有回调并将 `actions` 置 null，之后任意多次调用 `Cancel()` 都会因为 `actions == null` 而直接返回，不会重复触发。

这非常重要——在游戏逻辑中，取消操作可能来自多个路径（UI 取消、场景切换、网络断线），幂等性保证了多路径触发的安全。

---

## 六、Invoke 的一次性执行与异常隔离

```csharp
private void Invoke()
{
    HashSet<Action> runActions = this.actions;
    this.actions = null;
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

### 关键设计：先置 null，再执行

```csharp
HashSet<Action> runActions = this.actions;
this.actions = null;  // 先置 null！
```

为何要在执行前就把 `this.actions` 置 null，而不是执行完之后？

**防止回调中的重入问题**：如果某个回调 `action` 内部又调用了 `Cancel()`，如果先执行后置 null，会导致递归调用 `Invoke()`，造成回调被触发两次甚至死循环。

先置 null 后，无论回调内部如何调用 `Cancel()`，都会因为 `this.actions == null` 而提前返回，彻底消除重入风险。

### 异常隔离

```csharp
catch (Exception e)
{
    ETTask.ExceptionHandler.Invoke(e);
}
```

取消回调中的异常不会向外传播，而是通过 `ETTask.ExceptionHandler` 统一上报。这保证了**一个回调的失败不会阻止其他回调的执行**（尽管当前实现在 catch 后就退出了循环，这是一个可以改进的点）。

---

## 七、典型使用场景

### 场景一：可取消的定时等待

```csharp
private ETCancellationToken cancellationToken;

async ETTask StartCountdown()
{
    cancellationToken = new ETCancellationToken();
    
    // 等待3秒，支持中途取消
    await TimerComponent.Instance.WaitAsync(3000, cancellationToken);
    
    if (cancellationToken.IsDispose())
    {
        // 被取消了，不执行后续逻辑
        return;
    }
    
    // 正常完成
    OnCountdownFinished();
}

void OnBattleEnd()
{
    // 战斗结束，取消倒计时
    cancellationToken?.Cancel();
}
```

### 场景二：场景切换时批量取消

```csharp
public class BattleScene : Entity
{
    private ETCancellationToken sceneToken;
    
    public void Init()
    {
        sceneToken = new ETCancellationToken();
        StartAllBattleCoroutines(sceneToken).Coroutine();
    }
    
    public void Dispose()
    {
        // 场景销毁时，一次性取消所有挂载的异步操作
        sceneToken.Cancel();
    }
}
```

### 场景三：网络请求超时与取消联动

```csharp
async ETTask<ResponseData> SendRequestWithTimeout(RequestData req)
{
    var token = new ETCancellationToken();
    
    // 启动超时定时器
    ETTask timeoutTask = TimerComponent.Instance.WaitAsync(5000, token);
    ETTask<ResponseData> requestTask = NetworkComponent.SendAsync(req, token);
    
    // 谁先完成，谁取消另一个
    await ETTaskHelper.WaitAny(timeoutTask, requestTask);
    token.Cancel(); // 取消还未完成的那个
    
    return requestTask.IsCompleted ? requestTask.GetResult() : default;
}
```

---

## 八、与 .NET CancellationToken 的对比

| 特性 | ETCancellationToken | .NET CancellationToken |
|------|--------------------|-----------------------|
| 内存开销 | 极低（HashSet + 状态） | 较高（CancellationTokenSource + 链接树） |
| 线程安全 | 非线程安全（主线程使用） | 完整线程安全 |
| 取消传播 | 手动注册回调 | 自动链接传播 |
| 泄漏检测 | null 传入即异常 | 无内置检测 |
| 适用场景 | 游戏主逻辑异步 | 通用多线程场景 |

ETCancellationToken 的设计取向非常明确：**为游戏主线程单线程异步场景深度优化**，去掉了多线程开销，增加了游戏特有的泄漏检测能力。

---

## 小结

`ETCancellationToken` 用不到 50 行代码，实现了一个完整的取消机制：

- **HashSet** 确保回调去重与高效注销
- **null 哨兵** 实现状态表示与幂等取消
- **先置 null 后执行** 防止重入
- **`?.` 安全调用** 防止已取消后的二次清理崩溃
- **null 传入即异常** 转化泄漏为可见错误

这些设计共同构成了 xgame 框架异步取消体系的可靠基础，是每一个使用 ETTask 的开发者都应该深刻理解的核心组件。
