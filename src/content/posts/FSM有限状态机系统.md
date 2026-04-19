---
title: 03 FSM 有限状态机系统
published: 2024-01-01
description: "03 FSM 有限状态机系统 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# 03 FSM 有限状态机系统

> 本文介绍战斗系统中的有限状态机（FSM）设计，讲解角色如何在"待机/移动/技能/受击/死亡"等状态之间流转，以及状态事件的驱动机制。

---

## 1. 系统概述

有限状态机（Finite State Machine，FSM）是战斗系统中描述角色**行为逻辑流转**的核心机制。一个角色在任意时刻只处于一种状态（如 Idle、技能释放中、受击中、死亡），FSM 负责根据输入事件决定何时切换到哪个状态。

### 1.1 为什么需要 FSM？

没有 FSM 时，角色逻辑可能是这样的：

```csharp
// ❌ 没有 FSM，逻辑混乱
void Update() {
    if (isAttacking && !isHurt && !isDead) { DoAttack(); }
    if (isHurt && !isDead) { PlayHurtAnim(); }
    if (isDead) { PlayDeadAnim(); }
    // 各种 if-else，随着功能增加越来越难维护
}
```

有了 FSM 之后：

```csharp
// ✅ 有 FSM，逻辑清晰
// 角色在 Attack 状态，只有 Attack 状态的逻辑在运行
// 受击事件到来，FSM 自动切换到 Hurt 状态
// 每个状态只关心自己的逻辑，互不干扰
```

### 1.2 FSM 的核心组件

| 概念 | 说明 |
|------|------|
| `FSMComponent` | 挂载在 Unit 上的组件，持有 FSM 图实例 |
| `UniFSM` | FSM 的数据图（由 UniScript 配置），包含所有状态和转移条件 |
| `EFSMState` | 预定义的状态名称常量（字符串） |
| `ActionTask` | 每个状态对应的动作（如 `HurtAction`、`DeadAction`） |
| `EInputKey` | 触发状态转移的事件键（如受击、破防） |
| `FsmStateEvents` | 当前帧已触发的事件集合（HashSet<int>） |

---

## 2. 架构设计

### 2.1 FSMComponent 结构

```
FSMComponent
├── UniFSM Fsm              ── 状态机实例（UniScript 图）
├── HashSet<int> FsmStateEvents ── 当前帧触发的事件
├── bool DoBreakDefense     ── 正在破防中
├── bool CantBreak          ── 当前状态不可被打断
└── int DeadCnt             ── 死亡次数（支持多次死亡复活）
```

### 2.2 预定义状态枚举（EFSMState）

这些是游戏中所有角色共享的标准状态名称：

```csharp
public static class EFSMState
{
    public const string Idle = "Idle";                 // 待机
    public const string NavMove = "NavMove";           // 导航移动
    public const string NormalState = "NormalState";  // 普通状态（可接受攻击）
    public const string StiffState = "StiffState";    // 僵直受击
    public const string FloatState = "FloatState";    // 浮空状态
    public const string LieState = "LieState";        // 倒地状态
    public const string GetUpState = "GetUpState";    // 起身状态
    public const string Parry = "ParryState";         // 格挡状态
    public const string SwordPlay = "SwordPlay";      // 拼刀状态
    public const string Doge = "DogeState";           // 闪避状态
    public const string PerformState = "PerformHurtState"; // 演出受击状态
    public const string BreakDefense = "BreakDefense"; // 破防状态
    public const string Dead = "Dead";                // 死亡状态
    // ... 还有 CustomSkill、Equip 等
}
```

### 2.3 状态流转示意图

```
                    ┌──────────────────────────────────────────┐
                    │                                          │
             受击事件                                     恢复/无敌
                    │                                          │
    ┌────────────────▼──────────────────────────────────────────▼────┐
    │                                                                  │
    │   Idle ──(技能输入)──→ 执行技能 ──(技能结束)──→ Idle              │
    │    │                                                             │
    │    ├──(受击)──→ StiffState ──(僵直结束)──→ NormalState ──→ Idle  │
    │    │                                                             │
    │    ├──(连续受击)──→ FloatState ──(落地)──→ LieState             │
    │    │              ──(起身)──→ GetUpState ──→ Idle                │
    │    │                                                             │
    │    ├──(破防)──→ BreakDefense ──→ PerformHurtState ──→ Idle      │
    │    │                                                             │
    │    └──(死亡)──→ Dead                                             │
    │                                                                  │
    └──────────────────────────────────────────────────────────────────┘
```

### 2.4 事件驱动机制

FSM 的状态转移由**事件（Event）**驱动，而非每帧轮询判断。事件通过 `EInputKey`（虚拟键枚举）来表示：

```
玩家按下技能键
   └→ VirtualInputComponent 产生 EInputKey.Skill_A
        └→ FSMComponent.TryManualCondition(EInputKey.Skill_A)
             └→ 加入 FsmStateEvents 集合
                  └→ UniFSM 在下一个 FixedUpdate 检查条件
                       └→ 满足 → 切换到对应状态
```

### 2.5 FSM 与 UniScript 的关系

实际的状态机图（哪些状态、转移条件是什么）不是在代码里硬编码的，而是通过 **UniScript 编辑器**配置的。`UniFSM` 是一张图，图上的节点是状态，连线是转移条件，节点内嵌入的是 `ActionTask`（动作类）。

```
UniScript FSM 图
┌───────────────────────────────────────────────┐
│                                               │
│  [Idle State]                                 │
│  ├── Action: 播放 Idle 动画                   │
│  └── Transition: CT_CheckFSMEvent("受击") → HurtState │
│                                               │
│  [HurtState]                                  │
│  ├── Action: HurtAction（触发受击逻辑）         │
│  └── Transition: 受击时间结束 → NormalState    │
│                                               │
└───────────────────────────────────────────────┘
```

---

## 3. 核心代码展示

### 3.1 FSMComponent.cs

```csharp
public class FSMComponent : Entity, IAwake, IFixedUpdate, IUpdate, IDestroy, IReset
{
    public UniFSM Fsm { get; set; }  // FSM 图实例
    
    // 当前帧触发的事件集合（使用 int 而非字符串，提升性能）
    public HashSet<int> FsmStateEvents { get; } = new();
    
    public bool DoBreakDefense { get; set; } = false;  // 正在执行破防
    public bool CantBreak { get; set; } = false;       // 不可打断标志
    public int DeadCnt { get; set; }                   // 死亡次数

    // 触发事件（幂等：同一帧内触发多次等同于触发一次）
    public bool TryManualCondition(EInputKey key)
    {
        int intK = (int)key;
        if (!FsmStateEvents.Contains(intK))
        {
            FsmStateEvents.Add(intK);   
        }
        Log.Info($"unit id: {Parent.Id} key == {key}");
        return true;
    }

    // 清除某个事件（事件处理完毕后清除，避免重复触发）
    public void ClearManualCondition(EInputKey key)
    {
        FsmStateEvents.Remove((int)key);
    }

    // 查询事件是否存在
    public bool HasManualCondition(EInputKey key)
    {
        return FsmStateEvents.Contains((int)key);
    }
    
    // 切换出手方状态：自动切换 Host/UnHost 事件
    public void SetHostState(bool bHost)
    {
        if (bHost)
        {
            ClearManualCondition(EInputKey.UnHost);
            TryManualCondition(EInputKey.Host);
        }
        else
        {
            ClearManualCondition(EInputKey.Host);
            TryManualCondition(EInputKey.UnHost);
        } 
    }
    
    // 字符串事件名转枚举（兼容老配置）
    public static EInputKey GetKeyByStr(string eventStr)
    {
        if (!EInputKey.TryParse(eventStr, out EInputKey ret))
            Log.Error($"{eventStr} 未定义事件对应的Vkey");
        return ret;
    }
}
```

### 3.2 状态对应的 ActionTask 示例

每个状态在 UniScript 图里对应一个 `ActionTask`，逻辑在 Handler 类中实现：

```csharp
// HurtAction.cs — 受击动作（数据定义）
[MemoryPackable]
public partial class HurtAction : ActionTask { }

// DeadAction.cs — 死亡动作（数据定义）
[MemoryPackable]
public partial class DeadAction : ActionTask { }

// FloatStateAction.cs — 浮空状态（数据定义）
[MemoryPackable]
public partial class FloatStateAction : ActionTask { }

// BreakDefenseStateAction.cs — 破防状态（数据定义）
[MemoryPackable]
public partial class BreakDefenseStateAction : ActionTask { }
```

这些类本身很简单（只是数据定义），真正的逻辑在对应的 `Handler` 类中（遵循数据与逻辑分离原则）。

### 3.3 条件检查节点 —— CT_CheckFSMEvent

```csharp
// 状态机事件检测节点，用于在 FSM 图的转移条件上检查事件
[Name("状态机事件检测")]
[Category("xgame/条件")]
[MemoryPackable]
public partial class CT_CheckFSMEvent : ConditionTask
{
    protected override string info => Key;

    [fsSerializeAs("Key")]
    [MemoryPackOrder(0)]
    public string Key;        // 事件名（字符串配置）

    public EInputKey vKey;    // 运行时解析后的枚举值
}
```

### 3.4 状态 Tag 切换节点 —— AT_SetStateTag

```csharp
// 设置状态 Tag，用于标记当前处于哪个子状态
[Name("设置状态Tag")]
[MemoryPackable]
public partial class AT_SetStateTag : ActionTask
{
    [fsSerializeAs("tag")]
    [MemoryPackOrder(0)]
    public EStateTag tag;    // 如：Idle、Attack、Hurt 等
}
```

### 3.5 FSM 进入状态节点 —— TS_EnterState

```csharp
// 命令目标单位进入指定 FSM 状态
[Name("进入状态")]
[Category("xgame")]
[MemoryPackable]
public partial class TS_EnterState : ATargetScriptBase
{
    [fsSerializeAs("state")]
    [MemoryPackOrder(0)]
    public string stateName;  // 目标状态名
}
```

---

## 4. 状态动作详解

### 4.1 破防状态（BreakDefense）

破防（Break Defense）是这套战斗系统的核心战斗机制：当攻击打破敌方防御时，进入破防状态，敌方进入演出受击阶段（PerformHurtState），攻击方可以发动追打。

```
攻击命中 
   └→ 检查破防条件（DoBreakDefense）
        └→ 满足 → 触发 EInputKey.Hurt_BreakDefense 事件
             └→ FSM 进入 BreakDefenseStateAction 状态
                  └→ 被攻方进入 PerformHurtState
                       └→ 攻击方追打…
```

相关代码标志：
- `FSMComponent.DoBreakDefense = true` — 当前攻击要求破防
- `FSMComponent.CantBreak = true` — 当前状态不可被打断（无敌帧）
- `EBreakDefenseStatus.Broken/Breaking/NotBroken` — 破防阶段状态

### 4.2 受击状态体系

受击分为多个等级，对应不同的状态：

| 受击类型 | FSM 状态 | 说明 |
|---------|---------|------|
| 僵直（Stiff） | StiffState | 轻微受击，短暂僵直后恢复 |
| 格挡（Parry） | ParryState | 成功格挡，进入格挡状态 |
| 拼刀（SwordPlay） | SwordPlay | 双方拼刀，对赌状态 |
| 浮空（Float） | FloatState | 被打飞，处于空中 |
| 倒地（Lie） | LieState | 落地倒地 |
| 破招（CriticalHurt） | PerformHurtState | 破防追打演出 |
| 破防（BreakDefence） | BreakDefense | 防御被打破瞬间 |

---

## 5. 设计亮点

### 5.1 事件集合而非队列
`FsmStateEvents` 使用 `HashSet<int>` 而非 `Queue`，这意味着同一帧内重复触发的相同事件只计为一次。这样设计避免了事件堆积导致的状态异常（如连续多帧都触发"受击"事件，状态机只处理一次）。

### 5.2 int 替代 string 的性能优化
事件键存储为 `int`（`(int)EInputKey`）而非字符串。字符串比较开销大，每帧可能有数十个 Unit 需要处理 FSM，使用 int 比较极大提升了性能。

### 5.3 状态机与逻辑分离
FSM 图（哪些状态、如何转移）由策划在 UniScript 编辑器中配置，程序只提供 `ActionTask` 的实现。这样策划可以在不改代码的情况下调整角色的状态流转逻辑，极大提升了开发效率。

### 5.4 Host 状态自动同步
当 Unit 的 `bHost` 属性改变时，自动调用 `FSMComponent.SetHostState`，注入 `Host`/`UnHost` 事件到 FSM。这意味着状态机可以通过条件节点判断"我是否有出手权"，根据不同情况走不同的分支逻辑，而不需要在代码里特殊处理。

---

## 6. 常见问题与最佳实践

### Q1：同一帧内多次调用 TryManualCondition 会怎样？
**A**：由于 `FsmStateEvents` 是 `HashSet`，重复添加相同事件是幂等操作（无副作用）。事件在 `FSM.FixedUpdate` 处理完后应由对应逻辑清除（`ClearManualCondition`），否则会持续触发。

### Q2：如何让某个状态不可被打断？
**A**：在 UniScript FSM 图中，对应状态添加 `CLIP_CantBreak` Clip，或在 ActionTask 的 Handler 中设置 `FSMComponent.CantBreak = true`。注意要在状态退出时清除此标志。

### Q3：EFSMState 中的状态名和 UniScript 图中的状态名必须完全一致吗？
**A**：是的，这是字符串匹配。`EFSMState.Idle = "Idle"` 这些常量是为了代码里引用时不写"魔法字符串"。如果编辑器里的状态名改了，需要同步更新 `EFSMState` 常量，否则代码中的状态切换会失效。

### Q4：FSM 的 FixedUpdate 是如何被调用的？
**A**：ET 框架通过扫描实现了 `IFixedUpdate` 接口的组件，在每个固定帧自动调用其实现。`FSMComponent` 实现了 `IFixedUpdate`，所以框架会自动在固定帧调用它的更新方法，驱动 `UniFSM.UpdateGraph()`。

### Q5：死亡后角色还能复活吗？
**A**：支持。`FSMComponent.DeadCnt` 记录死亡次数，复活时重置 `DeadCnt`，并通过 FSM 事件驱动离开 `Dead` 状态。复活逻辑由 UniScript 脚本控制，通常通过特定 Buff（复活 Buff）或剧情触发。

### Q6：如何调试 FSM 的状态流转？
**A**：`FSMComponent.TryManualCondition` 中有 `Log.Info` 输出，可以看到每次触发的事件。在编辑器中，UniScript 的 FSM 图也提供可视化运行时调试（高亮当前状态和已触发的转移条件）。
