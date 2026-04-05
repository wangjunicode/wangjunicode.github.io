---
title: 战斗FSM状态机系统深度解析
published: 2026-04-05
description: 深入剖析战斗单位的有限状态机实现：EFSMState状态常量池、EInputKey事件驱动、StateAction行为层设计，以及破防/格挡/闪避等核心战斗状态的底层逻辑
tags: [Unity, 战斗系统, FSM, 状态机, UniFSM]
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# 战斗FSM状态机系统深度解析

> 战斗单位在任意时刻只能处于一种"主状态"——是在普通攻击、还是被击飞、还是格挡、还是死亡？这个问题由FSM（有限状态机）回答。本文基于`FSMComponent.cs`及全部13个StateAction，完整拆解这套系统。

---

## 一、FSM在战斗里解决什么问题

战斗的核心矛盾：**同一时间只能做一件事，但外部输入随时可能改变这件事**。

比如：
- 玩家正在施放技能 → 被打了 → 应该打断技能进入受击状态吗？
- 玩家在格挡 → 被连击3次 → 应该破防进入硬直吗？
- 玩家在浮空 → 动画还没播完 → 能接受新的攻击打断吗？

这些问题如果用`if-else`堆叠，维护成本呈指数级增长。FSM的价值在于：**每个状态只关心自己的逻辑，状态转换由事件驱动，规则在配置里管理。**

---

## 二、FSMComponent：状态机的持有者

```csharp
public class FSMComponent : Entity, IAwake, IFixedUpdate, IUpdate, IDestroy, IReset
{
    public UniFSM Fsm { get; set; }           // 状态机实例
    public HashSet<int> FsmStateEvents { get; } = new(); // 待处理事件池
    
    public bool DoBreakDefense { get; set; } = false; // 是否执行破防
    public bool CantBreak { get; set; } = false;      // 是否禁止被打断
    public int DeadCnt { get; set; }                  // 死亡次数（复活场景用）
}
```

**三个关键字段解读：**

**`FsmStateEvents`（事件池）**

这是状态机的"输入队列"。外部系统不直接切换状态，而是往这里塞事件，状态机在FixedUpdate里消费这些事件决定是否转换状态。

```csharp
// 外部系统触发事件
fsmComp.TryManualCondition(EInputKey.Hurt_Normal);

// 内部：事件转为int存入HashSet（避免重复）
public bool TryManualCondition(EInputKey key)
{
    int intK = (int)key;
    if (!FsmStateEvents.Contains(intK))
        FsmStateEvents.Add(intK);
    return true;
}
```

为什么用`HashSet<int>`而不是`Queue<EInputKey>`？
- **HashSet去重**：同一帧多次触发同一事件，只处理一次
- **int转换**：枚举转int零GC，比string比较快得多

**`CantBreak`（禁止打断标志）**

技能系统在特定帧（如技能起手、出招瞬间）会设置`CantBreak = true`，这期间FSM忽略所有受击事件，实现**霸体**效果。

**`DoBreakDefense`（破防标志）**

格挡积累达到阈值时，由格挡判定逻辑设置此标志，FSM在下一帧检测到后切换至`BreakDefense`状态。

---

## 三、EFSMState：状态常量池

所有状态名都是字符串常量，集中在`EFSMState`静态类管理：

```csharp
public static class EFSMState
{
    // 基础行为状态
    public const string Idle = "Idle";           // 待机
    public const string NavMove = "NavMove";     // 导航移动
    public const string Rotate = "Rotate";       // 旋转
    public const string CustomSkill = "CustomSkill"; // 技能执行中
    
    // 装备状态
    public const string Equip = "Equip";
    public const string UnEquip = "UnEquip";
    public const string ChangeEquip = "ChangeEquip";
    
    // 日常行为
    public const string Sleeping = "Sleeping";
    public const string Eating = "Eating";
    public const string Bath = "Bath";
    
    // 战斗核心状态 ↓↓↓
    public const string Hurt = "Hurt";               // 普通受击
    public const string NormalState = "NormalState"; // 普通状态
    public const string StiffState = "StiffState";   // 硬直（轻度）
    public const string FloatState = "FloatState";   // 浮空
    public const string LieState = "LieState";       // 倒地
    public const string GetUpState = "GetUpState";   // 起身
    public const string Parry = "ParryState";        // 格挡
    public const string SwordPlay = "SwordPlay";     // 剑舞（特殊格挡/反击）
    public const string Doge = "DogeState";          // 闪避
    public const string PerformState = "PerformHurtState"; // 演出受击
    public const string BreakDefense = "BreakDefense";     // 破防硬直
    public const string Dead = "Dead";               // 死亡
}
```

**战斗状态的层级关系：**

```
战斗状态分类
├── 主动行为（角色发起）
│   ├── CustomSkill   施放技能
│   ├── Parry         格挡
│   ├── Doge          闪避
│   └── SwordPlay     剑舞/反击
│
├── 被动响应（被打触发）
│   ├── Hurt          普通受击（小硬直）
│   ├── StiffState    硬直（重击）
│   ├── FloatState    浮空（被击飞）
│   ├── LieState      倒地
│   ├── GetUpState    起身（保护帧）
│   ├── BreakDefense  破防硬直
│   └── PerformHurtState  演出受击（BOSS专属）
│
└── 终止状态
    └── Dead          死亡
```

---

## 四、13个StateAction逐一解读

每个StateAction对应一种战斗状态下的具体行为逻辑（在UniScript中实现），以下是完整清单：

### 4.1 普通受击 —— `HurtAction`

```csharp
[MemoryPackable]
public partial class HurtAction : ActionTask { }
```

**职责：** 处理被普通攻击命中后的短暂硬直。

**核心逻辑（System层实现）：**
- 播放受击动画（根据受击点方向选择前/后/左/右受击动画）
- 应用攻击方传入的`AttackInfo.PowerXz/PowerY`击退力
- 计时硬直时长（由`CSubSkill.HurtFreezeFrames`决定）
- 硬直结束后触发`EInputKey.RecoverFromHurt`，回到Idle

**状态特性：** 可被连续触发（每次新的命中重置计时器）

---

### 4.2 硬直 —— `StiffStateAction`

```csharp
[MemoryPackable]
public partial class StiffStateAction : ActionTask { }
```

**与HurtAction的区别：**

| | HurtAction | StiffStateAction |
|---|---|---|
| 触发条件 | 普通攻击命中 | 重击/破甲攻击 |
| 动画 | 短暂受击抖动 | 明显的身体僵硬 |
| 可被打断 | 可被新攻击打断 | 硬直期间可连续追打 |
| 击退力 | 有 | 可能无（在原地硬直） |

---

### 4.3 浮空 —— `FloatStateAction`

```csharp
[MemoryPackable]
public partial class FloatStateAction : ActionTask { }
```

**职责：** 处理被击飞后的空中物理状态。

**核心逻辑：**
- 应用初速度（`PowerY`决定升空高度，`PowerXz`决定水平位移）
- 空中每帧施加重力（定点数FP，帧同步安全）
- 检测落地（Y坐标 ≤ 地面高度）
- 落地后触发`LieState`

**状态特性：** 空中可被追加攻击（空中连击），每次被击会重置物理速度

---

### 4.4 倒地 —— `LieStateAction`

```csharp
[MemoryPackable]
public partial class LieStateAction : ActionTask { }
```

**职责：** 倒地后的保护等待。

**核心逻辑：**
- 播放倒地动画（Loop）
- 倒地期间**无敌**（接受不到新的攻击碰撞）
- 等待倒地时长计时（由配表决定，通常1-2秒）
- 计时结束触发`GetUpState`

---

### 4.5 起身 —— `GetUpStateAction`

```csharp
[MemoryPackable]
public partial class GetUpStateAction : ActionTask { }
```

**职责：** 起身动画期间的保护帧处理。

**关键设计：** 起身动画期间有**部分无敌帧**（类似《黑魂》起身无敌），防止无限倒地连。计时结束回到`Idle`。

---

### 4.6 格挡 —— `ParryStateAction`（最复杂的状态）

```csharp
[Name("格挡状态")]
public partial class ParryStateAction : ActionTask
{
    public EActionType ActionType = EActionType.Parry; // 格挡类型
    
    [NonSerialized] public JumpTextType JumpText;    // 格挡飘字类型
    [NonSerialized] public EInputKey InputKey;       // 触发格挡的输入key
    [NonSerialized] public bool SubSkillCfg;         // 是否有子技能配置
}
```

**职责：** 处理角色主动格挡时的全部逻辑。

**格挡判定流程：**

```
攻击方出招
    → ColliderComponent检测到攻击碰撞体与格挡碰撞体重叠
    → 判断防御方FSM当前状态 == ParryState
    → 读取攻击方 CSubSkill.BreakParryHitTimes（破防所需命中次数）
    → HurtComponent.ParryHitTimes 累计命中次数
    → 若 ParryHitTimes >= BreakParryHitTimes：
        → FSMComponent.DoBreakDefense = true
        → 下帧切换到 BreakDefense
    → 否则：
        → 格挡成功，播放格挡音效/特效
        → JumpTextType决定飘字类型（"格挡"/"完美格挡"）
```

**`EActionType.Parry` 的扩展性：** 不同的`EActionType`对应不同的格挡效果（普通格挡、弹反、完美格挡等），通过配置扩展无需改代码。

---

### 4.7 破防 —— `BreakDefenseStateAction`

```csharp
[MemoryPackable]
public partial class BreakDefenseStateAction : ActionTask { }
```

**职责：** 格挡被打破后的硬直惩罚。

**破防状态特性：**
- **持续时间长**（比普通硬直长2-3倍）
- **无法抵抗**（不能被新的攻击重置，要等计时结束）
- 期间`DoBreakDefense`标志清除，格挡命中计数归零
- 结束后回到`NormalState`

**`EBreakDefenseStatus`枚举（追踪破防过程）：**

```csharp
public enum EBreakDefenseStatus
{
    NotBroken, // 未破防（格挡中）
    Broken,    // 已破防（受到惩罚中）
    Breaking   // 破防中（破防硬直的前几帧特效）
}
```

---

### 4.8 闪避 —— `DogeStateAction`

```csharp
[MemoryPackable]
public partial class DogeStateAction : ActionTask { }
```

**职责：** 处理闪避期间的无敌帧与位移。

**核心逻辑：**
- 无敌帧期间，`ColliderComponent.DodgeTokenInfo.bUsed`标记为已使用，攻击碰撞体不与此单位的受击体检测
- 位移方向由输入的方向向量决定（TSVector）
- 无敌帧时长由配表`CSubSkill.DogeTypes`决定
- 可与技能系统联动（闪避+攻击 = 闪避攻击技能）

---

### 4.9 剑舞 —— `SwordPlayStateAction`

```csharp
[MemoryPackable]
public partial class SwordPlayStateAction : ActionTask { }
```

**职责：** 剑舞是比格挡更高级的主动防御状态，类似"弹反"。

**与格挡的区别：**
- 格挡是被动承受攻击；剑舞有更精确的时机窗口
- 成功剑舞可反击：触发特殊的反击技能序列
- 失败（超时未命中）回到`Idle`

---

### 4.10 演出受击 —— `PerformHurtStateAction`

```csharp
[MemoryPackable]
public partial class PerformHurtStateAction : ActionTask { }
```

**职责：** 特殊剧情/BOSS战的演出受击。这是一种受控的受击状态——角色被"打飞"的轨迹、落点、动画都由配置的UniScript Timeline精确控制，用于制作电影感的打击演出。

---

### 4.11 死亡 —— `DeadAction`

```csharp
[MemoryPackable]
public partial class DeadAction : ActionTask { }
```

**职责：** 处理单位死亡后的流程。

**核心逻辑：**
- 播放死亡动画
- 广播`BattleEvent.OnUnitDead`事件
- `DeadCnt++`（用于多次死亡/复活场景）
- 通知`BattleComponent`检查胜负条件
- 根据是否有复活逻辑，决定销毁Entity还是等待复活触发

---

### 4.12 PuppetAttackStateAction（特殊）

```csharp
[MemoryPackable]
public partial class PuppetAttackStateAction : ActionTask { }
```

**职责：** 傀儡单位（被玩家技能召唤的从属单位）的攻击状态。傀儡单位的AI由`BTComponent`驱动，但攻击判定与普通单位一样走FSM + ColliderComponent，保证帧同步一致性。

---

## 五、Host状态：PVP中的主控权切换

`FSMComponent`有一个隐藏的关键机制：

```csharp
public void SetHostState(bool _bHost)
{
    if (_bHost)
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
```

**Host/UnHost 表示单位的"主控权"**：

- `Host = true`：此单位由**本地玩家操控**（接受输入）
- `Host = false`：此单位由**远端/AI控制**（只接受帧同步下发的指令）

PVP中换上出战角色、换下角色时，这个标志会在对应单位上切换，FSM据此决定是否处理本地输入。

---

## 六、新增战斗状态：完整操作步骤

以"石化状态"（无法行动，定格）为例：

**Step 1：添加状态名常量**
```csharp
// FSMComponent.cs
public static class EFSMState
{
    // ... 现有状态
    public const string Petrified = "Petrified"; // 石化
}
```

**Step 2：添加触发事件Key**
```csharp
// cfg/vkey/EInputKey.cs（Luban配表生成）
// 在配表中添加：Hurt_Petrified = xxx
```

**Step 3：创建StateAction**
```csharp
[MemoryPackable]
public partial class PetrifiedStateAction : ActionTask { }
```

**Step 4：在UniScript FSM编辑器中配置**
- 添加新状态节点 `Petrified`，绑定 `PetrifiedStateAction`
- 配置转入条件：`EInputKey.Hurt_Petrified` 事件触发时
- 配置转出条件：持续时间结束 → `Idle`

**Step 5：在System层实现行为**
```csharp
// PetrifiedStateActionSystem.cs (ET的System分离模式)
public class PetrifiedStateActionSystem : 
    UniScriptSystem<PetrifiedStateAction>, IActionTaskOnEnter, IActionTaskOnExit
{
    public override void OnEnter(PetrifiedStateAction self)
    {
        var unit = self.GetParent<Unit>();
        // 播放石化特效
        // 禁止所有输入
        unit.GetComponent<FSMComponent>().CantBreak = true;
    }
    
    public override void OnExit(PetrifiedStateAction self)
    {
        var unit = self.GetParent<Unit>();
        unit.GetComponent<FSMComponent>().CantBreak = false;
    }
}
```

---

## 七、总结

| 设计点 | 实现方式 | 优势 |
|--------|---------|------|
| 状态事件传递 | `HashSet<int>` 事件池 | 去重 + 零GC |
| 状态逻辑分离 | StateAction（数据）+ System（行为） | ET ECS设计，热更新友好 |
| 霸体实现 | `CantBreak` 标志位 | 不改FSM转换逻辑，一行代码控制 |
| 破防追踪 | `EBreakDefenseStatus` 三态枚举 | 精确描述破防的完整过程 |
| PVP主控权 | `Host/UnHost` Key | 与普通战斗状态无缝集成 |
| 扩展新状态 | 常量+StateAction+编辑器配置 | 策划可独立完成配置部分 |

这套FSM的核心设计理念：**代码提供所有可能，配置决定实际行为**。程序员只需保证StateAction覆盖足够多的行为组合，策划通过可视化配置组装出具体的战斗感。
