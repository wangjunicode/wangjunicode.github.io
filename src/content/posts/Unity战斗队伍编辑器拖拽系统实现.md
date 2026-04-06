---
title: Unity战斗队伍编辑器拖拽系统实现
published: 2026-03-31
description: 深入解析战前队伍编辑界面中的拖拽换位系统，包含DragItem框架、战术技能卡片拖拽、成员交换逻辑及ECS组件式架构的完整实现。
tags: [Unity, UI系统, 拖拽系统, 战斗准备]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity战斗队伍编辑器拖拽系统实现

## 拖拽UI的设计挑战

队伍编辑器是战斗准备阶段最复杂的界面之一。玩家需要通过拖拽来：
- 调整队伍中角色的出场顺序
- 将战术技能（Tactic）拖入特定回合的技能槽
- 将战术技能从当前槽中拖出（移除）

这类拖拽操作的技术挑战：
1. **位置交换**：拖动A到B的位置时，B也需要自动移动到A的原位
2. **合法性验证**：并非所有拖拽都被允许（比如主角不能拖到位置0以外的地方）
3. **视觉反馈**：拖动过程中的半透明效果、目标位置的高亮
4. **ECS集成**：拖拽完成后需要通知游戏逻辑层更新战斗数据

---

## DragItem 框架概览

整个拖拽系统建立在 `DragItem` + `DragItemSlot` 框架上：

```
DragItem            — 可拖动的元素
DragItemSlot        — 放置目标（插槽）
DragItemGroup       — 一组关联的Slot（只能在同组内拖动）

// 事件回调
DragItem.OnPointDown       — 按下
DragItem.OnStartDrag       — 开始拖动
DragItem.OnReleaseToPool   — 放回池中

DragItemSlot.OnSlotFresh           — 插槽刷新
DragItemSlot.OnItemMoveInRange     — 被拖动物进入范围
DragItemSlot.OnItemLeaveRange      — 被拖动物离开范围
DragItemSlot.OnItemReleaseInRange  — 被拖动物在此松手
```

---

## 战术技能槽（TacticSlot）的初始化

```csharp
public static DragItem SetData(this Item_TacticSlot self, PassiveSkillInstance pSkill, 
    Transform ViewTrans, DragItemGroup group, RectTransform viewport, bool bInDrag)
{
    // 1. 确保 TacticItem 子组件存在
    if (self.item == null)
        self.item = self.AddChild<Item_TacticItem>(true);
    
    // 2. 配置 Slot
    self.slot = ViewTrans.GetComponent<DragItemSlot>();
    self.slot.Group = group;       // 绑定拖拽组（只能在同组slot间拖动）
    self.slot.ViewPort = viewport; // 视口范围限制
    self.slot.bCanReleaseItem = false;  // 默认不允许放入
    
    // 3. 处理 DragItem 的创建或复用
    self.GetView().u_ComRT_SizeRectTransform.localScale = Vector3.zero;
    DragItem dragItem = self.slot.curItem;
    if (dragItem == null)
    {
        var itemTrans = self.slot.CreateItem();  // 新建
        dragItem = itemTrans.GetComponent<DragItem>();
    }
    else
    {
        self.slot.ReinitItem();  // 复用：重置状态
    }
    
    // 4. 正在被拖动中的技能显示半透明
    self.GetView().u_ComRT_RootCanvasGroup.alpha = bInDrag ? 0.5f : 1f;
    
    // 5. 将 TacticItem 视图绑定到 DragItem 的 GameObject
    UIViewContainer<Item_TacticItem, TacticItemView>.SetView(self.item, 
        YIUIFactory.GetOrCreateCommon<TacticItemView>(dragItem.gameObject));
    
    // 6. 设置战术数据
    dragItem.gameObject.SetActive(true);
    self.item.SetData(pSkill);
    
    // 7. 配置可拖动性（已使用过的技能不可再拖动）
    dragItem.bCanDrag = !pSkill.bIvoked || !pSkill.bUnIvoked;
    
    // 8. 注册事件回调
    dragItem.OnReleaseToPool.RemoveAllListeners();
    dragItem.OnStartDrag.RemoveAllListeners();
    dragItem.OnStartDrag.AddListener(self.OnTacticDragStart);
    
    return dragItem;
}
```

**重点解析**：

`dragItem.bCanDrag = !pSkill.bIvoked || !pSkill.bUnIvoked`：
- `bIvoked`：技能是否已被激活（投入使用）
- `bUnIvoked`：技能是否已被撤回
- 只有"已激活且未撤回"的技能（正在生效中）才不可拖动
- 其他状态都可以拖动调整

这是一种用两个布尔值表达三种状态的技巧：

| bIvoked | bUnIvoked | 状态 | 可拖动 |
|---------|-----------|------|--------|
| false | false | 未使用 | ✓ |
| true | false | 使用中 | ✗ |
| true | true | 已撤回 | ✓ |

---

## 拖动开始的处理

```csharp
public static void OnTacticDragStart(this Item_TacticSlot self, DragItem item)
{
    // 移除本次拖动开始的监听（防止重复触发）
    item.OnStartDrag.RemoveAllListeners();
    
    // 保存当前的 logicItem，并将 self.item 清空
    // 原因：拖动中的技能不再属于这个 Slot，Slot 变为"空"
    var logicItem = self.item;
    self.item = null;
    
    // 通知父组件（TeamEditor）开始拖动
    var yiui_TeamEditorComponent = self.Parent as YIUI.TeamEditor.YIUI_TeamEditorComponent;
    yiui_TeamEditorComponent.OnTacticDragStartAcion?.Invoke(item, logicItem);
}
```

`self.item = null` 是关键操作——当用户开始拖动技能卡片时，这个 Slot 在逻辑上就"空"了。之后用户把卡片放到其他位置或放回此位置，都会触发相应的 `OnItemReleaseInRange` 回调。

---

## 队伍成员的拖拽换位

```csharp
public static void OnItemReleaseInRange(this Item_TeamMember self, DragItem item)
{
    var itemIdx = item.curSlot.transform.GetSiblingIndex();  // 被拖来的 item 的目标位置
    int idx = self.item.curSlot.transform.GetSiblingIndex(); // 我的当前位置
    
    // 合法性验证：主角(idx=0)不能随意换位
    bool canSwap = 
        (itemIdx != 0 || BattleAPI.IsMemberCanChangeIdx(self.targetTeam, self.targetUnit)) &&
        (idx != 0 || BattleAPI.IsMemberCanChangeIdx(self.targetTeam, 
            (item.extraObj as Item_TeamMember).targetUnit));
    
    if (canSwap)
    {
        // 交换两者的 SiblingIndex（即交换在父物体中的位置）
        item.curSlot.transform.SetSiblingIndex(idx);
        self.item.curSlot.transform.SetSiblingIndex(itemIdx);
        
        // 刷新双方的视觉状态
        self.UpdateOnStage();
        (item.extraObj as Item_TeamMember).UpdateOnStage();
    }
    
    // 无论是否交换成功，都隐藏"可放置"高亮
    self.GetView().u_ComW_InactiveCoverImage.gameObject.SetActive(false);
}
```

**`SiblingIndex` 交换是 UGUI 拖拽换位的核心技巧**：

在 UGUI 中，子物体的 `SiblingIndex` 决定它在父物体中的顺序（也是显示顺序）。通过互换两个 Slot 的 `SiblingIndex`，就实现了"视觉上交换位置"。

`item.extraObj = self` 是一个 object 类型的额外数据，用于在 DragItem 和对应的逻辑 Item 之间建立关联。当处理 `OnItemReleaseInRange` 时，可以通过 `item.extraObj as Item_TeamMember` 拿到被拖来的那个 Item 的逻辑对象，从而同时更新两方的状态。

---

## 进入/离开范围的高亮反馈

```csharp
public static void OnItemMoveInRange(this Item_TeamMember self, DragItem item)
{
    // 同样检查是否允许交换
    var itemIdx = item.curSlot.transform.GetSiblingIndex();
    int idx = self.item.curSlot.transform.GetSiblingIndex();
    
    if (canSwap(itemIdx, idx))
    {
        // 预览交换效果（实时跟随拖动更新）
        item.curSlot.transform.SetSiblingIndex(idx);
        self.item.curSlot.transform.SetSiblingIndex(itemIdx);
        self.UpdateOnStage();
        (item.extraObj as Item_TeamMember).UpdateOnStage();
    }
    else
    {
        // 高亮显示"不可放置"提示
        self.GetView().u_ComW_InactiveCoverImage.gameObject.SetActive(true);
    }
}
```

注意这里有一个有趣的设计：`OnItemMoveInRange` 就已经在做真正的位置交换，而不是等到 `OnItemReleaseInRange` 才交换！

这是"预览换位"的体验设计——当用户拖着 A 靠近 B 的位置时，A 和 B 已经预先互换了显示位置，让用户提前看到交换效果。如果用户松手，`OnItemReleaseInRange` 确认这次交换；如果用户移走，`OnItemLeaveRange` 还原到交换前的状态。

---

## 战术编辑器的回合暂停模式

```csharp
public static void OnPSkillPointDownAtRoundPause(this YIUI_TeamEditorComponent self, 
    PassiveSkillInstance pSkill)
{
    var BattleSpt = self.CurrentScene().GetComponent<BattleScriptComponent>();
    if (BattleSpt.waitRoundPauseTeamId != -1)  // 如果当前是回合暂停状态
    {
        int roundCnt = BattleAPI.GetTotalRoundNum(BattleSpt);
        int curRound = BattleSpt.CurRound - 1;  // 当前轮次（0-based）
        
        var teamSys = self.CurrentScene().GetComponent<TeamComponent>();
        var team = teamSys.GetMyTeam();
        var curRoundPSkill = BattleAPI.GetAt(BattleAPI.GetTacticSlot(team), curRound);
        bool bOldSkill = curRoundPSkill != null && curRoundPSkill.bIvoked && !curRoundPSkill.bUnIvoked;
        
        for (int i = 0; i < roundCnt; i++)
        {
            if (pSkill.bIvoked && !pSkill.bUnIvoked)
            {
                // 已激活的技能：只有当前回合的 Slot 可以放置（移除）
                self.TacticOnStageSlot[i].FreashCanRelease(curRound == i);
            }
            else
            {
                if (BattleAPI.SlotType(pSkill) == EPSkillSlotType.Tactic)
                {
                    // 战术类技能：不能覆盖"已有生效技能的回合"
                    self.TacticOnStageSlot[i].FreashCanRelease(!bOldSkill || curRound != i);
                }
                else
                {
                    // 非战术类技能：所有 Slot 都可放置
                    self.TacticOnStageSlot[i].FreashCanRelease(true);
                }
            }
        }
    }
}
```

"回合暂停模式"是战斗中的特殊状态：系统暂停等待玩家调整本回合的战术。此时只有"当前回合的槽位"才允许修改，其他轮次的槽位受限。

这种"情境相关的可交互性控制"是高质量战斗UI的重要特征，让界面在不同游戏阶段有正确的交互边界。

---

## ECS 与 UI 的桥接：Evt_ChangeTeamUnit

```csharp
public static void OnTeamMemberPointUp(this YIUI_TeamEditorComponent self, DragItem item)
{
    UIDOTweenEx doTweenMgr = item.transform.GetComponent<UIDOTweenEx>();
    doTweenMgr.PlayAnime("Release");  // 播放松手动画

    TeamComponent teamSys = self.CurrentScene().GetComponent<TeamComponent>();
    TeamEntity team = teamSys.GetMyTeam();
    int idx = item.curSlot.transform.GetSiblingIndex();  // 目标位置
    
    Item_TeamMember teamMember = self.TeamMemberDic[item];
    teamMember.parent.GetView().u_ComRT_BackUpRectTransform.gameObject.SetActive(false);
    
    int curIdx = BattleAPI.GetUnitIdx(team, teamMember.targetUnit);  // 当前位置
    
    // 确定主成员队伍代码
    int mainMemberTeamCode = -1;
    foreach (var teamLogicItem in self.TeamMember)
    {
        if (teamLogicItem.item.curSlot.transform.GetSiblingIndex() == 0)
        {
            mainMemberTeamCode = self.TeamMemberDic[teamLogicItem.item].targetUnit.TeamCode;
            break;
        }
    }
    
    // 发布事件：通知游戏逻辑层执行真正的队伍换位
    EventSystem.Instance.Publish(self.CurrentScene(), new Evt_ChangeTeamUnit() 
    { 
        team = team, 
        curIdx = curIdx, 
        targetIdx = idx,
        teamCode = mainMemberTeamCode
    });
}
```

**UI层与逻辑层的解耦关键点**：

UI层（`OnTeamMemberPointUp`）只负责：
1. 播放松手动画
2. 计算"从第几位换到第几位"
3. 发布 `Evt_ChangeTeamUnit` 事件

游戏逻辑层（监听 `Evt_ChangeTeamUnit` 的系统）负责：
1. 实际修改队伍数据
2. 广播 `Evt_TeamSortChange` 事件

HUD（`Item_HudTeamMemberSystem`）监听 `Evt_TeamSortChange`，播放换位动画。

整个流程：**UI操作 → UI事件 → 逻辑变更 → 逻辑事件 → HUD动画**，每层都有明确的职责边界。

---

## 动画序列的延迟触发

战术卡出现/退场时，多张卡片有序地依次播放动画（而不是同时弹出）：

```csharp
public static bool ShowAnime(this Item_TacticSlot self, int cnt, int idx, 
    UnityAction callBack, RectTransform rightlimit)
{
    if (self.NeedExitAnime())
    {
        // 基于曼哈顿距离计算延迟时间：离起点越远，延迟越长
        Vector2Int first = new Vector2Int(0, 2);
        if (cnt < 3) first.y = cnt - 1;

        Vector2Int slotIdx = new Vector2Int(idx / 3, idx % 3);
        float delayTime = 0.05f * (Mathf.Abs(slotIdx.x - first.x) + Mathf.Abs(slotIdx.y - first.y));
        
        UIDOTweenEx doTweenMgr = self.GetView().u_ComTacticSlotViewUIDOTweenEx;
        doTweenMgr.RegisterCompleteEvent("OnShow", callBack, true);
        doTweenMgr.PlayAnime("OnShow", -1, delayTime);  // 第三个参数是延迟
        return true;
    }
    return false;
}
```

**曼哈顿距离（Manhattan Distance）计算延迟**：

战术卡排列在一个 3×N 的网格中。从某个起始格开始，按照格子间的曼哈顿距离（横纵格数之和）递增延迟，产生"波浪式展开"的动画效果。

比如3×4格子，起始格(0,2)：
- (0,2): 0×0.05 = 0s（立即播放）
- (0,1): 1×0.05 = 0.05s
- (1,2): 1×0.05 = 0.05s  
- (1,1): 2×0.05 = 0.10s

---

## 总结

队伍编辑器的拖拽系统展示了几个重要的工程实践：

1. **事件驱动的 UI-逻辑解耦**：UI 操作发布事件，逻辑层订阅响应，互不依赖
2. **SiblingIndex 实现位置交换**：UGUI 中最简洁的换位方案
3. **预览式交互**：进入范围就预览效果，提升用户体验
4. **情境化交互限制**：根据游戏状态动态控制哪些槽位可交互
5. **曼哈顿距离动画序列**：简单的数学公式产生自然的波浪动画效果
