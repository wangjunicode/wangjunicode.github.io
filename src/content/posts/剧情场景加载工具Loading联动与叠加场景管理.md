---
title: 剧情场景加载工具：Loading 联动与叠加场景管理
published: 2026-03-31
description: 深入解析剧情节点图中的场景加载工具实现，包含 Loading 界面的智能触发、主场景与叠加场景的同步加载，以及光照贴图的动态绑定机制。
tags: [Unity, 场景管理, 剧情系统, Loading]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 剧情场景加载工具：Loading 联动与叠加场景管理

## 前言

剧情系统需要在玩家"阅读"NodeCanvas 流图时，无缝切换场景背景——对话场景从教室变成走廊，从走廊变成操场。每次切换都可能需要：
- 显示 Loading 界面（如果场景还没加载）
- 主场景 + 多个叠加场景（Additive）同时加载
- 动态配置光照贴图

本文通过分析 `LoadStorySceneUtil`，理解剧情场景加载的完整流程。

---

## 一、两种加载模式

```csharp
public static async ETTask LoadStoryScene<T>(
    int sceneID, T flowNode, ...)
{
    if (!UILoadingComponent.HasLoading())
    {
        // 模式1：当前没有 Loading → 由本节点触发并控制 Loading
        bool hasLoading = await TriggerSwitchStorySceneLoading(sceneID);
        await LoadSceneInternal(...);
        if (hasLoading)
            await HideCurLoading(); // 本节点负责关闭
    }
    else
    {
        // 模式2：外部已有 Loading → 直接加载，不干扰外部 Loading
        RecordStorySceneID(sceneID);
        await LoadSceneInternal(...);
    }
}
```

**为什么需要两种模式？**

当剧情节点被嵌入在一个更大的流程（比如从地图切换进入剧情，外层已经显示 Loading）中时，剧情节点不应该再触发一个新的 Loading。

`HasLoading()` 检测当前是否已有 Loading 正在显示：
- **没有 Loading**：本节点主动触发，也负责关闭
- **已有 Loading**：搭顺风车，直接在 Loading 下加载，外层负责关闭

---

## 二、Loading 的智能触发

```csharp
bool hasLoading = await StoryComponent.TriggerSwitchStorySceneLoading(sceneID);
```

`TriggerSwitchStorySceneLoading` 内部逻辑（推断）：
- 如果目标场景已经缓存（SceneLoaderComponent 中 ReferenceCount > 0），不需要 Loading
- 如果是全新加载，触发 Loading 并返回 `true`

只有在真正需要等待的情况下才显示 Loading，已缓存的场景切换瞬间完成，不需要任何提示。

---

## 三、加载理由系统（Reason）的集成

```csharp
if (string.IsNullOrEmpty(reason))
{
    reason = DialogueUtil.GetSceneReason(flowNode, sceneID);
}

flowNode.sceneObj = await sceneLoaderComponent.LoadScene(
    loader, loadSceneId, reason, checkReason: checkReason);
```

注意每次加载都必须提供 `reason`——这是 `SceneLoaderComponent` 引用计数系统的要求（详见"场景加载与引用计数管理"一文）。

`DialogueUtil.GetSceneReason(flowNode, sceneID)` 生成一个唯一的原因字符串，通常是 `"对话节点ID_场景ID"` 格式，保证同一个节点的加载和卸载能正确配对。

---

## 四、叠加场景的同步加载

```csharp
if (additive && storyScene != null)
{
    var AdditiveSceneRes = await sceneLoaderComponent.LoadSceneAddition(
        loader, loadSceneId, reason, checkReason: checkReason);

    foreach (var additiveSceneObj in AdditiveSceneRes)
    {
        flowNode.additiveSceneObjs?.Add(additiveSceneObj);
        cutscene?.AdditiveScenes?.Add(additiveSceneObj);  // 同时注册到 Cutscene
    }
}
```

叠加场景（Additive Scene）的处理有两个接收方：

| 接收方 | 字段 | 用途 |
|-------|------|------|
| FlowNode | `additiveSceneObjs` | 节点持有引用，负责释放 |
| Cutscene | `AdditiveScenes` | Cutscene 在场景中寻找挂点时查找这里 |

**为什么 Cutscene 需要知道叠加场景？**

SLATE Cinematic Sequencer（Cutscene 工具）在播放动画时，需要找到场景中的目标对象（角色站位点、特效挂点等）。这些对象可能在叠加场景中，所以 `AdditiveScenes` 列表让 Cutscene 的查找范围扩展到叠加场景。

---

## 五、动态光照贴图绑定

```csharp
if (flowNode.sceneObj != null &&
    flowNode.sceneObj.TryGetComponent<SceneObjManager>(out var sceneManager) &&
    sceneManager != null)
{
    var sceneCfg = CfgManager.tables.TbStoryScene.GetOrDefault(loadSceneId);
    if (sceneCfg != null && sceneCfg.SceneLightmapDatas.Length > 0)
    {
        sceneManager.m_LightmapDatas.Clear();
        foreach (var path in sceneCfg.SceneLightmapDatas)
        {
            var lightData = await DialogueUtil.Load<LightingProfile>(path);
            if (lightData != null)
                sceneManager.m_LightmapDatas.Add(lightData);
        }
    }
}
```

场景加载完成后，从配置表读取对应的光照贴图列表，异步加载后绑定到 `SceneObjManager`。

**这是延迟绑定（Lazy Binding）模式：**

场景 Prefab 本身不硬引用光照贴图资源（避免 Prefab 过大）。光照贴图由配置表管理，加载时动态绑定。这样：
- 不同剧情场景可以复用同一个场景 Prefab，配不同的光照
- 光照资源可以按需加载，不会全部常驻内存

---

## 六、泛型约束的用途

```csharp
public static async ETTask LoadStoryScene<T>(
    int sceneID,
    T flowNode,
    ...)
    where T : FlowNode, ICutsceneNode
```

泛型约束 `where T : FlowNode, ICutsceneNode` 要求：
- `T` 必须是 `FlowNode`（NodeCanvas 的节点基类）：确保可以访问节点的 `ClientScene`、`sceneObj` 等属性
- `T` 必须实现 `ICutsceneNode`：确保可以调用 `OnSetSceneObj()`、访问 `ChangedCharacterDict` 等接口

这比使用接口注入（`interface`参数）更精确——调用方必须传入同时满足两个约束的类型，编译器会在类型不满足时报错，而不是等到运行时才发现。

---

## 七、`ChangedCharacterDict` 的传递

```csharp
if (cutscene != null)
{
    cutscene.ChangedCharacterDict = flowNode.ChangedCharacterDict;
}
```

`ChangedCharacterDict` 存储了"在场景切换前，哪些角色已经做了哪些变化"。把这个字典传给 Cutscene，使得过场动画能够感知场景中角色的当前状态，而不是从默认状态重新开始。

---

## 八、错误处理

```csharp
if (sceneLoaderComponent == null)
{
    return;  // 直接返回，不崩溃
}
```

`GetOrAddComponent` 理论上不会返回 null，但这里做了防御性检查。对于场景加载这种关键路径，"无声地失败"（不崩溃但不执行）比"抛出异常"更安全——至少游戏还能继续运行，玩家可能只是少看到了一个场景。

---

## 九、总结

| 设计要点 | 解决的问题 |
|---------|-----------|
| 双模式（有无外层 Loading）| 嵌套流程中不重复显示 Loading |
| 智能触发 Loading | 已缓存场景不触发，避免闪烁 |
| Reason 系统集成 | 正确配对加载和卸载 |
| 叠加场景双注册 | 节点持有 + Cutscene 可访问 |
| 延迟光照贴图绑定 | 场景 Prefab 轻量化，光照按需加载 |
| 泛型约束 | 编译时类型安全保证 |

这个工具类是剧情系统和场景管理系统的"连接器"——它不属于任何一个系统，但把两者的功能组合成了剧情节点所需要的精确行为。这种"工具类"的设计模式在大型项目中极其常见，值得仔细学习。
