---
title: 养成副本系统设计：日程驱动的 Roguelike 玩法
published: 2026-03-31
description: 深度解析剧本式养成副本的核心架构，包含循环本与剧情本的双轨入口、日程调度机制、角色技能构建与继承系统的设计思路。
tags: [Unity, 养成系统, Roguelike, 游戏设计]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 养成副本系统设计：日程驱动的 Roguelike 玩法

## 前言

养成副本是将 Roguelike 元素引入角色养成的创新玩法：玩家带着培养好的角色进入一段剧本旅程，经历多天的"日程"，通过战斗、交互、决策积累能力，最终到达不同结局。每次游玩都可能有新体验，某些成果还能带入下一轮——这就是"继承"机制的价值。

本文通过分析 `CultivationComponentSystem` 的多文件实现，带你理解这套复杂玩法背后的系统架构。

---

## 一、养成玩法的两种类型

```csharp
// 循环本：可以多次游玩，重复解锁
public static IEnumerable<CultivationCycleScriptDetailData> GetCycleScripts(
    this CultivationComponent self,
    Func<CultivationCycleScriptDetailData, bool> predicate = null)
{
    foreach (var script in self.CycleScripts)
    {
        if (predicate == null || predicate(script))
            yield return script;
    }
}

// 剧情本：有明确的结局和完成状态
public static IEnumerable<CultivationStoryScriptDetailData> GetStoryScripts(
    this CultivationComponent self,
    Func<CultivationStoryScriptDetailData, bool> predicate = null)
{
    // 类似实现
}
```

**循环本 vs 剧情本的设计差异：**

| 维度 | 循环本（CycleScript）| 剧情本（StoryScript）|
|-----|------|------|
| 重玩性 | 可以反复游玩 | 每个结局只能首次解锁 |
| 目标 | 刷取资源/练习 | 解锁故事内容 |
| 难度曲线 | 可能逐渐变难 | 固定叙事难度 |
| 结局 | 无固定结局 | 有多个分支结局 |

这种双轨入口设计让不同类型的玩家都有动力：
- 喜欢刷资源的玩家打循环本
- 喜欢故事的玩家专注剧情本

---

## 二、日程系统：时间轴驱动的玩法节奏

养成副本的核心是"日程（Schedule）"——玩家每天都有安排好的活动：

```csharp
public static bool IsFirstSchedule(this CultivationComponent self)
{
    var data = self.GetScheduleData();
    return self.GetScheduleID() == data.StartScheduleID;
}

public static bool IsLastMatchSchedule(this CultivationComponent self)
{
    var data = self.GetScheduleData();
    return self.GetScheduleID() == data.LastMatchScheduleID;
}

public static bool IsLastSchedule(this CultivationComponent self)
{
    var data = self.GetScheduleData();
    return self.GetScheduleID() == data.EndScheduleID;
}

public static int GetScheduleDay(this CultivationComponent self)
{
    var data = self.GetScheduleData();
    return data?.ScheduleDay ?? 0;
}
```

`StartScheduleID → ... → LastMatchScheduleID → ... → EndScheduleID`

日程有明确的首尾标记，中间是若干普通日程和至少一个"最后比赛日程"。这种设计让系统知道：
- 是否要提示"今天是最后一场比赛"
- 是否要触发结局演出
- 是否要展示最终结局选择界面

### 2.1 日程与天数的关系

`GetScheduleDay()` 返回当前是第几天。注意不是"已经过了几个日程"，而是"日历上的天数"——一个日程可能跨越多天（比如"第3天到第5天都是训练日"对应同一个 ScheduleID）。

这种设计更符合故事叙述的逻辑：玩家看到的是"第X天"，不是"第X个日程节点"。

---

## 三、角色扩展：在剧本中成长的角色数据

```csharp
// CultivationCharacterExtensions.cs

public static class CultivationCharacterExtensions
{
    // 获取角色在养成剧本中的当前好感度
    public static int GetCultivationFavor(this IPCharacterEnum characterIP,
        CultivationComponent cultComp)
    {
        var runData = cultComp.GetRunningData();
        if (runData == null) return 0;

        var character = runData.Characters.Find(c => c.IP == characterIP);
        return character?.Favor ?? 0;
    }

    // 获取角色的 "活动状态"（在场/请假/受伤等）
    public static EFormInTeam GetFormInTeam(this IPCharacterEnum characterIP,
        CultivationComponent cultComp)
    {
        var runData = cultComp.GetRunningData();
        var character = runData?.Characters.Find(c => c.IP == characterIP);
        return character?.FormInTeam ?? EFormInTeam.None;
    }
}
```

这是**扩展方法+枚举**的组合技：`IPCharacterEnum` 是角色的品牌形象枚举，通过扩展方法为其附加查询能力，而不需要改变枚举本身的定义。

`EFormInTeam`（活动状态）的设计值得注意——角色不只有"在/不在"两种状态，而是有更丰富的状态（请假、受伤、演出中……），这反映了偶像养成游戏对细节的重视。

---

## 四、批量查询：predicate 过滤器的使用

```csharp
// 使用示例：查找所有已完成的剧情本
var completedScripts = new List<CultivationStoryScriptDetailData>();
cultivationComp.GetStoryScripts(
    completedScripts,
    script => script.IsCompleted  // predicate：只要已完成的
);

// 查找指定 ID 的循环本
var targetScript = cultivationComp.GetCycleScript(
    script => script.ScriptID == 1001  // predicate：指定 ID
);
```

所有"获取XX列表"的方法都接受一个可选的 `Func<T, bool> predicate` 参数，实现了"带过滤的查询"。

**这个设计的优雅之处：**

1. **零成本抽象**：调用方传入 Lambda，系统在枚举时直接调用，不产生额外集合
2. **灵活组合**：两个 predicate 可以用 `&&` 组合：`s => s.IsCompleted && s.IsUnlocked`
3. **空安全**：`predicate == null` 时返回全部，调用方可以选择不传

---

## 五、分离关注点的文件组织

```
CultivationComponentSystem.Entry.cs       — 入口管理（获取剧本列表）
CultivationComponentSystem.Script.cs      — 剧本核心逻辑
CultivationComponentSystem.ScriptSchedule.cs — 日程调度
CultivationComponentSystem.ScriptCharacter.cs — 剧本内角色状态
CultivationComponentSystem.ScriptTeam.cs  — 剧本内队伍管理
CultivationComponentSystem.ScriptHistory.cs — 历史记录
CultivationComponentSystem.ScriptInteract.cs — 交互系统
CultivationComponentSystem.Battle.cs      — 战斗逻辑
CultivationComponentSystem.Cache.cs       — 数据缓存
```

这是 C# `partial class` 的最佳实践：一个逻辑上的 System（`CultivationComponentSystem`）被拆分到多个文件，每个文件专注一个子领域。

**为什么不用继承？**

`partial class` 和继承都能做到"分文件"，但继承会产生类型层级、增加 vtable 查找开销，而且子类无法直接访问父类私有字段。`partial class` 是真正的"零成本分割"——编译后等同于一个类。

---

## 六、缓存机制：避免重复计算

```csharp
// CultivationComponentSystem.Cache.cs

private static Dictionary<int, CultivationScheduleData> _scheduleCache = new();

private static CultivationScheduleData GetCachedScheduleData(int scheduleId)
{
    if (!_scheduleCache.TryGetValue(scheduleId, out var data))
    {
        data = CfgManager.tables.TbCultivationSchedule.GetOrDefault(scheduleId);
        _scheduleCache[scheduleId] = data;  // 缓存结果
    }
    return data;
}
```

日程数据来自配置表，配置表查询是 O(1) 的，但对象创建和 GC 有开销。缓存层将"配置表数据对象"变成"只创建一次，反复复用"，在日程频繁切换的场景下效果显著。

---

## 七、战斗恢复：掉线保护

```csharp
// CultivationBattleRecoveryHandler.cs

[Event(SceneType.Client)]
public class CultivationBattleRecoveryHandler : AAsyncEvent<Evt_EnterGame>
{
    protected override async ETTask Run(Scene scene, Evt_EnterGame argv)
    {
        var cultComp = scene.GetComponent<CultivationComponent>();
        var runData  = cultComp?.GetRunningData();

        // 如果有进行中的战斗
        if (runData?.IsInBattle == true)
        {
            // 弹出恢复对话框
            bool shouldRecover = await ShowRecoveryDialog();
            if (shouldRecover)
            {
                await cultComp.RecoverBattle(runData.BattleToken);
            }
            else
            {
                // 选择放弃：以失败处理
                await cultComp.HandleBattleAbandoned(runData);
            }
        }
    }
}
```

登录时检查是否有未完成的养成战斗，这是"战斗掉线恢复"机制在养成玩法中的具体实现。

**与 `DungeonComponent` 的 `BattleResumeData` 呼应：**

`PlayerComponent` 中的 `BattleResumeData` 是全局的战斗恢复数据，而这里的 `runData.IsInBattle` 是养成玩法专属的战斗状态。两者互不干扰，各自管理自己的恢复逻辑。

---

## 八、继承系统：上一局影响下一局

```csharp
// 继承数据结构（在 PlayerComponent 中）
public class CultivationInheritSourceData
{
    public CultivationRatingData  Rating       { get; set; }  // 上次评级
    public int                    MaxChessNum  { get; set; }  // 最多可继承的卡片数
    public int                    MaxChessRarity { get; set; } // 最高可继承稀有度
    public List<ReflectionCardData> ChessList  { get; set; }  // 可供选择继承的卡片
}
```

继承系统是 Roguelike 元素中"元进度"（Meta-progression）的体现：

1. **评级继承**：上次成绩越好，能带入的初始属性越高
2. **卡片继承**：优质的技能卡可以带入下一局
3. **双重限制**：`MaxChessNum`（数量）和 `MaxChessRarity`（品质）两个维度约束继承，防止无限强化

这种双限制设计保证了新玩家和老玩家的体验差距有上限——你不能靠继承无限强化，必须在每局中通过游戏本身的成长机制提升。

---

## 九、总结

养成副本系统是游戏中复杂度最高的系统之一，它的设计展示了：

| 设计决策 | 解决的问题 |
|---------|-----------|
| 循环本/剧情本双轨 | 满足不同玩家偏好 |
| 日程时间轴 | 控制玩法节奏，驱动叙事进展 |
| `partial class` 分文件 | 关注点分离，降低维护复杂度 |
| predicate 查询接口 | 灵活过滤，零额外集合开销 |
| 缓存层 | 避免重复配置表查询 |
| 继承系统 | Roguelike 元进度，激励长期游玩 |
| 战斗恢复处理 | 断线不丢失战斗进度 |

理解这套系统，核心是把握"日程 → 战斗 → 结局 → 继承"这条生命周期链，每个模块都服务于这条主线。
