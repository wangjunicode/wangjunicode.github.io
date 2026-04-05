---
title: 副本与关卡数据系统设计
published: 2026-03-31
description: 深入解析游戏副本系统的数据模型，包含副本类型、队伍数据、敌方情报解锁、战斗回溯与爆点系统的完整设计思路。
tags: [Unity, 副本系统, 关卡设计, 游戏开发]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 副本与关卡数据系统设计

## 前言

"副本"（Dungeon）是大多数手游的核心玩法单元，它将玩家带入一段有明确目标的战斗体验。一套好的副本数据系统，不仅要承载战斗的必要参数，还要支撑多样的玩法模式——PVE 普通关卡、PVP 匹配对战、Roguelike 养成副本……

本文通过分析 `DungeonComponent` 的数据设计，带你理解如何为一个多模式副本系统建立清晰的数据模型。

---

## 一、副本组件的核心字段

```csharp
[ComponentOf(typeof(Scene))]
public class DungeonComponent : Entity, IAwake, IDestroy
{
    public int         DungeonID      { get; set; }  // 副本 ID（对应配置表）
    public int         DungeonBattleID { get; set; } // 对局 ID（服务端生成，唯一标识一场战斗）
    public int         RandSeed       { get; set; }  // 随机种子（帧同步使用）
    public EDungeonType DungeonType   { get; set; }  // 副本类型（PVE/PVP/养成等）
    public int         LevelID        { get; set; }  // 关卡 ID

    // PVP 专属：赛事信息
    public int    MatchDay        { get; set; }  // 比赛日期
    public string MatchRegionText { get; set; }  // 赛区名称
    public string MatchNameText   { get; set; }  // 比赛名称

    // 战斗回溯
    public int RetryTimesUsed  { get; set; }  // 已使用的回溯次数
    public int RetryTimesLimit { get; set; }  // 最大回溯次数
}
```

### 1.1 DungeonID vs DungeonBattleID

| 字段 | 生成方 | 唯一性 | 用途 |
|------|--------|--------|------|
| `DungeonID` | 策划配置 | 副本模板级别 | 确定关卡配置、奖励、难度 |
| `DungeonBattleID` | 服务端 | 全局唯一 | 标识这一场具体的战斗，用于结算、回放、防作弊 |

`DungeonID = 1001` 可能是"第一章第一关"，而 `DungeonBattleID` 每场战斗都不同——就像同一部电影（DungeonID）每次放映都有不同的场次编号（DungeonBattleID）。

### 1.2 随机种子：帧同步的基石

```csharp
public int RandSeed { get; set; }
```

帧同步要求所有客户端的逻辑计算结果完全一致。随机数是破坏确定性的大敌——如果每个客户端独立调用 `Random.Range()`，结果会不同。

解决方案：服务端在对战匹配时生成一个随机种子，发送给所有客户端。所有需要随机的逻辑，都使用基于这个种子的确定性随机数生成器（`Rnd` 类），保证所有端计算出相同的"随机"结果。

---

## 二、队伍数据的层次设计

```csharp
public class DungeonTeamData
{
    public TeamSaveData             BattleTeamData      { get; set; }  // 战斗用队伍配置
    public TeamExtraBuildData       BattleExtraTeamData { get; set; }  // 附加技能/装备数据
    public DungeonAdditionalTeamData AdditionalTeamData { get; set; }  // 玩法特有数据

    // 键 = IPCharacterEnum（角色 IP），值 = 附加角色数据
    public Dictionary<int, DungeonAdditionalCharacterData> AdditionalCharacters { get; set; }

    // 有序角色列表（按站位排列）
    public List<IPCharacterEnum> OrderedCharacters { get; set; }
}
```

### 2.1 三层数据模型

**第一层：`TeamSaveData`（持久化数据）**

这是从服务端获取的队伍存档数据——哪些角色、哪些技能、哪些装备。这份数据在对战匹配前就确定了，代表玩家的"长期养成"。

**第二层：`TeamExtraBuildData`（临时增强数据）**

"芯盒"等临时加成，可以在每次出战前调整，不影响长期存档。

**第三层：`DungeonAdditionalTeamData`（本次对局专属）**

```csharp
public class DungeonAdditionalTeamData
{
    public int    Fans     { get; set; }  // 粉丝数（养成模式）
    public int    Points   { get; set; }  // 积分
    public int    TeamID   { get; set; }  // 队伍预设 ID
    public string TeamName { get; set; }  // 队伍名称
    public string TeamIcon { get; set; }  // 队伍图标
}
```

这一层是本次对局的上下文数据，而非玩家的长期状态。比如，养成模式下的粉丝数可能随战斗变化，但不等于玩家账号的总粉丝数。

### 2.2 按 IPCharacterEnum 索引的角色数据

```csharp
public Dictionary<int, DungeonAdditionalCharacterData> AdditionalCharacters { get; set; }
```

用角色 IP（品牌形象 ID，如"爱豆A"=1、"爱豆B"=2）而非角色 ID 作为索引键，体现了这个游戏的特殊性：同一个 IP 可以有多个皮肤/形态，但在一场对战中，一个 IP 只能有一个。

### 2.3 直接属性访问接口

```csharp
public int GetAttributeDirect(IPCharacterEnum characterIP, EAttributeType attributeType, bool isPlayer)
{
    var teamData  = isPlayer ? PlayerTeamData : EnemyTeamData;
    var characters = teamData?.AdditionalCharacters;
    if (characters == null || !characters.TryGetValue((int)characterIP, out var character))
        return 0;

    return character?.Attributes?.GetValueOrDefault((int)attributeType) ?? 0;
}
```

这个方法是"只读查询"的典型实现：
- 使用空合并运算符（`?.` 和 `??`）处理所有可能的 null
- 找不到数据时返回 0（安全的默认值），不抛出异常
- 调用方无需关心内部数据结构

---

## 三、敌方情报系统：信息不对称设计

```csharp
public EEnemyUnlockType EnemyInfoUnlockStatus { get; set; }
```

"敌方情报解锁状态"是游戏中信息不对称机制的体现：

```csharp
[Flags]
public enum EEnemyUnlockType
{
    None    = 0,
    HP      = 1 << 0,  // 解锁敌方 HP 显示
    Skills  = 1 << 1,  // 解锁技能信息
    Strategy = 1 << 2, // 解锁战术分析
}
```

注意 `[Flags]` 特性——这是一个位域枚举，可以同时持有多个解锁状态：

```csharp
// 同时解锁了 HP 和技能信息
var status = EEnemyUnlockType.HP | EEnemyUnlockType.Skills;
bool hasHp = (status & EEnemyUnlockType.HP) != 0; // true
```

这比用多个 `bool` 字段更节省内存，也更方便序列化和比较。

**注释 "复合值"** 明确提示了这个字段是用位运算组合的，开发者读到这行代码时知道不能用 `==` 直接比较。

---

## 四、战斗回溯（Retry）：第二次机会的设计

```csharp
public int RetryTimesUsed  { get; set; }  // 已使用的回溯次数
public int RetryTimesLimit { get; set; }  // 最大回溯次数
```

战斗回溯（Roguelike 养成模式中的"回头看"功能）允许玩家在某个关键回合结束时，查看结果并决定是否退回重来。

**设计约束：**
- `RetryTimesLimit` 由服务端或配置表决定，客户端不能自行增加上限
- `RetryTimesUsed < RetryTimesLimit` 才允许回溯
- 使用后立刻同步到服务端，防止作弊（客户端重启重置计数）

---

## 五、爆点系统：戏剧性时刻的设计

```csharp
public HashSet<int>        UnlockRoundFeatureList = new HashSet<int>();
public Dictionary<int, int> RoundFeatures = new Dictionary<int, int>();
// 键 = 回合数，值 = 爆点 ID
```

"爆点"是游戏设计中预设的"戏剧性时刻"——在特定回合，触发特殊事件（比如第 3 回合播放高潮动画，或者 Boss 进入狂暴状态）。

**`RoundFeatures` 的设计：**

```
RoundFeatures = {
    3 → EventID_1001,  // 第 3 回合：播放高潮演出
    5 → EventID_1002,  // 第 5 回合：敌方 Boss 技能强化
}
```

每回合结束时检查 `RoundFeatures[curRound]` 是否有爆点，有则触发。

**`UnlockRoundFeatureList`** 存储"已解锁"的爆点 ID——部分爆点需要玩家满足特定条件（如连续三回合未受伤）才会解锁，未解锁则不触发。

---

## 六、副本系统方法：System 层实现

`DungeonComponentSystem` 中的关键方法印证了数据模型的设计：

```csharp
public static void SetDungeonBasicData(this DungeonComponent self,
    int dungeonID, EDungeonType dungeonType, int levelID)
{
    // 以下数据基本同时确定
    self.DungeonID    = dungeonID;
    self.DungeonType  = dungeonType;
    self.LevelID      = levelID;
}

public static bool IsRealBattle(this DungeonComponent self)
{
    return self.GetDungeonType() != EDungeonType.Unknown;
}

public static void Clear(this DungeonComponent self)
{
    self.DungeonID         = 0;
    self.DungeonType       = EDungeonType.Unknown;
    self.TeamDataList.Clear();
    self.PlayerTeamData    = null;
    self.EnemyTeamData     = null;
    self.EnemyInfoUnlockStatus = EEnemyUnlockType.None;
    self.UnlockRoundFeatureList.Clear();
    self.RoundFeatures.Clear();
    // ...
}
```

**`SetDungeonBasicData` 的注释 "以下数据基本同时确定"** 是重要的文档：这三个字段总是一起设置的，调用方不应该单独设置其中一个（否则会造成数据不一致）。

---

## 七、调试模式：PVEDebugInfo

```csharp
// 测试用吹替数据
public PVEDebugInfo debugInfo = new PVEDebugInfo();
```

`debugInfo` 是专门用于调试的数据，其中 `debugPVEMode` 可以设置为不同的测试模式（如`ePVEMode.Normal`、`ePVEMode.AutoBattle`）。

注意它没有 `{ get; set; }` 属性访问器，而是直接公开字段——这是开发环境下的快速妥协，表明这个字段从一开始就被标记为"临时的"（注释写了"测试用"）。

---

## 八、总结

| 设计元素 | 解决的问题 |
|---------|-----------|
| DungeonID vs BattleID | 区分"模板"和"实例" |
| 三层队伍数据 | 分离长期养成、临时加成、对局上下文 |
| 位域枚举 EEnemyUnlockType | 多状态压缩存储，支持渐进解锁 |
| RandSeed | 帧同步随机数的确定性保证 |
| RetryTimesUsed/Limit | 游戏内"回悔权"的数量限制 |
| RoundFeatures | 策划可配置的戏剧性时刻设计 |

副本系统的数据设计需要同时考虑玩法逻辑（多模式支持）、技术实现（帧同步、序列化）和游戏体验（信息不对称、回溯机制）。对于新手同学，建议从最简单的 PVE 副本模型开始，逐步扩展到多模式支持。
