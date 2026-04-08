---
title: 游戏运行时Mesh合并与动态图集系统完全指南
published: 2026-04-08
description: 深度解析Unity运行时Mesh合并技术、动态图集生成、UV坐标重映射、合并批次管理、DrawCall优化策略，以及大规模场景中的动态合批系统完整工程实践
tags: [Unity, 性能优化, Mesh合并, 动态图集, DrawCall优化]
category: 性能优化
draft: false
---

# 游戏运行时Mesh合并与动态图集系统完全指南

## 一、运行时Mesh合并的核心价值

在游戏开发中，DrawCall数量是影响CPU性能的关键因素。Unity提供了静态合批（Static Batching）和GPU Instancing等方案，但它们都有限制：静态合批只适合不移动的物体，GPU Instancing要求使用相同Mesh。**运行时Mesh合并**填补了中间地带——将多个动态生成或频繁出现的相似物体在运行时合并为一个Mesh，彻底消除DrawCall。

### 1.1 合并策略对比

| 方案 | 适用场景 | 限制 | DrawCall效果 |
|------|----------|------|-------------|
| 静态合批 | 场景固定物体 | 内存翻倍，不可移动 | 极佳 |
| GPU Instancing | 大量相同Mesh | 同一Mesh才能合并 | 优秀 |
| 动态合批 | 小Mesh(<900顶点) | 顶点数限制严格 | 一般 |
| **运行时Mesh合并** | 中等复杂度动态场景 | 合并后无法单独移动 | 极佳 |
| SRP Batching | 相同Shader | 需URP/HDRP | 良好 |

### 1.2 典型应用场景

- **地图/关卡拼接**：程序化关卡中大量重复瓦片
- **植被系统**：草地、灌木合并（非GPU Instancing场景）
- **UI 3D元素**：地图标记、血条等World Space UI
- **建筑内装**：桌椅、道具等静置摆设的运行时合并
- **特效Mesh**：多个飞溅、碎片的合并渲染

---

## 二、核心Mesh合并系统实现

### 2.1 高性能Mesh合并器

```csharp
using System.Collections.Generic;
using Unity.Collections;
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// 运行时高性能Mesh合并系统
/// 支持多材质、UV重映射、法线变换
/// </summary>
public class RuntimeMeshCombiner : MonoBehaviour
{
    [System.Serializable]
    public class CombineGroup
    {
        public string groupName;
        public Material sharedMaterial;
        public List<MeshFilter> meshFilters = new();
        public GameObject combinedObject;
        public Mesh combinedMesh;
    }
    
    [Header("合并配置")]
    [SerializeField] private bool _combineOnStart = false;
    [SerializeField] private bool _destroyOriginals = false;
    [SerializeField] private bool _recalculateBounds = true;
    [SerializeField] private bool _recalculateNormals = false;
    
    [Header("性能配置")]
    [SerializeField] private int _maxVerticesPerMesh = 65535; // Unity默认上限
    [SerializeField] private bool _use32BitIndex = false;     // 超过65535顶点时启用
    
    private readonly List<CombineGroup> _combineGroups = new();
    private readonly List<GameObject> _combinedObjects = new();
    
    void Start()
    {
        if (_combineOnStart)
            CombineAll();
    }
    
    /// <summary>
    /// 收集子物体并按材质分组合并
    /// </summary>
    [ContextMenu("合并所有子物体Mesh")]
    public void CombineAll()
    {
        var meshFilters = GetComponentsInChildren<MeshFilter>(false);
        CombineByMaterial(meshFilters);
    }
    
    /// <summary>
    /// 按材质自动分组并合并
    /// </summary>
    public void CombineByMaterial(MeshFilter[] meshFilters)
    {
        // 清理旧合并结果
        CleanupCombined();
        
        // 按材质分组
        var materialGroups = new Dictionary<Material, List<MeshFilter>>();
        
        foreach (var mf in meshFilters)
        {
            if (mf == null || mf.sharedMesh == null) continue;
            
            var renderer = mf.GetComponent<Renderer>();
            if (renderer == null || !renderer.enabled) continue;
            
            // 支持多材质Mesh（SubMesh）
            foreach (var mat in renderer.sharedMaterials)
            {
                if (mat == null) continue;
                if (!materialGroups.ContainsKey(mat))
                    materialGroups[mat] = new List<MeshFilter>();
                materialGroups[mat].Add(mf);
            }
        }
        
        // 对每个材质组执行合并
        foreach (var kvp in materialGroups)
        {
            CombineMeshesForMaterial(kvp.Key, kvp.Value);
        }
        
        // 可选：禁用原始MeshRenderer
        if (_destroyOriginals)
        {
            foreach (var mf in meshFilters)
            {
                var renderer = mf.GetComponent<Renderer>();
                if (renderer) renderer.enabled = false;
            }
        }
        
        Debug.Log($"Mesh合并完成：{materialGroups.Count}个材质组，" +
                  $"生成{_combinedObjects.Count}个合并对象");
    }
    
    private void CombineMeshesForMaterial(Material material, List<MeshFilter> filters)
    {
        if (filters.Count == 0) return;
        
        // 分批处理（超过顶点上限时分成多个合并对象）
        var batches = SplitIntoBatches(filters, _maxVerticesPerMesh);
        
        foreach (var batch in batches)
        {
            var combinedMesh = CombineBatch(batch, material);
            if (combinedMesh == null) continue;
            
            // 创建合并后的GameObject
            var go = new GameObject($"Combined_{material.name}");
            go.transform.SetParent(transform);
            go.transform.localPosition = Vector3.zero;
            go.transform.localRotation = Quaternion.identity;
            go.transform.localScale = Vector3.one;
            
            var mf = go.AddComponent<MeshFilter>();
            mf.sharedMesh = combinedMesh;
            
            var mr = go.AddComponent<MeshRenderer>();
            mr.sharedMaterial = material;
            mr.shadowCastingMode = ShadowCastingMode.Off; // 合批通常关闭阴影
            
            _combinedObjects.Add(go);
        }
    }
    
    private List<List<MeshFilter>> SplitIntoBatches(
        List<MeshFilter> filters, int maxVertices)
    {
        var batches = new List<List<MeshFilter>>();
        var currentBatch = new List<MeshFilter>();
        int currentVertexCount = 0;
        
        foreach (var mf in filters)
        {
            int meshVertices = mf.sharedMesh.vertexCount;
            
            if (currentVertexCount + meshVertices > maxVertices && currentBatch.Count > 0)
            {
                batches.Add(currentBatch);
                currentBatch = new List<MeshFilter>();
                currentVertexCount = 0;
            }
            
            currentBatch.Add(mf);
            currentVertexCount += meshVertices;
        }
        
        if (currentBatch.Count > 0)
            batches.Add(currentBatch);
        
        return batches;
    }
    
    private Mesh CombineBatch(List<MeshFilter> filters, Material material)
    {
        var combineInstances = new CombineInstance[filters.Count];
        bool hasSubMesh = false;
        
        for (int i = 0; i < filters.Count; i++)
        {
            var mf = filters[i];
            var renderer = mf.GetComponent<Renderer>();
            
            // 找到此材质对应的SubMesh索引
            int subMeshIndex = 0;
            if (renderer != null)
            {
                var materials = renderer.sharedMaterials;
                for (int j = 0; j < materials.Length; j++)
                {
                    if (materials[j] == material)
                    {
                        subMeshIndex = j;
                        break;
                    }
                }
                if (materials.Length > 1) hasSubMesh = true;
            }
            
            combineInstances[i] = new CombineInstance
            {
                mesh = mf.sharedMesh,
                subMeshIndex = subMeshIndex,
                // 将各物体的世界空间变换烘焙进顶点（相对于父节点）
                transform = transform.worldToLocalMatrix * mf.transform.localToWorldMatrix
            };
        }
        
        var combinedMesh = new Mesh();
        combinedMesh.name = $"CombinedMesh_{material.name}";
        
        if (_use32BitIndex || GetTotalVertices(filters) > 65535)
            combinedMesh.indexFormat = IndexFormat.UInt32;
        
        // mergeSubMeshes=true：所有SubMesh合并为一个，同一材质只需一个DrawCall
        combinedMesh.CombineMeshes(combineInstances, mergeSubMeshes: true, useMatrices: true);
        
        if (_recalculateBounds)
            combinedMesh.RecalculateBounds();
        
        if (_recalculateNormals)
            combinedMesh.RecalculateNormals();
        
        combinedMesh.Optimize(); // 优化顶点缓存访问顺序
        combinedMesh.UploadMeshData(markNoLongerReadable: true); // 释放CPU端内存
        
        return combinedMesh;
    }
    
    private int GetTotalVertices(List<MeshFilter> filters)
    {
        int total = 0;
        foreach (var mf in filters)
            if (mf.sharedMesh != null)
                total += mf.sharedMesh.vertexCount;
        return total;
    }
    
    public void CleanupCombined()
    {
        foreach (var go in _combinedObjects)
        {
            if (go != null)
            {
                var mf = go.GetComponent<MeshFilter>();
                if (mf?.sharedMesh != null)
                    DestroyImmediate(mf.sharedMesh);
                DestroyImmediate(go);
            }
        }
        _combinedObjects.Clear();
        _combineGroups.Clear();
    }
}
```

### 2.2 使用Job System加速合并计算

```csharp
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;
using UnityEngine;

/// <summary>
/// 使用Burst Job加速顶点变换计算
/// 将矩阵变换操作并行化，适合大量Mesh合并场景
/// </summary>
public class BurstMeshCombiner : MonoBehaviour
{
    [Unity.Burst.BurstCompile]
    private struct TransformVerticesJob : IJobParallelFor
    {
        [ReadOnly] public NativeArray<float3> InputVertices;
        [ReadOnly] public float4x4 TransformMatrix;
        
        [WriteOnly] public NativeArray<float3> OutputVertices;
        
        public void Execute(int index)
        {
            float4 v = new float4(InputVertices[index], 1.0f);
            float4 transformed = math.mul(TransformMatrix, v);
            OutputVertices[index] = transformed.xyz;
        }
    }
    
    [Unity.Burst.BurstCompile]
    private struct TransformNormalsJob : IJobParallelFor
    {
        [ReadOnly] public NativeArray<float3> InputNormals;
        [ReadOnly] public float3x3 NormalMatrix; // 逆转置矩阵
        
        [WriteOnly] public NativeArray<float3> OutputNormals;
        
        public void Execute(int index)
        {
            OutputNormals[index] = math.normalize(
                math.mul(NormalMatrix, InputNormals[index])
            );
        }
    }
    
    /// <summary>
    /// 使用Job System并行变换顶点（异步，不阻塞主线程）
    /// </summary>
    public System.Collections.IEnumerator CombineMeshesAsync(
        MeshFilter[] filters,
        System.Action<Mesh> onComplete)
    {
        // 统计总顶点数
        int totalVertices = 0;
        foreach (var mf in filters)
            if (mf?.sharedMesh != null)
                totalVertices += mf.sharedMesh.vertexCount;
        
        var allVertices = new NativeArray<float3>(totalVertices, Allocator.TempJob);
        var allNormals = new NativeArray<float3>(totalVertices, Allocator.TempJob);
        
        var jobHandles = new List<JobHandle>();
        int vertexOffset = 0;
        
        try
        {
            // 为每个MeshFilter创建变换Job
            foreach (var mf in filters)
            {
                if (mf?.sharedMesh == null) continue;
                
                var mesh = mf.sharedMesh;
                var vertices = mesh.vertices;
                var normals = mesh.normals;
                int count = vertices.Length;
                
                var inputVerts = new NativeArray<float3>(count, Allocator.TempJob);
                var outputVerts = new NativeArray<float3>(count, Allocator.TempJob);
                
                // 复制输入数据
                for (int i = 0; i < count; i++)
                    inputVerts[i] = vertices[i];
                
                var matrix = (float4x4)mf.transform.localToWorldMatrix;
                
                var vertJob = new TransformVerticesJob
                {
                    InputVertices = inputVerts,
                    TransformMatrix = matrix,
                    OutputVertices = outputVerts
                };
                
                var handle = vertJob.Schedule(count, 64);
                jobHandles.Add(handle);
                
                // 等待此批次完成并复制到合并数组
                yield return new WaitUntil(() => handle.IsCompleted);
                handle.Complete();
                
                NativeArray<float3>.Copy(outputVerts, 0, allVertices, vertexOffset, count);
                vertexOffset += count;
                
                inputVerts.Dispose();
                outputVerts.Dispose();
            }
            
            // 构建最终Mesh
            var combinedMesh = new Mesh();
            combinedMesh.indexFormat = totalVertices > 65535 
                ? UnityEngine.Rendering.IndexFormat.UInt32 
                : UnityEngine.Rendering.IndexFormat.UInt16;
            
            // 从NativeArray转回Vector3[]
            var finalVertices = new Vector3[totalVertices];
            for (int i = 0; i < totalVertices; i++)
                finalVertices[i] = allVertices[i];
            
            combinedMesh.vertices = finalVertices;
            
            onComplete?.Invoke(combinedMesh);
        }
        finally
        {
            if (allVertices.IsCreated) allVertices.Dispose();
            if (allNormals.IsCreated) allNormals.Dispose();
        }
    }
}
```

---

## 三、动态图集系统

### 3.1 运行时纹理图集生成器

```csharp
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 运行时动态图集生成器
/// 将多张小纹理打包到一张大纹理，通过UV重映射减少材质切换DrawCall
/// 使用矩形装箱算法（Guillotine Algorithm）
/// </summary>
public class RuntimeAtlasGenerator
{
    public struct AtlasEntry
    {
        public Texture2D SourceTexture;
        public Rect UVRect;         // 在图集中的UV坐标（0-1范围）
        public Vector2Int PixelPos; // 在图集中的像素位置
        public Vector2Int PixelSize;
    }
    
    private class FreeRect
    {
        public RectInt Rect;
        public FreeRect Left, Right; // 二叉树分割
    }
    
    private Texture2D _atlasTexture;
    private int _atlasSize;
    private int _padding;
    private readonly Dictionary<Texture2D, AtlasEntry> _entries = new();
    private FreeRect _root;
    
    public Texture2D AtlasTexture => _atlasTexture;
    public IReadOnlyDictionary<Texture2D, AtlasEntry> Entries => _entries;
    
    public RuntimeAtlasGenerator(int atlasSize = 2048, int padding = 2)
    {
        _atlasSize = atlasSize;
        _padding = padding;
        
        _atlasTexture = new Texture2D(atlasSize, atlasSize, TextureFormat.RGBA32, true);
        _atlasTexture.name = "RuntimeAtlas";
        
        // 初始化整个图集为空闲区域
        _root = new FreeRect { Rect = new RectInt(0, 0, atlasSize, atlasSize) };
    }
    
    /// <summary>
    /// 向图集添加纹理，返回UV矩形
    /// </summary>
    public bool TryAddTexture(Texture2D texture, out AtlasEntry entry)
    {
        entry = default;
        
        if (texture == null) return false;
        if (_entries.ContainsKey(texture))
        {
            entry = _entries[texture];
            return true;
        }
        
        int width = texture.width + _padding * 2;
        int height = texture.height + _padding * 2;
        
        // 查找合适的空闲矩形（Guillotine算法）
        var freeRect = FindFreeRect(_root, width, height);
        if (freeRect == null) return false;
        
        // 将纹理像素复制到图集
        int x = freeRect.Rect.x + _padding;
        int y = freeRect.Rect.y + _padding;
        
        CopyTextureToAtlas(texture, x, y);
        
        // 分割空闲区域
        SplitFreeRect(freeRect, width, height);
        
        // 计算UV坐标
        float invSize = 1f / _atlasSize;
        var uvRect = new Rect(
            x * invSize, 
            y * invSize, 
            texture.width * invSize, 
            texture.height * invSize
        );
        
        entry = new AtlasEntry
        {
            SourceTexture = texture,
            UVRect = uvRect,
            PixelPos = new Vector2Int(x, y),
            PixelSize = new Vector2Int(texture.width, texture.height)
        };
        
        _entries[texture] = entry;
        return true;
    }
    
    /// <summary>
    /// 批量添加纹理并应用到图集（调用Apply()）
    /// </summary>
    public Dictionary<Texture2D, AtlasEntry> BatchAdd(IEnumerable<Texture2D> textures)
    {
        var results = new Dictionary<Texture2D, AtlasEntry>();
        
        // 按大小降序排序（大纹理优先，提高装填率）
        var sortedTextures = new List<Texture2D>(textures);
        sortedTextures.Sort((a, b) => 
            (b.width * b.height).CompareTo(a.width * a.height));
        
        foreach (var texture in sortedTextures)
        {
            if (TryAddTexture(texture, out var entry))
                results[texture] = entry;
            else
                Debug.LogWarning($"图集空间不足，无法添加纹理: {texture.name}");
        }
        
        // 应用所有更改
        _atlasTexture.Apply(updateMipmaps: true);
        
        return results;
    }
    
    private void CopyTextureToAtlas(Texture2D src, int destX, int destY)
    {
        // 注意：源纹理必须是readable=true
        Color[] pixels = src.GetPixels();
        _atlasTexture.SetPixels(destX, destY, src.width, src.height, pixels);
    }
    
    private FreeRect FindFreeRect(FreeRect node, int w, int h)
    {
        if (node == null) return null;
        
        // 叶节点：检查是否能放入
        if (node.Left == null && node.Right == null)
        {
            if (node.Rect.width >= w && node.Rect.height >= h)
                return node;
            return null;
        }
        
        // 先尝试左子树，再尝试右子树
        var result = FindFreeRect(node.Left, w, h);
        if (result != null) return result;
        return FindFreeRect(node.Right, w, h);
    }
    
    private void SplitFreeRect(FreeRect node, int usedW, int usedH)
    {
        // Guillotine分割：将使用后的剩余空间分为两个矩形
        int remainW = node.Rect.width - usedW;
        int remainH = node.Rect.height - usedH;
        
        // 水平分割优先（当剩余宽度 > 剩余高度）
        if (remainW > remainH)
        {
            // 右侧矩形
            if (remainW > 0)
                node.Right = new FreeRect 
                { 
                    Rect = new RectInt(node.Rect.x + usedW, node.Rect.y, remainW, node.Rect.height) 
                };
            // 上方矩形
            if (remainH > 0)
                node.Left = new FreeRect 
                { 
                    Rect = new RectInt(node.Rect.x, node.Rect.y + usedH, usedW, remainH) 
                };
        }
        else
        {
            // 上方矩形
            if (remainH > 0)
                node.Left = new FreeRect 
                { 
                    Rect = new RectInt(node.Rect.x, node.Rect.y + usedH, node.Rect.width, remainH) 
                };
            // 右侧矩形
            if (remainW > 0)
                node.Right = new FreeRect 
                { 
                    Rect = new RectInt(node.Rect.x + usedW, node.Rect.y, remainW, usedH) 
                };
        }
        
        // 标记此节点已被使用（非叶节点）
        // 通过将Rect设为零大小来标记
        node.Rect = new RectInt(node.Rect.x, node.Rect.y, 0, 0);
    }
    
    public void Dispose()
    {
        if (_atlasTexture != null)
            Object.Destroy(_atlasTexture);
        _entries.Clear();
    }
}
```

### 3.2 UV重映射系统

```csharp
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// 将原始Mesh的UV坐标重映射到图集UV空间
/// 这是动态图集能减少DrawCall的关键步骤
/// </summary>
public class UVRemapper
{
    /// <summary>
    /// 将Mesh的UV坐标从[0,1]映射到图集中的uvRect范围
    /// </summary>
    public static Mesh RemapUVs(Mesh sourceMesh, Rect atlasUVRect, bool createCopy = true)
    {
        Mesh mesh = createCopy ? Object.Instantiate(sourceMesh) : sourceMesh;
        
        var originalUVs = mesh.uv;
        var remappedUVs = new Vector2[originalUVs.Length];
        
        for (int i = 0; i < originalUVs.Length; i++)
        {
            // 线性插值：将[0,1]范围映射到图集的UV矩形
            remappedUVs[i] = new Vector2(
                atlasUVRect.x + originalUVs[i].x * atlasUVRect.width,
                atlasUVRect.y + originalUVs[i].y * atlasUVRect.height
            );
        }
        
        mesh.uv = remappedUVs;
        return mesh;
    }
    
    /// <summary>
    /// 批量重映射并合并：核心优化流程
    /// </summary>
    public static Mesh RemapAndCombine(
        List<(MeshFilter filter, Rect atlasUVRect)> meshAtlasPairs,
        out int totalVertices)
    {
        totalVertices = 0;
        
        var combineInstances = new CombineInstance[meshAtlasPairs.Count];
        var remappedMeshes = new List<Mesh>();
        
        for (int i = 0; i < meshAtlasPairs.Count; i++)
        {
            var (filter, uvRect) = meshAtlasPairs[i];
            if (filter?.sharedMesh == null) continue;
            
            // 重映射UV到图集空间
            var remapped = RemapUVs(filter.sharedMesh, uvRect, createCopy: true);
            remappedMeshes.Add(remapped);
            
            combineInstances[i] = new CombineInstance
            {
                mesh = remapped,
                transform = filter.transform.localToWorldMatrix
            };
            
            totalVertices += filter.sharedMesh.vertexCount;
        }
        
        var combined = new Mesh();
        combined.name = "AtlasCombinedMesh";
        
        if (totalVertices > 65535)
            combined.indexFormat = UnityEngine.Rendering.IndexFormat.UInt32;
        
        combined.CombineMeshes(combineInstances, mergeSubMeshes: true, useMatrices: true);
        combined.Optimize();
        
        // 清理临时Mesh
        foreach (var m in remappedMeshes)
            Object.Destroy(m);
        
        return combined;
    }
}
```

### 3.3 完整的图集合并管线

```csharp
using System.Collections;
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 完整的运行时图集合并管线
/// 自动处理：收集纹理 → 生成图集 → UV重映射 → Mesh合并
/// </summary>
public class AtlasMeshPipeline : MonoBehaviour
{
    [Header("图集配置")]
    [SerializeField] private int _atlasSize = 2048;
    [SerializeField] private int _padding = 2;
    [SerializeField] private bool _makeTexturesReadable = true;
    
    [Header("调试")]
    [SerializeField] private bool _showAtlasTexture = false;
    [SerializeField] private Renderer _debugAtlasRenderer;
    
    private RuntimeAtlasGenerator _atlasGenerator;
    private GameObject _combinedObject;
    
    [ContextMenu("执行图集合并")]
    public void ExecutePipeline()
    {
        StartCoroutine(ExecutePipelineCoroutine());
    }
    
    private IEnumerator ExecutePipelineCoroutine()
    {
        Debug.Log("开始图集合并管线...");
        
        // Step 1: 收集所有MeshRenderer
        var renderers = GetComponentsInChildren<MeshRenderer>();
        var meshFilters = GetComponentsInChildren<MeshFilter>();
        
        Debug.Log($"发现 {renderers.Length} 个渲染器");
        
        // Step 2: 收集所有唯一纹理
        var textureToFilters = new Dictionary<Texture2D, List<MeshFilter>>();
        
        for (int i = 0; i < renderers.Length; i++)
        {
            var renderer = renderers[i];
            var mf = meshFilters[i];
            
            if (renderer.sharedMaterial?.mainTexture is Texture2D tex)
            {
                // 确保纹理可读
                if (_makeTexturesReadable && !tex.isReadable)
                {
                    Debug.LogWarning($"纹理 {tex.name} 不可读，跳过。请在导入设置中启用Read/Write。");
                    continue;
                }
                
                if (!textureToFilters.ContainsKey(tex))
                    textureToFilters[tex] = new List<MeshFilter>();
                textureToFilters[tex].Add(mf);
            }
        }
        
        yield return null; // 让出一帧
        
        // Step 3: 生成动态图集
        _atlasGenerator = new RuntimeAtlasGenerator(_atlasSize, _padding);
        var atlasEntries = _atlasGenerator.BatchAdd(textureToFilters.Keys);
        
        Debug.Log($"图集生成完成，包含 {atlasEntries.Count} 张纹理");
        
        if (_showAtlasTexture && _debugAtlasRenderer != null)
        {
            _debugAtlasRenderer.sharedMaterial.mainTexture = _atlasGenerator.AtlasTexture;
        }
        
        yield return null;
        
        // Step 4: 构建UV重映射对
        var meshAtlasPairs = new List<(MeshFilter, Rect)>();
        
        foreach (var kvp in textureToFilters)
        {
            if (!atlasEntries.TryGetValue(kvp.Key, out var entry)) continue;
            
            foreach (var mf in kvp.Value)
            {
                meshAtlasPairs.Add((mf, entry.UVRect));
            }
        }
        
        yield return null;
        
        // Step 5: UV重映射并合并Mesh
        var combinedMesh = UVRemapper.RemapAndCombine(
            meshAtlasPairs, out int totalVerts);
        
        Debug.Log($"Mesh合并完成，总顶点数: {totalVerts}");
        
        // Step 6: 创建合并对象
        if (_combinedObject != null)
            Destroy(_combinedObject);
        
        _combinedObject = new GameObject("AtlasCombined");
        _combinedObject.transform.SetParent(transform);
        _combinedObject.transform.localPosition = Vector3.zero;
        
        var mfCombined = _combinedObject.AddComponent<MeshFilter>();
        mfCombined.sharedMesh = combinedMesh;
        
        var mrCombined = _combinedObject.AddComponent<MeshRenderer>();
        // 使用图集纹理的材质
        var atlasMaterial = new Material(renderers[0].sharedMaterial);
        atlasMaterial.mainTexture = _atlasGenerator.AtlasTexture;
        mrCombined.sharedMaterial = atlasMaterial;
        
        // Step 7: 隐藏原始对象
        foreach (var renderer in renderers)
            renderer.enabled = false;
        
        Debug.Log($"图集合并管线完成！DrawCall从 {renderers.Length} 降至 1");
    }
    
    void OnDestroy()
    {
        _atlasGenerator?.Dispose();
    }
}
```

---

## 四、增量更新与脏标记系统

### 4.1 支持局部更新的动态合并管理器

```csharp
using System.Collections.Generic;
using UnityEngine;

/// <summary>
/// 支持增量更新的Mesh合并管理器
/// 使用脏标记机制，只在有物体变更时重新合并
/// 适合频繁增删物体的场景（如塔防建造、城市建设）
/// </summary>
public class IncrementalMeshCombiner : MonoBehaviour
{
    private readonly HashSet<MeshFilter> _registeredFilters = new();
    private readonly HashSet<MeshFilter> _dirtyFilters = new();
    private bool _fullRebuildNeeded = false;
    private float _rebuildDelay = 0.1f; // 延迟合并，合并多次修改
    private float _lastDirtyTime = float.MinValue;
    
    private GameObject _combinedObject;
    private Material _sharedMaterial;
    
    /// <summary>
    /// 注册一个MeshFilter到合并系统
    /// </summary>
    public void Register(MeshFilter filter, Material material)
    {
        if (_registeredFilters.Add(filter))
        {
            _sharedMaterial = material; // 简化：所有使用同一材质
            MarkDirty(filter);
        }
    }
    
    /// <summary>
    /// 注销（物体被删除时调用）
    /// </summary>
    public void Unregister(MeshFilter filter)
    {
        if (_registeredFilters.Remove(filter))
        {
            _dirtyFilters.Remove(filter);
            _fullRebuildNeeded = true;
            _lastDirtyTime = Time.time;
        }
    }
    
    /// <summary>
    /// 标记某个物体已修改（位置/Mesh变更）
    /// </summary>
    public void MarkDirty(MeshFilter filter)
    {
        _dirtyFilters.Add(filter);
        _lastDirtyTime = Time.time;
    }
    
    void Update()
    {
        // 防抖：距上次修改超过延迟时间才重建
        if (_dirtyFilters.Count == 0 && !_fullRebuildNeeded) return;
        if (Time.time - _lastDirtyTime < _rebuildDelay) return;
        
        RebuildCombined();
    }
    
    private void RebuildCombined()
    {
        var combineInstances = new CombineInstance[_registeredFilters.Count];
        int index = 0;
        
        foreach (var mf in _registeredFilters)
        {
            if (mf == null || mf.sharedMesh == null) continue;
            
            combineInstances[index++] = new CombineInstance
            {
                mesh = mf.sharedMesh,
                transform = transform.worldToLocalMatrix * mf.transform.localToWorldMatrix
            };
        }
        
        // 创建或更新合并对象
        if (_combinedObject == null)
        {
            _combinedObject = new GameObject("DynamicCombined");
            _combinedObject.transform.SetParent(transform);
            _combinedObject.AddComponent<MeshFilter>();
            var mr = _combinedObject.AddComponent<MeshRenderer>();
            mr.sharedMaterial = _sharedMaterial;
        }
        
        var mfCombined = _combinedObject.GetComponent<MeshFilter>();
        
        // 销毁旧Mesh
        if (mfCombined.sharedMesh != null)
            Destroy(mfCombined.sharedMesh);
        
        var newMesh = new Mesh();
        newMesh.CombineMeshes(combineInstances, true, true);
        newMesh.Optimize();
        mfCombined.sharedMesh = newMesh;
        
        _dirtyFilters.Clear();
        _fullRebuildNeeded = false;
        
        Debug.Log($"Mesh重建完成，包含 {index} 个子Mesh");
    }
}
```

---

## 五、最佳实践与注意事项

### 5.1 性能陷阱与规避

```markdown
## 常见问题与解决方案

### 问题1：合并后光照贴图UV丢失
原因：CombineMeshes不会处理Lightmap UV（uv2）
解决：合并前确认不依赖烘焙光照，或使用Light Probe替代

### 问题2：合并后碰撞检测失效
原因：MeshCollider需要单独处理
解决：
- 保留原始碰撞体（不合并碰撞体）
- 或合并后重新生成MeshCollider（仅简单碰撞）

### 问题3：纹理isReadable限制
原因：GetPixels()要求纹理标记为Readable
解决：
- 构建时通过TextureImporter设置Read/Write Enable
- 或使用RenderTexture + Blit的方式绕过（无需CPU可读）

### 问题4：内存翻倍
原因：原始Mesh + 合并后Mesh同时存在内存
解决：
- 合并后调用mesh.UploadMeshData(true)释放CPU端
- 原始MeshRenderer禁用后，原始Mesh可由GC回收

### 问题5：蒙皮动画物体无法合并
原因：SkinnedMeshRenderer的Mesh是动态的
解决：
- 使用BakeMesh()烘焙某一帧姿势后再合并（静态展示用）
- 动态动画物体不适合Mesh合并，使用GPU Instancing代替
```

### 5.2 适用性决策树

```
需要减少DrawCall?
├── 物体完全静止 → 使用Static Batching
├── 完全相同的Mesh → 使用GPU Instancing  
├── 相同Shader不同材质属性 → 使用SRP Batcher
├── 小Mesh(<300顶点) → Unity Dynamic Batching
└── 其他（中等规模，可合并）
    ├── 位置固定（建筑、地形块）→ 运行时Mesh合并（本方案）
    ├── 纹理不同 → 运行时图集合并管线（本方案）
    └── 频繁增删 → IncrementalMeshCombiner（本方案）
```

---

## 总结

运行时Mesh合并与动态图集是两种强力的DrawCall优化手段，二者结合可以实现：多材质物体 → 合并为单一图集材质 → 所有几何体合并为一个Mesh → **理论上N个DrawCall降至1个**。关键技术点在于UV重映射的正确性（保证纹理采样不越界）、内存管理（及时销毁临时Mesh）、以及合理的脏标记更新策略（避免每帧重建）。该方案特别适合程序化关卡、城市建造、农场类等以静态摆放为主的游戏类型。
