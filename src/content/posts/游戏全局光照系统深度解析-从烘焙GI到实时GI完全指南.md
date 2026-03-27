---
title: 游戏全局光照系统深度解析：从烘焙GI到实时GI完全指南
published: 2026-03-27
description: 深入解析游戏开发中的全局光照（Global Illumination）技术体系，涵盖烘焙光照贴图、光照探针、实时GI、LPPV、GPU光线追踪等核心技术，结合Unity实战案例与移动端性能优化策略。
tags: [全局光照, GI, 光照探针, Lightmap, 实时GI, Unity, 渲染优化, 移动端]
category: 渲染技术
draft: false
---

# 游戏全局光照系统深度解析：从烘焙GI到实时GI完全指南

## 一、全局光照基础概念

### 1.1 什么是全局光照

全局光照（Global Illumination，GI）是一类模拟光线在场景中多次弹射、散射和相互影响的渲染技术。与只计算直接光照的局部光照模型不同，GI 能够产生间接光（Indirect Light）、颜色渗透（Color Bleeding）、软阴影和环境遮蔽等视觉效果，使场景看起来更真实自然。

```
直接光照（Local Illumination）：
  光源 → 表面 → 眼睛

全局光照（Global Illumination）：
  光源 → 表面A → 表面B → ... → 眼睛（多次弹射）
        ↘ 环境遮蔽 ↗
```

### 1.2 GI 技术分类

| 技术类型 | 代表算法 | 特点 | 适用场景 |
|---------|---------|------|---------|
| 烘焙GI | Lightmap、Enlighten | 预计算、零运行时开销 | 静态场景 |
| 动态GI | LPPV、SH探针 | 运行时更新、精度有限 | 动态对象 |
| 实时GI | SSGI、DDGI、RTGI | 高精度、性能开销大 | 高端平台 |
| 混合GI | 烘焙+动态探针 | 平衡质量与性能 | 商业项目主流 |

### 1.3 渲染方程基础

Kajiya 渲染方程（The Rendering Equation）是 GI 的数学基础：

$$L_o(x, \omega_o) = L_e(x, \omega_o) + \int_\Omega f_r(x, \omega_i, \omega_o) L_i(x, \omega_i) (\omega_i \cdot n) d\omega_i$$

- **L_o**：出射辐亮度
- **L_e**：自发光
- **f_r**：BRDF（双向反射分布函数）
- **L_i**：入射辐亮度（来自所有方向的间接光）

---

## 二、烘焙光照贴图（Lightmap）技术

### 2.1 Lightmap 工作原理

烘焙光照贴图将场景的静态光照信息预计算并存储到纹理中，运行时直接采样贴图而无需重新计算：

```csharp
// Unity 光照烘焙配置示例
using UnityEditor;
using UnityEngine;

public class LightmapBakeConfig
{
    [MenuItem("Tools/GI/Configure Lightmap Settings")]
    public static void ConfigureLightmapSettings()
    {
        // 设置烘焙模式
        LightmapEditorSettings.lightmapper = LightmapEditorSettings.Lightmapper.ProgressiveGPU;
        
        // 光照贴图分辨率（texels per unit）
        LightmapEditorSettings.bakeResolution = 40f;
        LightmapEditorSettings.resolution = 2f;  // 间接光分辨率
        
        // 最大光照贴图尺寸
        LightmapEditorSettings.maxAtlasSize = 1024;
        
        // 采样次数（影响质量和烘焙时间）
        LightmapEditorSettings.directSampleCount = 32;
        LightmapEditorSettings.indirectSampleCount = 512;
        
        // 光线反弹次数
        LightmapEditorSettings.bounces = 4;
        
        // 过滤设置（降噪）
        LightmapEditorSettings.filteringMode = LightmapEditorSettings.FilterMode.Auto;
        
        Debug.Log("光照贴图配置完成！");
    }
    
    [MenuItem("Tools/GI/Bake Lightmaps")]
    public static void BakeLightmaps()
    {
        // 异步烘焙
        Lightmapping.BakeAsync();
        EditorApplication.update += OnBakeProgress;
    }
    
    private static void OnBakeProgress()
    {
        if (!Lightmapping.isRunning)
        {
            EditorApplication.update -= OnBakeProgress;
            Debug.Log("烘焙完成！");
        }
        else
        {
            float progress = Lightmapping.buildProgress;
            EditorUtility.DisplayProgressBar("烘焙光照", $"进度: {progress * 100:F1}%", progress);
        }
    }
}
```

### 2.2 UV 展开与 Lightmap UV 规范

Lightmap 烘焙质量的关键在于合理的 UV2 展开：

```csharp
// 自动生成 Lightmap UV 的工具
using UnityEditor;
using UnityEngine;

public class LightmapUVGenerator
{
    [MenuItem("Tools/GI/Generate Lightmap UV")]
    public static void GenerateLightmapUV()
    {
        foreach (var obj in Selection.gameObjects)
        {
            var meshFilter = obj.GetComponent<MeshFilter>();
            if (meshFilter == null) continue;
            
            // 获取网格路径
            string meshPath = AssetDatabase.GetAssetPath(meshFilter.sharedMesh);
            if (string.IsNullOrEmpty(meshPath)) continue;
            
            // 配置导入设置
            var importer = AssetImporter.GetAtPath(meshPath) as ModelImporter;
            if (importer == null) continue;
            
            // 启用自动生成 Lightmap UV
            importer.generateSecondaryUV = true;
            
            // UV 生成参数
            importer.secondaryUVAngleDistortion = 8f;   // 角度失真容差
            importer.secondaryUVAreaDistortion = 15f;    // 面积失真容差
            importer.secondaryUVHardAngle = 88f;         // 硬边角度阈值
            importer.secondaryUVMarginMethod = ModelImporterSecondaryUVMarginMethod.Calculate;
            importer.secondaryUVMinLightmapResolution = 40f;
            importer.secondaryUVMinObjectScale = 1f;
            
            // 重新导入
            importer.SaveAndReimport();
            Debug.Log($"已为 {obj.name} 生成 Lightmap UV");
        }
    }
    
    // 检查 UV 覆盖率（UV 利用率诊断）
    [MenuItem("Tools/GI/Diagnose UV Coverage")]
    public static void DiagnoseUVCoverage()
    {
        foreach (var obj in Selection.gameObjects)
        {
            var meshFilter = obj.GetComponent<MeshFilter>();
            if (meshFilter == null) continue;
            
            var mesh = meshFilter.sharedMesh;
            if (mesh.uv2 == null || mesh.uv2.Length == 0)
            {
                Debug.LogWarning($"{obj.name}: 没有 UV2（Lightmap UV）！");
                continue;
            }
            
            // 计算 UV 边界框
            float minX = float.MaxValue, minY = float.MaxValue;
            float maxX = float.MinValue, maxY = float.MinValue;
            
            foreach (var uv in mesh.uv2)
            {
                minX = Mathf.Min(minX, uv.x);
                minY = Mathf.Min(minY, uv.y);
                maxX = Mathf.Max(maxX, uv.x);
                maxY = Mathf.Max(maxY, uv.y);
            }
            
            float coverage = (maxX - minX) * (maxY - minY);
            Debug.Log($"{obj.name}: UV2 覆盖率 = {coverage * 100:F1}%，范围 [{minX:F3},{minY:F3}] - [{maxX:F3},{maxY:F3}]");
        }
    }
}
```

### 2.3 Lightmap 压缩与运行时加载

```csharp
// 运行时 Lightmap 动态切换（昼夜系统）
using UnityEngine;
using System.Collections.Generic;

[System.Serializable]
public struct LightmapSet
{
    public string name;
    public LightmapData[] lightmaps;
    public LightmapData[] lightmapsDirLight;
    public LightmapData[] lightmapsShadowMask;
}

public class DayNightLightmapManager : MonoBehaviour
{
    [SerializeField] private LightmapSet[] lightmapSets;  // 早/中/晚/夜 多套烘焙
    [SerializeField] private float blendDuration = 2f;
    
    private int currentSetIndex = 0;
    private Coroutine blendCoroutine;
    
    // 渲染器 -> 光照贴图索引映射（保存初始状态）
    private Dictionary<Renderer, int> rendererLightmapIndex = new Dictionary<Renderer, int>();
    
    private void Awake()
    {
        // 缓存所有渲染器的原始光照贴图索引
        var renderers = FindObjectsOfType<Renderer>();
        foreach (var r in renderers)
        {
            rendererLightmapIndex[r] = r.lightmapIndex;
        }
    }
    
    public void SwitchToLightmapSet(int targetIndex)
    {
        if (blendCoroutine != null)
            StopCoroutine(blendCoroutine);
        blendCoroutine = StartCoroutine(BlendLightmaps(currentSetIndex, targetIndex));
    }
    
    private System.Collections.IEnumerator BlendLightmaps(int from, int to)
    {
        float elapsed = 0f;
        var fromSet = lightmapSets[from];
        var toSet = lightmapSets[to];
        
        while (elapsed < blendDuration)
        {
            elapsed += Time.deltaTime;
            float t = elapsed / blendDuration;
            
            // 注意：原生 Lightmap 不支持运行时混合
            // 实际方案：使用 GPU 着色器混合两套光照贴图
            BlendLightmapsGPU(fromSet, toSet, t);
            yield return null;
        }
        
        // 切换完成，应用目标光照集
        LightmapSettings.lightmaps = toSet.lightmaps;
        currentSetIndex = to;
    }
    
    private void BlendLightmapsGPU(LightmapSet from, LightmapSet to, float t)
    {
        // 通过全局 Shader 属性传递混合因子
        Shader.SetGlobalFloat("_LightmapBlend", t);
        // 传递两套光照贴图（需要自定义 Shader 支持）
        if (from.lightmaps.Length > 0 && to.lightmaps.Length > 0)
        {
            Shader.SetGlobalTexture("_LightmapA", from.lightmaps[0].lightmapColor);
            Shader.SetGlobalTexture("_LightmapB", to.lightmaps[0].lightmapColor);
        }
    }
}
```

---

## 三、光照探针（Light Probe）系统

### 3.1 光照探针原理

光照探针在场景中采样间接光，用球谐函数（Spherical Harmonics）编码存储，供动态物体查询：

```
SH 编码阶数与精度：
  L0（1个系数）  ：仅均匀光照，极低精度
  L1（4个系数）  ：低频漫反射方向，4×RGB = 12 float
  L2（9个系数）  ：标准精度，9×RGB = 27 float  ← Unity 使用
  L3（16个系数） ：高精度，主机/PC 高端效果
```

```csharp
// 自定义光照探针组放置工具
using UnityEditor;
using UnityEngine;

public class LightProbeAutoplacer : EditorWindow
{
    private float gridSpacing = 2f;
    private float heightOffset = 0.5f;
    private Vector3 areaSize = new Vector3(20f, 4f, 20f);
    private int heightLayers = 2;
    
    [MenuItem("Tools/GI/Light Probe Auto Placer")]
    static void ShowWindow()
    {
        GetWindow<LightProbeAutoplacer>("光照探针自动放置");
    }
    
    private void OnGUI()
    {
        GUILayout.Label("光照探针自动放置工具", EditorStyles.boldLabel);
        gridSpacing = EditorGUILayout.FloatField("网格间距（米）", gridSpacing);
        heightOffset = EditorGUILayout.FloatField("起始高度偏移", heightOffset);
        areaSize = EditorGUILayout.Vector3Field("区域大小", areaSize);
        heightLayers = EditorGUILayout.IntField("高度层数", heightLayers);
        
        if (GUILayout.Button("生成光照探针"))
        {
            GenerateLightProbes();
        }
    }
    
    private void GenerateLightProbes()
    {
        var probeGroup = new GameObject("LightProbeGroup_Auto");
        var lpg = probeGroup.AddComponent<LightProbeGroup>();
        
        var positions = new System.Collections.Generic.List<Vector3>();
        
        int xCount = Mathf.RoundToInt(areaSize.x / gridSpacing) + 1;
        int zCount = Mathf.RoundToInt(areaSize.z / gridSpacing) + 1;
        
        for (int layer = 0; layer < heightLayers; layer++)
        {
            float y = heightOffset + layer * (areaSize.y / Mathf.Max(1, heightLayers - 1));
            
            for (int xi = 0; xi < xCount; xi++)
            {
                for (int zi = 0; zi < zCount; zi++)
                {
                    float x = -areaSize.x * 0.5f + xi * gridSpacing;
                    float z = -areaSize.z * 0.5f + zi * gridSpacing;
                    
                    // 做射线检测，剔除在几何体内部的探针
                    var pos = new Vector3(x, y, z);
                    if (!IsInsideGeometry(pos))
                    {
                        positions.Add(pos);
                    }
                }
            }
        }
        
        lpg.probePositions = positions.ToArray();
        Debug.Log($"已放置 {positions.Count} 个光照探针");
        
        // 烘焙
        Lightmapping.BakeAsync();
    }
    
    private bool IsInsideGeometry(Vector3 pos)
    {
        // 向6个方向做射线检测，若全部碰撞则在几何体内部
        Vector3[] dirs = { Vector3.up, Vector3.down, Vector3.left, Vector3.right, Vector3.forward, Vector3.back };
        int hitCount = 0;
        foreach (var dir in dirs)
        {
            if (Physics.Raycast(pos, dir, 0.3f))
                hitCount++;
        }
        return hitCount >= 4;
    }
}
```

### 3.2 运行时光照探针采样

```csharp
// 手动查询光照探针（适用于特殊效果，如法术光效随环境光变色）
using UnityEngine;
using UnityEngine.Rendering;

public class EnvironmentLightSampler : MonoBehaviour
{
    [SerializeField] private Renderer targetRenderer;
    [SerializeField] private float updateInterval = 0.5f;  // 每0.5秒更新一次
    
    private SphericalHarmonicsL2 sh;
    private MaterialPropertyBlock mpb;
    private float lastUpdateTime;
    
    private void Start()
    {
        mpb = new MaterialPropertyBlock();
    }
    
    private void Update()
    {
        if (Time.time - lastUpdateTime < updateInterval) return;
        lastUpdateTime = Time.time;
        
        SampleEnvironmentLight();
    }
    
    private void SampleEnvironmentLight()
    {
        // 采样当前位置的 SH 光照
        LightProbes.GetInterpolatedProbe(transform.position, targetRenderer, out sh);
        
        // 提取主方向光颜色（近似）
        Color ambientColor = ExtractAmbientColorFromSH(sh);
        
        // 应用到材质
        targetRenderer.GetPropertyBlock(mpb);
        mpb.SetColor("_EnvironmentColor", ambientColor);
        targetRenderer.SetPropertyBlock(mpb);
    }
    
    private Color ExtractAmbientColorFromSH(SphericalHarmonicsL2 sh)
    {
        // 从 SH 中提取6个方向的光照并平均
        Vector3[] directions = 
        {
            Vector3.up, Vector3.down, 
            Vector3.right, Vector3.left, 
            Vector3.forward, Vector3.back
        };
        
        Color[] colors = new Color[6];
        sh.Evaluate(directions, colors);
        
        Color average = Color.black;
        foreach (var c in colors)
            average += c;
        average /= 6f;
        
        return average;
    }
    
    // 获取 SH 系数并传给 GPU（用于自定义着色器）
    public void ApplySHToMaterial(Material mat)
    {
        LightProbes.GetInterpolatedProbe(transform.position, targetRenderer, out sh);
        
        // Unity 标准 SH 系数传递
        MaterialPropertyBlock block = new MaterialPropertyBlock();
        
        // 将 SH 分解为着色器可用的常量
        // unity_SHAr/unity_SHAg/unity_SHAb = L1 系数
        // unity_SHBr/unity_SHBg/unity_SHBb = L2 系数
        // unity_SHC = L2 剩余系数
        
        for (int channelIdx = 0; channelIdx < 3; channelIdx++)
        {
            var vec = new Vector4(sh[channelIdx, 3], sh[channelIdx, 1], sh[channelIdx, 2], sh[channelIdx, 0] - sh[channelIdx, 6]);
            block.SetVector(channelIdx == 0 ? "unity_SHAr" : channelIdx == 1 ? "unity_SHAg" : "unity_SHAb", vec);
        }
        
        targetRenderer.SetPropertyBlock(block);
    }
}
```

### 3.3 LPPV（光照探针代理体积）

LPPV（Light Probe Proxy Volume）适用于体积较大的动态物体（如大型角色、车辆）：

```csharp
// LPPV 配置最佳实践
using UnityEngine;

[RequireComponent(typeof(LightProbeProxyVolume))]
public class LPPVController : MonoBehaviour
{
    private LightProbeProxyVolume lppv;
    
    private void Awake()
    {
        lppv = GetComponent<LightProbeProxyVolume>();
        ConfigureLPPV();
    }
    
    private void ConfigureLPPV()
    {
        // 分辨率模式
        lppv.resolutionMode = LightProbeProxyVolume.ResolutionMode.Automatic;
        
        // 探针位置刷新频率
        lppv.refreshMode = LightProbeProxyVolume.RefreshMode.EveryFrame;  // 动态对象用每帧
        // lppv.refreshMode = LightProbeProxyVolume.RefreshMode.ViaScripting;  // 手动控制
        
        // 数据格式
        lppv.dataFormat = LightProbeProxyVolume.DataFormat.HalfFloat;  // 移动端省内存
        
        // 边界设置（包围整个角色）
        var bounds = GetComponentInChildren<SkinnedMeshRenderer>()?.bounds ?? 
                     new Bounds(Vector3.zero, Vector3.one * 2f);
        lppv.boundingBoxOrigin = transform.InverseTransformPoint(bounds.center);
        lppv.sizeCustom = bounds.size * 1.2f;  // 略大于模型边界
    }
    
    // 低性能设备优化：降低刷新频率
    public void SetLowQualityMode()
    {
        lppv.refreshMode = LightProbeProxyVolume.RefreshMode.ViaScripting;
        InvokeRepeating(nameof(ManualRefresh), 0f, 1f);  // 每秒刷新一次
    }
    
    private void ManualRefresh()
    {
        lppv.Update();
    }
}
```

---

## 四、实时全局光照方案

### 4.1 屏幕空间全局光照（SSGI）

SSGI 基于已渲染的 G-Buffer 信息计算间接光，是目前移动端最实用的实时 GI 方案之一：

```hlsl
// SSGI Shader 核心算法（URP）
Shader "Hidden/SSGI"
{
    HLSLINCLUDE
    #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
    #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"
    
    TEXTURE2D(_GBuffer0);   // Albedo + Occlusion
    TEXTURE2D(_GBuffer1);   // Specular + Smoothness  
    TEXTURE2D(_GBuffer2);   // World Normal + (unused)
    TEXTURE2D(_CameraColorTexture);  // 前一帧颜色
    
    SAMPLER(sampler_GBuffer0);
    SAMPLER(sampler_CameraColorTexture);
    
    int _SampleCount;       // 光线采样数
    float _MaxDistance;     // 最大追踪距离
    float _Thickness;       // 几何体厚度（防止漏光）
    float _IndirectIntensity;
    
    // 重建世界坐标
    float3 ReconstructWorldPos(float2 uv, float depth)
    {
        float4 clipPos = float4(uv * 2.0 - 1.0, depth, 1.0);
        #if UNITY_UV_STARTS_AT_TOP
        clipPos.y = -clipPos.y;
        #endif
        float4 worldPos = mul(unity_MatrixInvVP, clipPos);
        return worldPos.xyz / worldPos.w;
    }
    
    // Ray-March 屏幕空间光线追踪
    bool RayMarch(float3 origin, float3 dir, int steps, out float2 hitUV)
    {
        hitUV = 0;
        float stepSize = _MaxDistance / steps;
        float3 pos = origin;
        
        for (int i = 0; i < steps; i++)
        {
            pos += dir * stepSize;
            
            // 投影到屏幕空间
            float4 clipPos = mul(UNITY_MATRIX_VP, float4(pos, 1.0));
            float2 screenUV = clipPos.xy / clipPos.w * 0.5 + 0.5;
            
            // 检查是否越界
            if (screenUV.x < 0 || screenUV.x > 1 || screenUV.y < 0 || screenUV.y > 1)
                return false;
            
            // 采样深度
            float sceneDepth = LinearEyeDepth(SampleSceneDepth(screenUV), _ZBufferParams);
            float rayDepth = -mul(UNITY_MATRIX_V, float4(pos, 1.0)).z;
            
            float diff = rayDepth - sceneDepth;
            if (diff > 0 && diff < _Thickness)
            {
                hitUV = screenUV;
                return true;
            }
        }
        return false;
    }
    
    // 余弦重要性采样（半球漫反射采样）
    float3 CosineSampleHemisphere(float2 randUV, float3 normal)
    {
        float phi = 2.0 * 3.14159 * randUV.x;
        float cosTheta = sqrt(randUV.y);
        float sinTheta = sqrt(1.0 - randUV.y);
        
        float3 tangent, bitangent;
        if (abs(normal.y) < 0.999)
        {
            tangent = normalize(cross(float3(0, 1, 0), normal));
        }
        else
        {
            tangent = normalize(cross(float3(1, 0, 0), normal));
        }
        bitangent = cross(normal, tangent);
        
        return tangent * (sinTheta * cos(phi)) 
             + bitangent * (sinTheta * sin(phi)) 
             + normal * cosTheta;
    }
    
    ENDHLSL
    
    SubShader
    {
        Pass
        {
            Name "SSGI"
            Cull Off ZWrite Off ZTest Always
            
            HLSLPROGRAM
            #pragma vertex vert_full_screen
            #pragma fragment frag
            
            float4 frag(Varyings input) : SV_Target
            {
                float2 uv = input.texcoord;
                
                // 获取当前像素信息
                float depth = SampleSceneDepth(uv);
                if (depth == 0) return 0;  // 天空盒跳过
                
                float3 worldPos = ReconstructWorldPos(uv, depth);
                float3 worldNormal = SAMPLE_TEXTURE2D(_GBuffer2, sampler_GBuffer0, uv).rgb * 2 - 1;
                float3 albedo = SAMPLE_TEXTURE2D(_GBuffer0, sampler_GBuffer0, uv).rgb;
                
                // 累积间接光
                float3 indirectLight = 0;
                float validSamples = 0;
                
                for (int i = 0; i < _SampleCount; i++)
                {
                    // 低差异序列采样（Halton）
                    float2 randUV = float2(
                        frac(i * 0.618034f),           // 黄金比例
                        frac(i * 0.381966f + 0.5f)
                    );
                    
                    float3 rayDir = CosineSampleHemisphere(randUV, worldNormal);
                    
                    float2 hitUV;
                    if (RayMarch(worldPos + worldNormal * 0.05, rayDir, 16, out hitUV))
                    {
                        float3 hitColor = SAMPLE_TEXTURE2D(_CameraColorTexture, sampler_CameraColorTexture, hitUV).rgb;
                        indirectLight += hitColor;
                        validSamples++;
                    }
                }
                
                if (validSamples > 0)
                    indirectLight /= validSamples;
                
                // 与 Albedo 相乘模拟颜色渗透
                indirectLight *= albedo * _IndirectIntensity;
                
                return float4(indirectLight, 1.0);
            }
            ENDHLSL
        }
    }
}
```

### 4.2 动态漫反射 GI（DDGI）

DDGI（Dynamic Diffuse Global Illumination）使用探针网格 + 光线追踪，适用于主机/高端 PC：

```csharp
// DDGI 系统管理器（概念实现，需 DXR 或 Vulkan RT 支持）
using UnityEngine;
using UnityEngine.Rendering;

public class DDGIManager : MonoBehaviour
{
    [Header("探针网格设置")]
    [SerializeField] private Vector3Int probeGridDimensions = new Vector3Int(16, 4, 16);
    [SerializeField] private float probeSpacing = 2.0f;
    [SerializeField] private int raysPerProbe = 128;      // 每探针光线数
    [SerializeField] private int irradianceTextureSize = 8;  // 辐照度图分辨率（每探针）
    [SerializeField] private float maxRayDistance = 20f;
    
    [Header("更新策略")]
    [SerializeField] private int probeUpdatesPerFrame = 64;  // 每帧更新的探针数
    [SerializeField] private float hysteresisBlend = 0.02f;  // 时间滤波（防止闪烁）
    
    private RenderTexture irradianceAtlas;   // 辐照度贴图集
    private RenderTexture visibilityAtlas;   // 可见性/距离贴图
    private ComputeShader ddgiCompute;
    
    private void Awake()
    {
        InitializeProbeAtlas();
    }
    
    private void InitializeProbeAtlas()
    {
        int totalProbes = probeGridDimensions.x * probeGridDimensions.y * probeGridDimensions.z;
        int atlasWidth = Mathf.CeilToInt(Mathf.Sqrt(totalProbes)) * irradianceTextureSize;
        
        // 辐照度贴图（RGB16F = HDR 颜色）
        irradianceAtlas = new RenderTexture(atlasWidth, atlasWidth, 0, RenderTextureFormat.RGB111110Float);
        irradianceAtlas.enableRandomWrite = true;
        irradianceAtlas.Create();
        
        // 可见性贴图（R = 平均距离，G = 距离平方均值，用于软阴影）
        visibilityAtlas = new RenderTexture(atlasWidth * 2, atlasWidth * 2, 0, RenderTextureFormat.RGHalf);
        visibilityAtlas.enableRandomWrite = true;
        visibilityAtlas.Create();
        
        // 传递给全局着色器
        Shader.SetGlobalTexture("_DDGIIrradiance", irradianceAtlas);
        Shader.SetGlobalTexture("_DDGIVisibility", visibilityAtlas);
        Shader.SetGlobalVector("_DDGIGridDimensions", new Vector4(
            probeGridDimensions.x, probeGridDimensions.y, probeGridDimensions.z, 0));
        Shader.SetGlobalFloat("_DDGIProbeSpacing", probeSpacing);
        Shader.SetGlobalVector("_DDGIGridOrigin", transform.position - 
            new Vector3(probeGridDimensions.x, probeGridDimensions.y, probeGridDimensions.z) 
            * probeSpacing * 0.5f);
    }
    
    private void Update()
    {
        // 分帧更新探针（避免单帧峰值）
        UpdateProbes();
        
        // 可视化调试
        if (Application.isEditor)
            DebugDrawProbeGrid();
    }
    
    private void UpdateProbes()
    {
        if (ddgiCompute == null) return;
        
        // 1. 光线追踪（在 GPU 上为每个探针发射射线）
        ddgiCompute.SetInt("_RaysPerProbe", raysPerProbe);
        ddgiCompute.SetFloat("_MaxRayDistance", maxRayDistance);
        ddgiCompute.SetFloat("_Hysteresis", hysteresisBlend);
        ddgiCompute.Dispatch(0,  // Kernel: RayTrace
            Mathf.CeilToInt(probeUpdatesPerFrame / 64f), 1, 1);
        
        // 2. 更新辐照度（从光线结果中提取 Irradiance，使用 Octahedral Encoding）
        ddgiCompute.Dispatch(1,  // Kernel: UpdateIrradiance
            Mathf.CeilToInt(probeUpdatesPerFrame * irradianceTextureSize * irradianceTextureSize / 64f), 1, 1);
        
        // 3. 更新可见性
        ddgiCompute.Dispatch(2,  // Kernel: UpdateVisibility
            Mathf.CeilToInt(probeUpdatesPerFrame * irradianceTextureSize * 2 * irradianceTextureSize * 2 / 64f), 1, 1);
    }
    
    private void DebugDrawProbeGrid()
    {
        var origin = (Vector3)transform.position - 
            new Vector3(probeGridDimensions.x, probeGridDimensions.y, probeGridDimensions.z) * probeSpacing * 0.5f;
        
        for (int x = 0; x < probeGridDimensions.x; x++)
        for (int y = 0; y < probeGridDimensions.y; y++)
        for (int z = 0; z < probeGridDimensions.z; z++)
        {
            var pos = origin + new Vector3(x, y, z) * probeSpacing;
            Debug.DrawRay(pos, Vector3.up * 0.3f, Color.yellow);
        }
    }
}
```

---

## 五、混合 GI 策略与移动端优化

### 5.1 分级 GI 策略

```csharp
// GI 质量分级管理器
using UnityEngine;
using UnityEngine.Rendering;

public enum GIQualityLevel
{
    Mobile_Low,      // 仅烘焙 Lightmap + 低精度 SH 探针
    Mobile_Medium,   // 烘焙 + LPPV + 实时阴影
    PC_High,         // SSGI + 完整探针系统
    Console_Ultra    // DDGI + 光线追踪
}

public class GIQualityManager : MonoBehaviour
{
    [SerializeField] private GIQualityLevel targetQuality = GIQualityLevel.Mobile_Medium;
    
    [Header("实时GI组件")]
    [SerializeField] private MonoBehaviour ssgiRenderer;
    [SerializeField] private ReflectionProbe[] reflectionProbes;
    [SerializeField] private LightProbeProxyVolume[] lppvList;
    
    private static GIQualityManager _instance;
    public static GIQualityManager Instance => _instance;
    
    private void Awake()
    {
        _instance = this;
        // 根据设备性能自动选择等级
        targetQuality = DetectOptimalQuality();
        ApplyGIQuality(targetQuality);
    }
    
    private GIQualityLevel DetectOptimalQuality()
    {
        // 根据 GPU Tier 自动分级
        switch (Graphics.activeTier)
        {
            case GraphicsTier.Tier1:
                return GIQualityLevel.Mobile_Low;
            case GraphicsTier.Tier2:
                return GIQualityLevel.Mobile_Medium;
            case GraphicsTier.Tier3:
                return SystemInfo.graphicsDeviceType == GraphicsDeviceType.PlayStation5 ||
                       SystemInfo.graphicsDeviceType == GraphicsDeviceType.XboxSeriesX
                    ? GIQualityLevel.Console_Ultra
                    : GIQualityLevel.PC_High;
            default:
                return GIQualityLevel.Mobile_Low;
        }
    }
    
    public void ApplyGIQuality(GIQualityLevel level)
    {
        switch (level)
        {
            case GIQualityLevel.Mobile_Low:
                SetMobileLow();
                break;
            case GIQualityLevel.Mobile_Medium:
                SetMobileMedium();
                break;
            case GIQualityLevel.PC_High:
                SetPCHigh();
                break;
            case GIQualityLevel.Console_Ultra:
                SetConsoleUltra();
                break;
        }
    }
    
    private void SetMobileLow()
    {
        // 关闭实时 GI
        DynamicGI.updateThreshold = float.MaxValue;  // 禁用动态更新
        
        // 禁用 SSGI
        if (ssgiRenderer != null) ssgiRenderer.enabled = false;
        
        // 最简 LPPV
        foreach (var lppv in lppvList)
        {
            lppv.refreshMode = LightProbeProxyVolume.RefreshMode.ViaScripting;
        }
        
        // 反射探针仅用烘焙
        foreach (var rp in reflectionProbes)
        {
            rp.mode = ReflectionProbeMode.Baked;
            rp.refreshMode = ReflectionProbeRefreshMode.ViaScripting;
        }
        
        // 环境光仅用 SH（L1 精度）
        RenderSettings.ambientMode = AmbientMode.Skybox;
        Debug.Log("[GI] 切换到 Mobile_Low 模式");
    }
    
    private void SetMobileMedium()
    {
        DynamicGI.updateThreshold = 0.5f;
        if (ssgiRenderer != null) ssgiRenderer.enabled = false;
        
        foreach (var lppv in lppvList)
        {
            lppv.refreshMode = LightProbeProxyVolume.RefreshMode.EveryFrame;
            lppv.dataFormat = LightProbeProxyVolume.DataFormat.HalfFloat;
        }
        
        foreach (var rp in reflectionProbes)
        {
            rp.mode = ReflectionProbeMode.Realtime;
            rp.refreshMode = ReflectionProbeRefreshMode.OnAwake;
            rp.timeSlicingMode = ReflectionProbeTimeSlicingMode.AllFacesAtOnce;
        }
        
        Debug.Log("[GI] 切换到 Mobile_Medium 模式");
    }
    
    private void SetPCHigh()
    {
        DynamicGI.updateThreshold = 0.1f;
        if (ssgiRenderer != null) ssgiRenderer.enabled = true;
        
        foreach (var rp in reflectionProbes)
        {
            rp.mode = ReflectionProbeMode.Realtime;
            rp.refreshMode = ReflectionProbeRefreshMode.EveryFrame;
            rp.timeSlicingMode = ReflectionProbeTimeSlicingMode.IndividualFaces;
        }
        
        Debug.Log("[GI] 切换到 PC_High 模式");
    }
    
    private void SetConsoleUltra()
    {
        SetPCHigh();
        // 开启 DDGI（需要硬件 RT 支持）
        // ddgiManager.enabled = true;
        Debug.Log("[GI] 切换到 Console_Ultra 模式");
    }
}
```

### 5.2 Lightmap 内存优化

```csharp
// Lightmap 内存精细管理
using UnityEngine;
using System.Collections.Generic;

public class LightmapMemoryManager : MonoBehaviour
{
    [SerializeField] private bool useHalfResolutionOnMobile = true;
    [SerializeField] private bool unloadUnusedLightmaps = true;
    
    // 按场景区域分块管理光照贴图
    private Dictionary<string, LightmapData[]> regionLightmaps = new Dictionary<string, LightmapData[]>();
    private HashSet<string> loadedRegions = new HashSet<string>();
    
    public void LoadRegionLightmaps(string regionName)
    {
        if (loadedRegions.Contains(regionName)) return;
        
        // 从 AssetBundle 按需加载
        string bundlePath = $"lightmaps/{regionName}";
        // AssetBundle bundle = AssetBundle.LoadFromFile(bundlePath);
        // var lightmaps = bundle.LoadAllAssets<Texture2D>();
        // regionLightmaps[regionName] = BuildLightmapData(lightmaps);
        
        loadedRegions.Add(regionName);
        Debug.Log($"[Lightmap] 已加载区域 {regionName} 的光照贴图");
    }
    
    public void UnloadRegionLightmaps(string regionName)
    {
        if (!loadedRegions.Contains(regionName)) return;
        
        if (regionLightmaps.TryGetValue(regionName, out var lightmaps))
        {
            foreach (var lm in lightmaps)
            {
                if (lm.lightmapColor != null)
                    Destroy(lm.lightmapColor);
                if (lm.lightmapDir != null)
                    Destroy(lm.lightmapDir);
            }
            regionLightmaps.Remove(regionName);
        }
        
        loadedRegions.Remove(regionName);
        Resources.UnloadUnusedAssets();
        Debug.Log($"[Lightmap] 已卸载区域 {regionName} 的光照贴图，释放显存");
    }
    
    // 半分辨率降级（移动端省显存）
    public Texture2D DownscaleLightmap(Texture2D original, int targetSize)
    {
        var rt = RenderTexture.GetTemporary(targetSize, targetSize, 0, RenderTextureFormat.RGB111110Float);
        Graphics.Blit(original, rt);
        
        var result = new Texture2D(targetSize, targetSize, TextureFormat.RGBAHalf, false);
        var prevRT = RenderTexture.active;
        RenderTexture.active = rt;
        result.ReadPixels(new Rect(0, 0, targetSize, targetSize), 0, 0);
        result.Apply(false, true);  // makeNoLongerReadable = true（节省内存）
        RenderTexture.active = prevRT;
        
        RenderTexture.ReleaseTemporary(rt);
        return result;
    }
}
```

---

## 六、GI 调试与性能分析

### 6.1 GI 可视化调试工具

```csharp
// GI 调试工具（Editor Only）
#if UNITY_EDITOR
using UnityEditor;
using UnityEngine;

public class GIDebugVisualizer : EditorWindow
{
    private enum DebugMode { Irradiance, Albedo, Normal, Occlusion, SHProbes }
    private DebugMode currentMode = DebugMode.Irradiance;
    
    [MenuItem("Tools/GI/GI Debug Visualizer")]
    static void ShowWindow()
    {
        GetWindow<GIDebugVisualizer>("GI 调试工具");
    }
    
    private void OnGUI()
    {
        GUILayout.Label("GI 调试可视化", EditorStyles.boldLabel);
        
        var newMode = (DebugMode)EditorGUILayout.EnumPopup("调试模式", currentMode);
        if (newMode != currentMode)
        {
            currentMode = newMode;
            ApplyDebugMode(currentMode);
        }
        
        GUILayout.Space(10);
        GUILayout.Label("光照贴图信息", EditorStyles.boldLabel);
        
        var lightmaps = LightmapSettings.lightmaps;
        GUILayout.Label($"光照贴图数量: {lightmaps.Length}");
        
        for (int i = 0; i < lightmaps.Length; i++)
        {
            var lm = lightmaps[i];
            if (lm.lightmapColor != null)
            {
                GUILayout.Label($"  [{i}] {lm.lightmapColor.width}x{lm.lightmapColor.height} " +
                               $"({lm.lightmapColor.format}) " +
                               $"{GetTextureSizeMB(lm.lightmapColor):F1} MB");
            }
        }
        
        GUILayout.Space(10);
        if (GUILayout.Button("分析场景 GI 覆盖率"))
            AnalyzeGICoverage();
            
        if (GUILayout.Button("重置调试模式"))
            ApplyDebugMode(DebugMode.Irradiance);
    }
    
    private void ApplyDebugMode(DebugMode mode)
    {
        switch (mode)
        {
            case DebugMode.Irradiance:
                Shader.DisableKeyword("DEBUG_ALBEDO");
                Shader.DisableKeyword("DEBUG_NORMAL");
                break;
            case DebugMode.Albedo:
                Shader.EnableKeyword("DEBUG_ALBEDO");
                break;
            case DebugMode.Normal:
                Shader.EnableKeyword("DEBUG_NORMAL");
                break;
            case DebugMode.SHProbes:
                DrawSHProbeColors();
                break;
        }
    }
    
    private void DrawSHProbeColors()
    {
        var probeGroups = FindObjectsOfType<LightProbeGroup>();
        foreach (var group in probeGroups)
        {
            foreach (var pos in group.probePositions)
            {
                var worldPos = group.transform.TransformPoint(pos);
                LightProbes.GetInterpolatedProbe(worldPos, null, out var sh);
                
                // 采样向上方向的颜色作为代表色
                var dirs = new[] { Vector3.up };
                var colors = new Color[1];
                sh.Evaluate(dirs, colors);
                
                // 绘制彩色球体标记
                Handles.color = colors[0];
                Handles.SphereHandleCap(0, worldPos, Quaternion.identity, 0.2f, EventType.Repaint);
            }
        }
        SceneView.RepaintAll();
    }
    
    private float GetTextureSizeMB(Texture2D tex)
    {
        // 估算纹理内存占用
        var width = tex.width;
        var height = tex.height;
        float bpp = tex.format == TextureFormat.BC6H ? 1f :
                    tex.format == TextureFormat.RGBAHalf ? 8f : 4f;
        return (width * height * bpp) / (1024f * 1024f);
    }
    
    private void AnalyzeGICoverage()
    {
        var renderers = FindObjectsOfType<Renderer>();
        int staticCount = 0, dynamicCount = 0, noCoverageCount = 0;
        
        foreach (var r in renderers)
        {
            var go = r.gameObject;
            if ((GameObjectUtility.GetStaticEditorFlags(go) & StaticEditorFlags.ContributeGI) != 0)
                staticCount++;
            else if (r.lightmapIndex >= 0 && r.lightmapIndex < LightmapSettings.lightmaps.Length)
                staticCount++;
            else if (FindObjectsOfType<LightProbeGroup>().Length > 0)
                dynamicCount++;
            else
                noCoverageCount++;
        }
        
        Debug.Log($"[GI 覆盖率分析]\n" +
                  $"  静态对象（Lightmap）: {staticCount}\n" +
                  $"  动态对象（探针）: {dynamicCount}\n" +
                  $"  无 GI 覆盖: {noCoverageCount}");
    }
}
#endif
```

---

## 七、最佳实践总结

### 7.1 GI 技术选型建议

```
移动端（中低端）：
  ✅ 静态场景  → 烘焙 Lightmap（1024x1024, BC6H/ASTC LDR）
  ✅ 动态角色  → L2 SH 光照探针（网格密度 2~4m）
  ✅ 大型动态体 → LPPV（每秒1次刷新）
  ❌ 避免      → 实时反射探针每帧刷新

移动端（高端，如 Apple A16/M 系列）：
  ✅ 烘焙 Lightmap + Screen Space AO
  ✅ 基于 Metal 的轻量级 SSGI
  ✅ 反射探针定时刷新（每 0.5s）

PC / 主机：
  ✅ 完整 GI Pipeline：Lightmap + SSGI + 反射探针每帧刷新
  ✅ DX12 / Vulkan 硬件光追 → RTGI / DDGI
  ✅ Lumen（UE5 独有）
```

### 7.2 常见问题与解决方案

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 光照接缝/漏光 | Lightmap UV 间距不足 | 增大 UV Margin，提升 `bakeResolution` |
| 动态对象与背景光照不匹配 | 探针密度不足 | 在光照变化区域增加探针密度 |
| Lightmap 烘焙噪点 | 采样数不足 | 提升 `indirectSampleCount`（512→1024） |
| LPPV 闪烁 | 刷新过快/Hysteresis 不足 | 增大 Hysteresis 或改为每秒1次刷新 |
| 烘焙场景动态物体黑色 | 未放置探针 | 添加 LightProbeGroup，确保覆盖动态对象路径 |
| Lightmap 内存占用过高 | 贴图尺寸/精度过高 | 移动端改用 ASTC 压缩，降低 `maxAtlasSize` |

### 7.3 核心优化数据参考

| 质量级别 | Lightmap 尺寸 | 探针密度 | 反射探针 | 参考显存占用 |
|---------|------------|---------|---------|------------|
| 移动低端 | 512×512 ×2 | 4m 网格 | 仅烘焙 | ~8 MB |
| 移动中端 | 1024×1024 ×4 | 2m 网格 | 定时刷新 | ~32 MB |
| PC 高品质 | 2048×2048 ×8 | 1m 网格 | 每帧刷新 | ~128 MB |
| 主机超高 | 4096×4096 ×16 | 1m + DDGI | 全实时 | ~512 MB |

---

## 结语

全局光照是游戏画面质量的核心决定因素之一。实际商业项目中，通常采用**烘焙 GI + 动态探针**的混合方案，在画质与性能之间取得平衡。随着移动 GPU 算力的提升（Metal 3、Vulkan Ray Query），实时 GI 在移动端的应用也将逐渐普及。掌握从 Lightmap UV 烘焙到 DDGI 光线追踪的完整技术栈，是游戏图形工程师进阶的必经之路。
