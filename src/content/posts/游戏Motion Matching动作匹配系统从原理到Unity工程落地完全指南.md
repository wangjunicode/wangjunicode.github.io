---
title: 游戏Motion Matching动作匹配系统：从原理到Unity工程落地完全指南
published: 2026-04-09
description: 深度解析Motion Matching动作匹配技术原理，涵盖姿态数据库构建、特征提取、KD树加速查询、轨迹预测、脚步IK校正、Root Motion处理及Unity完整工程实现，助你打造次世代角色动画系统。
tags: [Unity, 动画系统, Motion Matching, 角色动画, 游戏开发]
category: 动画系统
draft: false
---

# 游戏Motion Matching动作匹配系统：从原理到Unity工程落地完全指南

## 一、为什么需要Motion Matching

传统角色动画系统（状态机 + 动画混合树）在面对复杂运动需求时存在根本性局限：

- **状态爆炸**：跑步、走路、转身、加速、减速……每种组合都要手动设置过渡
- **过渡不自然**：硬切或固定时长混合往往导致"滑步"、"浮空"等视觉穿帮
- **维护成本高**：新增一个运动状态往往牵一发而动全身

**Motion Matching** 的核心思路是：不再手动设计状态机，而是**每帧从海量动画数据库中检索最匹配当前角色状态的动画帧**，直接播放或仅做极短混合。

> 代表作：EA/DICE《荣耀战魂》、育碧《刺客信条：起源》、Naughty Dog《最后生还者 Part II》均采用类似方案。

---

## 二、核心概念与数学基础

### 2.1 姿态（Pose）与特征向量

Motion Matching 的基本单元是**姿态帧**，每帧存储：

- 关键骨骼的局部位置/速度（身体、脚、手）
- 角色根节点的轨迹（未来 0.2s/0.4s/0.6s 三个采样点的位置和朝向）
- 脚步相位（左/右脚接地状态）

这些信息被压缩为一个**特征向量** `f ∈ ℝⁿ`，查询时计算欧氏距离：

```
cost(f_query, f_candidate) = Σ wᵢ · (fᵢ_query - fᵢ_candidate)²
```

权重 `wᵢ` 控制各特征的重要性，是调优的核心参数。

### 2.2 轨迹预测

输入：手柄摇杆方向 + 当前速度向量  
输出：未来 N 个时间步的预测轨迹

常用方法：**弹簧阻尼模型（Spring-Damper）**

```csharp
// 弹簧阻尼预测下一帧速度
Vector3 SpringDamperUpdate(Vector3 vel, Vector3 target, float halfLife, float dt)
{
    float y = HalfLifeToDamping(halfLife) / 2.0f;
    float j0 = vel - target;
    float eydt = FastNegExpApprox(y * dt);
    return eydt * j0 + target;
}
```

### 2.3 特征归一化

不同特征单位不同（米 vs 弧度），需要先归一化再加权：

```
f_normalized = (f - μ) / σ
```

其中 μ、σ 来自离线统计整个动画数据库。

---

## 三、数据库构建

### 3.1 动捕数据处理流程

```
原始 .fbx/.bvh 动捕数据
      ↓ 骨骼重定向（Retargeting）
    目标骨架姿态序列
      ↓ 特征提取（位置/速度/轨迹）
    每帧特征向量
      ↓ 归一化 + 加权
    Feature Database（二进制）
```

### 3.2 Unity 离线特征提取工具

```csharp
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;
using System.Collections.Generic;
using System.IO;

public class MotionMatchingBaker : EditorWindow
{
    [MenuItem("Tools/Motion Matching/Bake Database")]
    static void OpenWindow() => GetWindow<MotionMatchingBaker>();

    public AnimationClip[] clips;
    public Avatar avatar;
    public string outputPath = "Assets/MotionDB/features.bytes";

    // 特征提取关键骨骼名称
    static readonly string[] KeyBones = {
        "Hips", "LeftFoot", "RightFoot", "LeftHand", "RightHand"
    };

    // 轨迹采样时间点（秒）
    static readonly float[] TrajectoryTimes = { 0.2f, 0.4f, 0.6f };

    void OnGUI()
    {
        EditorGUILayout.LabelField("Motion Matching Database Baker", EditorStyles.boldLabel);
        // ... GUI 省略
        if (GUILayout.Button("Bake")) BakeDatabase();
    }

    void BakeDatabase()
    {
        var records = new List<PoseRecord>();
        
        foreach (var clip in clips)
        {
            if (clip == null) continue;
            int frameCount = Mathf.RoundToInt(clip.length * clip.frameRate);
            
            for (int f = 0; f < frameCount; f++)
            {
                float t = f / clip.frameRate;
                var record = ExtractFeatures(clip, t, f);
                record.clipIndex = System.Array.IndexOf(clips, clip);
                record.frameIndex = f;
                records.Add(record);
            }
        }

        // 计算归一化参数（均值/方差）
        var stats = ComputeNormalizationStats(records);
        
        // 序列化到二进制文件
        SaveDatabase(records, stats, outputPath);
        AssetDatabase.Refresh();
        Debug.Log($"[MotionMatching] Baked {records.Count} frames from {clips.Length} clips.");
    }

    PoseRecord ExtractFeatures(AnimationClip clip, float t, int frameIdx)
    {
        var record = new PoseRecord();
        
        // 1. 采样当前帧骨骼位置（需要通过 AnimationUtility 或运行时采样）
        // 实际项目中使用 AnimationClipPlayable 采样更准确
        var go = new GameObject("__SamplerTemp");
        var animator = go.AddComponent<Animator>();
        animator.avatar = avatar;
        
        // 采样当前帧
        clip.SampleAnimation(go, t);
        record.rootPosition = go.transform.position;
        record.rootRotation = go.transform.rotation;
        
        // 采样关键骨骼
        foreach (var boneName in KeyBones)
        {
            var bone = FindBoneRecursive(go.transform, boneName);
            if (bone != null)
                record.boneFeatures.Add(new BoneFeature { position = bone.position, velocity = Vector3.zero });
        }
        
        // 2. 提取轨迹（未来帧位置）
        record.trajectoryPoints = new Vector3[TrajectoryTimes.Length];
        for (int i = 0; i < TrajectoryTimes.Length; i++)
        {
            float futureT = Mathf.Clamp(t + TrajectoryTimes[i], 0, clip.length);
            clip.SampleAnimation(go, futureT);
            record.trajectoryPoints[i] = go.transform.position;
        }
        
        DestroyImmediate(go);
        return record;
    }

    NormalizationStats ComputeNormalizationStats(List<PoseRecord> records)
    {
        // 计算各特征维度的均值和标准差
        var stats = new NormalizationStats();
        // ... 实现省略
        return stats;
    }

    Transform FindBoneRecursive(Transform root, string name)
    {
        if (root.name == name) return root;
        foreach (Transform child in root)
        {
            var found = FindBoneRecursive(child, name);
            if (found != null) return found;
        }
        return null;
    }

    void SaveDatabase(List<PoseRecord> records, NormalizationStats stats, string path)
    {
        using var writer = new BinaryWriter(File.Open(path, FileMode.Create));
        writer.Write(records.Count);
        foreach (var r in records)
            r.Serialize(writer);
        stats.Serialize(writer);
    }
}
#endif
```

### 3.3 数据结构定义

```csharp
using System;
using System.Collections.Generic;
using System.IO;
using UnityEngine;

[Serializable]
public struct BoneFeature
{
    public Vector3 position;
    public Vector3 velocity;
}

[Serializable]
public class PoseRecord
{
    public int clipIndex;
    public int frameIndex;
    public Vector3 rootPosition;
    public Quaternion rootRotation;
    public List<BoneFeature> boneFeatures = new();
    public Vector3[] trajectoryPoints;
    public float[] trajectoryFacings;  // 未来帧朝向（弧度）
    public float leftFootPhase;
    public float rightFootPhase;

    // 缓存的特征向量（归一化后）
    [NonSerialized] public float[] featureVector;

    public void Serialize(BinaryWriter w)
    {
        w.Write(clipIndex);
        w.Write(frameIndex);
        WriteV3(w, rootPosition);
        WriteQ(w, rootRotation);
        w.Write(boneFeatures.Count);
        foreach (var bf in boneFeatures)
        {
            WriteV3(w, bf.position);
            WriteV3(w, bf.velocity);
        }
        w.Write(trajectoryPoints.Length);
        foreach (var tp in trajectoryPoints)
            WriteV3(w, tp);
        w.Write(leftFootPhase);
        w.Write(rightFootPhase);
    }

    static void WriteV3(BinaryWriter w, Vector3 v) { w.Write(v.x); w.Write(v.y); w.Write(v.z); }
    static void WriteQ(BinaryWriter w, Quaternion q) { w.Write(q.x); w.Write(q.y); w.Write(q.z); w.Write(q.w); }
}

[Serializable]
public class NormalizationStats
{
    public float[] mean;
    public float[] stdDev;

    public void Serialize(BinaryWriter w)
    {
        w.Write(mean.Length);
        foreach (var v in mean) w.Write(v);
        foreach (var v in stdDev) w.Write(v);
    }
}
```

---

## 四、KD 树加速查询

暴力线性搜索的时间复杂度是 O(N)，对于数十万帧的数据库来说每帧耗时极大。  
**KD 树** 将查询复杂度降至 O(log N)，是 Motion Matching 实现的标配。

```csharp
using System;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 简化版 KD 树，适用于 Motion Matching 特征查询
/// </summary>
public class MotionKDTree
{
    private struct KDNode
    {
        public int recordIndex;  // 指向 PoseRecord 数组下标
        public int left, right;  // 子节点下标，-1 表示空
        public int splitDim;
    }

    private KDNode[] _nodes;
    private float[][] _features;  // 已归一化的特征向量
    private int _dims;

    public void Build(float[][] features)
    {
        _features = features;
        _dims = features[0].Length;
        _nodes = new KDNode[features.Length * 2];
        int[] indices = new int[features.Length];
        for (int i = 0; i < indices.Length; i++) indices[i] = i;
        BuildRecursive(indices, 0, indices.Length, 0, 0);
    }

    int BuildRecursive(int[] indices, int start, int end, int depth, int nodeIdx)
    {
        if (start >= end) return -1;
        
        int splitDim = depth % _dims;
        int mid = (start + end) / 2;
        
        // 按 splitDim 排序（选择排序优化为快速选择）
        Array.Sort(indices, start, end - start, Comparer<int>.Create((a, b) =>
            _features[a][splitDim].CompareTo(_features[b][splitDim])));

        _nodes[nodeIdx] = new KDNode
        {
            recordIndex = indices[mid],
            splitDim = splitDim,
            left = -1,
            right = -1
        };

        if (nodeIdx * 2 + 1 < _nodes.Length)
        {
            _nodes[nodeIdx].left = BuildRecursive(indices, start, mid, depth + 1, nodeIdx * 2 + 1);
            _nodes[nodeIdx].right = BuildRecursive(indices, mid + 1, end, depth + 1, nodeIdx * 2 + 2);
        }

        return nodeIdx;
    }

    /// <summary>
    /// 最近邻查询，返回数据库中代价最小的记录下标
    /// </summary>
    public int QueryNearest(float[] query, float[] weights)
    {
        int bestIdx = -1;
        float bestCost = float.MaxValue;
        SearchRecursive(0, query, weights, ref bestIdx, ref bestCost);
        return bestIdx;
    }

    void SearchRecursive(int nodeIdx, float[] query, float[] weights, ref int bestIdx, ref float bestCost)
    {
        if (nodeIdx < 0 || nodeIdx >= _nodes.Length || _nodes[nodeIdx].recordIndex < 0) return;

        var node = _nodes[nodeIdx];
        int recIdx = node.recordIndex;

        // 计算当前节点代价
        float cost = ComputeCost(query, _features[recIdx], weights);
        if (cost < bestCost)
        {
            bestCost = cost;
            bestIdx = recIdx;
        }

        // 决定先访问哪棵子树
        int splitDim = node.splitDim;
        float diff = query[splitDim] - _features[recIdx][splitDim];
        int nearChild = diff < 0 ? nodeIdx * 2 + 1 : nodeIdx * 2 + 2;
        int farChild  = diff < 0 ? nodeIdx * 2 + 2 : nodeIdx * 2 + 1;

        SearchRecursive(nearChild, query, weights, ref bestIdx, ref bestCost);

        // 剪枝：只有远侧可能存在更近点时才访问
        float axisDistSq = diff * diff * weights[splitDim];
        if (axisDistSq < bestCost)
            SearchRecursive(farChild, query, weights, ref bestIdx, ref bestCost);
    }

    static float ComputeCost(float[] a, float[] b, float[] w)
    {
        float sum = 0;
        for (int i = 0; i < a.Length; i++)
        {
            float d = (a[i] - b[i]) * w[i];
            sum += d * d;
        }
        return sum;
    }
}
```

---

## 五、运行时核心系统

### 5.1 主控制器

```csharp
using UnityEngine;

[RequireComponent(typeof(Animator))]
public class MotionMatchingController : MonoBehaviour
{
    [Header("数据库")]
    public MotionMatchingDatabase database;

    [Header("特征权重")]
    [Range(0, 5)] public float trajectoryPosWeight = 2.0f;
    [Range(0, 5)] public float trajectoryDirWeight = 1.0f;
    [Range(0, 5)] public float bonePosWeight = 1.5f;
    [Range(0, 5)] public float boneVelWeight = 1.0f;

    [Header("搜索间隔（帧）")]
    public int searchIntervalFrames = 10;

    [Header("最小切换代价阈值")]
    public float switchCostThreshold = 0.05f;

    private Animator _animator;
    private MotionKDTree _kdTree;
    private TrajectoryPredictor _trajectoryPredictor;
    private FootIKSolver _footIK;

    private int _currentClipIdx = -1;
    private float _currentTime = 0f;
    private int _frameCounter = 0;

    // 当前查询特征（复用避免GC）
    private float[] _queryFeature;
    private float[] _featureWeights;

    void Awake()
    {
        _animator = GetComponent<Animator>();
        _trajectoryPredictor = GetComponent<TrajectoryPredictor>();
        _footIK = GetComponent<FootIKSolver>();

        // 加载数据库并构建 KD 树
        database.Load();
        _kdTree = new MotionKDTree();
        _kdTree.Build(database.normalizedFeatures);

        _queryFeature = new float[database.featureDimension];
        _featureWeights = BuildWeightArray();
    }

    void Update()
    {
        _frameCounter++;
        
        // 推进当前动画时间
        _currentTime += Time.deltaTime;

        // 每 N 帧执行一次搜索
        if (_frameCounter % searchIntervalFrames == 0)
        {
            PerformSearch();
        }
    }

    void PerformSearch()
    {
        // 1. 构建查询特征
        BuildQueryFeature();

        // 2. KD 树最近邻查询
        int bestRecordIdx = _kdTree.QueryNearest(_queryFeature, _featureWeights);
        var record = database.records[bestRecordIdx];

        // 3. 比较切换代价，决定是否切换
        if (ShouldSwitch(record))
        {
            SwitchToAnimation(record.clipIndex, record.frameIndex);
        }
    }

    void BuildQueryFeature()
    {
        int offset = 0;

        // 轨迹特征：未来 3 个采样点的相对位置
        var predictedTrajectory = _trajectoryPredictor.GetPredictedTrajectory();
        for (int i = 0; i < predictedTrajectory.Length; i++)
        {
            // 转换为角色本地空间
            Vector3 localPos = transform.InverseTransformPoint(predictedTrajectory[i].position);
            _queryFeature[offset++] = localPos.x;
            _queryFeature[offset++] = localPos.z;

            // 朝向（y 轴旋转的 sin/cos 编码）
            float angle = predictedTrajectory[i].facing;
            _queryFeature[offset++] = Mathf.Sin(angle);
            _queryFeature[offset++] = Mathf.Cos(angle);
        }

        // 关键骨骼位置特征
        foreach (var boneName in database.keyBoneNames)
        {
            var bone = _animator.GetBoneTransform(HumanBodyBones.Hips); // 简化，实际按骨骼名查找
            if (bone != null)
            {
                Vector3 localPos = transform.InverseTransformPoint(bone.position);
                _queryFeature[offset++] = localPos.x;
                _queryFeature[offset++] = localPos.y;
                _queryFeature[offset++] = localPos.z;
            }
        }

        // 归一化
        database.stats.Normalize(_queryFeature);
    }

    bool ShouldSwitch(PoseRecord newRecord)
    {
        if (_currentClipIdx < 0) return true;
        
        // 如果当前动画快播完，强制切换
        var currentClip = database.clips[_currentClipIdx];
        if (_currentTime >= currentClip.length - 0.1f) return true;

        // 计算切换代价（新帧的匹配度是否明显优于当前帧）
        float currentCost = ComputeCurrentFrameCost();
        float newCost = ComputeFeatureCost(newRecord);
        
        return (currentCost - newCost) > switchCostThreshold;
    }

    float ComputeCurrentFrameCost()
    {
        // 找到当前播放帧对应的记录，计算其代价
        // 简化：返回一个估算值
        return 0.5f;
    }

    float ComputeFeatureCost(PoseRecord record)
    {
        float cost = 0;
        var feat = database.normalizedFeatures[record.clipIndex * 1000 + record.frameIndex]; // 简化索引
        for (int i = 0; i < _queryFeature.Length; i++)
        {
            float d = (_queryFeature[i] - feat[i]) * _featureWeights[i];
            cost += d * d;
        }
        return cost;
    }

    void SwitchToAnimation(int clipIdx, int frameIdx)
    {
        if (clipIdx == _currentClipIdx) return;
        
        _currentClipIdx = clipIdx;
        _currentTime = frameIdx / database.clips[clipIdx].frameRate;
        
        // 触发 Animator 播放（通过 Playable API 精确定位帧）
        var clip = database.clips[clipIdx];
        _animator.CrossFadeInFixedTime(clip.name, 0.1f, 0);
        
        Debug.Log($"[MM] Switch to clip={clip.name} frame={frameIdx}");
    }

    float[] BuildWeightArray()
    {
        // 根据特征布局填充权重数组
        int dim = database.featureDimension;
        var weights = new float[dim];
        // 简化：统一填充，实际需按特征段分别设置
        for (int i = 0; i < dim; i++) weights[i] = 1.0f;
        return weights;
    }
}
```

### 5.2 轨迹预测器

```csharp
using UnityEngine;

public class TrajectoryPredictor : MonoBehaviour
{
    [Header("预测参数")]
    public float predictionHalfLife = 0.3f;
    public float[] sampleTimes = { 0.2f, 0.4f, 0.6f };

    [Header("输入设置")]
    public float maxSpeed = 4.0f;
    public float rotationSpeed = 180.0f;

    private Vector3 _currentVelocity;
    private float _currentFacing;

    public struct TrajectoryPoint
    {
        public Vector3 position;
        public float facing;
    }

    void Update()
    {
        // 从输入系统获取目标速度
        float h = Input.GetAxis("Horizontal");
        float v = Input.GetAxis("Vertical");
        Vector3 inputDir = new Vector3(h, 0, v).normalized;
        Vector3 targetVelocity = inputDir * maxSpeed;

        // 弹簧阻尼平滑速度
        _currentVelocity = SpringDamperV3(_currentVelocity, targetVelocity, predictionHalfLife, Time.deltaTime);

        // 更新角色朝向
        if (_currentVelocity.magnitude > 0.1f)
        {
            float targetFacing = Mathf.Atan2(_currentVelocity.x, _currentVelocity.z);
            _currentFacing = Mathf.MoveTowardsAngle(
                _currentFacing * Mathf.Rad2Deg,
                targetFacing * Mathf.Rad2Deg,
                rotationSpeed * Time.deltaTime
            ) * Mathf.Deg2Rad;
        }
    }

    public TrajectoryPoint[] GetPredictedTrajectory()
    {
        var result = new TrajectoryPoint[sampleTimes.Length];
        Vector3 pos = transform.position;
        Vector3 vel = _currentVelocity;
        float facing = _currentFacing;

        for (int i = 0; i < sampleTimes.Length; i++)
        {
            float dt = i == 0 ? sampleTimes[0] : sampleTimes[i] - sampleTimes[i - 1];
            vel = SpringDamperV3(vel, Vector3.zero, predictionHalfLife, dt);
            pos += vel * dt;

            if (vel.magnitude > 0.1f)
                facing = Mathf.Atan2(vel.x, vel.z);

            result[i] = new TrajectoryPoint { position = pos, facing = facing };
        }
        return result;
    }

    // 弹簧阻尼迭代
    Vector3 SpringDamperV3(Vector3 current, Vector3 target, float halfLife, float dt)
    {
        float damping = 0.6931472f / halfLife;  // ln(2) / halfLife
        float exp = Mathf.Exp(-damping * dt);
        return Vector3.Lerp(target, current, exp);
    }
}
```

### 5.3 脚步 IK 校正

```csharp
using UnityEngine;

/// <summary>
/// 基于射线检测的脚步 IK，确保角色在不平地面上脚部贴地
/// </summary>
[RequireComponent(typeof(Animator))]
public class FootIKSolver : MonoBehaviour
{
    [Header("IK 权重")]
    [Range(0, 1)] public float ikWeight = 1.0f;
    [Range(0, 1)] public float bodyWeight = 0.3f;

    [Header("射线参数")]
    public float raycastOriginHeight = 0.5f;
    public float raycastDistance = 1.5f;
    public LayerMask groundLayer;

    [Header("脚踝高度偏移")]
    public float footHeightOffset = 0.08f;

    private Animator _animator;
    private float _leftFootWeight, _rightFootWeight;
    private Vector3 _leftFootPos, _rightFootPos;
    private Quaternion _leftFootRot, _rightFootRot;

    void Awake() => _animator = GetComponent<Animator>();

    void OnAnimatorIK(int layerIndex)
    {
        if (!enabled) return;

        // 采样动画中脚步权重（来自动画曲线 LeftFootIK / RightFootIK）
        _leftFootWeight = _animator.GetFloat("LeftFootIK");
        _rightFootWeight = _animator.GetFloat("RightFootIK");

        SolveFootIK(AvatarIKGoal.LeftFoot, ref _leftFootPos, ref _leftFootRot, _leftFootWeight);
        SolveFootIK(AvatarIKGoal.RightFoot, ref _rightFootPos, ref _rightFootRot, _rightFootWeight);

        AdjustBodyHeight();
    }

    void SolveFootIK(AvatarIKGoal goal, ref Vector3 footPos, ref Quaternion footRot, float weight)
    {
        if (weight <= 0) return;

        Transform footTransform = goal == AvatarIKGoal.LeftFoot
            ? _animator.GetBoneTransform(HumanBodyBones.LeftFoot)
            : _animator.GetBoneTransform(HumanBodyBones.RightFoot);

        if (footTransform == null) return;

        Vector3 origin = footTransform.position + Vector3.up * raycastOriginHeight;

        if (Physics.Raycast(origin, Vector3.down, out RaycastHit hit, raycastDistance, groundLayer))
        {
            footPos = hit.point + Vector3.up * footHeightOffset;
            footRot = Quaternion.FromToRotation(Vector3.up, hit.normal) * transform.rotation;

            _animator.SetIKPositionWeight(goal, weight * ikWeight);
            _animator.SetIKRotationWeight(goal, weight * ikWeight);
            _animator.SetIKPosition(goal, footPos);
            _animator.SetIKRotation(goal, footRot);
        }
    }

    void AdjustBodyHeight()
    {
        // 根据两脚最低点下移身体
        float leftY = _leftFootWeight > 0 ? _leftFootPos.y : float.MaxValue;
        float rightY = _rightFootWeight > 0 ? _rightFootPos.y : float.MaxValue;
        float lowestFoot = Mathf.Min(leftY, rightY);

        if (lowestFoot < float.MaxValue)
        {
            Vector3 bodyPos = _animator.bodyPosition;
            float delta = lowestFoot - transform.position.y;
            bodyPos.y += delta * bodyWeight;
            _animator.bodyPosition = bodyPos;
        }
    }
}
```

---

## 六、Root Motion 处理

Motion Matching 中 Root Motion 的处理需要特别注意：

```csharp
using UnityEngine;

/// <summary>
/// 自定义 Root Motion 处理器，将动画位移映射到实际角色移动
/// </summary>
[RequireComponent(typeof(Animator), typeof(CharacterController))]
public class MotionMatchingRootMotion : MonoBehaviour
{
    private Animator _animator;
    private CharacterController _cc;

    [Header("Root Motion 混合")]
    [Range(0, 1)] public float rootMotionInfluence = 0.8f;
    public float gravityScale = -9.81f;

    private Vector3 _verticalVelocity = Vector3.zero;

    void Awake()
    {
        _animator = GetComponent<Animator>();
        _cc = GetComponent<CharacterController>();
        _animator.applyRootMotion = false;  // 手动处理
    }

    void OnAnimatorMove()
    {
        // 获取动画本帧的位移和旋转增量
        Vector3 animDeltaPos = _animator.deltaPosition;
        Quaternion animDeltaRot = _animator.deltaRotation;

        // 混合动画位移和物理位移
        Vector3 moveVelocity = (animDeltaPos / Time.deltaTime) * rootMotionInfluence;

        // 叠加重力
        if (_cc.isGrounded)
            _verticalVelocity.y = -0.5f;
        else
            _verticalVelocity.y += gravityScale * Time.deltaTime;

        moveVelocity.y = _verticalVelocity.y;

        _cc.Move(moveVelocity * Time.deltaTime);
        transform.rotation *= animDeltaRot;
    }
}
```

---

## 七、性能优化策略

### 7.1 搜索间隔与候选剪枝

| 策略 | 描述 | 性能提升 |
|------|------|---------|
| 间隔搜索 | 每 N 帧执行一次搜索 | 降低 CPU 占用 N 倍 |
| 轨迹剪枝 | 只搜索轨迹相似的子集 | 减少候选帧 50-70% |
| 连续性惩罚 | 优先当前播放帧附近的候选 | 减少不必要切换 |
| Burst + SIMD | 使用 Unity Burst 编译器向量化距离计算 | 4-8x 速度提升 |

### 7.2 Burst Job 加速距离计算

```csharp
using Unity.Burst;
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;

[BurstCompile]
public struct MotionSearchJob : IJobParallelFor
{
    [ReadOnly] public NativeArray<float> QueryFeature;
    [ReadOnly] public NativeArray<float> DatabaseFeatures;  // 行优先存储：[recordIdx * dim + featDim]
    [ReadOnly] public NativeArray<float> Weights;
    [ReadOnly] public int FeatureDim;

    public NativeArray<float> OutCosts;

    public void Execute(int recordIdx)
    {
        float cost = 0f;
        int baseOffset = recordIdx * FeatureDim;
        for (int d = 0; d < FeatureDim; d++)
        {
            float diff = QueryFeature[d] - DatabaseFeatures[baseOffset + d];
            cost += diff * diff * Weights[d];
        }
        OutCosts[recordIdx] = cost;
    }
}

// 使用示例
public class BurstMotionSearch : MonoBehaviour
{
    NativeArray<float> _dbFeatures;
    NativeArray<float> _weights;
    NativeArray<float> _costs;
    NativeArray<float> _query;

    public int FindBestMatch(float[] queryFeature)
    {
        // 复制查询特征到 NativeArray
        for (int i = 0; i < queryFeature.Length; i++)
            _query[i] = queryFeature[i];

        var job = new MotionSearchJob
        {
            QueryFeature = _query,
            DatabaseFeatures = _dbFeatures,
            Weights = _weights,
            FeatureDim = queryFeature.Length,
            OutCosts = _costs
        };

        job.Schedule(_costs.Length, 64).Complete();

        // 找最小代价
        int best = 0;
        float minCost = float.MaxValue;
        for (int i = 0; i < _costs.Length; i++)
        {
            if (_costs[i] < minCost)
            {
                minCost = _costs[i];
                best = i;
            }
        }
        return best;
    }
}
```

---

## 八、调试与可视化工具

```csharp
#if UNITY_EDITOR
using UnityEngine;

public class MotionMatchingDebugGizmos : MonoBehaviour
{
    public TrajectoryPredictor predictor;
    public bool showTrajectory = true;
    public bool showPose = true;

    void OnDrawGizmos()
    {
        if (predictor == null) return;

        if (showTrajectory)
        {
            var traj = predictor.GetPredictedTrajectory();
            Gizmos.color = Color.cyan;
            Vector3 prev = transform.position;
            foreach (var tp in traj)
            {
                Gizmos.DrawLine(prev, tp.position);
                Gizmos.DrawWireSphere(tp.position, 0.05f);
                // 绘制朝向箭头
                Vector3 dir = new Vector3(Mathf.Sin(tp.facing), 0, Mathf.Cos(tp.facing));
                Gizmos.color = Color.yellow;
                Gizmos.DrawRay(tp.position, dir * 0.3f);
                Gizmos.color = Color.cyan;
                prev = tp.position;
            }
        }
    }
}
#endif
```

---

## 九、最佳实践总结

### 数据采集阶段
- **覆盖所有速度层级**：静止→慢走→快走→跑→冲刺，每种速度至少采集 8 个方向
- **循环动画标记**：需精确标记循环帧，避免特征在边界处跳变
- **多地形动作**：上坡/下坡/侧步/急停，丰富数据库覆盖面
- **数据量建议**：基础移动至少 5-10 分钟动捕数据（≈9000-18000帧@30fps）

### 特征设计阶段
- **轨迹权重 > 骨骼权重**：响应玩家输入的优先级最高
- **归一化必做**：不归一化会导致单位大的特征（如位置米）主导搜索结果
- **脚步相位**：加入左/右脚相位特征可显著减少脚步切换时的视觉穿帮

### 工程集成阶段
- **Playable API 优于 Animator.CrossFade**：前者可精确定位到任意帧
- **搜索间隔 10-15 帧**：通常感知不到延迟，性能提升明显
- **热身时间**：游戏开始前预热 KD 树，避免首帧卡顿
- **兜底状态机**：对特殊状态（攻击/受击/跳跃）保留传统状态机，Motion Matching 只处理移动

### 调优流程
1. 先调轨迹权重，确保角色方向响应自然
2. 再调骨骼权重，减少姿态跳变
3. 最后调切换阈值，平衡响应速度与稳定性
4. 用慢动作录像检查脚步穿插、滑步等问题

---

## 十、延伸阅读

- [GDC 2016: Motion Matching, the Road to Next Gen Animation](https://www.gdcvault.com/play/1023280/)
- Ubisoft "Learning Motion Matching" (SIGGRAPH 2020)
- Unity DOTS Animation + Motion Matching 官方示例
- [Daniel Holden "Learned Motion Matching"](https://theorangeduck.com/page/learned-motion-matching)

Motion Matching 代表了游戏角色动画的未来方向，配合机器学习（Learned Motion Matching）可进一步提升自然度。掌握这套技术体系，将使你的游戏角色动画达到 AAA 级品质。
