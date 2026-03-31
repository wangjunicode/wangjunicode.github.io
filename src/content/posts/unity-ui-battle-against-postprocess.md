---
title: Unity游戏战斗进度对决动画与后期处理模糊特效
published: 2026-03-31
description: 深入解析战斗僵持进度条对决动画的速度计算、MEC协程管理、后期处理模糊特效与UI面板的协同以及战前演出全屏模糊效果的完整实现。
tags: [Unity, UI系统, 战斗特效, 后期处理]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏战斗进度对决动画与后期处理模糊特效

## 两种战斗视觉系统的结合

`BattleAgainstPanel`（进度条对决）和 `BeforeBattleAnimationPanel`（战前模糊演出）代表了两种不同的战斗视觉增强技术：

1. **进度条对决**：纯 UI 动画，双方进度条赛跑，展示力量对比
2. **后期处理模糊**：通过 `UIPostProcessComponent` 在世界空间应用径向模糊 Volume，制造"聚焦感"

---

## 进度条对决的速度计算

`BattleAgainstPanel` 展示了一个"双方进度条赛跑"的对决演出：

```csharp
// 胜利者以恒定速度跑完100%
var winnerSpeed = 1f / durationSec;

// 失败者以胜利者速度的 50%-90% 随机速度跑，但永远跑不完
var loserSpeed = UnityEngine.Random.Range(0.5f, 0.9f);
```

**设计思路**：
- 胜利者的进度条在 `durationSec` 秒内跑到100%（`speed = 1/duration`）
- 失败者的速度是随机的50%-90%，视觉上"接近但落后"
- 随机化让每场对决看起来不一样，避免单调

注意这里没有使用真实的属性值比较来决定速度差异：

```csharp
// 原来注释掉的基于属性值的计算：
// var attackerSpeed = (attackerPropertyValue / winnerPropertyValue) / durationSec;
// var defenderSpeed = (defenderPropertyValue / winnerPropertyValue) / durationSec;
```

改用随机值是视觉设计的决策——真实属性差距可能很悬殊（99:1），进度条差异太大反而没有对决的紧张感。随机50%-90%保持了视觉上的"竞争感"。

---

## MEC 协程管理进度条

```csharp
CoroutineHandle[] showProgressCoroutineHandles = new CoroutineHandle[2];

void StartShowProgress(int index, float speed, Action callback)
{
    if (showProgressCoroutineHandles[index].IsRunning)
        Timing.KillCoroutines(showProgressCoroutineHandles[index]);
    
    showProgressCoroutineHandles[index] = Timing.RunCoroutine(
        ShowProgress(index, speed, callback)
    );
}

IEnumerator<float> ShowProgress(int index, float speed, Action callback)
{
    progressImages[index].fillAmount = 0f;
    
    while (progressImages[index].fillAmount < 1f)
    {
        progressImages[index].fillAmount += speed * Time.deltaTime;
        yield return Timing.WaitForOneFrame;
    }
    
    progressImages[index].fillAmount = 1f;
    callback?.Invoke();
}
```

使用 **MEC（More Effective Coroutines）** 而不是 Unity 标准 Coroutine 的原因：
1. `CoroutineHandle` 提供了对协程的引用，可以通过 `Timing.KillCoroutines(handle)` 精确杀死特定协程
2. Unity 的 `StartCoroutine` 返回 `Coroutine` 对象，`StopCoroutine` 也可以用，但实例管理更繁琐
3. MEC 的 `IEnumerator<float>` 比标准 `IEnumerator` 有更多控制选项（`Timing.WaitForOneFrame` 等）

`showProgressCoroutineHandles[index].IsRunning` 检查是否有正在运行的协程，有则先杀死再启动新的。这处理了"对决在播放中途被重置"的情况（比如调用 `ResetState`）。

---

## 对决完成的互相等待

```csharp
int completedCount = 0;

void OnCompletedCallback()
{
    completedCount++;
    
    if (completedCount == 2)
    {
        // 两条进度条都完成了，播放结果动画
        PlayResultAnimation();
    }
}
```

`completedCount` 是一个简单的计数器——两条进度条各完成后调用一次回调，计数到2时触发结果动画。

这是等待多个异步操作都完成的简单计数器模式。

---

## BeforeBattleAnimationPanel：后期处理模糊

战前演出使用了径向模糊（Radial Blur）后期处理效果：

```csharp
public async ETTask PlayAniShow()
{
    using var tasks = new ListComponent<ETTask>();
    
    // 添加模糊 Volume
    var uiPostProcess = YIUIComponent.ClientScene.CurrentScene()
        .GetOrAddComponent<UIPostProcessComponent>();
    curVolumeId = uiPostProcess.AddVolumePrefab(
        VolumePrefabAssetPathType.VolumeBlur01, 
        null, 
        0
    );
    
    // 获取 Volume 上的 Animator
    var volume = uiPostProcess.GetVolumePrefab(curVolumeId);
    var volumeAnimator = volume?.GetComponent<Animator>();
    
    if (volumeAnimator != null)
    {
        tasks.Add(volumeAnimator.PlayAndWaitAnimation(
            Animator.StringToHash("UI_PP_RadiuBlur_In")));
    }
    
    // 同时播放 UI 面板出现动画
    tasks.Add(u_ComPanelAnimator.PlayAndWaitAnimation(UIAnimNameDefine.ShowHash));
    
    // 播放音效
    VGameAudioManager.Instance.PlaySound(30094);
    
    // 并行等待所有动画完成
    await ETTaskHelper.WaitAll(tasks);
}
```

**关键架构点**：

后期处理 Volume 和 UI 面板是**完全独立的两个系统**：
- Volume：挂在世界场景 Camera 的 Post Processing 堆栈中，影响整个画面的渲染
- UI Panel：UGUI Canvas 上的 2D 元素

`UIPostProcessComponent` 作为桥接层，负责：
1. 在场景中实例化 Volume Prefab（`AddVolumePrefab`）
2. 管理 Volume 的生命周期（返回 `VolumeId` 用于后续删除）
3. 关闭时发布 `Evt_HidePostProcessPrefab` 事件

---

## 关闭时的双动画并行

```csharp
protected override async ETTask OnCloseTween()
{
    using var tasks = new ListComponent<ETTask>();
    
    // 1. UI 面板退出动画
    tasks.Add(u_ComPanelAnimator.PlayAndWaitAnimation(UIAnimNameDefine.HideHash));
    
    // 2. Volume 模糊退出动画（与 UI 面板同步）
    var uiPostProcess = YIUIComponent.ClientScene.CurrentScene()
        .GetOrAddComponent<UIPostProcessComponent>();
    var volume = uiPostProcess.GetVolumePrefab(curVolumeId);
    var volumeAnimator = volume?.GetComponent<Animator>();
    if (volumeAnimator != null)
    {
        tasks.Add(volumeAnimator.PlayAndWaitAnimationEnd(
            Animator.StringToHash("UI_PP_RadiuBlur_Out")));
    }
    
    // 等待两个动画同时完成
    await ETTaskHelper.WaitAll(tasks);
    
    // 3. 销毁 Volume
    EventSystem.Instance.Publish(YIUIComponent.ClientScene.CurrentScene(),
        new Evt_HidePostProcessPrefab() { VolumeId = curVolumeId });
}
```

**为什么销毁 Volume 要在两个动画都完成后**：

如果提前销毁 Volume，模糊效果会在退出动画播放中途突然消失，视觉上非常突兀。等退出动画（"模糊淡出"）完成后再销毁，视觉上模糊效果已经完全消退，销毁不会有任何可见的突变。

`ETTaskHelper.WaitAll(tasks)` 等同于 `Task.WhenAll`，等最慢的那个完成。

---

## `ListComponent<ETTask>` 的对象池

```csharp
using var tasks = new ListComponent<ETTask>();
```

`ListComponent<ETTask>` 是框架提供的对象池化 `List<ETTask>`。`using` 语句确保作用域结束时自动调用 `Dispose()`（将 List 归还对象池）。

这避免了每次播放动画都 `new List<ETTask>()` 造成的 GC 压力。战前演出在战斗开始时播放，战斗中可能多次触发，对象池在这里收益明显。

---

## 初始化的状态重置

```csharp
protected override void Initialize()
{
    u_ComPanel_vx_01CanvasGroup.alpha = 0;  // 初始透明
}

protected override async ETTask<bool> OnOpen()
{
    u_ComPanel_vx_01CanvasGroup.alpha = 0;  // 再次确保透明
    await ETTask.CompletedTask;
    return true;
}
```

同样的 `alpha = 0` 在 `Initialize` 和 `OnOpen` 中都有，**为什么重复**？

- `Initialize`：面板第一次创建时调用（来自对象池的首次初始化）
- `OnOpen`：每次面板打开时调用（来自对象池的复用，可能不会再次调用 Initialize）

对象池复用时，`Initialize` 不会再调用（只调用一次），但 `OnOpen` 每次都调用。为了确保每次复用都从透明状态开始，需要在 `OnOpen` 里重置。

---

## 总结

这两个面板展示了两种不同的视觉增强技术：

1. **进度条对决**
   - 随机速度差保持视觉竞争感（而非真实数值比较）
   - MEC `CoroutineHandle` 精确管理协程生命周期
   - 计数器模式等待多个异步完成

2. **后期处理模糊**
   - `UIPostProcessComponent` 桥接 Volume 和 UI 系统
   - 关闭时并行播放 UI 动画和 Volume 退出动画
   - 动画完全结束后再销毁 Volume，避免视觉突变
   - `ListComponent<T>` 对象池减少 GC

两种技术组合，让战斗演出既有 UI 层的精确控制，又有渲染层的视觉冲击力。
