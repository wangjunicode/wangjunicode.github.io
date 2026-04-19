---
title: Unity游戏战斗结算界面奖励动画与解锁展示
published: 2026-03-31
description: 完整解析战斗结算界面的胜负判定、奖励列表动态生成、错开延迟动画序列、解锁内容展示和状态机胜负切换的实现方案。
tags: [Unity, UI系统, 战斗结算, 奖励系统]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏战斗结算界面奖励动画与解锁展示

## 结算界面的体验设计要点

战斗结算界面是整个游戏体验的"收尾"——玩家刚经历了一场战斗，需要在这里看到自己的战果。好的结算界面应该：

1. **清晰传达胜负**：胜利/失败要视觉冲击力强，一眼就能看出
2. **奖励"一件一件地出现"**：比同时显示所有奖励更有仪式感
3. **有期待感的延迟**：奖励不能太快出现，要给玩家足够时间"看清"每个奖励
4. **解锁内容单独展示**：新解锁的成就、称号等要突出显示

`BattleSettlementOutcomePanel.cs` 展示了一个完整的结算界面实现。

---

## 胜负状态切换

```csharp
public void Update()
{
    var isLose = !_data.SettleData.IsWin;
    
    // 状态机切换：0=胜利，1=失败
    u_ComWinOrLose.ApplyState(isLose ? 1 : 0);
    
    UpdateRewards();
    UpdateUnlocks();
    
    // 失败时播放失败音效
    if (isLose)
        xgameAudioManager.Instance.PlaySound(30122);
}
```

**状态机设计**：`u_ComWinOrLose.ApplyState(isLose)` 简洁地切换整个胜负区域的显示——胜利状态显示金色"VICTORY"文字和烟花粒子，失败状态显示灰色"DEFEAT"文字和不同的背景。

注意失败音效是在 `Update` 里播放，而不是在 `OnOpenTween` 里。界面出现音效（`Play_ui_battle_account_interface_single`）在 `OnOpenTween` 里播放，这两个音效分开处理，使得：
- 所有结算界面都播放"出现音效"（通用）
- 失败时额外播放"失败音效"（特殊）
- 胜利时不需要额外音效（胜利烟花的粒子系统自带音效）

---

## YIUIMatchUIElement 的三方参数版

```csharp
// 奖励列表
YIUIMatchUIElementHelper.MatchUIElement<BattleSettlementReward, BattleSettlementOutcomeRewardItem>(
    _data.RewardList,              // 数据列表
    battleSettlementOutcomeRewardItems,  // 已有组件列表（用于复用）
    Create<BattleSettlementOutcomeRewardItem>,  // 工厂函数
    SetData,                        // 数据绑定函数
    u_ComContainer_RewardsRectTransform  // 父节点（新创建的组件挂在这里）
);
```

与上一篇统计界面相比，这里多传了一个父节点参数 `u_ComContainer_RewardsRectTransform`。原因：奖励 Item 是动态生成的，不是预先放在场景中的，`YIUIFactory.Instantiate<T>()` 创建后需要知道挂在哪个父节点下。

---

## 错开延迟动画：数学公式驱动

```csharp
private const int rewardDelay = 600;    // 首个奖励延迟出现（ms）
private const int rewardInterval = 150; // 相邻奖励的间隔（ms）

void SetData(BattleSettlementReward data, BattleSettlementOutcomeRewardItem item, int idx)
{
    // 每个奖励的延迟时间 = 基础延迟 + 序号 × 间隔
    item.PlayAnim(idx * rewardInterval + rewardDelay);
    item.Update(data.rewardName, data.rewardNum, data.suffix, data.proportion, data.decimalPlaces);
    item.SetUpDownState(data.UpdownState);
}
```

这个公式让奖励按序号依次出现：
- 奖励0：600ms 后出现
- 奖励1：750ms 后出现（600 + 150）
- 奖励2：900ms 后出现（600 + 300）
- 奖励3：1050ms 后出现

这种"错开延迟"（Staggered Delay）的动画设计比"所有奖励同时出现"更有层次感，让玩家有时间看清每一个奖励。

**解锁内容的延迟在奖励之后**：

```csharp
private const int unlockInterval = 200;  // 解锁内容的间隔（ms）

void SetUnlockData(BattleSettlementUnlock data, BattleSettlementOutcomeUnlockItem item, int idx)
{
    // 解锁内容在所有奖励之后出现
    int delay = idx * unlockInterval 
              + _data.RewardList.Count * rewardInterval  // 等奖励全部出现
              + rewardDelay;                              // 再等基础延迟
    item.PlayAnim(delay);
    item.Update(data.unlockName);
}
```

解锁内容（新成就、称号等）的延迟计算包含了奖励列表的总时长：

假设有3个奖励（0, 1, 2）和2个解锁内容：
- 最后一个奖励出现时间：600 + 2×150 = 900ms
- 解锁内容0：900 + 150 + 200×0 = 1050ms
- 解锁内容1：1050 + 200 = 1250ms

这确保了"先看奖励，再看解锁"的展示顺序，不会让奖励和解锁混在一起展示。

---

## `PlayAnim(int delay)` 的实现原理

```csharp
// RewardItem 中的延迟动画方法
public void PlayAnim(int delayMs)
{
    // 先隐藏（从透明/缩放为0开始）
    u_ComRootCanvasGroup.alpha = 0;
    
    // 延迟指定毫秒后播放入场动画
    TimerComponent.Instance.NewOnceTimer(delayMs, () => {
        u_ComBattleSettlementOutcomeRewardItemAnimator.PlayAnimation(UIAnimNameDefine.Show);
        u_ComRootCanvasGroup.alpha = 1;
    });
}
```

`TimerComponent.Instance.NewOnceTimer(delayMs, callback)` 是框架提供的定时器，在指定毫秒后执行一次回调。这比 `StartCoroutine(WaitForSeconds(...))` 更简洁，也支持在不活动的 GameObject 上运行（Coroutine 在 GameObject 未激活时停止运行）。

---

## 奖励数值的格式化显示

```csharp
public void Update(string rewardName, float rewardNum, string suffix, 
    float proportion, int decimalPlaces)
{
    u_ComNameText.text = rewardName;
    
    // 数值格式化：proportion 是本场相对上次的倍率，decimalPlaces 控制小数位
    string numText;
    if (decimalPlaces == 0)
        numText = Mathf.RoundToInt(rewardNum).ToString();
    else
        numText = rewardNum.ToString($"F{decimalPlaces}");  // F1=保留1位小数
    
    u_ComNumText.text = numText + suffix;  // 例如："+250" 或 "1,250分"
    
    // 上升/下降状态（影响数值颜色：绿=增加，红=减少）
    SetUpDownState(updownState);
}
```

`proportion`（倍率）参数用于"相比上次的变化"展示（例如积分提升了150%），但具体如何使用取决于 `RewardItem` 的完整实现。`decimalPlaces` 参数使奖励数值的精度可配置——积分通常是整数（0位小数），战术成功率可能需要1位小数。

---

## 关闭按钮的事件发布

```csharp
protected override async ETTask OnEventCloseAction()
{
    await EventSystem.Instance.PublishAsync(YIUIComponent.ClientScene, 
        new Evt_BattleSettlementOutcomePanelClose { ViewData = _data });
}
```

结算界面的关闭**不直接调用 `Close()`**，而是通过事件系统发布关闭请求。这允许外部系统（比如主界面流程管理器）拦截这个事件并做额外处理（比如先播放退出战斗的过渡动画，再关闭结算界面）。

`await EventSystem.Instance.PublishAsync` 使用异步发布，等待所有监听者处理完毕再返回。如果监听者中有 `await PanelMgr.Inst.OpenPanelAsync<...>`，这个异步链确保了新面板完全打开后，`OnEventCloseAction` 才返回。

---

## 音效设计细节

```csharp
// 在 OnOpenTween 里播放"界面出现音效"
protected override async ETTask OnOpenTween()
{
    xgameAudioManager.Instance.PlaySound(Play_ui_battle_account_interface_single);  // 30064
    await u_ComBattleSettlementOutcomePanelAnimator.PlayAndWaitAnimation(UIAnimNameDefine.ShowHash);
}

// 在 Update 里播放"失败音效"
if (isLose)
    xgameAudioManager.Instance.PlaySound(30122);
```

**音效 ID 的命名规范**：

`Play_ui_battle_account_interface_single = 30064` 用有意义的常量名而不是直接写数字。如果音效 ID 变了（比如重新录制了新的音效），只需要改这个常量，不需要在代码里搜索数字 30064。

界面出现音效在 `OnOpenTween`（打开过渡动画）开始时播放，而不是在 `OnOpen`。这样玩家点击"进入结算"后，先听到音效再看到动画展开，时序上更自然。

---

## 上升/下降状态指示

```csharp
public void SetUpDownState(int updownState)
{
    // 0=中性（白色），1=上升（绿色），2=下降（红色）
    u_ComArrowStateSelector.ApplyState(updownState);
}
```

`UpdownState` 用于指示指标的变化趋势：
- 积分增加（本场比上场多）→ 绿色箭头↑
- 积分减少 → 红色箭头↓
- 第一次（没有历史数据比较）→ 白色/中性

这种趋势指示帮助玩家快速感知"这场打得比上次好还是差"。

---

## 空列表的保护

```csharp
private void UpdateRewards()
{
    // 防止 RewardList 为 null 导致后续崩溃
    if (_data.RewardList == null)
    {
        _data.RewardList = new List<BattleSettlementReward>();
    }
    
    YIUIMatchUIElementHelper.MatchUIElement<...>(_data.RewardList, ...);
}
```

在使用 `_data.RewardList` 前检查并初始化为空列表，而不是让 `MatchUIElement` 内部处理 null——因为我们并不确定框架方法是否对 null 做了保护。这是防御性编程的基本原则：**在你控制的代码边界上做校验，不要依赖第三方代码对 null 做特殊处理**。

---

## 总结

战斗结算界面的代码展示了游戏 UI 的多个精细设计：

1. **状态机胜负**：一行 `ApplyState` 切换整个胜负区域的视觉表现
2. **错开延迟动画**：简单的数学公式 `idx × interval + baseDelay` 创造层次感
3. **解锁在奖励后**：奖励总时长作为解锁动画的基础偏移，保证展示顺序
4. **定时器触发动画**：`TimerComponent.NewOnceTimer` 比 Coroutine 更灵活
5. **事件发布关闭**：不直接 Close，让外部系统有拦截机会
6. **null 保护**：在使用前主动初始化，而非依赖框架处理 null
