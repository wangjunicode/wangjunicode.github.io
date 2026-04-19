---
title: 02 Unit 战斗实体设计
published: 2024-01-01
description: "02 Unit 战斗实体设计 - xgame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
encryptedKey: henhaoji123
---

# 02 Unit 战斗实体设计

> 本文详细讲解战斗中最核心的数据单元——Unit（战斗实体），包括它的设计思路、字段含义、组件挂载方式，以及 Team（队伍）的组织方式。

---

## 1. 系统概述

`Unit` 是战斗系统中的"一切的起点"。无论是玩家角色、敌方 Boss、召唤物还是场景机关，都由 `Unit` 类来承载。它继承自 ET 框架的 `Entity` 类，本身只保存**最基础的身份和空间信息**，具体的技能、状态机、血量等能力则由挂载的 **Component（组件）** 来实现。

这种"实体-组件"设计的核心哲学是：**Unit 是什么（身份），Component 能做什么（行为）**。

### 1.1 Unit 的主要职责

| 职责 | 说明 |
|------|------|
| 身份识别 | LogicId（运行时唯一 ID）、ConfigId（配置表 ID） |
| 空间信息 | 坐标（Position）、朝向（Forward）、缩放（LocalScale） |
| 归属关系 | TeamCode（队伍编号）、RootUnit（创建者）、FollowUnit（跟随目标） |
| 暂停/冻结 | 管理多种暂停标志（战斗暂停、演出暂停）和冻结帧 |
| 出手权 | bHost 标记是否为当前出手方 |
| 组件容器 | 通过 GetComponent<T>() 获取挂载的各功能组件 |

---

## 2. 架构设计

### 2.1 Unit 类继承关系

```
Entity（ET框架基类）
    └── Unit（战斗实体）
            ├── IAwake<int>       ← 创建时传入 ConfigId
            ├── IDestroy          ← 销毁清理
            ├── ITransform        ← 变换接口（坐标/旋转/缩放）
            └── IUniAgent         ← UniScript 脚本代理接口
```

`IUniAgent` 接口是 Unit 与 UniScript 可视化脚本系统交互的桥梁，所有可以被脚本节点操作的实体都需要实现此接口。

### 2.2 Unit 上挂载的组件清单

```
Unit
├── FSMComponent          ── 有限状态机（状态流转：Idle/技能/受击/死亡等）
├── SkillComponent        ── 技能状态（当前技能、子技能索引等）
├── SkillMgrComponent     ── 技能管理（已学技能列表）
├── BuffComponent         ── Buff 列表（增益/减益效果）
├── AttackComponent       ── 攻击命中记录（本次攻击打到的目标）
├── ColliderComponent     ── 碰撞体（攻击框/受击框）
├── NumericComponent      ── 数值系统（血量/攻击/防御等）
├── BlackboardComponent   ── 黑板（运行时临时变量存储）
├── TeamComponent         ── 队伍归属信息
├── BattleScriptComponent ── 绑定的战斗脚本（UniScript 图）
├── BTComponent           ── AI 行为树（AI 单位专用）
├── UnitTimeComponent     ── 单位时间管理
└── VirtualInputComponent ── 虚拟输入（AI 自动产生输入）
```

### 2.3 坐标系统设计

```csharp
// 所有战斗坐标使用定点数 TSVector，而非 UnityEngine.Vector3
private TSVector position;

public TSVector Position {
    get => this.position;
    set {
        TSVector oldPos = this.position;
        this.position = value;
        // 改变坐标时发布事件，表现层响应更新渲染
    }
}

// 支持轴锁定（某些战斗场景只允许在特定轴移动）
public bool LockX { get; set; }
public bool LockZ { get; set; }

// 渲染帧插值移动（仅在 FixedUpdate 中调用，不立即更新渲染）
public void LerpTransform(TSVector pos, TSQuaternion rot, TSVector scale)
{
    this.position = pos;
    if (LockX) position.x = 0;
    if (LockZ) position.z = 0;
    this.rotation = rot;
    this.localScale = scale;
}

// 瞬移（触发 Evt_UnitWrap 事件通知表现层）
public void TeleportTransform(TSVector pos, TSQuaternion rot) { ... }
```

### 2.4 暂停与冻结机制

这是一个精巧的设计：暂停支持多种原因并存，只有所有原因都消除才能恢复。

```csharp
public enum EPauseFlag
{
    common = 0,      // 普通暂停（战斗逻辑暂停）
    puppetShow = 1,  // 演出暂停（播放过场动画时）
}

// 多个暂停原因可以同时存在
private HashSet<EPauseFlag> battlePause = new HashSet<EPauseFlag>();

public bool BattlePause => this.battlePause.Count > 0;

// Pause = 战斗暂停 OR 编辑器暂停
public bool Pause => this.BattlePause || this.EditorPause;

// Freeze = 冻结帧（技能命中打击感效果，短暂停止时间）
public bool Freeze => this.FreezeFrames > 0;

// PauseOrFreeze = 任意一种停止状态
public bool PauseOrFreeze => Pause || Freeze;

// 设置/清除某种暂停原因
public void SetBattlePause(bool value, EPauseFlag flag = EPauseFlag.common)
{
    bool oldValue = BattlePause;
    if (value) battlePause.Add(flag);
    else battlePause.Remove(flag);
    if (BattlePause != oldValue)
    {
        EventSystem.Instance.Publish(this.CurrentScene(), 
            new Evt_UnitPauseStateChange() { unit = this });
    }
}
```

**为什么这样设计？**
假设角色正在播放一个过场演出（puppetShow 暂停），同时战斗逻辑也被暂停（common 暂停）。当演出结束时只清除 puppetShow，角色仍然维持 common 暂停。如果直接用 bool 就无法区分这两种情况。

### 2.5 出手权（Host）设计

```csharp
public bool bHost {
    get => _bHost;
    set {
        if (_bHost != value) {
            _bHost = value;
            // 切换出手权时，自动更新 FSM 的 Host/UnHost 事件
            var fsmComp = GetComponent<FSMComponent>();
            fsmComp.SetHostState(_bHost);
        }
    }
}
```

在这套系统中，每个回合只有一个"出手方"（Host），出手方可以发动主动技能，非出手方只能响应（防守、反击等）。通过在 FSM 中注入 Host/UnHost 事件，可以在状态机里配置出手方专属状态。

---

## 3. 核心代码展示

### 3.1 Unit.cs 完整核心字段

```csharp
[MemoryPackable]
public partial class Unit : Entity, IAwake<int>, IDestroy, ITransform, IUniAgent
{
    // ── 身份 ──
    public int LogicId { get; set; }       // 运行时唯一 ID（≠ 配置 ID）
    public int ConfigId { get; set; }      // 对应配置表的 ID
    public CUnit Config => CfgManager.tables.TbCharacter.GetOrDefault(ConfigId);
    public string Identifier { get; set; } = string.Empty; // 特殊识别标志
    public EEntityType Type { get; set; }  // 实体类型（角色/召唤物/机关等）

    // ── 归属 ──
    public int TeamCode { get; set; }      // 所属队伍编号
    public Unit RootUnit { get; set; }     // 创建者（召唤物的原始角色）
    public Unit FollowUnit { get; set; }   // 当前跟随目标

    // ── 空间 ──
    private TSVector position;             // 定点数坐标
    private TSQuaternion rotation;         // 旋转
    public TSVector localScale = TSVector.one;

    // ── 状态 ──
    private HashSet<EPauseFlag> battlePause = new();
    public bool WillFreeze { get; set; }   // 下帧是否冻结
    public int FreezeFrames { get; set; }  // 剩余冻结帧数
    public bool bHost { get; set; }        // 是否为当前出手方
    public int Group { get; set; }         // 分组（多场景/多战场）
}
```

### 3.2 UnitComponent —— 全场单位管理器

```csharp
[ComponentOf(typeof(Scene))]
public class UnitComponent : Entity, IAwake, IDestroy
{
    public int selfAddId = 1;  // 自增 ID 生成器
    
    // 所有存活的 Unit（确定性字典，遍历顺序固定）
    public DeterministicDictionary<int, Unit> AllUnits { get; set; } = new();
    
    // 按类型分类缓存（加速按类型查询）
    public Dictionary<int, List<Unit>> unitCache = new();
    
    // ── 对象池缓存（避免频繁序列化/反序列化） ──
    // 技能图缓存
    public ConcurrentDictionary<string, ConcurrentStack<SkillGraph>> SkillCache = new();
    // FSM 图缓存
    public ConcurrentDictionary<int, ConcurrentStack<UniFSM>> FSMCache = new();
}
```

### 3.3 TeamEntity —— 队伍实体

```csharp
public class TeamEntity : Entity, IAwake<int>, IDestroy, IUniAgent
{
    public static int MaxMemberCnt = 3;   // 最多上场 3 名队员
    public int TeamId { get; set; }       // 队伍 ID（PVP 中等于 roleIdx）
    public bool bHumanTeam = false;       // 是否人类玩家队伍

    // 上场队员（最多 MaxMemberCnt 个）
    public List<Unit> _teamMember = new();

    // 候补队员（未上场，可通过换人技能切换）
    public List<Unit> _backupMember = new();

    // 换人信息
    public Unit changeSkillOldMember { get; set; }  // 即将下场的成员
    public Unit changeSkillNewMember { get; set; }  // 即将上场的成员
    public EChangeSkillType ChangeSkillType;        // 换人类型（攻击换/防守换）

    // 回合信息
    public int atkTurn { get; set; }    // 当前攻击回合数
    public int defTurn { get; set; }    // 当前防守回合数

    // 破防状态
    public int bHoldBreakDefense { get; set; }  // 持续破防计数
}
```

### 3.4 UnitInfo —— 创建 Unit 的参数包

```csharp
public class UnitInfo
{
    public long UnitId { get; set; }     // 目标 ID（0 = 自动分配）
    public int ConfigId { get; set; }    // 配置表 ID
    public int Type { get; set; }        // 实体类型
    public TSVector Pos;                 // 初始坐标
    public TSVector Forward;             // 初始朝向
    public int Group;                    // 分组
    public string Identifier;           // 特殊标识
    public int CreateTurn = 0;          // 创建时的回合数
    public int TeamCode = 0;            // 所属队伍
    public Unit RootUnit = null;        // 创建者（召唤物使用）
}
```

---

## 4. 设计亮点

### 4.1 身份与能力分离
Unit 本身非常"干净"，只有约 20 个核心字段。所有复杂功能（技能执行、碰撞检测、数值计算等）都委托给对应的 Component。这带来极大的灵活性：同一个 Unit 类可以代表玩家、AI、召唤物，只需挂载不同的 Component 组合即可。

### 4.2 MemoryPack 序列化
`[MemoryPackable]` 标注意味着 Unit 可以被高效地序列化/反序列化，支持战斗存档、断线重连时的状态恢复。相比 `JsonUtility`，MemoryPack 速度快 10 倍以上。

### 4.3 ITransform 接口抽象
Unit 实现 `ITransform` 接口，可以被引擎层统一处理坐标更新。无论是 Unity 的 `Transform` 还是逻辑层的 `TSVector`，都通过接口隔离，方便单元测试和非 Unity 环境运行。

### 4.4 Group 分组支持多战场
`Group` 字段支持同一场景中存在多个战场（如双线作战、多人副本），同一 Group 的 Unit 才参与相互的碰撞和技能交互。

### 4.5 FreezeFrames 打击感设计
`FreezeFrames` 字段实现了格斗游戏中的"顿帧"效果：当攻击命中时，被命中单位暂停几帧的逻辑更新，同时攻击方继续运行，给玩家强烈的打击感反馈，且完全在逻辑层实现，帧同步安全。

---

## 5. 常见问题与最佳实践

### Q1：如何正确创建一个 Unit？
**A**：通过填写 `UnitInfo` 并调用场景的单位工厂方法（如 `UnitFactory.Create`），不要直接 `new Unit()`。工厂方法会处理 ID 分配、组件挂载、缓存注册等工作。

### Q2：Unit 的 Id 和 LogicId 有什么区别？
**A**：`Unit` 重写了 `Id` 属性，使其返回 `LogicId`（int 类型），而 ET Entity 的原始 `Id` 是 `long` 类型。`LogicId` 在同一战斗场景内唯一，`ConfigId` 是配置表 ID（多个 Unit 可以有相同的 ConfigId，如批量生成同种敌人）。

### Q3：召唤物 Unit 如何与主单位关联？
**A**：通过 `RootUnit` 字段记录创建者，`FollowUnit` 记录当前跟随目标（可以动态改变，如转移跟随）。在计算伤害归属、技能命中判定等场景中，会追溯 `RootUnit` 来找到真正的所有者。

### Q4：Unit 被销毁后 Component 还能访问吗？
**A**：不能，也不应该。ET 框架会在 `IDestroy` 回调中清理所有组件。任何异步操作在 Unit 销毁后访问组件都会导致异常。需要在异步任务中添加 Unit 存活检查。

### Q5：如何判断一个 Unit 是玩家还是 AI？
**A**：通过 `EEntityType Type` 字段判断，或者检查 Unit 上是否挂载了 `BTComponent`（行为树组件只有 AI 单位才有）。也可以通过所属 `TeamEntity` 的 `bHumanTeam` 标志来判断整个队伍是否为人类玩家。

### Q6：BlackboardComponent 是什么时候用的？
**A**：`BlackboardComponent` 是 Unit 的运行时临时变量存储，主要供 UniScript 脚本节点读写（如 `TS_GetUnitBlackboard`、`TS_SetUnitBlackboard`）。当技能或 Buff 需要在多个帧之间传递临时数据时使用，不适合存储配置数据或持久化数据。

---

## 6. Unit 生命周期

```
创建阶段（IAwake）
    ├── 分配 LogicId
    ├── 读取 ConfigId 对应的配置
    ├── 挂载必要的 Component（FSM、Skill、Buff等）
    └── 注册到 UnitComponent.AllUnits

运行阶段（FixedUpdate/Update）
    ├── FSMComponent.FixedUpdate → 状态驱动
    ├── SkillComponent.FixedUpdate → 技能推进
    └── ColliderComponent.LateFixedUpdate → 碰撞检测

销毁阶段（IDestroy）
    ├── 广播死亡事件
    ├── 从 UnitComponent.AllUnits 移除
    ├── 销毁所有子 Component
    └── 将对象归还对象池（若使用池化）
```

掌握 Unit 的结构是理解整个战斗系统的第一步。接下来在 FSM、技能等文档中，将看到各 Component 如何在 Unit 上协同工作，构建出完整的战斗体验。
