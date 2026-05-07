---
title: xgame框架Log静态类深度解析-ZLogger集成与多级别日志输出及战斗错误追踪设计
date: 2026-05-07
tags: [Unity, xgame框架, 日志系统, ZLogger, 源码解析]
categories: [游戏开发, 框架源码]
description: 深入分析 xgame 框架 Log 静态类与 LogManager 的完整实现，涵盖 ZLogger 零分配日志集成、多级别输出策略、滚动文件日志与 Stack Trace 自动追加设计，以及与战斗日志体系的协同机制。
encryptedKey: henhaoji123
---

## 概述

在游戏框架中，**日志系统**是贯穿研发全生命周期的基础设施。`xgame` 框架的日志体系由两个核心类构成：

- `LogManager`：静态初始化工厂，负责构建 `ILoggerFactory` 并暴露全局 Logger 实例
- `Log`：静态门面类，对外提供简洁的调用接口，内部委托给 `LogManager.Logger`

两者共同实现了**零 GC 分配**、**滚动文件写入**、**多环境差异化级别**三大核心目标。

---

## 一、LogManager 静态工厂

### 1.1 核心字段

```csharp
public static class LogManager
{
    static Microsoft.Extensions.Logging.ILogger globalLogger;
    static ILoggerFactory loggerFactory;
    static string[] levelShort = {"T", "D", "I", "W", "E", "C"};
    // ...
}
```

`levelShort` 是一个长度为 6 的字符串数组，对应 `LogLevel` 枚举的 6 个级别（Trace/Debug/Information/Warning/Error/Critical），用于日志文件前缀格式化时的高效查表。

### 1.2 静态构造函数的环境分层

```csharp
static LogManager()
{
#if UNITY_EDITOR
    CreateLogger(LogLevel.Information);
#elif ONLY_CLIENT
    CreateLogger(LogLevel.Warning);
#else
    CreateLogger(LogLevel.Warning);
#endif
}
```

| 编译环境 | 最低日志级别 | 原因 |
|---------|------------|------|
| UNITY_EDITOR | Information | 编辑器下需要完整信息便于调试 |
| ONLY_CLIENT（真机） | Warning | 生产环境减少 IO 开销，仅记录警告与错误 |
| 服务器/其他 | Warning | 服务端同理，避免日志洪水 |

这种**编译期分层**策略确保线上包不产生大量无意义的 Info 级别日志，减少文件 IO 与存储压力。

### 1.3 滚动文件日志配置

```csharp
.AddZLoggerRollingFile(
    (dt, x) => $"{LogPathRoot}/game_{dt.ToLocalTime():yyyy-MM-dd_HH-mm-ss}_{x:000}.log",
    x => x.ToLocalTime().Date,
    4096, // 每个文件最大行数
    x =>
    {
        x.PrefixFormatter = (writer, info) =>
            ZString.Utf8Format(writer, "[{0}][{1}]",
                levelShort[(int)info.LogLevel],
                info.Timestamp.ToLocalTime().DateTime);
    }
);
```

**三个关键参数解析：**

1. **文件名生成委托**：`(dt, x)` — `dt` 是滚动触发时间，`x` 是文件序号（`000`→`001`...），避免同一天内多次滚动时覆盖。
2. **滚动策略**：`x => x.ToLocalTime().Date` — 按日期滚动，每天生成新文件。
3. **前缀格式化**：使用 `ZString.Utf8Format` 直接写入 UTF-8 字节流，**完全绕过 string 分配**，这是 ZLogger 零 GC 设计的核心。

### 1.4 LogPathRoot 的惰性初始化

```csharp
private static string LogPathRoot
{
    get
    {
        if (string.IsNullOrEmpty(cachedLogPathRoot))
        {
#if UNITY_EDITOR
            cachedLogPathRoot = Application.dataPath + "/../Logs";
#elif ONLY_CLIENT
            cachedLogPathRoot = Application.persistentDataPath;
#else
            cachedLogPathRoot = "./Logs";
#endif
        }
        return cachedLogPathRoot;
    }
}
```

注释中特别说明："可能在非主线程调用，需要用其他更稳的方法初始化log"。`Application.persistentDataPath` 在 Unity 中必须在主线程访问，这里采用**惰性缓存**而非构造函数赋值，是对潜在多线程竞争的防御性设计。

---

## 二、Log 静态门面类

### 2.1 基础日志方法

```csharp
public static void Info(string msg)
{
    ZLog(LogLevel.Information, default, null, msg);
}

public static void Error(string msg)
{
    ZLog(LogLevel.Error, default, null, msg);
    LogBattleInfo(BattleLogTag.Error, msg);  // 联动战斗日志
}
```

`Error` 方法有一个**独特设计**：调用了 `LogBattleInfo(BattleLogTag.Error, msg)`。这意味着游戏逻辑错误不仅写入文件日志，还会**同步到战斗日志系统**，使战报中可以追踪到异常来源。这种双写机制让战斗复盘时能直接看到关联的错误上下文。

### 2.2 Warning 以上级别自动追加 Stack Trace

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

关键逻辑：`(int)logLevel >= (int)LogLevel.Warning` — 当级别 >= Warning 时，**自动追加调用堆栈**。

`new StackTrace(2, true)` 中：
- `2`：跳过前2帧（即 `ZLog` 和 `Warning`/`Error` 自身），让 Stack Trace 从真正的业务调用处开始
- `true`：包含文件名和行号信息

这一机制极大降低了 Warning/Error 定位成本，不需要手动添加堆栈打印。

### 2.3 泛型 ZLog 的零 GC 设计

框架提供了最多 5 个泛型参数的重载：

```csharp
public static void LogInfo<T1>(string format, T1 arg1)
{
    ZLog<T1>(LogLevel.Information, default, null, format, arg1);
}

private static void ZLog<T1>(LogLevel logLevel, EventId eventId, Exception exception, string format, T1 arg1)
{
    logger.Log(logLevel, eventId,
        new FormatLogState<object, T1>(null, format, arg1),
        exception,
        (state, ex) => ZString.Format(state.Format, state.Arg1));
}
```

`FormatLogState<TPayload, T1>` 是一个**值类型状态容器**，将格式化延迟到最终写入时才执行。这样：
1. 如果当前日志级别低于阈值，`logger.Log` 内部直接短路，**不会触发格式化**，不产生任何字符串
2. 真正写入时使用 `ZString.Format`，内部用 `Span<char>` 操作，无堆分配

这是 ZLogger 区别于 `string.Format` 和 `$"interpolation"` 的核心价值。

---

## 三、ListComponent 与集合日志

```csharp
[System.Diagnostics.Conditional("UNITY_EDITOR")]
public static void LogList<T>(string title, IEnumerable<T> list, Func<T, string> formatter = null)
{
    var sb = ZString.CreateStringBuilder();
    sb.AppendLine($"===== {title} =====");
    int index = 0;
    foreach (var item in list)
    {
        string itemStr = formatter != null ? formatter(item) : item.ToString();
        sb.AppendLine($"[{index++}] {itemStr}");
    }
    sb.AppendLine($"===== 共 {index} 项 =====");
    Log.Info(sb.ToString());
}
```

`[Conditional("UNITY_EDITOR")]` 特性确保此方法**仅在编辑器下编译**，真机包中调用处的代码会被编译器完全消除，零运行时开销。`ZString.CreateStringBuilder()` 在栈上创建字符串构建器，避免 `StringBuilder` 的堆分配。

---

## 四、ChangeLogLevel 运行时动态调整

```csharp
public static void ChangeLogLevel(LogLevel level)
{
    var logger = globalLogger;
    var loggersArray = (Array)logger
        .GetType()
        .GetProperty("MessageLoggers", BindingFlags.Public | BindingFlags.Instance)
        ?.GetValue(logger);
    
    if (loggersArray != null)
    {
        for (int i = 0; i < loggersArray.Length; i++)
        {
            var info = loggersArray.GetValue(i);
            var piMinLevel = info?.GetType().GetProperty("MinLevel");
            var fiMinLevel = piMinLevel.GetBackingField();
            fiMinLevel.SetValue(info, level);
            loggersArray.SetValue(info, i);
        }
    }
}
```

这段代码通过**反射直接修改 Logger 内部的 MinLevel 字段**，实现运行时动态调整日志级别——这在调试特定场景时非常有用（例如线上版本临时开启 Debug 级别）。

`GetBackingField` 是自定义扩展方法，通过 `<PropertyName>k__BackingField` 命名规律获取自动属性的底层字段：

```csharp
private static FieldInfo GetBackingField(this PropertyInfo property)
{
    string backingFieldName = $"<{property.Name}>k__BackingField";
    return property.DeclaringType?.GetField(backingFieldName, BindingFlags.NonPublic | BindingFlags.Instance);
}
```

---

## 五、整体架构关系图

```
LogManager (工厂)
    ├── ILoggerFactory (ZLogger)
    │       ├── ZLoggerUnityDebug (编辑器 Console)
    │       └── ZLoggerRollingFile (滚动文件)
    └── globalLogger ──► Log (静态门面)
                            ├── Info / Debug / Warning
                            ├── Error ──► LogBattleInfo (战斗日志联动)
                            ├── LogInfo<T1..T5> (泛型零GC接口)
                            └── LogList (编辑器调试工具)
```

---

## 六、设计总结

| 设计点 | 实现方式 | 收益 |
|--------|---------|------|
| 零 GC 日志格式化 | `FormatLogState` + `ZString` | 消除 string 分配，高频调用友好 |
| 环境分层日志级别 | 编译期 `#if` | 线上包自动过滤无效日志 |
| Warning+ 自动 Stack Trace | `StackTrace(2, true)` 拼接 | 无需手动打堆栈，快速定位 |
| 滚动文件日志 | `AddZLoggerRollingFile` | 按日期自动分割，防止日志文件膨胀 |
| 运行时调整级别 | 反射修改 backing field | 线上调试神器，无需重启 |
| 战斗错误联动 | `Error` 内调用 `LogBattleInfo` | 错误与战斗上下文绑定，复盘更准确 |

`xgame` 框架的日志系统充分利用了 ZLogger 的零分配特性，结合游戏特有的战斗日志联动机制，构建了一套既高性能又实用的生产级日志基础设施。
