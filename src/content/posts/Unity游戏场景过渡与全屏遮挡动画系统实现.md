---
title: Unity游戏场景过渡与全屏遮挡动画系统实现
published: 2026-03-31
description: 深入解析全屏遮黑淡入淡出过渡系统的多版本接口设计、CanvasGroup Alpha 动画、DoTween回调转ETTask、自动关闭与手动关闭的异步流程控制。
tags: [Unity, UI系统, 场景过渡, 淡入淡出]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity游戏场景过渡与全屏遮挡动画系统实现

## 场景过渡的技术意义

每当游戏需要从大厅进入战斗、或从战斗返回大厅，必然要加载新的场景。如果直接切换，用户会看到一段白屏/黑屏，体验很差。**场景过渡（ScreenTransition）** 通过全屏遮挡层的渐变，优雅地隐藏了场景切换的"丑陋瞬间"。

`ScreenTransitionPanel` 是一个专用的全屏遮挡面板，支持：
- 黑色（或任意颜色）的渐入渐出过渡
- 带"Hacking"风格加载界面的过渡
- 可配置的淡入时长、停留时长、淡出时长
- 自动关闭或手动关闭两种模式

---

## 多级 OnOpen 接口的向下兼容

`ScreenTransitionPanel` 实现了 4 个版本的 `IYIUIOpen` 接口：

```csharp
// 版本1：最简，3个 float，使用默认黑色
public async ETTask<bool> OnOpen(float p1, float p2, float p3)
{
    return await OnOpen(Color.black, p1, p2, p3);
}

// 版本2：指定颜色，默认自动关闭
public async ETTask<bool> OnOpen(Color color, float p1, float p2, float p3)
{
    return await OnOpen(color, p1, p2, p3, true);
}

// 版本3：完整参数，可选是否自动关闭（核心实现）
public async ETTask<bool> OnOpen(Color color, float fadeIn, float stay, float fadeOut, bool autoClose)
{
    if (isPlaying) return true;
    
    u_ComUIBinder.ApplyState(0);  // 切换到"颜色遮挡"状态
    _fadeIn = fadeIn;
    _stay = stay;
    _fadeOut = fadeOut;
    isPlaying = true;
    
    u_ComW_TransitionRawImage.color = color;  // 设置遮挡颜色
    
    // 淡入：CanvasGroup Alpha 从 0 → 1
    var doFadeTween = u_ComW_TransitionCanvasGroup.DoFade(1, _fadeIn, Ease.Unset);
    var action = DoTweenExternal.TweenCallbackToAction(doFadeTween);
    await ETTaskWaitCallback.WaitCallback(action);  // 等待淡入完成
    
    // 淡入完成后：如果自动关闭，立即开始关闭流程（淡出）
    if (autoClose)
        CloseAsync().Coroutine();
    
    return true;
}

// 版本4：风格化过渡（Hacking界面等）
public async ETTask<bool> OnOpen(ScreenTransitionStyle style, float stay, bool autoClose)
{
    if (isPlaying) return true;
    
    u_ComUIBinder.ApplyState((int)style + 1);  // 切换到对应风格状态
    _stay = stay;
    isPlaying = true;
    
    u_ComBgPanel_loadingAnimator.Play("Show");
    await TimerComponent.Instance.WaitAsync((long)(stay * 1000));  // 停留指定时长
    
    if (autoClose)
        CloseAsync().Coroutine();
    
    return true;
}
```

**向下兼容的设计模式**：

最简版（3 float）调用稍复杂版（4参数），稍复杂版调用完整版（5参数）。这形成了一个"代理链"：

```
OnOpen(float×3)  →  OnOpen(Color, float×3)  →  OnOpen(Color, float×3, bool)
```

新增功能（颜色/自动关闭开关）通过添加新版本接口实现，旧的调用方不需要修改，符合"开闭原则"。

---

## DoTween 回调转 ETTask

```csharp
var doFadeTween = u_ComW_TransitionCanvasGroup.DoFade(1, _fadeIn, Ease.Unset);
var action = DoTweenExternal.TweenCallbackToAction(doFadeTween);
await ETTaskWaitCallback.WaitCallback(action);
```

这三行代码是 DOTween 和 ET 框架 异步系统桥接的典型用法：

**问题**：DOTween 动画完成通过 `OnComplete(callback)` 触发，但 ET 框架用 `await ETTask` 方式等待异步操作。两者的异步模型不同，需要桥接。

**`DoTweenExternal.TweenCallbackToAction(tween)`**：将 DOTween 的 OnComplete 回调转换为一个 `Action`，当动画完成时调用这个 Action。

**`ETTaskWaitCallback.WaitCallback(action)`**：返回一个 `ETTask`，当传入的 Action 被调用时，Task 完成。

两者结合：DOTween 动画完成 → 调用 Action → ETTask 变为完成状态 → `await` 之后的代码继续执行。

---

## 关闭过渡（淡出）的分支逻辑

```csharp
protected override async ETTask OnCloseTween()
{
    switch (u_ComUIBinder.CurrentState)
    {
        case 0:  // 颜色遮挡状态
            var fadeTween = u_ComW_TransitionCanvasGroup.DoFade(0, _fadeOut, Ease.Unset);
            if (_stay > 0)
            {
                _ = fadeTween.SetDelay(_stay);  // 停留时长 > 0：先延迟再淡出
            }
            var action = DoTweenExternal.TweenCallbackToAction(fadeTween);
            await ETTaskWaitCallback.WaitCallback(action);
            OnComplete();
            break;
        
        case (int)ScreenTransitionStyle.Hacking + 1:  // Hacking 风格
            await TimerComponent.Instance.WaitAsync((long)(_stay * 1000));
            u_ComBgPanel_loadingAnimator.Play("Hide");
            var seconds = u_ComBgPanel_loadingAnimator.GetCurrentAnimatorStateInfo(0).length;
            await TimerComponent.Instance.WaitAsync((int)(seconds * 1000));
            OnComplete();
            break;
    }
}
```

**`CurrentState == 0`**（颜色遮挡）的关闭流程：
1. 启动 Alpha 淡出动画（0.8f → 0）
2. 如果有停留时长（`_stay > 0`），通过 `SetDelay` 在动画前延迟
3. 等待动画完成

**`Hacking + 1`**（风格化）的关闭流程：
1. 等待停留时长
2. 播放 Animator 的 "Hide" 动画
3. **读取 Hide 动画的时长**（`GetCurrentAnimatorStateInfo(0).length`）然后等待这么久
4. 完成

读取 Animator 动画时长这个操作很精妙——不是硬编码等待2秒，而是动态读取动画实际时长，保证了即使动画时长被美术调整，等待时间也自动跟着变。

---

## 防重入的 `isPlaying` 标志

```csharp
public async ETTask<bool> OnOpen(Color color, float p1, float p2, float p3, bool autoClose)
{
    if (isPlaying)  // 已经在播放过渡中
    {
        return true;  // 直接返回，不重新开始
    }
    // ...
    isPlaying = true;
}
```

`isPlaying` 防止了场景切换时如果连续触发两次过渡（比如玩家快速点击进入战斗），第二次调用被忽略。

注意 `isPlaying = false` 是在 `OnComplete()` 里（所有动画播完后）才重置，而不是在 `OnOpen` 返回时重置——因为 `autoClose=true` 时，`CloseAsync` 是异步的，`OnOpen` 返回时关闭动画还没结束。

---

## 自动关闭 vs 手动关闭的使用场景

```csharp
// 自动关闭模式（autoClose=true）
// 用于：加载时间确定的场景切换
// 流程：淡入完成 → 自动开始淡出
ScreenTransitionPanel.OpenAsync(0.3f, 0.5f, 0.3f);
// 结果：0.3秒淡入 → 0.5秒停留 → 0.3秒淡出 → 面板关闭

// 手动关闭模式（autoClose=false）
// 用于：加载时间不确定的场景切换
// 流程：淡入完成 → 等待加载 → 手动调用 Close 触发淡出
var transPanel = ScreenTransitionPanel.OpenAsync(Color.black, 0.3f, 0f, 0.3f, false);
await LoadScene(nextScene);  // 等待场景加载
transPanel.Close();  // 场景加载完成后手动关闭（触发淡出）
```

关键区别在于 `_stay = 0` 时 `SetDelay` 不生效（`if (_stay > 0)` 检查）：
- 自动模式：淡入后立即等 `_stay` 秒再淡出（`_stay` 可以是0.5秒）
- 手动模式：`_stay = 0`，外部 `Close()` 时立即淡出

---

## CanvasGroup 的多用途

```csharp
u_ComW_TransitionCanvasGroup.DoFade(1, _fadeIn, Ease.Unset);  // 淡入
u_ComW_TransitionCanvasGroup.DoFade(0, _fadeOut, Ease.Unset); // 淡出
```

使用 `CanvasGroup.alpha` 而不是 `Image.color.a` 来做全屏淡入淡出的原因：
- `CanvasGroup.alpha` 影响整个 Canvas 节点及其所有子节点
- 如果全屏遮挡层是一个包含多个子元素的复杂面板（比如 Hacking 风格），只改 `CanvasGroup.alpha` 就能同时控制所有子元素的透明度
- 改 `Image.color.a` 只影响单个 Image 组件

---

## 总结

`ScreenTransitionPanel` 虽然功能相对简单，但展示了几个精妙的工程设计：

1. **接口代理链**：简单版 → 完整版，向下兼容，新参数递进添加
2. **DoTween-ETTask 桥接**：`TweenCallbackToAction + WaitCallback` 让 DOTween 接入 await
3. **动态读取 Animator 时长**：`GetCurrentAnimatorStateInfo(0).length` 动态等待，不硬编码
4. **autoClose 控制模式**：自动关闭适合确定时长，手动关闭适合不确定时长（等待加载）
5. **CanvasGroup 统一控制**：单点控制整个遮挡层的透明度，不需要逐个子节点处理
6. **`isPlaying` 防重入**：在 `OnComplete` 时才重置，覆盖动画全过程
