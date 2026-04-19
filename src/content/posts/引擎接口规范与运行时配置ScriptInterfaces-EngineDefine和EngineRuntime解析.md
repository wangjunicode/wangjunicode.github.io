---
title: 引擎接口规范与运行时配置——ScriptInterfaces、EngineDefine 和 EngineRuntime 解析
published: 2026-03-31
description: 解析框架中的脚本接口规范体系、引擎常量定义类和运行时状态管理类，理解定点数时间、确定性随机数以及多平台条件编译的工程实践。
tags: [Unity, ECS, 接口规范, 确定性随机, 定点数]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 引擎接口规范与运行时配置——ScriptInterfaces、EngineDefine 和 EngineRuntime 解析

## 前言

框架中有一些"定义层"的文件——它们不实现复杂逻辑，但为整个系统提供基础定义和运行时配置。今天我们来分析三个这样的文件：

- `ScriptInterfaces.cs`：脚本系统的接口规范
- `EngineDefine.cs`：引擎常量和全局配置
- `EngineRuntime.cs`：运行时状态和确定性随机数

---

## 一、ScriptInterfaces——脚本系统的标记接口体系

```csharp
namespace xgame.Framework
{
    // 用于泛型脚本 handler 实例化
    public interface IGenericEvtScriptHandler { }
    
    // 用于 blackboard 泛型脚本 handler 实例化
    public interface IBlackboardGenericScriptHandler { }
    
    // 黑板泛型脚本
    public interface IBlackboardGenericScript { }

    // 用于序列化泛型脚本
    public interface IGenericScript { }

    // 事件泛型脚本
    public interface IGenericEvtScript { }

    // 用于脚本序列化的事件参数
    public interface IScriptEventArg { }
    
    public interface IScriptNeedCheckEvent
    {
        bool check(IScriptNeedCheckEvent other);
    }
    
    public interface IPassiveEventArg : IScriptEventArg { }
    
    // 返回实际进度结果
    public interface IProgressScript
    {
        string GetProgress();
    }
}
```

### 1.1 命名空间 xgame.Framework

这里使用的是 `xgame.Framework` 命名空间，而非 `ET`。这暗示这是项目在 ET 框架基础上的自定义扩展层（xgame 是项目代号）。

这些接口都是用于**可视化脚本系统**（Visual Scripting）的标记接口，用于：
- 行为树节点（Blackboard 是行为树中的共享数据）
- 事件处理脚本
- 泛型脚本实例化

### 1.2 IScriptNeedCheckEvent——有逻辑的标记接口

```csharp
public interface IScriptNeedCheckEvent
{
    public bool check(IScriptNeedCheckEvent other);
}
```

这个接口不是空的，它有一个 `check` 方法——用于检查两个事件是否"同类"或"匹配"。

在事件系统中，某些事件不应该重复触发（比如"进入区域"事件，已经在区域里了就不再触发）。`check` 方法可以判断"待触发的事件是否与已处理的事件相同，不需要再次处理"。

### 1.3 IPassiveEventArg——被动事件参数

```csharp
public interface IPassiveEventArg : IScriptEventArg { }
```

`IPassiveEventArg` 继承自 `IScriptEventArg`，添加了"被动"的语义。

在游戏逻辑中，事件可以分为：
- **主动事件**：玩家主动触发（攻击、使用技能）
- **被动事件**：外部条件触发（受到伤害、进入范围）

通过接口继承区分两者，方便在处理时过滤。

---

## 二、EngineDefine——引擎常量的集中定义

```csharp
public class EngineDefine
{
    // 逻辑帧率（60FPS）
    public const int FPS = 60;
    
    // 时间缩放系统
    public static FP logicTimeScale = FP.One;   // 逻辑时间缩放
    public static FP editorTimeScale = FP.One;  // 编辑器时间缩放
    public static FP timeScale => logicTimeScale * editorTimeScale; // 合并缩放
    
    // 帧间隔时间（定点数）
    public static readonly FP fixedDeltaTime_Orignal = (FP)0.016667f; // 约 1/60 秒
    public static FP fixedDeltaTime => fixedDeltaTime_Orignal * timeScale;
    public static FP deltaTime => Game.deltaTime * timeScale;
    
    // 网络配置
    public static bool UseIPv6 = false;
    public static bool CheckUDPRemoteIP = true;
    
    // 调试和性能选项
    public static bool DeepProfileMode = false;
    public static bool DisablePreload = false;
    
    // 热更新检测
#if !UNITY_EDITOR && !UNITY_STANDALONE
    public static bool isHybridCLR = true;  // 手机平台使用 HybridCLR 热更新
#else
    public static bool isHybridCLR = false; // 编辑器和 PC 不用热更新
#endif
}
```

### 2.1 fixedDeltaTime_Orignal = 0.016667f

`1/60 ≈ 0.016667`，这是 60FPS 的帧间隔时间。

使用定点数 `FP` 而非 `float`，保证帧同步的确定性：

```csharp
public static readonly FP fixedDeltaTime_Orignal = (FP)0.016667f;
```

`FP` 类型在所有平台上产生相同的计算结果，`float` 则可能因 CPU 架构不同产生微小差异。

### 2.2 双时间缩放

```csharp
public static FP logicTimeScale = FP.One;   // 程序控制的时间缩放
public static FP editorTimeScale = FP.One;  // 编辑器测试用的时间缩放
public static FP timeScale => logicTimeScale * editorTimeScale;
```

两个时间缩放相乘：
- 开发时，编辑器可以设置 `editorTimeScale = 2`，游戏以 2x 速度运行，方便测试
- 游戏内有"慢动作"效果时，设置 `logicTimeScale = 0.5`
- 两者独立，不互相干扰

### 2.3 HybridCLR 条件编译

```csharp
#if !UNITY_EDITOR && !UNITY_STANDALONE
    public static bool isHybridCLR = true;
#else
    public static bool isHybridCLR = false;
#endif
```

HybridCLR 是 Unity 的 AOT 热更新方案（类似 ILRuntime 的继任者）。

在手机（iOS/Android）上必须用 HybridCLR 才能支持热更新代码；在编辑器和 PC 上直接运行原生代码，不需要 HybridCLR。

这个 bool 值让框架知道当前运行模式，可以做相应的适配（比如热更时如何加载程序集）。

---

## 三、EngineRuntime——运行时的可变状态

```csharp
public class EngineRuntime
{
    public static bool Pause;   // 游戏是否暂停
    public static int Seed;     // 随机数种子

    private TSRandom m_random;
    public TSRandom random => m_random;

    public EngineRuntime(int seed)
    {
        Seed = seed;
        m_random = TSRandom.New(seed);
    }

    public void SetRandomSeed(int seed)
    {
        Seed = seed;
        m_random = TSRandom.New(Seed);
    }

    public int GetRandomTime()
    {
        return m_random.CallTime;
    }
}
```

### 3.1 确定性随机数——TSRandom

```csharp
private TSRandom m_random;
```

`TSRandom` 是 TrueSync 库提供的**确定性随机数生成器**（Deterministic RNG）。

**为什么普通的 `System.Random` 不够用？**

在帧同步游戏中，所有客户端必须产生完全相同的随机数序列。`System.Random` 使用系统时间作为默认种子，不同客户端产生不同的随机数，会导致游戏状态分叉（不同步）。

`TSRandom` 使用固定的 `Seed`，只要种子相同，所有客户端的随机数序列完全一致。

**随机数同步的关键**：所有客户端使用同一个 `Seed` 初始化，然后每次调用随机数时，所有客户端调用同样次数（`CallTime`），产生的结果完全一致。

### 3.2 GetRandomTime——追踪调用次数

```csharp
public int GetRandomTime()
{
    return m_random.CallTime;
}
```

`CallTime` 记录了随机数被调用的总次数。

这个值在帧同步调试中非常有用：如果两个客户端的 `CallTime` 不同，说明某处代码调用了不应该调用的随机数，导致序列偏移。

### 3.3 Pause——全局暂停标志

```csharp
public static bool Pause;
```

游戏暂停状态是静态字段，全局共享。

前面分析 `LogicTimerComponent` 时看到它的使用：

```csharp
public void BeforeFixedUpdate()
{
    if (!EngineRuntime.Pause)
    {
        Update(); // 暂停时不更新定时器
    }
}
```

所有需要响应暂停的系统都检查这个标志。

**为什么是静态字段而非单例属性？**

静态字段访问没有额外的对象访问开销，而暂停状态是"游戏级别的全局状态"，用静态字段最简洁。

---

## 四、三个文件的协作

```
EngineDefine（常量）
    提供：FPS = 60, fixedDeltaTime_Orignal, timeScale
         
EngineRuntime（运行时状态）
    提供：Pause, Seed, m_random
    依赖：EngineDefine.fixedDeltaTime_Orignal（帧时间）

Game（调度中心）
    依赖：EngineDefine.fixedDeltaTime_Orignal（计算 FixedTime）
    依赖：EngineRuntime.Pause（定时器暂停检查）
```

---

## 五、写给初学者

这三个文件体现了一个重要的工程实践：

**把"什么是常量"和"什么是变量"分清楚。**

- `EngineDefine`：大部分是常量或几乎不变的值（帧率、帧间隔）
- `EngineRuntime`：运行时可变状态（暂停、随机数状态）

把这两类数据混在一起（比如都放在一个 `GameManager` 单例里）会导致：
- 难以测试（每次测试都要手动重置所有状态）
- 难以定位 Bug（哪里改了哪个值？）
- 难以热更新（常量和变量混在一起，热更时不好处理）

分开定义，关注点分离，代码更清晰。
