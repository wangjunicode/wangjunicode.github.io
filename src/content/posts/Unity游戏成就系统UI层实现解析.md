---
title: Unity游戏成就系统UI层实现解析
published: 2026-03-31
description: 深入解析成就系统的分类展示、进度追踪、奖励领取的完整UI层实现，包含成就列表的分组管理、进度条更新及红点驱动机制。
tags: [Unity, UI系统, 成就系统, 进度追踪]
category: Unity技术
draft: false
encryptedKey:henhaoji123
---

# Unity游戏成就系统UI层实现解析

## 成就系统的产品价值与技术挑战

成就系统（Achievement System）是现代游戏的标配功能，它的产品价值在于：
- 为玩家提供短中长期目标（增加游戏深度）
- 记录玩家的游戏历程（满足收藏欲）
- 引导玩家探索游戏内容（降低流失）

从技术角度，成就 UI 的挑战在于：
1. **数量庞大**：成就条目可达数百条，需要分类管理和高效渲染
2. **状态复杂**：未解锁/进行中/已完成/已领取奖励，四种状态
3. **进度实时性**：玩家进行游戏时，成就进度需要实时更新
4. **异步操作**：领取奖励需要等待服务器确认

---

## 成就数据模型

```csharp
public class AchievementData
{
    public int ID;                    // 成就ID
    public int GroupId;               // 成就分组ID（用于分类展示）
    public string Name;               // 成就名称
    public string Description;        // 成就描述
    public int Type;                  // 成就类型（常规/限时/每日等）
    
    // 进度信息
    public int CurrentProgress;       // 当前进度值
    public int TotalProgress;         // 完成所需进度
    
    // 状态
    public EAchievementStatus Status; // 0=未开始 1=进行中 2=已完成 3=已领取
    
    // 奖励
    public List<AwardItem> Awards;    // 奖励列表
    
    // 附加信息
    public bool IsNew;                // 是否新解锁（用于高亮显示）
    public long CompletedTime;        // 完成时间戳
}

public enum EAchievementStatus
{
    NotStarted = 0,   // 未开始（进度为0）
    InProgress = 1,   // 进行中
    Completed = 2,    // 已完成但未领取奖励
    Rewarded = 3      // 已领取奖励
}
```

**状态分离**是成就数据模型的关键设计——"已完成"和"已领取"是两个不同的状态。这允许 UI 在奖励未领取时持续展示提醒（红点）。

---

## 成就分组管理

```csharp
[EntitySystem]
private static void Awake(this YIUI_AchievementComponent self)
{
    self.AllAchievements = new List<AchievementData>();
    self.GroupedAchievements = new Dictionary<int, List<AchievementData>>();
    self.CurrentGroupId = -1;
}

public static void SetAchievements(this YIUI_AchievementComponent self, 
    List<AchievementData> achievements)
{
    self.AllAchievements.Clear();
    self.GroupedAchievements.Clear();
    
    foreach (var achievement in achievements)
    {
        self.AllAchievements.Add(achievement);
        
        // 按 GroupId 分组
        if (!self.GroupedAchievements.ContainsKey(achievement.GroupId))
            self.GroupedAchievements[achievement.GroupId] = new List<AchievementData>();
        
        self.GroupedAchievements[achievement.GroupId].Add(achievement);
    }
    
    // 按完成状态排序：未完成的在前，已完成未领取的在中间，已领取的在最后
    foreach (var group in self.GroupedAchievements.Values)
    {
        group.Sort(SortAchievement);
    }
}

private static int SortAchievement(AchievementData a, AchievementData b)
{
    // 未领取的已完成成就（有待领奖励）最优先
    bool aHasPendingReward = a.Status == EAchievementStatus.Completed;
    bool bHasPendingReward = b.Status == EAchievementStatus.Completed;
    if (aHasPendingReward != bHasPendingReward)
        return aHasPendingReward ? -1 : 1;
    
    // 其次按进度降序（快完成的排前面，有激励感）
    float aProgress = a.TotalProgress > 0 ? (float)a.CurrentProgress / a.TotalProgress : 0;
    float bProgress = b.TotalProgress > 0 ? (float)b.CurrentProgress / b.TotalProgress : 0;
    if (Mathf.Abs(aProgress - bProgress) > 0.001f)
        return bProgress > aProgress ? 1 : -1;
    
    // 最后按ID排序（保证稳定排序）
    return a.ID.CompareTo(b.ID);
}
```

排序策略的产品逻辑：
- 有奖励可领的排最前 → 提醒玩家去领奖
- 快完成的（进度高的）排前面 → 让玩家感受到"快了"的激励
- 已全部完成的分组排最后 → 减少视觉干扰

---

## 分组标签切换的数据流

```csharp
public static void OnGroupTabSelected(this YIUI_AchievementComponent self, int groupId)
{
    if (self.CurrentGroupId == groupId) return;  // 防止重复切换
    
    self.CurrentGroupId = groupId;
    
    // 获取当前分组的成就列表
    List<AchievementData> groupAchievements;
    if (groupId == -1)
    {
        // -1 代表"全部"标签
        groupAchievements = self.AllAchievements;
    }
    else if (self.GroupedAchievements.TryGetValue(groupId, out var list))
    {
        groupAchievements = list;
    }
    else
    {
        groupAchievements = new List<AchievementData>();
    }
    
    // 通知视图层刷新列表
    EventSystem.Instance.Publish(YIUIComponent.ClientScene,
        new Evt_Achievement_GroupChanged()
        {
            GroupId = groupId,
            Achievements = groupAchievements
        });
}
```

注意 `groupId == -1` 代表"全部"分组。这是一种常见的"虚拟分组"技巧——`-1` 不对应配置表中的任何真实分组，只是代码层面的"显示全部"语义。

---

## 成就进度实时更新

```csharp
[Event(SceneType.Client)]
public class AchievementProgressUpdatedHandler : AEvent<Evt_AchievementProgressUpdated>
{
    protected override void Run(Scene scene, Evt_AchievementProgressUpdated evt)
    {
        var comp = YIUIComponent.Instance.GetUIComponent<YIUI_AchievementComponent>();
        if (comp == null) return;
        
        // 查找并更新对应成就
        foreach (var achievement in comp.AllAchievements)
        {
            if (achievement.ID == evt.AchievementId)
            {
                var oldStatus = achievement.Status;
                achievement.CurrentProgress = evt.NewProgress;
                
                // 检查是否刚好达成
                if (achievement.TotalProgress > 0 
                    && achievement.CurrentProgress >= achievement.TotalProgress
                    && oldStatus < EAchievementStatus.Completed)
                {
                    achievement.Status = EAchievementStatus.Completed;
                    achievement.CompletedTime = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                    achievement.IsNew = true;  // 标记为新解锁
                    
                    // 显示成就解锁弹窗
                    ShowAchievementUnlockPopup(achievement);
                    
                    // 更新红点（有奖励未领）
                    RedDotMgr.Inst?.SetCount((int)ERedDotKeyType.Achievement, 
                        GetPendingRewardCount(comp));
                }
                
                // 刷新当前显示的成就条目
                if (IsAchievementVisible(comp, achievement))
                {
                    EventSystem.Instance.Publish(scene,
                        new Evt_Achievement_ItemRefresh() { AchievementId = evt.AchievementId });
                }
                
                break;
            }
        }
    }
}
```

**"达成即标记 IsNew"** 是一个重要的设计——新解锁的成就在列表中会有特殊高亮效果，让玩家一眼看到。当玩家点击查看该成就后，`IsNew = false`，高亮消失。

---

## 成就进度条的计算与显示

```csharp
public static AchievementItemViewData BuildItemViewData(this YIUI_AchievementComponent self, 
    AchievementData achievement)
{
    float progressPercent = achievement.TotalProgress > 0
        ? Mathf.Clamp01((float)achievement.CurrentProgress / achievement.TotalProgress)
        : 0f;
    
    // 进度文本格式化
    string progressText;
    if (achievement.Status >= EAchievementStatus.Completed)
    {
        progressText = "已完成";
    }
    else if (achievement.TotalProgress <= 1)
    {
        // 单步成就（做了/没做）
        progressText = achievement.CurrentProgress > 0 ? "进行中" : "未开始";
    }
    else
    {
        // 多步成就（显示数值进度）
        progressText = ZString.Format("{0}/{1}", achievement.CurrentProgress, achievement.TotalProgress);
    }
    
    return new AchievementItemViewData
    {
        ID = achievement.ID,
        Name = achievement.Name,
        Description = achievement.Description,
        ProgressPercent = progressPercent,
        ProgressText = progressText,
        CanClaim = achievement.Status == EAchievementStatus.Completed,  // 可以领取
        HasClaimed = achievement.Status == EAchievementStatus.Rewarded, // 已领取
        IsNew = achievement.IsNew,
        Awards = achievement.Awards
    };
}
```

**多步成就的进度格式化**是细节——`"5/10"` 比 `"50%"` 在成就场景下更直观，因为玩家想知道"还差几步"而不是百分比。

---

## 奖励领取的异步处理

```csharp
public static async ETTask ClaimReward(this YIUI_AchievementComponent self, int achievementId)
{
    // 防重复点击保护
    if (self.IsClaimingReward)
    {
        Log.Warning("[Achievement] 正在领取奖励中，请勿重复点击");
        return;
    }
    self.IsClaimingReward = true;
    
    try
    {
        var req = new ZoneAchievementClaimReq { AchievementId = achievementId };
        var result = await YIUIComponent.ClientScene.GetComponent<NetworkComponent>()
            .SendAsync<ZoneAchievementClaimResp>((uint)ZoneClientCmd.ZoneCsAchievementClaim, req);
        
        if (result.IsCompleteSuccess && result.Data.RetInfo?.RetCode == 0)
        {
            // 更新本地状态
            var achievement = self.AllAchievements.Find(a => a.ID == achievementId);
            if (achievement != null)
            {
                achievement.Status = EAchievementStatus.Rewarded;
                achievement.IsNew = false;
                
                // 刷新排序（已领取的下沉到列表底部）
                if (self.CurrentGroupId != -1 && self.GroupedAchievements.TryGetValue(
                    self.CurrentGroupId, out var group))
                    group.Sort(SortAchievement);
            }
            
            // 更新红点计数
            int pendingCount = self.GetPendingRewardCount();
            RedDotMgr.Inst?.SetCount((int)ERedDotKeyType.Achievement, pendingCount);
            
            // 刷新 UI
            EventSystem.Instance.Publish(YIUIComponent.ClientScene,
                new Evt_Achievement_ItemRefresh() { AchievementId = achievementId });
            
            // 显示奖励获得提示
            AwardIssueHelper.ShowAwards(result.Data.Awards);
        }
        else
        {
            UIHelper.ShowTips($"领取失败：{result.Data?.RetInfo?.RetCode}");
        }
    }
    finally
    {
        self.IsClaimingReward = false;  // 无论成败，都要解除锁
    }
}
```

**`try/finally` 确保解锁**是很重要的工程实践。如果领取过程中抛出异常（网络断开、服务器异常），`finally` 中的 `IsClaimingReward = false` 保证了"防重复点击锁"一定会被解除，不会导致按钮永远不可点击。

---

## 成就解锁弹窗

```csharp
private static void ShowAchievementUnlockPopup(AchievementData achievement)
{
    // 成就解锁使用专用的Toast式弹窗（而不是阻断性弹窗）
    // 因为成就解锁可能在任何时候触发，不能打断玩家的游戏操作
    ToastManager.Instance.ShowAchievementUnlock(new AchievementToastData
    {
        Name = achievement.Name,
        Icon = achievement.Description,
        Duration = 3f  // 3秒后自动消失
    });
}
```

成就解锁弹窗选用 **Toast 而不是弹窗**，理由：
- 成就解锁是游戏过程中的惊喜，不应该打断游戏
- 不需要玩家做任何操作（不需要确认）
- 3秒自动消失，不影响游戏体验

如果成就奖励丰厚（稀有道具），可以升级为半阻断式弹窗（不完全阻断，但屏幕中央显示）。

---

## 待领取奖励计数（驱动红点）

```csharp
public static int GetPendingRewardCount(this YIUI_AchievementComponent self)
{
    return self.AllAchievements.Count(a => a.Status == EAchievementStatus.Completed);
}
```

这个方法返回"已完成但未领取奖励的成就数量"，直接用 LINQ 的 `Count` 过滤。这个数量就是红点上显示的数字，也是红点显示/隐藏的依据。

每次成就状态变化（完成/领取）后都会调用这个方法更新红点：

```csharp
RedDotMgr.Inst?.SetCount((int)ERedDotKeyType.Achievement, self.GetPendingRewardCount());
```

---

## 总结

成就系统 UI 层的设计展示了以下工程要点：

1. **状态机**：四种明确的成就状态，每种状态对应不同的 UI 表现
2. **排序策略**：数据层排好序，视图层直接渲染，分离关注点
3. **红点驱动**：完成/领取事件触发红点计数更新，完全解耦
4. **防重复操作**：`IsClaimingReward` + `try/finally` 保证锁的正确释放
5. **实时更新**：进度变化通过事件系统推送，不需要轮询
6. **Toast vs Popup**：根据操作语境选择合适的提示形式
