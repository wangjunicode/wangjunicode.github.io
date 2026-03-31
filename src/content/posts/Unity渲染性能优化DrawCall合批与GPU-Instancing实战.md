---
title: Unity渲染性能优化：Draw Call合批与GPU Instancing实战
published: 2026-03-31
description: 深入解析Unity渲染性能优化的核心技术，包括静态/动态合批条件与限制、GPU Instancing原理与实现、SRP Batcher工作机制、DrawMeshInstanced实战、MaterialPropertyBlock用法，以及大型开放世界场景的渲染批次最优策略。
tags: [Unity, 渲染优化, Draw Call, GPU Instancing, SRP Batcher]
category: 性能优化
draft: false
---

## 一、Draw Call 的性能影响

每次 Draw Call 都意味着 CPU 向 GPU 发送一次绘制命令，包括：
1. 设置 Shader 状态
2. 传递 Uniform 参数
3. 提交顶点缓冲区
4. 触发光栅化

在移动端，**每帧 Draw Call 数量建议 <100**；PC 端建议 <500。

---

## 二、静态合批（Static Batching）

```csharp
/// <summary>
/// 静态合批工具类
/// </summary>
public static class StaticBatchingHelper
{
    /// <summary>
    /// 在运行时手动合批（适用于动态加载的静态物体）
    /// </summary>
    public static void BatchStaticObjects(GameObject[] objects, GameObject batchRoot = null)
    {
        // 标记为静态
        foreach (var obj in objects)
        {
            obj.isStatic = true;
            // 确保所有子物体也是静态的
            foreach (Transform child in obj.GetComponentsInChildren<Transform>())
                child.gameObject.isStatic = true;
        }
        
        // 运行时合批（仅在运行时使用，编辑器中用 BuildSettings 中的 Static Batching 选项）
        if (Application.isPlaying)
        {
            StaticBatchingUtility.Combine(objects, batchRoot ?? objects[0]);
        }
    }
    
    /// <summary>
    /// 检查对象是否适合静态合批
    /// </summary>
    public static bool IsEligibleForStaticBatching(GameObject obj)
    {
        var renderer = obj.GetComponent<MeshRenderer>();
        if (renderer == null) return false;
        
        // 静态合批条件：
        // 1. 使用相同的材质
        // 2. 标记为 Static
        // 3. 不使用 SkinnedMeshRenderer
        // 4. 顶点数 < 300 per mesh（建议值）
        
        return obj.isStatic && 
               renderer.sharedMaterials != null && 
               renderer.sharedMaterials.Length > 0;
    }
    
    /// <summary>
    /// 分析场景中的 Draw Call 分布
    /// </summary>
    [System.Diagnostics.Conditional("UNITY_EDITOR")]
    public static void AnalyzeDrawCalls()
    {
        var renderers = UnityEngine.Object.FindObjectsOfType<MeshRenderer>();
        var materialGroups = new Dictionary<Material, List<MeshRenderer>>();
        
        foreach (var r in renderers)
        {
            foreach (var mat in r.sharedMaterials)
            {
                if (mat == null) continue;
                if (!materialGroups.ContainsKey(mat))
                    materialGroups[mat] = new List<MeshRenderer>();
                materialGroups[mat].Add(r);
            }
        }
        
        Debug.Log($"[DrawCall Analysis] Total renderers: {renderers.Length}");
        Debug.Log($"[DrawCall Analysis] Unique materials: {materialGroups.Count}");
        
        foreach (var kv in materialGroups)
        {
            if (kv.Value.Count > 1)
                Debug.Log($"  Material '{kv.Key.name}': {kv.Value.Count} objects (potential batch)");
        }
    }
}
```

---

## 三、GPU Instancing

GPU Instancing 允许用一次 Draw Call 渲染多个使用相同 Mesh+Material 的对象：

```csharp
/// <summary>
/// GPU Instancing 手动批次渲染（DrawMeshInstanced）
/// 适用于：草地、树木、岩石等大量重复静态物体
/// </summary>
public class GPUInstancingRenderer : MonoBehaviour
{
    [Header("实例化配置")]
    [SerializeField] private Mesh instanceMesh;
    [SerializeField] private Material instanceMaterial;  // 必须启用 Enable GPU Instancing
    [SerializeField] private int instanceCount = 10000;
    [SerializeField] private float spawnRadius = 100f;
    [SerializeField] private ShadowCastingMode shadowMode = ShadowCastingMode.Off;

    private Matrix4x4[] matrices;       // 每个实例的变换矩阵
    private MaterialPropertyBlock propertyBlock;
    private Vector4[] colors;           // 每个实例的颜色（通过 MaterialPropertyBlock）

    // DrawMeshInstanced 每批次最多 1023 个实例
    private const int BATCH_SIZE = 1023;

    void Start()
    {
        GenerateInstances();
    }

    void GenerateInstances()
    {
        matrices = new Matrix4x4[instanceCount];
        colors = new Vector4[instanceCount];
        propertyBlock = new MaterialPropertyBlock();
        
        var rng = new System.Random(42);
        
        for (int i = 0; i < instanceCount; i++)
        {
            // 随机位置（圆形分布）
            float angle = (float)(rng.NextDouble() * Mathf.PI * 2);
            float radius = (float)(rng.NextDouble() * spawnRadius);
            Vector3 pos = new Vector3(
                Mathf.Cos(angle) * radius,
                0,
                Mathf.Sin(angle) * radius);
            
            // 随机旋转和缩放
            Quaternion rot = Quaternion.Euler(0, (float)(rng.NextDouble() * 360), 0);
            float scale = 0.8f + (float)(rng.NextDouble() * 0.4f);
            
            matrices[i] = Matrix4x4.TRS(pos, rot, Vector3.one * scale);
            
            // 随机颜色变化（草地颜色多样性）
            float greenVariation = 0.8f + (float)(rng.NextDouble() * 0.2f);
            colors[i] = new Vector4(0.3f, greenVariation, 0.2f, 1f);
        }
    }

    void Update()
    {
        // 分批渲染（每批1023个）
        int batches = Mathf.CeilToInt((float)instanceCount / BATCH_SIZE);
        
        for (int b = 0; b < batches; b++)
        {
            int startIdx = b * BATCH_SIZE;
            int batchCount = Mathf.Min(BATCH_SIZE, instanceCount - startIdx);
            
            // 提取当前批次的矩阵和颜色
            var batchMatrices = new Matrix4x4[batchCount];
            var batchColors = new Vector4[batchCount];
            Array.Copy(matrices, startIdx, batchMatrices, 0, batchCount);
            Array.Copy(colors, startIdx, batchColors, 0, batchCount);
            
            // 设置每实例颜色（通过 MaterialPropertyBlock）
            propertyBlock.SetVectorArray("_Color", batchColors);
            
            // 渲染（一次 Draw Call！）
            Graphics.DrawMeshInstanced(
                instanceMesh, 0, 
                instanceMaterial, 
                batchMatrices,
                batchCount,
                propertyBlock,
                shadowMode
            );
        }
    }
}
```

---

## 四、Compute Buffer 无限实例（DrawMeshInstancedIndirect）

```csharp
/// <summary>
/// 使用 Compute Buffer 的 GPU-Driven Rendering
/// 支持数十万个实例，由 GPU 直接控制绘制参数
/// </summary>
public class GPUDrivenGrassRenderer : MonoBehaviour
{
    [SerializeField] private Mesh grassMesh;
    [SerializeField] private Material grassMaterial;
    [SerializeField] private Texture2D heightMap;
    [SerializeField] private int instanceCount = 100000;
    [SerializeField] private float terrainSize = 500f;

    private ComputeBuffer instanceBuffer;
    private ComputeBuffer argsBuffer;
    private uint[] args = new uint[5] { 0, 0, 0, 0, 0 };
    private Bounds renderBounds;

    struct GrassInstanceData
    {
        public Vector3 position;
        public float rotation;
        public float scale;
        public float colorVariation;
    }

    void Start()
    {
        InitBuffers();
        PopulateInstances();
        SetupMaterialAndArgs();
    }

    void InitBuffers()
    {
        int stride = System.Runtime.InteropServices.Marshal.SizeOf(typeof(GrassInstanceData));
        instanceBuffer = new ComputeBuffer(instanceCount, stride);
        argsBuffer = new ComputeBuffer(1, args.Length * sizeof(uint), 
            ComputeBufferType.IndirectArguments);
    }

    void PopulateInstances()
    {
        var instances = new GrassInstanceData[instanceCount];
        var rng = new System.Random(123);
        
        for (int i = 0; i < instanceCount; i++)
        {
            float x = (float)(rng.NextDouble() * terrainSize - terrainSize / 2);
            float z = (float)(rng.NextDouble() * terrainSize - terrainSize / 2);
            float y = SampleHeight(x, z); // 采样地形高度
            
            instances[i] = new GrassInstanceData
            {
                position = new Vector3(x, y, z),
                rotation = (float)(rng.NextDouble() * 360f),
                scale = 0.5f + (float)(rng.NextDouble() * 0.5f),
                colorVariation = (float)rng.NextDouble()
            };
        }
        
        instanceBuffer.SetData(instances);
    }

    void SetupMaterialAndArgs()
    {
        grassMaterial.SetBuffer("_InstanceBuffer", instanceBuffer);
        
        // 设置间接绘制参数
        args[0] = (uint)grassMesh.GetIndexCount(0);
        args[1] = (uint)instanceCount;
        args[2] = (uint)grassMesh.GetIndexStart(0);
        args[3] = (uint)grassMesh.GetBaseVertex(0);
        
        argsBuffer.SetData(args);
        
        renderBounds = new Bounds(Vector3.zero, new Vector3(terrainSize, 100, terrainSize));
    }

    void Update()
    {
        // GPU端一次Draw Call绘制全部实例
        Graphics.DrawMeshInstancedIndirect(
            grassMesh, 0, grassMaterial, renderBounds, argsBuffer);
    }

    float SampleHeight(float x, float z)
    {
        if (heightMap == null) return 0f;
        
        float u = (x + terrainSize / 2f) / terrainSize;
        float v = (z + terrainSize / 2f) / terrainSize;
        return heightMap.GetPixelBilinear(u, v).grayscale * 50f;
    }

    void OnDestroy()
    {
        instanceBuffer?.Release();
        argsBuffer?.Release();
    }
}
```

---

## 五、SRP Batcher 原理

```csharp
/// <summary>
/// SRP Batcher 兼容的 Shader 要求
/// SRP Batcher 要求所有 Per-Material 属性在 CBUFFER 中
/// </summary>
/*
Shader "Custom/SRPBatcherCompatible"
{
    Properties
    {
        _BaseColor ("Base Color", Color) = (1,1,1,1)
        _Smoothness ("Smoothness", Range(0,1)) = 0.5
    }
    
    SubShader
    {
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            // ✅ SRP Batcher 兼容：所有自定义属性放在 UnityPerMaterial CBUFFER 中
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float _Smoothness;
            CBUFFER_END
            
            // Unity 内置的 UnityPerDraw 也已经是 CBUFFER
            // SRP Batcher 通过批量更新 CBUFFER 大幅减少状态切换开销
            
            ENDHLSL
        }
    }
}
*/

/// <summary>
/// 使用 MaterialPropertyBlock（不破坏合批）设置每对象属性
/// </summary>
public class OptimizedMaterialSetter : MonoBehaviour
{
    [SerializeField] private Color teamColor;
    
    private static readonly int ColorPropId = Shader.PropertyToID("_TeamColor");
    private MaterialPropertyBlock mpb;
    private Renderer rend;

    void Awake()
    {
        rend = GetComponent<Renderer>();
        mpb = new MaterialPropertyBlock();
    }

    void Start()
    {
        // ✅ 正确：使用 MaterialPropertyBlock，不会破坏合批
        rend.GetPropertyBlock(mpb);
        mpb.SetColor(ColorPropId, teamColor);
        rend.SetPropertyBlock(mpb);
        
        // ❌ 错误：修改 material（创建实例，破坏合批）
        // rend.material.color = teamColor;
    }
}
```

---

## 六、优化策略总结

| 场景 | 推荐方案 | 节省 Draw Call |
|------|----------|---------------|
| 场景静态建筑 | 静态合批 | ⭐⭐⭐⭐ |
| 相同材质大量对象 | GPU Instancing | ⭐⭐⭐⭐⭐ |
| 自定义 Shader | SRP Batcher | ⭐⭐⭐ |
| 百万级草地/粒子 | DrawMeshInstancedIndirect | ⭐⭐⭐⭐⭐ |
| UI 元素 | Canvas 合批（同 Canvas 组件） | ⭐⭐⭐ |

**性能监控工具：**
- Frame Debugger：查看每帧 Draw Call 详情
- RenderDoc：GPU 帧分析
- Unity Profiler：CPU/GPU 时间分布
- Stats 面板：实时 Draw Call 数量
