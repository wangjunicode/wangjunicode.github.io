---
title: 游戏日志系统设计——Logger 单例的可替换日志接口与日志级别过滤
published: 2026-03-31
description: 解析 Logger 单例的设计，理解 ILog 接口的依赖注入思想、多级日志过滤机制、注释代码透露的设计演化历程，以及如何在不同环境中替换日志实现。
tags: [Unity, ECS, 日志系统, 依赖注入, 接口设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 游戏日志系统设计——Logger 单例的可替换日志接口与日志级别过滤

## 前言

"哦，日志嘛，不就是 `Debug.Log` 么？"

在个人项目里确实如此。但在大型游戏项目中，日志系统需要：
- 在不同环境（客户端/服务端）使用不同的日志实现
- 过滤不同级别的日志（开发时输出所有，发布时只输出错误）
- 不改代码就能切换日志后端（Unity Console、文件日志、远程日志系统）

`Logger` 类就是为这些需求设计的。

```csharp
public class Logger : Singleton<Logger>
{
    private ILog iLog;

    public ILog ILog
    {
        set { this.iLog = value; }
    }

    public int LogLevel { get; set; }

    private const int TraceLevel = 1;
    private const int DebugLevel = 2;
    private const int InfoLevel = 3;
    private const int WarningLevel = 4;
}
```

---

## 一、ILog 接口——策略模式的核心

```csharp
private ILog iLog;

public ILog ILog
{
    set { this.iLog = value; } // 只有 set，没有 get
}
```

`ILog` 是日志后端的接口，`Logger` 通过这个接口与具体实现解耦。

**注意只有 `set` 没有 `get`**——这是有意设计的。外部可以设置日志实现，但不能读取（日志实现是内部细节）。

`ILog` 接口可能长这样（根据注释中的方法推断）：

```csharp
public interface ILog
{
    void Trace(string message);
    void Debug(string message);
    void Info(string message);
    void Warning(string message);
    void Error(string message);
}
```

**不同环境的实现**：

```csharp
// 客户端：使用 Unity Debug.Log
public class UnityLog : ILog
{
    public void Trace(string msg) => UnityEngine.Debug.Log($"[TRACE] {msg}");
    public void Debug(string msg) => UnityEngine.Debug.Log($"[DEBUG] {msg}");
    public void Info(string msg) => UnityEngine.Debug.Log($"[INFO] {msg}");
    public void Warning(string msg) => UnityEngine.Debug.LogWarning(msg);
    public void Error(string msg) => UnityEngine.Debug.LogError(msg);
}

// 服务端：写入文件
public class FileLog : ILog
{
    public void Info(string msg) => File.AppendAllText("server.log", $"[INFO] {msg}\n");
    // ...
}

// 远程日志：发送到 ELK 集群
public class RemoteLog : ILog { ... }
```

游戏启动时注入对应的实现：

```csharp
Logger.Instance.ILog = new UnityLog(); // 客户端
Logger.Instance.ILog = new FileLog();  // 服务端
```

---

## 二、LogLevel——动态日志过滤

```csharp
public int LogLevel { get; set; }

private const int TraceLevel = 1;
private const int DebugLevel = 2;
private const int InfoLevel = 3;
private const int WarningLevel = 4;

private bool CheckLogLevel(int level)
{
    return LogLevel <= level;
}
```

`LogLevel` 是一个过滤阈值：只有级别 >= `LogLevel` 的日志才会输出。

**过滤逻辑**：

```
LogLevel = 1（Trace）  → 所有日志都输出
LogLevel = 3（Info）   → Trace 和 Debug 被过滤，只输出 Info/Warning/Error
LogLevel = 4（Warning）→ 只输出 Warning 和 Error
LogLevel = 99          → 什么都不输出（关闭所有日志）
```

```csharp
// 使用方式（根据注释推断）
private void Info(string msg)
{
    if (!CheckLogLevel(InfoLevel)) return; // 如果当前 LogLevel > InfoLevel，过滤
    this.iLog.Info(msg);
}
```

**实际场景**：

```csharp
// 开发时：显示所有级别日志
Logger.Instance.LogLevel = TraceLevel; // = 1

// 测试环境：只显示 Info 以上
Logger.Instance.LogLevel = InfoLevel; // = 3

// 生产环境：只显示 Warning 以上（减少日志量）
Logger.Instance.LogLevel = WarningLevel; // = 4
```

---

## 三、注释代码——设计演化的历史痕迹

`Logger` 中有大量被注释掉的方法：

```csharp
// public void Trace(string msg)
// {
//     if (!CheckLogLevel(DebugLevel))
//     {
//         return;
//     }
//     StackTrace st = new StackTrace(2, true);
//     this.iLog.Trace($"{msg}\n{st}");
// }
```

这些注释揭示了几个重要信息：

### 3.1 StackTrace 的使用（已弃用）

```csharp
StackTrace st = new StackTrace(2, true);
this.iLog.Trace($"{msg}\n{st}");
```

旧版本在 Trace 级别会自动附带调用栈信息，便于调试。

为什么被注释掉？因为 `new StackTrace()` 是极其耗时的操作（反射遍历调用栈），在高频日志调用时会严重影响性能。

现代做法：让 IDE 或 Unity 的日志系统自动提供调用栈，而不是手动在日志消息中附加。

### 3.2 格式化日志方法

```csharp
// public void Info(string message, params object[] args)
// {
//     if (!CheckLogLevel(InfoLevel)) return;
//     this.iLog.Info(string.Format(message, args));
// }
```

`string.Format(message, args)` 是带参数格式化。注释掉的原因可能是：

现代 C# 的 `$"{}"` 插值字符串更安全更直观，而且编译器可以对它做优化（如[LogProperties 的零开销格式化](https://learn.microsoft.com/en-us/dotnet/core/extensions/logger-message-generator)）。

### 3.3 E/D/T 异常数据

```csharp
// public void Error(Exception e)
// {
//     if (e.Data.Contains("StackTrace"))
//     {
//         this.iLog.Error($"{e.Data["StackTrace"]}\n{e}");
//         return;
//     }
//     string str = e.ToString();
//     this.iLog.Error(str);
// }
```

异常对象的 `Data` 字典可以携带额外信息。代码检查是否有自定义的 StackTrace 数据（可能是在异步代码中手动记录的），如果有就用自定义的，否则用异常本身的。

这解决了异步代码中 StackTrace 丢失的问题（async/await 会导致调用栈不完整）。

---

## 四、为什么方法都被注释了？

当前 `Logger` 类的所有方法都被注释，说明实际的日志调用方式已经迁移到了别处（可能是 `Log` 静态类）：

```csharp
// 推断：项目中实际使用的日志 API
public static class Log
{
    public static void Info(string msg) => Logger.Instance.iLog?.Info(msg);
    public static void Error(Exception e) => Logger.Instance.iLog?.Error(e.ToString());
    // ...
}
```

这样调用更简洁：

```csharp
Log.Info("玩家进入场景"); // 比 Logger.Instance.Info("...") 更简短
```

`Logger` 类保留为单例基础设施（管理 `ILog` 实例和 `LogLevel`），具体的调用通过静态 `Log` 类进行。

---

## 五、依赖注入的设计思想

整个 `Logger` 设计体现了**依赖注入**（Dependency Injection）的思想：

```
Logger（消费者）
  ↑ 注入
ILog（接口）
  ↑ 实现
UnityLog / FileLog / RemoteLog（具体实现）
```

`Logger` 不创建 `ILog` 的实例，而是通过属性注入接收外部提供的实现。

这让：
1. `Logger` 与具体日志实现解耦（客户端用 Unity，服务端用文件，互不干扰）
2. 测试时可以注入 Mock 实现（验证特定操作是否产生了预期的日志）
3. 运行时可以动态切换日志实现（如开启调试模式时切换到更详细的实现）

---

## 六、设计总结

| 特性 | 设计 | 价值 |
|---|---|---|
| 单例 | `Singleton<Logger>` | 全局唯一的日志入口 |
| ILog 接口 | 策略模式 | 可替换的日志实现 |
| 只有 set | 封装内部实现 | 外部无法读取日志实现 |
| LogLevel | 过滤阈值 | 运行时控制日志量 |
| 注释代码 | 演化历史 | StackTrace 成本太高，被移除 |

---

## 写给初学者

日志系统是游戏中最容易被忽视但影响最大的系统之一：

**好的日志系统**：出现 Bug 时，日志能帮你快速定位问题
**差的日志系统**：要么刷屏（太多无用日志），要么关键信息缺失

`Logger` 的设计思路：
1. 用接口解耦，适应不同环境
2. 用日志级别过滤，控制日志量
3. 用单例统一入口，避免日志配置混乱

在自己的项目中，即使用最简单的封装（一个包裹 `Debug.Log` 的静态类），也要考虑日志级别控制——这样在发布版本中可以一行代码关闭所有调试日志，而不用挨个删除。
