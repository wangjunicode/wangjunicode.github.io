---
title: 游戏路径平滑化算法深度实践：Funnel算法、B样条与后处理优化完全指南
published: 2026-05-09
description: 深入解析游戏寻路后处理中的路径平滑化技术，涵盖NavMesh Funnel算法（Simple Stupid Funnel Algorithm）、B样条曲线平滑、Catmull-Rom样条、弦长参数化以及路径优化完整工程实践。
tags: [Unity, 寻路, NavMesh, 路径平滑, 算法, 游戏开发]
category: 游戏AI与寻路
draft: false
---

# 游戏路径平滑化算法深度实践：Funnel算法、B样条与后处理优化完全指南

## 1. 路径平滑化的必要性

A*或NavMesh等寻路算法产出的原始路径是由离散路点组成的折线路径，角色沿此路径移动时会在路点处产生明显的折向，既不自然也不美观。路径平滑化（Path Smoothing）是游戏寻路系统中至关重要的后处理步骤。

```
原始折线路径：          平滑后路径：
  A──B──C──D          A⌒─────⌒D
  （锐角转折）          （曲线过渡）
```

### 1.1 平滑化目标

- **视觉自然**：避免角色在路点处急转弯
- **移动高效**：削除不必要的绕行，缩短实际路程
- **可预测性**：曲线路径让玩家更容易预判角色轨迹
- **物理友好**：曲率连续的路径利于物理系统中的速度/加速度计算

### 1.2 技术方案对比

| 算法 | 时间复杂度 | 平滑度 | 保持在NavMesh内 | 适用场景 |
|------|-----------|--------|----------------|----------|
| Simple Path Smoothing | O(n²) | 低 | 是 | 快速粗略平滑 |
| Funnel Algorithm | O(n) | 中高 | 是 | NavMesh标准方案 |
| Catmull-Rom样条 | O(n) | 高 | 否（需验证） | 观赏性路径 |
| B样条（Cubic） | O(n) | 高 | 否（需验证） | 过场动画、镜头路径 |
| 弦长参数化 | O(n) | 极高 | 否（需验证） | 精确速度控制 |

## 2. Simple Path Smoothing（射线检测法）

最直观的平滑方案：从起点不断向后续路点射线检测，跳过可直接可达的中间路点。

```csharp
// SimplePathSmoother.cs
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

public static class SimplePathSmoother
{
    /// <summary>
    /// 使用NavMesh射线检测移除冗余中间路点
    /// </summary>
    public static Vector3[] Smooth(Vector3[] rawPath, int agentTypeId = 0, int areaMask = NavMesh.AllAreas)
    {
        if (rawPath == null || rawPath.Length <= 2) return rawPath;

        var result = new List<Vector3> { rawPath[0] };
        int checkFrom = 0;

        while (checkFrom < rawPath.Length - 1)
        {
            int farthest = checkFrom + 1;

            // 从checkFrom出发，找到能直连的最远路点
            for (int i = checkFrom + 2; i < rawPath.Length; i++)
            {
                if (CanReachDirect(rawPath[checkFrom], rawPath[i], agentTypeId, areaMask))
                    farthest = i;
                else
                    break; // NavMesh射线检测，遇到障碍终止
            }

            result.Add(rawPath[farthest]);
            checkFrom = farthest;
        }

        return result.ToArray();
    }

    private static bool CanReachDirect(Vector3 from, Vector3 to,
        int agentTypeId, int areaMask)
    {
        // NavMesh.Raycast 沿NavMesh表面射线检测
        NavMesh.Raycast(from, to, out NavMeshHit hit, areaMask);
        return !hit.hit; // hit.hit = true 表示射线被阻挡
    }
}
```

## 3. Simple Stupid Funnel Algorithm（SSFA）

Funnel算法是NavMesh三角形网格上的最优路径平滑算法，能找到在多边形通道中的真正最短路径。

### 3.1 算法原理

```
多边形通道示意（NavMesh三角形序列）：
  
  ┌──────────────┐
  │  △  △  △  △  │   ← 三角形序列（portal序列）
  └──────────────┘
  
  Funnel漏斗：
    apex（顶点）
     /\
    /  \
   /    \
  left  right   ← 漏斗左右边界
  
  当新portal点在漏斗内：缩窄漏斗
  当新portal点在漏斗外：apex移至对侧边界点，输出该点为路径节点
```

### 3.2 完整Funnel算法实现

```csharp
// FunnelPathSmoother.cs
using System.Collections.Generic;
using UnityEngine;

public class FunnelPathSmoother
{
    /// <summary>portal表示NavMesh相邻三角形间的共享边（左端、右端）</summary>
    public struct Portal
    {
        public Vector3 Left;
        public Vector3 Right;
    }

    /// <summary>
    /// 从NavMesh路径提取portal序列并执行Funnel平滑
    /// </summary>
    public static List<Vector3> SmoothNavMeshPath(NavMeshPath navPath)
    {
        var corners = navPath.corners;
        if (corners.Length <= 2)
            return new List<Vector3>(corners);

        // NavMesh.corners 已经是经过简单处理的路点，可直接用Catmull-Rom再平滑
        // 若需要真正SSFA需要三角形信息（Unity NavMesh不直接暴露三角形）
        // 此处实现基于corners的近似Funnel平滑
        return ApproximateFunnel(new List<Vector3>(corners));
    }

    /// <summary>
    /// 基于路点序列的近似Funnel平滑（利用NavMesh投影验证）
    /// </summary>
    private static List<Vector3> ApproximateFunnel(List<Vector3> waypoints)
    {
        if (waypoints.Count <= 2) return waypoints;

        var result = new List<Vector3> { waypoints[0] };

        int apexIdx = 0;
        Vector3 apexPos = waypoints[0];
        Vector3 leftDir = Vector3.zero, rightDir = Vector3.zero;
        bool initialized = false;

        for (int i = 1; i < waypoints.Count; i++)
        {
            Vector3 dir = (waypoints[i] - apexPos).normalized;

            if (!initialized)
            {
                // 用第一个方向初始化漏斗
                Vector3 perp = Vector3.Cross(dir, Vector3.up).normalized * 0.5f;
                leftDir  = (dir + perp).normalized;
                rightDir = (dir - perp).normalized;
                initialized = true;
                continue;
            }

            // 检查新方向是否在漏斗内
            float leftCross  = CrossY(leftDir,  dir);
            float rightCross = CrossY(rightDir, dir);

            if (leftCross < 0)
            {
                // 超出左边界：更新apex为左边界节点
                result.Add(waypoints[i - 1]);
                apexPos = waypoints[i - 1];
                apexIdx = i - 1;
                initialized = false;
            }
            else if (rightCross > 0)
            {
                // 超出右边界：更新apex为右边界节点
                result.Add(waypoints[i - 1]);
                apexPos = waypoints[i - 1];
                apexIdx = i - 1;
                initialized = false;
            }
            else
            {
                // 在漏斗内，缩窄漏斗
                if (leftCross  > 0) leftDir  = dir;
                if (rightCross < 0) rightDir = dir;
            }
        }

        result.Add(waypoints[waypoints.Count - 1]);
        return result;
    }

    private static float CrossY(Vector3 a, Vector3 b)
        => a.x * b.z - a.z * b.x; // XZ平面2D叉积的Y分量
}
```

## 4. Catmull-Rom样条平滑

Catmull-Rom样条通过所有控制点（插值型），适合将路点序列平滑为连续曲线。

```csharp
// CatmullRomSmoother.cs
using System.Collections.Generic;
using UnityEngine;

public static class CatmullRomSmoother
{
    /// <summary>
    /// 对路点序列做Catmull-Rom样条插值
    /// </summary>
    /// <param name="waypoints">输入路点</param>
    /// <param name="samplesPerSegment">每段采样点数</param>
    /// <param name="alpha">0=Uniform, 0.5=Centripetal(推荐), 1=Chordal</param>
    public static List<Vector3> Smooth(
        List<Vector3> waypoints,
        int samplesPerSegment = 10,
        float alpha = 0.5f)
    {
        if (waypoints.Count < 2) return waypoints;

        // 首尾扩展虚拟控制点（保证端点切线正确）
        var pts = new List<Vector3>(waypoints.Count + 2);
        pts.Add(waypoints[0] + (waypoints[0] - waypoints[1]));  // 虚拟起点
        pts.AddRange(waypoints);
        pts.Add(waypoints[^1] + (waypoints[^1] - waypoints[^2])); // 虚拟终点

        var result = new List<Vector3>();

        for (int i = 1; i < pts.Count - 2; i++)
        {
            Vector3 p0 = pts[i - 1];
            Vector3 p1 = pts[i];
            Vector3 p2 = pts[i + 1];
            Vector3 p3 = pts[i + 2];

            // Centripetal Catmull-Rom：节点间距按弦长0.5次方
            float t0 = 0f;
            float t1 = t0 + Mathf.Pow(Vector3.Distance(p0, p1), alpha);
            float t2 = t1 + Mathf.Pow(Vector3.Distance(p1, p2), alpha);
            float t3 = t2 + Mathf.Pow(Vector3.Distance(p2, p3), alpha);

            for (int s = 0; s < samplesPerSegment; s++)
            {
                float t = Mathf.Lerp(t1, t2, (float)s / samplesPerSegment);
                Vector3 pt = EvalCatmullRom(p0, p1, p2, p3, t0, t1, t2, t3, t);
                result.Add(pt);
            }
        }

        result.Add(waypoints[^1]);
        return result;
    }

    private static Vector3 EvalCatmullRom(
        Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3,
        float t0, float t1, float t2, float t3, float t)
    {
        Vector3 A1 = t1 != t0 ? (p0 * (t1 - t) + p1 * (t - t0)) / (t1 - t0) : p1;
        Vector3 A2 = t2 != t1 ? (p1 * (t2 - t) + p2 * (t - t1)) / (t2 - t1) : p2;
        Vector3 A3 = t3 != t2 ? (p2 * (t3 - t) + p3 * (t - t2)) / (t3 - t2) : p3;

        Vector3 B1 = t2 != t0 ? (A1 * (t2 - t) + A2 * (t - t0)) / (t2 - t0) : A2;
        Vector3 B2 = t3 != t1 ? (A2 * (t3 - t) + A3 * (t - t1)) / (t3 - t1) : A3;

        return t2 != t1 ? (B1 * (t2 - t) + B2 * (t - t1)) / (t2 - t1) : B2;
    }
}
```

## 5. B样条平滑（Cubic B-Spline）

B样条不通过控制点（逼近型），曲线更平滑，适合生成平滑度极高的路径。

```csharp
// BSplineSmoother.cs
using System.Collections.Generic;
using UnityEngine;

public static class BSplineSmoother
{
    /// <summary>
    /// 均匀三次B样条平滑
    /// </summary>
    public static List<Vector3> Smooth(List<Vector3> controlPoints, int totalSamples = 200)
    {
        if (controlPoints.Count < 4) return controlPoints;

        var result = new List<Vector3>(totalSamples);
        int n = controlPoints.Count - 1;
        float step = (float)(n - 2) / totalSamples;

        for (int i = 0; i <= totalSamples; i++)
        {
            float u = 2f + i * step; // u范围 [2, n-1]
            int k = Mathf.FloorToInt(u);
            k = Mathf.Clamp(k, 2, n - 1);
            float t = u - k;

            Vector3 p = EvalCubicBSpline(
                controlPoints[k - 2],
                controlPoints[k - 1],
                controlPoints[k],
                controlPoints[k + 1],
                t);
            result.Add(p);
        }

        return result;
    }

    private static Vector3 EvalCubicBSpline(
        Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
    {
        // 均匀三次B样条基函数矩阵（Cox-de Boor递推的矩阵形式）
        float t2 = t * t;
        float t3 = t2 * t;

        float b0 = (-t3 + 3f * t2 - 3f * t + 1f) / 6f;
        float b1 = ( 3f * t3 - 6f * t2          + 4f) / 6f;
        float b2 = (-3f * t3 + 3f * t2 + 3f * t + 1f) / 6f;
        float b3 = ( t3                               ) / 6f;

        return b0 * p0 + b1 * p1 + b2 * p2 + b3 * p3;
    }

    /// <summary>
    /// 计算B样条上某点的切线方向（用于角色朝向）
    /// </summary>
    public static Vector3 EvalTangent(List<Vector3> controlPoints, float normalizedT)
    {
        int n = controlPoints.Count - 1;
        float u = 2f + normalizedT * (n - 2);
        int k = Mathf.Clamp(Mathf.FloorToInt(u), 2, n - 1);
        float t = u - k;

        float t2 = t * t;
        float db0 = (-3f * t2 + 6f * t - 3f) / 6f;
        float db1 = ( 9f * t2 - 12f* t      ) / 6f;
        float db2 = (-9f * t2 + 6f * t + 3f ) / 6f;
        float db3 = ( 3f * t2                ) / 6f;

        return (db0 * controlPoints[k - 2] + db1 * controlPoints[k - 1]
              + db2 * controlPoints[k] + db3 * controlPoints[k + 1]).normalized;
    }
}
```

## 6. 弦长参数化（Arc-Length Parameterization）

等弦长参数化使得路径上的 t 参数与实际距离成正比，实现均速运动。

```csharp
// ArcLengthParameterizer.cs
using System.Collections.Generic;
using UnityEngine;

public class ArcLengthParameterizer
{
    private readonly List<Vector3> _points;
    private readonly float[] _arcLengths; // 每点累积弧长
    private float _totalLength;

    public float TotalLength => _totalLength;

    public ArcLengthParameterizer(List<Vector3> sampledPoints)
    {
        _points     = sampledPoints;
        _arcLengths = new float[sampledPoints.Count];
        BuildLUT();
    }

    private void BuildLUT()
    {
        _arcLengths[0] = 0f;
        for (int i = 1; i < _points.Count; i++)
        {
            _arcLengths[i] = _arcLengths[i - 1]
                           + Vector3.Distance(_points[i - 1], _points[i]);
        }
        _totalLength = _arcLengths[^1];
    }

    /// <summary>按弧长比例 [0,1] 采样路径上的点</summary>
    public Vector3 Sample(float t)
    {
        float targetLen = Mathf.Clamp01(t) * _totalLength;
        int idx = BinarySearchArcLength(targetLen);

        if (idx >= _points.Count - 1)
            return _points[^1];

        float segStart = _arcLengths[idx];
        float segEnd   = _arcLengths[idx + 1];
        float segLen   = segEnd - segStart;

        if (segLen < 1e-6f) return _points[idx];

        float localT = (targetLen - segStart) / segLen;
        return Vector3.Lerp(_points[idx], _points[idx + 1], localT);
    }

    /// <summary>按实际距离（米）采样</summary>
    public Vector3 SampleByDistance(float distance)
        => Sample(distance / _totalLength);

    private int BinarySearchArcLength(float targetLen)
    {
        int lo = 0, hi = _arcLengths.Length - 1;
        while (lo < hi)
        {
            int mid = (lo + hi) / 2;
            if (_arcLengths[mid] < targetLen) lo = mid + 1;
            else                              hi = mid;
        }
        return Mathf.Max(0, lo - 1);
    }
}
```

## 7. NavMesh约束平滑（路径回投）

样条平滑后路径可能脱离NavMesh，需要将偏离点投影回NavMesh。

```csharp
// NavMeshConstrainedSmoother.cs
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

public static class NavMeshConstrainedSmoother
{
    /// <summary>
    /// 将平滑后路径上的点投影回NavMesh表面
    /// </summary>
    public static List<Vector3> ProjectToNavMesh(
        List<Vector3> smoothedPath,
        float maxProjectionDist = 1.5f,
        int areaMask = NavMesh.AllAreas)
    {
        var result = new List<Vector3>(smoothedPath.Count);

        foreach (var pt in smoothedPath)
        {
            if (NavMesh.SamplePosition(pt, out NavMeshHit hit, maxProjectionDist, areaMask))
                result.Add(hit.position);
            else
                result.Add(pt); // 投影失败，保留原始点
        }

        return result;
    }

    /// <summary>
    /// 完整的平滑+约束流程：Catmull-Rom平滑后投影NavMesh
    /// </summary>
    public static List<Vector3> SmoothAndConstrain(
        Vector3[] navCorners,
        int samplesPerSegment = 8,
        float maxProjectionDist = 1f)
    {
        // Step1: Simple Path Smoothing移除冗余路点
        var simplified = SimplePathSmoother.Smooth(navCorners);

        // Step2: Catmull-Rom样条插值
        var smoothed = CatmullRomSmoother.Smooth(
            new List<Vector3>(simplified),
            samplesPerSegment);

        // Step3: 投影回NavMesh
        var constrained = ProjectToNavMesh(smoothed, maxProjectionDist);

        // Step4: 弧长参数化（可选，用于均速移动）
        return constrained;
    }
}
```

## 8. 路径跟随器（Path Follower）

集成弧长参数化的路径跟随组件，实现角色平滑均速移动。

```csharp
// SmoothPathFollower.cs
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

public class SmoothPathFollower : MonoBehaviour
{
    [Header("移动参数")]
    [SerializeField] private float _moveSpeed   = 4f;
    [SerializeField] private float _rotateSpeed = 360f;
    [SerializeField] private float _arrivalDist = 0.1f;

    [Header("平滑参数")]
    [SerializeField] private int _samplesPerSegment = 10;

    private ArcLengthParameterizer _parameterizer;
    private float   _traveledDistance;
    private bool    _isMoving;
    private Vector3 _destination;

    public bool IsMoving => _isMoving;

    public void MoveTo(Vector3 target)
    {
        _destination = target;
        var navAgent  = GetComponent<NavMeshAgent>();

        // 使用NavMeshAgent计算NavMesh路径
        var path = new NavMeshPath();
        NavMesh.CalculatePath(transform.position, target,
            NavMesh.AllAreas, path);

        if (path.status == NavMeshPathStatus.PathComplete)
        {
            // 平滑并约束路径
            var smoothedPoints = NavMeshConstrainedSmoother.SmoothAndConstrain(
                path.corners, _samplesPerSegment);

            _parameterizer    = new ArcLengthParameterizer(smoothedPoints);
            _traveledDistance = 0f;
            _isMoving         = true;

            // 禁用NavMeshAgent自动移动（我们手动控制位置）
            if (navAgent != null) navAgent.isStopped = true;
        }
        else
        {
            Debug.LogWarning($"[PathFollower] 无法找到到 {target} 的路径");
        }
    }

    private void Update()
    {
        if (!_isMoving || _parameterizer == null) return;

        _traveledDistance += _moveSpeed * Time.deltaTime;

        if (_traveledDistance >= _parameterizer.TotalLength)
        {
            transform.position = _destination;
            _isMoving = false;
            OnArrived();
            return;
        }

        Vector3 currentPos = _parameterizer.SampleByDistance(_traveledDistance);
        Vector3 nextPos    = _parameterizer.SampleByDistance(
            _traveledDistance + 0.05f);

        // 更新位置
        transform.position = currentPos;

        // 平滑旋转朝向前方
        Vector3 dir = nextPos - currentPos;
        if (dir.sqrMagnitude > 1e-6f)
        {
            Quaternion targetRot = Quaternion.LookRotation(dir);
            transform.rotation = Quaternion.RotateTowards(
                transform.rotation, targetRot,
                _rotateSpeed * Time.deltaTime);
        }
    }

    protected virtual void OnArrived()
    {
        Debug.Log($"[PathFollower] {name} 到达目的地");
    }

    private void OnDrawGizmosSelected()
    {
        if (_parameterizer == null) return;
        // 绘制平滑路径预览
        Gizmos.color = Color.cyan;
        for (int i = 0; i < 50; i++)
        {
            float t0 = (float)i / 50;
            float t1 = (float)(i + 1) / 50;
            Gizmos.DrawLine(
                _parameterizer.Sample(t0),
                _parameterizer.Sample(t1));
        }
    }
}
```

## 9. 群体路径平滑与避障联合优化

```csharp
// GroupPathOptimizer.cs
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 多Agent路径平滑优化器：避免群体路径在同一曲线上重叠
/// </summary>
public static class GroupPathOptimizer
{
    /// <summary>
    /// 为同一目标的多个Agent生成偏移后的平滑路径
    /// 使各Agent在同一条路上排成队列而非重叠
    /// </summary>
    public static List<Vector3>[] GenerateGroupPaths(
        Vector3[] sharedPath,
        int agentCount,
        float spacing = 0.8f,
        int samplesPerSegment = 10)
    {
        // 先平滑主路径
        var smoothed = CatmullRomSmoother.Smooth(
            new List<Vector3>(sharedPath), samplesPerSegment);
        var parameterizer = new ArcLengthParameterizer(smoothed);

        var groupPaths = new List<Vector3>[agentCount];

        for (int i = 0; i < agentCount; i++)
        {
            // 每个Agent的起始位置偏移，形成队列
            float startOffset = i * spacing;
            var agentPath = new List<Vector3>();

            for (int s = 0; s <= 100; s++)
            {
                float dist = startOffset + (float)s / 100 * parameterizer.TotalLength;
                agentPath.Add(parameterizer.SampleByDistance(dist));
            }

            groupPaths[i] = agentPath;
        }

        return groupPaths;
    }
}
```

## 10. 动态障碍物局部路径修复

```csharp
// DynamicObstacleRepairer.cs
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.AI;

public class DynamicObstacleRepairer : MonoBehaviour
{
    [SerializeField] private SmoothPathFollower _follower;
    [SerializeField] private float _checkInterval  = 0.3f;
    [SerializeField] private float _lookAheadDist  = 3f;

    private float _timer;

    private void Update()
    {
        if (!_follower.IsMoving) return;

        _timer += Time.deltaTime;
        if (_timer < _checkInterval) return;
        _timer = 0f;

        CheckAndRepairPath();
    }

    private void CheckAndRepairPath()
    {
        // 向前检测障碍物
        Vector3 forward = transform.forward;
        if (Physics.SphereCast(transform.position, 0.5f, forward,
            out RaycastHit hit, _lookAheadDist, LayerMask.GetMask("Obstacle")))
        {
            Debug.Log($"[PathRepair] 检测到动态障碍物: {hit.collider.name}，重新寻路");
            // 重新导航至原目标
            _follower.MoveTo(_follower.transform.position
                + transform.forward * (_lookAheadDist + 2f)); // 临时绕行目标
        }
    }
}
```

## 11. 性能优化策略

```csharp
// PathSmoothingProfiler.cs
using UnityEngine;

public static class PathSmoothingPerformance
{
    /// <summary>
    /// 根据屏幕距离动态调整采样密度（LOD策略）
    /// </summary>
    public static int GetAdaptiveSamples(Vector3 agentPos, Camera cam, 
        int minSamples = 4, int maxSamples = 16)
    {
        float screenDist = Vector3.Distance(
            cam.WorldToViewportPoint(agentPos),
            new Vector3(0.5f, 0.5f, 0));
        
        // 距离屏幕中心越近，采样密度越高
        float factor = 1f - Mathf.Clamp01(screenDist * 2f);
        return Mathf.RoundToInt(Mathf.Lerp(minSamples, maxSamples, factor));
    }
}
```

## 12. 最佳实践总结

| 实践要点 | 说明 |
|----------|------|
| 分层应用 | 先用Simple Smoothing删除冗余路点，再用B样条/Catmull-Rom插值，减少样条段数 |
| NavMesh回投 | 样条平滑后必须投影回NavMesh，防止穿模或穿越障碍 |
| 弧长参数化 | 均速移动场景必须做弧长参数化，否则速度不均匀 |
| 采样密度LOD | 根据与摄像机距离动态调整采样数，近处密远处稀 |
| Catmull-Rom α=0.5 | Centripetal参数化避免Uniform Catmull-Rom的尖点（cusps）问题 |
| 异步计算 | 路径平滑在子线程完成，主线程只读取最终结果，避免卡帧 |
| 切线驱动旋转 | 用曲线切线控制角色朝向，而非速度方向，更平滑 |
| 群体队列间距 | 多NPC共享路径时按弧长偏移形成自然队列，避免重叠穿插 |

---

> 本文代码基于 Unity 2022.3 LTS，NavMesh路径处理需 AI Navigation 包。Catmull-Rom alpha=0.5（Centripetal参数化）是游戏实践中最推荐的参数设置。
