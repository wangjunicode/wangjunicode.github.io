---
title: 游戏LOD系统与遮挡剔除完全指南：从原理到大规模场景优化实战
published: 2026-03-28
description: 深入剖析游戏中LOD（Level of Detail）与遮挡剔除（Occlusion Culling）技术体系，涵盖HLOD层级细节、GPU Occlusion Query、软件遮挡剔除、植被与城市场景的大规模优化实战，配合完整代码示例。
tags: [LOD, OcclusionCulling, 渲染优化, Unity, 游戏图形学]
category: 渲染优化
draft: false
---

# 游戏LOD系统与遮挡剔除完全指南

## 一、为什么需要LOD与遮挡剔除？

现代游戏场景动辄数千个动态物体、数百万面的静态几何体。GPU每帧能处理的三角面数有其上限（移动端通常 100~300万，PC端可达数千万），若将所有物体不加区分地提交渲染，帧率将急剧下降。

**核心矛盾**：
- 玩家眼中远处物体仅占几个像素，却消耗与近处相同的渲染成本
- 被遮挡的物体从未出现在屏幕上，却仍然占用 Draw Call 和顶点着色器时间

LOD 解决"太远用高精度"的浪费，遮挡剔除解决"渲染了看不见的物体"的浪费。两者配合可将典型开放世界场景的渲染开销降低 **60%~80%**。

---

## 二、LOD系统深度解析

### 2.1 LOD基本概念

**LOD（Level of Detail）** 根据物体与摄像机的距离，动态替换为不同精度的网格：

| LOD级别 | 距离范围 | 面数比例 | 典型用途 |
|---------|---------|---------|---------|
| LOD0 | 0~15m | 100% | 近景主角、重要道具 |
| LOD1 | 15~40m | 50% | 中景建筑、NPC |
| LOD2 | 40~80m | 20% | 远景树木、岩石 |
| LOD3 | 80~150m | 5% | 地平线装饰物 |
| Culled | >150m | 0% | 完全剔除 |

### 2.2 Unity LOD Group 实现原理

Unity 的 `LODGroup` 组件通过屏幕相对高度（Screen Relative Transition Height）决定切换：

```csharp
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// 运行时动态设置LOD组，支持自定义切换阈值和淡入淡出
/// </summary>
public class DynamicLODSetup : MonoBehaviour
{
    [System.Serializable]
    public class LODConfig
    {
        public GameObject meshObject;       // 每个LOD级别的网格对象
        [Range(0, 1)] public float screenHeight; // 屏幕高度占比阈值（0~1）
        public float fadeTransitionWidth;   // 交叉淡入淡出宽度
    }

    [Header("LOD配置")]
    public List<LODConfig> lodConfigs = new List<LODConfig>();
    
    [Header("淡入淡出模式")]
    public LODFadeMode fadeMode = LODFadeMode.CrossFade;

    private LODGroup lodGroup;

    void Awake()
    {
        lodGroup = GetComponent<LODGroup>();
        if (lodGroup == null)
            lodGroup = gameObject.AddComponent<LODGroup>();
        
        BuildLODGroup();
    }

    void BuildLODGroup()
    {
        if (lodConfigs.Count == 0) return;

        LOD[] lods = new LOD[lodConfigs.Count];
        
        for (int i = 0; i < lodConfigs.Count; i++)
        {
            var cfg = lodConfigs[i];
            var renderers = cfg.meshObject.GetComponentsInChildren<Renderer>();
            
            lods[i] = new LOD(cfg.screenHeight, renderers);
        }

        lodGroup.SetLODs(lods);
        lodGroup.RecalculateBounds();
        lodGroup.fadeMode = fadeMode;
    }

    /// <summary>
    /// 根据质量设置动态调整LOD阈值（低端设备激进剔除）
    /// </summary>
    public void AdjustForQualityLevel(int qualityLevel)
    {
        // qualityLevel: 0=低, 1=中, 2=高
        float multiplier = qualityLevel switch
        {
            0 => 2.0f,  // 低端设备：更早切换到低精度LOD
            1 => 1.2f,
            2 => 1.0f,
            _ => 1.0f
        };

        // 调整全局LOD Bias
        QualitySettings.lodBias = 1.0f / multiplier;
        
        Debug.Log($"[LOD] 质量等级={qualityLevel}, LOD Bias={QualitySettings.lodBias:F2}");
    }
}
```

### 2.3 自动LOD生成工具

大型项目需要对上千个模型批量生成LOD，手动操作效率极低。以下是基于 Unity Editor 的自动化工具：

```csharp
#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using UnityMeshSimplifier;  // 需要安装 UnityMeshSimplifier 包

/// <summary>
/// 批量LOD生成编辑器工具
/// 支持对选中对象或整个文件夹自动生成多级LOD
/// </summary>
public class LODGeneratorTool : EditorWindow
{
    private float[] lodRatios = { 1.0f, 0.5f, 0.2f, 0.05f };
    private float[] lodScreenHeights = { 0.6f, 0.3f, 0.1f, 0.03f };
    private int lodLevels = 3;
    private bool preserveBorderEdges = true;
    private bool preserveUVSeamEdges = true;
    private string targetFolder = "Assets/Prefabs/Environment";

    [MenuItem("Tools/LOD Generator")]
    static void Open()
    {
        GetWindow<LODGeneratorTool>("LOD Generator");
    }

    void OnGUI()
    {
        GUILayout.Label("LOD批量生成工具", EditorStyles.boldLabel);
        EditorGUILayout.Space();
        
        lodLevels = EditorGUILayout.IntSlider("LOD级别数", lodLevels, 1, 4);
        preserveBorderEdges = EditorGUILayout.Toggle("保留边界边", preserveBorderEdges);
        preserveUVSeamEdges = EditorGUILayout.Toggle("保留UV接缝边", preserveUVSeamEdges);
        
        EditorGUILayout.Space();
        GUILayout.Label("各级LOD面数比例:");
        for (int i = 0; i < lodLevels; i++)
        {
            lodRatios[i] = EditorGUILayout.Slider($"LOD{i}", lodRatios[i], 0.01f, 1.0f);
            lodScreenHeights[i] = EditorGUILayout.Slider($"  └屏幕高度阈值", lodScreenHeights[i], 0.001f, 1.0f);
        }

        EditorGUILayout.Space();
        if (GUILayout.Button("对选中对象生成LOD"))
        {
            GenerateLODForSelection();
        }
        
        EditorGUILayout.Space();
        targetFolder = EditorGUILayout.TextField("目标文件夹", targetFolder);
        if (GUILayout.Button("批量处理文件夹"))
        {
            BatchGenerateLOD(targetFolder);
        }
    }

    void GenerateLODForSelection()
    {
        var selections = Selection.gameObjects;
        if (selections.Length == 0)
        {
            EditorUtility.DisplayDialog("提示", "请先选择要处理的游戏对象", "确定");
            return;
        }

        int processed = 0;
        foreach (var go in selections)
        {
            if (ProcessObject(go))
                processed++;
        }

        AssetDatabase.SaveAssets();
        Debug.Log($"[LOD] 成功处理 {processed}/{selections.Length} 个对象");
    }

    bool ProcessObject(GameObject go)
    {
        var meshFilter = go.GetComponent<MeshFilter>();
        if (meshFilter == null || meshFilter.sharedMesh == null)
            return false;

        // 获取或创建LODGroup
        var lodGroup = go.GetComponent<LODGroup>();
        if (lodGroup == null)
            lodGroup = go.AddComponent<LODGroup>();

        Mesh originalMesh = meshFilter.sharedMesh;
        LOD[] lods = new LOD[lodLevels + 1]; // +1 包含原始LOD0

        // LOD0 使用原始网格
        var lod0Renderer = go.GetComponent<Renderer>();
        if (lod0Renderer == null) return false;
        lods[0] = new LOD(lodScreenHeights[0], new Renderer[] { lod0Renderer });

        // 生成LOD1~N的简化网格
        for (int i = 1; i <= lodLevels; i++)
        {
            var simplifiedMesh = SimplifyMesh(originalMesh, lodRatios[i]);
            if (simplifiedMesh == null) continue;

            // 创建子对象存放简化网格
            string childName = $"LOD{i}";
            var childGo = GetOrCreateChild(go, childName);
            var childMeshFilter = childGo.GetComponent<MeshFilter>() ?? childGo.AddComponent<MeshFilter>();
            var childRenderer = childGo.GetComponent<MeshRenderer>() ?? childGo.AddComponent<MeshRenderer>();
            
            childMeshFilter.sharedMesh = simplifiedMesh;
            childRenderer.sharedMaterials = lod0Renderer.sharedMaterials;
            childGo.SetActive(false);

            float threshold = i < lodLevels ? lodScreenHeights[i] : 0f;
            lods[i] = new LOD(threshold, new Renderer[] { childRenderer });
        }

        lodGroup.SetLODs(lods);
        lodGroup.RecalculateBounds();

        EditorUtility.SetDirty(go);
        return true;
    }

    Mesh SimplifyMesh(Mesh originalMesh, float targetRatio)
    {
        var simplifier = new MeshSimplifier();
        simplifier.Initialize(originalMesh);
        simplifier.PreserveBorderEdges = preserveBorderEdges;
        simplifier.PreserveUVSeamEdges = preserveUVSeamEdges;
        simplifier.SimplifyMesh(targetRatio);
        return simplifier.ToMesh();
    }

    GameObject GetOrCreateChild(GameObject parent, string name)
    {
        var existing = parent.transform.Find(name);
        if (existing != null) return existing.gameObject;
        
        var child = new GameObject(name);
        child.transform.SetParent(parent.transform);
        child.transform.localPosition = Vector3.zero;
        child.transform.localRotation = Quaternion.identity;
        child.transform.localScale = Vector3.one;
        return child;
    }

    void BatchGenerateLOD(string folder)
    {
        var guids = AssetDatabase.FindAssets("t:Prefab", new[] { folder });
        int total = guids.Length;
        int processed = 0;

        for (int i = 0; i < total; i++)
        {
            string path = AssetDatabase.GUIDToAssetPath(guids[i]);
            EditorUtility.DisplayProgressBar("批量LOD生成", path, (float)i / total);

            var prefab = AssetDatabase.LoadAssetAtPath<GameObject>(path);
            if (prefab == null) continue;

            var instance = PrefabUtility.InstantiatePrefab(prefab) as GameObject;
            if (ProcessObject(instance))
            {
                PrefabUtility.SaveAsPrefabAssetAndConnect(instance, path, InteractionMode.AutomatedAction);
                processed++;
            }
            DestroyImmediate(instance);
        }

        EditorUtility.ClearProgressBar();
        AssetDatabase.SaveAssets();
        Debug.Log($"[LOD] 批量处理完成: {processed}/{total}");
    }
}
#endif
```

### 2.4 HLOD（Hierarchical LOD）

HLOD 是将多个相邻物体在远距离时合并为一个低精度网格，大幅减少 Draw Call：

```
近景（LOD0）: 建筑A(5000面) + 建筑B(4000面) + 建筑C(6000面)  → 3个Draw Call
远景（HLOD）: 建筑ABC合并体(500面)                              → 1个Draw Call
```

Unity 的 HLOD 插件（com.unity.hlod）实现了这一功能。以下是关键配置代码：

```csharp
using Unity.HLODSystem;
using UnityEngine;

/// <summary>
/// HLOD构建配置助手
/// 针对不同场景类型（城市/森林/室内）提供预设配置
/// </summary>
public static class HLODPresetConfigs
{
    /// <summary>
    /// 城市场景HLOD配置：建筑物密集，需要激进合并
    /// </summary>
    public static void ConfigureUrbanScene(HLOD hlodRoot)
    {
        // 每个HLOD簇的最大物体数量
        hlodRoot.ChunkSize = 30f;       // 30米为一个合并单元
        hlodRoot.MinObjectSize = 1f;    // 忽略1米以下的小物件
        
        // LOD切换距离
        hlodRoot.LODDistance = 0.3f;    // 屏幕高度30%时切换到HLOD
        
        Debug.Log("[HLOD] 城市场景配置完成");
    }

    /// <summary>
    /// 自然场景（森林）HLOD配置
    /// </summary>
    public static void ConfigureForestScene(HLOD hlodRoot)
    {
        hlodRoot.ChunkSize = 50f;
        hlodRoot.MinObjectSize = 0.5f;
        hlodRoot.LODDistance = 0.2f;
    }
}
```

---

## 三、遮挡剔除（Occlusion Culling）深度解析

### 3.1 三种主流遮挡剔除方案对比

| 方案 | 原理 | 优点 | 缺点 | 适用场景 |
|------|------|------|------|---------|
| Unity Umbra | 离线烘焙可见性数据 | 精确、零运行时开销 | 需要烘焙、内存占用高 | 静态室内/城市场景 |
| GPU Occlusion Query | GPU查询物体是否可见 | 动态对象有效 | 查询结果延迟1帧 | 大型动态场景 |
| 软件光栅化剔除 | CPU光栅化深度缓冲 | 低延迟、跨平台 | CPU开销较高 | 移动端/复杂场景 |
| Hi-Z Buffer剔除 | GPU层级深度缓冲 | 极高效、GPU驱动 | 实现复杂 | 高端PC/主机 |

### 3.2 Unity Umbra 遮挡剔除烘焙优化

```csharp
#if UNITY_EDITOR
using UnityEngine;
using UnityEditor;
using UnityEngine.Rendering;

/// <summary>
/// Umbra遮挡剔除烘焙配置优化工具
/// 针对不同场景尺寸自动选择合适的烘焙参数
/// </summary>
public class OcclusionCullingOptimizer : EditorWindow
{
    public enum SceneType { Indoor, Urban, OpenWorld }
    
    private SceneType sceneType = SceneType.Urban;
    private float smallestOccluder = 5f;    // 最小遮挡体尺寸
    private float smallestHole = 0.25f;     // 最小遮挡孔洞

    [MenuItem("Tools/Occlusion Culling Optimizer")]
    static void Open() => GetWindow<OcclusionCullingOptimizer>("OC Optimizer");

    void OnGUI()
    {
        GUILayout.Label("Umbra遮挡剔除优化", EditorStyles.boldLabel);
        
        sceneType = (SceneType)EditorGUILayout.EnumPopup("场景类型", sceneType);
        
        EditorGUILayout.Space();
        GUILayout.Label("推荐参数:");
        
        switch (sceneType)
        {
            case SceneType.Indoor:
                EditorGUILayout.HelpBox("室内场景：较小的遮挡体，精确剔除", MessageType.Info);
                smallestOccluder = 1f;
                smallestHole = 0.1f;
                break;
            case SceneType.Urban:
                EditorGUILayout.HelpBox("城市场景：建筑物为主要遮挡体", MessageType.Info);
                smallestOccluder = 5f;
                smallestHole = 0.25f;
                break;
            case SceneType.OpenWorld:
                EditorGUILayout.HelpBox("开放世界：山丘地形为主要遮挡体，减少烘焙时间", MessageType.Info);
                smallestOccluder = 15f;
                smallestHole = 1f;
                break;
        }

        smallestOccluder = EditorGUILayout.FloatField("最小遮挡体(m)", smallestOccluder);
        smallestHole = EditorGUILayout.FloatField("最小孔洞(m)", smallestHole);

        EditorGUILayout.Space();
        if (GUILayout.Button("应用参数并烘焙"))
        {
            ApplyAndBake();
        }

        if (GUILayout.Button("分析遮挡剔除效果"))
        {
            AnalyzeOcclusionEffect();
        }
    }

    void ApplyAndBake()
    {
        // 设置遮挡剔除参数
        StaticOcclusionCulling.smallestOccluder = smallestOccluder;
        StaticOcclusionCulling.smallestHole = smallestHole;
        
        // 自动标记大型静态物体为 Occluder
        MarkOccluders();
        
        // 开始烘焙
        StaticOcclusionCulling.Compute();
        
        Debug.Log($"[OC] 烘焙参数: 最小遮挡体={smallestOccluder}m, 最小孔洞={smallestHole}m");
    }

    void MarkOccluders()
    {
        var renderers = FindObjectsOfType<MeshRenderer>();
        int markedCount = 0;

        foreach (var r in renderers)
        {
            // 非静态对象跳过
            if (!r.gameObject.isStatic) continue;
            
            var bounds = r.bounds;
            float minDimension = Mathf.Min(bounds.size.x, bounds.size.y, bounds.size.z);
            
            // 体积足够大的物体标记为遮挡体
            if (minDimension >= smallestOccluder)
            {
                GameObjectUtility.SetStaticEditorFlags(r.gameObject,
                    GameObjectUtility.GetStaticEditorFlags(r.gameObject) 
                    | StaticEditorFlags.OccluderStatic);
                markedCount++;
            }
            
            // 所有静态物体标记为被遮挡体
            GameObjectUtility.SetStaticEditorFlags(r.gameObject,
                GameObjectUtility.GetStaticEditorFlags(r.gameObject) 
                | StaticEditorFlags.OccludeeStatic);
        }

        Debug.Log($"[OC] 标记了 {markedCount} 个遮挡体");
    }

    void AnalyzeOcclusionEffect()
    {
        // 统计场景中的遮挡状态
        var renderers = FindObjectsOfType<Renderer>();
        int total = 0, culled = 0;

        Camera mainCam = Camera.main;
        if (mainCam == null)
        {
            Debug.LogWarning("[OC] 未找到主摄像机");
            return;
        }

        foreach (var r in renderers)
        {
            if (!r.gameObject.isStatic) continue;
            total++;
            if (!r.isVisible) culled++;
        }

        float cullRate = total > 0 ? (float)culled / total * 100f : 0;
        Debug.Log($"[OC] 静态物体剔除率: {cullRate:F1}% ({culled}/{total})");
    }
}
#endif
```

### 3.3 Hi-Z Buffer 遮挡剔除（GPU驱动）

Hi-Z 是目前高端游戏引擎最流行的 GPU 端遮挡剔除方案：

```hlsl
// Hi-Z Buffer 降采样 Compute Shader
// 文件：HiZMipGen.compute
#pragma kernel BuildHiZ

Texture2D<float> _DepthTexture;
RWTexture2D<float> _HiZMip;

[numthreads(8, 8, 1)]
void BuildHiZ(uint3 id : SV_DispatchThreadID)
{
    // 从更细层级的深度缓冲中取4个样本，保留最大深度（最近的）
    int2 srcCoord = id.xy * 2;
    
    float d0 = _DepthTexture[srcCoord + int2(0, 0)];
    float d1 = _DepthTexture[srcCoord + int2(1, 0)];
    float d2 = _DepthTexture[srcCoord + int2(0, 1)];
    float d3 = _DepthTexture[srcCoord + int2(1, 1)];
    
    // 保留最大值（OpenGL反向深度时用min）
    _HiZMip[id.xy] = max(max(d0, d1), max(d2, d3));
}
```

```csharp
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// Hi-Z Buffer遮挡剔除系统
/// 利用层级深度缓冲在GPU上高效剔除被遮挡的物体
/// </summary>
public class HiZOcclusionCulling : MonoBehaviour
{
    [Header("Hi-Z Buffer配置")]
    public ComputeShader hiZBuildShader;
    public ComputeShader occlusionTestShader;
    
    [Header("调试")]
    public bool showDebugVisualization = false;

    private RenderTexture hiZBuffer;
    private ComputeBuffer visibilityBuffer;
    private Camera mainCamera;
    
    // 被管理的渲染器列表（通常通过场景扫描填充）
    private Renderer[] managedRenderers;
    private int[] visibilityResults;

    void Start()
    {
        mainCamera = GetComponent<Camera>();
        InitializeBuffers();
        CollectManagedRenderers();
    }

    void InitializeBuffers()
    {
        int width = mainCamera.pixelWidth;
        int height = mainCamera.pixelHeight;
        
        // 创建Hi-Z缓冲（Mip链）
        hiZBuffer = new RenderTexture(width, height, 0, RenderTextureFormat.RFloat);
        hiZBuffer.enableRandomWrite = true;
        hiZBuffer.useMipMap = true;
        hiZBuffer.autoGenerateMips = false;
        hiZBuffer.filterMode = FilterMode.Point;
        hiZBuffer.Create();
        
        Debug.Log($"[HiZ] 初始化 {width}x{height} Hi-Z Buffer，Mip层数: {hiZBuffer.mipmapCount}");
    }

    void CollectManagedRenderers()
    {
        managedRenderers = FindObjectsOfType<MeshRenderer>();
        visibilityResults = new int[managedRenderers.Length];
        
        // 创建可见性结果Buffer
        visibilityBuffer = new ComputeBuffer(managedRenderers.Length, sizeof(int));
        
        Debug.Log($"[HiZ] 管理 {managedRenderers.Length} 个渲染器");
    }

    void OnPreRender()
    {
        // 每帧构建Hi-Z Buffer，然后进行可见性测试
        BuildHiZBuffer();
        TestVisibility();
        ApplyVisibilityResults();
    }

    void BuildHiZBuffer()
    {
        // 将当前深度缓冲复制到Hi-Z Buffer第0层
        // 然后逐层降采样构建Mip链
        int kernel = hiZBuildShader.FindKernel("BuildHiZ");
        
        for (int mip = 1; mip < hiZBuffer.mipmapCount; mip++)
        {
            int mipWidth = Mathf.Max(1, hiZBuffer.width >> mip);
            int mipHeight = Mathf.Max(1, hiZBuffer.height >> mip);
            
            hiZBuildShader.SetInt("_MipLevel", mip);
            hiZBuildShader.SetTexture(kernel, "_HiZMip", hiZBuffer, mip);
            hiZBuildShader.Dispatch(kernel, 
                Mathf.CeilToInt(mipWidth / 8f),
                Mathf.CeilToInt(mipHeight / 8f), 1);
        }
    }

    void TestVisibility()
    {
        // 为每个物体计算其AABB在屏幕上的投影，与Hi-Z对比
        // 这里简化示意，完整实现需要在Compute Shader中处理
        int kernel = occlusionTestShader.FindKernel("TestOcclusion");
        
        occlusionTestShader.SetTexture(kernel, "_HiZBuffer", hiZBuffer);
        occlusionTestShader.SetBuffer(kernel, "_VisibilityResult", visibilityBuffer);
        occlusionTestShader.SetMatrix("_ViewProjectionMatrix", 
            mainCamera.projectionMatrix * mainCamera.worldToCameraMatrix);
        
        occlusionTestShader.Dispatch(kernel,
            Mathf.CeilToInt(managedRenderers.Length / 64f), 1, 1);
        
        // 异步回读（会引入1帧延迟，可接受）
        visibilityBuffer.GetData(visibilityResults);
    }

    void ApplyVisibilityResults()
    {
        for (int i = 0; i < managedRenderers.Length; i++)
        {
            if (managedRenderers[i] != null)
                managedRenderers[i].enabled = visibilityResults[i] != 0;
        }
    }

    void OnDestroy()
    {
        if (hiZBuffer != null) hiZBuffer.Release();
        if (visibilityBuffer != null) visibilityBuffer.Release();
    }
}
```

### 3.4 软件遮挡剔除（移动端友好）

移动端 GPU 不支持异步计算，软件光栅化剔除是更好的选择：

```csharp
using UnityEngine;
using Unity.Collections;
using Unity.Jobs;
using Unity.Mathematics;
using Unity.Burst;

/// <summary>
/// 基于Jobs系统的软件遮挡剔除
/// 在CPU端进行高效的视锥剔除 + 简单深度测试
/// </summary>
public class SoftwareOcclusionCulling : MonoBehaviour
{
    private Camera mainCamera;
    private NativeArray<float4> frustumPlanes;     // 视锥6个平面
    private NativeArray<float3> boundsCenters;     // AABB中心
    private NativeArray<float3> boundsExtents;     // AABB半尺寸
    private NativeArray<bool> visibilityResults;
    
    private Renderer[] renderers;
    private JobHandle cullingJobHandle;

    void Start()
    {
        mainCamera = Camera.main;
        CollectRenderers();
        AllocateBuffers();
    }

    void CollectRenderers()
    {
        renderers = FindObjectsOfType<MeshRenderer>();
    }

    void AllocateBuffers()
    {
        int count = renderers.Length;
        frustumPlanes = new NativeArray<float4>(6, Allocator.Persistent);
        boundsCenters = new NativeArray<float3>(count, Allocator.Persistent);
        boundsExtents = new NativeArray<float3>(count, Allocator.Persistent);
        visibilityResults = new NativeArray<bool>(count, Allocator.Persistent);

        // 缓存Bounds数据（静态物体只需计算一次）
        for (int i = 0; i < count; i++)
        {
            if (renderers[i] != null)
            {
                var bounds = renderers[i].bounds;
                boundsCenters[i] = bounds.center;
                boundsExtents[i] = bounds.extents;
            }
        }
    }

    void Update()
    {
        // 等待上一帧的Job完成
        cullingJobHandle.Complete();
        
        // 应用上一帧的可见性结果
        ApplyVisibility();
        
        // 更新视锥平面
        UpdateFrustumPlanes();
        
        // 调度新的剔除Job
        var cullingJob = new FrustumCullingJob
        {
            FrustumPlanes = frustumPlanes,
            BoundsCenters = boundsCenters,
            BoundsExtents = boundsExtents,
            Results = visibilityResults
        };

        cullingJobHandle = cullingJob.Schedule(renderers.Length, 64);
    }

    void UpdateFrustumPlanes()
    {
        Plane[] planes = GeometryUtility.CalculateFrustumPlanes(mainCamera);
        for (int i = 0; i < 6; i++)
        {
            frustumPlanes[i] = new float4(
                planes[i].normal.x,
                planes[i].normal.y,
                planes[i].normal.z,
                planes[i].distance
            );
        }
    }

    void ApplyVisibility()
    {
        for (int i = 0; i < renderers.Length; i++)
        {
            if (renderers[i] != null)
                renderers[i].enabled = visibilityResults[i];
        }
    }

    void OnDestroy()
    {
        cullingJobHandle.Complete();
        if (frustumPlanes.IsCreated) frustumPlanes.Dispose();
        if (boundsCenters.IsCreated) boundsCenters.Dispose();
        if (boundsExtents.IsCreated) boundsExtents.Dispose();
        if (visibilityResults.IsCreated) visibilityResults.Dispose();
    }

    /// <summary>
    /// Burst编译的视锥剔除Job
    /// </summary>
    [BurstCompile]
    struct FrustumCullingJob : IJobParallelFor
    {
        [ReadOnly] public NativeArray<float4> FrustumPlanes;
        [ReadOnly] public NativeArray<float3> BoundsCenters;
        [ReadOnly] public NativeArray<float3> BoundsExtents;
        [WriteOnly] public NativeArray<bool> Results;

        public void Execute(int index)
        {
            float3 center = BoundsCenters[index];
            float3 extents = BoundsExtents[index];

            // 对6个视锥平面逐一测试
            for (int p = 0; p < 6; p++)
            {
                float4 plane = FrustumPlanes[p];
                float3 normal = new float3(plane.x, plane.y, plane.z);
                
                // 计算AABB在法线方向上的投影半径
                float r = math.abs(extents.x * normal.x) 
                        + math.abs(extents.y * normal.y) 
                        + math.abs(extents.z * normal.z);
                
                // 中心点到平面的有符号距离
                float d = math.dot(normal, center) + plane.w;
                
                // 完全在平面外侧 → 不可见
                if (d + r < 0)
                {
                    Results[index] = false;
                    return;
                }
            }

            Results[index] = true;
        }
    }
}
```

---

## 四、大规模场景综合优化方案

### 4.1 开放世界场景流水线

```
[场景数据]
    │
    ├─ 静态物体 ──→ [Umbra 烘焙OC] ──→ [HLOD合并] ──→ GPU渲染
    │
    ├─ 植被/草地 ──→ [GPU Instance] ──→ [Hi-Z剔除] ──→ Indirect Draw
    │
    ├─ 动态物体 ──→ [视锥剔除 Jobs] ──→ [距离剔除] ──→ 常规渲染
    │
    └─ 远景 ──→ [Imposter替代] ──→ Billboard渲染
```

### 4.2 GPU Instancing + LOD 植被系统

```csharp
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// 基于GPU Instancing的大规模植被LOD渲染系统
/// 支持百万级实例，结合距离LOD和视锥剔除
/// </summary>
public class VegetationLODSystem : MonoBehaviour
{
    [System.Serializable]
    public struct VegetationLOD
    {
        public Mesh mesh;
        public Material material;
        public float maxDistance;    // 此LOD级别的最大渲染距离
    }

    [Header("植被配置")]
    public VegetationLOD[] lods;           // LOD0(近) → LOD2(远)
    public int maxInstanceCount = 100000;

    private Matrix4x4[][] instanceMatrices; // 按LOD分组的实例矩阵
    private int[] instanceCounts;
    private MaterialPropertyBlock propertyBlock;
    private Camera mainCamera;

    // 所有植被实例的原始数据
    private Vector3[] allPositions;
    private Vector3[] allScales;
    private Quaternion[] allRotations;
    private int totalInstances;

    void Start()
    {
        mainCamera = Camera.main;
        propertyBlock = new MaterialPropertyBlock();
        
        instanceMatrices = new Matrix4x4[lods.Length][];
        instanceCounts = new int[lods.Length];
        
        for (int i = 0; i < lods.Length; i++)
            instanceMatrices[i] = new Matrix4x4[maxInstanceCount];
        
        // 实际项目中从场景数据加载植被位置
        GenerateRandomVegetation(totalInstances = 50000);
    }

    void GenerateRandomVegetation(int count)
    {
        allPositions = new Vector3[count];
        allScales = new Vector3[count];
        allRotations = new Quaternion[count];

        for (int i = 0; i < count; i++)
        {
            allPositions[i] = new Vector3(
                Random.Range(-500f, 500f), 0,
                Random.Range(-500f, 500f));
            allScales[i] = Vector3.one * Random.Range(0.8f, 1.2f);
            allRotations[i] = Quaternion.Euler(0, Random.Range(0f, 360f), 0);
        }
    }

    void Update()
    {
        Vector3 camPos = mainCamera.transform.position;
        Plane[] frustumPlanes = GeometryUtility.CalculateFrustumPlanes(mainCamera);

        // 重置计数
        for (int i = 0; i < lods.Length; i++)
            instanceCounts[i] = 0;

        // 分配每个实例到对应LOD
        for (int i = 0; i < totalInstances; i++)
        {
            float dist = Vector3.Distance(camPos, allPositions[i]);
            
            // 视锥剔除（简化版：按距离球形判断）
            float maxDist = lods[lods.Length - 1].maxDistance;
            if (dist > maxDist) continue;

            // 根据距离选择LOD级别
            int lodLevel = GetLODLevel(dist);
            if (lodLevel < 0) continue;

            int idx = instanceCounts[lodLevel];
            if (idx >= maxInstanceCount) continue;

            instanceMatrices[lodLevel][idx] = Matrix4x4.TRS(
                allPositions[i], allRotations[i], allScales[i]);
            instanceCounts[lodLevel]++;
        }

        // 提交渲染
        DrawAllLODs();
    }

    int GetLODLevel(float distance)
    {
        for (int i = 0; i < lods.Length; i++)
        {
            if (distance <= lods[i].maxDistance)
                return i;
        }
        return -1; // 超出最远距离，不渲染
    }

    void DrawAllLODs()
    {
        for (int i = 0; i < lods.Length; i++)
        {
            int count = instanceCounts[i];
            if (count == 0) continue;

            // Unity Graphics.DrawMeshInstanced 每次最多1023个实例
            int batchSize = 1023;
            for (int offset = 0; offset < count; offset += batchSize)
            {
                int thisCount = Mathf.Min(batchSize, count - offset);
                
                // 提取当前批次的矩阵子集
                Matrix4x4[] batch = new Matrix4x4[thisCount];
                System.Array.Copy(instanceMatrices[i], offset, batch, 0, thisCount);
                
                Graphics.DrawMeshInstanced(
                    lods[i].mesh,
                    0,
                    lods[i].material,
                    batch,
                    thisCount,
                    propertyBlock,
                    ShadowCastingMode.Off,  // 远处植被不投射阴影
                    false                   // 不接收阴影
                );
            }
        }
    }

    void OnGUI()
    {
        // 调试信息
        GUILayout.Label($"[植被LOD] 总实例: {totalInstances}");
        for (int i = 0; i < lods.Length; i++)
            GUILayout.Label($"  LOD{i}: {instanceCounts[i]} 个实例");
    }
}
```

---

## 五、性能分析与调优

### 5.1 关键性能指标

| 指标 | 工具 | 目标值（移动端） |
|------|------|----------------|
| Draw Call数量 | Frame Debugger | < 200 |
| 顶点数/帧 | Unity Profiler | < 500万 |
| 视锥剔除率 | 自定义统计 | > 60% |
| HLOD切换频率 | Custom Event | < 5次/秒 |

### 5.2 常见问题排查

**问题1：LOD切换时出现明显闪烁**
```csharp
// 解决方案：启用CrossFade模式并增大过渡宽度
lodGroup.fadeMode = LODFadeMode.CrossFade;
// 在Shader中添加LOD淡入淡出支持：
// #pragma multi_compile _ LOD_FADE_CROSSFADE
// UNITY_APPLY_DITHER_CROSSFADE(i.pos);
```

**问题2：Umbra烘焙数据过大**
```
优化步骤：
1. 增大 smallestOccluder 参数（减少遮挡体数量）
2. 仅对重要区域烘焙，使用Occlusion Area划分
3. 检查是否有过多细小碎片标记为OccluderStatic
```

**问题3：远距离物体仍然可见（LOD Culled失效）**
```csharp
// 确认LODGroup的最后一个LOD的screenRelativeTransitionHeight > 0
// 或者使用距离直接剔除
float distSq = (transform.position - Camera.main.transform.position).sqrMagnitude;
renderer.enabled = distSq < maxDistanceSq;
```

---

## 六、最佳实践总结

### LOD最佳实践

1. **面数比例黄金准则**：LOD1 = 50%，LOD2 = 15~25%，LOD3 = 5%
2. **屏幕高度阈值**：不要设置小于 0.02（2%），过小的阈值反而浪费性能
3. **CrossFade必须配合Shader支持**：使用 `UNITY_APPLY_DITHER_CROSSFADE` 宏
4. **HLOD优先于LOD**：对于10米以上的建筑，HLOD带来的Draw Call减少更显著
5. **移动端LOD Bias降低**：移动端将 `QualitySettings.lodBias` 设为 0.5~0.7

### 遮挡剔除最佳实践

1. **室内场景必用Umbra**：正确烘焙的Umbra几乎无运行时开销
2. **开放世界优先视锥剔除**：Umbra在超大场景烘焙成本过高
3. **动态物体用GPU Query或Jobs**：Umbra只对静态物体有效
4. **避免频繁Enable/Disable**：高频切换Renderer.enabled有开销，改用Layer Mask
5. **Hi-Z适合PC/主机**：移动端GPU异步计算支持有限，建议软件光栅化方案

### 综合优化流程

```
Step1: 开启Stats面板，记录基准Draw Call数和面数
Step2: 对所有静态物体运行Umbra烘焙，观察改善
Step3: 为场景中的100面以上物体添加LOD
Step4: 对建筑群使用HLOD合并
Step5: 对植被使用GPU Instancing + 距离剔除
Step6: 再次测量，对比改善效果
```

通过 LOD + 遮挡剔除 + HLOD + GPU Instancing 的组合，典型开放世界场景可以实现：

- **Draw Call 减少 70%**
- **GPU 顶点负载减少 60%**
- **整体帧率提升 2~3 倍**
