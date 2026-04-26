---
title: 游戏框架ISingletonFixedUpdate三段式物理帧驱动接口设计深度解析
published: 2026-04-26
description: 深入解析ET/ECS框架中ISingletonFixedUpdate接口的BeforeFixedUpdate、FixedUpdate、LateFixedUpdate三段式设计，剖析Game静态类物理帧调度的完整流程，以及与帧同步战斗、物理模拟、定点数时间轴的工程结合实践。
tags: [Unity, ECS, 游戏框架, C#, 物理帧, 帧同步]
category: 技术
draft: false
encryptedKey: henhaoji123
---

## 前言

Unity 的物理更新（`FixedUpdate`）提供了一个与渲染帧解耦的固定时间步长调用入口，是帧同步战斗、物理模拟、定点数逻辑计时的黄金场所。ET/ECS 框架在此基础上更进一步，将物理帧拆分为**三个阶段**：`BeforeFixedUpdate`、`FixedUpdate`、`LateFixedUpdate`，形成完整的物理帧生命周期管道。本文从源码出发，深度解析这套三段式设计的动机、实现与工程价值。

---

## 一、接口定义

```csharp
public interface ISingletonFixedUpdate
{
    void BeforeFixedUpdate();
    void FixedUpdate();
    void LateFixedUpdate();
}
```

与 `ISingletonUpdate` 的单方法设计不同，`ISingletonFixedUpdate` 一次性定义了三个回调，强制实现者关注物理帧的完整生命周期，而非只处理"主体逻辑"。

---

## 二、Game 静态类中的注册与调度

### 注册阶段

```csharp
public static void AddSingleton(ISingleton singleton)
{
    // ...
    if (singleton is ISingletonFixedUpdate)
    {
        beforeFixedUpdates.Enqueue(singleton);
        fixedUpdates.Enqueue(singleton);
        lateFixedUpdates.Enqueue(singleton);
    }
}
```

一个单例如果实现了 `ISingletonFixedUpdate`，会**同时**被加入三个独立队列：`beforeFixedUpdates`、`fixedUpdates`、`lateFixedUpdates`。三个队列分别对应三个调度时机，彼此完全独立。

### 调度阶段

```csharp
// 第一阶段：物理帧前置准备
public static void BeforeFixedUpdate()
{
    FixedFrames++;
    FixedTime = FixedFrames * EngineDefine.fixedDeltaTime_Orignal;
    // 遍历 beforeFixedUpdates 队列...
    update.BeforeFixedUpdate();
}

// 第二阶段：物理帧主逻辑
public static void FixedUpdate()
{
    // 遍历 fixedUpdates 队列...
    update.FixedUpdate();
}

// 第三阶段：物理帧后处理
public static void LateFixedUpdate()
{
    // 遍历 lateFixedUpdates 队列...
    update.LateFixedUpdate();
}
```

---

## 三、三个阶段的职责划分

### BeforeFixedUpdate：时间基准推进 + 输入准备

```csharp
public static void BeforeFixedUpdate()
{
    FixedFrames++;
    FixedTime = FixedFrames * EngineDefine.fixedDeltaTime_Orignal;
    // ...
}
```

**框架在调用任何单例的 `BeforeFixedUpdate` 前，首先推进帧计数和定点时间**：

| 字段 | 类型 | 含义 |
|------|------|------|
| `FixedFrames` | `int` | 物理帧计数，自游戏启动单调递增 |
| `FixedTime` | `FP`（定点数）| 当前物理时刻 = 帧数 × 固定步长 |

使用定点数 `FP` 而非 `float` 是帧同步战斗的基础要求——所有客户端在相同 `FixedFrames` 下，`FixedTime` 严格相等，消除浮点误差。

**单例在 `BeforeFixedUpdate` 中的典型工作：**
- 收集当前帧的输入指令（来自网络或本地）
- 重置"脏标记"或帧级别的临时状态
- 同步全局配置（如慢动作倍率应用到 `FixedTime`）

### FixedUpdate：物理与逻辑主体

这是物理帧的核心阶段，所有确定性逻辑在此执行：

**适合在 `FixedUpdate` 中做的事：**
- 碰撞检测与伤害计算（基于 `FixedTime` 的确定性结果）
- 帧同步战斗指令消费（消费 BeforeFixedUpdate 中收集的指令）
- 定点数物理模拟（位置、速度积分）
- Buff/技能冷却的 Tick 推进
- AI 决策计算

```csharp
// 示例：帧同步战斗 Tick
public class BattleSystem : Singleton<BattleSystem>, ISingletonFixedUpdate
{
    public void BeforeFixedUpdate()
    {
        // 收集本帧所有网络指令
        CollectNetworkCommands(Game.FixedFrames);
    }
    
    public void FixedUpdate()
    {
        // 消费指令，推进战斗逻辑
        ProcessCommands(Game.FixedFrames, Game.FixedTime);
        UpdatePhysics(Game.FixedTime);
        UpdateSkillCooldowns(Game.FixedTime);
    }
    
    public void LateFixedUpdate()
    {
        // 发送本帧结果到服务器或录像系统
        SnapshotFrameResult(Game.FixedFrames);
    }
}
```

### LateFixedUpdate：结果同步 + 后处理

物理帧所有主逻辑执行完毕后，`LateFixedUpdate` 用于：

- **状态快照**：将本帧的确定性状态打包，用于回放/录像
- **网络同步**：向服务端或其他客户端发送本帧结果
- **视图更新通知**：通知渲染层（非确定性）本帧逻辑结果
- **事件清理**：清理本帧产生的一次性事件队列

---

## 四、三队列独立的设计价值

注册时，同一单例被加入**三个独立队列**，而非一个队列。这看似冗余，实则关键：

```csharp
beforeFixedUpdates.Enqueue(singleton);  // 独立队列1
fixedUpdates.Enqueue(singleton);        // 独立队列2
lateFixedUpdates.Enqueue(singleton);    // 独立队列3
```

**好处：**

1. **销毁安全**：某单例在 `FixedUpdate` 中被销毁（`IsDisposed()==true`），其 `LateFixedUpdate` 调用会被安全跳过，不会访问已释放对象
2. **多系统顺序可控**：三个队列的遍历彼此独立，可分别控制各阶段的系统执行顺序
3. **未来可扩展**：理论上可为特定阶段插入优先级排序，而不影响其他阶段

---

## 五、FixedFrames 与 FixedTime 的工程意义

```csharp
public static FP FixedTime;
public static int FixedFrames;
```

这两个字段是框架全局共享的"帧同步时钟"：

### FixedFrames：帧序号，用于同步边界

```csharp
// 在任意系统中可通过 Game.FixedFrames 获取当前物理帧序号
if (Game.FixedFrames % 60 == 0)
{
    // 每60物理帧（约1秒）执行一次的逻辑
    PeriodicSync();
}
```

### FixedTime：确定性时间轴

```csharp
FixedTime = FixedFrames * EngineDefine.fixedDeltaTime_Orignal;
```

`fixedDeltaTime_Orignal` 是固定步长（通常为 `FP.FromFloat(0.016666f)`，即约 60Hz），`FixedTime` 的计算完全基于整数 `FixedFrames` 和常量，**两个客户端在相同帧号下 `FixedTime` 必然相等**，这是帧同步的数学基础。

---

## 六、与 Update 调度的对比

| 特性 | ISingletonUpdate | ISingletonFixedUpdate |
|------|-----------------|----------------------|
| 调用频率 | 每渲染帧（不定） | 固定时间步长（定期）|
| 阶段数 | 1（Update） | 3（Before/Fixed/Late） |
| 时间参考 | `Game.deltaTime` | `Game.FixedTime`（定点数）|
| 确定性 | 否（帧率依赖） | 是（固定步长+定点数）|
| 适用场景 | UI、渲染、非确定性逻辑 | 战斗、物理、帧同步逻辑 |

---

## 七、实战：LogicTimerComponent 的三阶段适配

框架中的帧同步定时器 `LogicTimerComponent` 就是 `ISingletonFixedUpdate` 的典型实现者：

```csharp
public class LogicTimerComponent : Singleton<LogicTimerComponent>, ISingletonFixedUpdate
{
    public void BeforeFixedUpdate()
    {
        // 更新当前帧时间基准
        currentFrame = Game.FixedFrames;
    }
    
    public void FixedUpdate()
    {
        // 检查并触发到期的定时器回调
        TickTimers(Game.FixedTime);
    }
    
    public void LateFixedUpdate()
    {
        // 清理本帧已触发的一次性定时器
        CleanupFiredTimers();
    }
}
```

这种三段式分工让定时器的"准备 → 执行 → 清理"各阶段边界清晰，避免在 `FixedUpdate` 主体中处理已失效对象。

---

## 八、总结

`ISingletonFixedUpdate` 的三段式设计是 ET/ECS 框架物理帧调度的精华所在：

- **BeforeFixedUpdate** 是时间基准推进和输入准备的专用阶段，与帧同步时钟的更新紧密耦合
- **FixedUpdate** 是确定性逻辑的主战场，所有帧同步计算在此发生
- **LateFixedUpdate** 是物理帧的"收尾工人"，承担快照、同步、清理等收尾职责

三个独立队列的设计保证了各阶段的安全性和可扩展性，配合定点数 `FixedTime` 和整数 `FixedFrames`，为帧同步战斗提供了严密的时间确定性保障。理解这套三段式管道，是掌握 ET/ECS 框架物理帧驱动的关键一步。
