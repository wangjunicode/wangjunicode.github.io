---
title: 06 UniScript 可视化脚本驱动战斗逻辑
published: 2024-01-01
description: "06 UniScript 可视化脚本驱动战斗逻辑 - VGame项目技术文档"
tags: ['Unity', '游戏开发', '技术文档']
category: 战斗系统
draft: false
---

# 06 UniScript 可视化脚本驱动战斗逻辑

> 本文介绍项目自研的 UniScript 可视化脚本系统，讲解它如何将战斗逻辑从代码中解放出来，让策划和技术美术能够通过"连连看"的方式编辑技能、Buff、AI 等战斗流程。

---

## 1. 系统概述

UniScript 是本项目自研的可视化脚本框架，灵感来源于 Unity 的 NodeCanvas、Bolt（现 Visual Scripting）等工具。它提供两种图类型：

| 图类型 | 说明 | 典型用途 |
|--------|------|---------|
| **FlowCanvas** | 流程图（有向无环图，类似流程图） | 技能执行逻辑、全局脚本触发 |
| **UniFSM** | 有限状态机图 | 角色 FSM 状态配置 |
| **UniBT** | 行为树图 | AI 决策逻辑 |
| **Timeline（TL）** | 时间轴图 | 技能每帧的精确行为控制 |

### 1.1 UniScript 的三大价值

**价值一：策划可以独立迭代战斗逻辑**
技能的释放条件、效果流程全部在 UniScript 图中配置，策划不需要等待程序修改代码，直接在编辑器里拖拽节点即可调整。

**价值二：热更新友好**
所有图都序列化为 JSON 存储，可以随游戏资源热更新，不需要重新打包客户端。

**价值三：运行时确定性保证**
UniScript 的所有计算使用定点数（`FP`/`TSVector`），与帧同步系统配合，确保多端一致。

### 1.2 节点命名规范

UniScript 的节点按功能前缀分类：

| 前缀 | 全称 | 说明 |
|------|------|------|
| `GS_` | Global Script | 全局脚本节点（不依赖特定目标） |
| `AT_` | Action Task | 动作任务节点（FSM/FlowCanvas 中的动作） |
| `CT_` | Condition Task | 条件判断节点 |
| `TS_` | Target Script | 目标脚本节点（针对特定 Unit 操作） |
| `CLIP_` | Timeline Clip | Timeline 时间轴上的片段 |
| `TG_` | Trigger | 触发器节点 |

---

## 2. 架构设计

### 2.1 整体系统结构

```
UniScript 框架
├── 图类型
│   ├── SkillGraph（FlowCanvas 技能图）
│   ├── UniFSM（状态机图）
│   ├── UniBT（行为树图）
│   └── Timeline（时间轴）
│
├── 节点类型（基类）
│   ├── ActionTask       ← 动作节点基类
│   ├── ConditionTask    ← 条件节点基类
│   ├── AsyncNode        ← 异步节点基类（如 GS_TryUseSkill）
│   └── ActionClip       ← Timeline Clip 基类
│
├── 内置节点实现
│   ├── Impl/Task/       ← AT_* 动作任务（AT_AddBuff, AT_Move 等）
│   ├── Impl/ConditionTask/ ← CT_* 条件判断
│   ├── Impl/Global/     ← GS_* 全局脚本节点
│   ├── Impl/Target/     ← TS_* 目标脚本节点
│   ├── Impl/Switch/     ← Switch 分支节点
│   └── Impl/Timeline/   ← CLIP_* 时间轴片段
│
├── 类型系统（ScriptDefine.cs）
│   ├── 基础类型（bool/int/FP/TSVector/Unit 等）
│   ├── 枚举类型（ENumericId/EInputKey 等）
│   └── 黑板类型（FP/TSVector/object 等）
│
└── 运行时
    ├── UniScriptRuntimeInit（运行时初始化）
    └── GraphFactory（图实例化工厂）
```

### 2.2 FlowCanvas（流程图）工作原理

FlowCanvas 以**流程流（Flow）**为基础，节点按连线顺序执行：

```
开始节点（Enter）
    │
    ▼
CT_CheckCD（检查 CD）── 不满足 ──→ FlowOutput.failed
    │
    ▼（满足）
AT_DefaultUsePP（消耗体力点）
    │
    ▼
GS_TryUseSkill（执行技能）
    ├──→ _successEnter ──→ 技能开始演出
    ├──→ _successComplete ──→ 技能结束处理
    └──→ _failed ──→ 技能失败处理
```

### 2.3 Timeline（时间轴）工作原理

Timeline 是线性时间轴，精确到帧：

```
时间轴（Timeline）
│
├─ Track（轨道）一：ActorActionTrack（角色动作轨道）
│    ├─ [0~5帧]  CLIP_RootMotion（Root Motion 位移）
│    ├─ [3~10帧] CLIP_HurtCollider（受击框激活）
│    ├─ [4~8帧]  CLIP_SetAttackCollider（攻击框激活）
│    └─ [8帧]    CLIP_AttackEnd（攻击结束）
│
├─ Track 二：ActorColliderTrack（碰撞轨道）
│    └─ CLIP_HurtCollider（帧精确受击框配置）
│
└─ Track 三：WwiseTrack（音效轨道）
     └─ 音效触发（Wwise 事件）
```

### 2.4 类型系统（ScriptDefine）

UniScript 需要预注册所有在图中可以使用的类型：

```csharp
public class ScriptDefine
{
    // 基础类型（可用于变量节点、ValueInput/Output 连线）
    [UniTypeCollect(UniCollectType.Basic)]
    public static List<Type> s_preferedTypes = new List<Type>()
    {
        typeof(bool), typeof(int), typeof(long),
        typeof(FP),          // 定点数（重要！所有数值用 FP）
        typeof(TSVector),    // 定点数向量
        typeof(TSQuaternion),// 定点数四元数
        typeof(Unit),        // 战斗单位
        typeof(string),
        // ...
    };

    // 枚举类型（可在 Switch 节点中使用）
    [UniTypeCollect(UniCollectType.Enum)]
    public static List<Type> s_enumTypes = new List<Type>()
    {
        typeof(ENumericId),    // 数值 ID（血量/攻击/防御等）
        typeof(EInputKey),     // 输入键（技能键/受击键等）
        typeof(EStateTag),     // 状态 Tag
        typeof(EAttackType),   // 攻击类型
        typeof(EDogeType),     // 闪避类型
        // ...
    };

    // 黑板类型（可在黑板节点中存取）
    [UniTypeCollect(UniCollectType.Blackboard)]
    public static List<Type> s_blackboardTypes = new List<Type>()
    {
        typeof(FP), typeof(TSVector), typeof(object), typeof(List<FP>)
    };
}
```

---

## 3. 核心代码展示

### 3.1 UniScriptRuntimeInit.cs —— 类型转换注册

```csharp
public class UniScriptRuntimeInit
{
#if UNITY_EDITOR
    [UnityEditor.InitializeOnLoadMethod]
#endif
    public static void RegisterTypeConverter()
    {
        // 注册自定义类型转换：Unit → IActor
        // 当脚本图中需要将 Unit 转为 IActor 接口时使用
        UniScript.TypeConverter.customConverter += TypeConverterOncustomConverter;
        UniScript.FlowCanvas.TypeConverter.customConverter += TypeConverterOncustomConverter;
    }

    private static ValueHandler<object> TypeConverterOncustomConverter(
        Type sourcetype, Type targettype, ValueHandler<object> func)
    {
        if (sourcetype == typeof(Unit) && targettype == typeof(IActor))
        {
            return (() => new SerializableUnit() { Unit = (Unit)func() });
        }
        return null;
    }
}
```

### 3.2 FlowScriptNode.cs —— FSM 中内嵌 FlowCanvas 子图

这是一个特别强大的设计：在 FSM 的状态节点内部，可以嵌入一个完整的 FlowCanvas 子图（SkillGraph）。这样 FSM 负责状态切换，每个状态内部的具体逻辑由 FlowCanvas 来描述。

```csharp
[Name("Sub FlowScript Node", -1)]
[Description("并行逻辑")]
[MemoryPackable]
public partial class FlowScriptNode : FSMNodeNested<SkillGraph>, IUpdatable
{
    // 内嵌子图的 JSON 序列化数据
    [fsSerializeAs("_skillJson")]
    [MemoryPackOrder(-29)]
    internal string _skillJson;

    [NonSerialized]
    internal SkillGraph _flowScript = null;  // 运行时反序列化的子图

    // 状态激活时，启动子图
    public override void OnGraphStarted()
    {
        base.OnGraphStarted();
        if (subGraph == null)
        {
            subGraph = SimpleLoadSkill(_skillJson);
        }
        this.TryStartSubGraph(graphAgent);
        this.status = Status.Running;
    }

    // 子图每帧更新
    public void Update()
    {
        if (this.status == Status.Running && currentInstance != null)
        {
            currentInstance.UpdateGraph(this.graph.deltaTime);
        }
    }

    // 状态退出时，停止子图
    public override void OnGraphStoped()
    {
        if (currentInstance != null)
        {
            currentInstance.Stop();
        }
        this.status = Status.Resting;
        base.OnGraphStoped();
    }
}
```

### 3.3 GS_SetFSMParam —— 全局设置 FSM 参数

```csharp
[Name("设置FSM参数")]
[Category("VGame/FSM")]
[MemoryPackable]
public partial class GS_SetFSMParam : AGlobalScriptBase
{
    public ValueInput<Unit> target;    // 目标单位
    public ValueInput<string> param;   // 参数名（对应 EInputKey 字符串）
    public ValueInput<bool> value;     // 参数值
    public FlowOutput output;
    // Handler 中：调用 FSMComponent.TryManualCondition 或 ClearManualCondition
}
```

### 3.4 GS_GetFSMState —— 获取当前 FSM 状态

```csharp
[Name("获取FSM状态")]
[Category("VGame/FSM")]
[MemoryPackable]
public partial class GS_GetFSMState : AGlobalScriptBase
{
    public ValueInput<Unit> target;        // 目标单位
    public ValueOutput<string> stateName;  // 当前状态名（输出端口）
    // Handler 中：读取 FSMComponent.Fsm.CurrentState.name
}
```

### 3.5 CT_CheckFSMLastState —— 检查 FSM 上一个状态

```csharp
[Name("状态机前一个状态检测")]
[Category("VGame/条件")]
[MemoryPackable]
public partial class CT_CheckFSMLastState : ConditionTask
{
    [fsSerializeAs("Key")]
    [MemoryPackOrder(0)]
    public string Key;   // 期望的上一个状态名
    
    // 用途：如"只有从 FloatState 过来才能触发特殊起身动作"
}
```

### 3.6 CLIP_UniHurt —— Timeline 中的通用受击配置

```csharp
[Name("通用受击")]
[Description("标记受击类型并附加Tag")]
[MemoryPackable]
public partial class CLIP_UniHurt : ActionClip
{
    public EHurtType hurtType;      // 受击类型（僵直/格挡/拼刀/闪避等）
    public EStateTag stateTag;      // 附加状态 Tag
    
    // 各阶段的后摇帧数（单位：帧）
    public int hurtPerfomBreakDelayFrames = 4;   // 表演打断后摇
    public int hurtAtkDelayFrames = 16;          // 攻击打断后摇
    public int hurtMoveDelayFrames = 20;         // 移动打断后摇
    
    // 运行时计算得出的结果（供 Handler 使用）
    public int hurtEffectTime;   // 受击特效时间
    public int hurtPerformTime;  // 受击表演时间
    public int hurtAtkTime;      // 受击后可攻击时间
    public int moveBreakTime;    // 移动打断时间
}
```

### 3.7 CT_CompareNumeric —— 数值比较条件节点

```csharp
[Name("比较数值")]
[Category("VGame/条件")]
[MemoryPackable]
public partial class CT_CompareNumeric : ConditionTask
{
    public ValueInput<Unit> target;             // 比较的单位
    public ValueInput<ENumericId> numericId;    // 数值 ID（如 HP、Attack）
    public ValueInput<ENumericPart> part;       // 数值分量（Base/Add/Final等）
    public ValueInput<ENumericCmpType> cmpType; // 比较类型（大于/小于/等于）
    public ValueInput<FP> value;                // 比较目标值
    // Handler 中：读取 target 的 NumericComponent，比较对应数值
}
```

---

## 4. 节点分类详解

### 4.1 条件判断节点（CT_*）完整列表

| 节点 | 功能 |
|------|------|
| `CT_CheckFSMEvent` | 检查 FSM 是否有特定事件（触发状态转移） |
| `CT_CheckState` | 检查单位当前 FSM 状态 |
| `CT_CheckCD` | 检查技能 CD 是否冷却完毕 |
| `CT_CompareNumeric` | 比较单位的某个数值（血量/攻击/防御等） |
| `CT_CheckRange` | 检查目标是否在攻击范围内 |
| `CT_Grounded` | 检查单位是否在地面 |
| `CT_CheckInDodge` | 检查单位是否正在闪避 |
| `CT_RandomProbability` | 随机概率判断（如 30% 概率触发暴击效果） |
| `CT_CheckPerform` | 检查是否处于表演状态 |
| `CT_ConditionList` | 条件列表（AND/OR 组合多个条件） |

### 4.2 全局脚本节点（GS_*）功能

| 节点 | 功能 |
|------|------|
| `GS_TryUseSkill` | 尝试释放技能 |
| `GS_AddBuff` | 给目标添加/删除 Buff |
| `GS_SetFSMParam` | 设置 FSM 事件参数 |
| `GS_SetNumeric` | 设置数值 |
| `GS_AddNumeric` | 增减数值 |
| `GS_PlayTimeline` | 播放 Timeline |
| `GS_Timer` | 计时器（等待 N 帧/N 秒） |
| `GS_Wait` | 等待条件满足 |
| `GS_Log` | 日志输出（调试用） |
| `GS_StartCD` | 开始 CD 倒计时 |
| `GS_StartStory` | 触发剧情 |

### 4.3 目标脚本节点（TS_*）功能

| 节点 | 功能 |
|------|------|
| `TS_GetNumeric` | 获取目标单位的数值 |
| `TS_HealHp` | 治疗目标生命值 |
| `TS_HealGuard` | 恢复目标护盾 |
| `TS_ModifyNumeric` | 修改目标数值 |
| `TS_EnterState` | 让目标单位进入指定 FSM 状态 |
| `TS_GetAttackInfo` | 获取攻击信息（攻击者/攻击方向等） |
| `TS_SetTargetVelocity` | 设置目标速度 |
| `TS_TriggerSkillPerform` | 触发目标的技能表演 |
| `TS_GetOwnerTeam` | 获取目标所属队伍 |
| `TS_DestroyUnit` | 销毁目标单位 |

---

## 5. 设计亮点

### 5.1 图的嵌套（Sub FlowScript Node）
UniScript 支持在 FSM 状态节点内嵌套 FlowCanvas 子图（`FlowScriptNode`）。这让复杂的状态逻辑可以层次化拆分，FSM 管理宏观状态流转，每个状态内部用 FlowCanvas 管理微观执行流程，极大提升了可读性和可维护性。

### 5.2 图缓存与对象池
所有图（SkillGraph、UniFSM）都有对应的缓存池（`UnitComponent.SkillCache`、`FSMCache`）。图的 JSON 反序列化很耗时，对象池确保同一种图只被反序列化一次，后续使用时直接从池中取出、Reset 后使用，用完归还。

### 5.3 MemoryPack 高性能序列化
所有节点类都标注 `[MemoryPackable]`，支持 MemoryPack 二进制序列化（用于战斗存档/断线重连的状态快照），同时保留 JSON 序列化用于配置存储。两种序列化格式可以按场景选择。

### 5.4 ValueInput/ValueOutput 类型安全连线
UniScript 的节点端口是泛型类型（`ValueInput<T>`、`ValueOutput<T>`），编辑器在连线时会做类型检查，不兼容的类型无法连接，减少了类型错误的可能性。

### 5.5 fsSerializeAs 紧凑 JSON 键
所有节点字段使用 `[fsSerializeAs("短键")]` 标注（如 `[fsSerializeAs("at")]` 代替字段名 `dmgType`），将 JSON 中的键名从驼峰命名压缩为 1-3 个字符，大幅减少序列化后的文件体积。

---

## 6. 常见问题与最佳实践

### Q1：策划如何新增一个战斗逻辑节点？
**A**：策划无需改代码，通过现有节点（AT_*、CT_*、GS_*、TS_*）组合即可实现大多数逻辑。若确实需要新节点，程序员新建一个继承对应基类（如 `ActionTask`）的 C# 类，标注 `[Name]`/`[Category]` 属性，重新编译后即自动出现在编辑器的节点列表中。

### Q2：Timeline 的帧率和游戏帧率是同步的吗？
**A**：是的。Timeline 在 `SkillComponent.FixedUpdate` 中被手动推进（`UpdateGraph(deltaTime)`），每调用一次相当于推进一个逻辑帧，完全由逻辑层控制，不依赖 Unity 的 Time.fixedDeltaTime。

### Q3：如何在脚本节点之间传递复杂数据？
**A**：通过两种方式：
1. **ValueInput/ValueOutput 直接连线**：适合节点间的直接数值传递
2. **BlackboardComponent 黑板变量**：适合跨节点的临时数据存储（`TS_SetUnitBlackboard`/`TS_GetUnitBlackboard`）

### Q4：ct_ 条件节点的返回值是什么类型？
**A**：`ConditionTask` 继承体系中，条件节点的 `Evaluate()` 方法返回 `bool`。`true` 表示条件满足，`false` 表示不满足，FlowCanvas 和 FSM 根据此结果选择执行路径。

### Q5：CLIP 的激活时间范围是如何判断的？
**A**：每个 `ActionClip` 有 `startTime` 和 `length` 属性（定点数），每帧推进时，Timeline 会检查当前时间是否在 `[startTime, startTime+length)` 范围内。进入范围时调用 `Enter()`，在范围内每帧调用 `Update()`，离开范围时调用 `Exit()`。

### Q6：如何调试运行时的 UniScript 图执行情况？
**A**：在 Unity 编辑器运行模式下，UniScript 提供可视化调试界面：
- 流程图中当前执行的路径高亮显示
- FSM 中当前状态高亮
- 行为树中当前执行的节点高亮
- 可以在节点上设置断点，暂停执行
此外，`GS_Log` 节点可以在任意位置输出日志，方便追踪逻辑流程。
