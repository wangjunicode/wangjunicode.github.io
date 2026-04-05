---
title: 05 Buff 系统架构
published: 2024-01-01
description: "05 Buff 系统架构 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# 05 Buff 系统架构

> 本文介绍战斗中的 Buff（增益/减益效果）系统，包括 Buff 的数据结构、叠加策略、与数值系统的联动，以及 Buff 的完整生命周期管理。

---

## 1. 系统概述

Buff 系统负责管理战斗中所有**持续性的状态效果**，包括增益（加攻击力、回血）和减益（中毒、减速、沉默）。每个 Buff 本质上是一段"绑定在单位身上的逻辑脚本（BuffGraph）"，在特定条件下监听战斗事件并执行效果。

### 1.1 Buff 系统的核心职责

| 职责 | 说明 |
|------|------|
| Buff 的添加与移除 | 管理 Unit 上的 Buff 列表 |
| 叠加策略 | 替换/共存/丢弃（`EBuffOverlayType`） |
| 事件监听 | Buff 监听战斗点事件（如攻击开始、回合结束）触发效果 |
| 数值修改 | 通过 `NumericComponent` 修改攻防血量等属性 |
| 可视化反馈 | 通过 `BuffViewState` 通知 UI 更新 Buff 图标 |

### 1.2 战斗中 Buff 的典型场景

```
场景一：中毒
  每回合结束（BPDef.TurnEndEvtID）时
  → 对持有者扣除当前最大血量的 5%
  → 持续 3 回合后自动移除

场景二：狂战
  攻击开始（BPDef.AttackStartEvtID）时
  → 临时提升 30% 攻击力（AddModifier）
  攻击结束（BPDef.AttackEndEvtID）时
  → 移除临时攻击力加成（RemoveModifier）

场景三：护盾
  受伤前（BPDef.PreDamage）时
  → 检查护盾值 > 0 → 优先抵消伤害
  → 护盾值归零时移除 Buff
```

---

## 2. 架构设计

### 2.1 核心类结构

```
BuffComponent（Unit 上的 Buff 管理器）
├── List<SimpleBuff> buffs        ── 当前生效的 Buff 列表
├── List<BuffOpInfo> m_toAddBuffs ── 待处理的添加/删除队列
└── bool bDead                    ── 标记 Unit 是否已死亡

SimpleBuff（单个 Buff 实例）
├── int buffConfigId    ── Buff 配置 ID
├── int level           ── Buff 等级
├── Entity owner        ── 持有者（Unit 实体）
├── BuffGraph graph     ── Buff 逻辑图（UniScript）
└── PassiveSkillInstance ownerSkill ── 触发该 Buff 的被动技能
```

### 2.2 Buff 叠加策略

```csharp
public enum EBuffOverlayType
{
    BuffReplace,   // 替换：同 ID 的 Buff，新的替换旧的（刷新持续时间）
    BuffCoexist,   // 叠加共存：同 ID 的 Buff 可多个同时存在（层数叠加）
    BuffDiscard    // 丢弃：已有该 Buff 时，新的直接丢弃（不刷新）
}
```

**使用场景：**
- `BuffReplace`：灼烧 Buff（被二次点燃时刷新燃烧计时）
- `BuffCoexist`：攻击强化叠层（每次触发+1层，最多10层）
- `BuffDiscard`：无法被同一 Buff 施加两次的特殊状态（如变身）

### 2.3 BuffComponent 的延迟队列机制

Buff 的添加和删除不是立即执行的，而是先放入队列，在下一个合适的时机批量处理：

```csharp
public class BuffComponent : Entity, IAwake, ITransfer, IDestroy, IReset
{
    public List<SimpleBuff> buffs { get; } = new();   // 主 Buff 列表
    public List<SimpleBuff> buffs2 = new();           // 临时 Buff 列表

    // 待处理的操作队列（添加和移除都通过此队列）
    public List<BuffOpInfo> m_toAddBuffs = new();
    public List<BuffOpInfo> m_toAddBuffs2 = new();

    public struct BuffOpInfo
    {
        public int id;                      // Buff 配置 ID
        public int level;                   // Buff 等级
        public PassiveSkillInstance addedby; // 触发来源（被动技能实例）
        public IBlackboard bb;              // 黑板（传递给 Buff 图的上下文）
        public bool add;                    // true=添加, false=移除
        public bool fromCache;              // 是否从缓存获取
        public SimpleBuff buff;             // 指定实例移除时使用
    }
}
```

**为什么用延迟队列而非立即处理？**

在战斗事件处理链中，可能在同一帧内产生多个 Buff 操作。立即处理可能导致：
- 在遍历 `buffs` 列表时修改列表（迭代器异常）
- 在 Buff A 的事件回调中添加 Buff B，导致 Buff B 在同帧立即响应事件（时序错误）

使用延迟队列确保每帧开始时统一处理所有 Buff 变更，逻辑时序清晰。

### 2.4 Buff 与数值系统的联动

Buff 通过 `NumericComponent` 的 `AddModifier`/`RemoveModifier` 接口修改角色数值：

```
Buff 添加攻击力 +100
    └→ numericComp.AddModifier(ENumericId.Attack, ENumericPart.Add, 100, buffInstance)
         └→ 返回 ModifierHandle（用于后续移除）

Buff 移除时：
    └→ numericComp.RemoveModifier(handle)
         └→ 数值自动重算，攻击力 -100
```

数值计算公式（详见数值系统文档）：
```
最终值 = ((base + add) × (100 + pct) / 100 + finalAdd) × (100 + finalPct) / 100
```

### 2.5 Buff 可视化（BuffViewState）

Buff 不仅影响逻辑，还需要在 UI 上显示图标和状态：

```csharp
public enum EBuffViewState
{
    // UI 图标显示控制
    Show,    // 显示 Buff 图标
    Hidden,  // 隐藏 Buff 图标
}

public enum EBuffValueState
{
    // Buff 数值槽位状态
    Active,   // 激活
    Inactive, // 未激活
}
```

相关节点：
- `AT_AddOrSetBuffView`：添加/设置 Buff 的 UI 显示
- `AT_SetBuffViewState`：设置 Buff 图标的显示/隐藏
- `AT_SetBuffViewValue`：更新 Buff 数值槽（如护盾层数显示）

---

## 3. 核心代码展示

### 3.1 SimpleBuff.cs —— Buff 实例基类

```csharp
public class SimpleBuff : IHasHandler
{
    public PassiveSkillInstance ownerSkill; // 触发此 Buff 的被动技能
    public int buffConfigId;               // 配置表 ID
    public int level;                      // Buff 等级（影响数值效果）
    public Entity owner;                   // 所有者（Unit 实体）
    public BuffGraph graph;                // 关联的 Buff 逻辑图

    // Handler 缓存（延迟查找 + 缓存，避免反射开销）
    protected AHandler _handlerCache = null;
    protected bool bFindHandler = false;

    public T GetHandler<T>() where T : AHandler
    {
        if (!bFindHandler)
        {
            bFindHandler = true;
            HandlerHelper.TryGetHandler<T>(GetType(), out var retHandler);
            _handlerCache = retHandler;
        }
        return _handlerCache as T;
    }
}
```

### 3.2 EBuffOverlayType.cs —— 叠加策略枚举

```csharp
public enum EBuffOverlayType
{
    // 替换：同 ID 的 Buff 已存在时，用新的覆盖旧的（重置持续时间和层数）
    BuffReplace,

    // 叠加共存：同 ID 的 Buff 可以有多个实例（最大叠层数由配置控制）
    BuffCoexist,

    // 不可替换：同 ID 的 Buff 已存在时，新的直接丢弃
    BuffDiscard
}
```

### 3.3 BuffField.cs —— Buff 字段标注系统

```csharp
// 用于标注 Buff 子类中哪些字段是数值字段（供 Buff 系统序列化和反射使用）
[AttributeUsage(AttributeTargets.All)]
public class BuffFieldAttribute : Attribute
{
    public int index;  // 字段索引（对应配置表中的字段位置）
    
    public BuffFieldAttribute(int i) { index = i; }
}

// 用于标注字符串类型的字段
[AttributeUsage(AttributeTargets.All)]
public class BuffStringFieldAttribute : Attribute
{
    public int index;
    public BuffStringFieldAttribute(int i) { index = i; }
}
```

### 3.4 UniScript 节点 —— GS_AddBuff（添加 Buff）

```csharp
[Name("增加(删除)Buff")]
[Category("VGame/脚本")]
[MemoryPackable]
public partial class GS_AddBuff : AGlobalScriptBase
{
    [LabelText("目标")]
    public ValueInput<Unit> target;     // 目标单位（哪个 Unit 受到 Buff）

    [LabelText("Buff ID")]
    public ValueInput<int> buffId;      // Buff 配置 ID

    [LabelText("增加/移除")]
    [fsSerializeAs("add")]
    [MemoryPackOrder(0)]
    public bool add = true;             // true = 添加, false = 移除
    
    [NonSerialized]
    public FlowOutput output;           // 执行完毕后的流程输出端口
}
```

### 3.5 UniScript 节点 —— AT_AddBuff（Timeline 中添加 Buff）

```csharp
[Name("添加Buff")]
[LabelText("添加Buff")]
[MemoryPackable]
public partial class AT_AddBuff : ActionTask
{
    [fsSerializeAs("buffId")]
    [MemoryPackOrder(0)]
    [LabelText("Buff Id")]
    [ArgIndex(0)]
    public int buffId;        // Buff 配置 ID
    
    [fsSerializeAs("isTeam")]
    [MemoryPackOrder(1)]
    [LabelText("Is Team")]
    [ArgIndex(1)]
    public bool isTeam;       // 是否添加给整队（true=全队, false=当前单位）
}
```

### 3.6 UniScript 节点 —— AT_RemoveBuff（移除 Buff）

```csharp
[Name("移除Buff")]
[MemoryPackable]
public partial class AT_RemoveBuff : ActionTask
{
    [fsSerializeAs("buffId")]
    public int buffId;         // 要移除的 Buff ID（0 = 移除当前执行上下文的 Buff）
    
    [fsSerializeAs("all")]
    public bool removeAll;     // true = 移除所有同 ID 的 Buff 层数
}
```

---

## 4. Buff 生命周期

```
添加请求
    └→ BuffComponent.m_toAddBuffs.Add(new BuffOpInfo { ... })

下帧批量处理（在 FixedUpdate 中）
    └→ 遍历 m_toAddBuffs
         ├→ 查找同 ID 的 Buff（如果存在）
         │    ├→ BuffReplace → 移除旧的，添加新的
         │    ├→ BuffCoexist → 直接添加（层数+1，上限检查）
         │    └→ BuffDiscard → 跳过
         ├→ 创建 SimpleBuff 实例
         ├→ 加载 BuffGraph（UniScript 图）
         ├→ 注册战斗事件监听
         └→ 加入 buffs 列表，触发 EBuffEventType.Add 事件

Buff 运行中
    └→ 监听战斗点事件（TurnEnd、PreDamage 等）
         └→ 触发时执行 BuffGraph 中对应的节点逻辑

移除请求（条件：持续时间到/手动移除/死亡清除）
    └→ BuffComponent.m_toAddBuffs.Add(new BuffOpInfo { add = false, ... })

下帧批量处理
    └→ 找到对应 Buff 实例
         ├→ 注销战斗事件监听
         ├→ 撤销所有数值修改（RemoveModifier）
         ├→ 触发 EBuffEventType.Exit 事件
         └→ 从 buffs 列表移除，释放 BuffGraph 资源
```

---

## 5. 设计亮点

### 5.1 Handler 模式实现数据与逻辑分离
`SimpleBuff` 只是数据定义，具体的逻辑（如"中毒每回合扣血"）实现在对应的 Handler 类中（通过 `HandlerHelper.TryGetHandler` 查找）。新增一种 Buff 只需新建一个 Handler 类并注册，无需修改 `SimpleBuff` 或 `BuffComponent`，完全符合开闭原则。

### 5.2 被动技能与 Buff 的关联
每个 `SimpleBuff` 持有 `PassiveSkillInstance ownerSkill`，记录是哪个被动技能触发了该 Buff。这让系统可以：
- 当触发源（被动技能）失效时批量清除对应 Buff
- 在伤害计算时追溯 Buff 来源，用于伤害归因和统计

### 5.3 Buff 图（BuffGraph）的灵活配置
Buff 的效果逻辑通过 UniScript 的 BuffGraph（类似 FlowCanvas 图）配置，策划可以在编辑器中可视化地定义 Buff 的触发条件和效果，无需每种新 Buff 都写代码。

### 5.4 修改器句柄（ModifierHandle）精确管理
每次通过 `AddModifier` 添加的数值修改都会返回一个 `ModifierHandle`，后续移除时通过句柄精确定位，避免了"移除了其他 Buff 的加成"这类 Bug。句柄包含版本号，过期句柄操作会被安全忽略。

### 5.5 死亡时自动清理
`BuffComponent.bDead` 标志防止已死亡单位继续处理 Buff 添加请求，并在死亡时批量触发所有 Buff 的移除逻辑（如：死亡时撤销所有数值增益）。

---

## 6. 常见问题与最佳实践

### Q1：如何新增一种 Buff 效果？
**A**：
1. 在 Luban 配置表中配置新的 Buff ID 和基础参数
2. 在 UniScript 编辑器中创建 BuffGraph，定义触发事件和执行节点
3. 若需要特殊逻辑，创建继承 `SimpleBuff` 的子类和对应 Handler
4. 代码变更最小，大多数 Buff 通过纯配置实现

### Q2：Buff 如何知道自己应该在什么时候生效？
**A**：Buff 在 BuffGraph 中注册战斗点事件监听（通过 `BPDef` 中定义的事件 ID）。例如：注册 `BPDef.TurnEndEvtID`，系统就会在每个回合结束时调用该 Buff 的逻辑。

### Q3：同一个 Buff 的多层叠加如何处理数值？
**A**：对于 `BuffCoexist` 类型的 Buff，每一层是独立的 `SimpleBuff` 实例，各自持有独立的 `ModifierHandle`。每层独立添加数值修改，移除时逐层撤销，不会互相干扰。层数上限由配置表的 `MaxStack` 字段控制。

### Q4：Buff 的持续时间是帧数还是回合数？
**A**：两者都支持，由 BuffGraph 中的逻辑决定：
- 基于帧数：在 BuffGraph 中使用 `GS_Timer` 节点计时
- 基于回合数：监听 `BPDef.TurnEndEvtID` 事件计数

### Q5：怎么让 Buff 只作用于特定类型的单位？
**A**：在 BuffGraph 的条件节点中检查 `CT_CheckState`（检查单位状态）或 `CT_CompareNumeric`（数值比较）等条件。也可以在添加 Buff 时（`AT_AddBuff`）通过前置条件判断是否执行添加。

### Q6：Buff 系统和被动技能（PassiveSkill）是什么关系？
**A**：被动技能（`PassiveSkillInstance`）是 Buff 的触发来源。被动技能通过监听战斗点事件（如攻击命中），在满足条件时调用 `AT_AddBuff` 向目标添加 Buff。Buff 则是被动技能效果的载体，持有 `ownerSkill` 字段记录是谁触发的。
