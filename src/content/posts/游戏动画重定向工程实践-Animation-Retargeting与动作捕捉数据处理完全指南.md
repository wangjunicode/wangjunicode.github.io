---
title: 游戏动画重定向工程实践：Animation Retargeting与动作捕捉数据处理完全指南
published: 2026-05-08
description: 深入讲解Unity动画重定向（Animation Retargeting）的工作原理、Humanoid Avatar骨骼映射体系、不同体型角色间的动画共享方案，以及动作捕捉BVH/FBX数据的清洗流程，包含完整的编辑器工具与运行时重定向实践代码。
tags: [动画, 骨骼动画, 重定向, 动作捕捉, Unity, 游戏开发]
category: 动画
draft: false
---

# 游戏动画重定向工程实践：Animation Retargeting与动作捕捉数据处理完全指南

## 1. 动画重定向的价值与挑战

### 1.1 为什么需要动画重定向

在一款角色类游戏中，可能有几十个不同体型的英雄，每个角色都需要数百个动作。如果每个角色独立制作所有动画，美术成本将是不可接受的。

**动画重定向（Animation Retargeting）** 解决了这个问题：
- 一套基础动画（走、跑、跳、攻击）可以被**所有 Humanoid 角色共用**
- 每个角色通过 Avatar 定义其骨骼比例，重定向系统自动适配
- 运动捕捉数据可以直接应用到任意体型角色，无需逐一调整

**典型收益：**

| 场景 | 无重定向 | 有重定向 |
|------|---------|---------|
| 10 个英雄 × 200 个动作 | 2000 套动画资产 | 200 套动画 + 10 个 Avatar |
| 动作捕捉接入 | 需针对每个角色重新绑定 | 绑定一次 Avatar 即可共用 |
| 动画修改成本 | 每个角色独立修改 | 修改一套，所有角色生效 |

### 1.2 核心挑战

动画重定向不是简单的骨骼数据拷贝，需要解决：

1. **骨骼比例差异**：矮人的腿短，高精灵的腿长，同一走路动画应用后步距不同
2. **骨骼结构差异**：有的骨骼有 Twist Bone（扭转骨），有的没有
3. **世界空间对齐**：脚部不应悬空或穿地（需要 Foot IK 修正）
4. **手部接触点**：握持武器时，不同体型的手骨位置不同
5. **面部与手指**：Humanoid 系统不包含面部骨骼，需要单独处理

---

## 2. Unity Avatar 骨骼映射系统

### 2.1 Humanoid Avatar 原理

Unity 的 Humanoid 系统定义了一套**标准骨骼空间（Normalized Space）**，也称为"人形肌肉空间"：

```
标准骨骼定义（共 22 个必需骨骼 + 可选骨骼）：
必需：Hips, Spine, Chest, Neck, Head
      Left/Right: Shoulder, UpperArm, LowerArm, Hand
      Left/Right: UpperLeg, LowerLeg, Foot
可选：UpperChest, Jaw, LeftEye/RightEye
     Toe, Fingers（各 3 个关节 x 5 根 x 2 手 = 30 个可选）
```

**Avatar 的两层抽象：**

```
原始骨骼层（Character Skeleton）
    └── Avatar 映射（骨骼名称 → 标准骨骼角色）
            └── 肌肉定义（关节旋转范围限制）
                    └── 标准人形空间（Normalized Muscle Values）
                            └── 另一角色的 Avatar 映射（逆向）
                                    └── 目标角色骨骼
```

当动画曲线以"肌肉值"形式存储时，它可以驱动任何配置了 Avatar 的角色，且自动适配体型比例。

### 2.2 手动配置 Avatar（编辑器实践）

```csharp
// AvatarConfigHelper.cs - 辅助检查 Avatar 配置质量
using UnityEditor;
using UnityEngine;

public static class AvatarConfigHelper
{
    [MenuItem("Tools/Animation/Validate All Avatars")]
    public static void ValidateAllAvatars()
    {
        // 找到项目中所有 FBX 导入的 Avatar
        string[] guids = AssetDatabase.FindAssets("t:Avatar");
        int errorCount = 0;
        
        foreach (string guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var avatar = AssetDatabase.LoadAssetAtPath<Avatar>(path);
            
            if (avatar == null) continue;
            if (!avatar.isHuman) continue;  // 只检查 Humanoid Avatar
            
            if (!avatar.isValid)
            {
                Debug.LogError($"[Avatar] 无效的 Avatar: {path}", avatar);
                errorCount++;
                continue;
            }
            
            // 检查 T-Pose 是否正确（手臂是否水平）
            ValidateTpose(avatar, path);
        }
        
        Debug.Log($"[Avatar] 检查完成，共发现 {errorCount} 个错误");
    }

    private static void ValidateTpose(Avatar avatar, string assetPath)
    {
        // 获取 Avatar 的骨骼描述
        var desc = avatar.humanDescription;
        
        // 检查关键比例
        float armSpan = desc.armStretch;
        float legLength = desc.legStretch;
        
        if (Mathf.Abs(armSpan) > 0.05f)
            Debug.LogWarning($"[Avatar] {assetPath}: armStretch={armSpan:F3}，建议调整 T-Pose 使手臂水平", avatar);
        
        if (Mathf.Abs(legLength) > 0.05f)
            Debug.LogWarning($"[Avatar] {assetPath}: legStretch={legLength:F3}，建议调整 T-Pose 使腿部伸直", avatar);
    }
}
```

### 2.3 代码创建 Avatar（运行时动态绑定）

```csharp
// RuntimeAvatarBuilder.cs - 运行时为非标准骨骼角色创建 Avatar
using UnityEngine;
using System.Collections.Generic;

public static class RuntimeAvatarBuilder
{
    /// <summary>
    /// 为给定骨骼层级动态创建 Humanoid Avatar
    /// boneMappings: 标准骨骼名称 → 实际骨骼 Transform 的映射
    /// </summary>
    public static Avatar BuildAvatar(Transform root, 
        Dictionary<HumanBodyBones, Transform> boneMappings)
    {
        var skeletonBones = new List<SkeletonBone>();
        var humanBones = new List<HumanBone>();
        
        // 遍历所有骨骼，生成 SkeletonBone 列表
        CollectSkeletonBones(root, skeletonBones);
        
        // 生成 HumanBone 列表（标准骨骼 → 实际骨骼名称映射）
        foreach (var (boneType, boneTrans) in boneMappings)
        {
            if (boneTrans == null) continue;
            humanBones.Add(new HumanBone
            {
                humanName = HumanTrait.BoneName[(int)boneType],
                boneName = boneTrans.name,
                limit = new HumanLimit { useDefaultValues = true }
            });
        }
        
        var humanDesc = new HumanDescription
        {
            human = humanBones.ToArray(),
            skeleton = skeletonBones.ToArray(),
            armStretch = 0.05f,
            legStretch = 0.05f,
            upperArmTwist = 0.5f,
            lowerArmTwist = 0.5f,
            upperLegTwist = 0.1f,
            lowerLegTwist = 0.1f,
            feetSpacing = 0f,
            hasTranslationDoF = false
        };
        
        return AvatarBuilder.BuildHumanAvatar(root.gameObject, humanDesc);
    }

    private static void CollectSkeletonBones(Transform t, List<SkeletonBone> result)
    {
        result.Add(new SkeletonBone
        {
            name = t.name,
            position = t.localPosition,
            rotation = t.localRotation,
            scale = t.localScale
        });
        
        for (int i = 0; i < t.childCount; i++)
            CollectSkeletonBones(t.GetChild(i), result);
    }
}
```

---

## 3. 动作捕捉数据处理工作流

### 3.1 BVH 文件解析与导入

BVH（Biovision Hierarchy）是动作捕捉行业的标准格式，Unity 不原生支持，需要解析后转换为 AnimationClip：

```csharp
// BvhImporter.cs - BVH 文件解析器
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

public class BvhParser
{
    public class BvhJoint
    {
        public string Name;
        public Vector3 Offset;
        public List<string> Channels = new();  // XPOSITION, YPOSITION, ZPOSITION, XROTATION, etc.
        public List<BvhJoint> Children = new();
    }

    public class BvhData
    {
        public BvhJoint Root;
        public int FrameCount;
        public float FrameTime;  // 每帧时间（秒）
        public float[][] Frames;  // [帧索引][通道数据]
    }

    public static BvhData Parse(string filePath)
    {
        var lines = File.ReadAllLines(filePath);
        var data = new BvhData();
        int lineIndex = 0;
        
        // 解析 HIERARCHY 部分
        while (lineIndex < lines.Length && lines[lineIndex].Trim() != "MOTION")
        {
            if (lines[lineIndex].Trim().StartsWith("ROOT"))
            {
                data.Root = ParseJoint(lines, ref lineIndex);
            }
            lineIndex++;
        }
        
        // 解析 MOTION 部分
        lineIndex++;  // 跳过 "MOTION"
        data.FrameCount = int.Parse(lines[lineIndex++].Replace("Frames:", "").Trim());
        data.FrameTime = float.Parse(lines[lineIndex++].Replace("Frame Time:", "").Trim());
        
        data.Frames = new float[data.FrameCount][];
        for (int i = 0; i < data.FrameCount; i++)
        {
            var values = lines[lineIndex++].Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
            data.Frames[i] = Array.ConvertAll(values, float.Parse);
        }
        
        return data;
    }

    private static BvhJoint ParseJoint(string[] lines, ref int lineIndex)
    {
        var parts = lines[lineIndex].Trim().Split(' ');
        var joint = new BvhJoint { Name = parts[^1] };
        lineIndex++;  // 跳过 "{"
        lineIndex++;

        while (lineIndex < lines.Length)
        {
            string line = lines[lineIndex].Trim();
            if (line == "}") { break; }
            else if (line.StartsWith("OFFSET"))
            {
                var v = line.Split(' ');
                joint.Offset = new Vector3(float.Parse(v[1]), float.Parse(v[2]), float.Parse(v[3]));
            }
            else if (line.StartsWith("CHANNELS"))
            {
                var parts2 = line.Split(' ');
                int count = int.Parse(parts2[1]);
                for (int i = 0; i < count; i++)
                    joint.Channels.Add(parts2[2 + i]);
            }
            else if (line.StartsWith("JOINT") || line.StartsWith("End Site"))
            {
                var child = ParseJoint(lines, ref lineIndex);
                joint.Children.Add(child);
            }
            lineIndex++;
        }
        return joint;
    }
}
```

### 3.2 BVH 转 AnimationClip

```csharp
// BvhToAnimationClip.cs - 将解析后的 BVH 数据转换为 Unity AnimationClip
using UnityEngine;
using System.Collections.Generic;

#if UNITY_EDITOR
using UnityEditor;
#endif

public static class BvhConverter
{
    public static AnimationClip Convert(BvhParser.BvhData bvhData, 
        Dictionary<string, string> boneNameMapping,  // BVH骨骼名 → Unity骨骼名
        float scaleFactor = 0.01f)  // cm → m 转换
    {
        var clip = new AnimationClip();
        clip.frameRate = 1f / bvhData.FrameTime;
        
        // 为每个关节建立曲线容器
        var curvesPos = new Dictionary<string, AnimationCurve[]>();  // [3] = X,Y,Z
        var curvesRot = new Dictionary<string, AnimationCurve[]>();  // [4] = X,Y,Z,W（四元数）

        // 初始化曲线
        InitCurves(bvhData.Root, curvesPos, curvesRot, boneNameMapping);
        
        // 填充帧数据
        int channelOffset = 0;
        FillCurves(bvhData.Root, bvhData.Frames, bvhData.FrameTime,
            ref channelOffset, curvesPos, curvesRot, boneNameMapping, scaleFactor);
        
        // 将曲线写入 AnimationClip
        foreach (var (bonePath, curves) in curvesPos)
        {
            clip.SetCurve(bonePath, typeof(Transform), "localPosition.x", curves[0]);
            clip.SetCurve(bonePath, typeof(Transform), "localPosition.y", curves[1]);
            clip.SetCurve(bonePath, typeof(Transform), "localPosition.z", curves[2]);
        }
        foreach (var (bonePath, curves) in curvesRot)
        {
            clip.SetCurve(bonePath, typeof(Transform), "localRotation.x", curves[0]);
            clip.SetCurve(bonePath, typeof(Transform), "localRotation.y", curves[1]);
            clip.SetCurve(bonePath, typeof(Transform), "localRotation.z", curves[2]);
            clip.SetCurve(bonePath, typeof(Transform), "localRotation.w", curves[3]);
        }
        
        return clip;
    }

    private static void InitCurves(BvhParser.BvhJoint joint,
        Dictionary<string, AnimationCurve[]> pos,
        Dictionary<string, AnimationCurve[]> rot,
        Dictionary<string, string> mapping)
    {
        string unityName = mapping.TryGetValue(joint.Name, out var n) ? n : joint.Name;
        
        bool hasPos = joint.Channels.Contains("Xposition");
        bool hasRot = joint.Channels.Contains("Xrotation");
        
        if (hasPos) pos[unityName] = new[] { new AnimationCurve(), new AnimationCurve(), new AnimationCurve() };
        if (hasRot) rot[unityName] = new[] { new AnimationCurve(), new AnimationCurve(), new AnimationCurve(), new AnimationCurve() };
        
        foreach (var child in joint.Children)
            InitCurves(child, pos, rot, mapping);
    }

    private static void FillCurves(BvhParser.BvhJoint joint, float[][] frames, float frameTime,
        ref int channelOffset, Dictionary<string, AnimationCurve[]> pos,
        Dictionary<string, AnimationCurve[]> rot,
        Dictionary<string, string> mapping, float scale)
    {
        string unityName = mapping.TryGetValue(joint.Name, out var n) ? n : joint.Name;
        int localOffset = channelOffset;
        channelOffset += joint.Channels.Count;
        
        for (int f = 0; f < frames.Length; f++)
        {
            float t = f * frameTime;
            var frame = frames[f];
            
            int ci = localOffset;
            Vector3 position = Vector3.zero;
            Vector3 eulerAngles = Vector3.zero;
            bool hasPos = false, hasRot = false;
            
            foreach (string ch in joint.Channels)
            {
                switch (ch)
                {
                    case "Xposition": position.x =  frame[ci] * scale; hasPos = true; break;
                    case "Yposition": position.y =  frame[ci] * scale; hasPos = true; break;
                    case "Zposition": position.z = -frame[ci] * scale; hasPos = true; break;  // BVH是右手系
                    case "Xrotation": eulerAngles.x = -frame[ci]; hasRot = true; break;
                    case "Yrotation": eulerAngles.y = -frame[ci]; hasRot = true; break;
                    case "Zrotation": eulerAngles.z =  frame[ci]; hasRot = true; break;
                }
                ci++;
            }
            
            if (hasPos && pos.TryGetValue(unityName, out var pc))
            {
                pc[0].AddKey(t, position.x);
                pc[1].AddKey(t, position.y);
                pc[2].AddKey(t, position.z);
            }
            
            if (hasRot && rot.TryGetValue(unityName, out var rc))
            {
                var q = Quaternion.Euler(eulerAngles);
                rc[0].AddKey(t, q.x);
                rc[1].AddKey(t, q.y);
                rc[2].AddKey(t, q.z);
                rc[3].AddKey(t, q.w);
            }
        }
        
        foreach (var child in joint.Children)
            FillCurves(child, frames, frameTime, ref channelOffset, pos, rot, mapping, scale);
    }
}
```

---

## 4. 动画曲线清洗与降噪

动作捕捉原始数据通常有噪点，需要清洗后才能投入游戏使用：

```csharp
// AnimationCurveCleaner.cs - 动画曲线清洗工具
#if UNITY_EDITOR
using UnityEditor;
#endif
using UnityEngine;

public static class AnimationCurveCleaner
{
    /// <summary>
    /// 对动画曲线应用高斯平滑滤波（消除抖动噪点）
    /// </summary>
    public static AnimationCurve SmoothCurve(AnimationCurve source, int windowSize = 5, float sigma = 1.5f)
    {
        var keys = source.keys;
        if (keys.Length < windowSize) return source;
        
        // 计算高斯权重
        float[] weights = new float[windowSize];
        float sum = 0f;
        int half = windowSize / 2;
        for (int i = 0; i < windowSize; i++)
        {
            float x = i - half;
            weights[i] = Mathf.Exp(-(x * x) / (2 * sigma * sigma));
            sum += weights[i];
        }
        for (int i = 0; i < windowSize; i++) weights[i] /= sum;
        
        // 应用平滑
        var newKeys = new Keyframe[keys.Length];
        for (int i = 0; i < keys.Length; i++)
        {
            float value = 0f;
            for (int j = 0; j < windowSize; j++)
            {
                int idx = Mathf.Clamp(i + j - half, 0, keys.Length - 1);
                value += keys[idx].value * weights[j];
            }
            newKeys[i] = new Keyframe(keys[i].time, value);
        }
        
        var result = new AnimationCurve(newKeys);
        // 重新计算切线
        for (int i = 0; i < result.length; i++)
            result.SmoothTangents(i, 0);
        return result;
    }

    /// <summary>
    /// 压缩动画曲线：移除误差小于阈值的关键帧（减少存储大小）
    /// </summary>
    public static AnimationCurve CompressCurve(AnimationCurve source, float errorThreshold = 0.0001f)
    {
        var keys = source.keys;
        if (keys.Length <= 2) return source;
        
        var keepKeys = new System.Collections.Generic.List<Keyframe> { keys[0] };
        
        for (int i = 1; i < keys.Length - 1; i++)
        {
            // 线性插值估算该点的值
            float t0 = keys[i - 1].time, v0 = keys[i - 1].value;
            float t1 = keys[i + 1].time, v1 = keys[i + 1].value;
            float t = keys[i].time;
            float lerped = Mathf.Lerp(v0, v1, (t - t0) / (t1 - t0));
            
            // 若实际值与线性插值差异超过阈值，保留该关键帧
            if (Mathf.Abs(keys[i].value - lerped) > errorThreshold)
                keepKeys.Add(keys[i]);
        }
        
        keepKeys.Add(keys[^1]);
        Debug.Log($"[Compress] 从 {keys.Length} 帧压缩至 {keepKeys.Count} 帧 " +
                 $"（减少 {(1f - (float)keepKeys.Count / keys.Length) * 100:F1}%）");
        return new AnimationCurve(keepKeys.ToArray());
    }

#if UNITY_EDITOR
    /// <summary>
    /// 批量清洗选中的 AnimationClip 资产
    /// </summary>
    [MenuItem("Tools/Animation/Clean Selected Clips")]
    public static void CleanSelectedClips()
    {
        foreach (var obj in Selection.objects)
        {
            if (obj is not AnimationClip clip) continue;
            
            var bindings = AnimationUtility.GetCurveBindings(clip);
            foreach (var binding in bindings)
            {
                var curve = AnimationUtility.GetEditorCurve(clip, binding);
                var smoothed = SmoothCurve(curve, windowSize: 5);
                var compressed = CompressCurve(smoothed, errorThreshold: 0.0005f);
                AnimationUtility.SetEditorCurve(clip, binding, compressed);
            }
            
            EditorUtility.SetDirty(clip);
            Debug.Log($"[AnimClean] 已清洗: {clip.name}");
        }
        AssetDatabase.SaveAssets();
    }
#endif
}
```

---

## 5. 运行时重定向：不同体型角色动画共享

### 5.1 Foot IK 修正（防止脚悬空）

```csharp
// FootIKSolver.cs - 运行时 Foot IK，修正重定向后的脚部穿地/悬空
using UnityEngine;

[RequireComponent(typeof(Animator))]
public class FootIKSolver : MonoBehaviour
{
    [Header("IK 权重")]
    [Range(0f, 1f)] public float IKPositionWeight = 1f;
    [Range(0f, 1f)] public float IKRotationWeight = 0.5f;

    [Header("射线检测")]
    public float RaycastOriginHeight = 1f;  // 射线起点高度（避免从地面内部发射）
    public float RaycastDistance = 1.5f;
    public LayerMask GroundLayer;
    public float FootOffset = 0.05f;  // 脚与地面的偏移（鞋底厚度）

    private Animator _animator;
    
    // 左右脚的 IK 目标（平滑处理避免抖动）
    private Vector3 _leftFootPos, _rightFootPos;
    private Quaternion _leftFootRot, _rightFootRot;
    private float _leftWeight, _rightWeight;

    private void Awake()
    {
        _animator = GetComponent<Animator>();
    }

    private void OnAnimatorIK(int layerIndex)
    {
        if (!_animator) return;
        
        // 处理左脚
        SolveFootIK(AvatarIKGoal.LeftFoot, 
            ref _leftFootPos, ref _leftFootRot, ref _leftWeight);
        
        // 处理右脚
        SolveFootIK(AvatarIKGoal.RightFoot, 
            ref _rightFootPos, ref _rightFootRot, ref _rightWeight);
    }

    private void SolveFootIK(AvatarIKGoal goal, 
        ref Vector3 targetPos, ref Quaternion targetRot, ref float weight)
    {
        // 获取动画系统计算出的脚部位置
        Vector3 footAnimPos = _animator.GetIKPosition(goal);
        
        // 从脚部上方向下发射射线
        Ray ray = new Ray(footAnimPos + Vector3.up * RaycastOriginHeight, Vector3.down);
        
        if (Physics.Raycast(ray, out RaycastHit hit, RaycastDistance + RaycastOriginHeight, GroundLayer))
        {
            // 计算脚应该落在的位置
            Vector3 desiredPos = hit.point + Vector3.up * FootOffset;
            
            // 平滑过渡，避免突变
            targetPos = Vector3.Lerp(targetPos, desiredPos, Time.deltaTime * 15f);
            
            // 计算地面法线对应的脚部旋转
            Quaternion desiredRot = Quaternion.LookRotation(
                Vector3.ProjectOnPlane(transform.forward, hit.normal), hit.normal);
            targetRot = Quaternion.Slerp(targetRot, desiredRot, Time.deltaTime * 10f);
            
            // 根据脚与地面的距离调整 IK 权重（靠近地面时权重高）
            float distToGround = Vector3.Distance(footAnimPos, hit.point);
            weight = Mathf.Lerp(weight, 1f - Mathf.Clamp01(distToGround * 2f), Time.deltaTime * 10f);
        }
        else
        {
            weight = Mathf.Lerp(weight, 0f, Time.deltaTime * 10f);
        }
        
        float finalWeight = weight * IKPositionWeight;
        _animator.SetIKPositionWeight(goal, finalWeight);
        _animator.SetIKRotationWeight(goal, finalWeight * IKRotationWeight);
        _animator.SetIKPosition(goal, targetPos);
        _animator.SetIKRotation(goal, targetRot);
    }

    private void OnDrawGizmosSelected()
    {
        if (!_animator) return;
        Gizmos.color = Color.green;
        Gizmos.DrawWireSphere(_leftFootPos, 0.05f);
        Gizmos.DrawWireSphere(_rightFootPos, 0.05f);
    }
}
```

### 5.2 手部武器对齐 IK

```csharp
// WeaponHandIK.cs - 确保持武器时手部与武器握柄对齐
using UnityEngine;

[RequireComponent(typeof(Animator))]
public class WeaponHandIK : MonoBehaviour
{
    [Header("武器握柄点")]
    public Transform RightHandGrip;   // 武器上的右手握柄 Transform
    public Transform LeftHandGrip;    // 双手武器时的左手辅助握柄

    [Header("IK 权重")]
    [Range(0f, 1f)] public float RightHandWeight = 1f;
    [Range(0f, 1f)] public float LeftHandWeight = 0f;  // 单手武器默认关闭左手 IK

    [Header("过渡速度")]
    public float WeightTransitionSpeed = 10f;

    private Animator _animator;
    private float _currentRightWeight, _currentLeftWeight;

    private void Awake() => _animator = GetComponent<Animator>();

    private void OnAnimatorIK(int layerIndex)
    {
        // 右手 IK
        if (RightHandGrip != null)
        {
            _currentRightWeight = Mathf.MoveTowards(
                _currentRightWeight, RightHandWeight, Time.deltaTime * WeightTransitionSpeed);
            _animator.SetIKPositionWeight(AvatarIKGoal.RightHand, _currentRightWeight);
            _animator.SetIKRotationWeight(AvatarIKGoal.RightHand, _currentRightWeight);
            _animator.SetIKPosition(AvatarIKGoal.RightHand, RightHandGrip.position);
            _animator.SetIKRotation(AvatarIKGoal.RightHand, RightHandGrip.rotation);
        }

        // 左手 IK（双手武器）
        if (LeftHandGrip != null && _currentLeftWeight > 0.01f)
        {
            _currentLeftWeight = Mathf.MoveTowards(
                _currentLeftWeight, LeftHandWeight, Time.deltaTime * WeightTransitionSpeed);
            _animator.SetIKPositionWeight(AvatarIKGoal.LeftHand, _currentLeftWeight);
            _animator.SetIKRotationWeight(AvatarIKGoal.LeftHand, _currentLeftWeight);
            _animator.SetIKPosition(AvatarIKGoal.LeftHand, LeftHandGrip.position);
            _animator.SetIKRotation(AvatarIKGoal.LeftHand, LeftHandGrip.rotation);
        }
    }

    /// <summary>
    /// 切换武器时动态更新握柄点
    /// </summary>
    public void SetWeapon(Transform rightGrip, Transform leftGrip = null, 
        float rightWeight = 1f, float leftWeight = 0f)
    {
        RightHandGrip = rightGrip;
        LeftHandGrip = leftGrip;
        RightHandWeight = rightWeight;
        LeftHandWeight = leftWeight;
    }
}
```

---

## 6. 批量动画重定向工具

```csharp
// AnimationRetargetTool.cs - 批量将动画从源角色重定向到目标角色
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;
using System.IO;

public class AnimationRetargetTool : EditorWindow
{
    private Avatar _sourceAvatar;
    private Avatar _targetAvatar;
    private AnimationClip[] _clipsToRetarget;
    private string _outputFolder = "Assets/Animations/Retargeted";

    [MenuItem("Tools/Animation/Retarget Tool")]
    public static void ShowWindow()
    {
        GetWindow<AnimationRetargetTool>("动画重定向工具");
    }

    private void OnGUI()
    {
        GUILayout.Label("动画重定向批处理", EditorStyles.boldLabel);
        EditorGUILayout.Space();

        _sourceAvatar = (Avatar)EditorGUILayout.ObjectField(
            "源 Avatar（动画原始角色）", _sourceAvatar, typeof(Avatar), false);
        _targetAvatar = (Avatar)EditorGUILayout.ObjectField(
            "目标 Avatar（目标角色）", _targetAvatar, typeof(Avatar), false);

        EditorGUILayout.Space();
        _outputFolder = EditorGUILayout.TextField("输出目录", _outputFolder);

        EditorGUILayout.Space();
        GUILayout.Label("说明：选中要重定向的 AnimationClip，然后点击处理按钮", EditorStyles.wordWrappedLabel);

        if (GUILayout.Button("处理选中的 AnimationClip", GUILayout.Height(30)))
            RetargetSelectedClips();

        if (GUILayout.Button("一键重定向整个文件夹", GUILayout.Height(30)))
            RetargetFolder();
    }

    private void RetargetSelectedClips()
    {
        if (_targetAvatar == null)
        {
            EditorUtility.DisplayDialog("错误", "请先设置目标 Avatar", "确定");
            return;
        }

        int count = 0;
        foreach (var obj in Selection.objects)
        {
            if (obj is AnimationClip clip)
            {
                RetargetClip(clip);
                count++;
            }
        }
        AssetDatabase.SaveAssets();
        Debug.Log($"[Retarget] 完成，共处理 {count} 个 AnimationClip");
    }

    private void RetargetClip(AnimationClip sourceClip)
    {
        // 获取源动画的所有曲线
        var bindings = AnimationUtility.GetCurveBindings(sourceClip);
        var newClip = new AnimationClip
        {
            frameRate = sourceClip.frameRate,
            wrapMode = sourceClip.wrapMode,
            name = $"{sourceClip.name}_retargeted"
        };

        foreach (var binding in bindings)
        {
            var curve = AnimationUtility.GetEditorCurve(sourceClip, binding);
            // 重定向时骨骼路径可能不同，这里需要按映射关系转换路径
            string newPath = RemapBonePath(binding.path);
            var newBinding = new EditorCurveBinding
            {
                path = newPath,
                type = binding.type,
                propertyName = binding.propertyName
            };
            AnimationUtility.SetEditorCurve(newClip, newBinding, curve);
        }

        // 设置目标 Avatar（关键步骤！）
        // 通过 ModelImporter 来设置 clip 的 sourceAvatar
        Directory.CreateDirectory(_outputFolder);
        string savePath = $"{_outputFolder}/{newClip.name}.anim";
        AssetDatabase.CreateAsset(newClip, savePath);
    }

    private string RemapBonePath(string originalPath)
    {
        // 这里可以根据实际骨骼层级差异做路径替换
        // 例如：源骨骼 "Armature/Hips" → 目标骨骼 "Root/Skeleton/Hips"
        return originalPath;  // 简化示例，实际使用时需要配置映射表
    }

    private void RetargetFolder()
    {
        string folder = EditorUtility.OpenFolderPanel("选择动画文件夹", "Assets", "");
        if (string.IsNullOrEmpty(folder)) return;
        
        folder = "Assets" + folder.Substring(Application.dataPath.Length);
        string[] guids = AssetDatabase.FindAssets("t:AnimationClip", new[] { folder });
        
        foreach (string guid in guids)
        {
            string path = AssetDatabase.GUIDToAssetPath(guid);
            var clip = AssetDatabase.LoadAssetAtPath<AnimationClip>(path);
            if (clip != null) RetargetClip(clip);
        }
        
        AssetDatabase.SaveAssets();
        Debug.Log($"[Retarget] 文件夹处理完成，共 {guids.Length} 个文件");
    }
}
#endif
```

---

## 7. 最佳实践总结

| 实践 | 建议 |
|------|------|
| **T-Pose 规范** | 所有参与重定向的角色必须在严格 T-Pose 下配置 Avatar（手臂水平、掌心向下） |
| **骨骼命名统一** | 制定团队骨骼命名规范，减少 Avatar 映射错误 |
| **Foot IK 必备** | 重定向几乎必然导致脚部偏移，Foot IK 是标配而非可选项 |
| **动捕数据清洗** | 原始动捕数据必须经过噪点过滤再使用，否则动画会有明显抖动 |
| **曲线压缩** | 动捕数据每帧都有关键帧，压缩后可减少 60%~80% 数据量 |
| **Avatar 版本管理** | Avatar 资产变更会影响所有使用该 Avatar 的动画，需严格版本控制 |
| **Generic vs Humanoid** | 非人形角色（怪物、动物）用 Generic 骨骼，不要强制套 Humanoid |
| **面部动画分离** | 面部表情动画不走 Humanoid 重定向，使用 BlendShape 或单独 AnimationClip |
| **LOD 动画** | 远距离角色使用简化骨骼 + 低帧率动画，节省 CPU 采样开销 |
| **工具内嵌 CI** | 将 Avatar 验证和曲线清洗集成到资产导入管线，保证入库质量 |

---

## 结语

动画重定向是大型游戏项目控制动画资产规模的核心技术。从 Avatar 骨骼映射体系的正确配置，到动作捕捉数据的完整清洗流程，再到运行时 Foot IK 和武器手部 IK 的精细修正，每个环节都需要工程化的工具支持。建立一套规范化的重定向流水线，能够让一套高质量动作数据赋能整个角色阵容，是游戏动画系统工程化成熟度的重要标志。
