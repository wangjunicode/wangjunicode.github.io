---
title: 战斗数值调试工具设计：可视化与日志系统
published: 2026-03-31
description: 解析战斗中实时数值屏幕显示调试工具的设计，涵盖 OnGUI 实时绘制、战斗日志分类筛选、帧快照与文件写入等调试能力的实现。
tags: [Unity, 调试工具, 战斗系统, 开发工具]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗数值调试工具设计：可视化与日志系统

## 前言

在复杂的战斗系统开发中，最大的难题往往不是写逻辑，而是**看清楚逻辑在运行时发生了什么**。伤害数值是否符合预期？某个 Buff 到底触发了几次？敌方角色的 AP（行动点）为什么异常？

本文分析 `BattleNumericScreenDisplay`——一个运行时内嵌于游戏的战斗调试可视化工具，看它如何将这些问题的答案实时呈现在屏幕上。

---

## 一、架构：独立不侵入

```csharp
/// <summary>
/// 战斗数值屏幕显示系统。
/// 监听战斗初始化/结束事件，将 BattleNumericScreenDisplay 注册到 OnGuiTransponder，
/// 不修改任何已有代码，独立新增。
/// </summary>
public static partial class BattleNumericScreenDisplaySystem
{
    [Event(SceneType.Current)]
    public class NumericDisplay_InitEvent : AEvent<Evt_InitLogShowrOnGUI>
    {
        protected override void Run(Scene scene, Evt_InitLogShowrOnGUI argv)
        {
            var bsComp = scene.GetComponent<BattleScriptComponent>();
            var display = new BattleNumericScreenDisplay(bsComp);
            var holder  = scene.GetOrAddComponent<BattleNumericScreenDisplayHolder>();
            SetupDisplay(holder, display);

            if (OnGuiTransponder.Instance != null)
                OnGuiTransponder.Instance.ShowLogToScreenEvent += display.OnGUI;
        }
    }

    [Event(SceneType.Current)]
    public class NumericDisplay_UnInitEvent : AEvent<Evt_UnInitLogShowrOnGUI>
    {
        protected override void Run(Scene scene, Evt_UnInitLogShowrOnGUI argv)
        {
            var holder = scene.GetComponent<BattleNumericScreenDisplayHolder>();
            var display = GetDisplay(holder);
            if (display != null && OnGuiTransponder.Instance != null)
                OnGuiTransponder.Instance.ShowLogToScreenEvent -= display.OnGUI;

            scene.RemoveComponent<BattleNumericScreenDisplayHolder>();
        }
    }
}
```

**核心设计理念：不侵入任何已有代码**

- 通过事件监听挂载：战斗开始时注册，战斗结束时注销
- 通过 `OnGuiTransponder` 统一管理所有 OnGUI 绘制，而不是直接写 MonoBehaviour
- `BattleNumericScreenDisplayHolder` 作为 ECS 组件持有 Display 对象的引用

这意味着：即使把这套调试工具完全删掉，也不会影响任何战斗逻辑。

---

## 二、UI 布局：四象限信息分区

```
┌─────────────────────────────────────────────┐
│     顶部：Turn/Frame | 己方HP/AP/PP | 敌方   │
├──────────────┬──────────────┬────────────────┤
│   己方单位   │   战斗日志   │   敌方单位     │
│   （左下）   │   （中下）   │   （右下）     │
└──────────────┴──────────────┴────────────────┘
```

这种四象限布局是调试 HUD 的经典设计：
- **顶部全局**：Turn（回合数）、Frame（帧数）是最关键的时序信息
- **左右单位**：己方和敌方的状态对比，方便发现数值异常
- **中间日志**：按时序记录战斗事件，支持关键词筛选

### 字号分级

```csharp
private const int FontBase  = 24;
private const int FontMain  = (int)(FontBase * 1.1f); // 26：一号位
private const int FontTopHp = FontBase * 2;           // 48：顶部 HP，最重要最大
private const int FontLog   = (int)(16 * 1.5f);       // 24：日志
private const int FontBtn   = (int)(13 * 1.75f);      // 22：按钮
```

字号设计体现了信息层级——HP 是最重要的数值，字号最大；日志是辅助信息，字号较小。

### 颜色语义

```csharp
private const string ColHp    = "#FFD700"; // 金黄 — HP
private const string ColGuard = "#FF8C00"; // 深橙 — Guard
```

颜色与数值类型绑定，让眼睛能快速定位关键信息。

---

## 三、日志系统：实时过滤的战斗事件流

### 3.1 日志缓冲区

```csharp
private readonly List<string> _logLines = new List<string>();
private const int MaxLogLines = 30;  // 只保留最新的 30 条

// 新日志插入头部（index 0 = 最新）
private bool _logNewArrived = false; // 有新日志时滚到顶部
```

插入头部而非尾部的设计，使得最新的日志始终显示在最上方，符合调试时"关注最新事件"的习惯。

### 3.2 关键词过滤

```csharp
private LogFilter[] _logFilters;

private void EnsureLogFilters()
{
    if (_logFilters != null) return;
    _logFilters = new LogFilter[]
    {
        new LogFilter
        {
            Label    = "Damage",
            Keywords = new[]{ "Damage", "damage", "伤害", "Dmg", "dmg" },
            Enabled  = true
        },
        new LogFilter
        {
            Label    = "Token",
            Keywords = new[]{ "Token", "token", "Focus", "Dodge", "Critical" },
            Enabled  = true
        },
        // 更多筛选器...
    };
}
```

每个过滤器有一个 `Enabled` 标志，可以在运行时通过 UI 按钮开关。**中英文关键词并存**（`"伤害"` 和 `"Damage"`）体现了本地化环境下调试工具的实用性——日志可能来自不同模块，使用不同的语言。

### 3.3 快捷键控制

```
Ctrl+T   显示/隐藏（开启时自动启用 Log.EnableStateLog）
Space    暂停/恢复（仅显示时有效）
```

注意 `Ctrl+T` 不只是显示/隐藏，还会联动 `Log.EnableStateLog`——这意味着调试显示关闭时，某些高频状态日志也同步关闭，避免性能损耗。这是"调试工具零性能影响"的重要设计。

---

## 四、帧快照机制

```csharp
private int _snapshotIntervalFrames = 20; // 默认每 20 帧快照一次
private int _lastSnapshotFrame = -1;

public int SnapshotIntervalFrames
{
    get => _snapshotIntervalFrames;
    set => _snapshotIntervalFrames = Mathf.Max(1, value); // 最少 1 帧
}
```

快照机制每 N 帧记录一次完整的战斗数值状态（HP、AP、Buff、状态标签等），而不是每帧都记录（会产生海量数据）。

**属性设置器中的 `Mathf.Max(1, value)` 是防御性设计**：快照间隔不能为 0 或负数，否则每帧都会快照。

---

## 五、战斗日志文件写入

```csharp
private StreamWriter _logFileWriter   = null;
private string       _logFileTempPath = null;
private bool         _wasInBattle     = false; // 检测新战斗开始
```

除了屏幕显示，系统还支持把战斗日志写入文件：

```
路径：Application.dataPath/../../battlelogs/
（即与 UnityProj 目录同级的 battlelogs/ 文件夹）
```

文件日志与屏幕显示的区别：
- **屏幕显示**：只保留最新 30 条，支持筛选，用于实时观察
- **文件日志**：全量无筛选记录，用于事后分析和 Bug 复现

`_wasInBattle` 检测战斗状态变化，当新战斗开始时重新创建日志文件，避免不同局的日志混杂在一起。

---

## 六、读取受保护字段的 Friend 机制

```csharp
[FriendOf(typeof(BattleScriptComponent))]
public static partial class BattleNumericScreenDisplaySystem
{
    // 通过 System 中转，暴露 BattleScriptComponent 的私有字段
    public static int GetCurTurn(BattleScriptComponent bsComp) => bsComp.CurTurn;
    public static int GetCurFrame(BattleScriptComponent bsComp) => bsComp.curFrame;
    public static Dictionary<long, Dictionary<EStateTag, int>> GetStateList(BattleScriptComponent bsComp)
        => bsComp.StateList;
}
```

`[FriendOf]` 是 ET 框架提供的特性，类似 C++ 的 `friend class`，允许指定类访问另一个类的受保护成员。

**为什么不直接暴露字段为 public？**

`CurTurn`、`curFrame`、`StateList` 是战斗逻辑的内部状态，不应该被任意代码读写。但调试工具需要读取它们。`[FriendOf]` 是一种精确的访问控制：只允许特定的类读取，而不是对所有人开放。

---

## 七、`OnGuiTransponder`：统一调度的 OnGUI

```csharp
OnGuiTransponder.Instance.ShowLogToScreenEvent += display.OnGUI;
```

`OnGuiTransponder` 是一个单例 MonoBehaviour，它的 `OnGUI` 方法会逐个调用所有注册的绘制委托。

**为什么要中转？**

- ECS 中的对象（`BattleNumericScreenDisplay`）不是 MonoBehaviour，没有 `OnGUI` 回调
- 通过 `OnGuiTransponder`，任何对象都可以注册绘制逻辑
- 统一管理注册和注销，避免忘记注销导致的野委托引用

---

## 八、GUIStyle 缓存

```csharp
private GUIStyle _bgStyle;
private GUIStyle _styleLeft;
private GUIStyle _styleRight;
private GUIStyle _styleTop;
private GUIStyle _styleLog;
private GUIStyle _btnOn;
private GUIStyle _btnOff;
```

GUIStyle 对象每次调用 `new GUIStyle()` 都有开销，在 `OnGUI`（每帧调用）中创建会导致严重的 GC。代码将所有 Style 缓存为字段，**只创建一次，重复使用**。

---

## 九、调试工具的设计原则

通过这个工具的分析，总结出调试工具的几条设计原则：

| 原则 | 实现 |
|------|------|
| 零侵入 | 事件监听，不修改业务代码 |
| 零性能影响（关闭时）| Ctrl+T 关闭时同步关闭高频日志 |
| 信息分层 | 字号/颜色/位置区分重要程度 |
| 可筛选 | 关键词过滤，聚焦关注点 |
| 可持久化 | 文件写入，支持事后分析 |
| 帧同步支持 | 显示 Turn/Frame，而非时间 |

对于刚入行的同学：**好的调试工具能让开发效率提升 3-5 倍**。在项目初期投入时间建设调试工具，是最高回报的技术投资之一。
