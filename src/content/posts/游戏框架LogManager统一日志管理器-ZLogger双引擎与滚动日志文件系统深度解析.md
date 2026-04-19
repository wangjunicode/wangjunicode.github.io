---
title: 游戏框架LogManager统一日志管理器-ZLogger双引擎与滚动日志文件系统深度解析
published: 2026-04-19
description: 深度解析游戏框架中LogManager静态日志管理类的完整实现，涵盖ZLogger + Microsoft.Extensions.Logging双引擎架构、UnityLoggerFactory跨平台适配、滚动日志文件策略、动态日志级别运行时修改，以及Exceptionless远端错误上报的工程设计。
tags: [Unity, 日志系统, ZLogger, LogManager, 游戏框架, 工程实践]
category: 游戏开发
draft: false
encryptedKey: henhaoji123
---

## 前言

在大型游戏项目中，日志系统往往是最容易被忽视却最关键的基础设施之一。一个好的日志框架需要满足以下要求：

- **跨平台**：同时支持 Unity Editor、移动端 IL2CPP、纯服务端 .NET
- **高性能**：游戏主循环每帧调用，不能产生大量 GC
- **可配置**：运行时动态调整日志级别，不重启进程
- **持久化**：滚动文件日志，便于线上问题排查

本文将深入分析游戏框架 `LogManager` 的完整实现，揭示其背后的双引擎设计思路。

---

## 架构总览

```
LogManager (静态类)
├── 编译器分支
│   ├── ONLY_CLIENT  → UnityLoggerFactory（移动端 IL2CPP 兼容）
│   └── 非 CLIENT   → LoggerFactory（标准 .NET / 服务端）
├── ZLogger 滚动文件 Provider
│   └── 按日期 + 序号分片（最大 4096 KB）
├── 日志前缀格式化
│   └── [级别][时间戳]
└── 动态级别修改（运行时反射）
```

---

## 核心数据结构

```csharp
public static class LogManager
{
    static ILogger globalLogger;           // 全局 Logger 实例
    private static string logFileName;    
    private static string cachedLogPathRoot; // 日志根目录缓存
    static ILoggerFactory loggerFactory;   // 标准 LoggerFactory
    static ILoggerFactory rndLoggerFactory;
    
    // 日志级别短标识：T D I W E C
    static string[] levelShort = {"T", "D", "I", "W", "E", "C"};
}
```

`levelShort` 数组与 `Microsoft.Extensions.Logging.LogLevel` 枚举一一对应（Trace=0 到 Critical=5），用于日志文件的前缀格式化。

---

## 跨平台路径策略

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

| 环境 | 日志路径 | 说明 |
|------|---------|------|
| Unity Editor | `项目根/Logs/` | 便于开发者直接查看 |
| 移动端（IL2CPP） | `Application.persistentDataPath` | iOS/Android 沙箱内可读写路径 |
| 服务端 / 测试 | `./Logs/` | 相对于可执行文件的工作目录 |

值得注意的是，这里用了**惰性初始化 + 缓存**。原因是 `Application.persistentDataPath` 只能在主线程获取，而 LogManager 的静态构造函数可能在非主线程首次触发，因此延迟到第一次实际使用时才初始化路径。

---

## 双引擎 Logger 创建

### ONLY_CLIENT：UnityLoggerFactory

```csharp
loggerFactory = UnityLoggerFactory.Create(builder =>
{
    builder
        .SetMinimumLevel(level)
        .AddZLoggerUnityDebug()        // → UnityEngine.Debug.Log
        .AddZLoggerRollingFile(        // → 滚动文件
            (dt, x) => $"{LogPathRoot}/game_{dt.ToLocalTime():yyyy-MM-dd_HH-mm-ss}_{x:000}.log",
            x => x.ToLocalTime().Date, // 按日期滚动
            4096,                       // 单文件最大 4096 KB
            x =>
            {
                x.PrefixFormatter = (writer, info) =>
                    ZString.Utf8Format(writer, "[{0}][{1}]",
                        levelShort[(int) info.LogLevel],
                        info.Timestamp.ToLocalTime().DateTime
                    );
            }
        );
});
```

`UnityLoggerFactory` 是 ZLogger 专为 Unity 提供的 LoggerFactory 实现，解决了标准 `LoggerFactory` 在 IL2CPP 下因反射限制无法正常工作的问题。

**两路输出同时工作：**
- `AddZLoggerUnityDebug()`：发送到 Unity Console，在 Editor 和开发机上实时可见
- `AddZLoggerRollingFile()`：写入文件，用于线上崩溃日志收集

### 非 CLIENT：标准 LoggerFactory

```csharp
loggerFactory = LoggerFactory.Create(builder =>
{
    builder
        .SetMinimumLevel(level)
        .AddZLoggerRollingFile(...);   // 只有文件输出
});
```

服务端环境去掉了 `AddZLoggerUnityDebug()`，仅保留文件输出，减少依赖。

---

## 滚动文件命名策略

```csharp
(dt, x) => $"{LogPathRoot}/game_{dt.ToLocalTime():yyyy-MM-dd_HH-mm-ss}_{x:000}.log"
```

文件名由三部分组成：
- `game_`：固定前缀
- `yyyy-MM-dd_HH-mm-ss`：日志文件创建时间（本地时区）
- `{x:000}`：同一时间段内的文件序号（000, 001, 002...）

```csharp
x => x.ToLocalTime().Date  // 滚动条件：日期变化时新建文件
```

当日期发生变化（跨天）时，ZLogger 会自动创建新的日志文件，旧文件关闭。单文件大小上限为 4096 KB，超出后也会自动递增序号新建文件。

---

## 日志前缀格式化

```csharp
x.PrefixFormatter = (writer, info) =>
    ZString.Utf8Format(writer, "[{0}][{1}]",
        levelShort[(int) info.LogLevel],
        info.Timestamp.ToLocalTime().DateTime
    );
```

**为什么用 ZString.Utf8Format？**

`ZString` 是 ZLogger 配套的零分配字符串格式化库，直接将格式化结果写入 `IBufferWriter<byte>`，完全避免了 `string.Format` 产生的临时字符串 GC。

实际日志输出格式：
```
[I][2026-04-19 10:00:00]应用启动完成
[W][2026-04-19 10:00:05]网络连接超时，重试次数: 3
[E][2026-04-19 10:00:10]加载资源失败: hero_001.prefab
```

---

## 动态日志级别修改

这是整个 LogManager 中最具技巧性的部分：

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
            if (piMinLevel == null) return;
            
            var fiMinLevel = piMinLevel.GetBackingField();
            fiMinLevel.SetValue(info, level);
            loggersArray.SetValue(info, i);
        }
    }
}

private static FieldInfo GetBackingField(this PropertyInfo property)
{
    string backingFieldName = $"<{property.Name}>k__BackingField";
    return property.DeclaringType?.GetField(
        backingFieldName,
        BindingFlags.NonPublic | BindingFlags.Instance
    );
}
```

**实现原理：**

`Microsoft.Extensions.Logging` 的 `Logger` 内部维护着一个 `MessageLoggers` 数组，每个元素对应一个已注册的 `ILoggerProvider`，其中包含 `MinLevel` 属性。

由于 `MinLevel` 是自动属性（`{ get; private set; }`），无法直接通过属性设置器修改。框架通过以下步骤绕过这个限制：

1. 反射获取 `MessageLoggers` 数组
2. 对每个 `ILogger` 信息，找到 `MinLevel` 属性
3. 通过命名约定 `<PropertyName>k__BackingField` 找到自动属性的 backing field
4. 直接用 `FieldInfo.SetValue` 修改 backing field 的值

这个技巧允许游戏在运行时通过 GM 指令或调试面板动态调整日志详细程度，而无需重启。

> **注意**：这种反射操作依赖于 C# 编译器的内部命名约定，在不同 .NET 版本下需要确认 backing field 命名规则一致。IL2CPP 下需要额外配置 `link.xml` 保留相关类型。

---

## 初始化级别策略

```csharp
static LogManager()
{
#if UNITY_EDITOR
    CreateLogger(LogLevel.Information);   // 编辑器：显示 Info 及以上
#elif ONLY_CLIENT
    CreateLogger(LogLevel.Warning);       // 移动端发布：只显示 Warning 及以上
#else
    CreateLogger(LogLevel.Warning);       // 服务端：同移动端
#endif
}
```

这种分级初始化策略确保：
- **开发阶段**（Editor）：可以看到 Info 级别的调试信息
- **发布包**（移动端 / 服务端）：只记录 Warning 及以上，减少日志量和 IO 压力

---

## Exceptionless 远端上报（预留）

```csharp
public static string CreateExceptionLessError(string message, StackTrace st)
{
    var simpleError = new Dictionary<string, string>()
    {
        {"message", message},
        {"type", "System.Exception"},
        {"stack_trace", ""}
    };
    // ...
    return "";
}
```

代码中预留了 [Exceptionless](https://exceptionless.com/) 的上报接口（目前处于注释状态）。这是一个开源的错误日志聚合服务，支持私有化部署，适合游戏线上崩溃上报场景。

激活方式（注释中可见）：
```csharp
// .AddZLoggerExceptionless("your-api-key", "http://your-server:5000")
```

---

## 与 Logger / Log 的关系

```csharp
// Logger 单例（Log.cs）
public static class Log
{
    public static ILog ILog;
    public static void Debug(string msg) => ILog?.Debug(msg);
    // ...
}

// LogManager 提供底层 ILogger
public static ILogger Logger => globalLogger;
```

整个日志体系分为两层：
- **LogManager**：底层，管理 `ILoggerFactory` 和 `ILogger`，负责写文件
- **Log / Logger**：上层，提供游戏代码调用的简洁接口

游戏业务代码统一调用 `Log.Debug()`，`Log.Error()` 等，与底层实现解耦。

---

## 总结

| 特性 | 实现方式 |
|------|---------|
| 跨平台兼容 | `#if ONLY_CLIENT` 分支选用不同 LoggerFactory |
| 零 GC 写日志 | ZLogger + ZString.Utf8Format |
| 滚动日志文件 | AddZLoggerRollingFile 按日期 + 大小分片 |
| 动态级别修改 | 反射修改 backing field |
| Unity Console 同步 | AddZLoggerUnityDebug 双路输出 |
| 线上错误上报 | 预留 Exceptionless 集成接口 |

`LogManager` 展示了如何在游戏项目中构建一个真正工程化的日志基础设施——它不仅仅是 `Debug.Log` 的封装，而是一个覆盖从开发调试到线上运维全链路的日志解决方案。
