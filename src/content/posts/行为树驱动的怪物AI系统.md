---
title: 行为树驱动的怪物AI系统
published: 2026-03-31
description: 深入解析基于行为树的怪物AI架构，理解如何通过可视化节点图配置复杂的战斗AI行为
tags: [Unity, 战斗系统, AI系统, 行为树]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 行为树驱动的怪物AI系统

好的游戏 AI 能让玩家感受到"真实的挑战"——怪物会选择合适的时机攻击，会在玩家格挡时换用不同的攻击方式，甚至会在血量低时使用特殊技能。这些行为不是硬编码的，而是通过可配置的"行为树（Behavior Tree）"系统实现的。

本文深入解析这套 AI 系统的设计。

---

## 第一性原理：怪物 AI 需要解决什么？

怪物 AI 的核心需求：
1. **感知**：知道周围有哪些目标，目标的状态如何
2. **决策**：根据感知到的信息，选择当前最优行动
3. **执行**：将决策转化为具体的游戏行为（移动、攻击、逃跑）
4. **可配置**：策划可以方便地调整 AI 行为，不需要修改代码

传统方案（有限状态机）能处理简单的 AI，但随着行为复杂度提升，状态机会变得难以维护（转换条件爆炸）。

**行为树**是目前最流行的游戏 AI 解决方案，它将行为组织为树状结构：

```
Root
 └── Selector（选择器：选执行第一个能成功的子节点）
      ├── Sequence（序列：所有子节点都成功才算成功）
      │    ├── IsEnemyInRange
      │    └── Attack
      └── Sequence（移动到目标）
           ├── HasTarget
           └── MoveToTarget
```

行为树的优势：直观、易配置、模块化——每个行为节点是独立的，可以在多个 AI 中复用。

---

## BTComponent：行为树组件

```csharp
[FriendOf(typeof(BTComponent))]
public static partial class BTComponentSystem
{
    [EntitySystem]
    private static void Awake(this BTComponent self)
    {
        self.BT = self.StartBTInfo(333);  // 333 是行为树配置文件 ID
    }
    
    [EntitySystem]
    private static void Destroy(this BTComponent self)
    {
        self.BT.Stop(false);  // 销毁时停止行为树
    }

    private static UniBT StartBTInfo(this BTComponent self, int stateId)
    {
        var path = ZString.Format("BehaviorTree/{0}.json", stateId);
        var text = AssetCache.GetCachedAssetAutoLoad<string>(path);
        
        if (string.IsNullOrEmpty(text)) return null;
        
        // 从 JSON 反序列化行为树
        var info = JSONSerializer.Deserialize<UniBT>(text);
        
        // 以手动更新模式启动（由 WorldComponent 帧循环驱动）
        info.StartGraph(self, info.localBlackboard, Graph.UpdateMode.Manual);
        return info;
    }
    
    // 重启行为树（如角色复活后）
    public static void Restart(this BTComponent self)
    {
        self.BT.Restart();
    }
}
```

行为树存储为 JSON 文件，在运行时反序列化为 `UniBT` 对象。与技能图和 FSM 类似，使用手动更新模式，由帧循环统一驱动。

---

## AI 黑板（BlackboardComponent）

行为树节点之间通过黑板共享数据：

```csharp
public class BlackboardComponent : Entity, IAwake, IDestroy, IReset
{
    public Dictionary<string, FP> FPValues = new();         // 数值型（HP比例、距离等）
    public Dictionary<string, TSVector> VectorValues = new(); // 向量型（目标位置等）
    public Dictionary<string, object> ObjectValues = new();   // 对象型（目标Unit等）
    public Dictionary<string, List<FP>> ListFPValues = new(); // 列表型
}
```

典型的黑板使用场景：

```
行为树节点 A（感知）：
  → 扫描周围，找到最近的敌人
  → blackboard.ObjectValues["Target"] = nearestEnemy
  → blackboard.FPValues["TargetDistance"] = distance

行为树节点 B（攻击决策）：
  → target = blackboard.ObjectValues["Target"]
  → distance = blackboard.FPValues["TargetDistance"]
  → if (distance < attackRange) ExecuteAttack()

行为树节点 C（移动）：
  → targetPos = target.Position
  → blackboard.VectorValues["MoveTarget"] = targetPos
```

黑板充当了 AI 各节点的"工作台"，节点之间不直接通信，而是通过黑板共享状态。

---

## 群体AI协调：SceneAIComponent

```csharp
[ComponentOf(typeof(Scene))]
public class SceneAIComponent : Entity, IAwake
{
    public MarkTracker<Unit> Units = new();  // 追踪哪些位置/目标被占用
}

public class MarkTracker<T>
{
    public Dictionary<T, Unit> Map = new();  // T → 占用者 的映射

    // 标记某个目标已被某个 AI 单位"占用"
    public void Taken(T item, Unit who)
    {
        Map[item] = who;
    }

    // 检查目标是否被其他 AI 占用（而不是自己）
    public bool IsTakenByOther(T site, Unit me)
    {
        if (Map.TryGetValue(site, out var unit))
            return unit != me;
        return false;
    }

    // 释放占用
    public bool Release(T site)
    {
        return Map.Remove(site);
    }
    
    // 释放某个单位占用的所有目标（角色死亡时调用）
    public bool ReleaseHolder(Unit holder)
    {
        using var _ = ListPool<T>.Get(out List<T> tmp);
        foreach (var (key, value) in Map)
        {
            if (value == holder) tmp.Add(key);
        }
        foreach (var key in tmp) Map.Remove(key);
        return true;
    }
}
```

`SceneAIComponent` 解决了**群体 AI 的协调问题**：

**问题**：5 个怪物同时追同一个玩家，全部都会移动到玩家的正前方攻击，互相重叠。

**解决方案**：用 `MarkTracker` 标记"哪个攻击位置已经被某只怪物占用"。新怪物在选择攻击位置时，检查 `IsTakenByOther`，如果被占用就选择其他位置（如侧面、背面）。

这实现了自然的包围战术，不同怪物自动分散到目标周围的不同位置。

---

## AI 权重决策系统

AI 的技能选择使用权重随机系统（配置在 `TbAIWeight` 表中）：

```csharp
// AIWeight 配置数据（Luban 生成）
public class AIWeight
{
    public int SkillId;      // 技能 ID
    public int Weight;       // 基础权重
    public int CooldownTime; // 冷却时间（帧数）
    public List<AICondition> Conditions; // 触发条件
}
```

权重选择算法：

```csharp
// 行为树节点：选择要使用的技能
public static int PickSkillByWeight(Unit unit, List<AIWeight> skills)
{
    // 1. 过滤掉不满足条件或在冷却中的技能
    var available = skills.Where(s => 
        s.CooldownRemaining <= 0 && 
        CheckConditions(unit, s.Conditions)).ToList();
    
    if (available.Count == 0) return -1;
    
    // 2. 计算总权重
    int totalWeight = available.Sum(s => s.Weight);
    
    // 3. 随机选择（定点数随机，保证帧同步）
    int rand = (int)(unit.CurrentScene().GetComponent<BattleComponent>()
        .Engine.random.NextFP() * totalWeight).AsInt();
    
    // 4. 按权重区间找到选中的技能
    int accumulated = 0;
    foreach (var skill in available)
    {
        accumulated += skill.Weight;
        if (rand < accumulated) return skill.SkillId;
    }
    
    return available.Last().SkillId;
}
```

权重随机让 AI 行为具有可预测的概率分布，同时保留随机性，避免玩家找到完全固定的应对模式。

---

## 行为树的更新时机

```csharp
// WorldComponent.Tick 中
// 注意：BT 的更新在 FSM 之后
foreach (var unit in activeUnits)
{
    unit.GetComponent<FSMComponent>()?.EnterFrame(deltaTime);  // 状态机先更新
    unit.GetComponent<BTComponent>()?.UpdateBT(deltaTime);     // 行为树后更新
}
```

**为什么 BT 在 FSM 之后？**

行为树决策"下一步做什么"，但真正执行（如发动攻击）是通过向 FSM 注入输入来完成的。这种分离保证了：
- 行为树决策时，FSM 已经处于本帧的最新状态
- 行为树的决策可以被 FSM 的当前状态"过滤"（如 FSM 处于受击中，忽略攻击输入）

---

## AI 感知系统：目标搜索

```csharp
// 搜索攻击范围内的敌方单位
public static Unit FindNearestEnemy(this Unit self, FP searchRadius)
{
    var unitComp = self.Domain.GetComponent<UnitComponent>();
    var myTeam = teamSys.GetTeamByUnit(self);
    
    Unit nearest = null;
    FP nearestDist = FP.MaxValue;
    
    foreach (var unit in unitComp.GetActiveUnits())
    {
        var unitTeam = teamSys.GetTeamByUnit(unit);
        if (unitTeam == myTeam) continue;  // 跳过队友
        if (unit.BattlePause) continue;    // 跳过暂停的单位
        
        var dist = TSVector.Distance(self.Position, unit.Position);
        if (dist <= searchRadius && dist < nearestDist)
        {
            nearestDist = dist;
            nearest = unit;
        }
    }
    
    return nearest;
}
```

使用定点数（`TSVector.Distance`）保证帧同步一致性。

---

## AI 与技能系统的集成

行为树决策后，通过与玩家相同的虚拟输入通道执行行为：

```csharp
// BT 节点：执行攻击技能
public class BT_AttackSkill : ActionTask
{
    [SerializeField] private int skillId;
    
    protected override void OnExecute()
    {
        var unit = agent as Unit;
        
        // 通过 SkillComponent 直接触发技能
        var skillComp = unit.GetComponent<SkillComponent>();
        skillComp.StartSkill(skillId).Coroutine();
        
        EndAction(true);  // 告诉 BT 此节点成功执行
    }
}
```

或者通过虚拟输入触发，走状态机流程：

```csharp
// BT 节点：发送攻击输入
var inputComp = unit.GetComponent<VirtualInputComponent>();
inputComp.OnTap((int)EInputKey.Attack);

var fsmComp = unit.GetComponent<FSMComponent>();
fsmComp.CheckAnyState();  // 立刻检查状态转换
```

AI 和玩家共用同一套输入处理流程，这意味着 AI 技能会经过完整的技能系统流程（碰撞检测、伤害计算、Buff 施加），与玩家控制没有区别。

---

## 行为树与 FSM 的关系

在这套架构中，行为树和状态机（FSM）承担不同的角色：

| 系统 | 职责 | 决策层次 |
|------|------|---------|
| 行为树（BT） | "应该做什么" | 高层战略决策 |
| 状态机（FSM） | "正在做什么" | 低层动作执行 |

**行为树决策**（频率较低，如每帧或每几帧）：
- 要攻击谁？
- 使用哪个技能？
- 要移动到哪里？

**状态机执行**（每帧）：
- 当前在哪个动画阶段？
- 能否接受新输入？
- 是否需要切换状态？

这种分离让 AI 逻辑清晰：BT 负责"想"，FSM 负责"做"。

---

## 设计总结

行为树 AI 系统的核心价值：

| 特性 | 实现方式 |
|------|---------|
| 可视化配置 | JSON 行为树文件，工具编辑 |
| 群体协调 | SceneAIComponent + MarkTracker |
| 数据共享 | BlackboardComponent 黑板 |
| 技能选择 | 权重随机 + 条件过滤 |
| 帧同步兼容 | 定点数随机，手动更新模式 |
| 与技能系统集成 | 通过虚拟输入和技能系统执行 |

对于初学者，学习行为树的最佳方式是：
1. 从最简单的"感知→决策→执行"三节点 BT 开始
2. 理解 Selector、Sequence、Condition、Action 四种基本节点
3. 逐步增加复杂度（条件组合、优先级、冷却）
4. 最后加入群体协调逻辑

好的 AI 不是写出来的，而是"设计"出来的——行为树让策划和程序都能参与 AI 设计，这是它最大的优势。
