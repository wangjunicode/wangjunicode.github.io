---
title: ET框架ZLog日志系统深度解析-分层日志架构与战斗信息过滤机制设计
published: 2026-04-23
description: 深入解析ET框架中基于ZLogger的高性能日志系统，涵盖Log/LogEx双分部类设计、ZString零分配格式化、BattleLogTag战斗日志分类、LogFilterType位掩码过滤、LogState状态追踪以及AggressiveInlining性能优化等核心技术。
image: ''
tags: [Unity, ET框架, 日志系统, ZLogger, 游戏架构]
category: Unity游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

日志系统在游戏开发中往往被低估——直到你需要复现一个只在联网对战时出现的战斗 bug。ET框架围绕 ZLogger 构建了一套分层日志系统，通过 `Log.cs`（基础日志）和 `LogEx.cs`（战斗扩展）两个分部类（`partial class`），在零分配格式化、多级别过滤、状态追踪等方向做了深度优化。本文从源码出发全面解析这套系统的设计思路。

---

## 一、整体架构：双分部类设计

```
ET.Log (static partial class)
├── Log.cs          → 基础日志：Info/Debug/Warning/Error + ZLog泛型重载
└── LogEx.cs        → 战斗扩展：BattleLogTag分类、LogFilterType过滤、LogState状态追踪
```

使用 `partial class` 的好处是将**通用日志能力**和**战斗专用日志能力**物理隔离，编译时合并为同一个类型，调用方无需区分，维护时各自独立。

底层 logger 实例来自 ZLogger（通过 `VGame.Framework.LogManager`）：

```csharp
static Microsoft.Extensions.Logging.ILogger logger = LogManager.Logger;
```

---

## 二、基础日志层（Log.cs）

### 2.1 核心方法与内联优化

```csharp
[DebuggerStepThrough]
[MethodImpl(MethodImplOptions.AggressiveInlining)]
public static void Info(string msg)
{
    ZLog(LogLevel.Information, default, null, msg);
}

[DebuggerStepThrough]
[MethodImpl(MethodImplOptions.AggressiveInlining)]
public static void Warning(string msg)
{
    ZLog(LogLevel.Warning, default, null, msg);
}

[DebuggerStepThrough]
[MethodImpl(MethodImplOptions.AggressiveInlining)]
public static void Error(string msg)
{
    ZLog(LogLevel.Error, default, null, msg);
    LogBattleInfo(BattleLogTag.Error, msg); // 错误同步写入战斗日志
}
```

三个装饰器各有作用：
- `[DebuggerStepThrough]`：调试时跳过此方法，F11 不会进入日志代码。
- `[MethodImpl(MethodImplOptions.AggressiveInlining)]`：提示 JIT 内联，消除函数调用开销，在高频日志场景下显著降低性能损耗。

### 2.2 ZLog 内部实现：堆栈追踪自动附加

```csharp
private static void ZLog(LogLevel logLevel, EventId eventId, Exception exception, string message)
{
    logger.Log(logLevel, eventId, new MessageLogState<object>(null,
            (int)logLevel >= (int)LogLevel.Warning 
                ? ZString.Concat(message, '\n', new StackTrace(2, true).ToString()) 
                : message),
        exception,
        (state, ex) => state.Message);
}
```

关键细节：**Warning 及以上级别自动追加调用堆栈**。`new StackTrace(2, true)` 中 `2` 表示跳过前两层框架方法，直接显示业务调用点。`ZString.Concat` 是零分配字符串拼接（来自 Cysharp/ZString 库），避免堆分配。

### 2.3 泛型 ZLog 重载：零分配格式化

框架生成了大量泛型重载（T1 到 T5），延迟格式化到实际输出时：

```csharp
private static void ZLog<T1>(LogLevel logLevel, EventId eventId, Exception exception, string format, T1 arg1)
{
    logger.Log(logLevel, eventId, 
        new FormatLogState<object, T1>(null, 
            (int)logLevel >= (int)LogLevel.Warning 
                ? ZString.Concat(format, '\n', new StackTrace(2, true).ToString()) 
                : format, arg1),
        exception,
        (state, ex) => ZString.Format(state.Format, state.Arg1));
}
```

`FormatLogState<TPayload, T1>` 是一个结构体，将参数保存在栈上，只有在 logger 真正输出时才调用 `ZString.Format` 格式化。若 logger 的日志级别过滤掉了这条日志，格式化完全不发生，**实现了真正的零分配懒格式化**。

### 2.4 调试辅助：LogList

```csharp
[System.Diagnostics.Conditional("UNITY_EDITOR")]
public static void LogList<T>(string title, IEnumerable<T> list, System.Func<T, string> formatter = null)
{
    // 仅在 Editor 下编译，使用 ZString 构建格式化列表输出
}
```

`[Conditional("UNITY_EDITOR")]` 特性使得这个方法在非 Editor 构建中**完全不生成调用代码**，零运行时开销。

---

## 三、战斗日志扩展层（LogEx.cs）

### 3.1 BattleLogTag 分类体系

`LogEx.cs` 定义了完整的战斗日志分类枚举：

```csharp
public enum BattleLogTag
{
    Default, Combo, Perform, Input, ComboDetail, SelectPerform,
    RegisterPerform, UnRegisterPerform, TryUsePerform,
    BattlePointTryPerform, PerformDetail,
    AddToken, UseToken, ClearToken,
    BattlePointStart, BattlePointEnd,
    DirectorSkill, Turn, ChangeDef, Skill, Node, Damage, Debug, Error,
}
```

每个标签对应一个字符串常量和 LogTagTable 映射：

```csharp
public const string Combo = "[Combo]";
public const string Perform = "[Perform]";
// ...

public static readonly Dictionary<BattleLogTag, string> LogTagTable = new()
{
    {BattleLogTag.Combo, Combo},
    {BattleLogTag.Perform, Perform},
    // ...
};
```

### 3.2 LogFilterType 位掩码过滤

```csharp
[Flags]
public enum LogFilterType
{
    Default = 0,
    Turn    = 1 << 0,
    Input   = 1 << 1,
    ChangeDef = 1 << 2,
    Token   = 1 << 3,
    BattlePoint = 1 << 4,
    Perform = 1 << 5,
    Combo   = 1 << 6,
    Skill   = 1 << 7,
    Node    = 1 << 8,
    Damage  = 1 << 9,
    Debug   = 1 << 10,
}
```

`[Flags]` 特性 + 位移枚举，允许组合过滤：

```csharp
// 同时过滤 Turn + Perform + Combo
var filter = LogFilterType.Turn | LogFilterType.Perform | LogFilterType.Combo;
```

过滤扩展方法：

```csharp
public static bool FilterResult(this LogFilterType type, string str)
{
    return Log.LogFilter
        .Where(x => ((int)x.Key & (int)type) == (int)x.Key) // 找到所有命中的过滤条目
        .Any(filter => filter.Value.Any(str.StartsWith));     // 日志是否以对应前缀开头
}
```

这里 `((int)x.Key & (int)type) == (int)x.Key` 是标准的位掩码子集检测，判断 x.Key 中所有置位位是否都在 type 中存在。

### 3.3 战斗日志写入

```csharp
private static void LogBattleInfo(BattleLogTag tag, string message)
{
    if (!EnableStateLog) return;
    LogInfo(ZString.Concat(
        LogPrefix,              // "BattleInfo: "
        LogTagTable[tag],       // "[Combo]" 等
        " ",
        BattleFrameGetter?.Invoke() ?? Game.FixedFrames, // 当前逻辑帧号
        " ",
        message
    ));
}
```

格式：`BattleInfo: [Combo] 1234 xxx发动了连击`

带有帧号的日志对于**战斗复盘**极其关键——调试时可以精确定位到哪一帧发生了异常行为。

### 3.4 LogState 状态追踪系统

这是 LogEx 中最独特的设计，用于追踪某个逻辑对象的当前状态快照：

```csharp
private static Dictionary<string, string> LogStateCache = new();
private static LogKey LastKey;

public static void LogState<T1>(LogKey key, bool append, T1 t1)
{
    if (EnableStateLog) LogState(key, t1.ToString(), append);
}

private static void LogState(LogKey key, string message, bool append)
{
    LastKey = key;
    var str = key.ToString();
    if (string.IsNullOrEmpty(str)) return;
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

`LogKey` 是一个值类型结构体：

```csharp
public partial struct LogKey
{
    private string name;

    public static LogKey Make(string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = name };
        return default; // 未启用时返回空结构体，零开销
    }

    public static LogKey Make(long id, string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = ZString.Concat(id, " ", name) };
        return default;
    }
}
```

典型使用场景——记录角色状态变化：

```csharp
var key = LogKey.Make(entityId, "[-States-]");
Log.LogState(key, false, "状态机进入: Idle");
// 追加更多状态
Log.LogState(key, true, " -> Attack");
// 最后读取完整状态链
string stateHistory = Log.GetLogState(key);
```

`LogStateAppend` 系列方法使用 `LastKey` 省去每次传 key：

```csharp
public static void LogStateAppend<T1>(T1 t1)
{
    if (EnableStateLog) LogState(LastKey, t1.ToString(), true);
}
```

---

## 四、EnableStateLog 开关设计

```csharp
#if UNITY_EDITOR
public static bool EnableStateLog = false;
#else
public static bool EnableStateLog = false;
#endif
```

目前两种环境下默认都是 `false`，但通过 `#if` 分开定义，方便针对 Editor 版本单独启用，不影响 Release 包性能。所有 LogState / LogBattleInfo 方法首行都检查此开关：

```csharp
public static void LogBattleInfo<T1>(BattleLogTag tag, T1 t1)
{
    if (!EnableStateLog) return; // 未启用直接返回，无任何分配
    // ...
}
```

---

## 五、ILog 接口与依赖倒置

```csharp
public interface ILog
{
    void Trace(string message);
    void Warning(string message);
    void Info(string message);
    void Debug(string message);
    void Error(string message);
}
```

`ILog` 接口是日志系统的抽象层，允许替换底层实现（Unity Console、文件日志、远程日志等），而不影响调用方。当前框架选择了 ZLogger 作为实现，但通过接口保留了替换空间。

---

## 六、设计亮点总结

| 设计点 | 技术手段 | 收益 |
|--------|----------|------|
| 零分配格式化 | ZString.Concat / FormatLogState | 高频日志无 GC 压力 |
| 懒格式化 | logger.Log 泛型 state 延迟 | 被过滤的日志零开销 |
| Warning+ 自动堆栈 | new StackTrace(2, true) | 无需手动埋点即可定位 |
| 方法内联 | AggressiveInlining | 消除日志调用开销 |
| 位掩码过滤 | [Flags] 枚举 | 灵活组合多类别过滤 |
| 帧号记录 | BattleFrameGetter | 精准复盘战斗问题 |
| conditional 调试方法 | [Conditional("UNITY_EDITOR")] | Editor 辅助工具零 Release 开销 |
| LogKey 值类型 | struct + Make 工厂 | 未启用时返回 default，栈分配 |

---

## 七、小结

ET框架的日志系统在看似简单的 `Log.Info` 背后，隐藏了大量工程细节：零分配懒格式化保证高帧率下的低 GC，自动堆栈附加减少手动调试成本，战斗专用的 Tag + Filter + LogState 三件套为联机战斗调试提供了完整工具链。理解这套日志系统的设计，不仅能更好地用好它，也能为自己设计高质量日志系统提供参考。
