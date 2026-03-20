---
title: 09 AI 行为树（BehaviorTree）系统
published: 2024-01-01
description: "09 AI 行为树（BehaviorTree）系统 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
---

# 09 AI 行为树（BehaviorTree）系统

> 本文介绍战斗 AI 的行为树系统，包括行为树的基本概念、BTComponent 的设计、AI 与 UniScript 的结合方式，以及如何配置和调试 AI 行为逻辑。

---

## 1. 系统概述

AI 行为树（Behavior Tree，BT）负责控制非玩家单位（NPC、Boss、召唤物等）在战斗中的决策逻辑：何时攻击、选择哪个技能、何时防守或闪避。与固定的脚本式 AI 不同，行为树提供了一种**模块化、可复用、可视化**的 AI 逻辑描述方式。

### 1.1 行为树 vs 有限状态机

| 对比维度 | 行为树（BT） | 有限状态机（FSM） |
|---------|------------|--------------|
| 设计焦点 | 决策（做什么） | 状态（处于什么状态） |
| 组合方式 | 树形层次结构 | 状态+转移条件 |
| 可扩展性 | 添加叶节点即可 | 需要修改转移关系 |
| 并发支持 | 原生支持（Parallel 节点） | 需要特殊处理 |
| 适用场景 | AI 决策 | 角色状态流转 |

在本项目中，两者**互补配合**：
- FSM 负责角色的**状态管理**（受击/攻击/死亡等）
- 行为树负责 AI 的**决策控制**（选择释放哪个技能）

### 1.2 行为树的基本节点类型

```
行为树节点类型
├── 控制节点（Control）
│   ├── Sequence（序列）：按顺序执行子节点，全部成功才成功
│   ├── Selector（选择器）：按顺序尝试子节点，第一个成功就返回
│   └── Parallel（并行）：同时执行所有子节点
│
├── 装饰节点（Decorator）
│   ├── Inverter（取反）：反转子节点结果
│   ├── Repeater（重复）：重复执行子节点 N 次
│   └── Cooldown（冷却）：限制执行频率
│
└── 叶节点（Leaf）
    ├── Condition（条件）：检查某个条件，返回成功/失败
    └── Action（动作）：执行具体行为（如释放技能）
```

---

## 2. 架构设计

### 2.1 BTComponent 结构

```csharp
public class BTComponent : Entity, IAwake, IFixedUpdate, IUpdate, IDestroy, IUniAgent
{
    // 行为树图实例（由 UniScript 的 UniBT 实现）
    public UniBT BT { get; set; }
    
    // 暂停控制
    public bool Pause { get; }
    public bool EditorPause { get; set; }
    
    // IUniAgent 接口让 BTComponent 可以作为 UniScript 图的 Agent
    // 即行为树节点可以直接操作 BTComponent 所在的 Unit
}
```

`BTComponent` 实现了 `IUniAgent` 接口，这意味着行为树图的各节点可以通过 `graphAgent` 访问到关联的 Unit，进而获取 FSM、技能、数值等组件。

### 2.2 AI 与战斗系统的整合

AI 单位与玩家单位在架构上基本相同，都有 FSM、Skill、Buff、Collider 等组件。唯一区别是：
- 玩家单位：由玩家输入（`VirtualInputComponent` 接收 VKey）驱动 FSM 事件
- AI 单位：由行为树（`BTComponent`）决策后，直接触发 FSM 事件

```
玩家单位的输入链：
    玩家按键 → VKey → FSMComponent.TryManualCondition

AI 单位的输入链：
    BTComponent.FixedUpdate → 行为树运行
        → AT_UseSkill 节点（决策使用技能）
            → FSMComponent.TryManualCondition（注入技能事件）
```

### 2.3 TeamEntity 中的 AI 状态机

`TeamEntity` 中定义了 AI 团队的宏观状态，辅助行为树做高层决策：

```csharp
public enum EAIStateType
{
    None,          // 初始状态
    Ready,         // 准备就绪（等待出手）
    Move,          // 移动中
    WaitBeHurt,    // 等待受击（防守状态）
    Skill          // 正在使用技能
}

// TeamEntity 上的 AI 状态
public EAIStateType aiState { get; set; } = EAIStateType.None;
```

### 2.4 UniBT —— UniScript 的行为树图

`UniBT` 是 UniScript 框架中行为树的实现，继承自统一的图框架：

```
UniBT（行为树图）
├── 根节点（Root）
│   └── Selector（最高层决策）
│       ├── 死亡检查（优先级最高）
│       │   └── CT_CheckHP（HP≤0?）
│       │       └── AT_EnterDeadState
│       ├── 技能决策
│       │   ├── CT_HasSkillReady（有可用技能?）
│       │   └── AT_UseSkill（释放技能）
│       └── 移动追击
│           └── AT_MoveToTarget（追踪玩家）
└── 黑板（BT Blackboard）
    └── 存储 AI 运行时变量（目标Unit/上次技能时间等）
```

### 2.5 行为树黑板（Blackboard）

行为树使用**黑板（Blackboard）**在节点间共享数据：

```csharp
// UniScript 行为树黑板
// 在 ScriptDefine.s_blackboardTypes 中注册的类型可作为黑板变量
[UniTypeCollect(UniCollectType.Blackboard)]
public static List<Type> s_blackboardTypes = new List<Type>()
{
    typeof(FP),        // 定点数（如距离值、计时器）
    typeof(TSVector),  // 向量（如目标位置）
    typeof(object),    // 任意对象引用（如目标 Unit）
    typeof(List<FP>)   // 数值列表
};
```

---

## 3. 核心代码展示

### 3.1 BTComponent.cs —— 完整实现

```csharp
using ET;
using UniScript;

namespace VGame.Framework
{
    public class BTComponent : Entity, IAwake, IFixedUpdate, IUpdate, IDestroy, IUniAgent
    {
        // 行为树图实例
        public UniBT BT { get; set; }

        // 暂停控制（与 Unit.Pause 联动）
        public bool Pause { get; }          // 战斗暂停时为 true
        public bool EditorPause { get; set; } // 编辑器暂停

        // IUniAgent 接口实现：将 BTComponent 作为行为树图的宿主 Agent
        // 使得节点可以通过 graph.agent 访问到 BTComponent 及其父 Unit
    }
}
```

### 3.2 TeamEntity 中的 AI 控制字段

```csharp
public class TeamEntity : Entity, IAwake<int>, IDestroy, IUniAgent
{
    // AI 团队状态
    public EAIStateType aiState { get; set; } = EAIStateType.None;
    
    // AI 是否有残余输入（AI 已决策但尚未消耗的输入）
    public bool bHasRestInput { get; set; } = false;
    
    // AI 状态枚举
    public enum EAIStateType
    {
        None,       // 未初始化
        Ready,      // 待机（等待出手权）
        Move,       // 移动/追击
        WaitBeHurt, // 防守/等待
        Skill       // 技能执行中
    }
}
```

### 3.3 AI 决策相关的 UniScript 条件节点

```csharp
// CT_CheckRange —— 检查目标是否在技能攻击范围内
[Name("检查范围")]
[Category("VGame/条件")]
[MemoryPackable]
public partial class CT_CheckRange : ConditionTask
{
    public ValueInput<Unit> target;       // 检测目标
    public ValueInput<FP> range;          // 范围半径
    public ValueInput<bool> checkHorizontal; // 只检查水平距离
    // Handler 中：计算 attacker.Position 到 target.Position 的距离 <= range
}

// CT_CheckHP —— 检查目标血量百分比
[Name("检查血量")]
[Category("VGame/条件")]
[MemoryPackable]
public partial class CT_CheckHP : ConditionTask
{
    public ValueInput<Unit> target;          // 目标
    public ValueInput<FP> hpPercent;         // 血量百分比阈值
    public ValueInput<ENumericCmpType> cmp;  // 比较类型（大于/小于）
    // Handler 中：target.NumericComponent[HP].Final / HP_Max * 100 cmp hpPercent
}

// CT_CheckTeamHostState —— 检查队伍是否有出手权
[Name("检查出手权")]
[Category("VGame/条件")]
[MemoryPackable]
public partial class CT_CheckTeamHostState : ConditionTask
{
    public ValueInput<TeamEntity> team;   // 检查的队伍
    public bool isHost;                   // 期望是否有出手权
}
```

### 3.4 AI 行为节点 —— AT_UseSkill（AI 使用技能）

```csharp
// AI 主动使用技能的 ActionTask
[Name("AI使用技能")]
[LabelText("AI使用技能")]
[MemoryPackable]
public partial class AT_UseAISkill : ActionTask
{
    [fsSerializeAs("skillId")]
    [MemoryPackOrder(0)]
    public int skillId;         // 技能配置 ID
    
    [fsSerializeAs("priority")]
    [MemoryPackOrder(1)]
    public int priority;        // 技能优先级（多个技能可用时选择最高优先级）
    
    // Handler 中：
    // 1. 检查 CD（CT_CheckCD）
    // 2. 检查能量/条件
    // 3. 通过 FSMComponent.TryManualCondition 注入技能输入事件
    // 4. TeamEntity.aiState = EAIStateType.Skill
}
```

### 3.5 AI 移动节点 —— AT_MoveToTarget

```csharp
[Name("移动到目标")]
[LabelText("移动到目标")]
[MemoryPackable]
public partial class AT_MoveToTarget : ActionTask
{
    public ValueInput<Unit> target;     // 移动目标
    public ValueInput<FP> stopRange;    // 停止距离（进入此范围停止）
    
    // Handler 中：
    // 1. 计算到目标的方向
    // 2. 通过 FSMComponent.TryManualCondition(EInputKey.Move_Forward) 触发移动
    // 或直接修改 Unit.Position（某些 AI 直接移动）
}
```

### 3.6 AT_SetAIState —— 切换 AI 状态

```csharp
[Name("设置AI状态")]
[MemoryPackable]
public partial class AT_SetAIState : ActionTask
{
    [fsSerializeAs("state")]
    public EAIStateType state;   // 目标 AI 状态
    
    // Handler 中：
    // team.aiState = state;
    // 根据状态切换相应的行为和动画
}
```

---

## 4. AI 决策流程详解

### 4.1 完整 AI 决策流程（每帧）

```
BTComponent.FixedUpdate
    │
    └→ BT.UpdateGraph(deltaTime)
         │
         └→ 从根节点开始遍历行为树
              │
              ├─ Selector（选择器，按优先级依次尝试）
              │   │
              │   ├─ 优先级最高：死亡检查
              │   │   └─ CT_CheckHP（HP≤0?）→ 失败 → 继续下一个
              │   │
              │   ├─ 技能选择器
              │   │   ├─ CT_HasSkillReady（有技能可用且在范围内?）
              │   │   │   └─ 失败 → 继续下一个
              │   │   └─ AT_UseSkill（使用优先级最高的技能）
              │   │       └─ 成功 → 返回 Running（等待技能完成）
              │   │
              │   └─ 默认行为：移动追击
              │       └─ AT_MoveToTarget（追近目标）
              │           └─ 成功 → 继续下一帧
              │
              └→ 记录结果到黑板（为下帧决策提供上下文）
```

### 4.2 AI 技能优先级系统

AI 通常配置多个技能，每个技能有优先级和使用条件：

```
技能优先级配置（示例 Boss AI）：
优先级1: 大招（HP < 30% 时可用，范围3格，CD 30秒）
优先级2: 范围技能（有多个目标在范围内时优先，CD 10秒）
优先级3: 单体技能（任意时刻可用，CD 5秒）
优先级4: 普通攻击（无CD，近战范围内可用）

行为树按优先级 1→2→3→4 依次检查条件，第一个满足的技能就执行。
```

### 4.3 AI 与 FSM 的联动

AI 不直接控制角色动画，而是通过 FSM 触发状态：

```
行为树决策：使用技能 A
    └→ AT_UseAISkill(skillId=1001)
         └→ FSMComponent.TryManualCondition(EInputKey.SkillA)
              └→ FSM 检测到 SkillA 事件
                   └→ 切换到技能状态（CustomSkill）
                        └→ 执行技能图（GS_TryUseSkill）
                             └→ 技能完成后 FSM 返回 Idle
                                  └→ 行为树继续下一帧决策
```

---

## 5. 设计亮点

### 5.1 AI 与玩家共用同一套战斗基础
AI 单位和玩家单位在战斗底层完全相同，都通过 FSM 管理状态，都通过 Skill 系统释放技能，都有碰撞检测和伤害计算。AI 只是"自动生成输入"的玩家。这意味着：
- AI 技能的判定逻辑与玩家完全一致（公平性保证）
- 测试 AI 就是测试玩家的对手体验
- AI 可以直接使用策划为玩家设计的所有技能配置

### 5.2 行为树与 FSM 职责分离
行为树管"决策"（该做什么），FSM 管"状态"（正在做什么）。行为树只负责"我决定使用技能 A"，然后把控制权交给 FSM，由 FSM 管理技能执行中的各种状态（前摇/攻击帧/后摇/受击打断等）。这种分层设计使 AI 逻辑简洁，不需要在行为树里处理每一帧的动作状态。

### 5.3 行为树热更新
行为树图序列化为 JSON，可以随资源包热更新，AI 策略调整不需要重新发包。策划可以在不改代码的情况下调整 Boss 的行为模式，甚至在测试阶段直接在线调整 AI 强度。

### 5.4 编辑器可视化调试
`BTComponent.EditorPause` 允许在编辑器中单步调试 AI 决策，配合 UniScript 的行为树可视化界面，可以看到每一帧行为树的执行路径和每个节点的成功/失败状态。

---

## 6. 常见问题与最佳实践

### Q1：行为树每帧都从根节点重新开始执行吗？
**A**：不一定。UniBT 支持**中断（Interrupt）**机制：
- 当前执行的子树返回 `Running`（异步等待中），下帧从该节点继续
- 只有条件变化时才触发重新评估（通过 Observer 机制监听黑板变量变化）
- `Abort.Self` 或 `Abort.LowerPriority` 配置控制中断行为

### Q2：AI 的随机性是如何保证帧同步的？
**A**：AI 的随机决策（如 30% 概率使用特殊技能）使用确定性随机数生成器（与战斗系统共享同一个随机数序列），所有客户端的 AI 随机结果完全一致。`NumericComponent.RandExpFTimes` 记录随机调用次数用于同步校验。

### Q3：如何给一个新的 Boss 配置 AI 行为树？
**A**：
1. 在 UniScript 编辑器中创建新的 BT 图
2. 从节点库中拖拽 Selector/Sequence/条件/动作节点
3. 配置各节点参数（技能 ID、攻击范围、CD 等）
4. 在 Boss 的配置表中关联该 BT 图 ID
5. 程序无需修改，框架自动加载

### Q4：BTComponent 和 FSMComponent 可以同时存在于同一个 Unit 吗？
**A**：可以，且这是设计的常规用法。AI 单位同时有 BT（决策）和 FSM（状态管理），两者通过 FSM 事件通道联动。玩家单位只有 FSM（由玩家输入驱动），没有 BTComponent。

### Q5：行为树节点如何读写黑板变量？
**A**：通过 `Blackboard.GetValue<T>(key)` 和 `Blackboard.SetValue(key, value)` 方法。UniScript 的节点通过 `BBParameter<T>` 类型的字段声明黑板绑定，编辑器会显示黑板变量选择框。

### Q6：AI 同步性如何保证？（多端 AI 行为一致）
**A**：所有端都运行完整的 AI 逻辑（不区分主机/从机）。帧同步保证每帧执行的 VKey 输入相同，AI 行为树每帧的输入（各 Unit 状态、随机数）也相同，因此每帧的决策结果必然相同，无需额外同步 AI 状态。
