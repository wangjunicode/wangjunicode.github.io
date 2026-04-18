---
title: 游戏战斗日志分层系统-BattleLogTag枚举与LogFilterType标志位与LogKey结构体的完整设计解析
published: 2026-04-18
description: 深入解析游戏框架战斗日志系统的分层架构设计，包括BattleLogTag枚举、LogFilterType位运算过滤器、LogKey结构体、LogState状态日志机制及ZString零GC字符串拼接在实战中的应用
tags: [Unity, 游戏框架, 日志系统, 战斗系统, 性能优化]
category: 技术深度
draft: false
encryptedKey: henhaoji123
---

# 游戏战斗日志分层系统设计与解析

## 概述

在大型游戏项目的战斗系统中，日志不是简单的 `Debug.Log`，而是一套有层次、有分类、可过滤的调试基础设施。本文深入解析框架中 `LogEx.cs` 的战斗日志体系，包括 `BattleLogTag` 枚举分类、`LogFilterType` 位运算过滤器、`LogKey` 零GC结构体，以及 `LogState` 状态追踪机制。

---

## 一、三层日志架构

```
游戏框架日志体系
    ├── 基础日志层（Logger + ILog）        - 通用 Info/Warning/Error
    ├── 战斗日志层（LogEx / Log partial） - 战斗专属分类日志
    └── 状态日志层（LogState）            - 键值式持久化状态追踪
```

`LogEx.cs` 属于战斗日志层与状态日志层，专为战斗系统设计，关注的是**战斗逻辑追踪**而非一般运行时错误。

---

## 二、BattleLogTag：战斗日志分类枚举

### 源码定义

```csharp
public enum BattleLogTag
{
    Default,
    Combo,           // 连击
    Perform,         // 演出/技能表现
    Input,           // 输入
    ComboDetail,     // 连击详情
    SelectPerform,   // 选择演出
    RegisterPerform, // 注册演出
    UnRegisterPerform,
    TryUsePerform,
    BattlePointTryPerform,
    PerformDetail,   // 演出详情
    AddToken,        // 添加Token资源
    UseToken,        // 使用Token资源
    ClearToken,      // 清除Token资源
    BattlePointStart,
    BattlePointEnd,
    DirectorSkill,   // 导演技能
    Turn,            // 回合
    ChangeDef,       // 防御值变化
    Skill,           // 技能
    Node,            // 节点
    Damage,          // 伤害
    Debug,           // 调试
    Error,           // 错误
}
```

这个枚举设计体现了战斗系统的**功能边界划分**：

| 分类 | Tags | 对应战斗子系统 |
|------|------|--------------|
| 连击系统 | Combo, ComboDetail | 连击判断与计数 |
| 技能演出 | Perform, SelectPerform, RegisterPerform... | 技能表现层 |
| 资源管理 | AddToken, UseToken, ClearToken | 技能资源（Token/法力/怒气） |
| 回合系统 | Turn, BattlePointStart/End | 回合制战斗流程 |
| 伤害计算 | Damage, ChangeDef | 数值计算层 |
| 技能节点 | Skill, Node, DirectorSkill | 可视化技能图节点 |

---

## 三、LogFilterType：位运算过滤器

### 源码定义

```csharp
[Flags]
public enum LogFilterType
{
    Default     = 0,
    Turn        = 1 << 0,   // 1
    Input       = 1 << 1,   // 2
    ChangeDef   = 1 << 2,   // 4
    Token       = 1 << 3,   // 8
    BattlePoint = 1 << 4,   // 16
    Perform     = 1 << 5,   // 32
    Combo       = 1 << 6,   // 64
    Skill       = 1 << 7,   // 128
    Node        = 1 << 8,   // 256
    Damage      = 1 << 9,   // 512
    Debug       = 1 << 10,  // 1024
}
```

`[Flags]` 特性使枚举支持位运算组合：

```csharp
// 只看 Combo + Damage 相关日志
var filter = LogFilterType.Combo | LogFilterType.Damage;  // = 64 | 512 = 576

// 过滤判断核心逻辑
public static bool FilterResult(this LogFilterType type, string str)
{
    return Log.LogFilter
        .Where(x => ((int)x.Key & (int)type) == (int)x.Key)  // 位AND判断是否包含该类型
        .Any(filter => filter.Value.Any(str.StartsWith));      // 前缀匹配日志字符串
}
```

### LogFilter 映射表

```csharp
public static readonly Dictionary<LogFilterType, List<string>> LogFilter = new()
{
    { LogFilterType.Turn, new List<string>
    {
        LogPrefix + Turn,    // "BattleInfo: [Turn]"
        LogPrefix + Perform,
        LogPrefix + Combo,
    }},
    { LogFilterType.Token, new List<string>
    {
        LogPrefix + AddToken,    // "BattleInfo: [Add Token]"
        LogPrefix + UseToken,
        LogPrefix + ClearToken
    }},
    // ...
};
```

这里有个有趣的设计：**Turn 过滤器包含了 Perform 和 Combo 的前缀**，因为回合制战斗中，连击和演出信息对于回合调试往往是必要的上下文。

### 位运算过滤器的优势

```csharp
// 旧方案：字符串比较，每次 O(n)
if (tag == "Turn" || tag == "Combo" || tag == "Damage") { ... }

// 新方案：位运算，O(1)
if ((activeFilter & LogFilterType.Turn) != 0) { ... }

// 组合开关极其简洁
activeFilter |= LogFilterType.Damage;   // 开启伤害日志
activeFilter &= ~LogFilterType.Node;   // 关闭节点日志
```

---

## 四、LogState：键值式状态日志

### 设计理念

不同于普通日志（时序流水记录），`LogState` 是**键值存储**式的状态快照：

```
普通日志：  [Turn 1] Attack A; [Turn 1] Attack B; [Turn 2] Defend;
LogState：  Unit[101].State = "HP:100 ATK:50 DEF:30"  ← 随时覆写，只保留最新状态
```

### LogKey 结构体：零GC设计

```csharp
public partial struct LogKey
{
    private string name;

    public override string ToString() => name ?? string.Empty;

    public static LogKey Make(string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = name };
        return default;  // ← 未启用时返回空结构体，零开销
    }

    public static LogKey Make(long id, string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = ZString.Concat(id, " ", name) };
        return default;
    }
}
```

`LogKey` 是 **struct（值类型）**，原因：
1. 避免堆分配和 GC 压力（战斗系统每帧调用频繁）
2. `EnableStateLog = false` 时直接返回 `default`，连字符串拼接都不执行

预定义的业务键：
```csharp
public static readonly LogKey DistanceKey   = LogKey.Make("[Distance]");
public static readonly LogKey ExecutantKey  = LogKey.Make("[Executant]");
public static readonly LogKey TurnKey       = LogKey.Make("[Turn]");
public static readonly LogKey DamageKey     = LogKey.Make("[Damage]");

// 带 ID 的实例键（每个单位独立追踪）
public static LogKey StateKey(long id)   => LogKey.Make(id, "[-States-]");
public static LogKey TokenKey(long id)   => LogKey.Make(id, "[-Token-]");
public static LogKey PerformKey(long id) => LogKey.Make(id, "[-Perform-]");
```

### LogState 操作 API

```csharp
// 覆写状态
Log.LogState(LogKey.StateKey(unitId), append: false, "HP", ":", hp);

// 追加状态（不覆盖，追加到已有内容后面）
Log.LogStateAppend("ATK:", atk, " DEF:", def);

// 读取状态（用于调试窗口展示）
string state = Log.GetLogState(LogKey.StateKey(unitId));

// 清除状态
Log.ClearLogState(LogKey.StateKey(unitId));
```

`append` 参数控制写入模式：
- `false` → 完全覆写，每帧刷新最新状态
- `true` → 追加，构建历史记录流

---

## 五、BattleInfo 日志：带帧号的结构化输出

### 输出格式

```csharp
private static void LogBattleInfo(BattleLogTag tag, string message)
{
    if (!EnableStateLog) return;
    LogInfo(ZString.Concat(
        LogPrefix,              // "BattleInfo: "
        LogTagTable[tag],       // "[Damage]"
        " ",
        BattleFrameGetter?.Invoke() ?? Game.FixedFrames,  // 战斗帧号
        " ",
        message                 // 具体内容
    ));
}
```

输出示例：
```
BattleInfo: [Damage] 142 Unit[101] deal 256 dmg to Unit[202]
BattleInfo: [Combo]  142 Unit[101] combo x3
BattleInfo: [Turn]   143 Round 5 starts
```

**帧号设计**的价值：
- 精确定位"第几帧发生了什么"
- 帧同步游戏中，不同客户端可以对比帧日志查找分歧点

### ZString 零GC字符串拼接

```csharp
// 传统写法：大量字符串对象，触发GC
string msg = tag + " " + frame + " " + content;

// ZString写法：StackAlloc + ZeroAlloc，无堆分配
var msg = ZString.Concat(tag, " ", frame, " ", content);
```

ZString 使用栈分配和内存池，在不产生 GC 压力的前提下完成字符串拼接，这对于每帧可能调用数十次的战斗日志系统至关重要。

---

## 六、多参数重载的模板设计

```csharp
// LogState 的多参数重载（T1 ~ T7）
public static void LogState<T1>(LogKey key, bool append, T1 t1) { ... }
public static void LogState<T1, T2>(LogKey key, bool append, T1 t1, T2 t2) { ... }
// ... 最多支持 7 个参数
```

这种设计替代了 `params object[]`：
- **`params object[]`** 会触发数组堆分配 + 装箱（int→object），造成 GC
- **泛型重载** 通过 JIT 特化，避免装箱，零GC

这是与 ZString 的设计哲学完全一致的：**用代码冗余换取运行时零分配**。

---

## 七、LogStateCache：调试窗口数据源

```csharp
private static Dictionary<string, string> LogStateCache = new();
```

`LogStateCache` 作为内存中的"状态黑板"，可以直接被编辑器调试窗口读取：

```csharp
// 调试窗口 OnGUI 中实时展示所有战斗状态
foreach (var kv in Log.LogStateCache)
{
    GUILayout.Label($"{kv.Key}: {kv.Value}");
}
```

这样在不暂停游戏的情况下，开发者可以实时观察每个单位的状态（HP、Token、Combo次数等），大幅提升战斗调试效率。

---

## 八、BattleFrameGetter：注入式帧号获取

```csharp
public static Func<int> BattleFrameGetter;
```

这是一个**可选注入的委托**，设计意图：

1. 战斗帧号由战斗系统维护，日志系统不应直接依赖战斗系统（避免循环引用）
2. 通过依赖注入，日志系统与战斗系统解耦
3. 框架不存在时降级使用 `Game.FixedFrames`（逻辑帧）

```csharp
// 战斗系统初始化时注入
Log.BattleFrameGetter = () => BattleWorld.Instance.CurrentFrame;
```

---

## 九、设计总结

| 设计点 | 技术手段 | 解决的问题 |
|--------|----------|-----------|
| 日志分类 | BattleLogTag 枚举 + 映射表 | 海量日志中快速定位目标 |
| 动态过滤 | [Flags] 位运算 | O(1) 开关多维度日志 |
| 零GC键 | LogKey struct + conditional | 生产环境零开销 |
| 零GC拼接 | ZString.Concat 泛型重载 | 战斗帧内无堆分配 |
| 状态追踪 | LogStateCache Dictionary | 实时调试窗口数据源 |
| 帧精度 | BattleFrameGetter 注入 | 帧同步分歧定位 |

这套战斗日志系统的核心哲学是：**开发期提供尽可能丰富的调试信息，发布期实现绝对零开销**——通过 `EnableStateLog` 开关，所有日志相关代码在 Release 构建中完全短路，不产生任何性能损耗。
