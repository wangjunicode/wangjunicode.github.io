---
title: 协程锁类型注册表与分类队列管理-CoroutineLockType与CoroutineLockQueueType深度解析
published: 2026-04-16
description: 深入解析游戏框架中协程锁类型常量表（CoroutineLockType）与按类型分组管理锁队列的容器（CoroutineLockQueueType），理解其在分布式多系统并发隔离中的设计思路。
tags: [Unity, 游戏框架, 协程锁, 并发, ECS]
category: Unity游戏框架源码解析
encryptedKey: henhaoji123
draft: false
---

## 前言

在前一篇文章中我们解析了 `CoroutineLockQueue` 的单队列等待机制。然而真实的游戏服务端往往有几十个相互独立的并发域：**登录系统**、**数据库操作**、**资源加载**、**UI 状态机**……每个域都需要用锁来串行化，但彼此之间又不能互相阻塞。

`CoroutineLockType` 与 `CoroutineLockQueueType` 这两个类就是为了解决这个问题而存在的。前者是**全局类型常量表**，后者是**按类型管理所有锁队列的容器**。本文将深入分析二者的设计原理与工程实践。

---

## 一、CoroutineLockType：并发域的全局编号表

### 1.1 源码全览

```csharp
namespace ET
{
    public static class CoroutineLockType
    {
        public const int None = 0;
        public const int Location = 1;         // location 进程上使用
        public const int ActorLocationSender = 2; // ActorLocationSender 中队列消息
        public const int Mailbox = 3;          // Mailbox 中队列
        public const int UnitId = 4;           // Map 服务器上线下线时使用
        public const int DB = 5;
        public const int Resources = 6;
        public const int ResourcesLoader = 7;

        public const int UI = 10;
        public const int DNS = 11;
        public const int ZoneLogin = 12;

        public const int Max = 100;            // 必须最大
    }
}
```

### 1.2 设计意图

这是一张**静态常量注册表**，用整数 ID 为每个并发域命名。好处是：

| 特性 | 说明 |
|------|------|
| **零开销** | 编译期常量，运行时无字符串比较、无哈希 |
| **可读性** | `CoroutineLockType.DB` 比数字 `5` 更语义化 |
| **有界** | `Max = 100` 限定了最多 100 种锁类型，为数组索引预分配做准备 |
| **分组** | 编号留有间隙（7→10），便于后续插入同类子系统 |

### 1.3 Max 的作用

```csharp
// CoroutineLockComponent 初始化时预分配数组
_lockQueues = new CoroutineLockQueueType[CoroutineLockType.Max];
for (int i = 0; i < CoroutineLockType.Max; i++)
    _lockQueues[i] = new CoroutineLockQueueType(i);
```

`Max` 不是随意写的，它决定了上层组件**能用 O(1) 数组下标直接索引**到对应的 `CoroutineLockQueueType`，而不必走字典查找。

---

## 二、CoroutineLockQueueType：按 key 管理的锁队列容器

### 2.1 源码全览

```csharp
public class CoroutineLockQueueType
{
    private readonly int type;
    private readonly Dictionary<long, CoroutineLockQueue> coroutineLockQueues
        = new Dictionary<long, CoroutineLockQueue>();

    public CoroutineLockQueueType(int type)
    {
        this.type = type;
    }

    private CoroutineLockQueue Get(long key) { ... }
    private CoroutineLockQueue New(long key) { ... }
    private void Remove(long key) { ... }

    public async ETTask<CoroutineLock> Wait(long key, int time)
    {
        CoroutineLockQueue queue = this.Get(key) ?? this.New(key);
        return await queue.Wait(time);
    }

    public void Notify(long key, int level)
    {
        CoroutineLockQueue queue = this.Get(key);
        if (queue == null) return;
        if (queue.Count == 0)
            this.Remove(key);
        queue.Notify(level);
    }
}
```

### 2.2 两层结构：type × key

理解这个类需要明白它处于**两级索引体系**的第二层：

```
CoroutineLockComponent
  └─ CoroutineLockQueueType[type]   ← 第一层：按系统类型
        └─ CoroutineLockQueue[key]  ← 第二层：按资源 key
              └─ WaitCoroutineLock  ← 具体等待节点
```

以数据库操作为例：
- `type = CoroutineLockType.DB`（5）
- `key = unitId`（哪个玩家的 DB 操作）

这样**每个玩家的 DB 操作**形成独立队列，互不干扰；不同玩家之间天然并行；同一玩家的 DB 操作天然串行。

### 2.3 懒创建与及时回收

```csharp
// Wait: 懒创建
CoroutineLockQueue queue = this.Get(key) ?? this.New(key);

// Notify: 空队列立即销毁
if (queue.Count == 0)
    this.Remove(key);
```

这是**资源按需分配**策略：
- 队列只在第一个等待者到来时创建
- 队列在最后一个等待者离开后立即销毁（`Remove` 调用 `queue.Recycle()` 归还对象池）

避免为每个可能的 `key` 预先分配队列对象，内存利用率极高。

### 2.4 Notify 时机的微妙之处

```csharp
public void Notify(long key, int level)
{
    CoroutineLockQueue queue = this.Get(key);
    if (queue == null) return;
    
    if (queue.Count == 0)
        this.Remove(key);   // 先移除空队列
    
    queue.Notify(level);    // 再通知（即使已移除，对象仍有效直到 Recycle）
}
```

注意这里先判断 `Count == 0` 再 Remove，看起来如果队列已空为何还要 Notify？

原因在于：`Count` 统计的是**等待中的协程数**，而此刻持有锁的协程正在执行（还未加入等待），当它释放锁时会调用 `Notify`，此时队列可能已无新等待者（Count=0），需要先清理掉这个空队列条目，再让内部状态归零。

---

## 三、WaitCoroutineLock：带超时的异步等待凭证

```csharp
[Invoke(TimerCoreInvokeType.CoroutineTimeout)]
public class WaitCoroutineLockTimer : ATimer<WaitCoroutineLock>
{
    protected override void Run(WaitCoroutineLock waitCoroutineLock)
    {
        if (waitCoroutineLock.IsDisposed()) return;
        waitCoroutineLock.SetException(new Exception("coroutine is timeout!"));
    }
}

public class WaitCoroutineLock
{
    public static WaitCoroutineLock Create()
    {
        var w = new WaitCoroutineLock();
        w.tcs = ETTask<CoroutineLock>.Create(true);
        return w;
    }

    private ETTask<CoroutineLock> tcs;

    public void SetResult(CoroutineLock coroutineLock) { ... }
    public void SetException(Exception exception) { ... }
    public bool IsDisposed() => this.tcs == null;
    public async ETTask<CoroutineLock> Wait() => await this.tcs;
}
```

`WaitCoroutineLock` 本质上是对 `ETTask<CoroutineLock>` 的封装，提供：

1. **`Wait()`**：挂起当前协程，等待锁被授予
2. **`SetResult()`**：锁队列唤醒时调用，传入 `CoroutineLock` 对象
3. **`SetException()`**：超时定时器调用，向等待者抛出异常
4. **`IsDisposed()`**：防止重复通知（tcs 置 null 后视为已处理）

### 超时机制流程

```
CoroutineLockQueue.Wait(time)
  ├─ 创建 WaitCoroutineLock
  ├─ 如果 time > 0 → 启动定时器 WaitCoroutineLockTimer
  ├─ 挂起等待
  │
  ├─ 情况A: 前一个锁释放 → SetResult(lock) → 协程继续执行
  └─ 情况B: 超时触发 → SetException → 协程收到异常
```

---

## 四、完整使用示例

```csharp
// 锁住特定玩家 ID 的 DB 操作
using (await CoroutineLockComponent.Instance.Wait(CoroutineLockType.DB, playerId, 5000))
{
    // 这里是串行安全区，同一 playerId 的其他协程会等待
    var data = await DBManager.LoadPlayer(playerId);
    data.Gold += 100;
    await DBManager.SavePlayer(playerId, data);
} // using 结束自动释放锁，下一个等待者被唤醒
```

C# 的 `using` 语句配合 `IDisposable` 实现**锁的自动释放**，即使发生异常也能正确释放，避免死锁。

---

## 五、设计总结

| 组件 | 职责 |
|------|------|
| `CoroutineLockType` | 全局并发域命名，整数常量，零运行时开销 |
| `CoroutineLockQueueType` | 单一并发域内按 key 管理所有锁队列，懒创建+及时回收 |
| `WaitCoroutineLock` | 单个等待节点，封装 ETTask 并支持超时异常 |
| `WaitCoroutineLockTimer` | 定时器集成，到期后注入超时异常 |

三者共同构成了**游戏框架协程锁的完整等待—通知—超时链路**，是服务端高并发场景下异步串行化的核心基础设施。
