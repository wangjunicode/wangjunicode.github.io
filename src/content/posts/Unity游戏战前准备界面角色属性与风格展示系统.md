---
title: Unity游戏战前准备界面角色属性与风格展示系统
published: 2026-03-31
description: 深入解析战前准备界面的多Tab切换、角色逻辑评分五档状态机展示、属性分类分组、风格/技能信息及角色关系连接线可视化的完整实现。
tags: [Unity, UI系统, 战前准备, 角色属性]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏战前准备界面角色属性与风格展示系统

## 战前准备界面的信息密度

战前准备界面（BattlePreparePanel）在每场战斗开始前展示当前角色的详细信息，供玩家做战术决策。界面需要展示：
- 角色逻辑值（核心评分）及评级（E/D/C/B/A/S）
- 多类属性数值（攻击、防御、克制、弱点）
- 角色风格/皮肤信息
- 角色爱好（Hobbies）
- 角色关系连接线（队伍成员间的关系）

`BattlePreparePanel` 通过三个 Tab（属性/爱好/风格）组织这些信息。

---

## 多版本 OnOpen 设计

```csharp
public sealed partial class BattlePreparePanel : BattlePreparePanelBase, 
    IYIUIOpen,              // 无参数打开
    IYIUIOpen<bool>,        // bool=是否直接显示风格 Tab
    IYIUIOpen<Action>,      // 带关闭回调
    IYIUIOpen<Action, bool> // 关闭回调 + 是否隐藏爱好 Tab
```

四个版本的 `OnOpen` 应对了不同的打开场景：
- 从队伍编辑器进入：无参数
- 从新手引导进入：直接显示风格 Tab（`bool=true`）
- 从其他功能界面进入：带关闭回调（关闭时通知来源界面）
- 特殊模式（雇佣角色等）：带关闭回调 + 隐藏爱好 Tab

---

## 逻辑评分五档状态机

```csharp
if (!CultivationUtil.TryGetAttributeGrade(EAttributeType.Logic, characterLogic, out var _grade))
{
    u_ComItem_LogicSkillScoreUIStateBinder.gameObject.SetActive(false);
}
else
{
    u_ComTxt_ValueTextMeshProUGUI.SetText(characterLogic);
    u_ComTxt_LevelTextMeshProUGUI.SetText(_grade.Name);
    switch (_grade.GradeType)
    {
        case EAttributeGradeType.E:  u_ComItem_LogicSkillScoreUIStateBinder.ApplyState(0); break;
        case EAttributeGradeType.D:
        case EAttributeGradeType.D_PLUS:  u_ComItem_LogicSkillScoreUIStateBinder.ApplyState(1); break;
        case EAttributeGradeType.C:
        case EAttributeGradeType.C_PLUS:  u_ComItem_LogicSkillScoreUIStateBinder.ApplyState(2); break;
        case EAttributeGradeType.B:
        case EAttributeGradeType.B_PLUS:  u_ComItem_LogicSkillScoreUIStateBinder.ApplyState(3); break;
        case EAttributeGradeType.A:
        case EAttributeGradeType.A_PLUS:  u_ComItem_LogicSkillScoreUIStateBinder.ApplyState(4); break;
        case EAttributeGradeType.S:
        case EAttributeGradeType.SS:      u_ComItem_LogicSkillScoreUIStateBinder.ApplyState(5); break;
    }
}
```

**D 和 D_PLUS 映射到同一状态（1）** 是视觉设计决策——"D-" 和 "D+" 在视觉上用相同的图标/颜色表示，不需要细分。同样 A_PLUS 和 A 共用状态 4，S 和 SS 共用状态 5。

这样状态机只有 6 个状态（E/D/C/B/A/S），而评级枚举有 11 个值，switch 中的合并映射起到了"合并同类视觉"的作用。

---

## 属性分组动态布局

```csharp
int normalIdx = 0;   // 普通属性位置索引
int bonusIdx = 0;    // 加成属性位置索引
int againstIdx = 0;  // 克制属性位置索引

for (int i = 0; i < u_ComAttrRootRectTransform.childCount; i++)
{
    u_ComAttrRootRectTransform.GetChild(i).gameObject.SetActive(false);
}

foreach (var attriData in attriDataList)
{
    switch (attriData.Type)
    {
        case EAttrType.Normal:
            if (normalIdx < u_ComNormalAttriRootRectTransform.childCount)
            {
                var normal = u_ComNormalAttriRootRectTransform.GetChild(normalIdx);
                normal.gameObject.SetActive(true);
                var normalComp = normal.GetComponent<Item_AttriValue>();
                normalComp.SetData(attriData);
                normalIdx++;
            }
            break;
        case EAttrType.Bonus:
            // 类似...
        case EAttrType.Against:
            // 类似...
    }
}
```

属性被分为三类，分别放在三个不同的布局容器里（`NormalAttriRoot`、`BonusAttriRoot` 等）。与第一篇弹幕系统里"先全隐再按需显示"的思路一样：

**先全部隐藏**（所有子节点 `SetActive(false)`）→ **按需激活**（只激活有数据的那些）

这比"不够就创建，多了就删除"的方案：
- 性能更好（只有 SetActive 切换，不需要 Instantiate/Destroy）
- 代码更简单（不需要管理动态列表）
- 但适用前提：属性数量有上限，预设了足够的子节点

---

## 角色关系连接线可视化

队伍成员间有关系（对手/陌生人/朋友/知己），连接线颜色区分：

```csharp
public static readonly Color ColorCharacterRelationRival = new Color32(255, 102, 116, 255);   // 红：对手
public static readonly Color ColorCharacterRelationStranger = new Color32(185, 129, 255, 255); // 紫：陌生
public static readonly Color ColorCharacterRelationFriend = new Color32(114, 213, 200, 255);   // 青：朋友
public static readonly Color ColorCharacterRelationConfidant = new Color32(255, 135, 223, 255);// 粉：知己
```

连接线的绘制逻辑：

```csharp
void SetRelationLines()
{
    var team = curTeam;
    var members = BattleAPI.GetTeamMembers(team);
    
    // 对队伍中的每对成员，检查关系
    for (int i = 0; i < members.Count; i++)
    {
        for (int j = i + 1; j < members.Count; j++)
        {
            var relation = BattleAPI.GetCharacterRelation(members[i], members[j]);
            Color lineColor;
            switch (relation)
            {
                case ECharacterRelation.Rival:     lineColor = ColorCharacterRelationRival; break;
                case ECharacterRelation.Friend:    lineColor = ColorCharacterRelationFriend; break;
                case ECharacterRelation.Confidant: lineColor = ColorCharacterRelationConfidant; break;
                default:                           lineColor = ColorCharacterRelationStranger; break;
            }
            
            // 在两个角色头像之间画线（i,j 对应预设的线条GameObject）
            int lineIdx = GetLineIdx(i, j, members.Count);
            if (lineIdx < _lineList.Count)
            {
                _lineList[lineIdx].color = lineColor;
                _lineList[lineIdx].gameObject.SetActive(true);
            }
        }
    }
}
```

`GetLineIdx(i, j, n)` 将二维索引对 (i,j) 映射到一维线条列表的索引：

对于3人队伍（0,1,2），三条连接线分别是：(0,1)→0, (0,2)→1, (1,2)→2。

---

## Tab 切换的统一处理

```csharp
// 自定义 Toggle 外观（Unity Toggle 组件不提供双子节点切换）
public void FreshToggleState(Toggle tog, bool isOn)
{
    var OnBG = tog.transform.Find("OnBG");    // 选中态背景
    var OffBG = tog.transform.Find("OffBG");  // 未选中态背景
    var cn = tog.transform.Find("btn_Chinese").GetComponent<TextMeshProUGUI>();
    var eng = tog.transform.Find("btn_English").GetComponent<TextMeshProUGUI>();
    
    if (isOn)
    {
        OnBG.gameObject.SetActive(true);
        OffBG.gameObject.SetActive(false);
        cn.color = new Color(87f/255f, 83f/255f, 107f/255f, 1);  // 深色文字（白背景上）
    }
    else
    {
        OnBG.gameObject.SetActive(false);
        OffBG.gameObject.SetActive(true);
        cn.color = Color.white;  // 白色文字（深色背景上）
    }
}
```

**为什么不用 Unity Toggle 的 Graphic 机制**（设置目标 Graphic 自动切换颜色）？

因为这个 Tab 的选中/未选中状态需要切换两个背景节点（OnBG 和 OffBG），同时还要切换文字颜色。Unity Toggle 的 Graphic 机制只能控制一个目标的颜色，不满足需求，所以手写了 `FreshToggleState` 来精确控制。

Tab 切换时播放对应的 Animator 动画（`"pnl_Property"`、`"pnl_Hobbies"`、`"pnl_Style"`）：

```csharp
public void PropertyToggleValueChange(bool isOn)
{
    FreshToggleState(u_ComBtn_PropertyToggle, isOn);
    if (isOn)
    {
        u_ComBattlePreparePanelAnimator
            .PlayAndWaitAnimationEnd(Animator.StringToHash("pnl_Property"))
            .Coroutine();  // 不等待，并行播放
        
        // 切换显示的面板
        u_ComPnl_HobbiesRectTransform.gameObject.SetActive(false);
        u_ComPnl_PropertyRectTransform.gameObject.SetActive(true);
        u_ComPnl_StyleRectTransform.gameObject.SetActive(false);
    }
    VGameAudioManager.Instance.PlaySound(Play_ui_batttle_common_tab_switch_midle);
}
```

注意 `.Coroutine()` 让动画并行播放（不等待），面板切换是同步的（立即 SetActive），动画在后台播放。这避免了"Tab 切换时有一段黑屏等待动画"的体验问题。

---

## 雇佣角色的特殊处理

```csharp
var chessConf = CfgManager.tables.TbChess.GetOrDefault(chessID);
bMercenary = chessConf.Type == ECellType.FakeCharacter;

if (bMercenary || IsFakeBattle() || comp.DungeonType == EDungeonType.CharacterRoom)
{
    u_ComBtn_HobbiesToggle.gameObject.SetActive(false);  // 隐藏爱好 Tab
}
else
{
    InitHobbiesPnl();  // 正常角色才有爱好系统
}
```

"爱好"系统只对真实角色有意义，雇佣角色（`FakeCharacter`）、假战斗（`IsFakeBattle`）或角色展示房间（`CharacterRoom`）都不显示爱好 Tab。这种条件判断让 UI 根据上下文自动调整展示内容，而不是每个使用场景单独写一套界面。

---

## 时间埋点

```csharp
private void LogOpenTime()
{
    var playerComp = YIUIComponent.ClientScene.GetComponent<PlayerComponent>();
    if (playerComp.bFromLogin)  // 只有"从登录进来"的玩家才记录
    {
        var comp = YIUIComponent.ClientScene.GetComponent<DataAnalysisComponent>();
        comp.OpenPanelTimeLog();  // 记录面板开始时间
    }
}

protected override void OnClose()
{
    base.OnClose();
    var playerComp = YIUIComponent.ClientScene.GetComponent<PlayerComponent>();
    if (playerComp.bFromLogin)
    {
        var comp = YIUIComponent.ClientScene.GetComponent<DataAnalysisComponent>();
        comp.ClosePanelTimeLog(ResName);  // 计算停留时长，上报分析
    }
}
```

`DataAnalysisComponent` 是数据分析组件，记录玩家在各个界面的停留时长。`bFromLogin` 限定只记录"正常游戏流程"进入的情况（排除 QA 测试、GM 直接跳转等情况，避免数据污染）。

---

## 总结

战前准备界面展示了复杂信息展示 UI 的工程实践：

1. **多版本 OnOpen**：不同调用场景对应不同参数版本，保持接口清晰
2. **评级折叠映射**：11个枚举值折叠到6个视觉状态，减少设计工作量
3. **先隐再显布局**：所有子节点先 SetActive(false)，按需激活
4. **颜色枚举常量**：关系颜色定义为静态常量，语义清晰，易于维护
5. **并行动画**：Tab 切换动画用 `.Coroutine()` 并行，避免切换卡顿
6. **条件功能展示**：根据角色类型/场景类型动态显示/隐藏 Tab
7. **数据埋点**：面板开关时记录时长，条件过滤保证数据质量
