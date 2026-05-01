---
title: "游戏框架AwaiterStatus枚举与ETTask异步等待状态机核心设计深度解析"
description: "深入剖析ET框架中IAwaiter.cs里的AwaiterStatus枚举，揭示Pending/Succeeded/Faulted三态状态机如何驱动ETTask异步系统，以及byte底层类型选择的性能考量"
pubDate: "2026-05-01"
heroImage: ""
encryptedKey: "henhaoji123"
tags: ["Unity", "ET框架", "异步编程", "状态机", "ETTask"]
---

## 前言

在ET框架的异步系统中，有一个看似极其简单却至关重要的枚举——`AwaiterStatus`。它只有三个值，却是整个ETTask异步状态机运转的基础。本文将深入分析这个枚举的设计哲学，以及它如何与C#的awaiter模式紧密结合。

## AwaiterStatus 源码解析

```csharp
namespace ET
{
    public enum AwaiterStatus: byte
    {
        /// <summary>The operation has not yet completed.</summary>
        Pending = 0,
        
        /// <summary>The operation completed successfully.</summary>
        Succeeded = 1,

        /// <summary>The operation completed with an error.</summary>
        Faulted = 2,
    }
}
```

代码极其精简，但每一个设计细节都值得深究。

## 设计要点一：byte 底层类型

枚举继承自 `byte` 而不是默认的 `int`，这是一个有意识的性能优化决策。

### 内存占用对比

| 类型 | 占用内存 | 适用场景 |
|------|----------|----------|
| int（默认） | 4 bytes | 通用，值域大 |
| byte | 1 byte | 值域小（0-255）|

在游戏运行时，可能同时存在成千上万个 awaiter 对象。将状态字段从4字节压缩到1字节，在大量并发异步操作的游戏场景中，累积效果相当可观。

### 缓存行友好性

CPU缓存行通常为64字节。更小的字段意味着单个缓存行能容纳更多对象，有助于提升缓存命中率，减少 cache miss。

## 设计要点二：三态状态机

### Pending（待定，值=0）

```
初始状态 → Pending
```

`Pending = 0` 利用了C#枚举的零值初始化特性。当一个 awaiter 对象刚被创建时，其状态字段会被默认初始化为0，即 `Pending`，无需额外赋值。这避免了"未初始化即完成"的语义错误。

### Succeeded（成功，值=1）

```
Pending → Succeeded（操作正常完成）
```

表示异步操作已经成功完成，可以安全地获取结果。对应C#标准 `INotifyCompletion` 接口中 `IsCompleted` 返回 `true` 且无异常的情况。

### Faulted（故障，值=2）

```
Pending → Faulted（操作发生异常）
```

表示异步操作以错误结束。与 `Succeeded` 区分开来，使得调用方能够在不捕获异常的前提下，通过状态枚举预先判断操作结果，从而选择性地处理错误路径。

## 与标准 Task 状态对比

C# 标准库 `Task` 有更多状态（Created、WaitingForActivation、WaitingToRun、Running、WaitingForChildrenToComplete、RanToCompletion、Canceled、Faulted）。ET框架的 AwaiterStatus 做了大幅简化：

| 标准 Task 状态 | AwaiterStatus 对应 |
|---------------|-------------------|
| Created / WaitingForActivation / Running | Pending |
| RanToCompletion | Succeeded |
| Faulted | Faulted |
| Canceled | — （ET框架通过 ETCancellationToken 另行处理）|

**注意**：ET框架没有 `Canceled` 状态。取消逻辑通过独立的 `ETCancellationToken` 机制实现，不污染 awaiter 核心状态机，职责更单一。

## IAwaiter 接口如何使用这个枚举

```csharp
// ETTask 系统中 IAwaiter 的使用模式（推断）
public interface IAwaiter
{
    AwaiterStatus Status { get; }
    bool IsCompleted => Status != AwaiterStatus.Pending;
}
```

框架通过检查 `Status != Pending` 来确定 `IsCompleted`，这是 C# await 语法糖展开后调用的关键属性。只要状态不是 `Pending`（无论成功还是故障），`IsCompleted` 就返回 `true`，促使状态机推进。

## 状态流转图

```
         ┌─────────────────────┐
         │      创建 Awaiter    │
         └──────────┬──────────┘
                    │ 初始化为 0
                    ▼
         ┌─────────────────────┐
         │       Pending        │ ← 等待异步操作完成
         └──────────┬──────────┘
                    │
          ┌─────────┴──────────┐
          │                    │
          ▼                    ▼
 ┌────────────────┐  ┌────────────────────┐
 │   Succeeded    │  │      Faulted        │
 │ 正常获取结果   │  │  抛出异常/错误处理  │
 └────────────────┘  └────────────────────┘
```

## 实际使用示例

```csharp
// ET框架中典型的异步等待模式
public async ETTask DoSomethingAsync()
{
    ETTask task = SomeAsyncOperation();
    var awaiter = task.GetAwaiter();
    
    // 状态机检查
    if (awaiter.Status == AwaiterStatus.Pending)
    {
        // 注册继续回调，挂起当前协程
        awaiter.OnCompleted(continuation);
    }
    else if (awaiter.Status == AwaiterStatus.Succeeded)
    {
        // 直接获取结果，无需切换
        var result = awaiter.GetResult();
    }
    else // Faulted
    {
        // GetResult() 会重新抛出异常
        awaiter.GetResult();
    }
}
```

## 为什么不用 bool IsCompleted 替代？

有人可能会问：直接用 `bool IsCompleted` 不够吗？

确实，仅判断"是否完成"只需要一个bool。但 `AwaiterStatus` 额外提供了 `Succeeded` 和 `Faulted` 的区分，使得框架层可以：

1. **性能优化**：在某些路径上，通过状态枚举比异常捕获更高效地处理错误
2. **调试友好**：序列化 awaiter 状态时，枚举比 bool 更具可读性
3. **扩展余地**：未来若需要增加如 `Canceled` 等状态，只需新增枚举值

## 总结

`AwaiterStatus` 是ET框架异步系统设计智慧的缩影：

- **byte 底层类型**：极致的内存效率，适应游戏高并发场景
- **零值初始化为 Pending**：利用语言特性消除初始化代码
- **三态简化**：砍掉 .NET Task 的复杂状态，专注于游戏需求
- **独立取消机制**：职责分离，保持状态机纯粹

小小的枚举，大大的设计。
