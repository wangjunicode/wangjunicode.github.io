---
title: 07 帧同步锁步（LockStep）方案
published: 2024-01-01
description: "07 帧同步锁步（LockStep）方案 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# 07 帧同步锁步（LockStep）方案

> 本文介绍战斗系统中的帧同步机制，讲解如何保证多个客户端在同一战斗中的状态完全一致，以及确定性、输入同步、哈希校验等核心技术点。

---

## 1. 系统概述

帧同步（LockStep / Deterministic Lockstep）是一种多人游戏同步方案：所有客户端**不同步游戏状态，只同步玩家输入**。每个客户端在收到所有玩家的输入后，按照完全相同的顺序执行计算，得到完全相同的结果——前提是游戏逻辑必须是**确定性（Deterministic）**的。

### 1.1 帧同步 vs 状态同步

| 对比维度 | 帧同步（LockStep） | 状态同步 |
|---------|------|------|
| 同步内容 | 玩家输入（VKey） | 游戏状态（坐标/血量/技能） |
| 网络流量 | 极低 | 较高 |
| 一致性保证 | 逻辑层 100% 一致 | 依赖服务端权威 |
| 断线重连 | 需要快速追帧 | 直接同步最新状态 |
| 适用场景 | 动作/格斗游戏 | MMORPG/休闲游戏 |

本项目选择帧同步方案，因为：
1. 动作战斗游戏的碰撞判定、连击时序需要严格的帧级别精度
2. 状态同步难以保证帧级别的打击感和技能时序

### 1.2 帧同步的前提：确定性

帧同步的核心要求是**所有参与计算的操作都是确定性的**：
- ✅ 相同输入 → 相同输出（无论在哪台机器上）
- ❌ 浮点数运算（不同硬件/编译器优化结果可能不同）
- ❌ `Dictionary` 的遍历顺序（不同运行时可能不同）
- ❌ `Random.Next()`（各端随机种子不同）
- ❌ 多线程并发（执行顺序不确定）

---

## 2. 架构设计

### 2.1 帧同步的基本流程

```
玩家输入（按下技能键）
    │
    ▼
客户端 A                              客户端 B
    │                                     │
    ▼                                     ▼
VKey（EInputKey.Skill_X）             VKey（EInputKey.Move_Left）
    │                                     │
    └──────────→ 服务器（收集) ←──────────┘
                    │
                    ▼
         广播所有客户端的输入
         （帧 N 的输入包：[A: Skill_X, B: Move_Left]）
                    │
         ┌──────────┘──────────┐
         ▼                     ▼
     客户端 A             客户端 B
   执行帧 N 逻辑          执行帧 N 逻辑
  （输入完全相同）        （输入完全相同）
         │                     │
         ▼                     ▼
     状态完全相同           状态完全相同 ✅
```

### 2.2 VKey 输入系统

`VKey`（Virtual Key，虚拟键）是帧同步中传输的最小单元，代表一个时刻的玩家操作：

```csharp
// VKeyDef.cs - PVP 相关的 VKey 常量定义
public class VKeyDef
{
    public const int PVP_ROUND_BEGIN = 402;          // 对局开始
    public const int PVP_ROUND_END = 403;            // 对局结束
    public const int PVP_BATTLE_END = 404;           // 战斗结束
    public const int PVP_AUTH = 405;                 // 身份验证
    public const int PVP_CONTROL_START = 407;        // 可以开始控制
    public const int PVP_SYNC_HASH = 502;            // 同步状态哈希（不同步检测）
    public const int PVP_SYNC_ERROR = 507;           // 不同步通知
    public const int PVP_CLIENT_BUFFERING_REPORT = 492; // 客户端 Buffer 统计
    public const int PVP_PING = 499;                 // Ping 上报

    // 判断是否是 PVP 逻辑 VKey（400~511 范围）
    static public bool IS_PVP_LOGIC_VKEY(int vkey)
    {
        return (vkey >= 400 && vkey <= 511);
    }
}
```

### 2.3 EInputKey 枚举 —— 技能/状态输入键

除了 `VKeyDef` 中的网络控制 VKey，还有 `EInputKey` 枚举描述战斗逻辑输入：

```csharp
// cfg.vkey.EInputKey（由 Luban 工具生成）
// 部分 Key 列举：
public enum EInputKey
{
    // 普通攻击输入
    NormalAtk,        // 普通攻击
    SkillA, SkillB, SkillC, SkillD,  // 技能键
    
    // 移动相关
    Move_Forward, Move_Back, Move_Left, Move_Right,
    Jump, Dodge,
    
    // 状态转移事件
    Host, UnHost,           // 出手权切换
    Hurt_Stiff,             // 僵直受击
    Hurt_Float,             // 浮空受击  
    Hurt_BreakDefense,      // 破防受击
    Hurt_Parry,             // 格挡成功
    Hurt_SwordPlay,         // 拼刀状态
    
    // ... 更多
    Max                     // 边界值
}
```

### 2.4 VKeyArgPool —— 参数对象池

VKey 通常携带参数（如移动方向、技能目标 ID 等），为了避免频繁 GC，参数数组使用对象池：

```csharp
public class VKeyArgPool
{
    public static VKeyArgPool Instance = new VKeyArgPool();
    
    // 分别维护 1~6 个参数长度的数组池
    private List<int[]> m_args1Pool = new List<int[]>();
    private List<int[]> m_args2Pool = new List<int[]>();
    // ...
    private List<int[]> m_args6Pool = new List<int[]>();

    // 获取克隆（传入现有数组，返回从池中取出的副本）
    public int[] GetArgsClone(int[] args) { ... }
    
    // 获取空数组（指定长度）
    public int[] GetArgs(int len) { ... }
    
    // 归还数组到池
    public void ReturnArgs(int[] args) { ... }
}
```

### 2.5 确定性保证措施

**① 定点数（Fixed-Point Number）**
```csharp
// 所有数值计算用 FP（TrueSync 定点数）替代 float
// FP 使用整数运算，在所有平台上结果完全一致
TSVector pos = new TSVector(FP.One, FP.Zero, FP.Zero);
FP distance = TSVector.Distance(posA, posB);  // 确定性距离计算
```

**② 确定性字典（DeterministicDictionary）**
```csharp
// 普通 Dictionary 的遍历顺序可能不同
// DeterministicDictionary 确保遍历顺序按插入顺序固定
public DeterministicDictionary<int, Unit> AllUnits { get; set; } = new();
```

**③ 确定性随机数**
```csharp
// 不使用 UnityEngine.Random（依赖系统随机种子）
// 战斗开始时用同一个种子初始化确定性随机数生成器
// 所有客户端种子相同 → 随机数序列相同
// 存储在 NumericComponent.RandExpFTimes 中记录随机调用次数（用于校验）
public DeterministicDictionary<EExpression, int> RandExpFTimes = new();
```

**④ 固定帧率（FixedUpdate）**
```csharp
// 战斗逻辑只在 FixedUpdate 中执行（固定帧率，不受渲染帧率影响）
// EngineDefine.fixedDeltaTime_Original 是固定的定点数常量
FP fixedDt = EngineDefine.fixedDeltaTime_Original; // 如 1/30 秒
```

### 2.6 哈希校验与不同步检测

```csharp
// VKeyDef 中的不同步相关 VKey
public const int PVP_SYNC_HASH = 502;   // 上报当前状态哈希
public const int PVP_SYNC_ERROR = 507;  // 不同步通知（包含时间戳/帧号）
```

每隔一定帧数，各客户端计算当前战斗状态的哈希值并上报，若不同步则通过 `PVP_SYNC_ERROR` 通知所有端，方便排查确定性问题。

哈希计算内容（典型）：
- 所有 Unit 的位置、朝向
- 所有 Unit 的关键数值（血量、AP等）
- 当前 FSM 状态
- Buff 列表

---

## 3. 核心代码展示

### 3.1 VKeyDef.cs —— 完整 PVP VKey 定义

```csharp
public class VKeyDef
{
    // 策略卡操作
    public const int PVP_CHANGE_TACTIC_START = 100;   // 开始调整策略卡
    public const int PVP_CHANGE_TACTIC_END = 101;     // 结束调整策略卡
    public const int PVP_CHANGE_TEAM_UNIT = 102;      // 队伍换人
    public const int PVP_SET_TACTIC_TO_STAGE = 103;   // 装配策略卡
    public const int PVP_SET_TACTIC_TO_BACK = 104;    // 卸下策略卡
    public const int PVP_CALL_ROUND_PAUSE = 105;      // 喊停（暂停回合）
    public const int PVP_CHANGE_TACTIC_TIMEOUT = 106; // 策略调整超时（强制结束）

    // 对局流程
    public const int PVP_ROUND_BEGIN = 402;    // 对局开始
    public const int PVP_ROUND_END = 403;      // 对局结束
    public const int PVP_BATTLE_END = 404;     // 整场战斗结束
    public const int PVP_AUTH = 405;           // UDP 身份验证字段
    public const int PVP_CONTROL_START = 407;  // 开始控制（初始化完成后）

    // 统计与校验
    public const int PVE_ROUND_END_ERR_HASH = 441;        // PVE 回合结束 Hash 上报
    public const int PVP_CLIENT_BUFFERING_REPORT = 492;   // 客户端缓冲统计
    public const int PVP_PING = 499;                      // Ping/延迟上报
    public const int PVP_SYNC_HASH = 502;                 // 不同步检测 Hash 上报
    
    // 不同步通知格式：[时间戳, BusID(16进制), GameID, 不同步帧号]
    public const int PVP_SYNC_ERROR = 507;

    // 判断是否是 PVP 逻辑控制类 VKey（区别于战斗操作 VKey）
    static public bool IS_PVP_LOGIC_VKEY(int vkey)
    {
        return (vkey >= 400 && vkey <= 511);
    }
}
```

### 3.2 VKeyArgPool.cs —— 参数对象池完整实现

```csharp
public class VKeyArgPool
{
    public static VKeyArgPool Instance = new VKeyArgPool();
    
    // 按参数数量分池管理（1~6个参数）
    private List<int[]>[] m_arrCount2Pool = new object[6];
    
    public VKeyArgPool()
    {
        // 初始化各长度的池
        m_arrCount2Pool[0] = new List<int[]>(); // 1个参数
        m_arrCount2Pool[1] = new List<int[]>(); // 2个参数
        // ...
    }
    
    // 克隆一个已有的参数数组（从池中取或新建）
    public int[] GetArgsClone(int[] args)
    {
        if (args != null && args.Length >= 1 && args.Length <= 6)
        {
            var pool = m_arrCount2Pool[args.Length - 1];
            int[] copy;
            if (pool.Count > 0)
            {
                copy = pool[0];
                pool.RemoveAt(0);
            }
            else
            {
                copy = new int[args.Length];
            }
            args.CopyTo(copy, 0);
            return copy;
        }
        return null;
    }
    
    // 归还数组（清零后放回池）
    public void ReturnArgs(int[] args)
    {
        if (args != null && args.Length >= 1 && args.Length <= 6)
        {
            for (int i = 0; i < args.Length; i++) args[i] = 0;
            m_arrCount2Pool[args.Length - 1].Add(args);
        }
    }
}
```

### 3.3 NumericComponent 中的确定性随机记录

```csharp
[ComponentOf(typeof(Unit))]
public class NumericComponent : Entity, IAwake, ITransfer, IReset
{
    // 记录每种随机表达式的调用次数（用于哈希校验时对比随机一致性）
    public DeterministicDictionary<EExpression, int> RandExpFTimes = new();
    
    // 记录每个技能每段的随机次数（[技能ID,子技能索引] → [随机ID → 次数]）
    public DeterministicDictionary<Vector2_Int, DeterministicDictionary<int, int>> RandSkillFTimes = new();
    
    // 锁定状态（批量操作时锁定，避免中间状态触发事件）
    public bool locked = false;
    public bool Locked => locked;
}
```

---

## 4. 帧同步的关键问题与解决方案

### 4.1 网络延迟处理（Buffering）

当某个客户端的输入因网络延迟未能及时到达时，系统需要等待。`PVP_CLIENT_BUFFERING_REPORT` VKey 上报当前客户端的缓冲统计：

```
正常情况：
帧 N：A 的输入已到 ✅，B 的输入已到 ✅ → 执行帧 N

延迟情况：
帧 N：A 的输入已到 ✅，B 的输入未到 ⏳
→ 等待（最多等待 X 帧）
→ 超时后执行帧 N（B 的输入按"无输入"处理）
→ B 追帧时重新执行，可能需要回滚（视是否支持 Rollback）
```

`PVP_CLIENT_BUFFERING_REPORT` 让服务器可以统计各端缓冲情况，动态调整等待时间。

### 4.2 断线重连与追帧

断线重连时，客户端需要快速"追帧"到当前帧：
1. 服务器发送从开始到当前的所有 VKey 序列
2. 客户端以最快速度（不渲染/跳过表现层）重放所有帧
3. 追帧完成后恢复正常同步

`Unit.InForceTick` 标志用于标记追帧模式，此时跳过表现层更新：
```csharp
public bool InForceTick { get; set; } = false;
// 追帧时 InForceTick = true，表现层检查此标志决定是否播放动画/特效
```

### 4.3 不同步检测与定位

当 `PVP_SYNC_HASH` 上报的哈希值不一致时，触发 `PVP_SYNC_ERROR`，包含：
- 时间戳
- BusID（转 16 进制）
- GameID
- 不同步的帧号

收到此信息后，开发工具可以重放该帧前后的状态，对比每个 Unit 的每个数值，精确定位是哪一步计算产生了差异。

---

## 5. 设计亮点

### 5.1 VKey 的对象池降低 GC
战斗中每帧可能产生大量 VKey 参数数组，`VKeyArgPool` 的对象池机制完全消除了参数数组的 GC 压力，这在 30fps 的固定帧率战斗中尤为重要（每秒 30 次 FixedUpdate）。

### 5.2 IS_PVP_LOGIC_VKEY 快速分类
通过约定 PVP 逻辑控制 VKey 在 400~511 范围内，`IS_PVP_LOGIC_VKEY` 可以 O(1) 地判断一个 VKey 是否是网络控制类，战斗逻辑处理时可以快速分流，避免逐一 switch-case。

### 5.3 确定性字典的遍历安全性
`DeterministicDictionary` 保证遍历顺序固定，这看似小细节，却是帧同步稳定性的关键。普通 `Dictionary` 在扩容时哈希桶位置变化，遍历顺序可能改变，导致相同逻辑在不同帧执行结果不同（如遍历 Unit 列表施放 AOE 时，命中顺序不同会影响 Buff 叠加次序）。

### 5.4 策略卡调整超时机制
`PVP_CHANGE_TACTIC_TIMEOUT` VKey 由服务器在超时后强制发送，所有客户端收到后强制结束策略调整阶段，进入战斗。这确保了即使玩家网络问题无法及时确认，游戏也不会无限等待。

---

## 6. 常见问题与最佳实践

### Q1：为什么用 FP 定点数而不是直接用 int？
**A**：战斗中有大量需要小数的计算（如移动速度 1.5 格/帧、伤害倍率 0.8 等）。`FP` 是基于 `long`（64位整数）实现的定点数，能表示小数但计算结果确定，同时比 `float` 的语义更接近数学运算，适合游戏逻辑。

### Q2：帧同步中可以使用 async/await 吗？
**A**：战斗逻辑中谨慎使用。ET 框架的 `ETTask` 是确定性异步（在 FixedUpdate 中推进），可以使用。标准 `async/await`（依赖线程池）不应在战斗逻辑中使用，因为会破坏单线程确定性假设。

### Q3：如何处理玩家长时间无操作的情况？
**A**：帧同步中"无输入"本身也是一种确定性输入（空 VKey）。等待超时后，服务端广播空输入包，所有客户端正常推进帧逻辑，结果仍然一致。

### Q4：哈希校验的性能开销大吗？
**A**：哈希校验不是每帧都做，通常每隔 30~60 帧（1~2 秒）计算一次。哈希计算只遍历关键数值，不计算所有内存状态，开销可控。校验频率可以在服务端配置调整。

### Q5：帧同步方案下怎么实现"预测性移动"（输入预测）？
**A**：本项目有 `ONLY_CLIENT` 宏控制的纯客户端逻辑（如 `TeamEntity.fakeBeHitList`），这是客户端预测的结果，不参与帧同步逻辑计算，仅用于表现层的即时响应，真实逻辑结果以服务器广播的输入包执行后的结果为准。
