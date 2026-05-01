---
title: 游戏框架EngineDefine与EngineRuntime运行时常量与确定性随机数种子管理深度解析
published: 2026-05-01
description: '深度解析 xGame 框架中 EngineDefine 静态配置类与 EngineRuntime 运行时状态类的设计哲学，涵盖帧率常量、多层 TimeScale 叠加、IPv6 优先策略、HybridCLR 平台分支，以及 TSRandom 确定性随机数种子管理机制，揭示帧同步游戏客户端配置层的核心设计模式。'
image: ''
tags: [Unity, 游戏框架, xGame, 帧同步, 确定性随机数, EngineDefine, TrueSync]
category: '技术分析'
draft: false
lang: ''
encryptedKey: henhaoji123
---

## 引言

在一个帧同步游戏框架里，"配置"和"运行时状态"是两种本质不同的东西。`EngineDefine` 和 `EngineRuntime` 这对组合，正是 xGame 框架对这个区分的具体落地。

- `EngineDefine`：全局静态常量 + 可调 Flag，描述"这个引擎以什么规则运行"
- `EngineRuntime`：运行时实例，持有"这局游戏的当前状态"

两者共同构成帧同步客户端的"宪法"与"执法机关"。

---

## EngineDefine：引擎的静态"宪法"

```csharp
public class EngineDefine
{
    public const int FPS = 60;
    public static FP logicTimeScale = FP.One;
    public static FP editorTimeScale = FP.One;
    public static FP timeScale => logicTimeScale * editorTimeScale;
    
    public static FP fixedDeltaTime => fixedDeltaTime_Orignal * timeScale;
    public static FP deltaTime => Game.deltaTime * timeScale;
    
    public static readonly FP fixedDeltaTime_Orignal = (FP)0.016667f;
    ...
}
```

### 1. FPS 常量与定点数 deltaTime

`FPS = 60` 是逻辑帧率的"宪法条款"——整个帧同步体系的时间基准。注意 `fixedDeltaTime_Orignal = (FP)0.016667f`，这里用的是 TrueSync 的 `FP`（Fixed-Point）定点数，而不是 C# 的 `float`。

**为什么用定点数？**

浮点数在不同 CPU 架构、编译器优化开关下计算结果可能微妙不同，帧同步游戏要求所有客户端每帧计算完全一致，所以物理/逻辑层统一用 `FP` 定点数。`0.016667f` 对应 1/60 秒，但直接写 `FP.One / 60` 在某些版本的 TrueSync 实现里精度更差，这里选择直接用近似小数转换。

### 2. 双层 TimeScale 设计

```csharp
public static FP logicTimeScale = FP.One;   // 游戏逻辑层控制（慢动作、暂停）
public static FP editorTimeScale = FP.One;  // 编辑器调试用
public static FP timeScale => logicTimeScale * editorTimeScale;
```

两个 Scale 相乘，而非同一个变量，这是很精妙的设计：

- `logicTimeScale`：运行时可以被游戏逻辑修改（比如Boss战慢动作），会影响正式的帧同步运算
- `editorTimeScale`：只在开发调试时用，用于在不影响逻辑的情况下让游戏快跑/慢跑以便观察
- 两者分开，避免调试操作污染逻辑状态

```csharp
// 逻辑层 deltaTime（受 timeScale 影响）
public static FP fixedDeltaTime => fixedDeltaTime_Orignal * timeScale;

// 相机/渲染层 deltaTime（ONLY_CLIENT 宏保护）
#if ONLY_CLIENT
public static FP cameraFixedDeltaTime => Time.unscaledDeltaTime * timeScale;
#endif
```

`cameraFixedDeltaTime` 用的是 Unity 的 `Time.unscaledDeltaTime`（不受 Unity TimeScale 影响的真实时间），再乘以自己的 `timeScale`，实现了相机动画与引擎物理节拍的解耦。

### 3. 网络策略 Flag

```csharp
public static bool UseIPv6 = false;
public static bool CheckUDPRemoteIP = true;
```

`UseIPv6` 默认关闭，只在系统支持且 DNS 解析出 v6 时才启用，这是移动端游戏的常见保守策略——IPv6 在部分运营商环境下并不稳定。

`CheckUDPRemoteIP` 是 UDP 下行包的来源 IP 校验开关，防止伪造服务端地址的 UDP 劫持攻击。

### 4. 平台宏与热更标志

```csharp
#if !UNITY_EDITOR && !UNITY_STANDALONE
    public static bool isHybridCLR = true;
#else
    public static bool isHybridCLR = false;
#endif
```

这个宏的逻辑是：移动端（iOS/Android）开启 HybridCLR 热更，Editor 和 PC 发行版不走热更路径（方便开发和 PC 版上架）。

### 5. 编辑器专属配置

```csharp
#if UNITY_EDITOR
    public static bool EnableShelveCommit {
        get => PlayerPrefs.GetInt("EnableShelveCommit", 0) != 0;
        set => PlayerPrefs.SetInt("EnableShelveCommit", value ? 1 : 0);
    }
    public static string SvnCommitCmd => EnableShelveCommit ? "gfshelf" : "commit";
    
    public const string AssetsMobile = "Assets_Mobile";
    public static bool EnableAssetsMobile = false;
#endif
```

`PlayerPrefs` 持久化 SVN shelve 模式开关，团队中不同成员可以独立设置自己的提交习惯，不影响其他人。`AssetsMobile` 支持切换移动端资源目录，方便在 PC Editor 里验证移动端资源包。

---

## EngineRuntime：运行时"执法机关"

```csharp
public class EngineRuntime
{
    public static bool Pause;
    public static int Seed;

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

### 1. 确定性随机数的核心：种子机制

`TSRandom` 是 TrueSync 提供的确定性伪随机数生成器，只要种子相同，`CallTime`（调用次数）相同，任意时刻生成的随机数序列必然一致。

这是帧同步最核心的约束之一：**不允许使用非确定性随机源**（比如 `UnityEngine.Random.value`、`System.Random` 无种子构造）。所有随机行为必须走 `EngineRuntime.random`。

```
Round 开始
    ↓
服务器下发 Seed
    ↓
所有客户端以相同 Seed 构造 TSRandom
    ↓
每帧每个随机调用产生完全相同序列
    ↓
所有客户端游戏状态始终一致
```

### 2. SetRandomSeed 的语义

`SetRandomSeed` 不只是"修改种子"，它还会重建整个 `TSRandom` 实例，重置调用计数为 0。这意味着调用此方法会让随机数序列从头开始，适用于以下场景：

- **局内重置**：加载存档、回放时从某个快照节点恢复
- **调试回放**：记录 Seed 后用同一 Seed 复现 Bug

### 3. GetRandomTime 的审计价值

```csharp
public int GetRandomTime()
{
    return m_random.CallTime;
}
```

`CallTime` 是 `TSRandom` 内部维护的调用次数计数器。暴露这个方法的意义在于**同步检测**：两个客户端在同一帧结束时，`GetRandomTime()` 返回值应该完全一样。如果不一致，说明某个客户端多/少调用了随机数，存在逻辑分叉。这是帧同步调试中极有价值的一项指标。

### 4. Pause 的静态设计

```csharp
public static bool Pause;
```

`Pause` 是静态字段而非实例字段，意味着它是全局唯一的暂停状态，与 `EngineRuntime` 实例无关。这样即使还没有创建 `EngineRuntime`（游戏局尚未开始），也可以设置暂停标志。

---

## 两者的配合关系

| 维度 | EngineDefine | EngineRuntime |
|------|-------------|---------------|
| 生命周期 | 全程静态 | 每局游戏实例化 |
| 修改频率 | 开发/调试时 | 运行时按需 |
| 数据类型 | 常量、Flag | 有状态对象（随机数） |
| 线程安全 | 无要求 | 局限于逻辑帧线程 |

典型的使用路径如下：

```csharp
// 游戏开始时，服务器下发种子
var runtime = new EngineRuntime(serverSeed);
Game.SetRuntime(runtime);

// 逻辑帧内需要随机时
var damage = Game.Runtime.random.Next(minDamage, maxDamage);

// 每帧末尾做同步校验（可选）
int callTime = Game.Runtime.GetRandomTime();
SyncChecker.Verify(frame, callTime);
```

---

## 设计启示

1. **定点数而非浮点数**：帧同步的物理/逻辑层不能妥协，`FP` 类型虽然有性能开销，但正确性第一。

2. **双层 TimeScale 解耦**：调试需求和运行时需求用不同变量承载，两者相乘，互不污染。

3. **随机数审计接口**：`GetRandomTime()` 这种暴露内部调用计数的设计，是帧同步调试的重要工具，不是多余的。

4. **Pause 全局静态**：暂停逻辑不依赖游戏局的存在，设计为静态字段更合理。

5. **平台宏集中管理**：将 `isHybridCLR` 这类平台判断收拢到 `EngineDefine`，避免代码库中散落大量 `#if` 判断。

---

## 小结

`EngineDefine` 和 `EngineRuntime` 是 xGame 框架的"地基"——一个定义规则，一个持有状态。它们的设计简洁到极致，但每个字段背后都有实实在在的工程考量。理解这两个类，就理解了这个帧同步客户端为什么能跑得稳、调得明、测得透。
