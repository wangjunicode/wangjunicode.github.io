---
title: PVP竞技场状态机设计——用阶段切换驱动完整的对战流程
published: 2026-03-31
description: 深入解析PVP竞技场的阶段状态机设计，从角色选择到最终结算的完整流程控制与UI联动
tags: [Unity, PVP系统, 状态机]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# PVP竞技场状态机设计——用阶段切换驱动完整的对战流程

PVP游戏的核心复杂度在于流程控制：一场比赛要经历"进入大厅→选角色→匹配→战前准备→战斗→回合结算→最终结算"等多个阶段。每个阶段有自己的UI面板、网络交互和逻辑处理。

如何管理这些阶段？最简单的做法是用一堆if-else和全局状态变量，但这会迅速变得不可维护。xgame项目用**组合型状态机**来解决这个问题。

## 一、PVP阶段的枚举定义

```csharp
public enum EPVPArenaPhase
{
    None,               // 未初始化
    CharacterSelect,    // 选角色
    MainMenu,           // PVP主界面
    Matching,           // 匹配中
    BattlePrepare,      // 战前准备
    Battle,             // 战斗中
    RoundSettlement,    // 回合结算（多局制，每局后结算）
    FinalSettlement     // 最终结算（全部局结束）
}
```

一个完整PVP对战流程：
```
None → CharacterSelect → MainMenu → Matching → BattlePrepare 
     → Battle → RoundSettlement → Battle → ... → FinalSettlement
```

多局制的关键在于`RoundSettlement → Battle`可以循环，直到达到总局数。

## 二、阶段切换的核心逻辑

```csharp
public static void SwitchPhase(this PVPArenaComponent self, EPVPArenaPhase toPhase)
{
    EPVPArenaPhase fromPhase = self.CurrentPhase;
    Log.Info(ZString.Format("[PVPArena] Switch Phase: {0} -> {1}", fromPhase, toPhase));
    
    // 注意：允许"切换到同一阶段"，用于刷新当前阶段
    if (fromPhase == toPhase)
    {
        Log.Warning(ZString.Format("[PVPArena] Already in phase: {0}", toPhase));
        // return; // 注意这里是注释掉的，不直接返回
    }
    
    // 1. 退出当前阶段（清理当前阶段的资源）
    self.ExitPhase(fromPhase);
    
    // 2. 更新阶段记录
    self.PreviousPhase = fromPhase;
    self.CurrentPhase = toPhase;
    
    // 3. 发布阶段变化事件（逻辑层监听）
    EventSystem.Instance.Publish(self.ClientScene(), new PVPArenaPhaseChangeEvent
    {
        FromPhase = fromPhase,
        ToPhase = toPhase
    });
    
    // 4. 进入新阶段（初始化新阶段的资源）
    self.EnterPhase(toPhase);
    
    // 5. 发布UI阶段变化事件（View层监听）
    EventSystem.Instance.Publish(self.ClientScene(), new PVPShowPanelArenaPhaseChangeEvent
    {
        FromPhase = fromPhase,
        ToPhase = toPhase
    });
}
```

这个设计有几个精妙之处：

**双事件机制**：发布两个不同的事件——`PVPArenaPhaseChangeEvent`（逻辑层）和`PVPShowPanelArenaPhaseChangeEvent`（UI层）。逻辑和UI分离，各自订阅各自关心的事件。

**允许同阶段切换**：虽然会打印Warning，但不return。某些情况下需要"刷新"当前阶段（比如重新匹配），通过切换到同一阶段来实现。

## 三、阶段的Entity化设计

每个阶段对应一个独立的`PVPPhaseEntity`实体，而不是一个状态枚举值：

```csharp
private static void EnterPhase(this PVPArenaComponent self, EPVPArenaPhase phase)
{
    // 销毁上一个阶段实体
    if (self.CurrentPhaseEntityId != 0)
    {
        Entity oldPhaseEntity = self.GetChild<Entity>(self.CurrentPhaseEntityId);
        oldPhaseEntity?.Dispose();
        self.CurrentPhaseEntityId = 0;
    }
    
    // 创建新阶段实体
    PVPPhaseEntity phaseEntity = self.AddChild<PVPPhaseEntity, EPVPArenaPhase>(phase);
    self.CurrentPhaseEntityId = phaseEntity.Id;
    
    // 根据阶段类型，添加对应的功能组件
    switch (phase)
    {
        case EPVPArenaPhase.CharacterSelect:
            phaseEntity.AddComponent<PVPCharacterSelectComponent>();
            break;
        
        case EPVPArenaPhase.MainMenu:
            phaseEntity.AddComponent<PVPMainMenuComponent>();
            break;
        
        case EPVPArenaPhase.Matching:
            var match = phaseEntity.AddComponent<PVPMatchComponent>();
            match.StartMatch().Coroutine(); // 异步开始匹配
            break;
        
        case EPVPArenaPhase.BattlePrepare:
            phaseEntity.AddComponent<PVPBattlePrepareComponent>();
            break;
        
        case EPVPArenaPhase.Battle:
            phaseEntity.AddComponent<PVPBattleComponent>();
            break;
        
        case EPVPArenaPhase.RoundSettlement:
        case EPVPArenaPhase.FinalSettlement:
            phaseEntity.AddComponent<PVPSettlementComponent>(); // 两种结算共用同一组件
            break;
    }
}
```

**为什么要用Entity而不是简单地保存一个状态枚举？**

每个阶段都有自己的数据和逻辑：
- Matching阶段需要记录"已经等待了多久"
- Battle阶段需要引用战斗脚本组件
- Settlement阶段需要存储结算数据

把这些数据放在一个中心化的`PVPArenaComponent`里会让它变得庞大。将每个阶段的数据封装到独立的`PVPPhaseEntity`中，数据随阶段的创建/销毁而自动管理。

## 四、退出阶段的清理机制

```csharp
private static void ExitPhase(this PVPArenaComponent self, EPVPArenaPhase phase)
{
    if (phase == EPVPArenaPhase.None)
    {
        return; // 初始阶段无需清理
    }
    
    // 通过Dispose销毁阶段实体（包括其上所有组件）
    // Dispose触发Entity的DestroySystem，每个组件有机会清理自己的资源
}
```

`Entity.Dispose()`会触发该实体及其所有子组件的`DestroySystem`，实现自动级联清理。比如`PVPMatchComponent`的Destroy会取消正在进行的网络匹配请求，`PVPBattleComponent`的Destroy会清理战斗状态。

这是ECS架构的优势：**组件负责自己的生命周期清理**，阶段切换只需要Dispose旧实体，不需要知道里面有什么组件。

## 五、UI层的阶段响应

```csharp
[Event(SceneType.Client)]
public class PVPShowPanelArenaPhaseChangeEvent_Handler : AEvent<PVPShowPanelArenaPhaseChangeEvent>
{
    protected async override void Run(Scene scene, PVPShowPanelArenaPhaseChangeEvent args)
    {
        EPVPArenaPhase phase = args.ToPhase;
        
        switch (phase)
        {
            case EPVPArenaPhase.MainMenu:
                // 显示PVP主界面
                EventSystem.Instance.Publish(YIUIComponent.ClientScene, 
                    new Evt_ShowUIPanel { PanelName = PanelNameDefine.PVPMainPanel });
                break;
            
            case EPVPArenaPhase.BattlePrepare:
                // 设置队伍信息（名称、图标、赛区）
                var dungeon = scene.GetOrAddComponent<DungeonComponent>();
                dungeon.SetTeamNameAndIcon(arena.TeamName, arena.TeamIcon, true);
                
                // 读取回合名称（多语言）
                var commonData = CfgManager.tables.TbRound.GetOrDefault(curRound);
                var textId = int.Parse(commonData.BattleName);
                var matchName = Lang.GetText(textId);
                dungeon.SetDungeonMatchData(matchRegion, matchName);
                
                // 继续切换到Battle阶段
                arena.SwitchPhase(EPVPArenaPhase.Battle);
                break;
            
            case EPVPArenaPhase.RoundSettlement:
                // 构建回合结算数据
                var settleData = BattleSettleUtils.CreateSettleDataFromBattle(
                    arena.CurBattleIsWin, scene.CurrentScene());
                
                // PVP特有数据：积分变化、粉丝数变化、胜场变化、容忍度变化
                var element1 = new BattleSettlementReward { 
                    rewardName = "获得积分", 
                    rewardNum = pvpSettlementData.PointNum 
                };
                var element2 = new BattleSettlementReward { 
                    rewardName = "获得粉丝", 
                    rewardNum = pvpSettlementData.FansNum 
                };
                // ... 更多结算数据元素
                
                // 显示结算面板
                EventSystem.Instance.Publish(YIUIComponent.ClientScene, 
                    new Evt_ShowUIPanel<BattleSettlementData> { 
                        PanelName = PanelNameDefine.BattleSettlementOutcomePanel,
                        p1 = settlementData 
                    });
                break;
        }
    }
}
```

注意`BattlePrepare`阶段的处理：设置好数据后，直接调用`arena.SwitchPhase(EPVPArenaPhase.Battle)`继续切换。这是一个"自动推进"的阶段——`BattlePrepare`不需要用户交互，只是做些准备工作，完成后自动进入Battle。

## 六、PVP结算数据的特殊性

PVP的结算数据与普通副本不同：

```csharp
var element1 = new BattleSettlementReward { 
    rewardName = BattleSettlementDataConst.GetPoint, 
    rewardNum = pvpSettlementData.PointNum, 
    suffix = BattleSettlementDataConst.GetPointSuffix  // "积分"
};
var element3 = new BattleSettlementReward { 
    rewardName = BattleSettlementDataConst.WinNum, 
    rewardNum = pvpSettlementData.WinNum,
    // 赢了显示变化量，输了不显示
    suffix = isLose ? "" : $"(+{pvpSettlementData.WinNumChange})"
};
var element4 = new BattleSettlementReward { 
    rewardName = BattleSettlementDataConst.Tolerance, 
    rewardNum = pvpSettlementData.ToleranceNum,
    // 输了显示扣除量，赢了不显示
    suffix = isLose ? $"(-{pvpSettlementData.ToleranceNumChange})" : ""
};
```

PVP结算面板共用了与副本相同的`BattleSettlementOutcomePanel`，但数据内容不同。通过`BattleSettlementReward`列表的灵活组装，同一个UI面板可以展示不同的结算内容。

## 七、服务器数据的容错处理

```csharp
public static TeamSaveData PVPGetTeamSaveDataFromMsg(
    this PVPArenaComponent self, CellBoxInfoMsg info)
{
    var data = new TeamSaveData();
    data.dataSource = ESaveDataSource.PVPNetwork;
    
    // 服务器数据为空的兜底逻辑
    if (info == null)
    {
        Log.Info("[PVPArena] Get Team Save Data From Msg: Info is null");
        // 构造一个默认队伍数据，用于测试/兜底
        // （默认放一个绮海在棋盘上）
        // ...
        return data;
    }
    
    // 服务器数据校验：棋子列表为空时从棋盘列表重新构建
    if (info.ChessList.Count == 0)
    {
        foreach (var board in info.BoardList)
            foreach (var chess in board.ChessList)
                info.ChessList.Add(chess.Info);
    }
    
    // 服务器下发的样式ID为0时的处理
    foreach (var board in info.BoardList)
        foreach (var character in board.CharacterList)
            foreach (var characterStyle in character.VtypeList)
                if (characterStyle.SelectStyleId == 0)
                {
                    Log.Info("[PVPArena] Server Select Style Id is 0");
                    characterStyle.SelectStyleId = 1; // 默认样式
                }
    
    data.GetDataFromServer(info);
    return data;
}
```

注释里有一句`#region todo:服务器下发数据的冗余校验`，这段校验逻辑说明项目遇到过服务器下发数据不完整的情况（开发阶段服务器还未完善），客户端加了多层防御性校验。

## 八、状态机设计的实战经验

**问题1：阶段切换时旧UI还没关**

`SwitchPhase`是同步的，但UI关闭可能是异步的（有关闭动画）。如果新阶段的UI立刻打开，会与旧UI的关闭动画叠加。

解决方案：UI关闭时使用`async`，确保动画完成后才回调，或者新UI等待旧UI完全关闭后再打开。

**问题2：网络请求在阶段切换后响应**

Matching阶段发出了匹配请求，但在收到响应之前用户取消了匹配（阶段切换走了）。此时收到的匹配成功消息应该被忽略。

解决方案：`PVPMatchComponent.Destroy`时记录"已取消"标志，收到响应时先检查是否仍在Matching阶段。

## 九、总结

PVP竞技场状态机设计的核心思想：

| 设计点 | 解决的问题 |
|--------|---------|
| Entity化阶段 | 阶段数据自动随阶段生命周期管理 |
| 双事件分离 | 逻辑层和UI层独立响应阶段变化 |
| Dispose清理 | 离开阶段时自动级联清理所有资源 |
| 阶段组件化 | 每个阶段的功能由对应组件封装 |

对新手来说，这套设计最重要的启发是：**复杂的流程控制不是用if-else来堆，而是把每个阶段变成一个独立的"可管理实体"**。阶段有明确的进入和退出，数据有明确的归属，代码自然就清晰了。
