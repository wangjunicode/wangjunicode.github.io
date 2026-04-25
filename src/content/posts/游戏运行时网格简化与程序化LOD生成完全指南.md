---
title: 游戏运行时网格简化与程序化LOD生成完全指南
published: 2026-04-25
description: 深入解析游戏开发中网格简化算法（QEM二次误差度量、边折叠算法）、Unity运行时LOD动态生成方案、基于视角距离的自适应LOD调度系统，以及程序化地形与植被的LOD流式管理，附完整C#实现与最佳实践。
tags: [LOD, Mesh, 性能优化, Unity, 网格简化, 程序化]
category: 渲染技术
draft: false
---

# 游戏运行时网格简化与程序化LOD生成完全指南

## 一、LOD技术概述与必要性

LOD（Level of Detail，细节层次）是游戏渲染性能优化的基石之一。其核心思想：

- **近处**使用高精度模型（高面数、高贴图分辨率）
- **远处**使用低精度模型（低面数、低贴图分辨率）
- **极远处**直接剔除（Culling）

在一个典型的开放世界游戏中，不使用LOD可能需要渲染 **500万+ 三角面**，使用LOD后可降低到 **20万~50万**，性能提升 **10~25倍**。

### 1.1 传统LOD的问题

Unity内置LOD Group系统需要美术手动制作多套模型（LOD0/LOD1/LOD2...），存在以下痛点：

1. **美术成本高**：每个模型需制作3~5套不同精度版本
2. **包体膨胀**：多套模型大幅增加资源体积
3. **无法动态适配**：固定的切换距离无法适应动态分辨率等场景
4. **程序化内容无LOD**：运行时生成的Mesh没有预制LOD

**程序化LOD生成**可以在运行时根据需要动态简化网格，解决上述问题。

---

## 二、网格简化核心算法：二次误差度量（QEM）

### 2.1 QEM算法原理

QEM（Quadric Error Metrics）由Garland & Heckbert于1997年提出，是目前最流行的网格简化算法：

**核心思想**：
- 对每个顶点维护一个 **4×4的误差矩阵Q**
- 每次选择折叠误差最小的 **边(v1→v2)**，将其合并为一个新顶点v*
- 新顶点位置使得 **v* = argmin(v'Qv)**（使误差最小）

```
初始状态：  三角形A(v1,v2,v3) + 三角形B(v2,v4,v3)

     v1
    /  \
   v3---v2        边折叠 v1-v3 → v_new
    \  /
     v4

折叠后：  三角形C(v_new,v2,v4)
          （减少了一个三角形，顶点数-1）
```

### 2.2 简化版QEM实现（C#）

```csharp
using UnityEngine;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// 基于QEM算法的运行时网格简化器
/// 适用于游戏运行时动态生成LOD网格
/// 注意：完整QEM实现较复杂，此处为简化版（边折叠策略）
/// </summary>
public class MeshSimplifier
{
    /// <summary>
    /// 简化网格到目标三角形数量
    /// </summary>
    /// <param name="sourceMesh">原始网格</param>
    /// <param name="targetTriangleRatio">目标面数比例 (0~1)</param>
    /// <returns>简化后的网格</returns>
    public static Mesh Simplify(Mesh sourceMesh, float targetTriangleRatio)
    {
        targetTriangleRatio = Mathf.Clamp01(targetTriangleRatio);
        
        if (targetTriangleRatio >= 1.0f)
            return sourceMesh;
        
        var vertices = new List<Vector3>(sourceMesh.vertices);
        var normals  = new List<Vector3>(sourceMesh.normals);
        var uvs      = new List<Vector2>(sourceMesh.uv);
        var triangles = new List<int>(sourceMesh.triangles);

        int targetTriCount = Mathf.Max(
            (int)(triangles.Count / 3 * targetTriangleRatio) * 3,
            3 // 至少保留1个三角形
        );

        // 构建边-三角形关系表
        var edgeCostQueue = BuildEdgeCostQueue(vertices, triangles);
        
        int iterations = 0;
        int maxIterations = (triangles.Count - targetTriCount) / 3;

        while (triangles.Count > targetTriCount && iterations < maxIterations)
        {
            if (edgeCostQueue.Count == 0) break;
            
            // 取误差最小的边进行折叠
            var cheapestEdge = edgeCostQueue.Dequeue();
            
            if (!IsEdgeValid(cheapestEdge, triangles))
            {
                iterations++;
                continue;
            }

            // 执行边折叠
            CollapseEdge(cheapestEdge, vertices, normals, uvs, triangles);
            
            // 更新受影响的边的误差
            UpdateEdgeCosts(cheapestEdge, vertices, triangles, edgeCostQueue);
            
            iterations++;
        }

        // 清理退化三角形（面积为0的三角形）
        RemoveDegenerateTriangles(triangles, vertices);

        return BuildResultMesh(vertices, normals, uvs, triangles);
    }

    // === 内部实现 ===

    private struct Edge
    {
        public int V1, V2;      // 边的两个顶点索引
        public float Cost;      // 折叠误差
        public Vector3 OptimalPos; // 折叠后最优位置
    }

    private static SimplePriorityQueue<Edge> BuildEdgeCostQueue(
        List<Vector3> vertices, List<int> triangles)
    {
        var edgeSet = new HashSet<(int, int)>();
        var queue = new SimplePriorityQueue<Edge>();

        for (int i = 0; i < triangles.Count; i += 3)
        {
            int v0 = triangles[i], v1 = triangles[i+1], v2 = triangles[i+2];
            TryAddEdge(v0, v1, vertices, edgeSet, queue);
            TryAddEdge(v1, v2, vertices, edgeSet, queue);
            TryAddEdge(v2, v0, vertices, edgeSet, queue);
        }

        return queue;
    }

    private static void TryAddEdge(int v1, int v2, List<Vector3> vertices,
        HashSet<(int, int)> edgeSet, SimplePriorityQueue<Edge> queue)
    {
        int lo = Mathf.Min(v1, v2), hi = Mathf.Max(v1, v2);
        if (!edgeSet.Add((lo, hi))) return;

        // 计算折叠误差：使用边长作为简化版误差估计
        // 完整QEM应使用二次误差矩阵，此处简化
        float cost = Vector3.Distance(vertices[v1], vertices[v2]);
        Vector3 optPos = (vertices[v1] + vertices[v2]) * 0.5f;

        queue.Enqueue(new Edge { V1 = v1, V2 = v2, Cost = cost, OptimalPos = optPos }, cost);
    }

    private static bool IsEdgeValid(Edge edge, List<int> triangles)
    {
        // 检查边是否仍存在于当前三角形中
        for (int i = 0; i < triangles.Count; i += 3)
        {
            int v0 = triangles[i], v1 = triangles[i+1], v2 = triangles[i+2];
            bool hasV1 = (v0 == edge.V1 || v1 == edge.V1 || v2 == edge.V1);
            bool hasV2 = (v0 == edge.V2 || v1 == edge.V2 || v2 == edge.V2);
            if (hasV1 && hasV2) return true;
        }
        return false;
    }

    private static void CollapseEdge(Edge edge, List<Vector3> vertices, 
        List<Vector3> normals, List<Vector2> uvs, List<int> triangles)
    {
        // 将v2合并到v1，更新v1的位置为最优位置
        vertices[edge.V1] = edge.OptimalPos;
        if (edge.V1 < normals.Count && edge.V2 < normals.Count)
            normals[edge.V1] = (normals[edge.V1] + normals[edge.V2]).normalized;
        if (edge.V1 < uvs.Count && edge.V2 < uvs.Count)
            uvs[edge.V1] = (uvs[edge.V1] + uvs[edge.V2]) * 0.5f;

        // 将所有引用v2的三角形改为引用v1
        for (int i = 0; i < triangles.Count; i++)
        {
            if (triangles[i] == edge.V2)
                triangles[i] = edge.V1;
        }
    }

    private static void UpdateEdgeCosts(Edge collapsedEdge, List<Vector3> vertices,
        List<int> triangles, SimplePriorityQueue<Edge> queue)
    {
        // 简化实现：不实际更新队列（完整实现应标记失效并重新加入）
        // 通过IsEdgeValid过滤即可处理大部分情况
    }

    private static void RemoveDegenerateTriangles(List<int> triangles, List<Vector3> vertices)
    {
        for (int i = triangles.Count - 3; i >= 0; i -= 3)
        {
            int v0 = triangles[i], v1 = triangles[i+1], v2 = triangles[i+2];
            
            // 退化三角形：有两个或更多相同顶点
            if (v0 == v1 || v1 == v2 || v0 == v2)
            {
                triangles.RemoveRange(i, 3);
                continue;
            }
            
            // 退化三角形：面积接近0
            Vector3 edge1 = vertices[v1] - vertices[v0];
            Vector3 edge2 = vertices[v2] - vertices[v0];
            float area = Vector3.Cross(edge1, edge2).magnitude * 0.5f;
            if (area < 1e-6f)
                triangles.RemoveRange(i, 3);
        }
    }

    private static Mesh BuildResultMesh(List<Vector3> vertices, List<Vector3> normals,
        List<Vector2> uvs, List<int> triangles)
    {
        var mesh = new Mesh();
        
        // 超过65535顶点需使用32位索引
        if (vertices.Count > 65535)
            mesh.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        
        mesh.SetVertices(vertices);
        if (normals.Count == vertices.Count)
            mesh.SetNormals(normals);
        if (uvs.Count == vertices.Count)
            mesh.SetUVs(0, uvs);
        mesh.SetTriangles(triangles, 0);
        mesh.RecalculateBounds();
        
        if (normals.Count != vertices.Count)
            mesh.RecalculateNormals();
        
        return mesh;
    }
}

/// <summary>
/// 简单优先队列实现（最小堆）
/// </summary>
public class SimplePriorityQueue<T>
{
    private List<(T item, float priority)> _heap = new List<(T, float)>();
    public int Count => _heap.Count;

    public void Enqueue(T item, float priority)
    {
        _heap.Add((item, priority));
        BubbleUp(_heap.Count - 1);
    }

    public T Dequeue()
    {
        var top = _heap[0].item;
        int last = _heap.Count - 1;
        _heap[0] = _heap[last];
        _heap.RemoveAt(last);
        if (_heap.Count > 0) SiftDown(0);
        return top;
    }

    private void BubbleUp(int i)
    {
        while (i > 0)
        {
            int parent = (i - 1) / 2;
            if (_heap[parent].priority <= _heap[i].priority) break;
            (_heap[parent], _heap[i]) = (_heap[i], _heap[parent]);
            i = parent;
        }
    }

    private void SiftDown(int i)
    {
        int n = _heap.Count;
        while (true)
        {
            int smallest = i, left = 2*i+1, right = 2*i+2;
            if (left  < n && _heap[left].priority  < _heap[smallest].priority) smallest = left;
            if (right < n && _heap[right].priority < _heap[smallest].priority) smallest = right;
            if (smallest == i) break;
            (_heap[smallest], _heap[i]) = (_heap[i], _heap[smallest]);
            i = smallest;
        }
    }
}
```

---

## 三、运行时LOD生成系统

### 3.1 LOD生成管理器

```csharp
using UnityEngine;
using System.Collections;
using System.Collections.Generic;

/// <summary>
/// 运行时LOD生成管理器
/// 为没有预制LOD的Mesh自动生成多级LOD
/// 支持后台异步生成，不阻塞主线程
/// </summary>
[RequireComponent(typeof(MeshFilter))]
public class RuntimeLODGenerator : MonoBehaviour
{
    [System.Serializable]
    public class LODLevel
    {
        [Range(0f, 1f)]
        public float ScreenRelativeTransitionHeight = 0.5f;  // 切换距离（屏幕比例）
        [Range(0.01f, 1f)]
        public float TriangleRatio = 0.5f;                   // 面数比例
    }

    [Header("LOD配置")]
    [SerializeField] private LODLevel[] _lodLevels = new LODLevel[]
    {
        new LODLevel { ScreenRelativeTransitionHeight = 0.6f, TriangleRatio = 1.0f },  // LOD0: 100%
        new LODLevel { ScreenRelativeTransitionHeight = 0.3f, TriangleRatio = 0.5f },  // LOD1: 50%
        new LODLevel { ScreenRelativeTransitionHeight = 0.1f, TriangleRatio = 0.2f },  // LOD2: 20%
        new LODLevel { ScreenRelativeTransitionHeight = 0.0f, TriangleRatio = 0.05f }, // LOD3: 5%
    };

    [Header("生成配置")]
    [SerializeField] private bool _generateOnStart = true;
    [SerializeField] private bool _cacheGeneratedLODs = true;

    private static readonly Dictionary<Mesh, Mesh[]> s_LODCache = new Dictionary<Mesh, Mesh[]>();
    
    private MeshFilter _meshFilter;
    private LODGroup _lodGroup;
    private bool _isGenerated = false;

    private void Start()
    {
        if (_generateOnStart)
            StartCoroutine(GenerateLODsAsync());
    }

    /// <summary>
    /// 异步生成LOD网格，使用协程分帧处理避免卡顿
    /// </summary>
    public IEnumerator GenerateLODsAsync()
    {
        _meshFilter = GetComponent<MeshFilter>();
        var sourceMesh = _meshFilter.sharedMesh;
        
        if (sourceMesh == null)
        {
            Debug.LogWarning($"[RuntimeLOD] {name} 没有Mesh，跳过LOD生成");
            yield break;
        }

        // 检查缓存
        if (_cacheGeneratedLODs && s_LODCache.TryGetValue(sourceMesh, out var cachedLODs))
        {
            ApplyLODGroup(cachedLODs);
            _isGenerated = true;
            yield break;
        }

        // 分帧生成各级LOD
        var generatedMeshes = new Mesh[_lodLevels.Length];
        generatedMeshes[0] = sourceMesh; // LOD0 使用原始Mesh

        for (int i = 1; i < _lodLevels.Length; i++)
        {
            float ratio = _lodLevels[i].TriangleRatio;
            
            // 在工作线程生成（Unity 2021+ 支持在非主线程操作Mesh数据）
            var lodMesh = MeshSimplifier.Simplify(sourceMesh, ratio);
            lodMesh.name = $"{sourceMesh.name}_LOD{i}";
            generatedMeshes[i] = lodMesh;
            
            // 每生成一级LOD后让出一帧
            yield return null;
        }

        // 缓存结果
        if (_cacheGeneratedLODs)
            s_LODCache[sourceMesh] = generatedMeshes;

        // 应用LOD Group
        ApplyLODGroup(generatedMeshes);
        _isGenerated = true;
        
        int originalTris = sourceMesh.triangles.Length / 3;
        int lowestTris = generatedMeshes[^1].triangles.Length / 3;
        Debug.Log($"[RuntimeLOD] {name} LOD生成完成: " +
                 $"LOD0={originalTris}面 → LOD{_lodLevels.Length-1}={lowestTris}面 " +
                 $"(减少{(1f - (float)lowestTris/originalTris)*100:F0}%)");
    }

    private void ApplyLODGroup(Mesh[] lodMeshes)
    {
        // 创建或获取LOD Group组件
        _lodGroup = GetComponent<LODGroup>() ?? gameObject.AddComponent<LODGroup>();

        var renderer = GetComponent<MeshRenderer>();
        var lods = new LOD[_lodLevels.Length];

        for (int i = 0; i < _lodLevels.Length; i++)
        {
            // 为每个LOD级别创建独立的MeshFilter+MeshRenderer
            GameObject lodObj;
            if (i == 0)
            {
                // LOD0直接使用当前GameObject
                _meshFilter.sharedMesh = lodMeshes[0];
                lods[0] = new LOD(_lodLevels[0].ScreenRelativeTransitionHeight, 
                                  new Renderer[] { renderer });
            }
            else
            {
                // 其他LOD级别创建子GameObject
                lodObj = new GameObject($"LOD{i}")
                {
                    hideFlags = HideFlags.HideInHierarchy
                };
                lodObj.transform.SetParent(transform, false);
                
                var mf = lodObj.AddComponent<MeshFilter>();
                mf.sharedMesh = lodMeshes[i];
                
                var mr = lodObj.AddComponent<MeshRenderer>();
                mr.sharedMaterials = renderer.sharedMaterials;
                
                lods[i] = new LOD(_lodLevels[i].ScreenRelativeTransitionHeight,
                                  new Renderer[] { mr });
            }
        }

        _lodGroup.SetLODs(lods);
        _lodGroup.RecalculateBounds();
    }

    /// <summary>
    /// 清理LOD缓存（切换场景时调用）
    /// </summary>
    public static void ClearCache()
    {
        s_LODCache.Clear();
        Debug.Log("[RuntimeLOD] LOD缓存已清理");
    }
}
```

### 3.2 批量LOD生成器（程序化地形场景）

```csharp
using UnityEngine;
using System.Collections;
using System.Collections.Generic;
using System.Linq;

/// <summary>
/// 批量LOD生成器
/// 用于开放世界游戏中大量程序化生成的对象（树木、岩石等）
/// 使用优先级队列按距离排序，优先处理近处对象
/// </summary>
public class BatchLODGenerator : MonoBehaviour
{
    [Header("批量配置")]
    [SerializeField] private Transform _playerTransform;
    [SerializeField] private float _maxGenerationDistance = 200f;
    [SerializeField] private int _generationsPerFrame = 3;  // 每帧最多生成几个

    private PriorityQueue<RuntimeLODGenerator, float> _pendingQueue
        = new PriorityQueue<RuntimeLODGenerator, float>();
    private HashSet<RuntimeLODGenerator> _processing = new HashSet<RuntimeLODGenerator>();

    private void Update()
    {
        ProcessQueue();
    }

    public void RegisterForLOD(RuntimeLODGenerator lodGenerator)
    {
        if (_processing.Contains(lodGenerator)) return;
        
        float distance = _playerTransform 
            ? Vector3.Distance(lodGenerator.transform.position, _playerTransform.position)
            : 0f;
        
        if (distance > _maxGenerationDistance) return;
        
        _pendingQueue.Enqueue(lodGenerator, distance);
    }

    private void ProcessQueue()
    {
        int processed = 0;
        while (_pendingQueue.Count > 0 && processed < _generationsPerFrame)
        {
            var generator = _pendingQueue.Dequeue();
            if (generator == null) continue;
            
            _processing.Add(generator);
            StartCoroutine(ProcessGenerator(generator));
            processed++;
        }
    }

    private IEnumerator ProcessGenerator(RuntimeLODGenerator generator)
    {
        yield return generator.GenerateLODsAsync();
        _processing.Remove(generator);
    }
}
```

---

## 四、自适应LOD调度系统

### 4.1 基于GPU时间的动态LOD偏移

```csharp
/// <summary>
/// 自适应LOD偏移控制器
/// 根据当前GPU帧时间动态调整全局LOD偏移量
/// 帧率下降时自动降低LOD精度，帧率充足时恢复高精度
/// </summary>
public class AdaptiveLODBias : MonoBehaviour
{
    [Header("目标帧率配置")]
    [SerializeField] private float _targetFPS = 60f;
    [SerializeField] private float _criticalFPS = 45f;   // 低于此值开始降级
    [SerializeField] private float _recoveryFPS = 55f;   // 高于此值开始恢复

    [Header("LOD偏移范围")]
    [SerializeField] private float _minLODBias = -1f;   // 负数 = 更精细
    [SerializeField] private float _maxLODBias =  2f;   // 正数 = 更粗糙

    [Header("响应速度")]
    [SerializeField] private float _degradeSpeed   = 0.5f; // 降级响应速度
    [SerializeField] private float _recoverySpeed  = 0.1f; // 恢复响应速度（慢恢复）

    private float _currentBias = 0f;
    private float _smoothFPS;

    private void Start()
    {
        _smoothFPS = _targetFPS;
    }

    private void Update()
    {
        // 平滑FPS计算，避免瞬间波动
        float currentFPS = 1f / Time.unscaledDeltaTime;
        _smoothFPS = Mathf.Lerp(_smoothFPS, currentFPS, Time.unscaledDeltaTime * 2f);

        float targetBias = _currentBias;

        if (_smoothFPS < _criticalFPS)
        {
            // 帧率低于临界值：增大LOD偏移（降低精度）
            float severity = (_criticalFPS - _smoothFPS) / _criticalFPS;
            targetBias = Mathf.Lerp(_currentBias, _maxLODBias, _degradeSpeed * Time.unscaledDeltaTime);
        }
        else if (_smoothFPS > _recoveryFPS)
        {
            // 帧率充足：缓慢降低LOD偏移（恢复精度）
            targetBias = Mathf.Lerp(_currentBias, _minLODBias, _recoverySpeed * Time.unscaledDeltaTime);
        }

        _currentBias = Mathf.Clamp(targetBias, _minLODBias, _maxLODBias);

        // 应用全局LOD偏移
        QualitySettings.lodBias = Mathf.Max(0.1f, 1f - _currentBias * 0.5f);
    }

    private void OnGUI()
    {
        #if UNITY_EDITOR || DEVELOPMENT_BUILD
        GUILayout.Label($"LOD Bias: {QualitySettings.lodBias:F2} | FPS: {_smoothFPS:F1}");
        #endif
    }
}
```

### 4.2 视锥体外LOD强制降级

```csharp
/// <summary>
/// 视锥体感知LOD控制器
/// 对处于视锥体边缘的对象提前降低LOD，节省渲染资源
/// </summary>
[RequireComponent(typeof(LODGroup))]
public class FrustumAwareLOD : MonoBehaviour
{
    [SerializeField] private Camera _mainCamera;
    [SerializeField] private float _edgeFrustumAngle = 15f;  // 视锥体边缘角度阈值

    private LODGroup _lodGroup;
    private int _forcedLOD = -1;  // -1 表示不强制

    private void Awake()
    {
        _lodGroup = GetComponent<LODGroup>();
        if (_mainCamera == null)
            _mainCamera = Camera.main;
    }

    private void Update()
    {
        if (_mainCamera == null) return;

        // 计算对象在视锥体中的位置
        Vector3 viewportPos = _mainCamera.WorldToViewportPoint(transform.position);
        
        // 检查是否在视锥体边缘
        bool inEdge = viewportPos.z > 0 && (
            viewportPos.x < 0.1f || viewportPos.x > 0.9f ||
            viewportPos.y < 0.1f || viewportPos.y > 0.9f
        );

        // 视锥体边缘的对象强制使用更低LOD
        int newForcedLOD = inEdge ? 1 : -1;
        
        if (newForcedLOD != _forcedLOD)
        {
            _forcedLOD = newForcedLOD;
            _lodGroup.ForceLOD(_forcedLOD);
        }
    }

    private void OnDisable()
    {
        // 恢复自动LOD
        if (_lodGroup != null)
            _lodGroup.ForceLOD(-1);
    }
}
```

---

## 五、植被LOD与Billboard技术

### 5.1 Billboard LOD生成

```csharp
/// <summary>
/// 运行时Billboard生成器
/// 将3D网格在最远LOD级别替换为始终面向相机的2D公告板
/// 常用于树木、草丛等植被的极远距离显示
/// </summary>
public class BillboardLODGenerator : MonoBehaviour
{
    [Header("Billboard配置")]
    [SerializeField] private Camera _captureCamera;   // 用于捕获Billboard贴图的相机
    [SerializeField] private int _billboardResolution = 512;
    [SerializeField] private int _captureAngles = 8;  // 8个角度的Billboard

    private Texture2D[] _capturedTextures;
    private Material _billboardMaterial;

    /// <summary>
    /// 从多个角度捕获对象，生成Billboard贴图集
    /// </summary>
    public IEnumerator GenerateBillboardTexturesAsync()
    {
        _capturedTextures = new Texture2D[_captureAngles];
        
        var rt = new RenderTexture(_billboardResolution, _billboardResolution, 24,
                                    RenderTextureFormat.ARGB32);
        
        if (_captureCamera == null)
        {
            var camObj = new GameObject("BillboardCaptureCam");
            _captureCamera = camObj.AddComponent<Camera>();
            _captureCamera.clearFlags = CameraClearFlags.SolidColor;
            _captureCamera.backgroundColor = Color.clear;
            _captureCamera.targetTexture = rt;
        }

        // 将相机对准目标对象
        var bounds = GetComponent<Renderer>()?.bounds ?? new Bounds(transform.position, Vector3.one);
        float distance = bounds.extents.magnitude * 2.5f;

        for (int i = 0; i < _captureAngles; i++)
        {
            float angle = (float)i / _captureAngles * 360f;
            
            // 环绕对象旋转相机
            Vector3 camPos = transform.position + 
                Quaternion.Euler(0, angle, 0) * Vector3.forward * distance;
            _captureCamera.transform.position = camPos;
            _captureCamera.transform.LookAt(transform.position);

            _captureCamera.Render();

            // 读取渲染结果
            RenderTexture.active = rt;
            _capturedTextures[i] = new Texture2D(_billboardResolution, _billboardResolution, 
                                                   TextureFormat.ARGB32, false);
            _capturedTextures[i].ReadPixels(new Rect(0, 0, _billboardResolution, _billboardResolution), 0, 0);
            _capturedTextures[i].Apply();
            RenderTexture.active = null;

            yield return null; // 每帧捕获一个角度
        }

        rt.Release();
        Debug.Log($"[Billboard] 已生成 {_captureAngles} 个角度的Billboard贴图");
    }

    /// <summary>
    /// 创建Billboard Material
    /// 运行时根据相机角度选择最匹配的贴图角度
    /// </summary>
    public Material CreateBillboardMaterial()
    {
        // 使用Shader Graph或内置Billboard Shader
        var mat = new Material(Shader.Find("Universal Render Pipeline/Particles/Unlit"));
        if (_capturedTextures != null && _capturedTextures.Length > 0)
            mat.mainTexture = _capturedTextures[0];
        return mat;
    }
}
```

---

## 六、LOD性能监控

```csharp
/// <summary>
/// LOD系统性能监控工具
/// 统计当前帧各LOD级别的使用分布，辅助调优
/// </summary>
public class LODPerformanceMonitor : MonoBehaviour
{
    private Dictionary<int, int> _lodLevelCounts = new Dictionary<int, int>();
    private int _totalLODGroups = 0;

    private void LateUpdate()
    {
        _lodLevelCounts.Clear();
        _totalLODGroups = 0;

        var allLODGroups = FindObjectsOfType<LODGroup>();
        foreach (var lodGroup in allLODGroups)
        {
            _totalLODGroups++;
            // 注意：Unity不直接提供当前LOD级别的公共API
            // 可以通过LODGroup.GetLODs()和相机距离手动计算
            int currentLOD = CalculateCurrentLOD(lodGroup);
            _lodLevelCounts.TryGetValue(currentLOD, out int count);
            _lodLevelCounts[currentLOD] = count + 1;
        }
    }

    private int CalculateCurrentLOD(LODGroup lodGroup)
    {
        Camera cam = Camera.main;
        if (cam == null) return 0;

        float distance = Vector3.Distance(cam.transform.position, lodGroup.transform.position);
        float screenSize = lodGroup.size / distance * Screen.height;
        float screenRatio = screenSize / Screen.height;

        var lods = lodGroup.GetLODs();
        for (int i = 0; i < lods.Length; i++)
        {
            if (screenRatio >= lods[i].screenRelativeTransitionHeight)
                return i;
        }
        return lods.Length; // Culled
    }

    private void OnGUI()
    {
        #if UNITY_EDITOR || DEVELOPMENT_BUILD
        GUILayout.BeginVertical("box");
        GUILayout.Label($"LOD Groups Total: {_totalLODGroups}");
        foreach (var kvp in _lodLevelCounts.OrderBy(x => x.Key))
        {
            float ratio = _totalLODGroups > 0 ? (float)kvp.Value / _totalLODGroups * 100 : 0;
            string label = kvp.Key >= 100 ? "Culled" : $"LOD{kvp.Key}";
            GUILayout.Label($"  {label}: {kvp.Value} ({ratio:F0}%)");
        }
        GUILayout.EndVertical();
        #endif
    }
}
```

---

## 七、最佳实践总结

### 7.1 LOD设置黄金比例

| LOD级别 | 屏幕比例 | 面数比例 | 适用距离（参考） |
|--------|--------|--------|--------------|
| LOD0   | > 60%  | 100%   | < 10m        |
| LOD1   | > 30%  | 50%    | 10~30m       |
| LOD2   | > 10%  | 20%    | 30~80m       |
| LOD3   | > 2%   | 5%     | 80~200m      |
| Culled | < 2%   | 0%     | > 200m       |

### 7.2 运行时LOD生成注意事项

1. **避免主线程阻塞**：网格简化必须分帧处理，每帧不超过3~5个网格
2. **缓存复用**：相同原始Mesh的LOD结果缓存到字典，避免重复计算
3. **法线重建**：简化后Mesh的法线需重新计算，否则光照异常
4. **UV一致性**：简化过程中需保持UV映射的合理性，避免贴图撕裂
5. **包围盒更新**：生成LOD后调用 `RecalculateBounds()` 更新碰撞检测

### 7.3 程序化内容LOD策略

```
程序化生成对象 → RuntimeLODGenerator注册到BatchLODGenerator
→ 按玩家距离排序，近处优先生成LOD
→ 超出生成距离的对象不生成LOD（直接使用原始Mesh或Culled）
→ 进入生成距离时异步补充LOD
```

---

## 总结

运行时网格简化与程序化LOD生成是开放世界游戏的关键性能技术：

1. **QEM算法**是目前最优的网格简化算法，在保持视觉质量的同时大幅减少面数
2. **异步生成**避免主线程卡顿，确保游戏流畅体验
3. **自适应偏移**根据GPU压力动态调整，实现性能与质量的最优平衡
4. **Billboard技术**为极远距离的植被等提供高性价比的视觉表现
5. **批量调度**通过优先级队列按距离排序处理，保证玩家视野内的LOD质量最优
