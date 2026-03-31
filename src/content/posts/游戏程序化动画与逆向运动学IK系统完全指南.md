---
title: 游戏程序化动画与逆向运动学IK系统完全指南
published: 2026-03-31
description: 深入解析游戏中程序化动画的原理与实现，从基础的逆向运动学（IK）算法到高级的全身IK、布娃娃物理融合，涵盖FABRIK、CCD、Two-Bone IK等核心算法，并结合Unity Animation Rigging实战案例。
tags: [Unity, 程序化动画, IK, 逆向运动学, 角色动画, FABRIK, CCD, Animation Rigging]
category: 动画系统
draft: false
---

# 游戏程序化动画与逆向运动学（IK）系统完全指南

## 前言

在现代游戏开发中，仅靠美术预制的动画已无法满足复杂的交互需求：角色脚踩在不平坦地面时需要自适应、攀爬时手臂需要精准抓住把手、瞄准时枪口必须指向目标……这些都需要**程序化动画（Procedural Animation）**技术的支撑。

逆向运动学（Inverse Kinematics，IK）是程序化动画的核心算法，它通过"已知末端执行器目标位置，反向求解骨骼链各关节旋转角度"来实现动态骨骼控制。本文将从数学原理到工程实践，完整呈现IK系统的构建过程。

---

## 一、正向运动学 vs 逆向运动学

### 1.1 正向运动学（FK）

正向运动学（Forward Kinematics）是从根节点到末端节点逐级计算变换：

```
Root → Bone1 → Bone2 → ... → EndEffector
```

每个骨骼的世界矩阵 = 父骨骼世界矩阵 × 当前骨骼局部矩阵：

```csharp
// FK 计算示例
Matrix4x4 ComputeWorldMatrix(Transform bone)
{
    if (bone.parent == null) return bone.localToWorldMatrix;
    return ComputeWorldMatrix(bone.parent) * bone.localToWorldMatrix;
}
```

**FK 的局限**：你无法直接指定末端位置，只能通过手动调每个关节角度来间接控制。

### 1.2 逆向运动学（IK）

IK 反过来：已知末端目标位置 Target，求解骨骼链各关节的旋转使末端到达 Target：

```
已知: EndEffector 需要到达 Target
求解: Bone1.rotation, Bone2.rotation, ..., BoneN.rotation
```

这是一个**欠定方程组**（解不唯一），不同 IK 算法采用不同策略来约束唯一解。

---

## 二、Two-Bone IK：最高效的手臂/腿部解算

Two-Bone IK（两骨 IK）是游戏中最常用的 IK 算法，专为肢体（大腿-小腿-脚，上臂-前臂-手）设计。

### 2.1 数学原理

给定骨骼链 Root → Mid → Tip，以及目标点 Target 和 Hint（弯曲方向提示）：

```
骨骼长度: a = |Root → Mid|, b = |Mid → Tip|
目标距离: c = |Root → Target|

余弦定理:
cos(∠Root) = (a² + c² - b²) / (2ac)
cos(∠Mid)  = (a² + b² - c²) / (2ab)
```

### 2.2 C# 实现

```csharp
using UnityEngine;

public class TwoBoneIK : MonoBehaviour
{
    [Header("骨骼链")]
    public Transform root;    // 大腿 / 上臂
    public Transform mid;     // 膝盖 / 肘部
    public Transform tip;     // 脚踝 / 手腕

    [Header("IK 目标")]
    public Transform target;  // 末端目标位置
    public Transform hint;    // 极向量（弯曲方向提示）

    [Range(0f, 1f)]
    public float weight = 1f; // IK 权重，支持与原始动画混合

    // 记录原始旋转（用于混合）
    private Quaternion _rootRotOrigin;
    private Quaternion _midRotOrigin;

    void LateUpdate()
    {
        if (weight <= 0f || target == null) return;

        _rootRotOrigin = root.rotation;
        _midRotOrigin  = mid.rotation;

        SolveTwoBoneIK();

        // 按权重与原始动画混合
        if (weight < 1f)
        {
            root.rotation = Quaternion.Slerp(_rootRotOrigin, root.rotation, weight);
            mid.rotation  = Quaternion.Slerp(_midRotOrigin,  mid.rotation,  weight);
        }
    }

    void SolveTwoBoneIK()
    {
        Vector3 rootPos   = root.position;
        Vector3 midPos    = mid.position;
        Vector3 tipPos    = tip.position;
        Vector3 targetPos = target.position;

        float a = (midPos - rootPos).magnitude;  // 上骨长度
        float b = (tipPos - midPos).magnitude;   // 下骨长度
        float c = Mathf.Clamp((targetPos - rootPos).magnitude, 1e-5f, a + b - 1e-5f);

        // 余弦定理求角度
        float angleA = Mathf.Acos(Mathf.Clamp((a * a + c * c - b * b) / (2 * a * c), -1f, 1f));
        float angleB = Mathf.Acos(Mathf.Clamp((a * a + b * b - c * c) / (2 * a * b), -1f, 1f));

        // 计算参考平面法线（由极向量 hint 决定弯曲方向）
        Vector3 axis;
        if (hint != null)
        {
            Vector3 hintDir = (hint.position - rootPos).normalized;
            Vector3 targetDir = (targetPos - rootPos).normalized;
            axis = Vector3.Cross(hintDir, targetDir).normalized;
            if (axis.sqrMagnitude < 1e-6f)
                axis = Vector3.Cross(Vector3.up, targetDir).normalized;
        }
        else
        {
            axis = Vector3.Cross(midPos - rootPos, tipPos - rootPos).normalized;
        }

        // 旋转根骨骼：对齐到目标方向，并施加角度偏移
        Vector3 rootToMid    = (midPos - rootPos).normalized;
        Vector3 rootToTarget = (targetPos - rootPos).normalized;
        Quaternion rootRotation = Quaternion.FromToRotation(rootToMid, 
            RotateVectorAroundAxis(rootToTarget, axis, -angleA));
        root.rotation = rootRotation * root.rotation;

        // 更新 mid 位置（根旋转后）
        midPos = root.position + (root.rotation * root.InverseTransformPoint(midPos + rootPos) - root.position);
        midPos = root.TransformPoint(root.InverseTransformPoint(midPos));

        // 重新计算 mid，使用旋转后的实际位置
        Vector3 newMidPos = root.position + root.rotation * 
            (Quaternion.Inverse(_rootRotOrigin) * (midPos - root.position));
        
        // 旋转中间骨骼：弯曲到 π - angleB
        Vector3 midToTip    = (tipPos - midPos).normalized;
        Vector3 midToTarget = (targetPos - root.TransformPoint(
            root.InverseTransformPoint(midPos))).normalized;
        float currentAngle  = Mathf.Acos(Mathf.Clamp(
            Vector3.Dot((tipPos - midPos).normalized, (root.position - midPos).normalized), -1f, 1f));
        float targetAngle   = Mathf.PI - angleB;
        
        mid.rotation = Quaternion.AngleAxis(
            Mathf.Rad2Deg * (targetAngle - currentAngle), axis) * mid.rotation;

        // 对齐末端到目标朝向
        if (target.TryGetComponent<IKTarget>(out var ikTarget) && ikTarget.matchRotation)
        {
            tip.rotation = target.rotation;
        }
    }

    // 绕任意轴旋转向量（Rodrigues公式）
    static Vector3 RotateVectorAroundAxis(Vector3 v, Vector3 axis, float angle)
    {
        float cos = Mathf.Cos(angle);
        float sin = Mathf.Sin(angle);
        return v * cos + Vector3.Cross(axis, v) * sin + axis * Vector3.Dot(axis, v) * (1 - cos);
    }
}

// IK 目标标记组件
public class IKTarget : MonoBehaviour
{
    public bool matchRotation = true;
}
```

---

## 三、FABRIK 算法：多骨骼链的优雅解法

**FABRIK（Forward And Backward Reaching Inverse Kinematics）**是一种迭代算法，特别适用于 3 个以上骨骼组成的链条（如脊柱、尾巴、触手）。

### 3.1 算法原理

FABRIK 通过前向+反向两次扫描迭代求解：

```
迭代过程:
1. 反向传播（Backward Pass）:
   - 将末端骨骼移动到目标位置
   - 依次将每个骨骼"拉"到距其子节点 boneLength 处
   
2. 正向传播（Forward Pass）:
   - 将根骨骼恢复到原始位置
   - 依次将每个骨骼"推"到距其父节点 boneLength 处
   
3. 重复直到末端与目标距离 < tolerance 或达到最大迭代次数
```

### 3.2 C# 完整实现

```csharp
using UnityEngine;
using System.Collections.Generic;

public class FABRIKSolver : MonoBehaviour
{
    [Header("骨骼链（从根到末端）")]
    public List<Transform> bones = new List<Transform>();

    [Header("IK 参数")]
    public Transform target;
    public int maxIterations = 10;
    public float tolerance = 0.001f;

    [Range(0f, 1f)]
    public float weight = 1f;

    private float[] _boneLengths;
    private float   _totalLength;
    private Vector3[] _positions;        // 工作区位置数组
    private Vector3[] _originalPositions;// 原始位置

    void Awake()
    {
        InitializeBones();
    }

    void InitializeBones()
    {
        int n = bones.Count;
        _boneLengths = new float[n - 1];
        _positions   = new Vector3[n];
        _originalPositions = new Vector3[n];

        _totalLength = 0f;
        for (int i = 0; i < n - 1; i++)
        {
            _boneLengths[i] = Vector3.Distance(bones[i].position, bones[i + 1].position);
            _totalLength += _boneLengths[i];
        }
    }

    void LateUpdate()
    {
        if (target == null || bones.Count < 2) return;
        if (weight <= 0f) return;

        // 更新骨骼长度（支持运行时缩放）
        for (int i = 0; i < _boneLengths.Length; i++)
            _boneLengths[i] = Vector3.Distance(bones[i].position, bones[i + 1].position);

        SolveFABRIK();
    }

    void SolveFABRIK()
    {
        int n = bones.Count;
        Vector3 targetPos = target.position;
        Vector3 rootPos   = bones[0].position;

        // 复制当前世界位置到工作数组
        for (int i = 0; i < n; i++)
            _positions[i] = bones[i].position;

        // 如果目标超出骨骼链总长度，直接朝目标方向拉伸
        float dist = Vector3.Distance(rootPos, targetPos);
        if (dist >= _totalLength)
        {
            Vector3 dir = (targetPos - rootPos).normalized;
            for (int i = 1; i < n; i++)
                _positions[i] = _positions[i - 1] + dir * _boneLengths[i - 1];
        }
        else
        {
            // FABRIK 迭代
            for (int iter = 0; iter < maxIterations; iter++)
            {
                // 1. 反向传播
                _positions[n - 1] = targetPos;
                for (int i = n - 2; i >= 0; i--)
                {
                    Vector3 dir = (_positions[i] - _positions[i + 1]).normalized;
                    _positions[i] = _positions[i + 1] + dir * _boneLengths[i];
                }

                // 2. 正向传播
                _positions[0] = rootPos;
                for (int i = 1; i < n; i++)
                {
                    Vector3 dir = (_positions[i] - _positions[i - 1]).normalized;
                    _positions[i] = _positions[i - 1] + dir * _boneLengths[i - 1];
                }

                // 3. 收敛判断
                if (Vector3.Distance(_positions[n - 1], targetPos) < tolerance)
                    break;
            }
        }

        // 应用结果：将位置转换为旋转
        ApplyPositionsToRotations(n);
    }

    void ApplyPositionsToRotations(int n)
    {
        for (int i = 0; i < n - 1; i++)
        {
            // 计算当前骨骼指向下一骨骼的方向
            Vector3 currentDir = bones[i + 1].position - bones[i].position;
            Vector3 targetDir  = _positions[i + 1] - _positions[i];

            if (currentDir.sqrMagnitude < 1e-8f || targetDir.sqrMagnitude < 1e-8f)
                continue;

            // 计算旋转增量
            Quaternion rotDelta = Quaternion.FromToRotation(
                currentDir.normalized, targetDir.normalized);

            // 混合权重
            if (weight < 1f)
                rotDelta = Quaternion.Slerp(Quaternion.identity, rotDelta, weight);

            bones[i].rotation = rotDelta * bones[i].rotation;
        }

        // 对齐末端骨骼朝向
        if (target != null)
        {
            bones[n - 1].rotation = Quaternion.Slerp(
                bones[n - 1].rotation, target.rotation, weight);
        }
    }

    // 约束关节角度（避免骨骼穿入自身）
    void ApplyAngleConstraint(int boneIndex, float maxAngle)
    {
        if (boneIndex == 0) return;

        Vector3 parentDir = (_positions[boneIndex] - _positions[boneIndex - 1]).normalized;
        Vector3 childDir  = (_positions[boneIndex + 1] - _positions[boneIndex]).normalized;

        float angle = Vector3.Angle(parentDir, childDir);
        if (angle > maxAngle)
        {
            Vector3 axis = Vector3.Cross(parentDir, childDir).normalized;
            _positions[boneIndex + 1] = _positions[boneIndex] +
                (Quaternion.AngleAxis(maxAngle, axis) * parentDir) * _boneLengths[boneIndex];
        }
    }

    void OnDrawGizmos()
    {
        if (bones == null) return;
        Gizmos.color = Color.green;
        for (int i = 0; i < bones.Count - 1; i++)
        {
            if (bones[i] && bones[i + 1])
                Gizmos.DrawLine(bones[i].position, bones[i + 1].position);
        }
        if (target)
        {
            Gizmos.color = Color.red;
            Gizmos.DrawWireSphere(target.position, 0.05f);
        }
    }
}
```

---

## 四、CCD 算法：加入约束的关节解算

**CCD（Cyclic Coordinate Descent）**逐个关节迭代旋转，每次旋转使当前关节到末端的方向与目标方向尽量对齐：

```csharp
public class CCDSolver : MonoBehaviour
{
    public Transform[] joints;     // 关节数组（从根到末端）
    public Transform endEffector;  // 末端执行器
    public Transform target;       // IK 目标

    [Header("约束")]
    public float[] minAngles;      // 每个关节最小角度限制
    public float[] maxAngles;      // 每个关节最大角度限制

    public int maxIterations = 20;
    public float tolerance = 0.01f;

    void LateUpdate()
    {
        if (target == null || joints.Length == 0) return;
        SolveCCD();
    }

    void SolveCCD()
    {
        for (int iter = 0; iter < maxIterations; iter++)
        {
            // 从末端向根部逐个关节优化
            for (int i = joints.Length - 1; i >= 0; i--)
            {
                Transform joint = joints[i];

                // 计算：当前关节 → 末端执行器 方向
                Vector3 toEndEffector = (endEffector.position - joint.position).normalized;
                // 计算：当前关节 → 目标 方向
                Vector3 toTarget      = (target.position - joint.position).normalized;

                // 计算旋转量
                Quaternion rotation = Quaternion.FromToRotation(toEndEffector, toTarget);
                joint.rotation = rotation * joint.rotation;

                // 应用关节角度约束（以局部X轴为旋转轴示例）
                if (minAngles != null && maxAngles != null && i < minAngles.Length)
                {
                    Vector3 localEuler = joint.localEulerAngles;
                    localEuler.x = ClampAngle(localEuler.x, minAngles[i], maxAngles[i]);
                    joint.localEulerAngles = localEuler;
                }
            }

            // 收敛检测
            if (Vector3.Distance(endEffector.position, target.position) < tolerance)
                break;
        }
    }

    float ClampAngle(float angle, float min, float max)
    {
        if (angle > 180f) angle -= 360f;
        return Mathf.Clamp(angle, min, max);
    }
}
```

---

## 五、脚步 IK：地形自适应的核心技术

脚步 IK 让角色的脚自动适应凹凸不平的地面，是开放世界游戏的必备特性。

### 5.1 架构设计

```
FootIK System
├── 地面检测（Raycast）
├── 脚部目标位置计算
├── 骨盆高度调整
├── 脚部旋转匹配地面法线
└── 动画权重混合
```

### 5.2 完整实现

```csharp
using UnityEngine;

[RequireComponent(typeof(Animator))]
public class FootIK : MonoBehaviour
{
    [Header("IK 参数")]
    [Range(0f, 1f)] public float ikWeight = 1f;

    [Header("脚部设置")]
    public float footHeight = 0.1f;       // 脚底高度偏移
    public float footRaycastUp = 0.5f;    // 射线起点上方偏移
    public float footRaycastDown = 1.5f;  // 射线向下距离
    public LayerMask groundLayer = 1;     // 地面层

    [Header("骨盆调整")]
    public float pelvisOffset = 0f;       // 骨盆额外偏移
    public float pelvisUpDownSpeed = 0.3f;// 骨盆上下插值速度
    public float pelvisHorizontalSpeed = 1f;

    [Header("脚部插值")]
    public float feetToIkPositionSpeed = 0.5f;

    private Animator _animator;
    private Vector3 _rightFootPosition, _leftFootPosition;
    private Vector3 _rightFootIkPosition, _leftFootIkPosition;
    private Quaternion _rightFootIkRotation, _leftFootIkRotation;
    private float _lastPelvisPositionY, _lastRightFootY, _lastLeftFootY;

    // 动画层索引
    private static readonly int RightFootIndex = 0;
    private static readonly int LeftFootIndex  = 1;

    void Start()
    {
        _animator = GetComponent<Animator>();
    }

    /// <summary>
    /// OnAnimatorIK 在 LateUpdate 前由 Animator 调用
    /// </summary>
    void OnAnimatorIK(int layerIndex)
    {
        if (_animator == null) return;

        // 1. 移动骨盆到正确高度
        MovePelvisHeight();

        // 2. 设置 IK 目标
        _animator.SetIKPositionWeight(AvatarIKGoal.RightFoot, ikWeight);
        _animator.SetIKRotationWeight(AvatarIKGoal.RightFoot, ikWeight);
        _animator.SetIKPositionWeight(AvatarIKGoal.LeftFoot,  ikWeight);
        _animator.SetIKRotationWeight(AvatarIKGoal.LeftFoot,  ikWeight);

        // 3. 从动画中获取脚部当前位置
        MoveFeetToIkPoint(AvatarIKGoal.RightFoot, _rightFootIkPosition,
            _rightFootIkRotation, ref _lastRightFootY);
        MoveFeetToIkPoint(AvatarIKGoal.LeftFoot,  _leftFootIkPosition,
            _leftFootIkRotation, ref _lastLeftFootY);
    }

    void FixedUpdate()
    {
        // 在物理更新中进行射线检测（性能优化）
        FeetPositionSolver(
            _animator.GetIKPosition(AvatarIKGoal.RightFoot),
            ref _rightFootIkPosition,
            ref _rightFootIkRotation);

        FeetPositionSolver(
            _animator.GetIKPosition(AvatarIKGoal.LeftFoot),
            ref _leftFootIkPosition,
            ref _leftFootIkRotation);
    }

    void MoveFeetToIkPoint(AvatarIKGoal foot, Vector3 targetPos,
        Quaternion targetRot, ref float lastY)
    {
        Vector3 currPos = _animator.GetIKPosition(foot);

        // Y轴插值（平滑落地）
        currPos.y = Mathf.Lerp(lastY, targetPos.y, feetToIkPositionSpeed);
        lastY = currPos.y;

        // 水平位置直接设置（X/Z 由动画控制）
        currPos.x = targetPos.x;
        currPos.z = targetPos.z;

        _animator.SetIKPosition(foot, currPos);
        _animator.SetIKRotation(foot, targetRot);
    }

    void MovePelvisHeight()
    {
        if (_rightFootIkPosition == Vector3.zero || _leftFootIkPosition == Vector3.zero
            || _lastPelvisPositionY == 0f)
        {
            _lastPelvisPositionY = _animator.bodyPosition.y;
            return;
        }

        // 获取动画骨盆位置
        float animatedBodyY = _animator.bodyPosition.y;

        // 计算两脚中较低的一只脚需要的骨盆偏移
        float rightOffset = _rightFootIkPosition.y - transform.position.y;
        float leftOffset  = _leftFootIkPosition.y  - transform.position.y;
        float pelvisYOffset = rightOffset < leftOffset ? rightOffset : leftOffset;

        float newPelvisY = Mathf.Lerp(_lastPelvisPositionY,
            animatedBodyY + pelvisYOffset + pelvisOffset,
            pelvisUpDownSpeed);

        // 应用骨盆位置
        Vector3 newBodyPos = _animator.bodyPosition;
        newBodyPos.y = newPelvisY;
        _animator.bodyPosition = newBodyPos;

        _lastPelvisPositionY = _animator.bodyPosition.y;
    }

    void FeetPositionSolver(Vector3 fromSkyPosition,
        ref Vector3 feetIkPosition, ref Quaternion feetIkRotation)
    {
        // 从脚部正上方射线向下检测地面
        RaycastHit hit;
        Vector3 rayStart = fromSkyPosition + Vector3.up * footRaycastUp;

        if (Physics.Raycast(rayStart, Vector3.down, out hit,
            footRaycastUp + footRaycastDown, groundLayer))
        {
            // 脚部 IK 位置 = 碰撞点 + 脚高偏移
            feetIkPosition = fromSkyPosition;
            feetIkPosition.y = hit.point.y + footHeight;

            // 脚部旋转匹配地面法线
            feetIkRotation = Quaternion.FromToRotation(Vector3.up, hit.normal)
                * transform.rotation;
        }
        else
        {
            // 没有地面则保持原始动画位置
            feetIkPosition = fromSkyPosition;
        }

        Debug.DrawLine(rayStart, rayStart + Vector3.down * (footRaycastUp + footRaycastDown),
            Color.yellow);
    }

    void OnDrawGizmosSelected()
    {
        Gizmos.color = Color.cyan;
        Gizmos.DrawWireSphere(_rightFootIkPosition, 0.05f);
        Gizmos.DrawWireSphere(_leftFootIkPosition,  0.05f);
    }
}
```

---

## 六、Unity Animation Rigging 实战

Unity 的 Animation Rigging 包提供了声明式 IK 组件，无需手写代码即可配置复杂的 IK 约束。

### 6.1 安装与配置

```bash
# Package Manager 搜索安装
com.unity.animation.rigging

# 为 Animator 角色开启 Rig 支持
GameObject → Add Component → Rig Builder
GameObject → 子节点 → Add Component → Rig
Rig 下的骨骼 → 添加各类 Constraint 组件
```

### 6.2 常用 Constraint 组件

| Constraint | 用途 | 关键参数 |
|---|---|---|
| `Two Bone IK Constraint` | 手臂/腿部 IK | Root/Mid/Tip + Target + Hint |
| `Multi-Aim Constraint` | 头部/眼睛朝向目标 | Source Objects + Aim Axis |
| `Chain IK Constraint` | 脊柱/尾巴多骨骼 IK | Root → Tip + Target |
| `Multi-Parent Constraint` | 抓取/携带物品 | Sources 多权重混合 |
| `Blend Constraint` | 在两个位置/旋转间插值 | Position/Rotation Weight |
| `Override Transform` | 直接覆盖骨骼变换 | Space + Weight |

### 6.3 运行时控制 IK 权重

```csharp
using UnityEngine;
using UnityEngine.Animations.Rigging;

public class IKWeightController : MonoBehaviour
{
    [Header("Rig 约束引用")]
    public TwoBoneIKConstraint rightHandIK;
    public TwoBoneIKConstraint leftHandIK;
    public MultiAimConstraint  headAimIK;
    public ChainIKConstraint   spineIK;

    [Header("瞄准目标")]
    public Transform aimTarget;

    // 武器拾取：从0平滑过渡到1
    public void PickupWeapon(Transform weaponGrab, float transitionTime = 0.3f)
    {
        rightHandIK.data.target = weaponGrab;
        StartCoroutine(LerpWeight(rightHandIK, 0f, 1f, transitionTime));
    }

    // 放下武器
    public void DropWeapon(float transitionTime = 0.2f)
    {
        StartCoroutine(LerpWeight(rightHandIK, 1f, 0f, transitionTime,
            () => rightHandIK.data.target = null));
    }

    // 开始瞄准
    public void StartAiming()
    {
        headAimIK.data.sourceObjects = new WeightedTransformArray
        {
            new WeightedTransform(aimTarget, 1f)
        };
        StartCoroutine(LerpWeight(headAimIK, 0f, 1f, 0.2f));
    }

    System.Collections.IEnumerator LerpWeight(
        IRigConstraint constraint, float from, float to,
        float duration, System.Action onComplete = null)
    {
        float elapsed = 0f;
        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            constraint.weight = Mathf.Lerp(from, to, elapsed / duration);
            yield return null;
        }
        constraint.weight = to;
        onComplete?.Invoke();
    }
}
```

---

## 七、全身 IK（Full Body IK）与布娃娃融合

### 7.1 布娃娃物理融合

```csharp
using UnityEngine;

/// <summary>
/// 布娃娃与动画的混合控制器
/// 用于死亡动画过渡、受击物理反馈等场景
/// </summary>
public class RagdollBlender : MonoBehaviour
{
    private Animator _animator;
    private Rigidbody[] _ragdollBodies;
    private CharacterJoint[] _ragdollJoints;

    [Header("混合参数")]
    public float blendInDuration  = 0.5f;  // 切入布娃娃时长
    public float blendOutDuration = 1.0f;  // 切出布娃娃时长

    private float _blendWeight;
    private bool  _isRagdoll;

    // 骨骼姿势快照（用于混合）
    private BonePose[] _bonePoses;

    struct BonePose
    {
        public Transform bone;
        public Vector3   position;
        public Quaternion rotation;
    }

    void Awake()
    {
        _animator      = GetComponent<Animator>();
        _ragdollBodies = GetComponentsInChildren<Rigidbody>();
        _ragdollJoints = GetComponentsInChildren<CharacterJoint>();

        // 默认关闭布娃娃物理
        SetRagdollPhysics(false);
    }

    /// <summary>
    /// 触发布娃娃（死亡/重击）
    /// </summary>
    public void EnableRagdoll(Vector3 impactForce = default, Transform impactBone = null)
    {
        if (_isRagdoll) return;
        _isRagdoll = true;

        SetRagdollPhysics(true);
        _animator.enabled = false;

        // 施加冲击力
        if (impactBone != null && impactForce != Vector3.zero)
        {
            var rb = impactBone.GetComponent<Rigidbody>();
            if (rb != null) rb.AddForce(impactForce, ForceMode.Impulse);
        }

        // 拍摄当前骨骼快照（用于混合起始帧）
        SnapshotBonePoses();

        StartCoroutine(BlendToRagdoll());
    }

    /// <summary>
    /// 从布娃娃状态恢复（站起来）
    /// </summary>
    public void DisableRagdoll()
    {
        if (!_isRagdoll) return;

        // 拍摄布娃娃最终姿势快照
        SnapshotBonePoses();

        SetRagdollPhysics(false);
        _animator.enabled = true;
        _animator.Play("GetUp", 0, 0f);

        StartCoroutine(BlendFromRagdoll());
    }

    void SetRagdollPhysics(bool enable)
    {
        foreach (var rb in _ragdollBodies)
        {
            rb.isKinematic = !enable;
            rb.detectCollisions = enable;
        }
    }

    void SnapshotBonePoses()
    {
        var allBones = GetComponentsInChildren<Transform>();
        _bonePoses = new BonePose[allBones.Length];
        for (int i = 0; i < allBones.Length; i++)
        {
            _bonePoses[i] = new BonePose
            {
                bone     = allBones[i],
                position = allBones[i].position,
                rotation = allBones[i].rotation
            };
        }
    }

    System.Collections.IEnumerator BlendToRagdoll()
    {
        float elapsed = 0f;
        while (elapsed < blendInDuration)
        {
            elapsed += Time.deltaTime;
            _blendWeight = elapsed / blendInDuration;
            yield return null;
        }
        _blendWeight = 1f;
    }

    System.Collections.IEnumerator BlendFromRagdoll()
    {
        float elapsed = 0f;
        while (elapsed < blendOutDuration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / blendOutDuration;
            // 从快照姿势插值到当前动画姿势
            foreach (var pose in _bonePoses)
            {
                if (pose.bone == null) continue;
                pose.bone.position = Vector3.Lerp(pose.position, pose.bone.position, t);
                pose.bone.rotation = Quaternion.Slerp(pose.rotation, pose.bone.rotation, t);
            }
            yield return null;
        }
        _isRagdoll = false;
    }
}
```

---

## 八、性能优化策略

### 8.1 IK 更新频率优化

```csharp
public class IKOptimizer : MonoBehaviour
{
    // 根据距离动态调整 IK 更新频率
    public Transform playerCamera;
    public float highDetailDistance = 5f;
    public float mediumDetailDistance = 15f;

    private FootIK _footIK;
    private int _updateInterval;
    private int _frameOffset;

    void Start()
    {
        _footIK = GetComponent<FootIK>();
        // 错开不同角色的 IK 计算帧，避免同帧峰值
        _frameOffset = GetInstanceID() % 3;
    }

    void Update()
    {
        float dist = Vector3.Distance(transform.position, playerCamera.position);
        
        if (dist < highDetailDistance)
            _updateInterval = 1;       // 每帧更新
        else if (dist < mediumDetailDistance)
            _updateInterval = 2;       // 隔帧更新
        else
            _updateInterval = 4;       // 每4帧更新

        bool shouldUpdate = (Time.frameCount + _frameOffset) % _updateInterval == 0;
        _footIK.enabled = shouldUpdate;
    }
}
```

### 8.2 关键性能指标

| 场景 | 推荐方案 | 预期开销 |
|---|---|---|
| 主角脚部 IK | FootIK + Animation Rigging | < 0.2ms/帧 |
| 主角手部抓握 | Two-Bone IK Constraint | < 0.1ms/帧 |
| 近处 NPC (5m内) | FABRIK (10次迭代) | 0.3ms/帧 |
| 中距离 NPC (5-15m) | Two-Bone IK，2帧/次 | 0.1ms/帧 |
| 远处 NPC (15m+) | 关闭 IK | 0ms |
| 布娃娃 | 仅死亡时启用，限制数量≤5 | 1-2ms/帧 |

---

## 九、最佳实践总结

### ✅ 应该做

1. **LateUpdate 中更新 IK**：确保在动画系统评估完成后再修改骨骼变换
2. **使用 IK 权重渐变**：不要突然切换，0→1 的过渡时间控制在 0.2~0.5s
3. **Hint/极向量设置**：Two-Bone IK 必须设置正确的极向量，否则膝盖/肘部方向错误
4. **地面射线缓存**：脚步 IK 的 Raycast 在 FixedUpdate 中做，结果在 OnAnimatorIK 中使用
5. **LOD 降频**：超过 15m 的 NPC 减少 IK 更新频率或完全关闭
6. **骨骼长度预计算**：FABRIK/Two-Bone 的骨骼长度在 Awake 中计算并缓存

### ❌ 避免这些坑

1. **不要在 Update 中直接修改骨骼**：会与 Animator 的评估产生竞争，导致抖动
2. **IK 与根运动冲突**：启用 Root Motion 时注意骨盆 IK 的坐标系转换
3. **过度迭代**：FABRIK 超过 20 次迭代在多角色场景会造成明显性能问题
4. **忽略关节约束**：不加角度约束会导致骨骼翻转或穿模
5. **布娃娃不限制数量**：同时启用的布娃娃物理不要超过 5 个

### 技术选型参考

```
需求 → 推荐方案
────────────────────────────────────
手臂/腿部 IK (2骨骼)     → Two-Bone IK
脊柱/尾巴 IK (多骨骼)    → FABRIK / Chain IK Constraint
头部/眼睛朝向            → Multi-Aim Constraint
地形自适应脚步            → FootIK + Raycast
武器抓握 / 攀爬          → Two-Bone IK + Override Transform
死亡 / 击飞物理           → Ragdoll + 混合过渡
触手 / 机械臂 (带约束)    → CCD Solver
```

---

## 参考资料

- [Unity Animation Rigging 官方文档](https://docs.unity3d.com/Packages/com.unity.animation.rigging@latest)
- [FABRIK: A fast, iterative solver for the Inverse Kinematics problem](http://www.andreasaristidou.com/FABRIK.html)
- [Inverse Kinematics for Game Developers - GDC Vault](https://www.gdcvault.com/)
- [Unity Learn: Inverse Kinematics](https://learn.unity.com/)
