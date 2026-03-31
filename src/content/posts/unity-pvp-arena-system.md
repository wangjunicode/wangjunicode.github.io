---
title: PVP 匹配与竞技场系统设计
published: 2026-03-31
description: 深入解析 PVP 竞技场的多阶段流程管理，包含匹配系统、角色选择、赛季数据与服务端数据适配的完整设计思路。
tags: [Unity, PVP系统, 匹配系统, 游戏开发]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# PVP 匹配与竞技场系统设计

## 前言

PVP（Player vs Player）是竞技类手游的核心玩法，也是技术复杂度最高的系统之一。它需要处理：实时匹配、角色禁/选（Ban/Pick）、赛季积分、多局制胜负、服务端数据适配……

本文通过分析 `PVPArenaComponent` 和 `PVPMatchComponentSystem`，带你理解一套完整的 PVP 竞技场系统的客户端架构。

---

## 一、竞技场的状态机：EPVPArenaPhase

```csharp
public EPVPArenaPhase CurrentPhase  { get; set; }
public EPVPArenaPhase PreviousPhase { get; set; }
```

`EPVPArenaPhase` 定义了 PVP 整个流程的阶段：

```csharp
public enum EPVPArenaPhase
{
    None,             // 初始状态
    MainMenu,         // 主菜单
    Matching,         // 匹配中
    MatchFound,       // 匹配成功
    CharacterSelect,  // 角色选择（禁选）
    PreBattle,        // 战前准备
    InBattle,         // 战斗中
    Settlement,       // 结算
    Return,           // 返回大厅
}
```

`PreviousPhase` 存储上一个阶段，用于：
1. 部分状态切换需要知道"从哪里来"（如结算后是否返回匹配页或主菜单）
2. 调试时追踪状态历史

---

## 二、竞技场核心数据

```csharp
// 赛季信息
public int  CurrentSeasonId  { get; set; }
public long SeasonStartTime  { get; set; }
public long SeasonEndTime    { get; set; }

// 多局制赛分
public int CurrentRound  { get; set; }  // 当前第几局（从1开始）
public int TotalRounds   { get; set; }  // 总局数（通常3局）
public int PlayerScore   { get; set; }  // 玩家胜场数
public int OpponentScore { get; set; }  // 对手胜场数

// 角色禁选
public List<int>  PlayerTeamCharacterIds    { get; set; }  // 玩家队伍选择的角色
public List<int>  OpponentTeamCharacterIds  { get; set; }  // 对手队伍的角色
public List<PVPIPCharacterData> IPCharacters { get; set; }  // 可选的 IP 角色列表
public List<int>  AvailableCharacterIds      { get; set; }  // 当前可选的角色
public int        SelectedCharacterId        { get; set; }  // 本次选择的角色

// 容错值（防止匹配中的玩家因网络问题被惩罚）
public int MaxWinCountPerRound  { get; set; }
public int CurToleranceCount    { get; set; }
```

**`CurToleranceCount`（容错值）的设计：**

容错值是竞技游戏常见的"挂机/断线保护"机制：当玩家因网络问题断线时，不立即判负，而是消耗容错值给予重连机会。`CurToleranceCount = 100` 意味着初始有 100 点宽容，每帧消耗一定数量，归零后才判断处理。

---

## 三、匹配系统

```csharp
[FriendOf(typeof(PVPMatchComponent))]
public class PVPMatchingComponentUpdateSystem : UpdateSystem<PVPMatchComponent>
{
    protected override void Update(PVPMatchComponent self)
    {
        if (!self.PvpArena().IsMatching()) return;

        if (self.IsTimeout())
            self.OnMatchTimeout();
    }
}
```

### 3.1 开始匹配

```csharp
public static async ETTask StartMatch(this PVPMatchComponent self)
{
    self.MatchStartTime = TimeInfo.Instance.ClientNow();

    var req  = new ZoneFightPvpStartMatchReq();
    var resp = await NetworkComponent.SendAsync<ZoneFightPvpStartMatchResp>(
        (uint)ZoneClientCmd.ZoneCsFightPvpStartMatch, req);

    if (!resp.IsCompleteSuccess)
        self.OnMatchFailed();
    // 成功：等待服务端推送 Notify
}
```

注意：开始匹配后，客户端**不在这里等待匹配结果**，而是等待服务端主动推送 `ZoneFightPvpMatchNotify`。这是游戏服务器的标准模式——服务端推送比客户端轮询更高效，延迟也更低。

### 3.2 取消匹配

```csharp
public static async ETTask CancelMatch(this PVPMatchComponent self)
{
    if (!self.PvpArena().IsMatching())
        return;  // 非匹配状态时取消无效

    var resp = await NetworkComponent.SendAsync<ZoneFightPvpCancelMatchResp>(
        (uint)ZoneClientCmd.ZoneCsFightPvpCancelMatch, req);

    if (resp.IsCompleteSuccess)
        self.PvpArena().OnMatchCanceled();
}
```

取消匹配需要等待服务端确认才更新本地状态——这防止了"发送取消请求但网络丢包，客户端误以为已取消"的情况。

### 3.3 匹配超时

```csharp
public static bool IsTimeout(this PVPMatchComponent self)
{
    // TODO 先忽略超时逻辑
    return false;
    // ...
}
```

这里有一个注释掉的超时逻辑，还剩下 `return false`。注意这是代码中的**技术债注释**：超时逻辑已经写好但被暂时禁用（"先忽略"）。

在实际开发中，这种代码很常见——超时弹窗的 UX 体验还没确认，或者服务端超时逻辑已经处理了这个问题，客户端暂时不需要。

---

## 四、角色选择：选角完成的数据记录

```csharp
public static void OnCharacterSelectComplete(this PVPArenaComponent self,
    int ip, int characterId, int characterStyleId, List<int> initialCardIds)
{
    self.SelectedIpCharacterId = ip;         // IP 形象 ID
    self.SelectedCharacterId   = characterId;  // 具体角色 ID
    self.selectedStyleId       = characterStyleId;  // 皮肤/形态
    self.InitialCardIds        = initialCardIds;    // 初始心得卡
}
```

PVP 的角色选择包含多个维度：
- **IP**：角色品牌形象（"爱豆A"）
- **CharacterId**：具体的技能构建版本
- **StyleId**：皮肤/形态
- **InitialCardIds**：心得卡（Roguelike 元素，带入局内的能力牌）

这种多层次的"角色"概念是该游戏独特性的体现——同一个 IP 可以选择不同的战术构建。

---

## 五、服务端数据适配：`PVPGetTeamSaveDataFromMsg`

这是整个 PVP 系统中最"脏"的代码，也是最值得学习的：

```csharp
public static TeamSaveData PVPGetTeamSaveDataFromMsg(this PVPArenaComponent self, CellBoxInfoMsg info)
{
    var data = new TeamSaveData();
    data.dataSource = ESaveDataSource.PVPNetwork;

    #region todo: 服务器下发数据的冗余校验

    if (info == null)
    {
        // 兜底数据：info 为空时用硬编码数据代替
        Log.Info("[PVPArena] Get Team Save Data From Msg: Info is null");
        // ... 创建一个默认的 BoardInfo 和 ChessData ...
        return data;
    }

    if (info.ChessList.Count == 0)
    {
        // 服务端有时候 ChessList 为空但 BoardList 不为空
        // 手动从 BoardList 里提取 ChessInfo 补充 ChessList
        foreach (var board in info.BoardList)
        {
            foreach (var chess in board.ChessList)
            {
                info.ChessList.Add(chess.Info);
            }
        }
    }

    // 处理服务端可能下发 SelectStyleId=0 的异常情况
    foreach (var board in info.BoardList)
    {
        foreach (var character in board.CharacterList)
        {
            foreach (var characterStyle in character.VtypeList)
            {
                if (characterStyle.SelectStyleId == 0)
                {
                    Log.Info("[PVPArena] Server Select Style Id is 0");
                    characterStyle.SelectStyleId = 1;  // 默认使用样式1
                }
            }
        }
    }

    #endregion

    data.GetDataFromServer(info);
    return data;
}
```

**这段代码的价值在于它展示了真实项目的"客户端防御"：**

1. **服务端数据可能为空**：`info == null` 时用硬编码数据兜底，不崩溃
2. **服务端数据可能不完整**：`ChessList` 为空但 `BoardList` 不为空，手动合并
3. **服务端数据可能违反约定**：`SelectStyleId = 0` 是无效值，但服务端可能误发

每一个 `if` 背后都是一个线上 Bug 或联调发现的问题。`#region todo` 的标注表示这些防御是临时的——正确做法是修复服务端使其下发合法数据，客户端的防御最终应该被移除。

但在实际开发中，联调期间和上线初期，这种"多疑的客户端"往往能救命。

---

## 六、赛季系统的时间管理

```csharp
public long SeasonStartTime { get; set; }
public long SeasonEndTime   { get; set; }
```

PVP 赛季有明确的开始和结束时间。客户端保存这两个时间戳，用于：
- 显示赛季剩余时间
- 判断是否在赛季内（赛季外不允许匹配）
- 赛季结算动画（赛季结束时的积分结算）

---

## 七、帧同步配置

```csharp
public bool EnableFrameSync { get; set; }  // 是否启用帧同步
```

`EnableFrameSync` 是 PVP 模式的技术标志。与 PVE 不同，PVP 需要两个客户端完全确定性同步——每帧都必须产生相同的结果。

启用帧同步时：
- 所有逻辑计算使用定点数（`FP`）而非 `float`
- 随机数使用确定性伪随机生成器
- 网络延迟通过延迟帧处理（Rollback 或固定延迟）

---

## 八、PVP 系统的架构总结

PVP 系统的客户端架构遵循以下原则：

| 原则 | 实现 |
|------|------|
| 阶段状态机 | `EPVPArenaPhase` 明确管理流程 |
| 服务端主推 | 匹配结果、对手数据全部由服务端推送 |
| 防御性适配 | 对服务端数据做多层校验和修复 |
| 多局制支持 | `CurrentRound/TotalRounds/Score` 三元组管理赛况 |
| 容错保护 | `CurToleranceCount` 给玩家一定的断线宽容 |

对于新手同学，PVP 系统是一个很好的"综合练习"——它涉及网络、状态机、数据适配、帧同步等多个技术领域，理解它能大幅提升对游戏架构的整体认知。
