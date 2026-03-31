---
title: Loading界面状态机设计——最小显示时间与异步关闭流程的完整实现
published: 2026-03-31
description: 深入解析UI Loading界面管理系统，包括ELoadingState状态机、最小循环等待时间与级别防抢占的精细控制
tags: [Unity, UI系统, Loading]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Loading界面状态机设计——最小显示时间与异步关闭流程的完整实现

游戏的Loading界面看起来简单，但一个真正健壮的Loading系统需要处理很多边界情况：加载太快时Loading一闪而过（用户体验差），加载超时时界面卡住，异步关闭时有其他操作请求等。

VGame项目的`UILoadingComponentSystem`实现了一套精细的Loading状态机，解决了上述所有问题。

## 一、ELoadingState五阶段状态机

```csharp
public enum ELoadingState
{
    Idle,       // 闲置（没有Loading在显示）
    Opening,    // 正在打开（UI动画进入中）
    Looping,    // 循环中（可以关闭但在等待最小时间）
    CanClose,   // 可以关闭（最小等待时间已到）
    Closing,    // 正在关闭（UI动画退出中）
}
```

**五个状态的职责**：
- `Idle`：初始状态，可以打开新的Loading
- `Opening`：打开动画播放中，不接受重复打开请求
- `Looping`：Loading动画循环中，等待"最小显示时间"到期
- `CanClose`：最小时间已到，收到关闭请求可以立刻开始关闭
- `Closing`：关闭动画播放中，不接受重复关闭请求

## 二、防重复打开：状态检查

```csharp
private static async ETTask ShowLoading(this UILoadingComponent self, LoadingOptions options)
{
    var panelName = options.UIPath;
    if (string.IsNullOrEmpty(panelName))
    {
        Log.LogError("[Loading] 无法打开界面，名称为空");
        return;
    }
    
    // 关键检查：只有Idle状态才能打开
    if (self.LoadingState != ELoadingState.Idle)
    {
        Log.LogInfo("[Loading] 无法打开界面 {0}，已打开界面 {1}，并处于 {2} 状态", 
            panelName, self.LoadingOptions.UIPath, self.LoadingState);
        return; // 不是Idle则直接返回，不强制打开
    }
    
    self.Reset();
    self.SetLoadingOptions(options);
    self.LoadingState = ELoadingState.Opening;
    // ... 打开UI面板
    self.LoadingState = ELoadingState.Looping;
}
```

这确保了全局同时只有一个Loading界面存在。如果已经有Loading在显示，新的打开请求会被忽略（打印日志便于调试）。

## 三、Loading级别防抢占

```csharp
private static async ETTask HideLoading(this UILoadingComponent self, int loadingLevel, bool forceClose = false)
{
    // 不能关闭更高级别的Loading
    if (loadingLevel < self.LoadingOptions.Level)
    {
        Log.LogInfo("[Loading] 无法关闭界面 {0}，目标级别 {1} 低于当前级别 {2}", 
            panelName, loadingLevel, self.LoadingOptions.Level);
        return;
    }
    // ...
}
```

`ELoadingLevel`（级别）解决了这样的问题：

- 战斗加载使用"高级别Loading"（`Level=2`，覆盖全屏的详细进度条）
- 某些UI操作使用"低级别Loading"（`Level=1`，小转圈）

如果战斗加载正在进行（Level=2），UI的小转圈（Level=1）请求关闭时，因为级别不够，会被拒绝——战斗Loading不会被低级别的关闭请求误关闭。

## 四、最小显示时间机制

```csharp
// 打开完毕后
self.LoadingState = ELoadingState.Looping;

// 等待最小时间
if (self.ShouldWaitMinLoop)
    self.CreateMinLoopWaitTask().Coroutine(); // 异步等待，不阻塞
else
    self.LoadingState = ELoadingState.CanClose; // 无需等待，直接可关闭
```

```csharp
private static async ETTask CreateMinLoopWaitTask(this UILoadingComponent self)
{
    self.MinLoopWaitToken = new ETCancellationToken();
    
    // 等待最小循环时间（如800ms）
    await TimerComponent.Instance.WaitAsync(self.MinLoopWaitTime, self.MinLoopWaitToken);
    
    self.LoadingState = ELoadingState.CanClose;
    self.MinLoopWaitToken = null;
}
```

**最小显示时间的用户体验价值**：

没有最小时间：Loading界面可能出现后几十毫秒就关了，玩家看到一个快速闪烁的白屏，不仅视觉不好，还会让玩家不确定"是否真的加载完了"。

有最小时间（如800ms）：Loading界面至少显示0.8秒，玩家有足够的时间看到加载指示器，心理上确认了"系统在处理中"。

**`forceClose`强制关闭**：

```csharp
if (forceClose)
    self.MinLoopWaitToken?.Cancel(); // 取消最小时间等待
```

有些情况需要强制关闭：比如网络断线、用户手动取消，这时可以传`forceClose=true`，即使最小时间没到也立刻关闭。

## 五、等待最小时间到期后才关闭

```csharp
// 等待直至允许关闭
await ETTaskWaitUntil.WaitUntil(() => self.LoadingState != ELoadingState.Looping);
```

`HideLoading`在收到关闭请求时，如果还在`Looping`状态（最小时间还没到），会一直等待直到状态变为`CanClose`。

这实现了"关闭请求排队等待"的效果：即使加载完成时立刻调用`HideLoading`，它也会自动等到最小时间到期。

## 六、关闭时的任务链

```csharp
private static async ETTask CloseLoading(this UILoadingComponent self, string panelName)
{
    // 1. 播放关闭音效
    self.PlayLoadingCloseSoundEffect(panelName);
    
    // 2. 播放关闭动画（Tween）
    await EventSystem.Instance.PublishAsync(self.ClientScene(), 
        new Evt_PlayCloseUITween { PanelName = panelName });
    
    // 3. 通知Loading隐藏动画结束（其他系统可能在等待这个）
    FireEvent(new Evt_LoadingHideAnimationEnd());
    
    // 4. 标记Scene不再加载中
    self.ClientScene().GetComponent<SceneComponent>().SetIsLoading(false);
    
    // 5. 等待关闭动画后注册的任务完成（比如：关闭时同时触发的特殊逻辑）
    await self.ClientScene().GetComponent<SceneComponent>().BeforeLoadingTasksFinish();
    
    // 6. 实际关闭面板（不带Tween，因为Tween已经在步骤2播放了）
    await EventSystem.Instance.PublishAsync(self.ClientScene(), 
        new Evt_CloseUIPanelWithOutTween { PanelName = panelName });
    
    // 7. 重置状态
    self.Reset();
}
```

关闭任务链的顺序非常关键：
- 先播关闭音效（让用户立刻听到反馈）
- 等待关闭Tween（确保动画播完）
- 通知Loading已隐藏（其他系统可以继续）
- 设置`IsLoading=false`（允许新操作）
- 等待`BeforeLoadingTasksFinish`（允许其他系统注册"关闭后执行"的任务）
- 真正关闭面板对象
- 重置自身状态为Idle

**`BeforeLoadingTasksFinish`的设计意图**：

某些系统需要在Loading关闭时执行一些操作（比如解除某些UI的锁定）。通过`BeforeLoadingTasksFinish`，它们可以注册回调，在Loading动画完成后、面板实际销毁前执行。

## 七、不同Loading面板的特殊初始化

```csharp
switch (panelName)
{
    case YIUI_PanelNameDefine.BlackScreenLoadingPanel:
        // 黑屏Loading：传入0.5f的淡入时间
        await EventSystem.Instance.PublishAsync(self.ClientScene(), 
            new Evt_ShowUIPanel<float> { PanelName = panelName, p1 = 0.5f });
        break;
    
    case PanelNameDefine.LoadingAnimationPanel:
        // 战斗Loading：传入队伍名称和比赛信息
        var dungeonComp = YIUIComponent.ClientScene.Dungeon();
        await TimerComponent.Instance.WaitAsync(500); // 等500ms（给上一个UI动画完成时间）
        await EventSystem.Instance.PublishAsync(self.ClientScene(), 
            new Evt_ShowUIPanel<string, string, string, bool>
            {
                PanelName = panelName,
                p1 = dungeonComp.GetTeamName(true),  // 我方队名
                p2 = dungeonComp.MatchRegionText,     // 赛区
                p3 = dungeonComp.MatchNameText,       // 比赛名称
                p4 = false,
            });
        break;
    
    default:
        await EventSystem.Instance.PublishAsync(self.ClientScene(), 
            new Evt_ShowUIPanel { PanelName = panelName });
        break;
}
```

不同的Loading界面需要不同的初始化参数。通过`switch`在UILoadingComponent层面处理这些差异，Loading的调用方（事件发送者）不需要知道每种Loading的具体参数。

**战斗Loading的500ms等待**：在打开战斗Loading之前等500ms，给当前界面（如大厅界面）的关闭动画留时间。如果太快打开Loading，可能看到两个界面叠加的瞬间。

## 八、总结

Loading系统的设计精华：

| 机制 | 解决的问题 |
|------|---------|
| 五阶段状态机 | 精确控制Loading的生命周期，防止重复操作 |
| 级别防抢占 | 低级别关闭不影响高级别Loading |
| 最小显示时间 | 防止Loading一闪而过，体验差 |
| forceClose | 允许特殊情况（断线、取消）强制关闭 |
| 关闭任务链 | 确保动画→通知→实际关闭的顺序正确 |

对新手来说，"Loading系统是状态机"这个认知非常重要——不要把Loading管理写成一堆bool标志，而是用清晰的状态枚举来描述Loading当前处于什么阶段，每个状态有明确的转换条件。
