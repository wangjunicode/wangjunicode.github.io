---
title: 游戏框架ZLogger与UnityLogger日志系统双引擎设计深度解析
published: 2026-04-14
description: 从LogManager.cs与UnityLogger.cs源码出发，深度剖析游戏框架中基于ZLogger的跨平台高性能日志系统架构，覆盖多平台条件编译、滚动文件日志、日志级别动态切换与UnityEngine.Debug桥接的完整设计方案。
tags: [Unity, 日志系统, ZLogger, LogManager, 性能优化, 跨平台]
category: 游戏框架源码解析
draft: false
encryptedKey: henhaoji123
---

## 前言

日志系统是游戏框架的"黑匣子"，直接决定了线上问题排查的效率。本篇从 `LogManager.cs` 与 `UnityLogger.cs` 两个源文件出发，深入分析该框架如何通过 **ZLogger + Microsoft.Extensions.Logging** 构建了一套跨平台、高性能、可动态调节级别的日志体系。

---

## 一、架构概览

```
┌──────────────────────────────────────────┐
│            业务调用层                      │
│   LogManager.Logger.ZLogInformation(...)  │
└──────────────────┬───────────────────────┘
                   │
┌──────────────────▼───────────────────────┐
│         LogManager (静态门面)              │
│  ┌───────────────┐  ┌──────────────────┐  │
│  │  ILoggerFactory│  │  globalLogger    │  │
│  └───────────────┘  └──────────────────┘  │
└──────────────────┬───────────────────────┘
                   │
       ┌───────────┴───────────┐
       │                       │
┌──────▼──────┐       ┌────────▼──────────┐
│  ONLY_CLIENT │       │  Server/Editor    │
│ UnityLogger  │       │ ZLoggerRollingFile│
│  Factory    │       │   Factory         │
└─────────────┘       └───────────────────┘
```

两套 Factory 的选择完全由编译宏 `ONLY_CLIENT` 控制——客户端走 `UnityLoggerFactory`，服务端和编辑器走标准 `LoggerFactory`，彻底隔离了两套运行时的日志后端。

---

## 二、LogManager 核心设计

### 2.1 静态构造器与默认级别

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

- **编辑器模式**：`Information` 级别，开发期间输出更多信息，方便调试。
- **客户端/服务端**：`Warning` 级别，生产环境只记录警告及以上，减少 I/O 开销。

这种"编译期分层"策略是零运行时成本的经典应用：不同环境下的日志量差异完全在编译期固化，无需运行时 `if` 判断。

### 2.2 滚动文件日志配置

```csharp
.AddZLoggerRollingFile(
    (dt, x) => $"{LogPathRoot}/game_{dt.ToLocalTime():yyyy-MM-dd_HH-mm-ss}_{x:000}.log",
    x => x.ToLocalTime().Date,   // 按日期滚动
    4096,                         // 单文件最大行数
    x =>
    {
        x.PrefixFormatter = (writer, info) =>
            ZString.Utf8Format(writer, "[{0}][{1}]",
                levelShort[(int) info.LogLevel],
                info.Timestamp.ToLocalTime().DateTime
            );
    }
)
```

**三个关键参数的工程含义：**

| 参数 | 值 | 意义 |
|------|----|------|
| 文件名模板 | `game_{日期}_{序号}.log` | 每次启动生成唯一文件，避免并发写入冲突 |
| 滚动策略 | `x.ToLocalTime().Date` | 跨日午夜自动切换新文件 |
| 最大行数 | `4096` | 单文件不超过 4096 行，防止单文件过大难以分析 |

**ZString.Utf8Format** 的性能优势：直接向 `IBufferWriter<byte>` 写 UTF-8 字节，绕过 `string` 中间对象，在高频日志场景下可减少大量 GC 压力。

### 2.3 跨平台 LogPathRoot

```csharp
private static string LogPathRoot
{
    get
    {
#if UNITY_EDITOR
        cachedLogPathRoot = Application.dataPath + "/../Logs";
#elif ONLY_CLIENT
        cachedLogPathRoot = Application.persistentDataPath;
#else
        cachedLogPathRoot = "./Logs";
#endif
    }
}
```

三套路径策略各有其意：
- **编辑器**：写到项目根目录下的 `Logs/`，便于开发时直接用文件管理器查看
- **客户端**：写到 `persistentDataPath`（`/sdcard/Android/data/...` 或 iOS 的沙盒目录），满足移动端读写权限要求
- **服务端**：写到当前工作目录下的 `./Logs/`，便于 Docker 容器挂载日志卷

### 2.4 日志级别动态切换（运行时）

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

这个方法展示了一个有趣的技巧：**通过反射修改 backing field 实现运行时日志级别热切换**。

正常情况下 `MinLevel` 属性没有 public setter，但通过 `GetBackingField()` 拿到 `<MinLevel>k__BackingField` 这个私有字段后可以强制赋值。这使得**无需重启即可在线上动态提升/降低日志级别**，在需要临时排查问题时非常有用。

```csharp
private static FieldInfo GetBackingField(this PropertyInfo property)
{
    string backingFieldName = $"<{property.Name}>k__BackingField";
    return property.DeclaringType?.GetField(backingFieldName, 
        BindingFlags.NonPublic | BindingFlags.Instance);
}
```

> ⚠️ 注意：IL2CPP 在 AOT 编译时会 strip 私有成员，生产环境慎用反射热切换。建议在客户端通过 ZLogger 的 `IOptionsMonitor<ZLoggerOptions>` 方案替代。

---

## 三、UnityLogger：轻量桥接层

```csharp
#if ONLY_CLIENT
public class UnityLogger: ILog
{
    public void Trace(string msg) => UnityEngine.Debug.Log(msg);
    public void Debug(string msg) => UnityEngine.Debug.Log(msg);
    public void Info(string msg)  => UnityEngine.Debug.Log(msg);
    public void Warning(string msg) => UnityEngine.Debug.LogWarning(msg);
    public void Error(string msg)   => UnityEngine.Debug.LogError(msg);
    public void Error(Exception e)  => UnityEngine.Debug.LogException(e);
}
#endif
```

`UnityLogger` 实现了框架自定义的 `ILog` 接口，是将 ET 框架日志调用路由到 `UnityEngine.Debug` 的**适配器**。

### 3.1 为何不直接用 UnityEngine.Debug？

在纯客户端项目里直接调用 `UnityEngine.Debug` 没有问题，但框架为了保持**服务端可复用性**（服务端没有 `UnityEngine` 命名空间），将日志行为抽象为 `ILog` 接口：

```
ILog（接口）
  ├── UnityLogger（客户端实现 → UnityEngine.Debug）
  └── ConsoleLogger（服务端实现 → Console.WriteLine / ZLogger）
```

这样同一套业务代码在服务端和客户端都能正常运行，日志输出目标由注入的具体实现决定。

### 3.2 日志等级映射关系

| ILog 方法 | UnityEngine.Debug | Console 颜色 |
|-----------|-------------------|-------------|
| Trace/Debug/Info | Log → LogType.Log | 白色 |
| Warning | LogWarning → LogType.Warning | 黄色 |
| Error(string) | LogError → LogType.Error | 红色 |
| Error(Exception) | LogException | 红色+堆栈 |

---

## 四、两套日志系统的协作关系

框架中实际存在**两条日志链路**：

```
链路1（服务端/框架底层）：
  业务代码 → LogManager.Logger.ZLogXxx() 
           → ZLoggerFactory → ZLoggerRollingFile

链路2（客户端/ET框架）：
  ET框架内部 → Log.Info() / Log.Warning()
             → ILog（UnityLogger实现）
             → UnityEngine.Debug.Log
```

两条链路独立工作，互不干扰：
- 链路1 负责**结构化日志**输出到文件，适合后期日志分析
- 链路2 负责**Unity Console 显示**，适合开发期调试

---

## 五、工程实践建议

### 5.1 日志分级规范

```csharp
// ✅ 正确使用姿势
LogManager.Logger.ZLogTrace("帧同步：收到帧 {0}", frameId);        // 高频调试，生产关闭
LogManager.Logger.ZLogInformation("场景加载完成：{0}", sceneName); // 重要流程节点
LogManager.Logger.ZLogWarning("网络重试 {0} 次", retryCount);      // 非致命异常
LogManager.Logger.ZLogError(ex, "战斗数据异常，战场ID {0}", battleId); // 需要告警的错误
```

### 5.2 避免日志 GC 的最佳实践

```csharp
// ❌ 字符串拼接产生 GC
LogManager.Logger.ZLogInformation("玩家 " + playerId + " 进入房间 " + roomId);

// ✅ ZString 插值，零 GC
LogManager.Logger.ZLogInformation($"玩家 {playerId} 进入房间 {roomId}");
// ZLogger 会自动将 C# 插值字符串优化为 ZString，无中间对象
```

### 5.3 移动端日志上报

```csharp
// 结合 Exceptionless（代码中已有注释的方案）：
// .AddZLoggerExceptionless("api-key", "http://your-server:5000")
// 可实现自动将 Error 级别日志上报到中心化日志服务
```

---

## 六、总结

| 特性 | 实现方式 | 收益 |
|------|---------|------|
| 跨平台日志后端 | `#if ONLY_CLIENT` + `UnityLoggerFactory` vs `LoggerFactory` | 同一接口兼容客户端/服务端 |
| 高性能输出 | ZLogger + ZString.Utf8Format | 消除日志路径 GC 分配 |
| 滚动文件策略 | 按日期 + 按行数双重滚动 | 防止单日志文件过大 |
| 运行时级别切换 | 反射修改 backing field | 线上热切换无需重启 |
| 接口适配 | UnityLogger 实现 ILog | ET 框架与 Unity 解耦 |

`LogManager` + `UnityLogger` 的组合展示了一个成熟游戏框架如何在**性能、可维护性和跨平台兼容性**三个维度上同时做好取舍，这种双引擎日志设计值得在实际项目中借鉴。
