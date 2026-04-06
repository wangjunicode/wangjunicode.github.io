---
title: Unity游戏战斗结算统计界面数据处理与排序展示
published: 2026-03-31
description: 深入解析战斗结算统计界面的数据聚合、技能使用次数排序展示、Buff/Token分组显示、状态槽填充机制及YIUIMatchUIElement数据驱动绑定模式。
tags: [Unity, UI系统, 战斗结算, 数据统计]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity游戏战斗结算统计界面数据处理与排序展示

## 战斗结算统计界面的设计目标

战斗结算后的统计界面（Combat Log / Statistics Panel）让玩家回顾整场战斗的表现：
- 每个角色使用了哪些技能、使用了几次
- 关键Buff/Token的获得情况
- 角色出战编号（#1, #2, #3）

这个界面虽然不参与主要游戏流程，但它直接影响玩家对战斗体验的记忆——好的统计展示能让玩家感受到"这场战斗打得有策略性"，强化游戏深度感。

从技术角度，统计界面的挑战是：
1. **数据聚合**：从战斗日志中计算每个技能被使用了多少次
2. **排序**：按使用次数降序排列，突出"主力技能"
3. **固定槽位填充**：无论技能数量多少，永远显示5个槽（不足用空槽填充）
4. **数据驱动绑定**：数据列表和 UI 组件列表的自动匹配

---

## YIUIMatchUIElement：数据驱动的 UI 绑定框架

```csharp
YIUIMatchUIElementHelper.MatchUIElement<CharacterSkillCountInfo, BattleStatisticsCharacterSkillGroup>(
    characterSkillCounts,                    // 数据列表
    BattleStatisticsCharacterSkillGroupList, // UI组件列表
    Create,                                  // 创建新组件的工厂函数
    SetData                                  // 数据绑定函数
);
```

`YIUIMatchUIElementHelper.MatchUIElement` 是 YIUI 框架提供的数据-视图绑定辅助方法，它解决了"数据列表和 UI 列表数量不匹配"的问题：

- 如果 UI 组件比数据少，调用 `Create` 创建新组件
- 如果 UI 组件比数据多，隐藏多余的组件
- 对每个数据-组件对，调用 `SetData` 绑定数据

这是**数据驱动 UI（Data-Driven UI）**的核心工具，让代码只关注"数据是什么"，不需要手动管理 UI 组件的增删。

```csharp
// 工厂函数：如何创建一个新的角色技能分组
BattleStatisticsCharacterSkillGroup Create(int idx)
{
    return YIUIFactory.Instantiate<BattleStatisticsCharacterSkillGroup>(
        u_ComCharacterSkillContainerRectTransform  // 父节点
    );
}

// 绑定函数：如何给组件设置数据
void SetData(CharacterSkillCountInfo info, BattleStatisticsCharacterSkillGroup group, int idx)
{
    group.SetData(info.CharacterInfo, info.SkillCountInfos);
    
    // Buff/Token 分组需要特殊处理（只有前3个角色）
    switch (idx)
    {
        case 0: u_UIBattleStatisticsBuffTokenGroup.SetData(info.BuffTokenCountInfos); break;
        case 1: u_UIBattleStatisticsBuffTokenGroup_1.SetData(info.BuffTokenCountInfos); break;
        case 2: u_UIBattleStatisticsBuffTokenGroup_2.SetData(info.BuffTokenCountInfos); break;
    }
}
```

**Buff/Token 用 switch 而不是循环**的原因：这三个 Buff/Token 分组是预先在 Prefab 中配置好的三个独立 UI 节点（`u_UIBattleStatisticsBuffTokenGroup`, `_1`, `_2`），数量固定为3，不支持动态增加。switch 比维护一个 List 更直观。

---

## 技能使用统计的排序逻辑

```csharp
public void SetData(CharacterInfo characterInfo, List<SkillCountInfo> skillCountInfos)
{
    // 按使用次数降序排列（最常用的技能排最前面）
    skillCountInfos.Sort((a, b) =>
    {
        return b.Count.CompareTo(a.Count);  // b.Count - a.Count 降序
    });
    
    // 设置角色头像和出战编号
    u_UIBattleStatisticsCharacterItem.SetData(
        characterInfo.CharacterId, characterInfo.TeamNum);
    
    // 固定显示5个技能槽，不足用"空槽"填充
    if (skillCountInfos.Count < slotCount)
    {
        var addCount = slotCount - skillCountInfos.Count;
        for (int i = 0; i < addCount; i++)
        {
            skillCountInfos.Add(new SkillCountInfo { State = 3 });  // State=3 代表空槽
        }
    }
    
    LoopScroll.SetDataRefresh(skillCountInfos);
}
```

**固定槽位设计（5个）的产品逻辑**：

无论角色有几个技能，统计界面永远显示5个方格。空的方格用特殊状态（State=3）显示为灰色占位，视觉上保持整齐的网格布局，避免不同角色的统计区域高度不一致（影响整体布局稳定性）。

**`skillCountInfos.Add` 的副作用警告**：

这里直接修改了传入的 `skillCountInfos` 列表（而不是先复制一份再修改）。如果调用方在 `SetData` 后还会使用这个列表，会发现它已经被添加了空槽数据。这是一个潜在的设计陷阱——更安全的做法是：

```csharp
// 更安全的版本：先复制
var displayList = new List<SkillCountInfo>(skillCountInfos);
// 对 displayList 进行操作，不影响原始数据
```

---

## SkillItem 的状态管理

```csharp
private void Renderer(int idx, SkillCountInfo skillCountInfo, 
    BattleStatisticsSkillItem battleStatisticsSkillItem, bool select)
{
    if (skillCountInfo.State == 3)
    {
        // State=3: 空槽（没有技能）
        battleStatisticsSkillItem.SetState(skillCountInfo.State);
        return;  // 不设置数据，只设置状态
    }
    
    if (skillCountInfo.Count <= 0)
    {
        // 有技能但本场战斗没有使用 → 灰色（State=1）
        skillCountInfo.State = 1;
    }
    
    battleStatisticsSkillItem.SetState(skillCountInfo.State);
    battleStatisticsSkillItem.SetData(skillCountInfo.SkillId, skillCountInfo.lv, skillCountInfo.Count);
}
```

技能槽有三种状态：
- `State=0`：正常（有技能，使用过）→ 彩色显示
- `State=1`：灰色（有技能，没使用）→ 灰色显示（表示角色有这个技能但本场没用到）
- `State=3`：空槽（位置占位）→ 空白灰框

注意 `State=1` 是在 Renderer 里**动态判断赋值**的（`skillCountInfo.State = 1`），而不是从外部预设。这意味着 `SkillCountInfo` 的 `State` 字段在填充后会被 Renderer 修改——同样是潜在的副作用问题，在多次调用时需要注意。

---

## 数据流：从战斗日志到统计界面

```
战斗进行中
    ↓
每次技能使用 → 战斗日志系统记录 SkillUsageLog
    ↓
战斗结束 → 触发 Evt_BattleSettlementEnd
    ↓
BattleStatisticsPanelDataHelper.GetBattleStatisticsPanelData(settleData)
    ↓
聚合计算：
    foreach (SkillUsageLog in settleData.SkillLogs)
    {
        if (!characterSkillMap.ContainsKey(log.CharacterId))
            characterSkillMap[log.CharacterId] = new Dictionary<int, int>();
        if (!characterSkillMap[log.CharacterId].ContainsKey(log.SkillId))
            characterSkillMap[log.CharacterId][log.SkillId] = 0;
        characterSkillMap[log.CharacterId][log.SkillId]++;
    }
    ↓
转换为 List<CharacterSkillCountInfo>
    ↓
BattleStatisticsPanel.OnOpen(data)
    ↓
UI 渲染（MatchUIElement + LoopScroll）
```

---

## CharacterItem：角色头像和出战编号

```csharp
public void SetData(int characterId, int num)
{
    // 出战编号 #1, #2, #3
    u_ComTextNumTextMeshProUGUI.text = ZString.Format("#{0}", num);
    
    // 加载角色立绘图标
    var characterConf = CfgManager.tables.TbCharacter.GetCharacterById(characterId);
    if (characterConf == null) return;
    
    u_ComImageCharacterIconImage
        .SetImageSpriteByIconStr(characterConf.Illustration, isSetNative: false)
        .Coroutine();
}
```

`ZString.Format("#{0}", num)` 用 ZString 避免字符串分配。`isSetNative: false` 说明这个图标不使用原生分辨率（会根据 UI 尺寸自动缩放），节省纹理内存。

---

## 关闭时的状态检查

```csharp
protected override async ETTask OnEventCloseAction()
{
    bool wasShown = RewindPanelState.IsShown;
    
    // 发布"结算结束"事件，可能触发回放界面打开
    await EventSystem.Instance.PublishAsync(YIUIComponent.ClientScene, 
        new Evt_BattleSettlementEnd { ViewData = _settlementData });
    
    // 如果事件处理后回放界面打开了，不关闭当前界面
    if (!wasShown && RewindPanelState.IsShown)
    {
        return;
    }
    
    Close();
}
```

这段代码展示了"事件可能改变关闭行为"的设计模式：

1. 记录`RewindPanel`的当前状态（`wasShown`）
2. 发布事件（可能触发回放界面打开）
3. 检查状态是否改变：如果发布事件后回放界面被打开了，当前统计界面就不需要关闭（用户会从回放界面跳转回来）

这避免了"用户点关闭→打开了回放界面→但统计界面也关了→回放结束后找不到统计界面"的问题。

---

## Buff/Token 分组的展示

```csharp
public void SetData(CharacterInfo characterInfo, List<SkillCountInfo> skillCountInfos)
```

`BattleStatisticsBuffTokenGroup` 展示角色在战斗中收集的 Buff 和 Token 总量：

```
角色1
├── 技能使用记录（水平循环列表）
│     [技能A×3] [技能B×1] [技能C×0 灰色] [  空  ] [  空  ]
└── Buff/Token 汇总（图标+数量）
      [专注×5] [格挡×3] [被动技能A×2]
```

Buff/Token 的展示让玩家理解"这场战斗的核心资源是什么"，加深对游戏机制的理解。

---

## 总结

战斗统计界面展示了多个重要工程实践：

1. **YIUIMatchUIElement**：数据列表和 UI 组件列表的自动匹配，数据驱动 UI
2. **降序排序**：`b.Count.CompareTo(a.Count)` 简洁地实现降序
3. **固定槽位填充**：`State=3` 空槽保证布局稳定，视觉整齐
4. **状态机渲染**：Renderer 中动态判断 `State=1`（有技能但未使用）
5. **副作用警告**：直接修改传入列表（`skillCountInfos.Add`）是设计债，实际项目中应复制一份操作
6. **关闭前事件检查**：关闭按钮点击后可能触发其他 UI 打开，需要检查状态再决定是否真的关闭
