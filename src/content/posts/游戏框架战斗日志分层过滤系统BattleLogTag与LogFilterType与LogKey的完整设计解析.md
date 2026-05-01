---
title: 游戏框架战斗日志分层过滤系统BattleLogTag与LogFilterType与LogKey的完整设计解析
published: 2026-05-01
description: '深入解析 xGame 框架 LogEx.cs 中的战斗信息分层日志体系：BattleLogTag 枚举定义的24种战斗事件类别、LogFilterType 标志位枚举实现的按位组合过滤、LogKey 结构体的零分配 ID 键设计，以及 LogState 快照系统和 BattleInfo 帧绑定输出机制，全面揭示生产级战斗调试基础设施的设计原理。'
image: ''
tags: [Unity, 游戏框架, xGame, 战斗系统, 日志系统, ZLogger, BattleLogTag, 调试工具]
category: '技术分析'
draft: false
lang: ''
encryptedKey: henhaoji123
---

## 引言

战斗系统是游戏客户端最复杂的模块之一，每帧可能产生数百条调试信息。如果所有日志无差别输出，开发时完全无法定位问题；如果全部关闭，又丧失了洞察力。

xGame 框架的 `LogEx.cs` 给出了一个精心设计的解答：以 `BattleLogTag` 为分类维度，以 `LogFilterType` 标志位为过滤粒度，以 `LogKey` 结构体为零分配键，构建了一套"按需开灯"的战斗日志系统。

---

## 架构全景

```
战斗事件发生
    ↓
Log.LogBattleInfo(tag, message)
    ↓
EnableStateLog 检查（全局开关）
    ↓
查询 LogTagTable → 生成 "BattleInfo: [Tag] [Frame] message"
    ↓
LogState 缓存 / 直接 LogInfo 输出
    ↓
外部工具通过 LogFilter + FilterResult() 按位过滤
```

整套系统的开销只在 `EnableStateLog == true` 时产生，Release 构建直接短路，不影响性能。

---

## BattleLogTag：24 种战斗事件分类

```csharp
public enum BattleLogTag
{
    Default,
    Combo,          // 连击
    Perform,        // 演出/行为执行
    Input,          // 输入
    ComboDetail,    // 连击细节
    SelectPerform,  // 选择演出
    RegisterPerform, UnRegisterPerform, TryUsePerform,
    BattlePointTryPerform, PerformDetail,
    AddToken, UseToken, ClearToken,  // 代币/资源管理
    BattlePointStart, BattlePointEnd,
    DirectorSkill,
    Turn,    // 回合
    ChangeDef,
    Skill,
    Node,    // 行为节点
    Damage,
    Debug,
    Error,
}
```

这 24 个分类覆盖了一场战斗从"输入 → Perform 选择 → Combo 连击 → 伤害计算 → 回合结束"的完整链路。每个分类对应一个独立的字符串常量前缀：

```csharp
public const string Combo   = "[Combo]";
public const string Perform = "[Perform]";
public const string Damage  = "[Damage]";
// ... 共 24 个
```

**为什么用 enum + Dictionary 而不是直接 switch？**

`LogTagTable` 是一个 `Dictionary<BattleLogTag, string>`，查找是 O(1)。更重要的是，这个 Table 可以在运行时被替换或扩展，而 switch 是编译时固定的。若后续要支持自定义标签，只需往字典里加条目。

---

## LogFilterType：标志位过滤粒度

```csharp
[Flags]
public enum LogFilterType
{
    Default    = 0,
    Turn       = 1 << 0,
    Input      = 1 << 1,
    ChangeDef  = 1 << 2,
    Token      = 1 << 3,
    BattlePoint = 1 << 4,
    Perform    = 1 << 5,
    Combo      = 1 << 6,
    Skill      = 1 << 7,
    Node       = 1 << 8,
    Damage     = 1 << 9,
    Debug      = 1 << 10,
}
```

注意 `[Flags]` 特性，这允许按位组合过滤器：

```csharp
// 只看 Combo 和 Damage
var filter = LogFilterType.Combo | LogFilterType.Damage;

// 查某条日志是否在这个过滤器范围内
bool visible = filter.FilterResult(logLine);
```

`FilterResult` 的实现：

```csharp
public static bool FilterResult(this LogFilterType type, string str)
{
    return Log.LogFilter
        .Where(x => ((int)x.Key & (int)type) == (int)x.Key)
        .Any(filter => filter.Value.Any(str.StartsWith));
}
```

逻辑是：遍历 `LogFilter` 字典，找到 Key（`LogFilterType`）是 `type` 子集的所有条目，检查字符串是否以这些条目的前缀开头。

一个 `LogFilterType` 可以映射多个前缀字符串：

```csharp
{LogFilterType.Turn, new List<string> {
    LogPrefix + Turn,     // "BattleInfo: [Turn]"
    LogPrefix + Perform,  // "BattleInfo: [Perform]"
    LogPrefix + Combo,    // "BattleInfo: [Combo]"
}},
```

这是因为"Turn 过滤器"需要同时看到演出和连击信息，才能还原一个回合的完整上下文。

---

## LogKey：零分配的状态快照键

```csharp
public partial struct LogKey
{
    private string name;
    
    public static LogKey Make(string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = name };
        return default;  // EnableStateLog=false 时返回空结构体
    }
    
    public static LogKey Make(long id, string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = ZString.Concat(id, " ", name) };
        return default;
    }
}
```

`LogKey` 是值类型（struct），避免了对象分配。更关键的是，`Make` 方法在 `EnableStateLog == false` 时直接返回 `default`（空结构体），整个系统的字符串构造都被跳过。

框架提供了一批预定义的 LogKey：

```csharp
public static readonly LogKey DistanceKey   = LogKey.Make("[Distance]");
public static readonly LogKey ExecutantKey  = LogKey.Make("[Executant]");
public static readonly LogKey TurnKey       = LogKey.Make("[Turn]");
public static readonly LogKey DamageKey     = LogKey.Make("[Damage]");

// 带 ID 的动态键（每个实体独立）
public static LogKey StateKey(long id)  => LogKey.Make(id, "[-States-]");
public static LogKey PerformKey(long id) => LogKey.Make(id, "[-Perform-]");
public static LogKey ComboKey(long id)   => LogKey.Make(id, "[-Combo-]");
```

静态键用于全局状态，动态键（带 `id`）用于追踪特定战斗实体的状态，如"第 42 号单位的 Combo 状态"。

---

## LogState：帧内状态快照系统

```csharp
private static Dictionary<string, string> LogStateCache = new();
private static LogKey LastKey;

public static bool EnableStateLog = false;
public static Func<int> BattleFrameGetter;
```

`LogStateCache` 以 `LogKey.ToString()` 为键，存储当前状态字符串。这不是传统的"追加日志"，而是"状态快照"——每次 `LogState` 调用会**覆盖**或**追加**对应键的值。

```csharp
public static void LogState<T1>(LogKey key, bool append, T1 t1)
{
    if (EnableStateLog) LogState(key, t1.ToString(), append);
}

private static void LogState(LogKey key, string message, bool append)
{
    LastKey = key;
    var str = key.ToString();
    if (LogStateCache.TryGetValue(str, out var old))
    {
        LogStateCache[str] = append ? ZString.Concat(old, message) : message;
    }
    else
    {
        LogStateCache[str] = message;
    }
}
```

`append = true` 时追加，`= false` 时重写。搭配 `ClearLogState(key)` 可以在每帧开始时清除旧状态。

**LogStateAppend 便捷方法**利用 `LastKey` 字段，省去每次传 Key：

```csharp
private static LogKey LastKey;

public static void LogStateAppend<T1>(T1 t1)
{
    if (EnableStateLog) LogState(LastKey, t1.ToString(), true);
}
```

这是一种隐式上下文传递——上一次 `LogState` 设置了 `LastKey`，后续的 `LogStateAppend` 就自动追加到同一键下。典型用法：

```csharp
Log.LogState(Log.ComboKey(unitId), false, "Combo Start");
Log.LogStateAppend(comboCount, "hits");   // 追加到同一键
Log.LogStateAppend(totalDamage, "damage");
```

---

## BattleInfo：帧绑定的战斗事件输出

```csharp
private static void LogBattleInfo(BattleLogTag tag, string message)
{
    if (!EnableStateLog) return;
    LogInfo(ZString.Concat(
        LogPrefix,                              // "BattleInfo: "
        LogTagTable[tag],                       // "[Combo]"
        " ",
        BattleFrameGetter?.Invoke() ?? Game.FixedFrames,  // 当前帧号
        " ",
        message
    ));
}
```

输出格式：`BattleInfo: [Combo] 1234 连击触发，unitId=42`

帧号的来源是 `BattleFrameGetter`——一个委托，由外部注入。这使得战斗模块本身不依赖特定的帧计数实现，既可以用 `Game.FixedFrames`（全局逻辑帧），也可以用战斗专用帧计数器（支持暂停、回放偏移）。

---

## 泛型重载的设计哲学

整个系统中，`LogBattleInfo`、`LogState`、`LogStateAppend` 都有 T1~T8 的泛型重载，全部用 `ZString.Concat` 拼接而非 `string.Format`：

```csharp
public static void LogBattleInfo<T1,T2>(BattleLogTag tag, T1 t1, T2 t2)
{
    if (!EnableStateLog) return;
    LogBattleInfo(tag, ZString.Concat(t1, " ", t2));
}
```

**为什么不用 `params object[]`？**

`params object[]` 会产生数组堆分配，且值类型参数会装箱。泛型重载虽然代码膨胀，但完全避免了这两个问题——所有参数以原始类型传递，`ZString.Concat` 使用泛型重载，零 GC 分配。

---

## 实战使用示例

```csharp
// 开启战斗日志（仅调试）
Log.EnableStateLog = true;
Log.BattleFrameGetter = () => BattleSystem.CurrentFrame;

// 记录技能触发
Log.LogBattleInfo(BattleLogTag.Skill, skillId, "触发技能");

// 记录单位状态快照
var stateKey = LogKey.StateKey(unitId);
Log.LogState(stateKey, false, "HP:", hp, "MP:", mp);
Log.LogStateAppend("Buffs:", buffCount);

// 过滤查看：只看 Skill 和 Damage 相关
var filter = LogFilterType.Skill | LogFilterType.Damage;
foreach (var line in allLogLines)
{
    if (filter.FilterResult(line))
        ShowLine(line);
}

// 查询某单位当前状态
string unitState = Log.GetLogState(LogKey.StateKey(unitId));
```

---

## 设计亮点总结

| 特性 | 设计方案 | 优势 |
|------|---------|------|
| 分类 | `BattleLogTag` enum + Dictionary | 可扩展，O(1) 查找 |
| 过滤 | `[Flags]` enum 按位组合 | 灵活组合，无字符串比对 |
| 键设计 | `LogKey` struct | 零堆分配，开关为零开销 |
| 字符串拼接 | `ZString.Concat` 泛型重载 | 零 GC，无装箱 |
| 帧号绑定 | `BattleFrameGetter` 委托注入 | 解耦，支持回放偏移 |
| 全局开关 | `EnableStateLog` | Release 完全跳过 |

---

## 小结

`LogEx.cs` 展示了一个"不为日志而日志"的设计——所有结构决策都服务于一个目标：让开发者在战斗调试时能精准"开灯"，看到恰好需要看的信息，而不是被海量日志淹没，也不会为调试基础设施本身付出运行时开销。

这套系统的价值在于：当你在凌晨追一个帧同步 Desync bug，能够用 `LogFilterType.Combo | LogFilterType.Turn` 精准还原出那一帧发生了什么。
