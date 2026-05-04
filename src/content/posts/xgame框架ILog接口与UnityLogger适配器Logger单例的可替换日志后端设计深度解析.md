---
title: xgame框架ILog接口与UnityLogger适配器Logger单例的可替换日志后端设计深度解析
date: 2026-05-04
tags: [Unity, 游戏框架, 日志系统, 设计模式, xgame]
categories: [Unity游戏开发]
encryptedKey: henhaoji123
---

# xgame框架ILog接口与UnityLogger适配器Logger单例的可替换日志后端设计深度解析

## 一、前言：为什么日志系统需要抽象层

在游戏开发中，日志输出看似简单，实则暗藏玄机。Unity Editor 里 `Debug.Log` 很方便，但发布到服务端或其他平台时可能需要用 `Console.WriteLine`、文件日志、甚至云端日志聚合服务。如果直接在业务代码中散落大量 `UnityEngine.Debug.Log`，一旦需要迁移平台或切换日志后端，代价极大。

xgame 框架通过三层结构解决这个问题：

```
ILog（接口契约）
  └── Logger（单例管理器，持有 ILog 实例）
        └── UnityLogger（Unity 平台适配器，实现 ILog）
```

这是典型的**策略模式（Strategy Pattern）**+ **单例门面（Singleton Facade）**组合，让日志行为完全可替换，同时对调用方透明。

---

## 二、ILog接口：日志行为的最小契约

```csharp
namespace ET
{
    public interface ILog
    {
        void Trace(string message);
        void Warning(string message);
        void Info(string message);
        void Debug(string message);
        void Error(string message);
    }
}
```

### 设计要点分析

**1. 五级日志语义明确**

| 方法 | 语义 | 典型场景 |
|------|------|---------|
| `Trace` | 最细粒度跟踪 | 函数进出、变量快照 |
| `Debug` | 调试信息 | 中间状态、条件分支 |
| `Info` | 一般信息 | 系统初始化、关键事件 |
| `Warning` | 警告（不影响流程） | 资源缺失、降级处理 |
| `Error` | 错误（可能影响流程） | 异常捕获、状态非法 |

**2. 注释掉的 params 重载**

代码中有一批被注释的带 `params object[] args` 的重载：

```csharp
// void Trace(string message, params object[] args);
// void Warning(string message, params object[] args);
```

这是早期设计遗留。`params object[]` 在 C# 中会触发装箱（boxing），每次调用都产生 GC 分配，对高频战斗日志性能不友好。框架最终转向 ZLogger 的零分配模板（`ZString.Concat`），因此将这些重载废弃。这个决策体现了框架从"够用"走向"极致性能"的演进轨迹。

**3. 接口极简原则**

没有日志级别过滤、没有格式化、没有文件输出——这些全部留给实现层去决定。接口只定义"能做什么"，不定义"如何做"，这正是接口隔离原则（ISP）的体现。

---

## 三、UnityLogger：Unity平台适配器

```csharp
#if ONLY_CLIENT
using System;

namespace ET
{
    public class UnityLogger : ILog
    {
        public void Trace(string msg)   => UnityEngine.Debug.Log(msg);
        public void Debug(string msg)   => UnityEngine.Debug.Log(msg);
        public void Info(string msg)    => UnityEngine.Debug.Log(msg);
        public void Warning(string msg) => UnityEngine.Debug.LogWarning(msg);
        public void Error(string msg)   => UnityEngine.Debug.LogError(msg);
        
        public void Error(Exception e)  => UnityEngine.Debug.LogException(e);
    }
}
#endif
```

### 设计要点分析

**1. 编译时平台隔离：`#if ONLY_CLIENT`**

这是 xgame 双端同构架构（客户端/服务端同一套代码）的关键设计。`UnityLogger` 只在客户端编译时存在。服务端编译时该文件完全消失，避免 `UnityEngine` 命名空间污染非 Unity 环境。

对比：

```
客户端 (ONLY_CLIENT=true)   → 编译 UnityLogger
服务端 (ONLY_CLIENT=false)  → 使用 ZLogger/Console 实现
```

**2. Trace/Debug/Info 映射同一个后端**

三个轻量级日志方法全都映射到 `UnityEngine.Debug.Log`。这是有意为之——Unity Console 只有三级（Log/Warning/Error），没有细粒度分级。框架在上层语义上区分 Trace/Debug/Info，但在 Unity 平台实际输出时合并。若需要在 Console 中区分，可以在日志内容前加 `[TRACE]` `[DEBUG]` 前缀，这属于实现层优化，不影响接口契约。

**3. Error 的双重重载**

```csharp
public void Error(string msg)   => UnityEngine.Debug.LogError(msg);
public void Error(Exception e)  => UnityEngine.Debug.LogException(e);
```

`Error(Exception e)` 不在 `ILog` 接口中定义（接口只有 `Error(string)`），这是一个**接口外扩展方法**。Unity 的 `LogException` 能在 Console 中展示完整的异常堆栈折叠视图，比手动调 `e.ToString()` 的体验好得多，因此在 UnityLogger 专属实现中额外提供。

---

## 四、Logger单例：日志系统的管理器门面

```csharp
namespace ET
{
    public class Logger : Singleton<Logger>
    {
        private ILog iLog;

        public ILog ILog
        {
            set { this.iLog = value; }
        }

        public int LogLevel { get; set; }

        private const int TraceLevel   = 1;
        private const int DebugLevel   = 2;
        private const int InfoLevel    = 3;
        private const int WarningLevel = 4;

        private bool CheckLogLevel(int level)
        {
            return LogLevel <= level;
        }
    }
}
```

### 设计要点分析

**1. 单例门面模式**

`Logger` 继承自框架的 `Singleton<T>` 基类（通过 `ISingletonAwake` 管理生命周期），全局唯一，是访问日志系统的统一入口。外部代码只需：

```csharp
Logger.Instance.ILog = new UnityLogger();
Logger.Instance.LogLevel = 3; // Info 及以上
```

**2. 日志级别过滤器**

```csharp
private bool CheckLogLevel(int level)
{
    return LogLevel <= level;
}
```

`LogLevel` 是阈值，`level` 是当前消息级别。`LogLevel <= level` 意味着：设置的阈值越小，允许通过的日志越多（Trace=1 全部放行；WarningLevel=4 只放行 Warning 和 Error）。这个过滤器在注释掉的方法中被大量使用，说明运行时日志级别动态调整是核心需求——线上关 Trace，调试开全档。

**3. 大量方法被注释的背后**

Logger 的具体分发方法全部被注释掉，只保留了 `ILog` 属性和 `LogLevel`。这不是"未完成"，而是框架的**演进痕迹**：

```
早期：Logger.Instance.Info("xxx")
↓ 演进
中期：Log.Info("xxx")  (通过静态 Log 类代理)
↓ 演进
当前：Log.Info("xxx")  (底层走 ZLogger 零分配路径)
```

`Logger` 单例退化成了一个**配置持有者**——持有 `ILog` 实现和 `LogLevel`，而不再承担分发逻辑。分发逻辑迁移到了 `Log` 静态分部类（`Logger.cs` + `LogEx.cs`）中。

---

## 五、三层结构的完整数据流

```
业务代码
  │
  ▼
Log.Info("msg")  ← 静态门面（LogEx.cs 实现）
  │
  ▼
ZLog(LogLevel.Information, ...)  ← ZLogger 零分配路径
  │
  ├── 正常日志 → LogManager.Logger（ZLogger/UnityLogger）
  │
  └── Warning/Error → 自动附加 StackTrace（调试友好）
```

整个调用链中，`ILog` / `UnityLogger` / `Logger` 是**早期抽象层**，`LogEx.cs` 中的 `ZLog` 系列方法是**现代零分配路径**，两者通过 `Logger.Instance.ILog` 桥接，可以共存也可以各自演进。

---

## 六、扩展：如何接入自定义日志后端

假设需要接入腾讯 CLS（云日志服务），只需：

```csharp
public class CLSLogger : ILog
{
    private readonly CLSClient client;
    
    public CLSLogger(CLSClient client) => this.client = client;
    
    public void Trace(string message)   { /* 不上报，节省费用 */ }
    public void Debug(string message)   { /* 不上报 */ }
    public void Info(string message)    => client.SendAsync(LogLevel.Info, message);
    public void Warning(string message) => client.SendAsync(LogLevel.Warn, message);
    public void Error(string message)   => client.SendAsync(LogLevel.Error, message);
}

// 注册
Logger.Instance.ILog = new CLSLogger(clsClient);
```

业务代码零改动，日志后端完全替换。这正是依赖倒置原则（DIP）的价值所在。

---

## 七、设计总结

| 组件 | 职责 | 模式 |
|------|------|------|
| `ILog` | 定义日志行为契约 | 接口（Interface） |
| `UnityLogger` | Unity 平台适配 | 适配器（Adapter） |
| `Logger` | 全局配置与生命周期管理 | 单例门面（Singleton Facade） |
| `Log` 静态类 | 业务调用入口，分发到后端 | 外观（Facade） + 策略（Strategy） |

xgame 的日志体系是一个典型的**可替换后端**设计。通过 `ILog` 接口隔离平台依赖，通过 `Logger` 单例统一管理，通过 `#if ONLY_CLIENT` 实现编译期平台分离，最终在 `LogEx.cs` 中以零 GC 分配的 ZLogger 管线完成现代化升级。理解这套层次，是读懂框架其他日志相关代码（如 `LogManager`、战斗日志过滤体系）的前提。
