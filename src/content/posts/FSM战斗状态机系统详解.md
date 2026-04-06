---
title: FSM 状态机系统详解
published: 2024-01-01
description: "FSM 状态机系统详解 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# FSM 状态机系统详解

## 1. 系统概述

战斗角色的行为状态（站立、移动、技能、受击、死亡等）由有限状态机（FSM）统一管理。本项目使用 **UniScript FSM（对 NodeCanvas FSM 的定制版）** + `FSMComponent` 组合实现。

**FSM 在战斗中的核心职责：**
- 防止非法状态组合（技能中不能直接切到死亡，必须先经过受击）
- 统一管理动画播放（进入状态时播放对应 Timeline）
- 作为技能系统的"守门员"：只有 FSM 允许才能触发技能

---

## 2. FSM 状态枚举

```csharp
// 位置：Hotfix/Battle/Model/Framework/FSM/FSMComponent.cs
public static class EFSMState
{
    // 基础状态
    public const string Idle           = "Idle";           // 站立待机
    public const string NavMove        = "NavMove";        // 导航移动
    public const string Rotate         = "Rotate";         // 旋转朝向
    public const string NormalState    = "NormalState";    // 普通攻击状态
    public const string CustomSkill    = "CustomSkill";    // 自定义技能状态
    
    // 装备相关
    public const string Equip          = "Equip";
    public const string UnEquip        = "UnEquip";
    public const string ChangeEquip    = "ChangeEquip";
    
    // NPC 专有状态（主角不会进入）
    public const string Sleeping       = "Sleeping";
    public const string Eating         = "Eating";
    public const string Bath           = "Bath";
    
    // 受伤/被控状态（对战重点）
    public const string Hurt           = "Hurt";           // 普通受击
    public const string StiffState     = "StiffState";     // 硬直（受到重击，短暂无法操作）
    public const string FloatState     = "FloatState";     // 浮空（被打飞）
    public const string LieState       = "LieState";       // 倒地
    public const string GetUpState     = "GetUpState";     // 起身
    
    // 特殊反制状态
    public const string Parry          = "ParryState";     // 格挡
    public const string SwordPlay      = "SwordPlay";      // 拆招（对拼招式）
    public const string Doge           = "DogeState";      // 闪避（无敌帧）
    public const string BreakDefense   = "BreakDefense";   // 破防（对手格挡被破）
    
    // 演出状态
    public const string PerformState   = "PerformHurtState"; // 演出受击（慢动作、特殊特效）
    public const string SpecialAnimation = "SpecialAnimation"; // 特殊动画（过场等）
    
    // 终态
    public const string Dead           = "Dead";           // 死亡
}
```

---

## 3. FSMComponent 数据结构

```csharp
public class FSMComponent : Entity, IAwake, IFixedUpdate, IUpdate, IDestroy, IReset
{
    // 底层 FSM 实例（UniScript 的 FSM 图）
    public UniFSM Fsm { get; set; }
    
    // 帧内待处理的条件事件集合（避免重复添加）
    public HashSet<int> FsmStateEvents { get; } = new();
    
    // 当前状态ID
    public int curID;
    
    // 破防状态追踪
    public bool DoBreakDefense { get; set; } = false;
    public bool CantBreak { get; set; } = false;
    
    // 死亡计数（用于复活判断）
    public int DeadCnt { get; set; }
    
    // 手动触发 FSM 条件（如 EInputKey.Dead → 死亡状态）
    public bool TryManualCondition(EInputKey key)
    {
        int intK = (int)key;
        if (!FsmStateEvents.Contains(intK))
        {
            FsmStateEvents.Add(intK);
        }
        Log.Info(ZString.Format("unit id: {0} key == {1}", Parent.Id, key));
        return true;
    }
}
```

---

## 4. 状态 Action Handler

每个 FSM 状态对应一个 ActionHandler，处理进入/退出时的逻辑。以受击状态为例：

```csharp
// 位置：Hotfix/Battle/Function/Framework/FSM/HurtActionHandler.cs
[StateMachine(EFSMState.Hurt)]
public class HurtActionHandler : IFSMActionHandler
{
    public void OnEnter(FSMComponent fsm, Unit unit)
    {
        // 1. 设置受击组件信息（记录攻击者、伤害数值等）
        var hurtComp = unit.GetComponent<HurtComponent>();
        hurtComp.ApplyPendingAttackInfo();  // 应用待处理的攻击信息
        
        // 2. 播放受击 Timeline（表现层）
        var timelineComp = unit.GetComponent<TimelineComponent>();
        timelineComp.PlayHurtTimeline(hurtComp.AttackInfo.HurtType);
        
        // 3. 通知数值系统扣血
        HurtSystem.ApplyHurtDamage(unit, hurtComp.AttackInfo);
        
        // 4. 根据受击类型决定下一状态
        if (hurtComp.AttackInfo.IsKnockdown)
        {
            // 重击 → 进入硬直
            fsm.TryManualCondition(EInputKey.Stiff);
        }
        else
        {
            // 普通受击 → 播放完自动返回 Idle
            fsm.TryManualCondition(EInputKey.HurtEnd);
        }
    }

    public void OnExit(FSMComponent fsm, Unit unit)
    {
        // 清理受击状态
        unit.GetComponent<HurtComponent>().Clear();
    }
}
```

---

## 5. 受击与伤害处理流程

`HurtSystem` 协调攻击方、防御方、状态机三者的受击逻辑：

```csharp
// 位置：Hotfix/Battle/Function/Framework/FSM/HurtSystem.cs
public static class HurtSystem
{
    // 完整受击流程（含击退+冻帧效果）
    public static void HurtMoveAndFreeze(ActionTask task, Unit attacker, Unit defender,
        int skillID, JumpTextType jumpTextType)
    {
        var hurtComp = defender.GetComponent<HurtComponent>();
        if (attacker == null) { task.EndAction(); return; }
        
        // 1. 获取防御方当前状态（决定使用哪套受击配置）
        var defenderState = defender.GetComponent<FSMComponent>().CurrentLeafStateTag();
        
        // 2. 通知双方当前受击状态（用于后续受击动作调整）
        attacker.GetComponent<EventDispatcherComponent>()
            .FireEvent(new Evt_DefenderHitState() { HitState = defenderState });
        defender.GetComponent<EventDispatcherComponent>()
            .FireEvent(new Evt_DefenderHitState() { HitState = defenderState });
        
        // 3. 获取子技能配置（不同受击状态对应不同的击退参数）
        var subskillConfig = hurtComp.AttackInfo.SubSkillConfigClone;
        
        // 4. 让防御方播放受击技能（含受击动画 Timeline）
        CastSkill(task, defender, skillID, subskillConfig).Coroutine();
        
        // 5. 发布受击特效事件（视觉表现）
        EventSystem.Instance.Publish(defender.DomainScene(), new Evt_HurtHitEffect()
        {
            Attacker = attacker,
            Defender = defender,
            jumpTextType = jumpTextType
        });
        
        // 6. 击退：根据攻击方向+子技能力量参数施加速度
        if (subskillConfig != null)
        {
            defender.GetComponent<PhysicsComponent>().Stop();  // 先停止当前速度
            var simpleMoveComp = defender.GetComponent<SimpleMoveComponent>();
            var subskillParam = subskillConfig.GetSubSkillParam(defenderState);
            
            // 击退速度 = |力量XZ| * 攻击方向 + 力量Y * 上方向
            var velocity = TSMath.Abs(subskillParam.PowerXz) * hurtComp.AttackInfo.AttackDirection
                         + subskillParam.PowerY * TSVector.up;
            
            // 摩擦减速（如果配置了摩擦加速度）
            if (subskillParam.DefenderFrictionAcceleration > 0)
            {
                simpleMoveComp.FrictionRate = subskillParam.DefenderFrictionAcceleration
                                            / simpleMoveComp.FrictionAcceleration;
            }
            simpleMoveComp.AddForceVelocity(velocity);
            
            // 7. 冻帧（攻击方和防御方都短暂停止，增强打击感）
            attacker.GetComponent<UnitTimeComponent>()
                .Freeze(subskillParam.FinalAttackFreezeFrames(defenderState));
            defender.GetComponent<UnitTimeComponent>()
                .Freeze(subskillParam.FinalHurtFreezeFrames(defenderState));
        }
    }
}
```

---

## 6. 破防（BreakDefense）状态

破防是项目特色机制——当防御方处于格挡状态时，攻击方可以通过特定技能触发破防：

```csharp
// Hotfix/Battle/Function/Framework/FSM/BreakDefenseStateActionHandler.cs
[StateMachine(EFSMState.BreakDefense)]
public class BreakDefenseStateActionHandler : IFSMActionHandler
{
    public void OnEnter(FSMComponent fsm, Unit unit)
    {
        // 1. 设置破防标记（防止重复触发）
        fsm.DoBreakDefense = true;
        
        // 2. 播放破防 Timeline（特殊慢动作演出）
        var timelineComp = unit.GetComponent<TimelineComponent>();
        timelineComp.PlayBreakDefenseTimeline();
        
        // 3. 给对手施加破防 Debuff（如硬直、增加受到伤害等）
        var attacker = unit.GetAttacker();
        if (attacker != null)
        {
            BuffSystem.AddBuff(attacker, EBuffType.BreakDefenseDebuff);
        }
        
        // 4. 受击方强制进入硬直状态
        fsm.TryManualCondition(EInputKey.Stiff);
    }
}
```

---

## 7. EBreakDefenseStatus 枚举

```csharp
public enum EBreakDefenseStatus
{
    NotBroken,  // 格挡完好，未被破防
    Broken,     // 已被破防（进入 BreakDefense 状态）
    Breaking    // 破防中（动画播放中，尚未结算完毕）
}
```

---

## 8. 闪避无敌帧系统

```csharp
// DogeStateActionHandler.cs
[StateMachine(EFSMState.Doge)]
public class DogeStateActionHandler : IFSMActionHandler
{
    public void OnEnter(FSMComponent fsm, Unit unit)
    {
        var skillComp = unit.GetComponent<SkillComponent>();
        
        // 闪避期间设置无敌标记（碰撞系统检测此标记，跳过伤害计算）
        skillComp.bInDodge = true;
        
        // 根据输入方向确定闪避方向（定点数运算）
        var inputDir = unit.GetInputDirection();
        
        // 播放闪避 Timeline
        unit.GetComponent<TimelineComponent>().PlayDogeTimeline(inputDir);
    }
    
    public void OnExit(FSMComponent fsm, Unit unit)
    {
        // 退出闪避状态：取消无敌
        unit.GetComponent<SkillComponent>().bInDodge = false;
    }
}
```

---

## 9. 状态转换图（简化）

```
         闪避输入
    ┌────────────┐
    │            ↓
Idle ←──── DogeState（无敌帧）
    │
    ├─── 移动输入 ──→ NavMove
    │
    ├─── 普攻 ────→ NormalState ─→ Idle（完成后）
    │
    ├─── 技能 ────→ CustomSkill ──→ Idle（完成后）
    │
    ├─── 受击 ────→ Hurt ─→ StiffState ─→ FloatState ─→ LieState ─→ GetUpState ─→ Idle
    │                   ↘
    │                    BreakDefense（仅防御被破时）
    │
    └─── 血量为0 ─→ Dead
```

---

## 10. 常见问题与最佳实践

**Q: 为什么不用 Unity Animator 而用自研 FSM？**  
A: Unity Animator 基于 float，帧同步游戏无法使用。自研 FSM 全用定点数状态标识，且可精确控制每帧的状态转换时机。

**Q: FsmStateEvents 为什么用 HashSet？**  
A: 同一帧内可能多次触发同一条件（如同时被两个 Buff 触发受击），HashSet 保证每个条件只处理一次。

**Q: Dead 状态能不能出去？**  
A: 设计上 Dead 是终态，但项目中 `DeadCnt` 支持复活逻辑——死亡计数归零时可从 Dead 状态回到 Idle（复活）。

**Q: 如何调试 FSM 状态转换？**  
A: 在编辑器中选中 Unit，FSMComponent 的 Inspector 实时显示当前状态和待处理条件。可在 `TryManualCondition` 处加断点追踪状态变化。
