---
title: 战斗场景地形视图组件——分帧创建角色与红蓝阵营颜色切换
published: 2026-03-31
description: 解析战斗地形视图组件的设计，包括角色GameObject分帧创建队列、回合得分与场景颜色切换的事件联动
tags: [Unity, 战斗系统, 性能优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗场景地形视图组件——分帧创建角色与红蓝阵营颜色切换

战斗场景初始化时，需要把多个角色的GameObject放到场景里。如果同一帧内创建所有角色，会导致明显的卡顿（角色模型加载、动画初始化、Shader编译……）。

VGame项目的`TerrainViewComponent`用**分帧创建队列**解决了这个问题，同时管理了场景红蓝阵营颜色切换等视觉效果。

## 一、分帧创建队列机制

```csharp
[EntitySystem]
private static void Awake(this TerrainViewComponent self)
{
    // 注册角色创建任务事件
    self.RootDispatcher().RegisterEvent<Evt_CreateCharacterGoTask>(self.OnAddTeamMember);
    // ... 其他事件
}

// 收到创建任务时，不立刻创建，而是入队
private static void OnAddTeamMember(this TerrainViewComponent self, Evt_CreateCharacterGoTask evt)
{
    self.unitCreateQueue.Enqueue(evt);
}
```

关键在Update里：

```csharp
[EntitySystem]
private static void Update(this TerrainViewComponent self)
{
    float startTime = Time.realtimeSinceStartup;
    
    while (self.unitCreateQueue.Count > 0)
    {
        Evt_CreateCharacterGoTask task = self.unitCreateQueue.Dequeue();
        
        // 安全检查：如果单位已经被销毁，跳过
        if (task.unit == null || task.unit.IsDisposed)
            continue;
        
        // 发布"单位创建完成"事件（让其他系统处理后续初始化）
        EventSystem.Instance.Publish(self.CurrentScene(), 
            new Evt_AfterUnitCreate() { Unit = task.unit });
        
        // 时间预算检查：如果本帧已经超时，停止处理，下帧继续
        if (IsTimeOver(startTime, self.frameBudgetMS))
            return;
    }
}

static bool IsTimeOver(float startTime, float frameBudgetMS)
{
    return (Time.realtimeSinceStartup - startTime) * 1000f > frameBudgetMS;
}
```

**分帧创建的核心思路**：

1. 把所有创建任务放入队列（`unitCreateQueue`）
2. 每帧从队列中取出任务执行
3. 每次执行前记录开始时间，执行过程中检查已消耗时间
4. 如果超过帧时间预算（`frameBudgetMS`，比如5ms），立刻停止，留给下帧继续

这样每帧最多用5ms来创建角色，不会让单帧时间超过16ms（60fps），玩家看不到卡顿。

**`frameBudgetMS`是可配置的**，不同设备可以设置不同的预算：
- 高端机：8ms（每帧可以创建更多角色）
- 低端机：3ms（保守创建，优先保证帧率）

## 二、WaitComplete：等待队列清空

```csharp
public static async ETTask WaitComplete(this TerrainViewComponent self)
{
    var sceneLoaderComp = self.ClientScene().GetOrAddComponent<SceneLoaderComponent>();
    self.TerrainRoot = sceneLoaderComp.CurrentScene;
    
    if (self.TerrainRoot != null)
    {
        // 记录地形的初始位置（用于后续Reset还原）
        self.InitPos = self.TerrainRoot.transform.position;
    }
    
    // 等待队列清空（每帧检查一次）
    while (self.unitCreateQueue.Count > 0)
    {
        await TimerComponent.Instance.WaitFrameAsync();
    }
}
```

某些系统需要等待所有角色创建完毕才能继续（比如相机初始化需要所有角色的Transform）。`WaitComplete`提供了一个异步等待点，内部轮询队列是否清空。

`WaitFrameAsync()`是ET框架的"等待一帧"：每次循环等一帧，不会阻塞，给Update有机会继续消耗队列。

## 三、回合得分与场景颜色切换

战斗采用多局制，每局有胜负，场景颜色随胜负切换来强化视觉反馈：

```csharp
private static void OnRoundScore(this TerrainViewComponent self, Evt_RoundScoreEvent evt)
{
    // 只处理赢家的得分事件（不处理失败方）
    if (!evt.isWinner) return;
    
    var teamComp = self.Domain.GetComponent<TeamComponent>();
    bool isMyTeam = teamComp.GetMyTeam() == evt.team;
    
    // 赢了是蓝色（我方视角），输了是红色
    self.RoundScoreType = isMyTeam ? ERoundScoreType.Blue : ERoundScoreType.Red;
    
    // 找到场景中的颜色切换管理器
    var redBlueSwitchMgr = self.TerrainRoot.GetComponentInChildren<RedBlueSwitchManager>();
    if (redBlueSwitchMgr != null)
    {
        if (self.RoundScoreType == ERoundScoreType.Blue)
            redBlueSwitchMgr.SwitchBlueFunction(true).Coroutine();
        else
            redBlueSwitchMgr.SwitchRedFunction(true).Coroutine();
    }
}

private static void OnResetRoundScore(this TerrainViewComponent self, Evt_ResetRoundScore evt)
{
    self.ResetRoundScore(); // 每局开始前重置颜色
}
```

**RedBlueSwitchManager**是场景预制体上的组件，负责调整场景中的灯光颜色、地面材质颜色等视觉元素。胜利后场景偏蓝（代表我方主场），失败后场景偏红（代表对方优势）。

这种"状态→视觉"的联动设计，让玩家从场景颜色就能直观感受到战局走向，不需要盯着UI。

## 四、战斗点事件的地形响应

```csharp
private static void OnPointEvent(this TerrainViewComponent self, Evt_PointEvent evt)
{
    if (evt.EventID == BPDef.RoundEndEvtID || evt.EventID == BPDef.BattleEnd)
    {
        // 回合结束或战斗结束时重置地形到初始位置
        // （某些特效或地形动画会移动地形，结束时还原）
    }
}
```

战斗中可能有特效让地形"震动"或"位移"，`BPDef.RoundEndEvtID`（回合结束关键点）和`BPDef.BattleEnd`（战斗结束关键点）时，地形需要恢复到初始位置。

## 五、注释掉的逻辑：团队单位显示/隐藏

代码中有一段被注释掉的逻辑：

```csharp
/*if (task.bRefreshShowHide)
{
    if ((team.state == ETeamState.Battle && team.TeamMember.Count > 1) || task.bBackUp)
    {
        EventSystem.Instance.Publish(self.DomainScene(), 
            new Evt_TeamHiddenUnit() { team = team, unit = unit, ... });
    }
    else
    {
        EventSystem.Instance.Publish(self.DomainScene(), 
            new Evt_TeamShowUnit() { team = team, unit = unit, ... });
    }
}*/
```

这段注释代码曾经处理"创建角色时根据队伍状态决定是否显示"——多人队伍中，后备角色（backup）可能要隐藏，只显示上场的角色。注释掉了说明这个逻辑被移到其他地方处理了，或者创建流程变了。

这类注释保留价值很高：告诉后来者"这里曾经做过这件事，但被移走了"，防止后人重复实现。

## 六、GetComponentInChildren的性能考量

```csharp
var redBlueSwitchMgr = self.TerrainRoot.GetComponentInChildren<RedBlueSwitchManager>();
```

`GetComponentInChildren`会遍历场景层级，有一定性能开销。在每次回合得分时调用（比较低频），性能问题不大。

但如果是高频路径（比如每帧Update），应该在Awake时缓存：

```csharp
// Awake时缓存
self.redBlueSwitchMgr = self.TerrainRoot.GetComponentInChildren<RedBlueSwitchManager>();

// Update时直接使用缓存
if (self.redBlueSwitchMgr != null)
    self.redBlueSwitchMgr.SwitchBlue();
```

## 七、InitPos：场景位置的基准

```csharp
self.InitPos = self.TerrainRoot.transform.position;
```

场景加载时记录地形的初始位置。为什么场景位置会变化？

在VGame中，PVP等多人战斗需要"以战斗中心点为原点"计算帧同步逻辑，会移动地形：
- 战斗初始化时：把地形移到以0,0为中心的位置
- 战斗结束时：通过`InitPos`把地形还原到原始位置

这个技巧避免了在帧同步坐标系和Unity世界坐标系之间做复杂转换。

## 八、总结

TerrainViewComponent的设计展示了：

1. **分帧队列**：把大量工作分散到多帧执行，避免单帧卡顿
2. **帧时间预算**：实时测量帧用时，超时就停，保证帧率
3. **事件驱动场景效果**：回合胜负 → 场景颜色，不需要UI代码干预视觉
4. **InitPos记录基准**：允许场景动态移动而不丢失原始状态

对新手来说，"分帧处理队列"是优化批量初始化的通用技巧。无论是角色创建、资源加载还是AI寻路节点初始化，都可以用这套模式，让游戏在初始化阶段保持流畅。
