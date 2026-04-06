---
title: 场景对象分级管理与光照切换系统
published: 2026-03-31
description: 深入分析游戏场景中大家具互斥显示、摆件分层管理与动态光照贴图切换的实现原理，理解如何用代码驱动场景美术的层次变化。
tags: [Unity, 场景管理, 光照系统, 游戏开发]
category: Unity技术
draft: false
encryptedKey: henhaoji123
---

# 场景对象分级管理与光照切换系统

## 前言

在一款有"宿舍装扮""剧情场景变化"等功能的手游中，同一个场景会根据游戏进度或玩家操作呈现出不同的外观：家具可能从空房间变成布置好的温馨卧室，光照也会随之从冷色调变为暖色调。

如何高效管理这些场景对象的显示状态？如何做到切换家具的同时自动切换对应的光照贴图？本文通过 `SceneObjManager` 的实现，为你揭开场景分级管理的秘密。

---

## 一、核心设计：SubLevel（子等级）驱动

整个系统的核心概念是 **SceneSubLevel**——场景的"子等级"或"装扮阶段"：

```csharp
public void ShowItemBySubLevel(SceneSubLevel sceneSubLevel)
{
    if (_curSceneSubLevel == sceneSubLevel)
        return; // 等级未变化，无需处理

    _curSceneSubLevel = sceneSubLevel;
    // 切换大家具
    // 切换摆件
    // 切换光照贴图
}
```

调用一个方法，三件事同时发生，保证视觉表现的一致性。这就是**封装**的价值——外部调用者不需要知道内部切换了多少东西。

---

## 二、两类场景对象：大家具 vs 摆件

```csharp
public List<GameObject>  m_FurnituresList = new List<GameObject>();
// 大家具：一定互斥，且影响光照贴图，必须互斥

public GameObjectArray[] m_PartsList;
// 摆件：可以随意操作，可能有交叉，所以要分 sublevel 单独处理
```

这两个注释非常精确地描述了设计约束：

### 大家具（Furnitures）
- **互斥**：同一时刻只能显示一套家具（对应一个 SubLevel）
- **影响光照**：大家具改变了场景的遮挡关系，烘焙光照也需要对应切换
- **实现**：`List<GameObject>` 中每个元素是一套家具，通过 `SetActive(i == subLevel)` 实现互斥

```csharp
for (int i = 0; i < m_FurnituresList.Count; i++)
{
    if (m_FurnituresList[i] == null) continue;
    m_FurnituresList[i].SetActive(i == subLevel);  // 只激活目标等级
}
```

### 摆件（Parts）
- **非互斥**：不同等级的摆件可能在位置上有交叉，不能简单"全关再开一个"
- **按组管理**：`GameObjectArray[]` 中每组对应一个 SubLevel 的所有摆件

```csharp
[System.Serializable]
public class GameObjectArray
{
    public GameObject[] goList;  // 一组摆件
}
```

---

## 三、摆件切换的精细逻辑

摆件的切换比大家具复杂，因为需要处理"父节点可能被隐藏"的美术容错：

```csharp
// 关闭非目标等级的所有摆件
for (int i = 0; i < m_PartsList.Length; i++)
{
    if (i == partsLevel || m_PartsList[i] == null) continue;

    foreach (var go in m_PartsList[i].goList)
    {
        if (go == null) continue;

        // 美术总是隐藏父节点，程序兜底一下
        if (go.transform.parent != null && !go.transform.parent.gameObject.activeSelf)
        {
            go.transform.parent.gameObject.SetActive(true);
        }
        go.SetActive(false);
    }
}

// 激活目标等级的摆件
foreach (var go in parts)
{
    if (go == null) continue;
    go.SetActive(true);
    if (m_LightmapData != null)
        m_LightmapData.UpdateCacheRenderer(go);  // 更新光照贴图缓存
}
```

**"美术总是隐藏父节点"的 Bug 预防：**

这行注释是实际项目中非常典型的"程序防美术"逻辑。美术同学可能为了快速隐藏一组物体而直接关掉父节点，但代码层面是精确控制每个子节点的显示状态。如果父节点被隐藏，子节点的 `SetActive(false)` 实际上是无效的（因为父节点已经把整棵树隐藏了）。

程序员在这里加了一个修复：遇到父节点被隐藏的情况，先把父节点显示出来，再正确处理子节点的状态。

---

## 四、动态光照贴图切换

这是整个系统最技术含量高的部分。烘焙光照贴图是静态的——但场景在不同 SubLevel 下家具摆放不同，光照效果也不同，怎么办？

答案是：**为每个 SubLevel 烘焙一张光照贴图，运行时根据 SubLevel 切换**。

```csharp
public List<LightingProfile> m_LightmapDatas = new List<LightingProfile>();
private PrefabLightmapData m_LightmapData = null;

public void InitLightmapData()
{
    if (_isInitPrefabLightmapData) return;

    gameObject.TryGetComponent<PrefabLightmapData>(out m_LightmapData);

    m_LightmapData.EnableProfile = true;
    foreach (var data in m_LightmapDatas)
    {
        m_LightmapData.lightingProfileList.Add(data);
    }
    _isInitPrefabLightmapData = true;
}

// 切换光照
if (m_LightmapData != null)
{
    int lightIndex = Mathf.Min(subLevel, m_LightmapDatas.Count - 1);
    m_LightmapData.lightingProfileIDX = lightIndex;
    m_LightmapData.SwitchLightingProfile();  // 核心切换方法
}
```

**`PrefabLightmapData`** 是一个将烘焙光照信息附加到 Prefab 的工具组件（常见于 `Prefab Lightmapping` 方案）。它的作用是把原本只属于某个 Scene 的光照贴图"绑定"到 Prefab 上，让 Prefab 在任何场景中都能正确显示光照效果。

**光照贴图索引的安全处理：**

```csharp
int lightIndex = Mathf.Min(subLevel, m_LightmapDatas.Count - 1);
```

如果 `m_LightmapDatas` 的数量少于家具等级数（比如有些等级共用同一张光照图），用 `Min` 防止越界，取最后一张作为兜底。

---

## 五、数据一致性校验

```csharp
if (m_FurnituresList.Count != m_PartsList.Length)
{
    Debug.LogError(
        $"FurnituresList.Count != m_PartsList.Count " +
        $"FurnituresList.Count {m_FurnituresList.Count} " +
        $"m_PartsList.Count {m_PartsList.Length}");
}
```

这段校验在运行时检查"大家具数量"是否与"摆件组数量"一致，因为两者必须一一对应。如果美术在 Inspector 中配置错误（比如漏填了某个 SubLevel 的摆件组），这里会给出明确的错误信息。

---

## 六、编辑器辅助工具

```csharp
public int testState = 1;

[ButtonGroup("设置"), Button("一键设置 AutoSetup")]
public static void AutoSetup()
{
    if (!Application.isPlaying) return;

    var prefabs = FindObjectsOfType<SceneObjManager>();
    foreach (var instance in prefabs)
    {
        Debug.Log($"处理SceneObjManager: {instance.gameObject.name}");
        instance.ShowItemBySubLevel((SceneSubLevel)instance.testState);
    }
}
```

这是一个 **Odin Inspector** 按钮，让开发者可以在 Play Mode 下通过点击按钮测试不同 SubLevel 的效果，而不需要写测试代码或等待特定游戏流程触发。

`FindObjectsOfType<SceneObjManager>()` 找到场景中所有实例，批量处理，方便在场景中有多个 `SceneObjManager` 时一键同步状态。

---

## 七、边界处理：索引越界保护

```csharp
int subLevel  = (int)sceneSubLevel - 1;
int partsLevel = subLevel;

if (sceneSubLevel == SceneSubLevel.None || subLevel >= m_FurnituresList.Count)
{
    subLevel  = m_FurnituresList.Count - 1;
    partsLevel = m_PartsList.Length - 1;
}

if (partsLevel >= m_PartsList.Length)
{
    partsLevel = m_PartsList.Length - 1;
}

if (subLevel >= m_FurnituresList.Count || subLevel < 0)
{
    Debug.LogError($"scene sublevel error: sublevel {subLevel}...");
    return;
}
```

这段代码展示了工程实践中的**防御性编程**：

1. `SceneSubLevel.None` 是特殊情况，映射到最后一个等级（最终状态）
2. 索引超过列表长度时，夹到最大值（而不是崩溃）
3. 最终仍有问题，输出详细错误信息并 `return`（不执行有错误的逻辑）

这层层防护看起来冗余，但在实际项目中能避免很多"配置没做好导致的偶发崩溃"。

---

## 八、完整流程总结

```
游戏逻辑触发 ShowItemBySubLevel(SubLevel.Level2)
    │
    ├── 状态未变化？→ 提前返回
    │
    ├── 初始化光照数据（只执行一次）
    │
    ├── 计算索引
    │       subLevel = (int)sceneSubLevel - 1
    │
    ├── 切换大家具
    │       只激活 index == subLevel 的那个 GameObject
    │
    ├── 切换摆件
    │       关闭其他等级的摆件（处理父节点隐藏的边界情况）
    │       激活目标等级的摆件
    │       更新光照缓存
    │
    └── 切换光照贴图
            m_LightmapData.lightingProfileIDX = lightIndex
            m_LightmapData.SwitchLightingProfile()
```

---

## 九、对新手的启示

这个系统虽然代码量不大，但包含了大量实际工程经验：

1. **单一方法驱动多个状态**：一次调用保证所有相关状态同步更新
2. **防美术容错**：不要假设美术同学的配置一定正确
3. **边界保护**：索引操作必须防止越界
4. **编辑器工具**：好的工具让开发和测试效率翻倍
5. **注释即文档**：`// 大家具一定互斥` 这类注释比任何 wiki 都更及时

场景管理不只是"SetActive"，背后涉及渲染状态、光照贴图、对象池……每一个细节都可能成为线上 Bug 的来源。
