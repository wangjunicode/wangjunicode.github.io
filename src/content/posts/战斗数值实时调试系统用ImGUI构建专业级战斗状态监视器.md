---
title: 战斗数值实时调试系统——用ImGUI构建专业级战斗状态监视器
published: 2026-03-31
description: 详解在Unity战斗游戏中实现一套实时数值调试HUD，包括布局设计、日志筛选、数值快照与帧文件写入
tags: [Unity, 战斗系统, 调试工具]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗数值实时调试系统——用ImGUI构建专业级战斗状态监视器

游戏开发中最痛苦的事情之一，是战斗数值不对，但你不知道是哪一帧、哪个单位出了问题。

打日志？日志太多，翻半天。加断点？战斗实时运行，断了就没法测。写Inspector面板？每次打开Editor很慢，Inspector数据也不够实时。

xgame项目的`BattleNumericScreenDisplay`给出了一个优雅的解决方案：一个直接叠加在游戏画面上的实时战斗状态调试HUD，用Unity的`OnGUI`实现，性能开销只在显示时计算。

## 一、系统的整体布局设计

```
┌─────────────────────────────────────────────────────────────┐
│  [顶部] Turn: 5  Frame: 240  |  我方HP: 850 AP: 30  |  敌方HP: 420  │
├──────────────────┬───────────────────┬─────────────────────┤
│  [左下] 我方3人   │  [中下] 战斗日志   │  [右下] 敌方3人       │
│  英雄A: HP/AP/PP │  F240 Damage 350  │  Boss: HP/AP/PP     │
│  英雄B: HP/AP/PP │  F239 Token +2    │  小兵A: HP/AP/PP    │
│  英雄C: HP/AP/PP │  F238 Guard -100  │  小兵B: HP/AP/PP    │
└──────────────────┴───────────────────┴─────────────────────┘
```

代码注释清晰描述了这套布局：

```csharp
/// 布局：
///   [顶部]   全局(Turn/Frame) + 己方Team HP/AP/PP | 敌方Team HP/AP/PP
///   [左下]   己方3人单位数据（右对齐）
///   [中下]   战斗日志（可筛选，最新在最上方，带Frame前缀）
///   [右下]   敌方3人单位数据（左对齐）
///
/// 快捷键：
///   Ctrl+T   显示/隐藏
///   Space    暂停/恢复（仅显示时有效）
```

这套布局的设计思路是：让数值调试人员一眼看到双方全局状态（顶部），同时能看到单位详情（左下、右下），并实时追踪事件日志（中下）。

## 二、GUIStyle的缓存设计

```csharp
public class BattleNumericScreenDisplay
{
    // GUIStyle 缓存，避免每帧重新创建
    private GUIStyle _bgStyle;
    private GUIStyle _styleLeft;    // 左侧单位：左对齐
    private GUIStyle _styleRight;   // 右侧单位：左对齐（布局负责左右放置）
    private GUIStyle _styleTop;     // 顶部：居中
    private GUIStyle _styleLog;     // 日志：上对齐左
    private GUIStyle _btnOn;        // 激活状态按钮
    private GUIStyle _btnOff;       // 非激活状态按钮
    private GUIStyle _btnFold;      // 折叠展开按钮
}
```

`GUIStyle`对象的创建有一定的开销。在`OnGUI`里（每帧调用2次以上）重复创建是非常浪费的。将样式缓存起来，首次调用时初始化一次，后续直接使用。

**字号设计**：

```csharp
private const int FontBase   = 24;
private const int FontMain   = (int)(FontBase * 1.1f); // 一号位角色放大10%
private const int FontTopHp  = FontBase * 2;           // 顶部HP放大到48
private const int FontLog    = (int)(16 * 1.5f);       // 日志字体缩小但更密集
```

通过相对倍数而非绝对值定义字体大小，便于统一调整整体大小。

**颜色设计**：

```csharp
private const string ColHp    = "#FFD700"; // 金黄色——HP（重要数值）
private const string ColGuard = "#FF8C00"; // 深橙色——护盾（次要数值）
```

不同数值类型用不同颜色区分，快速识别。

## 三、日志缓冲与滚动控制

```csharp
// 日志缓冲（新日志插入头部，index 0 = 最新）
private readonly List<string> _logLines = new List<string>();
private const int MaxLogLines = 30;

// 日志滚动位置
private Vector2 _logScrollPos = Vector2.zero;
private bool    _logNewArrived = false; // 有新日志时自动滚到顶部
```

两个关键设计：

**新日志插入头部**：最新的日志在列表最上方，不需要滚动就能看到最新事件。（对比游戏内聊天是新消息在底部——这里是调试工具，需要立刻看到最新事件）

**自动滚到顶部**：收到新日志时设置`_logNewArrived = true`，OnGUI绘制时自动将滚动条滚到顶部。调试时不需要手动滚动。

```csharp
// 最多保留30条日志
private const int MaxLogLines = 30;
```

限制日志条数防止内存无限增长，同时30条足够看到最近的战斗事件序列。

## 四、日志筛选系统

```csharp
private struct LogFilter
{
    public string   Label;    // 筛选器名称（显示在按钮上）
    public string[] Keywords; // 关键词列表（任意匹配）
    public bool     Enabled;  // 是否启用
}

private LogFilter[] _logFilters;

private void EnsureLogFilters()
{
    if (_logFilters != null) return;
    _logFilters = new LogFilter[]
    {
        new LogFilter { 
            Label = "Damage",   
            Keywords = new[]{ "Damage", "damage", "伤害", "Dmg" },
            Enabled = true  
        },
        new LogFilter { 
            Label = "Token",    
            Keywords = new[]{ "Token", "token", "Focus", "Dodge", "Critical" },
            Enabled = true  
        },
        // 更多筛选器...
    };
}
```

战斗日志非常密集，如果全部显示会信息过载。筛选器让调试人员只看关心的内容：
- 看伤害问题 → 只开启"Damage"筛选器
- 看资源（Token）问题 → 只开启"Token"筛选器

**Keywords数组支持中英文关键词**，兼容代码中中英文混用的日志。

## 五、FriendOf特性与组件访问控制

```csharp
[FriendOf(typeof(BattleNumericScreenDisplayHolder))]
[FriendOf(typeof(BattleScriptComponent))]
[FriendOf(typeof(TeamEntity))]
public static partial class BattleNumericScreenDisplaySystem
{
    // 封装受保护字段的访问（通过FriendOf获取权限）
    public static int GetCurTurn(BattleScriptComponent bsComp) => bsComp.CurTurn;
    public static int GetCurFrame(BattleScriptComponent bsComp) => bsComp.curFrame;
    public static Dictionary<long, Dictionary<EStateTag, int>> GetStateList(BattleScriptComponent bsComp) 
        => bsComp.StateList;
}
```

ET框架的`[FriendOf]`特性类似C++的`friend class`声明，允许一个系统类访问另一个组件的私有/保护字段。

**为什么要用FriendOf而不是直接改成public？**

`BattleScriptComponent.CurTurn`这样的字段如果改成public，所有代码都能随意读写，容易出现乱改导致的bug。通过`[FriendOf]`，只有被授权的系统才能访问，既保持了接口整洁，又允许特定的跨组件访问。

## 六、数值快照机制

```csharp
private int _snapshotIntervalFrames = 20; // 每20帧快照一次
private int _lastSnapshotFrame = -1;       // 上次快照的帧号

public int SnapshotIntervalFrames
{
    get => _snapshotIntervalFrames;
    set => _snapshotIntervalFrames = Mathf.Max(1, value); // 最少1帧快照一次
}
```

不是每帧都记录全量数值（太多了），而是每20帧拍一次"快照"，记录当前所有单位的完整状态。

快照的用途：
- 战斗复盘：出了问题，可以看某一帧的完整状态
- 性能数值对比：每20帧的快照可以发现数值缓慢变化的趋势

## 七、日志文件写入

```csharp
private StreamWriter _logFileWriter   = null;
private string       _logFileTempPath = null;
private bool         _wasInBattle     = false;

// 日志路径：Application.dataPath/../../battlelogs/（与UnityProj同级）
```

除了屏幕显示，还支持将战斗日志写入文件。路径在`UnityProj`同级目录（不在Assets内），避免Unity因为发现新文件而触发不必要的资源导入。

`_wasInBattle`用来检测"新战斗开始"：当从非战斗状态转为战斗状态时，打开一个新的日志文件，避免多次战斗的日志混在一起。

## 八、系统注册/注销的Event设计

```csharp
[Event(SceneType.Current)]
public class NumericDisplay_InitEvent : AEvent<Evt_InitLogShowrOnGUI>
{
    protected override void Run(Scene scene, Evt_InitLogShowrOnGUI argv)
    {
        var bsComp = scene.GetComponent<BattleScriptComponent>();
        var display = new BattleNumericScreenDisplay(bsComp);
        var holder = scene.GetOrAddComponent<BattleNumericScreenDisplayHolder>();
        SetupDisplay(holder, display);
        
        // 注册到OnGUI回调
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
        OnGuiTransponder.Instance.ShowLogToScreenEvent -= display.OnGUI;
        scene.RemoveComponent<BattleNumericScreenDisplayHolder>();
    }
}
```

**注释里有一句关键话**：`不修改任何已有代码，独立新增`。

这是一个很好的扩展性设计思路。通过监听已有的`Evt_InitLogShowrOnGUI`事件，在战斗初始化时自动注入调试HUD，完全不需要修改战斗的核心代码。如果以后要移除调试HUD，删除这两个Event类就够了，不会影响战斗逻辑。

## 九、性能开销控制

调试工具不应该影响游戏性能。这套系统的性能设计：

1. **默认不显示**：`_visible = false`，OnGUI里不可见就不绘制
2. **样式缓存**：GUIStyle只初始化一次
3. **日志上限**：最多30条，不无限增长
4. **按帧率快照**：不是每帧全量记录

完整代码接近1000行，但在非调试状态下（`_visible=false`），每帧的OnGUI代价只有一次bool检查，可以忽略不计。

## 十、总结

这套调试HUD体现了"调试工具第一公民"的工程文化。好的游戏团队不会因为"这只是调试工具不重要"就草率实现，而是花精力设计好用的工具，这样节省的调试时间远超工具开发时间。

对新手的建议：**工具开发是投资，不是成本**。一个好的调试工具可以让一个问题从"排查3天"变成"10分钟定位"。
