---
title: 游戏程序化Mesh生成与运行时网格技术完全指南
published: 2026-04-01
description: 深入讲解Unity中程序化网格生成技术，涵盖Mesh API基础、程序化地形、动态道路网格、破碎特效、剑轨拖尾、LOD网格生成等核心场景，提供完整C#代码实现与性能优化策略。
tags: [Unity, Mesh, 程序化生成, 图形学, 性能优化, C#, 游戏开发]
category: 渲染技术
draft: false
---

# 游戏程序化Mesh生成与运行时网格技术完全指南

## 一、Unity Mesh API 基础

### 1.1 Mesh 数据结构

Unity 的 Mesh 由以下核心数据组成：

| 数据 | 类型 | 说明 |
|------|------|------|
| vertices | Vector3[] | 顶点坐标（局部空间） |
| normals | Vector3[] | 法线向量 |
| tangents | Vector4[] | 切线（用于法线贴图，w 分量为正负手性） |
| uv | Vector2[] | 第一套 UV 坐标 |
| uv2~uv8 | Vector2[] | 额外 UV 通道 |
| colors | Color32[] | 顶点颜色 |
| triangles | int[] | 三角形索引（每3个一组） |
| boneWeights | BoneWeight[] | 骨骼权重（蒙皮网格） |

### 1.2 高性能 Mesh 写入——Mesh Data API

Unity 2020.1 引入了 `Mesh.AllocateWritableMeshData` 接口，配合 Job System 实现零 GC 的并行 Mesh 生成：

```csharp
// ProceduralMeshUtility.cs - 高性能 Mesh 生成工具类
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;
using UnityEngine;
using UnityEngine.Rendering;

public static class ProceduralMeshUtility
{
    /// <summary>
    /// 使用 Mesh.MeshData API 高效创建平面网格
    /// </summary>
    public static Mesh CreatePlane(int resX, int resZ, float sizeX, float sizeZ)
    {
        int vertCount = (resX + 1) * (resZ + 1);
        int triCount  = resX * resZ * 2;
        
        var meshDataArray = Mesh.AllocateWritableMeshData(1);
        var meshData = meshDataArray[0];
        
        // 声明顶点属性布局
        var vertexAttributes = new NativeArray<VertexAttributeDescriptor>(4, Allocator.Temp)
        {
            [0] = new VertexAttributeDescriptor(VertexAttribute.Position, VertexAttributeFormat.Float32, 3),
            [1] = new VertexAttributeDescriptor(VertexAttribute.Normal,   VertexAttributeFormat.Float32, 3),
            [2] = new VertexAttributeDescriptor(VertexAttribute.Tangent,  VertexAttributeFormat.Float32, 4),
            [3] = new VertexAttributeDescriptor(VertexAttribute.TexCoord0, VertexAttributeFormat.Float32, 2),
        };
        
        meshData.SetVertexBufferParams(vertCount, vertexAttributes);
        meshData.SetIndexBufferParams(triCount * 3, IndexFormat.UInt32);
        vertexAttributes.Dispose();
        
        // 调度 Job 并行填充顶点数据
        var job = new FillPlaneJob
        {
            ResX = resX, ResZ = resZ,
            SizeX = sizeX, SizeZ = sizeZ,
            Vertices = meshData.GetVertexData<PlaneVertex>(),
            Indices  = meshData.GetIndexData<uint>(),
        };
        var handle = job.Schedule(vertCount, 64);
        handle.Complete();
        
        // 提交 Mesh
        meshData.subMeshCount = 1;
        meshData.SetSubMesh(0, new SubMeshDescriptor(0, triCount * 3, MeshTopology.Triangles));
        
        var mesh = new Mesh { name = "ProceduralPlane" };
        Mesh.ApplyAndDisposeWritableMeshData(meshDataArray, mesh);
        mesh.RecalculateBounds();
        return mesh;
    }
    
    // 顶点结构（匹配 VertexAttributeDescriptor 声明）
    struct PlaneVertex
    {
        public float3 position;
        public float3 normal;
        public float4 tangent;
        public float2 uv;
    }
    
    [Unity.Burst.BurstCompile]
    struct FillPlaneJob : IJobParallelFor
    {
        public int ResX, ResZ;
        public float SizeX, SizeZ;
        public NativeArray<PlaneVertex> Vertices;
        public NativeArray<uint> Indices;
        
        public void Execute(int index)
        {
            int z = index / (ResX + 1);
            int x = index % (ResX + 1);
            
            float u = (float)x / ResX;
            float v = (float)z / ResZ;
            
            Vertices[index] = new PlaneVertex
            {
                position = new float3(u * SizeX - SizeX * 0.5f, 0, v * SizeZ - SizeZ * 0.5f),
                normal   = new float3(0, 1, 0),
                tangent  = new float4(1, 0, 0, -1),
                uv       = new float2(u, v)
            };
            
            // 填充三角形索引（仅在非边界顶点处填写）
            if (x < ResX && z < ResZ)
            {
                int quadIndex = (z * ResX + x) * 6;
                uint tl = (uint)(z * (ResX + 1) + x);
                uint tr = tl + 1;
                uint bl = (uint)((z + 1) * (ResX + 1) + x);
                uint br = bl + 1;
                
                Indices[quadIndex + 0] = tl; Indices[quadIndex + 1] = bl; Indices[quadIndex + 2] = tr;
                Indices[quadIndex + 3] = tr; Indices[quadIndex + 4] = bl; Indices[quadIndex + 5] = br;
            }
        }
    }
}
```

---

## 二、程序化道路网格生成

### 2.1 样条曲线沿路挤出

道路、河流、管道等线性物体是程序化网格最常见的应用场景。核心思路：沿 Bezier/Catmull-Rom 曲线方向挤出矩形截面。

```csharp
// RoadMeshGenerator.cs
using System.Collections.Generic;
using UnityEngine;

[RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
public class RoadMeshGenerator : MonoBehaviour
{
    [Header("道路参数")]
    public float roadWidth  = 6f;
    public float roadHeight = 0.1f;
    public int   segmentsPerCurve = 20;
    
    [Header("路点（Catmull-Rom 控制点）")]
    public Transform[] waypoints;
    
    private Mesh _mesh;
    
    [ContextMenu("重新生成道路")]
    public void Generate()
    {
        if (waypoints == null || waypoints.Length < 2) return;
        
        _mesh = GetComponent<MeshFilter>().sharedMesh ?? new Mesh { name = "RoadMesh" };
        _mesh.Clear();
        
        var points = SampleCurve(waypoints, segmentsPerCurve);
        BuildRoadMesh(points);
        
        GetComponent<MeshFilter>().sharedMesh = _mesh;
    }
    
    // Catmull-Rom 曲线采样
    private List<Vector3> SampleCurve(Transform[] cps, int stepsPerSegment)
    {
        var result = new List<Vector3>();
        for (int i = 0; i < cps.Length - 1; i++)
        {
            var p0 = cps[Mathf.Max(i - 1, 0)].position;
            var p1 = cps[i].position;
            var p2 = cps[i + 1].position;
            var p3 = cps[Mathf.Min(i + 2, cps.Length - 1)].position;
            
            for (int s = 0; s < stepsPerSegment; s++)
            {
                float t = (float)s / stepsPerSegment;
                result.Add(CatmullRom(p0, p1, p2, p3, t));
            }
        }
        result.Add(cps[cps.Length - 1].position);
        return result;
    }
    
    private Vector3 CatmullRom(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
    {
        float t2 = t * t, t3 = t2 * t;
        return 0.5f * (
            2f * p1 +
            (-p0 + p2) * t +
            (2f * p0 - 5f * p1 + 4f * p2 - p3) * t2 +
            (-p0 + 3f * p1 - 3f * p2 + p3) * t3
        );
    }
    
    private void BuildRoadMesh(List<Vector3> centerPoints)
    {
        int n = centerPoints.Count;
        var vertices = new Vector3[n * 2];
        var uvs      = new Vector2[n * 2];
        var normals  = new Vector3[n * 2];
        var tris     = new int[(n - 1) * 6];
        
        float uvOffset = 0f;
        
        for (int i = 0; i < n; i++)
        {
            // 计算前进方向
            Vector3 forward = i < n - 1 
                ? (centerPoints[i + 1] - centerPoints[i]).normalized
                : (centerPoints[i] - centerPoints[i - 1]).normalized;
            
            // 右侧方向（道路水平宽度）
            Vector3 right = Vector3.Cross(Vector3.up, forward).normalized;
            
            vertices[i * 2 + 0] = centerPoints[i] - right * (roadWidth * 0.5f);
            vertices[i * 2 + 1] = centerPoints[i] + right * (roadWidth * 0.5f);
            
            normals[i * 2 + 0] = Vector3.up;
            normals[i * 2 + 1] = Vector3.up;
            
            // UV - u 沿道路方向拉伸
            if (i > 0)
                uvOffset += Vector3.Distance(centerPoints[i], centerPoints[i - 1]);
            
            float uv = uvOffset / roadWidth; // 保持道路纹理比例
            uvs[i * 2 + 0] = new Vector2(0f, uv);
            uvs[i * 2 + 1] = new Vector2(1f, uv);
            
            // 三角形
            if (i < n - 1)
            {
                int ti = i * 6;
                int vi = i * 2;
                tris[ti + 0] = vi + 0; tris[ti + 1] = vi + 2; tris[ti + 2] = vi + 1;
                tris[ti + 3] = vi + 1; tris[ti + 4] = vi + 2; tris[ti + 5] = vi + 3;
            }
        }
        
        _mesh.vertices  = vertices;
        _mesh.normals   = normals;
        _mesh.uv        = uvs;
        _mesh.triangles = tris;
        _mesh.RecalculateTangents();
        _mesh.RecalculateBounds();
    }
}
```

---

## 三、剑轨拖尾网格（Trail Mesh）

剑气拖尾是 ARPG 游戏中的经典效果，与 TrailRenderer 不同，自定义拖尾网格可以精准控制每帧的顶点数据，实现宽端到窄端、渐变UV等效果。

```csharp
// SwordTrailMesh.cs - 高质量剑轨网格
public class SwordTrailMesh : MonoBehaviour
{
    [Header("拖尾设置")]
    public Transform tipPoint;     // 剑尖
    public Transform basePoint;    // 剑根
    public int maxSegments  = 30;  // 最大段数
    public float lifetime   = 0.3f; // 拖尾存活时间
    public AnimationCurve widthCurve = AnimationCurve.EaseInOut(0, 1, 1, 0);
    public Gradient colorGradient;
    
    private struct TrailPoint
    {
        public Vector3 tipPos;
        public Vector3 basePos;
        public float   timestamp;
    }
    
    private readonly Queue<TrailPoint> _points = new Queue<TrailPoint>();
    private Mesh     _mesh;
    private Vector3[] _vertices;
    private Vector2[] _uvs;
    private Color[]   _colors;
    private int[]     _triangles;
    
    private void Awake()
    {
        _mesh = new Mesh { name = "SwordTrail" };
        _mesh.MarkDynamic(); // 告诉 GPU 此 Mesh 会频繁更新，优化上传策略
        GetComponent<MeshFilter>().mesh = _mesh;
        
        int maxVerts = (maxSegments + 1) * 2;
        _vertices  = new Vector3[maxVerts];
        _uvs       = new Vector2[maxVerts];
        _colors    = new Color[maxVerts];
        _triangles = new int[maxSegments * 6];
    }
    
    private void LateUpdate()
    {
        // 记录当前帧位置
        _points.Enqueue(new TrailPoint
        {
            tipPos    = tipPoint.position,
            basePos   = basePoint.position,
            timestamp = Time.time
        });
        
        // 移除超时点
        while (_points.Count > 0 && Time.time - _points.Peek().timestamp > lifetime)
            _points.Dequeue();
        
        // 限制最大段数
        while (_points.Count > maxSegments + 1)
            _points.Dequeue();
        
        RebuildMesh();
    }
    
    private void RebuildMesh()
    {
        var pointArray = _points.ToArray();
        int segCount = pointArray.Length - 1;
        
        if (segCount <= 0)
        {
            _mesh.Clear();
            return;
        }
        
        // 转换到局部空间
        var worldToLocal = transform.worldToLocalMatrix;
        
        for (int i = 0; i < pointArray.Length; i++)
        {
            float t = (float)i / segCount; // 0=最新，1=最旧
            float age = (Time.time - pointArray[i].timestamp) / lifetime;
            
            _vertices[i * 2 + 0] = worldToLocal.MultiplyPoint3x4(pointArray[i].tipPos);
            _vertices[i * 2 + 1] = worldToLocal.MultiplyPoint3x4(pointArray[i].basePos);
            
            // UV：u 沿时间方向，v 区分剑尖/剑根
            _uvs[i * 2 + 0] = new Vector2(1f - t, 0f);
            _uvs[i * 2 + 1] = new Vector2(1f - t, 1f);
            
            // 顶点色控制透明度
            Color c = colorGradient.Evaluate(age);
            _colors[i * 2 + 0] = c;
            _colors[i * 2 + 1] = c;
        }
        
        // 填充三角形
        int triIdx = 0;
        for (int i = 0; i < segCount; i++)
        {
            int v = i * 2;
            _triangles[triIdx++] = v + 0; _triangles[triIdx++] = v + 1; _triangles[triIdx++] = v + 2;
            _triangles[triIdx++] = v + 2; _triangles[triIdx++] = v + 1; _triangles[triIdx++] = v + 3;
        }
        
        int usedVerts = (segCount + 1) * 2;
        int usedTris  = segCount * 6;
        
        // 使用 SetVertexBufferData 避免频繁 GC
        _mesh.SetVertices(_vertices, 0, usedVerts);
        _mesh.SetColors(_colors,   0, usedVerts);
        _mesh.SetUVs(0, _uvs,      0, usedVerts);
        _mesh.SetTriangles(_triangles, 0, usedTris, 0);
        _mesh.RecalculateBounds();
    }
}
```

---

## 四、实时破碎网格（Fracture Mesh）

### 4.1 Voronoi 破碎算法

```csharp
// VoronoiFracture.cs - 基于 Voronoi 的网格破碎
using System.Collections.Generic;
using UnityEngine;

public static class VoronoiFracture
{
    /// <summary>
    /// 将原始 Mesh 按 Voronoi 分区切割为多个碎片
    /// </summary>
    public static List<Mesh> Fracture(Mesh sourceMesh, int pieceCount, int seed = 42)
    {
        Random.InitState(seed);
        var bounds = sourceMesh.bounds;
        
        // 随机生成 Voronoi 种子点
        var seeds = new Vector3[pieceCount];
        for (int i = 0; i < pieceCount; i++)
        {
            seeds[i] = new Vector3(
                Random.Range(bounds.min.x, bounds.max.x),
                Random.Range(bounds.min.y, bounds.max.y),
                Random.Range(bounds.min.z, bounds.max.z)
            );
        }
        
        var sourceVerts = sourceMesh.vertices;
        var sourceTris  = sourceMesh.triangles;
        var sourceUVs   = sourceMesh.uv;
        
        // 为每个种子点创建碎片的顶点/三角形列表
        var pieceVerts = new List<Vector3>[pieceCount];
        var pieceTris  = new List<int>[pieceCount];
        var pieceUVs   = new List<Vector2>[pieceCount];
        for (int i = 0; i < pieceCount; i++)
        {
            pieceVerts[i] = new List<Vector3>();
            pieceTris[i]  = new List<int>();
            pieceUVs[i]   = new List<Vector2>();
        }
        
        // 遍历所有三角形，根据重心点归属到最近的种子
        for (int t = 0; t < sourceTris.Length; t += 3)
        {
            int i0 = sourceTris[t], i1 = sourceTris[t+1], i2 = sourceTris[t+2];
            Vector3 centroid = (sourceVerts[i0] + sourceVerts[i1] + sourceVerts[i2]) / 3f;
            
            int nearest = FindNearestSeed(centroid, seeds);
            
            int baseIdx = pieceVerts[nearest].Count;
            pieceVerts[nearest].Add(sourceVerts[i0]);
            pieceVerts[nearest].Add(sourceVerts[i1]);
            pieceVerts[nearest].Add(sourceVerts[i2]);
            if (sourceUVs.Length > 0)
            {
                pieceUVs[nearest].Add(sourceUVs[i0]);
                pieceUVs[nearest].Add(sourceUVs[i1]);
                pieceUVs[nearest].Add(sourceUVs[i2]);
            }
            pieceTris[nearest].Add(baseIdx + 0);
            pieceTris[nearest].Add(baseIdx + 1);
            pieceTris[nearest].Add(baseIdx + 2);
        }
        
        // 生成碎片 Mesh
        var result = new List<Mesh>();
        for (int i = 0; i < pieceCount; i++)
        {
            if (pieceVerts[i].Count == 0) continue;
            
            var m = new Mesh();
            m.name = $"Fragment_{i}";
            m.vertices  = pieceVerts[i].ToArray();
            m.triangles = pieceTris[i].ToArray();
            if (pieceUVs[i].Count > 0)
                m.uv = pieceUVs[i].ToArray();
            m.RecalculateNormals();
            m.RecalculateBounds();
            result.Add(m);
        }
        
        return result;
    }
    
    private static int FindNearestSeed(Vector3 point, Vector3[] seeds)
    {
        int nearest = 0;
        float minDist = float.MaxValue;
        for (int i = 0; i < seeds.Length; i++)
        {
            float d = (point - seeds[i]).sqrMagnitude;
            if (d < minDist) { minDist = d; nearest = i; }
        }
        return nearest;
    }
}

// FractureOnHit.cs - 受击时触发破碎
public class FractureOnHit : MonoBehaviour
{
    [Header("破碎参数")]
    public int pieceCount = 12;
    public float explodeForce = 300f;
    public float explodeRadius = 2f;
    public float pieceLifetime = 3f;
    [Header("碎片材质")]
    public Material insideMaterial;  // 内部截面材质
    
    private bool _fractured = false;
    
    public void TriggerFracture(Vector3 hitPoint, Vector3 hitForce)
    {
        if (_fractured) return;
        _fractured = true;
        
        var sourceMesh = GetComponent<MeshFilter>().sharedMesh;
        var pieces = VoronoiFracture.Fracture(sourceMesh, pieceCount, 
            seed: (int)(hitPoint.x * 1000));
        
        foreach (var pieceMesh in pieces)
        {
            var pieceGO = new GameObject($"Fragment");
            pieceGO.transform.position = transform.position;
            pieceGO.transform.rotation = transform.rotation;
            pieceGO.transform.localScale = transform.lossyScale;
            
            pieceGO.AddComponent<MeshFilter>().mesh = pieceMesh;
            pieceGO.AddComponent<MeshRenderer>().sharedMaterial = 
                GetComponent<MeshRenderer>().sharedMaterial;
            
            var rb = pieceGO.AddComponent<Rigidbody>();
            rb.AddExplosionForce(explodeForce, hitPoint, explodeRadius);
            // 添加随机旋转
            rb.angularVelocity = Random.insideUnitSphere * 5f;
            
            var col = pieceGO.AddComponent<MeshCollider>();
            col.sharedMesh = pieceMesh;
            col.convex = true;
            
            Destroy(pieceGO, pieceLifetime);
        }
        
        gameObject.SetActive(false);
    }
}
```

---

## 五、动态 LOD 网格生成

### 5.1 渐进式网格简化（QEM 算法简化版）

```csharp
// SimpleMeshLOD.cs - 基于边折叠的简单 LOD 生成
public static class SimpleMeshLOD
{
    /// <summary>
    /// 按比例简化 Mesh（比例 0~1，1 为不简化）
    /// </summary>
    public static Mesh Simplify(Mesh source, float ratio)
    {
        ratio = Mathf.Clamp01(ratio);
        if (ratio >= 1f) return source;
        
        int targetTriCount = Mathf.Max(1, Mathf.RoundToInt(source.triangles.Length / 3 * ratio));
        
        var vertices = new List<Vector3>(source.vertices);
        var tris     = new List<int>(source.triangles);
        var uvs      = new List<Vector2>(source.uv.Length > 0 ? source.uv : new Vector2[source.vertexCount]);
        
        // 构建顶点-三角形邻接表
        var vertexNeighbors = BuildNeighborMap(vertices.Count, tris);
        
        while (tris.Count / 3 > targetTriCount)
        {
            // 找到一条可折叠的边（选择最短边）
            float minLen = float.MaxValue;
            int minV1 = -1, minV2 = -1;
            
            for (int i = 0; i < tris.Count; i += 3)
            {
                for (int e = 0; e < 3; e++)
                {
                    int va = tris[i + e];
                    int vb = tris[i + (e + 1) % 3];
                    float len = (vertices[va] - vertices[vb]).sqrMagnitude;
                    if (len < minLen)
                    {
                        minLen = len;
                        minV1 = va; minV2 = vb;
                    }
                }
            }
            
            if (minV1 < 0) break;
            
            // 边折叠：将 v2 合并到 v1 的中点
            Vector3 midpoint = (vertices[minV1] + vertices[minV2]) * 0.5f;
            Vector2 midUV = (uvs[minV1] + uvs[minV2]) * 0.5f;
            vertices[minV1] = midpoint;
            uvs[minV1] = midUV;
            
            // 将 v2 的所有引用替换为 v1
            for (int i = 0; i < tris.Count; i++)
            {
                if (tris[i] == minV2) tris[i] = minV1;
            }
            
            // 移除退化三角形（有两个相同顶点的三角形）
            for (int i = tris.Count - 3; i >= 0; i -= 3)
            {
                if (tris[i] == tris[i+1] || tris[i+1] == tris[i+2] || tris[i] == tris[i+2])
                {
                    tris.RemoveRange(i, 3);
                }
            }
        }
        
        // 重新索引（移除未使用顶点）
        var (newVerts, newTris, newUVs) = ReindexMesh(vertices, tris, uvs);
        
        var lod = new Mesh { name = source.name + $"_LOD{(int)(ratio * 100)}" };
        lod.SetVertices(newVerts);
        lod.SetTriangles(newTris, 0);
        if (newUVs.Count > 0) lod.SetUVs(0, newUVs);
        lod.RecalculateNormals();
        lod.RecalculateBounds();
        return lod;
    }
    
    private static Dictionary<int, HashSet<int>> BuildNeighborMap(int vertCount, List<int> tris)
    {
        var map = new Dictionary<int, HashSet<int>>();
        for (int i = 0; i < vertCount; i++) map[i] = new HashSet<int>();
        for (int i = 0; i < tris.Count; i += 3)
        {
            map[tris[i]].Add(tris[i+1]); map[tris[i]].Add(tris[i+2]);
            map[tris[i+1]].Add(tris[i]);  map[tris[i+1]].Add(tris[i+2]);
            map[tris[i+2]].Add(tris[i]);  map[tris[i+2]].Add(tris[i+1]);
        }
        return map;
    }
    
    private static (List<Vector3>, List<int>, List<Vector2>) ReindexMesh(
        List<Vector3> verts, List<int> tris, List<Vector2> uvs)
    {
        var usedSet = new HashSet<int>(tris);
        var oldToNew = new Dictionary<int, int>();
        var newVerts = new List<Vector3>();
        var newUVs   = new List<Vector2>();
        
        foreach (int oldIdx in usedSet)
        {
            oldToNew[oldIdx] = newVerts.Count;
            newVerts.Add(verts[oldIdx]);
            if (uvs.Count > oldIdx) newUVs.Add(uvs[oldIdx]);
        }
        
        var newTris = new List<int>(tris.Count);
        foreach (int idx in tris) newTris.Add(oldToNew[idx]);
        
        return (newVerts, newTris, newUVs);
    }
}
```

---

## 六、运行时变形网格（Blend Shape 替代方案）

```csharp
// RuntimeMeshDeformer.cs - 基于 ComputeShader 的 GPU 顶点变形
public class RuntimeMeshDeformer : MonoBehaviour
{
    public ComputeShader deformCS;
    public float deformRadius = 0.5f;
    public float maxDeformation = 0.2f;
    
    private Mesh _mesh;
    private ComputeBuffer _vertexBuffer;
    private ComputeBuffer _originalBuffer;
    private int _kernelIndex;
    
    private static readonly int VertexBufferProp  = Shader.PropertyToID("_VertexBuffer");
    private static readonly int OriginalBufferProp = Shader.PropertyToID("_OriginalBuffer");
    private static readonly int HitPointProp      = Shader.PropertyToID("_HitPoint");
    private static readonly int HitNormalProp     = Shader.PropertyToID("_HitNormal");
    private static readonly int RadiusProp        = Shader.PropertyToID("_Radius");
    private static readonly int MaxDepthProp      = Shader.PropertyToID("_MaxDepth");
    
    private void Awake()
    {
        _mesh = GetComponent<MeshFilter>().mesh;
        _mesh.MarkDynamic();
        
        var vertices = _mesh.vertices;
        _vertexBuffer  = new ComputeBuffer(vertices.Length, sizeof(float) * 3);
        _originalBuffer = new ComputeBuffer(vertices.Length, sizeof(float) * 3);
        _vertexBuffer.SetData(vertices);
        _originalBuffer.SetData(vertices);
        
        _kernelIndex = deformCS.FindKernel("CSDeform");
    }
    
    public void ApplyDeformation(Vector3 worldHitPoint, Vector3 worldHitNormal)
    {
        Vector3 localHit    = transform.InverseTransformPoint(worldHitPoint);
        Vector3 localNormal = transform.InverseTransformDirection(worldHitNormal);
        
        deformCS.SetBuffer(_kernelIndex, VertexBufferProp, _vertexBuffer);
        deformCS.SetBuffer(_kernelIndex, OriginalBufferProp, _originalBuffer);
        deformCS.SetVector(HitPointProp, localHit);
        deformCS.SetVector(HitNormalProp, localNormal);
        deformCS.SetFloat(RadiusProp, deformRadius);
        deformCS.SetFloat(MaxDepthProp, maxDeformation);
        
        int groups = Mathf.CeilToInt(_mesh.vertexCount / 64f);
        deformCS.Dispatch(_kernelIndex, groups, 1, 1);
        
        // 回读 GPU 数据到 CPU（有开销，可改用 GraphicsBuffer 直接绑定）
        var newVerts = new Vector3[_mesh.vertexCount];
        _vertexBuffer.GetData(newVerts);
        _mesh.vertices = newVerts;
        _mesh.RecalculateNormals();
        _mesh.RecalculateBounds();
    }
    
    private void OnDestroy()
    {
        _vertexBuffer?.Release();
        _originalBuffer?.Release();
    }
}
```

```hlsl
// MeshDeform.compute
#pragma kernel CSDeform

RWStructuredBuffer<float3> _VertexBuffer;
StructuredBuffer<float3>   _OriginalBuffer;
float3 _HitPoint;
float3 _HitNormal;
float  _Radius;
float  _MaxDepth;

[numthreads(64, 1, 1)]
void CSDeform(uint3 id : SV_DispatchThreadID)
{
    if ((int)id.x >= (int)_VertexBuffer.Length) return;
    
    float3 original = _OriginalBuffer[id.x];
    float3 current  = _VertexBuffer[id.x];
    
    float dist = distance(original, _HitPoint);
    if (dist < _Radius)
    {
        float influence = 1.0 - (dist / _Radius);
        influence = influence * influence; // 二次衰减
        float3 deform = _HitNormal * (-_MaxDepth * influence);
        _VertexBuffer[id.x] = original + deform;
    }
}
```

---

## 七、最佳实践总结

### 7.1 性能关键点

| 技术点 | 优化建议 |
|--------|---------|
| 频繁更新 Mesh | 调用 `mesh.MarkDynamic()`，使用 `SetVertices` 替代直接赋值 `.vertices` |
| 顶点数量 | 移动端单 Mesh < 65535 顶点（使用 UInt16 Index，省显存省带宽） |
| 并行生成 | 使用 `Mesh.AllocateWritableMeshData` + Burst Job 实现零 GC 并行 |
| 碰撞体 | 动态 Mesh 配合 `MeshCollider.convex = true` 才能作刚体使用 |
| 数据回传 | GPU Compute Shader 修改顶点后，`GetData` 开销大；优先考虑 GraphicsBuffer 直接绑定 |

### 7.2 常见陷阱

```csharp
// ❌ 错误：直接赋值会触发 GC 分配
mesh.vertices = new Vector3[count]; 

// ✅ 正确：重用 NativeArray 或使用 SetVertices(array, start, length)
mesh.SetVertices(cachedVertexList, 0, vertexCount);

// ❌ 错误：每帧 RecalculateNormals() 开销高
mesh.RecalculateNormals();

// ✅ 正确：在 Shader 中计算法线，或使用预计算法线纹理
// 对于平面网格，直接赋值固定法线
System.Array.Fill(normals, Vector3.up);
mesh.normals = normals;

// ❌ 错误：实时破碎后忘记设置 convex
col.sharedMesh = fractureMesh; // MeshCollider 默认 non-convex

// ✅ 正确：破碎片设为 Convex 才能与刚体系统协作
col.convex = true; 
col.sharedMesh = fractureMesh;
```

### 7.3 工具推荐

- **Obi Softbody** / **Obi Rope**：基于 PBD 的软体/绳索，使用自定义 Mesh 实现
- **Fracture Magic** / **Destructible**：Asset Store 成熟破碎方案
- **Blender Python API**：离线预生成 LOD/变形 Mesh，运行时直接加载
- **Unity Splines Package**（2022.1+）：官方样条工具，可驱动道路/管道 Mesh 生成

## 总结

程序化 Mesh 技术是游戏开发的底层利器：

1. **Mesh Data API + Burst Job** 是性能上限最高的方案，适合大规模地形/植被生成
2. **剑轨/拖尾**：用轻量动态 Mesh 替代 TrailRenderer，可实现更多自定义效果
3. **破碎系统**：Voronoi 简化版可满足大多数需求；高精度需求参考 CDLOD/V-HACD
4. **LOD 生成**：离线预生成比运行时简化更稳定，QEM 算法是工业标准
5. **GPU 变形**：Compute Shader 驱动，配合 GraphicsBuffer 可实现全 GPU 管线
