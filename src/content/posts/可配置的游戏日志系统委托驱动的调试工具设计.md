---
title: 可配置的游戏日志系统：委托驱动的调试工具设计
published: 2026-03-31
description: 深入解析委托驱动的日志系统设计，理解日志级别控制、条件编译宏和性能分析工具的工程最佳实践。
tags: [Unity, 调试工具, 日志系统, 工程实践]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

## 为什么不直接用 Debug.Log？

新手写代码通常直接用 `Debug.Log`，这有什么问题吗？

在小项目里没问题，但在团队协作的大型项目中，`Debug.Log` 有几个明显缺陷：

1. **无法分级**：没有区分"普通信息"、"警告"、"错误"的机制（`Debug.LogWarning/Error` 存在但接入不灵活）
2. **无法统一过滤**：想关掉某个模块的日志，只能手动注释代码
3. **无法重定向**：日志只能输出到 Unity Console，无法同时写文件或发送到服务器
4. **Release 版仍然执行**：`Debug.Log` 在 Release 包中仍然有一定开销（字符串构建本身）
5. **帧同步追踪困难**：多人帧同步游戏中，需要知道日志发生在哪一帧

`KHDebug` 正是针对这些问题设计的。

---

## 委托驱动的日志系统

`KHDebug` 的核心思想是：**日志系统只定义接口，具体实现通过委托注入**。

```csharp
public class KHDebug
{
    public delegate void PrintMessage(string message);
    
    // 四个委托槽位
    static public PrintMessage __logfunc = null;      // 普通日志
    static public PrintMessage __errorfunc = null;    // 错误日志
    static public PrintMessage __warningfunc = null;  // 警告日志
    static public PrintMessage __storyFlowLog = null; // 剧情流程日志

    public static bool EnableLog = true;
    public static int logLevel = (int)LogLevel.Warning;  // 默认只显示警告以上
}
```

委托为 null 时，日志调用会被静默忽略——这是一个**安全的默认值**（宁可静默不能崩溃）。

---

## 日志级别系统

```csharp
public enum LogLevel
{
    Error = 0,
    Assert = 1,
    Warning = 2,
    Log = 3,
    Exception = 4
}
```

每个日志方法都会检查当前 `logLevel`：

```csharp
public static void Log(string message)
{
    if (EnableLog && logLevel >= (int)LogLevel.Log && __logfunc != null)
        __logfunc(message);
}

public static void LogWarning(string message)
{
    if (EnableLog && logLevel >= (int)LogLevel.Warning && __warningfunc != null)
        __warningfunc(message);
}

public static void LogError(string message)
{
    if (EnableLog && logLevel >= (int)LogLevel.Error && __errorfunc != null)
        __errorfunc(message);
}
```

默认 `logLevel = LogLevel.Warning`，意味着 `Log`（普通信息）不会输出，只有 `Warning` 和 `Error` 才会显示。

**在 Release 包中**，可以通过设置 `EnableLog = false` 完全关闭所有日志，或者设置 `logLevel = LogLevel.Error` 只保留错误日志。

---

## 初始化：连接真实的日志实现

在游戏启动时，需要把委托连接到实际的日志实现（通常是 `UnityEngine.Debug`）：

```csharp
// 游戏初始化代码
public class GameBootstrap : MonoBehaviour
{
    private void Awake()
    {
        // 连接到 Unity Debug 系统
        KHDebug.__logfunc = UnityEngine.Debug.Log;
        KHDebug.__errorfunc = UnityEngine.Debug.LogError;
        KHDebug.__warningfunc = UnityEngine.Debug.LogWarning;
        
#if !UNITY_EDITOR
        // 非编辑器：同时写入文件
        var fileWriter = new LogFileWriter("game.log");
        var unityLog = KHDebug.__logfunc;
        KHDebug.__logfunc = msg => {
            unityLog(msg);
            fileWriter.Write(msg);
        };
#endif
    }
}
```

这种设计允许：
- 开发时：只输出到 Unity Console（快速）
- 测试时：同时写文件（便于复现问题）
- 线上：关闭普通日志，错误日志发到服务器

---

## ZString 集成：格式化日志的零 GC 实现

```csharp
public static void LogFormat(string format, params object[] args)
{
    if (EnableLog && logLevel >= (int)LogLevel.Log && __logfunc != null)
    {
        __logfunc(ZString.Format(format, args));
    }
}
```

注意：`params object[] args` 本身会有装箱（值类型参数装箱为 object）和数组分配。

更彻底的零 GC 做法是提供多个重载：

```csharp
// 理想的零 GC 版本（需要手动重载多个参数数量）
public static void LogFormat<T1>(string format, T1 arg1)
{
    if (EnableLog && logLevel >= (int)LogLevel.Log && __logfunc != null)
    {
        __logfunc(ZString.Format(format, arg1));  // ZString 的泛型重载无装箱
    }
}

public static void LogFormat<T1, T2>(string format, T1 arg1, T2 arg2) { ... }
```

当前实现在 `params object[]` 上还有优化空间，但对于日志系统来说，性能通常不是首要关注点，保持简洁更重要。

---

## 帧追踪：帧同步调试利器

```csharp
private static int m_frameIndex = 0;

public static void EnterFrame(int frameIndex)
{
    m_frameIndex = frameIndex;
}

[Conditional("ENABLE_LOG_FRAME")]
public static void LogFrame(string message)
{
    Log(ZString.Concat("#", m_frameIndex, ":", message));
}

public static void LogFrameError(string message)
{
    LogError(ZString.Concat("#", m_frameIndex, ":", message));
}
```

`EnterFrame` 在每帧开始时被调用，记录当前帧号。之后的 `LogFrame` 调用会在消息前自动附加帧号：

```
输出示例：
#1234: 英雄攻击了敌人
#1234: 敌人受到 100 点伤害
#1235: 敌人死亡
```

在帧同步游戏中，这对于复现 desync（不同步）问题至关重要——两台机器的日志应该逐帧完全一致，任何差异都意味着逻辑 bug。

**`[Conditional("ENABLE_LOG_FRAME")]`**：这是关键优化。当未定义宏 `ENABLE_LOG_FRAME` 时，**连调用这个函数的代码也会被编译器删除**，即使传入的字符串参数也不会被求值。这意味着发布包中帧日志的开销是真正的零，而不只是"函数体为空"。

---

## 条件编译宏：性能追踪工具

```csharp
[Conditional("ENABLE_PROFILER")]
public static void BeginSample(string token)
{
#if ONLY_CLIENT && (!KH_VALID_PROCESSOR || UNITY_EDITOR)
    UnityEngine.Profiling.Profiler.BeginSample(token);
#endif
}

[Conditional("ENABLE_PROFILER")]
public static void EndSample()
{
#if ONLY_CLIENT && !KH_VALID_PROCESSOR || UNITY_EDITOR
    UnityEngine.Profiling.Profiler.EndSample();
#endif
}
```

`Profiler.BeginSample/EndSample` 是 Unity 内置性能分析工具的标记接口，用于在 Profiler 窗口中显示自定义采样区域。

通过 `[Conditional("ENABLE_PROFILER")]` 包装，只有在定义了 `ENABLE_PROFILER` 宏时才会编译这些调用，Release 版本中完全没有性能开销。

---

## 日志追踪系统（LogTrack）

```csharp
[Conditional("Macro45402939")]
public static void BeginTrack() { }
[Conditional("Macro45402939")]
public static void EnterTrackFrame(int frameIndex) { }
[Conditional("Macro45402939")]
public static void EndTrack() { }
[Conditional("Macro45402939")]
public static void IgnoreTrack() { }
[Conditional("Macro45402939")]
public static void LogTrack(int hash) { }
[Conditional("Macro45402939")]
public static void LogTrack(int hash, int arg1) { }
// ... 多个重载
```

这组方法使用一个极不寻常的宏名称 `Macro45402939`——这显然是一个随机生成的宏，正常编译环境下永远不会定义，所以这些方法对性能没有任何影响。

它们是**帧同步追踪系统**的接口，只有在特定的调试工具链中才会启用，用于记录每帧的行为哈希值，对比不同客户端的执行路径以定位 desync。

---

## 剧情流程日志

```csharp
static public PrintMessage __storyFlowLog = null;
public static bool EnableStoryFlowLog = false;

public static void StoryFlowLog(string message)
{
    if (EnableStoryFlowLog && __storyFlowLog != null)
        __storyFlowLog(message);
}
```

这是针对剧情系统的专用日志，默认关闭（`EnableStoryFlowLog = false`）。剧情 QA 测试时可以独立开启这个日志，不影响其他日志的输出，便于追踪剧情流程是否正确推进。

---

## 实践建议：如何在项目中使用这套系统

```csharp
// 在项目中定义自己的 Log 门面类（减少直接依赖 KHDebug）
public static class Log
{
    public static void Info(string msg) => KHDebug.Log(msg);
    public static void InfoFormat(string format, params object[] args) 
        => KHDebug.LogFormat(format, args);
    public static void Warning(string msg) => KHDebug.LogWarning(msg);
    public static void Error(string msg) => KHDebug.LogError(msg);
    public static void Error(Exception e) => KHDebug.LogError(e.ToString());
}

// 业务代码中使用
Log.Info("角色加载完成");
Log.Warning("资源缺失，使用默认值");
Log.Error($"配置错误：{configPath}");
```

这样做的好处：如果将来需要替换底层日志实现，只需修改 `Log` 这个门面类，不需要改动所有业务代码。

---

## 总结

`KHDebug` 展示了一个工程师思维的日志系统设计：

| 需求 | 解决方案 |
|------|---------|
| 可重定向 | 委托（delegate）而不是直接调用 |
| 可分级 | LogLevel 枚举 + 过滤逻辑 |
| 零开销发布 | [Conditional] 宏 |
| 帧追踪 | EnterFrame + LogFrame |
| 性能分析 | BeginSample/EndSample 包装 |
| 模块专用 | StoryFlowLog 等专用委托 |

对于新手，这里最重要的工程经验是：**不要直接依赖具体实现，总是通过接口（委托/接口/抽象类）隔离变化点**。这让代码在未来更容易修改和测试。
