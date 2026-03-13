---
title: 战斗系统
published: 2021-07-10
description: "深入剖析游戏战斗系统的三层架构设计（功能组件层/行为策略层/操作决策层），涵盖技能系统设计、帧同步与状态同步选型、碰撞检测与伤害计算流程，结合 Unity + Lua 实践经验。"
tags: [游戏开发, Unity, C#, Lua, 架构设计]
category: 架构设计
draft: false
---

## 概述

战斗系统是游戏客户端最核心也最复杂的模块之一。一个设计良好的战斗系统应具备：可扩展性（快速迭代新技能/新怪物）、可维护性（逻辑清晰，易于调试）、高性能（低帧率卡顿）。本文结合实际 Unity + Lua 项目，分享战斗系统从架构到落地的完整思路。

---

## 一、三层架构设计

战斗系统推荐分成三个层次，层与层之间通过接口解耦：

```
操作决策层（何时攻击、何时追击）
      ↓ 调用接口
行为策略层（具体攻击/技能/移动策略）
      ↓ 调用接口
功能组件层（移动/动画/伤害计算等通用组件）
```

![战斗系统架构图](/images/posts/战斗系统/image-20230910161434083.png)

### 1. 功能组件层

功能组件层实现角色身上的具体功能组件，这一层 **只提供机制，不提供策略**。

| 组件 | 职责 |
|------|------|
| 移动组件 | 控制角色移动、行走，执行路径，不关心路径从何而来 |
| 动画状态机 | 根据外部传入的状态播放对应动画，不关心状态切换时机 |
| 寻路导航 | 执行寻路算法（A\*、NavMesh），提供路径结果 |
| 攻击伤害计算 | 提供伤害计算时机与重置机制，不提供具体伤害公式 |
| 技能特效 | 管理粒子/特效的生命周期，与逻辑解耦 |

这一层的组件可以在不同项目中复用，是基础设施层。

```csharp
// 移动组件示例：只提供机制
public class MoveComponent : MonoBehaviour
{
    public float MoveSpeed = 5f;
    
    // 只负责按路径走，不关心路径从哪来
    public void MoveTo(Vector3 target)
    {
        // NavMesh 寻路执行
        _agent.SetDestination(target);
    }
    
    public void Stop()
    {
        _agent.ResetPath();
    }
}
```

### 2. 行为策略层

策略层实现各战斗单元的 **具体战斗行为策略**。战斗单元的基类抽象公共属性和接口：

```csharp
// 战斗单元基类（C# 侧）
public abstract class BattleUnit
{
    public int HP;
    public int MaxHP;
    public int Attack;
    public int Defense;
    
    // 从配置表加载数值
    public virtual void LoadConfig(int configId) { }
    
    // 受到伤害（由伤害计算组件调用）
    public virtual void OnTakeDamage(int damage) 
    {
        HP = Mathf.Max(0, HP - Mathf.Max(0, damage - Defense));
        if (HP <= 0) OnDead();
    }
    
    protected abstract void OnDead();
}
```

Lua 侧实现具体策略（便于热更）：

```lua
-- 小怪策略层（Lua）
local MonsterUnit = class("MonsterUnit", BattleUnit)

function MonsterUnit:init(configId)
    self:loadConfig(configId)
    self.searchRange = 10  -- 搜索范围
    self.attackRange = 2   -- 攻击范围
end

-- 搜索目标策略
function MonsterUnit:searchTarget()
    local players = BattleManager:getPlayersInRange(self.pos, self.searchRange)
    if #players > 0 then
        self.target = players[1]  -- 选最近的玩家
    end
end

-- 攻击策略
function MonsterUnit:doAttack()
    if not self.target then return end
    local dist = Vector3.Distance(self.pos, self.target.pos)
    if dist <= self.attackRange then
        self.attackComponent:triggerAttack(self.target)
    end
end
```

![策略层对象关系](/images/posts/战斗系统/v2-8bfbecc81f6e0c6c742c200bee5d449d_720w.webp)

### 3. 操作决策层

决策层负责"**什么时候做什么**"——是玩家操作、网络事件，还是 AI 决策。

![操作决策层](/images/posts/战斗系统/v2-d9f0349837af3106126fc1765aacc7f6_720w.webp)

常见的决策来源：

- **玩家 UI 操作**：点击攻击按钮 → 调用策略层攻击接口
- **网络事件**（状态同步）：服务器下发指令 → 执行对应策略
- **AI 决策**：行为树 / 有限状态机 → 根据环境条件选择策略
- **固定操作序列**：Boss 技能固定序列，按时序执行

```lua
-- AI 决策层（行为树叶节点）
local AttackAction = class("AttackAction", BTAction)

function AttackAction:update(unit)
    -- 决策：有目标且在攻击范围内 → 执行攻击策略
    if unit.target and unit:isInAttackRange() then
        unit:doAttack()
        return BT_SUCCESS
    end
    return BT_FAILURE
end
```

---

## 二、技能系统设计

### 数据驱动

技能系统的核心思想是**数据驱动**：技能的行为由配置表定义，程序只提供通用执行框架。

```
skill_config.xlsx:
SkillID | Name   | CD  | Range | DamageRate | TargetType | EffectID
1001    | 普通攻击 | 0.8 | 2.0   | 1.0        | SINGLE     | fx_slash
1002    | 旋风斩  | 5.0 | 3.0   | 1.5        | AOE_CIRCLE | fx_spin
1003    | 箭雨   | 8.0 | 15.0  | 0.8        | AOE_RECT   | fx_arrow_rain
```

### 技能执行流程

```
触发技能
    ↓
目标选择（TargetSelector 根据 TargetType 选目标）
    ↓
前摇（播放动画，等待攻击帧）
    ↓
伤害生效（碰撞检测 / 子弹命中）
    ↓
后摇（动画收尾）
    ↓
进入 CD 冷却
```

```csharp
// 技能基类
public class SkillBase
{
    protected SkillConfig config;
    protected BattleUnit caster;
    
    public virtual void Execute(BattleUnit target)
    {
        if (!IsReady()) return;
        
        // 1. 选择目标
        var targets = TargetSelector.Select(config.TargetType, caster, config.Range);
        
        // 2. 播放动画（前摇）
        caster.AnimComp.PlaySkillAnim(config.SkillID, () => OnHitFrame(targets));
        
        // 3. 进入 CD
        StartCooldown(config.CD);
    }
    
    protected virtual void OnHitFrame(List<BattleUnit> targets)
    {
        foreach (var t in targets)
        {
            int dmg = DamageCalculator.Calc(caster, t, config.DamageRate);
            t.OnTakeDamage(dmg);
            EffectManager.Play(config.EffectID, t.transform.position);
        }
    }
}
```

---

## 三、帧同步 vs 状态同步

在网络对战游戏中，同步方案的选型对战斗系统架构有根本性影响。

| 维度 | 帧同步（Lockstep） | 状态同步（State Sync） |
|------|-------------------|----------------------|
| 数据传输 | 操作指令（轻量） | 完整状态快照（较重） |
| 服务端职责 | 仅转发指令，不做逻辑 | 权威服务端，运行全量逻辑 |
| 反作弊 | 弱（客户端执行逻辑） | 强（服务端权威） |
| 断线重连 | 需回放全量帧（耗时） | 直接同步当前状态 |
| 适用场景 | MOBA、RTS、格斗 | MMORPG、大型 FPS |
| 浮点一致性 | 需用定点数 | 无此要求 |

### 帧同步关键点

帧同步要求所有客户端**相同输入 → 相同输出**，因此：

1. **禁用浮点数**，使用定点数（FixedPoint）避免不同平台精度差异
2. **禁用 Unity Physics**，自行实现逻辑层物理（或用第三方定点数物理库）
3. **随机数统一种子**，所有端使用相同随机序列

```csharp
// 定点数示例
public struct FP
{
    private long rawValue;
    private const int SHIFT = 16;
    
    public static FP operator +(FP a, FP b) 
        => new FP { rawValue = a.rawValue + b.rawValue };
    
    public static FP operator *(FP a, FP b)
        => new FP { rawValue = (a.rawValue * b.rawValue) >> SHIFT };
}
```

---

## 四、碰撞检测与伤害计算

### 轻量碰撞检测

战斗逻辑层通常不直接用 Unity 的 PhysX，而是实现简化的逻辑碰撞，原因：
- PhysX 有浮点精度问题（帧同步场景不可用）
- 自定义碰撞可以更精确控制生效时机

```csharp
// 圆形范围检测（逻辑层）
public static List<BattleUnit> CircleOverlap(Vector3 center, float radius)
{
    var result = new List<BattleUnit>();
    foreach (var unit in BattleManager.AllUnits)
    {
        // 使用 sqrMagnitude 避免 sqrt 开销
        float sqrDist = (unit.LogicPos - center).sqrMagnitude;
        if (sqrDist <= radius * radius)
            result.Add(unit);
    }
    return result;
}

// 扇形范围检测
public static List<BattleUnit> SectorOverlap(Vector3 origin, Vector3 forward, 
    float radius, float halfAngle)
{
    var result = new List<BattleUnit>();
    foreach (var unit in BattleManager.AllUnits)
    {
        Vector3 dir = unit.LogicPos - origin;
        if (dir.sqrMagnitude > radius * radius) continue;
        
        float angle = Vector3.Angle(forward, dir);
        if (angle <= halfAngle)
            result.Add(unit);
    }
    return result;
}
```

### 伤害公式

```lua
-- 伤害计算（Lua 侧，便于数值热更调整）
local DamageCalculator = {}

function DamageCalculator.calc(attacker, defender, skillRate)
    local baseDmg = attacker.attack * skillRate
    -- 减伤公式：防御/(防御+200) 是经典游戏减伤曲线
    local reduction = defender.defense / (defender.defense + 200)
    local finalDmg = math.floor(baseDmg * (1 - reduction))
    -- 暴击
    if math.random() < attacker.critRate then
        finalDmg = math.floor(finalDmg * attacker.critMultiplier)
    end
    return math.max(1, finalDmg)  -- 最低造成1点伤害
end

return DamageCalculator
```

---

## 五、Unity + Lua 项目实践

### 逻辑与表现分离

在 xlua/tolua 方案中，战斗逻辑写在 Lua 侧（可热更），表现层（动画、特效、音效）在 C# 侧：

```
Lua 战斗逻辑层
    ├── BattleManager（战场管理）
    ├── BattleUnit（战斗单元）
    ├── SkillSystem（技能系统）
    └── DamageCalculator（伤害计算）
            ↕ 通过 C# 接口桥接
C# 表现层
    ├── AnimationController（动画控制）
    ├── EffectManager（特效管理）
    ├── AudioManager（音效管理）
    └── UIBattle（战斗 UI）
```

### 对象池

战斗中子弹、特效、伤害数字频繁创建销毁，必须使用对象池：

```csharp
// 简单对象池
public class BulletPool
{
    private Queue<Bullet> _pool = new Queue<Bullet>();
    private GameObject _prefab;
    
    public Bullet Get(Vector3 pos, Vector3 dir)
    {
        Bullet b = _pool.Count > 0 ? _pool.Dequeue() : CreateNew();
        b.gameObject.SetActive(true);
        b.Init(pos, dir);
        return b;
    }
    
    public void Return(Bullet b)
    {
        b.gameObject.SetActive(false);
        _pool.Enqueue(b);
    }
}
```

---

## 总结

| 层次 | 核心原则 | 典型实现 |
|------|---------|---------|
| 功能组件层 | 只提供机制，不提供策略 | 移动/动画/寻路等通用组件 |
| 行为策略层 | 数据驱动，配置表定义行为 | BattleUnit 基类 + 各单元策略 |
| 操作决策层 | 解耦输入来源（UI/网络/AI） | 行为树 / 状态机 / 网络指令 |

战斗系统的可维护性关键在于**层次清晰**、**数据驱动**、**逻辑表现分离**。随着项目迭代，把更多"写死"的逻辑下沉到配置表，是提升效率的持续方向。
