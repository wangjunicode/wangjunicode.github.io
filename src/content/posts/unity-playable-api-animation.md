---
title: Unity Playable API 动画系统：手动混合与融合控制
published: 2026-03-31
description: 解析基于 Unity Playable API 的动态动画系统，包含 PlayableGraph 的构建、AnimationMixerPlayable 的权重管理，以及协程驱动的平滑动画过渡实现。
tags: [Unity, 动画系统, Playable API, 性能优化]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# Unity Playable API 动画系统：手动混合与融合控制

## 前言

Unity 的 Animator Controller（状态机）是大多数项目的首选，但它有一个局限：**过渡由状态机规则驱动，不能在运行时动态添加新的动画片段**。对于需要在运行时根据配置组合动画的场景（如性能测试工具、动态换装预览），Playable API 提供了更底层、更灵活的控制能力。

本文通过 `PlayableAnimationPlayer` 的实现，带你理解 Unity Playable 图的构建方式，以及如何实现任意动画之间的平滑融合。

---

## 一、PlayableGraph：动画的"节点图"

Playable API 的核心概念是"图"——所有的动画处理都是图中节点的数据流：

```
AnimationClipPlayable(Clip1) ──\
                                AnimationMixerPlayable ──→ AnimationPlayableOutput ──→ Animator
AnimationClipPlayable(Clip2) ──/
```

```csharp
public void CreatePlayableGraph()
{
    // 1. 创建图
    playableGraph = PlayableGraph.Create("DynamicAnimationGraph");
    playableGraph.SetTimeUpdateMode(DirectorUpdateMode.GameTime);  // 跟随游戏时间

    // 2. 创建混合节点（初始0个输入）
    mixerPlayable = AnimationMixerPlayable.Create(playableGraph, 0);

    // 3. 创建输出，绑定到目标 Animator
    var output = AnimationPlayableOutput.Create(playableGraph, "Animation", GetComponent<Animator>());
    output.SetSourcePlayable(mixerPlayable);  // 输出源是混合节点

    // 4. 开始播放
    playableGraph.Play();
}
```

**关键点：`SetTimeUpdateMode(DirectorUpdateMode.GameTime)`**

设置为 `GameTime` 表示图随 `Time.time` 更新，会受到 `Time.timeScale` 影响（慢动作）。如果设置 `UnscaledGameTime`，则不受 TimeScale 影响，可用于 UI 动画。

---

## 二、动态添加动画片段

```csharp
public int AddAnimationClip(AnimationClip clip)
{
    // 1. 创建 Clip 播放节点
    var clipPlayable = AnimationClipPlayable.Create(playableGraph, clip);
    clipPlayables.Add(clipPlayable);

    // 2. 扩容 Mixer 的输入数
    mixerPlayable.SetInputCount(clipPlayables.Count);

    // 3. 连接 Clip 到 Mixer 的指定输入槽
    int index = clipPlayables.Count - 1;
    playableGraph.Connect(clipPlayable, 0, mixerPlayable, index);

    // 4. 初始权重为 0（不播放）
    mixerPlayable.SetInputWeight(index, 0f);

    return index;  // 返回索引，供后续控制
}
```

这个设计允许在任意时刻动态添加新的动画片段，而不需要预先知道所有可能的动画。

**对比 Animator Controller 的限制：**

| 特性 | Animator Controller | Playable API |
|------|---------------------|--------------|
| 添加动画 | 只能在 Inspector 预先配置 | 运行时动态添加 |
| 过渡控制 | 由状态机规则驱动 | 直接控制权重 |
| 混合精度 | 隐式（AnimatorWeight）| 显式（SetInputWeight）|
| 调试可见性 | Animator 调试器 | 需自行实现 |

---

## 三、协程驱动的平滑过渡

```csharp
private System.Collections.IEnumerator FadeToAnimation(int targetIndex, float fadeTime)
{
    float[] startWeights = new float[clipPlayables.Count];

    // 快照当前权重
    for (int i = 0; i < clipPlayables.Count; i++)
        startWeights[i] = mixerPlayable.GetInputWeight(i);

    float elapsedTime = 0f;

    while (elapsedTime < fadeTime)
    {
        float t = elapsedTime / fadeTime;  // 归一化时间 [0, 1]

        for (int i = 0; i < clipPlayables.Count; i++)
        {
            float targetWeight = (i == targetIndex) ? 1f : 0f;
            float currentWeight = Mathf.Lerp(startWeights[i], targetWeight, t);
            mixerPlayable.SetInputWeight(i, currentWeight);
        }

        elapsedTime += Time.deltaTime;
        yield return null;
    }

    // 确保权重精确到目标值（避免浮点误差）
    for (int i = 0; i < clipPlayables.Count; i++)
        mixerPlayable.SetInputWeight(i, (i == targetIndex) ? 1f : 0f);
}
```

**设计要点：**

1. **快照起始权重**：`startWeights` 记录过渡开始时每个动画的权重，允许从任意状态（包括正在过渡中）开始新过渡
2. **线性 Lerp**：简单但有效。如需更自然的过渡感，可改为 Easing 函数（ease-in/out）
3. **最终精确化**：避免浮点误差累积，循环结束后强制设置精确的目标权重

---

## 四、OnDestroy 的清理

```csharp
void OnDestroy()
{
    if (playableGraph.IsValid())
    {
        playableGraph.Destroy();
    }
}
```

`PlayableGraph.Destroy()` 必须显式调用，否则会内存泄漏。`playableGraph.IsValid()` 先检查有效性，防止重复销毁。

---

## 五、应用场景

这套 Playable API 实现主要用于**角色性能预览（Profiling）**工具：

在 Scene 视图中快速预览角色的各个动画状态，验证动画资源是否正确导入，检测动画融合的视觉效果，而不需要真正进入游戏战斗流程。

---

## 六、与 Animancer 的区别

项目的主要动画系统用的是 **Animancer**（一个 Playable API 的高层封装），而这个 `PlayableAnimationPlayer` 是直接使用底层 Playable API 的工具类。

| 层级 | 系统 | 用途 |
|-----|------|-----|
| 高层 | Animancer | 战斗动画、技能动画、过场动画 |
| 中层 | Unity Animator | 少量 UI 动画 |
| 底层 | Playable API | 性能测试工具、特殊调试场景 |

理解底层 Playable API，能帮助你更好地理解 Animancer 等高层封装的工作原理，在遇到复杂问题时知道如何深入调试。

---

## 七、总结

| 概念 | 理解 |
|-----|-----|
| PlayableGraph | 动画处理的节点图 |
| AnimationClipPlayable | 单个动画片段的播放节点 |
| AnimationMixerPlayable | 多动画的权重混合器 |
| AnimationPlayableOutput | 图的输出，连接到 Animator |
| 权重管理 | `[0,1]` 范围，所有输入权重之和应为 1 |
| 协程过渡 | 每帧更新权重实现平滑融合 |

对于刚入行的同学，建议先从 Animator Controller 开始，理解动画状态机后，再学习 Playable API 的底层控制。Playable API 的强大在于灵活性，但这也意味着你需要自己管理很多 Animator Controller 帮你处理的细节。
