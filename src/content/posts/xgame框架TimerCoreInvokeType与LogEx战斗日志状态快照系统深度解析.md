---
title: xgame框架TimerCoreInvokeType与LogEx战斗日志状态快照系统深度解析
date: 2026-05-04
tags: [Unity, 游戏框架, 定时器, 日志系统, xgame, 战斗系统]
categories: [Unity游戏开发]
encryptedKey: henhaoji123
---

# xgame框架TimerCoreInvokeType与LogEx战斗日志状态快照系统深度解析

## 一、前言：两个"小文件"里的大设计

在 xgame 框架的 `Core` 目录下，有两个看起来微不足道的文件：

- `TimerCoreInvokeType.cs`：只有寥寥几行，定义一个常量
- `LogEx.cs`：表面上是日志扩展，实则包含一套完整的**战斗状态快照系统**

单独看每个文件都"太简单"，但结合框架整体，这两个文件揭示了 xgame 在**定时器调度扩展机制**和**零开销调试日志**两个维度上的深层设计哲学。

---

## 二、TimerCoreInvokeType：框架级调用类型注册表

### 2.1 源码全文

```csharp
namespace ET
{
    [UniqueId(0, 100)]
    public static class TimerCoreInvokeType
    {
        public const int CoroutineTimeout = 1;
    }
}
```

对比 `TimerCoreCallbackId.cs`：

```csharp
namespace ET
{
    public static class TimerCoreCallbackId
    {
        public const int CoroutineTimeout = 1;
    }
}
```

### 2.2 两个常量类的职责分离

这两个类名字相似、内容相同（都是 `CoroutineTimeout = 1`），却服务于完全不同的机制：

| 类名 | 机制 | 用途 |
|------|------|------|
| `TimerCoreCallbackId` | 普通 Timer 回调 ID | 标识一次性定时器到期后触发哪个回调 |
| `TimerCoreInvokeType` | InvokeHandler 调用类型 | 标识通过 `Invoke` 机制派发给哪个处理器 |

**Timer 回调（CallbackId）**是简单的"时间到了执行某函数"；**InvokeType**则是框架级消息派发——定时器到期后触发一个 `IInvoke<T>` 处理器，处理器通过反射注册，支持热更替换。

### 2.3 `[UniqueId(0, 100)]` 特性的作用

```csharp
[UniqueId(0, 100)]
public static class TimerCoreInvokeType
```

`UniqueIdAttribute` 是 xgame 的 Analyzer 系列特性之一，配合 Roslyn 静态分析工具使用：

```
UniqueId(startId, endId)
```

意思是：这个静态类中的所有 `const int` 常量，其值必须在 `[startId, endId)` 范围内（即 0 到 99），且框架内全局唯一，不允许重复。

这解决了一个大型游戏框架中常见的问题：**魔法数字冲突**。当多个子系统都用整数作为消息类型 ID 时，很容易出现不同系统的 ID 碰撞，导致消息路由到错误的处理器。`[UniqueId]` 让编译器在构建时就报错，把运行时 BUG 变成编译期错误。

框架核心预留了 `[0, 100)` 区间，业务层的 InvokeType 从 100 以后开始分配，职责清晰，永不冲突。

### 2.4 CoroutineTimeout 的工作流程

```
协程启动
  │
  ├─ 注册 TimerCoreInvokeType.CoroutineTimeout 类型的超时定时器
  │   └── TimerComponent.AddTimer(timeout, CoroutineTimeout, cancellationToken)
  │
  ├─ 协程正常完成 → 取消定时器
  │
  └─ 定时器触发（超时）
        │
        ▼
       EventSystem.Invoke<CoroutineTimeoutInvokeHandler>(...)
        │
        ▼
       ETCancellationToken.Cancel() → 协程被取消
```

`TimerCoreInvokeType.CoroutineTimeout = 1` 是这个系统的"消息ID"，整个协程超时防护机制围绕这一个常量运转。

---

## 三、LogEx：战斗日志的状态快照系统

### 3.1 从 LogEx 的角度重新理解 Log 体系

`LogEx.cs` 是 `Log` 静态分部类（`partial class`）的扩展部分，和 `Logger.cs` 共同构成完整的 `Log` 类。其核心贡献是两套机制：

1. **战斗状态快照（LogState）**：按 Key 存储实体的状态字符串，支持追加与覆写
2. **战斗信息日志（LogBattleInfo）**：带标签、帧号的高精度战斗流水日志

### 3.2 LogState 快照系统

```csharp
private static Dictionary<string, string> LogStateCache = new();
private static LogKey LastKey;

#if UNITY_EDITOR
public static bool EnableStateLog = false;
#else
public static bool EnableStateLog = false;
#endif
```

**设计精要：条件编译 + 运行时开关双重保护**

注意 Editor 和非 Editor 下 `EnableStateLog` 的默认值都是 `false`。这看起来是个 BUG（if/else 值相同），实则是为了以后的差异化扩展预留槽位：Editor 下可能需要在某个 Debug 配置中默认打开，而发布包永远默认关闭。

**核心写入方法：**

```csharp
private static void LogState(LogKey key, string message, bool append)
{
    LastKey = key;
    var str = key.ToString();
    if (string.IsNullOrEmpty(str)) return;
    
    if (LogStateCache.TryGetValue(str, out var old))
    { 
        if (append)
            LogStateCache[str] = ZString.Concat(old, message);  // 追加
        else
            LogStateCache[str] = message;                        // 覆写
    }
    else
    {
        LogStateCache[str] = message;
    }
}
```

`append=true` 时，新消息追加到已有内容后面，适合记录"一帧内某实体状态的连续变化序列"；`append=false` 时覆写，适合"每帧刷新某实体的最新状态"。

**对外的泛型重载族（零 GC 设计）：**

```csharp
public static void LogState<T1>(LogKey key, bool append, T1 t1)
public static void LogState<T1, T2>(LogKey key, bool append, T1 t1, T2 t2)
// ... 最多 7 个参数
```

使用泛型而非 `params object[]`，配合 `ZString.Concat<T1, T2...>` 的零分配字符串拼接，整个调用链不产生任何装箱（boxing）。当 `EnableStateLog = false` 时，整个方法体只有一行 `if (!EnableStateLog) return;`，JIT 会将其优化为**接近零开销**的空调用。

**LogStateAppend 系列：**

```csharp
public static void LogStateAppend<T1>(T1 t1)
{
    if (EnableStateLog) LogState(LastKey, t1.ToString(), true);
}
```

`LogStateAppend` 省略了 Key 参数，自动复用 `LastKey`。这是一种"续写"语法糖——连续记录同一个实体的多段状态时，只需第一次传 Key，后续调用 `LogStateAppend` 即可，减少代码噪声。

### 3.3 LogKey 结构体的零开销设计

```csharp
public partial struct LogKey
{
    private string name;
    
    public static LogKey Make(string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = name };
        return default;  // 返回空结构体
    }
    
    public static LogKey Make(long id, string name)
    {
        if (Log.EnableStateLog) return new LogKey { name = ZString.Concat(id, " ", name) };
        return default;
    }
    
    public static LogKey Make<T>(long id, T e)
    {
        if (Log.EnableStateLog) return new LogKey { name = ZString.Concat(id, " ", e) };
        return default;
    }
}
```

`LogKey` 是一个值类型（`struct`）。当 `EnableStateLog = false` 时，`Make()` 直接返回 `default`（全零的空结构体），不创建任何字符串对象。所有基于此 Key 的 `LogState` 调用因 Key 为空而提前返回，实现了**完全零分配的调试日志**。

这种"特性标记开关 + 值类型 Key"的组合，是游戏开发中最优雅的调试日志优化方案之一。

### 3.4 LogBattleInfo：带帧号的战斗流水日志

```csharp
public static Func<int> BattleFrameGetter;

private static void LogBattleInfo(BattleLogTag tag, string message)
{
    if (!EnableStateLog) return;
    LogInfo(ZString.Concat(
        LogPrefix,           // "BattleInfo: "
        LogTagTable[tag],    // "[Combo]" / "[Damage]" / ...
        " ",
        BattleFrameGetter?.Invoke() ?? Game.FixedFrames,  // 战斗帧号
        " ",
        message
    ));
}
```

**BattleFrameGetter 的依赖注入**

`BattleFrameGetter` 是一个 `Func<int>` 委托，而非直接引用战斗系统的帧计数器。这是**依赖注入**的巧妙运用：

- Log 系统（Core 层）不依赖战斗系统（Business 层）
- 战斗系统初始化时注入自己的帧获取函数：`Log.BattleFrameGetter = () => battleWorld.CurrentFrame;`
- 未注入时降级使用 `Game.FixedFrames`（引擎固定帧计数）

通过一个委托，打通了 Core 层日志系统和业务层战斗系统之间的信息通道，同时保持了架构上的单向依赖。

### 3.5 FilterResult 扩展方法：日志过滤查询

```csharp
public static bool FilterResult(this LogFilterType type, string str)
{
    return Log.LogFilter
        .Where(x => ((int)x.Key & (int)type) == (int)x.Key)
        .Any(filter => filter.Value.Any(str.StartsWith));
}
```

`LogFilterType` 是 `[Flags]` 枚举（位掩码），`FilterResult` 检查一条日志字符串是否属于当前过滤器允许的类别。

```csharp
// 只看 Token 和 Combo 相关日志
var filter = LogFilterType.Token | LogFilterType.Combo;
bool show = filter.FilterResult(logLine);
```

这个扩展方法是战斗调试工具（如 ImGUI 调试面板）的核心支撑，让开发者可以在运行时动态切换关注的日志类别，从海量战斗日志中精准定位问题。

---

## 四、两个系统的协作关系

```
战斗帧开始
  │
  ├─ TimerCoreInvokeType 定时器触发超时检测
  │   └── CoroutineLock 超时 → CancellationToken.Cancel()
  │
  ├─ 战斗逻辑执行
  │   ├─ Log.LogState(key, false, "combo=", combo)     // 覆写当前状态
  │   ├─ Log.LogStateAppend(" skill=", skillId)         // 追加技能信息
  │   └─ Log.LogBattleInfo(BattleLogTag.Damage, ...)   // 记录伤害流水
  │
  └─ 调试面板
      └─ FilterResult(LogFilterType.Damage | LogFilterType.Combo, line)
          └── 过滤显示感兴趣的日志
```

---

## 五、设计总结

**TimerCoreInvokeType** 展示了框架如何用静态常量 + 编译期约束（`[UniqueId]`）构建可靠的调度扩展点，1 个常量撑起了整个协程超时防护体系。

**LogEx** 展示了如何在零性能开销（`EnableStateLog=false` 时接近 NOP）和完整调试能力（`EnableStateLog=true` 时逐帧记录战斗状态）之间找到平衡。关键技术点：

- `struct LogKey` + `default` 返回：Key 创建零分配
- 泛型参数代替 `params object[]`：消息构建零装箱
- `Func<int> BattleFrameGetter` 委托：跨层信息传递零耦合
- `[Flags] LogFilterType` 位掩码：运行时灵活过滤

两个文件合起来不超过 80 行有效代码，却体现了 xgame 框架在"小处见大"方面的一贯作风——每一行代码背后都有明确的设计意图。
