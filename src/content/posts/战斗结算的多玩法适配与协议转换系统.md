---
title: 战斗结算的多玩法适配与协议转换系统
published: 2026-03-31
description: 深入解析同一套战斗结算框架如何支持 PVE、养成、PVP 三种玩法，包含客户端与服务端的双向数据转换、两阶段结算设计与战斗回溯的完整实现。
tags: [Unity, 战斗系统, 协议设计, 结算系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 战斗结算的多玩法适配与协议转换系统

## 前言

一个游戏往往有多种战斗玩法：普通 PVE 关卡、Roguelike 养成副本、PVP 竞技……每种玩法的结算逻辑略有不同，但结算的核心数据（胜负、伤害、技能使用）大体相似。

如何用一套代码框架优雅地支持多种结算玩法？本文通过分析 `BattleSettleUtils` 中的设计，带你理解多玩法适配的工程实践。

---

## 一、统一的结算数据流

所有玩法的结算都经过这条数据流：

```
战斗结束
  ↓
CreateSettleDataFromBattle()   ← 从战斗组件收集数据
  ↓
BattleSettleData               ← 统一的结算数据结构
  ↓
ConvertSettleDataToServer()    ← 转换为服务端协议
  ↓
发送 Protobuf 请求
  ↓
服务端返回 BattleSettleInfo
  ↓
ConvertSettleDataFromServer()  ← 转换回客户端格式
  ↓
BattleSettleData               ← 用于 UI 展示
```

客户端和服务端各有一套数据结构，通过 `ConvertSettleDataToServer` 和 `ConvertSettleDataFromServer` 互相转换，中间是服务端的权威计算结果。

---

## 二、客户端数据采集

```csharp
public static BattleSettleData CreateSettleDataFromBattle(bool isWin, Scene currentScene)
{
    var teamComp      = currentScene.GetComponent<TeamComponent>();
    var statisticComp = currentScene.GetComponent<BattleStatisticComponent>();
    var myTeam        = teamComp.GetMyTeam();

    var settleData = new BattleSettleData
    {
        DungeonID  = dungeonComp.GetDungeonID(),
        IsWin      = isWin,
        Characters = new List<CharacterSettleData>(),
        FightDetail = statisticComp.GetFightDetail(myTeam.TeamId),
    };

    SetBattleSettlementCharacterList(isWin, myTeam, settleData.Characters);  // 采集角色数据
    SetBattleSettleCharacterSkillUseData(myTeam, settleData.Characters);     // 采集技能数据
    SetReportData(settleData.Characters, report.characterReports);           // 采集战报数据
    return settleData;
}
```

**三步采集，三个来源：**

| 步骤 | 方法 | 数据来源 | 内容 |
|-----|------|---------|------|
| 1 | `SetBattleSettlementCharacterList` | `NumericComponent` | 伤害/治疗/击杀/分数 |
| 2 | `SetBattleSettleCharacterSkillUseData` | `PassiveSlotComponent` | 技能/Buff 使用次数 |
| 3 | `SetReportData` | `BattleReport` | IP/皮肤/站位信息补全 |

---

## 三、MVP 判定

```csharp
if (Characters.Count > 0)
{
    var mvp = Characters[0];
    foreach (var c in Characters)
    {
        if (c.score > mvp.score)
            mvp = c;
    }
    mvp.isMvp = true;  // 分数最高者为 MVP
}
```

MVP 的判定逻辑极其简单——分数最高者。但 `score` 的计算本身是复杂的：

```csharp
settleScore = numericComp.结算积分(i, isWin, teamNumerics).AsFloat();
```

注意：`结算积分` 是一个**中文方法名**——这是一个在帧同步数值系统中用中文命名的函数（基于公式配置表，名称直接来自策划文档）。这是一种特殊但有效的做法：当函数名对应一个策划定义的公式时，用中文命名可以避免翻译导致的语义损失。

---

## 四、养成玩法的两阶段结算

养成副本（Roguelike）的结算与普通 PVE 不同，有两个阶段：

### 4.1 第一阶段：预结算（PreSettle）

```csharp
public static async ETTask<bool> RequestCultivationPreSettle(
    BattleSettleData data, int dungeonBattleID)
{
    var req = new ZoneCultivateBattleEndPreSettleReq
    {
        DungeonId      = data.DungeonID,
        DungeonBattleId = dungeonBattleID,
        IsWin          = data.IsWin,
        BattleSettleInfo = ConvertSettleDataToServer(data),  // 上报战斗数据
    };
    var nr = await NetworkComponent.SendAsync<ZoneCultivateBattleEndPreSettleResp>(...);

    if (nr.IsCompleteSuccess)
    {
        // 更新重连状态为"预结算已完成"
        Player().UpdateBattleResumeState(EDungeonType.Cultivation,
            EnumDungeonStateType.DungeonStatePreSettle);
        Dungeon().ClearDungeonRecord();  // 清除本地录像
        return true;
    }
}
```

**预结算的用途：**
- 战斗数据上报到服务端暂存
- 玩家可以查看战斗统计，决定是否回溯（Retry）
- 服务端此时不立刻落地结果，等待玩家决策

### 4.2 第二阶段：正式结算或放弃

```csharp
// 正式结算（保存结果）
SaveType = ECultivateBattleEndSaveResultTypeSave

// 放弃（回溯，丢弃结果）
SaveType = ECultivateBattleEndSaveResultTypeGiveUp
```

玩家看完统计后，选择"确认结算"还是"回溯重来"：

```csharp
public static async ETTask<bool> RequestCultivationBattleGiveUp(...)
{
    var req = new ZoneCultivateBattleEndReq
    {
        SaveType = ECultivateBattleEndSaveResultTypeGiveUp,  // 放弃这场战斗结果
        IsWin = false,  // 回溯等同于失败
    };
    // 更新回溯次数
    Dungeon().UpdateDungeonMatchRetryData(nr.Data.RemainTimes);
}
```

放弃时：
- 战斗结果不落地（数据库不保存）
- 更新本地回溯次数
- 允许重新开始战斗

---

## 五、战斗历史记录

```csharp
// 养成战斗成功结算后，记录角色参战历史
var characterHistories = new List<ZoneCultivateCharacterMatchHistoryInfo>();
foreach (var characterSettleData in data.Characters)
{
    characterHistories.Add(new ZoneCultivateCharacterMatchHistoryInfo
    {
        IpId          = (int)characterSettleData.ipID,
        BattleVtypeId = characterSettleData.vTypeID,  // 角色版本（皮肤/形态）
        BattleStyleId = characterSettleData.styleID,  // 风格
        TeamPosition  = characterSettleData.teamIndex,
        OnStage       = characterSettleData.isOnStage,
        Score         = (int)characterSettleData.score,
        IsMvp         = characterSettleData.isMvp ? 1 : 0
    });
}

// 本地缓存
Cultivation().RecordCharacterMatchHistory(data.DungeonID, data.IsWin, characterHistories);
```

养成副本的历史记录比普通 PVE 更细致——记录了每个角色在这场战斗中的详细表现，用于：
1. **成就系统**：某角色参战 N 次、某角色 MVP N 次
2. **养成进度**：证明角色"上过场"，可能解锁特殊对话
3. **统计展示**：养成结束时展示整个剧本的参战历史

---

## 六、结算场景的预加载与角色展示

```csharp
public static async ETTask PreloadBattleSettlementUI()
{
    await VGameUILoader.Instance.LoadAssetAsync<GameObject>(
        BattleSettlementOutcomePanelResLoadPath, "BattleSettlementOutcomePanel");
    await VGameUILoader.Instance.LoadAssetAsync<GameObject>(
        BattleSettleScene, "BattleSettlementOutcomePanel");
    // ... 预加载其他资源
}
```

结算界面需要：
1. 结算 UI 面板（奖励列表、胜负展示）
2. 结算场景（3D 背景）
3. 角色模型（展示 MVP 和其他角色）

这些资源在战斗进行时预加载，避免战斗结束时出现长时间黑屏。

```csharp
// 根据胜负选择不同的动画
if (isWin)
{
    anim  = battleSettleCfg.AnimList[0];  // 胜利待机动画
    anim2 = (i == 0) ? battleSettleCfg.AnimList[1] : null;  // MVP 的特殊动画
}
else
{
    anim  = battleSettleCfg.AnimList[2];  // 失败待机动画
    anim2 = (i == 0) ? battleSettleCfg.AnimList[3] : null;  // 失败时 MVP（得分最高者）的动画
}
```

注意：即使失败，得分最高的角色（`i == 0`，因为列表已按分数排序）仍有专属动画——这是一个贴心的设计：失败时还有英雄主义的情感宣泄出口。

---

## 七、技能过滤：不是所有技能都显示

```csharp
private static bool ShouldSkipSkill(PassiveSkillInstance pSkill)
{
    // 低于稀有品质的心得卡技能不参与显示
    if (skillInfo.rarity < ERarityType.Rare && skillInfo.type == EPSkillSourceType.Chess)
        return true;

    // 标记为隐藏的技能不显示
    if (ECharacterPassiveUIType.Hide == characterPassiveSkill.CharacterUIType)
        return true;

    // 持续效果的技能不显示（没有"使用次数"概念）
    if (ECharacterPassiveUIType.Continuously == characterPassiveSkill.CharacterUIType)
        return true;

    return false;
}
```

这三条过滤规则体现了设计判断：
1. 品质太低的技能不够有"高光感"，不展示
2. 某些技能是内部辅助技能，不该暴露给玩家
3. 持续性被动技能没有"使用次数"，展示出来没有意义

---

## 八、总结

| 设计要点 | 作用 |
|---------|-----|
| 统一 BattleSettleData | 多玩法共用一套数据结构 |
| 两阶段结算 | 允许玩家查看后决策（确认或回溯） |
| 双向协议转换 | 客户端/服务端数据格式隔离 |
| 预加载结算资源 | 避免战斗结束黑屏等待 |
| 按分数排序+专属动画 | 胜负都有高光时刻，增强情感共鸣 |
| 技能过滤规则 | 只展示有意义的战斗信息 |

结算系统是战斗体验的"收口"——玩家的所有努力都在这里得到回应。一个好的结算系统不只是"显示数字"，更要让玩家感受到被认可和被激励继续游玩的动力。
