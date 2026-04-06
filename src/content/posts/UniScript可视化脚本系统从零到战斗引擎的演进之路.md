---
title: UniScript 可视化脚本系统：从零到战斗引擎的演进之路
published: 2026-04-06
description: 横向剖析 UniScript 的节点体系分层，纵向还原它从"通用蓝图"走向"战斗专用可视化脚本引擎"的演进脉络，兼顾设计哲学与工程取舍。
tags: [Unity, 战斗系统, 可视化脚本, UniScript, 蓝图, NodeCanvas, FlowCanvas, FSM, Timeline]
category: 战斗系统
draft: false
encryptedKey:henhaoji123
---

# UniScript 可视化脚本系统：从零到战斗引擎的演进之路

## 序言：为什么游戏需要可视化脚本？

当一个战斗技能需要"在第 8 帧打开攻击判定框、检测到命中后根据目标状态机判断是否触发破防、随后按 AI 策略决定下一段连招、同步发送 FSM 事件让角色动画正确过渡"——这样的需求交给程序用纯代码写，每个技能都是一套特化逻辑，策划改一次数值就要拉代码评审。交给策划？Excel 配置表表达不了这种复杂的逻辑分支。

可视化脚本（Visual Script）本质上是一门**图形化编程语言**：节点是语句，连线是数据流/控制流，画布是程序。它让策划和 TA 也能描述"当 A 发生时，对 B 做 C，但如果 D 条件成立则改做 E"这样的逻辑，同时让程序员可以预先把每个原子能力封装成节点，以节点为边界做热更新与安全隔离。

本文围绕项目中实际使用的 **UniScript** 系统，做两个维度的剖析：

- **横向**：UniScript 的节点体系是如何分层的，各层职责是什么，它们拼在一起如何驱动一场战斗？
- **纵向**：这套系统从一个通用蓝图框架，是如何一步步演进成为深度定制的战斗脚本引擎的？

---

## 一、横向剖析：节点体系的五层架构

翻开 `UniScript/` 目录，可以识别出 5 个清晰的功能层次。

### 第一层：Graph 与 Canvas Core（画布核心）

整个系统以 **Graph（图）** 为最顶层容器。`GraphFactory.cs` 负责图的创建与反序列化：

```csharp
public static T CreateGraph<T>(string path)
{
    var result = TryGetCacheData<T>(path);
    if (result != null) return result;
    return SerializeHelper.Deserialize<T>(path);
}
```

在编辑器里它可以从 EditorLoader 读取缓存副本，运行时直接从序列化数据（JSON 或 MemoryPack 二进制）还原。这是图的"工厂入口"。

Graph 有两种核心子类型：

| 图类型 | 对应脚本层 | 职责 |
|---|---|---|
| `UniFSM` | FSMNode 层 | 状态机，驱动角色状态转换 |
| `SkillGraph` | FlowScript 层 | 技能流图，驱动一个技能的执行过程 |

### 第二层：FSMNode（状态机节点层）

`FlowScriptState` 和 `FlowScriptNode` 是状态机内部两种不同的嵌套方式：

**FlowScriptState**：FSM 的一个**完整状态**，内部包含一个完整的 `SkillGraph`（流图）。状态进入时启动流图，流图执行完毕触发 `successEvent` 或 `failureEvent`，FSM 据此决定下一个状态。这是"角色技能状态"的标准载体。

```csharp
void OnFlowScriptFinished(bool success) {
    if (!string.IsNullOrEmpty(successEvent) && success)
        SendEvent(successEvent);
    if (!string.IsNullOrEmpty(failureEvent) && !success)
        SendEvent(failureEvent);
    Finish(success);
    CheckTransitions();
}
```

**FlowScriptNode**：FSM 中的一个**并行逻辑节点**，带有 `IUpdatable` 接口，每帧主动调用 `UpdateGraph`。用于"不独占状态但需要持续运行的子逻辑"，比如某些被动效果的持续检测。

```csharp
[Name("Sub FlowScript Node",-1)]
[Description("并行逻辑")]
public override int maxInConnections => 0;  // 无入连接
public override int maxOutConnections => 0; // 无出连接
public override bool allowAsPrime => false; // 不能作为起始节点
```

这种设计将"状态"与"并行"两种逻辑模式都统一在 FSM 结构中，而不需要单独的并行层。

### 第三层：ActionTask 与 ConditionTask（原子动作与条件层）

这是战斗逻辑的**原子操作**层。

**ActionTask（AT_ 前缀）**：执行一个副作用——修改状态、发送事件、播放特效等：

| 节点 | 职责 |
|---|---|
| `AT_AttackDamage` | 使目标受到攻击伤害 |
| `AT_AddBuff` | 给目标添加 Buff |
| `AT_FireFsmEvent` | 向目标/自己的 FSM 发送事件 |
| `AT_Move` / `AT_StopMove` | 控制角色移动 |
| `AT_SetStateTag` | 设置角色状态标签（无敌、霸体等） |
| `AT_UseToken` | 消耗技能点（Token） |
| `AT_TimeScale` | 修改时间缩放 |

**ConditionTask（CT_ 前缀）**：纯读取，返回 bool——用于判断：

| 节点 | 职责 |
|---|---|
| `CT_CheckFSMEvent` | 检测是否存在指定 FSM 事件 |
| `CT_CheckState` | 检测角色当前状态标签 |
| `CT_CheckCD` | 检测技能 CD 状态 |
| `CT_CompareNumeric` | 比较数值变量 |
| `CT_RandomProbability` | 随机概率判断 |
| `CT_CheckVkeyInput` | 检测虚拟按键输入 |

这两类节点是**程序员和策划之间的契约接口**：程序写节点实现（保证安全、高效），策划在画布上组合使用（描述逻辑）。

### 第四层：Switch 节点（分支路由层）

Switch 节点做的是**枚举/状态路由**——根据当前上下文选择走哪条流程分支：

```
SwitchPerfromResult  → 根据技能表演结果分支
SwitchMoveType       → 根据移动类型分支
SwitchStateTag       → 根据状态标签分支
SwitchTokenType      → 根据 Token 类型分支
SwitchRandResult     → 随机分支
SwitchTeamIdx        → 根据队伍索引分支
```

这些 Switch 节点在 FlowScript 中充当"路由器"，策划把复杂的分支逻辑变成一目了然的放射状节点图，远比代码里的 `switch-case` 直观。

### 第五层：Timeline 与 Clip（时序执行层）

`GS_PlayTimeline` 是整个系统的"时间引擎入口"。它将技能执行映射到一条精确的时间线上：

```csharp
[Name("播放时间轴")]
[Description("播放一个时间轴，时间轴不能并行……时间轴分为 bound 类型和 id 类型")]
public EAssetType AssetType;  // Bound（节点专属）或 Persistent（通用 ID 引用）
public int SubSkillIndex;     // 子技能索引，用于多段技能
public Timeline MTimeline;    // 内嵌时间轴数据
```

Timeline 上的 Clip 类型极为丰富，按职责分类：

**碰撞判定 Clip**：
- `CLIP_HurtCollider`：受击框，按帧存储碰撞体列表，支持逐帧精确配置
- `CLIP_SetAttackCollider`：攻击判定框
- `CLIP_LogicCollider`：逻辑碰撞（不造成伤害，用于触发事件）

**事件触发 Clip**：
- `CLIP_BattleEvent`：触发战斗事件
- `CLIP_OnKeyInput`：检测按键输入窗口
- `CLIP_OnConditionTrue`：条件满足时触发

**衍生技能 Clip**：
- `CLIP_ConditionalDerive`：条件衍生，满足条件则在此时间点切换子技能
- `CLIP_UnhitDerive`：未命中衍生
- `CLIP_WaitDerive`：等待衍生

**运动控制 Clip**：
- `CLIP_RootMotion`：根骨骼运动区间
- `CLIP_MotionWarp`：运动扭曲（自动调整攻击距离）

`CLIP_HurtCollider` 的帧碰撞体方案尤其值得关注：

```csharp
public List<FrameCollider> frameColliders = new();

public List<ColliderInfo> GetNearestCollidersByFrame(int frame)
{
    for (int i = frameColliders.Count - 1; i >= 0; i--)
    {
        if (frameColliders[i].frame <= frame)
            return frameColliders[i].colliders;
    }
    return null;
}
```

它不是每帧都存一份碰撞体，而是**只存变化帧**，查询时找最近一个 `frame <= 当前帧` 的碰撞体。这是空间换时间+稀疏存储的典型设计——对于大多数帧碰撞体不变的情况，显著减少序列化数据量。

---

## 二、纵向剖析：从通用蓝图到战斗专用引擎

UniScript 不是凭空诞生的战斗脚本系统。它经历了一个"通用 → 专用 → 深度定制"的演进过程。

### 阶段一：移植通用蓝图框架

最早的基础来自 **NodeCanvas / FlowCanvas**，这是 Unity 生态中广为人知的可视化脚本解决方案。FlowCanvas 提供 FlowNode（流程节点）与 FlowGraph（流图），NodeCanvas 提供 BehaviourTree 和 FSM。

项目选择了这个底层，但没有直接用开箱即用的版本，而是**深度魔改**，核心改动在序列化层：

```csharp
// UniScriptRuntimeInit.cs
public static void RegisterTypeConverter()
{
    UniScript.TypeConverter.customConverter += TypeConverterOncustomConverter;
    UniScript.FlowCanvas.TypeConverter.customConverter += TypeConverterOncustomConverter;
}
```

注册了自定义类型转换器，将项目的 `Unit`（战斗单元）映射到框架的 `IActor` 接口。这是对接游戏专有类型体系的第一步。

序列化方案也从原版的纯 JSON 演变为双轨制：
- **Editor 阶段**：JSON（人类可读，方便调试与版本控制）
- **Runtime 阶段**：MemoryPack 二进制（极速反序列化，减少 GC 压力）

```csharp
[MemoryPackable]
public partial class FlowScriptNode : FSMNodeNested<SkillGraph>, IfsSerializationCallbackReceiver
{
    [fsSerializeAs("_skillJson")]   // JSON 序列化 key
    [MemoryPackOrder(-29)]          // 二进制序列化顺序
    internal string _skillJson;
    
    internal SkillGraph _flowScript = null;
}
```

### 阶段二：引入游戏领域模型

通用蓝图框架的节点是泛化的（数学运算、字符串处理、通用逻辑）。战斗系统需要的是领域节点。

于是 `ScriptDefine.cs` 诞生了——它是整个 UniScript 与战斗领域的**类型注册中心**：

```csharp
// 黑板支持的基础类型（变量系统使用）
[UniTypeCollect(UniCollectType.Basic)]
public static List<Type> s_preferedTypes = new List<Type>()
{
    typeof(bool), typeof(int), typeof(long),
    typeof(FP),          // 定点数（帧同步安全）
    typeof(TSVector),    // 定点向量
    typeof(Unit),        // 战斗单元
    typeof(StoryVariable)
};

// 枚举类型（供 Switch 节点使用）
[UniTypeCollect(UniCollectType.Enum)]
public static List<Type> s_enumTypes = new List<Type>()
{
    typeof(ENumericId),     // 数值类型枚举
    typeof(EInputKey),      // 虚拟按键
    typeof(EStateTag),      // 状态标签
    typeof(ETokenType),     // 技能点类型
    typeof(EBuffViewState), // Buff 显示状态
    // ...共 30+ 枚举类型
};
```

**关键决策点**：类型系统使用了**定点数 `FP` 而非 `float`**。这是帧同步的基本要求——浮点运算在不同平台、不同编译器可能产生微小差异，导致帧同步对局的状态分叉。将所有战斗数值强制为定点数，是在可视化脚本层面对帧同步安全的一种**强制约束**。

策划在编辑器里拖节点、填参数，但系统底层保证了他们无法引入浮点运算风险。

### 阶段三：Timeline 的演进——从引用到内嵌

早期的 `GS_PlayTimeline` 设计支持两种模式：
- `Persistent`：通过 ID 引用外部 Timeline 文件
- `Bound`：将 Timeline 数据直接内嵌在节点中

运行时代码中残留着历史痕迹：

```csharp
protected override void NodeOnAfterDeserialize()
{
    if (AssetType == EAssetType.Bound)
    {
        if (!string.IsNullOrEmpty(_boundJson))
        {
            MTimeline = JSONSerializer.Deserialize<Timeline>(_boundJson);
            Log.Warning("GS_PlayTimeline修改为Json展开保存模式，请重新保存文件");
        }
    }
    else
    {
        Log.Error("GS_PlayTimeline 引用功能已废弃 引用时间轴使用CLIP_TimelineReference");
        // 兼容旧数据，从文件加载...
    }
}
```

**Persistent（引用）模式被废弃了**，原因在于游戏后期发现"通用时间轴复用"的价值远低于预期——每个角色的技能时序都高度个性化，复用率低，反而带来了资源管理的额外复杂性（修改共享 Timeline 会影响所有引用者）。

演进方向是**彻底内嵌**：每个 `GS_PlayTimeline` 节点持有完整的 Timeline 数据，`JsonPrintToCSharp` 特性将其在构建时展开为 C# 代码，既消除了运行时的文件 IO，又让 HybridCLR 的热更新更加稳定。

这是一种**以冗余换确定性**的工程取舍：牺牲复用率，换来了零运行时依赖、零加载等待、零资源引用错误。

### 阶段四：节点分类的精细化

早期节点可能是扁平的，随着战斗需求爆炸式增长（光 Clip 就有 50+ 种），系统发展出了严格的命名前缀规范：

```
AT_   ActionTask     —— 执行副作用（改变世界状态）
CT_   ConditionTask  —— 纯查询（读状态，返回 bool）
TS_   Target Script  —— 对特定目标执行操作
GS_   Global Script  —— 全局脚本（不依赖特定目标）
TG_   Trigger        —— 触发器（订阅事件）
CLIP_ Timeline Clip  —— 时间轴片段
```

这套命名约定不只是美观问题，它在**编辑器的节点搜索面板中提供了隐式分组**，策划搜索 `AT_` 时快速定位所有动作节点，搜索 `CT_` 找条件节点。在节点数量超过 200 个时，这种分组效率极为关键。

### 阶段五：帧同步安全强化

UniScript 被应用于帧同步战斗的另一个挑战：**节点内部不能有非确定性行为**。

`ScriptEvtTypeDefine.cs` 中保留了一段被注释掉的旧代码（长达数百行的类型字典注册）：

```csharp
/*
public static void Register(Dictionary<long, Type> dict)
{
    dict.Add(2147483855, typeof(TG_Event<Evt_StartSelectAtkSkill>));
    // ...
}
*/
```

这段代码曾经是运行时的类型路由表——通过 ID → Type 的字典动态分发事件。被注释后，取而代之的是**构建时代码生成**（`JsonPrintToCSharp` 特性）。

原因很直接：运行时反射（`Type.GetType()`）在不同平台下可能有微秒级的时序差异；IL2CPP 和 Mono 的反射性能差异在帧同步高频调用下会被放大。将类型信息转为静态 C# 代码，消除了这类不确定性。

---

## 三、当前架构全景

将五个节点层次与三条主要数据流路径画在一起：

```
┌─────────────────────────────────────────────────────────┐
│                     UniFSM（状态机）                     │
│                                                         │
│  ┌──────────────┐      ┌──────────────┐                │
│  │FlowScriptState│ ──► │FlowScriptNode│（并行逻辑）     │
│  │  （主状态）   │      │  （辅助状态）  │                │
│  └──────┬───────┘      └──────────────┘                │
│         │ 内含                                          │
└─────────┼───────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────┐
│                  SkillGraph（技能流图）                   │
│                                                         │
│  [GS_ 全局节点] → [Switch 分支节点] → [TS_ 目标节点]    │
│       ↓                                                 │
│  GS_PlayTimeline                                        │
│       │ 内含                                            │
└───────┼─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────────────────────────────────────────┐
│                  Timeline（时间轴）                      │
│                                                         │
│  Frame 0──5──10──15──20──25──30──35──40──45──50        │
│    │    │         │              │                      │
│  CLIP_ │     CLIP_HurtCollider  │                      │
│  RootMotion    （受击框逐帧）    CLIP_AttackEnd         │
│       CLIP_OnKeyInput（输入窗口）                        │
│             CLIP_ConditionalDerive（条件衍生）           │
└─────────────────────────────────────────────────────────┘

                    ↑ 条件查询
┌─────────────────────────────────────────────────────────┐
│           CT_ / AT_ / TS_ 原子节点层                    │
│   CT_CheckFSMEvent  CT_CheckState  CT_RandomProbability │
│   AT_AttackDamage   AT_AddBuff     AT_FireFsmEvent      │
│   TS_ModifyNumeric  TS_HealHp      TS_ActionTask        │
└─────────────────────────────────────────────────────────┘
```

### 一次完整的技能执行流

以"角色发动一个连击技能"为例，数据流如下：

1. **输入层**：`CT_CheckVkeyInput` 检测到玩家按下攻击键 → FSM 事件触发
2. **FSM 层**：`UniFSM` 收到事件，从 Idle 状态转入 Attack1 状态
3. **FlowScript 层**：进入 `FlowScriptState`，启动对应的 `SkillGraph`
4. **技能图层**：`SkillGraph` 执行 `GS_PlayTimeline`，播放攻击时间轴
5. **Timeline 层**：
   - 第 3-8 帧：`CLIP_HurtCollider` 激活受击判定框
   - 第 5 帧：`CLIP_OnKeyInput` 开始监听追击输入窗口
   - 第 8 帧：`CLIP_OnColliderHit` 检测到命中 → 触发事件
6. **事件回调**：事件触发 `AT_AttackDamage`（算伤害）、`AT_AddBuff`（加减速 Buff）
7. **衍生判断**：`CLIP_ConditionalDerive` 检查玩家是否在窗口内按键 → 决定是否接续第二段攻击
8. **FSM 跳转**：时间轴结束，`successEvent` 发出 → FSM 决定回到 Idle 或进入 Attack2

整个流程跨越 5 个层次，每层各司其职，无一层需要了解其他层的内部细节。

---

## 四、设计哲学总结

### 1. 数据优先，逻辑热更新

UniScript 的每个节点都是**数据**（可序列化）而非硬编码逻辑。这意味着技能可以作为配置文件下发，支持热更新，策划修改技能不需要发版。

### 2. 帧同步安全是红线

所有运行时路径强制使用定点数，禁止浮点；类型路由从反射改为代码生成；随机数从系统随机改为帧同步随机（`CT_RandomProbability` 内部必须使用确定性随机器）。可视化脚本让策划"越权"的边界被硬约束在类型系统里。

### 3. 编辑器友好是生产力保障

`CLIP_HurtCollider` 中有大量 `#if UNITY_EDITOR` 代码用于在 Timeline 轨道上可视化每帧碰撞体；`GS_PlayTimeline` 节点名称显示子技能名称和时长，Strategy 策划在编辑器里能一眼看清技能结构；`CT_` 节点的 `info` 属性重写为关键参数，节点连线上直接显示判断条件。这些都是生产力细节。

### 4. 演进而非重写

从引用 Timeline 到内嵌 Timeline，从运行时反射到构建期代码生成，从纯 JSON 到 MemoryPack 双轨制——每次演进都是**外科手术式的局部替换**，保持向后兼容（旧数据有 fallback 逻辑），直到足够稳定后才清理旧代码。这种演进策略保证了"系统在线上稳定运行的同时持续改进"。

---

## 结语

UniScript 系统并不是一开始就被设计成今天这个形状的。它是在战斗复杂度的不断压迫下，每次遇到具体问题时做出具体决策的产物：帧同步压迫出了定点数约束，技能爆炸压迫出了 Timeline 内嵌，节点爆炸压迫出了命名前缀规范，热更新需求压迫出了序列化双轨制。

这种演进方式有一个深刻的内在逻辑：**好的架构不是被设计出来的，是被需求逼出来的**。真正重要的是在每次决策时，有清晰的权衡视角——知道在放弃什么、在得到什么。

对于想要在自己项目中引入可视化脚本的读者：不必从零实现一套完整系统，选一个成熟的底层（NodeCanvas、Bolt、XNode 都是合理选项），然后**在你的领域边界上定制它**。UniScript 的价值不在于它的底层有多精妙，而在于它把 NodeCanvas 和游戏战斗的"领域胶水层"做得足够结实。
