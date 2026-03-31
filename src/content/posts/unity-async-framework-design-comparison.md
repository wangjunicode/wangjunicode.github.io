---
title: 自研异步框架与主流开源方案的设计取舍深度对比
published: 2026-03-31
description: 系统对比两套 Unity 异步框架的核心设计思路、性能特征和适用场景，帮助你理解为什么不同项目会选择不同的技术方案。
tags: [Unity, 异步编程, 架构设计, 性能优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么要做这个对比？

UniTask 是 Unity 社区最流行的开源异步框架，被数百个商业游戏项目采用，GitHub Star 数量超过 5000。ETTask 是我们项目自研的轻量级替代方案。

新人加入项目时经常问：**为什么不直接用 UniTask？自研是不是在重复造轮子？**

这是一个很好的问题。技术选型从来不是"哪个更好"，而是"在特定约束下，哪个更适合"。这篇文章尝试系统地回答这个问题。

---

## 两者的共同出发点

UniTask 和 ETTask 解决的是**同一个问题**：

> 在 Unity 的单线程游戏主循环中，如何用 `async/await` 语法实现高性能、零 GC 的异步操作？

两者都：
- 通过 `[AsyncMethodBuilder]` 特性接入 C# 编译器
- 使用对象池减少 GC
- 设计为在主线程运行，不做线程切换
- 提供 `await` Unity 的 `AsyncOperation`（如 `Resources.LoadAsync`）

不同的是，它们在某些设计决策上走了不同的路。

---

## 核心架构差异

### 1. 任务对象的类型

**UniTask**：使用值类型（struct）封装

```csharp
// UniTask 是结构体！
public readonly struct UniTask
{
    private readonly IUniTaskSource source;
    private readonly short token;
    // ...
}
```

UniTask 本身是 struct（值类型），存在栈上，不分配堆内存。内部通过 `IUniTaskSource` 接口指向真正的任务状态。

**ETTask**：使用引用类型（class）

```csharp
// ETTask 是类！
public class ETTask : ICriticalNotifyCompletion, IETTask
{
    private AwaiterStatus state;
    private object callback;
    // ...
}
```

ETTask 是 class（引用类型），通过对象池复用来避免 GC。

**影响**：
- UniTask 的设计在**已完成**的情况下完全零分配（struct 在栈上）
- ETTask 在对象池热后也接近零分配，但首次使用会 new
- UniTask 的 struct 设计不能持有引用，有时需要通过 AutoResetUniTaskCompletionSource 等辅助类
- ETTask 作为 class 可以直接持有 callback 引用，API 更直接

### 2. 上下文传播机制

**ETTask**：内置 Context 链

```csharp
// ETTask 有 Context 和 TaskType 字段
public TaskType TaskType { get; set; }
public object Context { get; set; }

// 可以在异步链中隐式传递任意对象
await someTask.WithContext(myCharacter);

// 深层方法获取
var character = await ETTaskHelper.GetContextAsync<Character>();
```

这是 ETTask 独有的特性，UniTask 没有类似设计。

**UniTask**：不支持隐式上下文传播

UniTask 遵循"参数显式传递"的原则，没有隐式上下文机制。

**影响**：
- ETTask 的 Context 在某些架构中非常便利（如 ECS 的 Entity 传递）
- 但 Context 也增加了隐式依赖，降低了函数纯粹性
- UniTask 更符合函数式编程原则

### 3. 取消机制

**ETTask**：自定义 `ETCancellationToken`

```csharp
// 极简实现，仅用 HashSet<Action>
public class ETCancellationToken
{
    private HashSet<Action> actions = new();
    public void Cancel() { ... }
    public bool IsDispose() { ... }
}
```

**UniTask**：支持标准 `CancellationToken`

```csharp
// 兼容 C# 标准取消机制
public async UniTask SomeWork(CancellationToken cancellationToken)
{
    await UniTask.Delay(1000, cancellationToken: cancellationToken);
}

// 触发 OperationCanceledException
```

**影响**：
- UniTask 和 C# 标准库更好地互操作
- ETCancellationToken 更轻量，但不与标准库兼容
- UniTask 的取消会抛 `OperationCanceledException`，可以统一 try-catch
- ETTask 的取消是"隐式结束"，需要主动检查 `IsCancel()`

### 4. PlayerLoop 集成

**UniTask**：深度集成 Unity PlayerLoop

```csharp
// UniTask 可以精确指定在哪个 PlayerLoop 阶段执行
await UniTask.Yield(PlayerLoopTiming.Update);
await UniTask.Yield(PlayerLoopTiming.FixedUpdate);
await UniTask.Yield(PlayerLoopTiming.EarlyUpdate);
// 提供 14+ 个时间点
```

**ETTask**：不直接集成 PlayerLoop

ETTask 主要通过计时器组件（TimerComponent）和外部的 AsyncOperation 桥接来实现帧等待：

```csharp
// 通过扩展方法桥接 Unity 异步操作
public static async ETTask GetAwaiter(this AsyncOperation asyncOperation)
{
    ETTask task = ETTask.Create(true);
    asyncOperation.completed += _ => { task.SetResult(); };
    await task;
}
```

**影响**：
- UniTask 在 Unity 生命周期控制上更精细
- ETTask 更简单，但缺少精确的 PlayerLoop 控制点
- 对于需要精确控制执行时机（物理更新、渲染前等）的场景，UniTask 更合适

---

## 功能特性对比

| 特性 | ETTask | UniTask |
|------|--------|---------|
| 零 GC（热路径） | ✅ 对象池 | ✅ struct + 对象池 |
| await Task（C# 标准） | ❌ | ✅ |
| await AsyncOperation | ✅（手动桥接） | ✅（内置） |
| await coroutine | ❌ | ✅ |
| 多任务 WhenAll/WhenAny | ✅（WaitAll/WaitAny） | ✅（UniTask.WhenAll/WhenAny） |
| 取消令牌 | ✅（自定义） | ✅（兼容标准） |
| Context 传播 | ✅（独有） | ❌ |
| PlayerLoop 集成 | ❌ | ✅（14+ 时间点） |
| 异步 LINQ | ❌ | ✅ |
| dotnet 环境支持 | ❌（仅 Unity） | ✅ |
| 代码量 | 约 500 行 | 约 15000 行 |

---

## 性能维度对比

### 理论上的差异

**ETTask**（class + 对象池）：
- 冷启动（池空）：1 次堆分配
- 热路径（池命中）：0 次堆分配
- 装箱：通过 StateMachineWrap 避免

**UniTask**（struct + 对象池）：
- 已完成任务：0 次堆分配（struct 在栈上）
- 真正异步任务：通过 AutoResetUniTaskCompletionSource 对象池，0-1 次
- 装箱：通过 IUniTaskSource 接口避免

理论上，UniTask 的 struct 设计在"立即完成"场景下更优（真正零分配），而 ETTask 的对象池在真正异步场景下性能相近。

### 实际差异极小

在现代 CPU 上，两者的性能差异在微秒级别，对游戏帧率几乎没有感知。真正影响性能的往往是**业务逻辑本身**（资源加载、网络、复杂运算），而不是异步框架的开销。

---

## 自研的真正价值

既然 UniTask 功能更全，为什么还要自研？这个问题值得认真回答。

### 1. 架构控制权

自研意味着可以在框架中添加**项目特有的功能**，比如：

- **Context 传播**：UniTask 没有这个设计，但项目架构需要
- **与 ET 框架的深度集成**：ETTask 与 EntityComponent 系统无缝配合
- **定制化的对象池**：按照项目实际并发量调整池大小

### 2. 依赖最小化

UniTask 是一个功能丰富的框架（15000 行代码），引入了大量项目不需要的功能。

ETTask 约 500 行代码，每一行都在项目中被使用，没有多余的代码路径。对于定制化程度高的框架项目，**精简的依赖减少了理解和维护成本**。

### 3. 学习价值

自研框架是最好的学习机会。框架开发者需要深入理解：
- C# async/await 编译器协议
- 对象池设计
- 内存管理和 GC 优化
- Unity 与 C# 运行时的交互

这些知识是每个高级游戏程序员的必备技能。

### 4. 特定约束下的选择

如果项目使用 HybridCLR（热更新框架），UniTask 的某些特性（特别是值类型状态机优化）可能与 HybridCLR 的代码生成存在兼容性问题。自研框架可以精确控制与 HybridCLR 的兼容边界。

---

## 什么时候应该选 UniTask？

- 新项目，没有特殊架构要求
- 团队熟悉 UniTask，有现成的集成经验
- 需要 PlayerLoop 精确控制（如帧对齐的物理操作）
- 需要与 C# 标准 Task 互操作
- 团队规模大，需要有社区支持的成熟方案

## 什么时候自研或使用类 ETTask 方案？

- 项目有特殊架构需求（如 ECS、帧同步）
- 需要与特定框架（如 ET、热更新）深度集成
- 团队有足够能力维护框架代码
- 功能简单场景，不想引入重量级依赖

---

## 总结

ETTask 和 UniTask 代表了两种不同的工程哲学：

**ETTask**：最小可行原则。够用就好，每行代码都有其存在理由，通过精心设计的 Context 传播实现框架特有的能力。

**UniTask**：功能完备原则。尽可能兼容标准，提供丰富特性，深度集成 Unity 生态。

没有绝对的好坏。了解两者的设计取舍，才能在实际项目中做出合理的选择——这才是技术负责人应有的判断力。

对于正在学习的新手，建议：
1. 先深入理解 ETTask（代码少，更容易读懂）
2. 再看 UniTask 的源码（会发现很多共通的思路）
3. 最终能够自己评估何时需要什么
