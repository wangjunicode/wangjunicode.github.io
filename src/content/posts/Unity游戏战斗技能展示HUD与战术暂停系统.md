---
title: Unity游戏战斗技能展示HUD与战术暂停系统
published: 2026-03-31
description: 深度解析战斗中技能激活/触发的可视化反馈系统，包含双队伍技能组件刷新、回合边界动画触发逻辑及战术调整暂停计时器的完整实现。
tags: [Unity, UI系统, 战斗HUD, 技能系统]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity游戏战斗技能展示HUD与战术暂停系统

## 战斗HUD的信息密度挑战

战斗中的技能展示 HUD 需要在不打扰玩家注意力的前提下，实时反映战场上发生的每个技能激活、触发、切换事件。

`SkillDisplayHudPanel` 管理着双队技能展示板，`TacticHudPanel` 则负责战术调整暂停阶段的倒计时和队伍编辑器入口。

---

## SkillDisplayHudPanel 的双队技能刷新

```csharp
void RefreshSkills()
{
    var teamComp = YIUIComponent.ClientScene.CurrentScene().GetComponent<TeamComponent>();
    u_UIPanel_SkillGroup.Show(teamComp.GetMyTeam(), false);   // 我方（不镜像）
    u_UIPanel_SkillGroupR.Show(teamComp.GetOpponentTeam(), true); // 敌方（镜像翻转）
}
```

系统维护了两个 `Panel_SkillGroup` 实例（左边/右边），分别对应我方和对手方队伍。`false`/`true` 参数控制是否镜像翻转——与之前 HUD 角色卡片的左右镜像一样的设计哲学。

`RefreshSkills` 在三种情况下被调用：
1. `OnOpen`：面板初始打开时
2. `Evt_TeamSortChange`：队伍换位时（主角/副角交换，技能显示也要重排）
3. `Evt_TeamResetPSkill`：被动技能重置时

---

## 双标志位控制动画触发

```csharp
bool isEnable = true;   // 面板是否可见
bool roundStart = false; // 回合是否已开始

void TriggerShowAnim()
{
    // 只有"面板可见"且"回合已开始"才播放显示动画
    if (isEnable && roundStart)
    {
        u_ComSkillDisplayHudPanelAnimator
            .PlayAndWaitAnimation(UIAnimNameDefine.ShowHash).Coroutine();
    }
}
```

这两个标志位解决了一个时序问题：

**场景**：回合开始时（`OnRoundStart`），`roundStart = true`，调用 `TriggerShowAnim`。但如果此时面板被某个全屏 UI 遮住了（`isEnable = false`），不应该播放动画（因为玩家看不到）。

同样地，当被遮住的面板重新显示（`OnEnable` → `isEnable = true`），调用 `TriggerShowAnim`，这时如果回合还在进行中（`roundStart = true`），才补播显示动画。

这是**双条件门控**的经典应用——两个独立的条件都满足，才执行操作。

---

## 技能触发的路由分发

```csharp
void OnEvt_BattleSkillUIItemSwitch(Evt_BattleSkillUIItemSwitch evt)
{
    var unit = evt.entity as Unit;
    if (unit == null) return;
    
    var teamSys = YIUIComponent.ClientScene.CurrentScene().GetComponent<TeamComponent>();
    if (teamSys == null) return;
    
    var team = BattleAPI.GetTeamByUnit(teamSys, unit);
    var myTeam = teamSys.GetMyTeam();
    
    // 根据单位所属队伍，路由到正确的技能组
    if (team == myTeam)
        u_UIPanel_SkillGroup.TriggerSkill(true, state, skillId, skillLv, team, unit);
    else
        u_UIPanel_SkillGroupR.TriggerSkill(false, state, skillId, skillLv, team, unit);
}
```

战斗事件不包含"这是哪边的技能"这一信息，只有"哪个单位（Unit）的技能"。代码通过 `BattleAPI.GetTeamByUnit` 反向查询单位所属队伍，再与 `GetMyTeam()` 对比，确定是我方还是敌方的技能触发。

这是一个"数据查询替代直接标记"的设计：事件里不存队伍ID，通过接口查询，保持事件数据结构简洁。

---

## TacticHudPanel：战术暂停倒计时

```csharp
public class TacticHudPanel : TacticHudPanelBase, IYIUIUpdate
{
    public float cdTime;      // 总倒计时时长
    public float restTime;    // 剩余时间
    public bool bCountDown = false;  // 是否正在倒计时
```

`IYIUIUpdate` 接口让框架在每帧调用 `OnUpdate`，用于更新倒计时：

```csharp
public void OnUpdate()
{
    if (!bCountDown) return;
    
    restTime -= Time.deltaTime;
    
    if (restTime <= 0)
    {
        restTime = 0;
        bCountDown = false;
        OnCountDownEnd();
    }
    
    // 更新进度条（0~1）
    float progress = Mathf.Clamp01(restTime / cdTime);
    u_ComTimerCircleImage.fillAmount = progress;
    
    // 最后3秒的警示（闪烁/变红）
    if (restTime <= 3f && !isWarning)
    {
        isWarning = true;
        u_ComTacticHudPanelAnimator.Play("TimerWarning");
    }
}
```

`IYIUIUpdate` 比 `MonoBehaviour.Update` 的好处：框架统一管理哪些面板需要 Update，可以在全局暂停时批量停止所有 Update，而不需要每个面板自己检查暂停状态。

---

## 剧情与战术暂停的协调

战术暂停阶段可能触发战前/战后剧情，需要协调剧情播放和战术编辑器的顺序：

```csharp
public void OnTeamEditorClose(Evt_CloseTeamEditor argv)
{
    if (postStoryID != 0)
    {
        // 战术编辑器关闭后，如果有战后剧情，先播放剧情
        waitStory = postStoryID;
        bPreStroy = false;
        var storyComponent = YIUIComponent.ClientScene.GetComponent<StoryComponent>();
        storyComponent.DisposeLogicStorys(postStoryID);
        storyComponent.LoadAndStartStoryLogic(new(postStoryID)).Coroutine();
    }
}

public void OnStoryEnd(Evt_OnStoryGraphFinished argv)
{
    if (argv.StoryID == waitStory)
    {
        waitStory = 0;
        if (bPreStroy)
        {
            // 战前剧情结束 → 打开战术编辑器
            OpenUI();
        }
        else
        {
            // 战后剧情结束 → 恢复战斗
            var battleComp = YIUIComponent.ClientScene.CurrentScene().GetComponent<BattleComponent>();
            BattleAPI.Resume(battleComp);
        }
    }
}
```

这里维护了两个状态：
- `preStoryID`：战术暂停前要播的剧情
- `postStoryID`：战术编辑器关闭后要播的剧情
- `bPreStroy`：标记当前是战前还是战后剧情

当战前剧情结束（`argv.StoryID == preStoryID` 且 `bPreStroy = true`），才开启队伍编辑器。战术编辑器关闭后，如果有战后剧情就播放，播完才恢复战斗继续。

这是一个"剧情 → 战术 → 剧情 → 战斗"的序列化状态机，`waitStory` 是关键控制变量：不等于0说明"正在等某个剧情结束"，等于0说明"没有等待中的剧情"。

---

## 战术变更的状态机

```csharp
void OnTacticChangeStatusChanged(Evt_TacticChangeStatusChanged argv)
{
    switch (argv.NewStatus)
    {
        case ETacticChangeStatus.Start:
            StartTacticCountdown(argv);
            break;
        case ETacticChangeStatus.End:
            EndTacticCountdown();
            break;
        case ETacticChangeStatus.Cancel:
            CancelTacticCountdown();
            break;
    }
}

void StartTacticCountdown(Evt_TacticChangeStatusChanged argv)
{
    bCountDown = true;
    cdTime = argv.TimeoutMs / 1000f;
    restTime = cdTime;
    isWarning = false;
    
    // 显示编辑按钮
    u_ComW_EditeTeamButton.gameObject.SetActive(argv.ShowEditBtn);
    
    // 播放战术 HUD 出现动画
    u_ComTacticHudPanelAnimator.Play(showHash);
}
```

战术变更状态机有三个状态：Start（开始计时）、End（时间到自然结束）、Cancel（被外部取消）。

每个状态都有对应的 UI 响应：
- Start → 显示倒计时 + 编辑按钮 + 播放出现动画
- End → 倒计时归零 + 隐藏面板 + 恢复战斗
- Cancel → 静默关闭，不需要额外逻辑

---

## 等待剧情期间的视觉遮挡

```csharp
u_ComWaitingBGRectTransform.gameObject.SetActive(false);  // 初始隐藏

// 开始等待剧情时显示
void WaitForStory(int storyId)
{
    waitStory = storyId;
    u_ComWaitingBGRectTransform.gameObject.SetActive(true);
}

// 剧情结束后隐藏
public void OnStoryEnd(Evt_OnStoryGraphFinished argv)
{
    if (argv.StoryID == waitStory)
    {
        waitStory = 0;
        u_ComWaitingBGRectTransform.gameObject.SetActive(false);
        // ...
    }
}
```

`u_ComWaitingBGRectTransform` 是一个半透明遮罩——在等待剧情期间显示，防止玩家点击战术按钮（战术编辑器在剧情期间不可交互）。剧情结束后隐藏，恢复正常交互。

---

## 总结

战斗技能 HUD 和战术暂停系统展示了：

1. **双标志位门控**：`isEnable && roundStart` 确保动画只在正确时机触发
2. **查询替代标记**：通过 `GetTeamByUnit` 确定队伍归属，而不是在事件里附带队伍标记
3. **序列化状态机**：`waitStory` + `bPreStroy` 管理剧情-战术的时序关系
4. **IYIUIUpdate**：框架统一的逐帧更新，可全局暂停管理
5. **视觉遮挡保护**：剧情期间显示遮罩，阻止不应该响应的交互
