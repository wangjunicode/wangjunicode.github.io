---
title: Unity 角色换装系统：从骨骼蒙皮理论到完整实现
published: 2021-12-12
description: "系统讲解 Unity 角色换装的完整实现方案：从骨骼蒙皮基础原理出发，对比 Mesh 合并、多 Renderer 挂载、骨骼重定向三种技术方案的优劣，提供 SkinnedMeshRenderer 骨骼绑定的完整代码实现，以及合并 Mesh 降低 DrawCall 的具体方法，并整理骨骼名称匹配、材质合并等实践注意事项。"
tags: [Unity, 游戏开发, 渲染, 角色系统]
category: 游戏开发
draft: false
---

角色换装是 RPG 游戏的标配功能，但实现起来涉及的知识点挺多的——骨骼、蒙皮、SkinnedMeshRenderer、合批……第一次做的时候踩了不少坑。这篇文章把理论和实现都讲清楚。

---

## 基础理论：骨骼与蒙皮

### 骨骼（Bone）

游戏中任何可渲染的物体本质上都是由顶点信息组成的 Mesh。静态模型不需要骨骼，但带动画的角色需要一套骨骼系统来驱动 Mesh 变形。

在 3DMax/Maya 中，有两种骨骼类型：
- **Bones**：自由度高，用于披风、旗帜、鸟类翅膀等非人形结构
- **Bip**（Biped）：按人体关节布局预设的规范化骨骼，用于脊椎动物和类人生物

骨骼是典型的父子层次结构（Transform Tree）：根骨骼（Root）→ 脊椎 → 胸腔 → 肩膀 → 上臂 → 前臂 → 手掌 → 手指……

![角色骨骼结构示意](/images/posts/角色换装/401477-20171212163155269-36336142.jpg)

### 蒙皮（Skinning）

骨骼本身不会影响 Mesh 顶点——**蒙皮**是把顶点与骨骼关联起来的过程。

每个顶点记录：
- 受哪几根骨骼影响（通常最多 4 根）
- 每根骨骼的影响权重（权重之和为 1）

当骨骼运动时，顶点的最终位置 = 各根骨骼变换矩阵的加权混合结果。

![蒙皮权重示意](/images/posts/角色换装/401477-20171212195138004-752593782.jpg)

### 动作与关键帧插值

骨骼记录每个关键帧时相对父节点的 SQT（Scale/Quaternion/Translation）。假设游戏帧率 60FPS，美术只需要在关键动作时刻插入关键帧，中间帧的骨骼姿态由引擎在两个关键帧之间**插值**计算。

**重要组件**：
- **Animator**：读取动画数据，计算当前帧每根骨骼的 Transform
- **SkinnedMeshRenderer**：读取 Animator 计算好的骨骼姿态，进行蒙皮变换，输出最终的渲染 Mesh

这也解释了一个常见困惑：为什么直接移动 `SkinnedMeshRenderer` 所在 GameObject，模型位置不变？因为渲染位置由骨骼决定，不由 GameObject 的 Transform 决定。

### 资源导出规则（重要）

换装资源的导出规则决定了程序实现方式：

1. **基础骨骼体（Base）**：包含完整骨骼（Armature）+身体核心部件（躯干、头）
2. **可替换部件**：手套/手套/裤子/上衣/头发……每种样式单独导出为 FBX
3. **关键**：所有部件导出时必须包含相同的骨骼结构，或至少包含该部件所影响的骨骼

---

## 三种换装技术方案对比

### 方案一：多 SkinnedMeshRenderer 挂载

**原理**：每个部件是独立的 `SkinnedMeshRenderer`，所有部件共享同一套骨骼。换装时，激活/禁用对应的 Renderer，或替换其 `sharedMesh`。

```csharp
// 最简单的实现
public void EquipItem(SkinnedMeshRenderer targetRenderer, Mesh newMesh, Material newMaterial)
{
    targetRenderer.sharedMesh = newMesh;
    targetRenderer.material = newMaterial;
}
```

**优点**：实现简单，部件独立，换装后不需要重建 Mesh

**缺点**：
- 每个部件 = 一个 Draw Call，角色 Draw Call 数量等于装备部件数（通常 5-10 个）
- 移动端性能较差

**适用场景**：换装不频繁、部件数量少的游戏

### 方案二：合并 Mesh（CombinedMesh）

**原理**：换装时，将所有部件的 Mesh 合并成一个 Mesh，绑定到同一套骨骼，只剩一个 `SkinnedMeshRenderer`。

**优点**：只有 1 个 Draw Call（理想情况下），性能最好

**缺点**：
- 换装时需要重建合并后的 Mesh，有一定耗时（可异步）
- 材质需要合并成图集，否则材质数量决定了 DrawCall 数量

**适用场景**：高频战斗场景，对 Draw Call 敏感的移动端游戏

### 方案三：骨骼重定向（Bone Retargeting）

**原理**：部件导出时带有自己的骨骼，运行时将部件骨骼重新绑定到角色的主骨骼上。

这是方案一的规范化实现——确保部件骨骼和角色骨骼对应关系正确。

---

## 完整实现：骨骼重定向 + Mesh 合并

### 核心工具类

```csharp
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 角色换装系统
/// 支持骨骼重定向和 Mesh 合并两种模式
/// </summary>
public class CharacterEquipmentSystem : MonoBehaviour
{
    [Header("骨骼根节点")]
    public Transform SkeletonRoot;

    [Header("当前装备的部件")]
    private readonly Dictionary<EquipSlot, SkinnedMeshRenderer> _equippedParts = new();

    public enum EquipSlot
    {
        Body,       // 躯干
        Head,       // 头部/头盔
        Weapon,     // 武器（可能不用蒙皮）
        Gloves,     // 手套
        Pants,      // 裤子
        Shoes,      // 鞋子
        Hair,       // 头发
    }

    /// <summary>
    /// 替换指定槽位的装备（骨骼重定向方式）
    /// </summary>
    public void Equip(EquipSlot slot, SkinnedMeshRenderer newPart)
    {
        // 移除旧装备
        if (_equippedParts.TryGetValue(slot, out var oldPart))
        {
            Destroy(oldPart.gameObject);
        }

        // 实例化新部件
        var partObj = Instantiate(newPart.gameObject, transform);
        var newRenderer = partObj.GetComponent<SkinnedMeshRenderer>();

        // 执行骨骼重定向
        RebindBones(newRenderer, SkeletonRoot);

        _equippedParts[slot] = newRenderer;
    }

    /// <summary>
    /// 骨骼重定向：将部件的骨骼绑定到角色骨骼树上
    /// </summary>
    private static void RebindBones(SkinnedMeshRenderer targetRenderer, Transform skeletonRoot)
    {
        // 1. 构建角色骨骼的名称 → Transform 映射表
        var boneMap = new Dictionary<string, Transform>();
        foreach (var bone in skeletonRoot.GetComponentsInChildren<Transform>())
        {
            boneMap[bone.name] = bone;
        }

        // 2. 重新绑定骨骼数组
        var originalBones = targetRenderer.bones;
        var newBones = new Transform[originalBones.Length];

        for (int i = 0; i < originalBones.Length; i++)
        {
            string boneName = originalBones[i].name;
            if (boneMap.TryGetValue(boneName, out var matchedBone))
            {
                newBones[i] = matchedBone;
            }
            else
            {
                // ⚠️ 骨骼名称不匹配，这是换装最常见的问题！
                Debug.LogWarning($"[换装] 骨骼 '{boneName}' 在角色骨骼树中未找到！检查导出设置。");
                newBones[i] = originalBones[i]; // 保持原样，但会导致渲染错误
            }
        }

        targetRenderer.bones = newBones;

        // 3. 重新绑定 RootBone（影响 Bounds 计算）
        if (boneMap.TryGetValue(targetRenderer.rootBone?.name ?? "", out var rootBone))
        {
            targetRenderer.rootBone = rootBone;
        }
    }
}
```

### 合并 Mesh 降低 DrawCall

```csharp
using System.Collections.Generic;
using UnityEngine;

public static class MeshCombiner
{
    /// <summary>
    /// 合并多个 SkinnedMeshRenderer 为一个
    /// 要求：所有部件使用同一套材质图集（单一 Material）
    /// </summary>
    public static SkinnedMeshRenderer CombineMeshes(
        List<SkinnedMeshRenderer> renderers,
        Transform skeletonRoot,
        Material combinedMaterial)
    {
        // 1. 收集所有骨骼
        var allBones = new List<Transform>();
        var boneMap = new Dictionary<string, int>(); // 骨骼名 → 在 allBones 中的 index

        foreach (var bone in skeletonRoot.GetComponentsInChildren<Transform>())
        {
            if (!boneMap.ContainsKey(bone.name))
            {
                boneMap[bone.name] = allBones.Count;
                allBones.Add(bone);
            }
        }

        // 2. 构建合并所需的 CombineInstance 数组
        var combineInstances = new List<CombineInstance>();
        var bindPoses = new List<Matrix4x4>();

        // 先收集所有 Bone Weight（需要重新映射骨骼索引）
        int vertexOffset = 0;
        var allBoneWeights = new List<BoneWeight>();

        foreach (var renderer in renderers)
        {
            var mesh = renderer.sharedMesh;
            if (mesh == null) continue;

            // 构建该部件的骨骼索引重映射表
            var localToGlobalBoneIndex = new int[renderer.bones.Length];
            for (int i = 0; i < renderer.bones.Length; i++)
            {
                string boneName = renderer.bones[i].name;
                if (boneMap.TryGetValue(boneName, out int globalIndex))
                {
                    localToGlobalBoneIndex[i] = globalIndex;
                }
                else
                {
                    localToGlobalBoneIndex[i] = 0; // 找不到就绑到根骨骼
                    Debug.LogWarning($"骨骼 {boneName} 未找到！");
                }
            }

            // 重映射 BoneWeight 的骨骼索引
            var meshBoneWeights = mesh.boneWeights;
            foreach (var bw in meshBoneWeights)
            {
                allBoneWeights.Add(new BoneWeight
                {
                    boneIndex0 = localToGlobalBoneIndex[bw.boneIndex0],
                    boneIndex1 = localToGlobalBoneIndex[bw.boneIndex1],
                    boneIndex2 = localToGlobalBoneIndex[bw.boneIndex2],
                    boneIndex3 = localToGlobalBoneIndex[bw.boneIndex3],
                    weight0 = bw.weight0,
                    weight1 = bw.weight1,
                    weight2 = bw.weight2,
                    weight3 = bw.weight3,
                });
            }

            var ci = new CombineInstance
            {
                mesh = mesh,
                transform = renderer.transform.localToWorldMatrix,
            };
            combineInstances.Add(ci);
        }

        // 3. 合并 Mesh
        var combinedMesh = new Mesh { name = "CombinedCharacterMesh" };
        combinedMesh.CombineMeshes(combineInstances.ToArray(), true, false);
        combinedMesh.boneWeights = allBoneWeights.ToArray();

        // 4. 设置 BindPoses（骨骼从绑定姿势到当前姿势的变换矩阵）
        var bindPoseArray = new Matrix4x4[allBones.Count];
        for (int i = 0; i < allBones.Count; i++)
        {
            bindPoseArray[i] = allBones[i].worldToLocalMatrix * skeletonRoot.localToWorldMatrix;
        }
        combinedMesh.bindposes = bindPoseArray;

        // 5. 创建合并后的 SkinnedMeshRenderer
        var combinedObj = new GameObject("CombinedMesh");
        combinedObj.transform.SetParent(skeletonRoot.parent);
        var smr = combinedObj.AddComponent<SkinnedMeshRenderer>();
        smr.sharedMesh = combinedMesh;
        smr.bones = allBones.ToArray();
        smr.rootBone = skeletonRoot;
        smr.material = combinedMaterial;

        return smr;
    }
}
```

### 动态图集（Material 合并）

合并 Mesh 的前提是所有部件使用同一个 Material。如果每个部件有自己的贴图，需要先把贴图合并成图集：

```csharp
public static (Texture2D atlas, Rect[] uvRects) PackTextureAtlas(
    List<Texture2D> textures, 
    int atlasSize = 2048)
{
    var atlas = new Texture2D(atlasSize, atlasSize, TextureFormat.RGBA32, false);
    var uvRects = atlas.PackTextures(textures.ToArray(), 2, atlasSize);

    // PackTextures 后需要重新调整每个部件 Mesh 的 UV 坐标
    // uvRects[i] 是第 i 张贴图在图集中的 UV 范围
    return (atlas, uvRects);
}

// 调整 Mesh UV 到图集空间
public static Mesh RemapMeshUV(Mesh mesh, Rect uvRect)
{
    var newMesh = Instantiate(mesh);
    var uvs = newMesh.uv;
    for (int i = 0; i < uvs.Length; i++)
    {
        uvs[i] = new Vector2(
            uvRect.x + uvs[i].x * uvRect.width,
            uvRect.y + uvs[i].y * uvRect.height
        );
    }
    newMesh.uv = uvs;
    return newMesh;
}
```

---

## 注意事项与踩坑总结

### 1. 骨骼名称必须严格匹配

这是换装最高频的问题。美术在 Max/Maya 里导出不同部件时，骨骼名称要保持完全一致（包括大小写）。

```
❌ 常见问题：
  角色主骨骼：Bip001_R_Hand
  手套骨骼：  Bip001 R Hand（空格 vs 下划线）

✅ 解决方案：制定导出规范，或在工具里做名称标准化处理
```

### 2. RootBone 要正确设置

`SkinnedMeshRenderer.rootBone` 影响 Bounds 的计算，进而影响遮挡剔除。如果 rootBone 不对，角色在走到屏幕边缘时可能突然消失。

### 3. 合并 Mesh 的时机

合并 Mesh 有一定 CPU 耗时（复杂角色可能 5-10ms），不应该在 Update 里做。通常在：
- 换装界面确认按钮点击后
- 角色登场动画播放期间（利用 Loading 时间）
- 异步协程中分帧处理

### 4. LOD 与合并 Mesh 的配合

合并后的单个 `SkinnedMeshRenderer` 不能直接用 Unity 的 LODGroup（LODGroup 需要多个 Renderer）。如果需要 LOD，一种方案是对不同距离准备不同精度的合并 Mesh。

### 5. 材质实例问题

换装时直接修改 `renderer.material`（不是 `sharedMaterial`）会为每个角色创建独立的材质实例，可能导致 Draw Call 不合批。推荐使用 `MaterialPropertyBlock` 来设置每角色的差异化参数（比如染色）：

```csharp
// ✅ 用 MaterialPropertyBlock 而不是修改材质实例
var mpb = new MaterialPropertyBlock();
mpb.SetColor("_TintColor", playerColor);
renderer.SetPropertyBlock(mpb);
// 这样不会破坏 SRP Batcher 合批
```
