---
title: 游戏球谐函数与Light Probe系统深度实践：从IBL到APV完全指南
published: 2026-04-13
description: 深入解析球谐函数（Spherical Harmonics）在游戏光照中的数学原理与工程实践，涵盖Light Probe烘焙、IBL基于图像的光照、Adaptive Probe Volume（APV）动态GI系统，结合Unity URP完整代码实现。
tags: [球谐函数, Light Probe, IBL, APV, 全局光照, URP, 渲染]
category: 渲染技术
draft: false
---

# 游戏球谐函数与Light Probe系统深度实践：从IBL到APV完全指南

## 前言

在实时渲染中，间接光照（Indirect Lighting）是场景视觉质量的核心要素。烘焙光照贴图虽然高效，却无法处理动态物体的间接光。球谐函数（Spherical Harmonics, SH）提供了一种极其高效的方式，用极少的系数存储低频环境光信息，配合 Unity 的 Light Probe 与 Adaptive Probe Volume（APV）系统，可以实现动态物体的高质量实时间接光照。

本文将从数学原理出发，深入讲解 SH 的编码/解码、Light Probe 烘焙流程、IBL（Image-Based Lighting）实现，以及 Unity 6 中全新的 Adaptive Probe Volume 系统。

---

## 一、球谐函数数学基础

### 1.1 什么是球谐函数

球谐函数是定义在单位球面上的一组正交基函数，类似于傅里叶变换在频域的基函数，但针对球面信号。

数学定义：
$$Y_l^m(\theta, \phi) = \sqrt{\frac{(2l+1)(l-|m|)!}{4\pi(l+|m|)!}} P_l^{|m|}(\cos\theta) e^{im\phi}$$

其中 $l$ 为阶数（band），$m \in [-l, l]$，$P_l^m$ 为勒让德多项式。

**实球谐函数（Real SH）**在游戏中更常用：

| 阶 | 系数数量 | 用途 |
|---|---|---|
| L0 | 1 | 常量环境光 |
| L1 | 3 | 一阶漫反射（方向光近似） |
| L2 | 5 | 二阶漫反射（软阴影、色偏） |

前3阶共 **9个系数**（L0+L1+L2），足以编码大多数游戏场景的低频漫反射光照信息。

### 1.2 SH投影与重建

将环境光 $L(\omega)$ 投影到 SH 基函数：

$$c_l^m = \int_{\Omega} L(\omega) Y_l^m(\omega) d\omega$$

重建时直接用系数线性组合：

$$\hat{L}(\omega) \approx \sum_{l=0}^{n}\sum_{m=-l}^{l} c_l^m Y_l^m(\omega)$$

对于漫反射光照，法线方向 $\mathbf{n}$ 下的辐照度：

$$E(\mathbf{n}) \approx \sum_{i=0}^{8} A_i c_i Y_i(\mathbf{n})$$

其中 $A_i$ 是预计算的 ZH（Zonal Harmonics）系数，用于卷积余弦核。

---

## 二、Unity Light Probe 系统

### 2.1 Light Probe 工作原理

Light Probe 在空间中的采样点存储 L0-L2 球谐系数（共 27 个 float，3通道×9系数），运行时通过四面体插值（Tetrahedral Interpolation）为动态物体提供近似环境光。

```csharp
// Unity 内置 SH 系数访问
using UnityEngine;
using UnityEngine.Rendering;

public class LightProbeDebugger : MonoBehaviour
{
    [Header("调试显示")]
    public bool showProbeGizmos = true;
    public float probeRadius = 0.1f;

    private SphericalHarmonicsL2 _currentSH;
    private Vector3[] _sampleDirections;
    private Color[] _sampledColors;

    void Start()
    {
        // 预生成采样方向（正十二面体分布，更均匀）
        _sampleDirections = GenerateIcosahedronDirections(12);
        _sampledColors = new Color[_sampleDirections.Length];
    }

    void Update()
    {
        // 获取当前位置的 Light Probe SH 系数
        LightProbes.GetInterpolatedProbe(transform.position, GetComponent<Renderer>(), out _currentSH);
        
        // 用 SH 采样各方向光照
        _currentSH.Evaluate(_sampleDirections, _sampledColors);
        
        // 提取主光照方向（L1 系数方向）
        Vector3 dominantDir = ExtractDominantLightDirection(_currentSH);
        Debug.DrawRay(transform.position, dominantDir * 2f, Color.yellow);
    }

    /// <summary>
    /// 从 SH L1 系数提取主光照方向
    /// L1 系数：sh[0,1]=Y1-1, sh[0,2]=Y10, sh[0,3]=Y11（对应 XYZ 方向）
    /// </summary>
    private Vector3 ExtractDominantLightDirection(SphericalHarmonicsL2 sh)
    {
        // L1 系数存储在索引 1,2,3
        Vector3 dir = new Vector3(
            sh[0, 3] - sh[0, 1],  // X: Y11 - Y1-1
            sh[1, 2],              // Y: Y10 (绿通道)
            sh[2, 1]               // Z
        );
        return dir.normalized;
    }

    /// <summary>
    /// 将 SH 系数编码为半精度，减少内存占用
    /// 27 个 float → 27 个 half，节省 50% 内存
    /// </summary>
    public static ushort[] CompressSHToHalf(SphericalHarmonicsL2 sh)
    {
        var result = new ushort[27];
        int idx = 0;
        for (int rgb = 0; rgb < 3; rgb++)
        {
            for (int coeff = 0; coeff < 9; coeff++)
            {
                result[idx++] = Mathf.FloatToHalf(sh[rgb, coeff]);
            }
        }
        return result;
    }

    private Vector3[] GenerateIcosahedronDirections(int count)
    {
        var dirs = new Vector3[count];
        float goldenAngle = Mathf.PI * (3f - Mathf.Sqrt(5f));
        for (int i = 0; i < count; i++)
        {
            float y = 1f - (i / (float)(count - 1)) * 2f;
            float r = Mathf.Sqrt(1f - y * y);
            float theta = goldenAngle * i;
            dirs[i] = new Vector3(Mathf.Cos(theta) * r, y, Mathf.Sin(theta) * r);
        }
        return dirs;
    }

    void OnDrawGizmosSelected()
    {
        if (!showProbeGizmos || _sampledColors == null) return;
        for (int i = 0; i < _sampleDirections.Length; i++)
        {
            Gizmos.color = _sampledColors[i];
            Gizmos.DrawSphere(transform.position + _sampleDirections[i] * 0.5f, probeRadius);
        }
    }
}
```

### 2.2 自定义 Light Probe 插值系统

Unity 的默认四面体插值在稀疏探针场景下效果较差，可以实现自定义插值：

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using System.Collections.Generic;
using Unity.Collections;
using Unity.Jobs;
using Unity.Burst;

/// <summary>
/// 高级 Light Probe 管理器：支持动态探针、距离加权插值、遮挡检测
/// </summary>
public class AdvancedLightProbeManager : MonoBehaviour
{
    [Header("探针配置")]
    public LightProbeGroup[] probeGroups;
    public float probeUpdateInterval = 0.1f;
    public LayerMask occlusionMask;
    
    [Header("插值配置")]
    public InterpolationMode interpolationMode = InterpolationMode.Tetrahedral;
    public int nearestProbeCount = 8; // 距离加权时使用的最近探针数
    
    public enum InterpolationMode { Tetrahedral, DistanceWeighted, OcclusionAware }

    private Vector3[] _probePositions;
    private SphericalHarmonicsL2[] _probeCoefficients;
    private Dictionary<int, (SphericalHarmonicsL2 sh, float lastUpdate)> _objectCache;

    void Awake()
    {
        _objectCache = new Dictionary<int, (SphericalHarmonicsL2, float)>();
        RefreshProbeData();
    }

    public void RefreshProbeData()
    {
        _probePositions = LightmapSettings.lightProbes?.positions ?? new Vector3[0];
        _probeCoefficients = LightmapSettings.lightProbes?.bakedProbes ?? new SphericalHarmonicsL2[0];
    }

    /// <summary>
    /// 遮挡感知插值：通过射线检测过滤被遮挡的探针
    /// </summary>
    public SphericalHarmonicsL2 GetOcclusionAwareSH(Vector3 worldPos)
    {
        if (_probePositions.Length == 0)
            return GetAmbientSH();

        var validProbes = new List<(SphericalHarmonicsL2 sh, float weight)>();
        float totalWeight = 0f;

        // 找最近的 N 个探针
        int[] nearestIndices = FindNearestProbes(worldPos, nearestProbeCount);
        
        foreach (int idx in nearestIndices)
        {
            Vector3 probePos = _probePositions[idx];
            Vector3 dir = probePos - worldPos;
            float dist = dir.magnitude;
            
            // 遮挡检测
            bool isOccluded = Physics.Raycast(worldPos, dir.normalized, dist, occlusionMask);
            if (isOccluded) continue;
            
            // 反距离权重
            float weight = 1f / (dist * dist + 0.001f);
            validProbes.Add((_probeCoefficients[idx], weight));
            totalWeight += weight;
        }

        if (validProbes.Count == 0)
            return _probeCoefficients[nearestIndices[0]]; // 降级到最近探针

        // 加权平均 SH 系数
        return BlendSH(validProbes, totalWeight);
    }

    private SphericalHarmonicsL2 BlendSH(
        List<(SphericalHarmonicsL2 sh, float weight)> probes, float totalWeight)
    {
        SphericalHarmonicsL2 result = default;
        foreach (var (sh, weight) in probes)
        {
            float normalizedWeight = weight / totalWeight;
            for (int rgb = 0; rgb < 3; rgb++)
            {
                for (int coeff = 0; coeff < 9; coeff++)
                {
                    result[rgb, coeff] += sh[rgb, coeff] * normalizedWeight;
                }
            }
        }
        return result;
    }

    private int[] FindNearestProbes(Vector3 pos, int count)
    {
        count = Mathf.Min(count, _probePositions.Length);
        var distances = new (float dist, int idx)[_probePositions.Length];
        for (int i = 0; i < _probePositions.Length; i++)
            distances[i] = (Vector3.SqrMagnitude(_probePositions[i] - pos), i);
        
        System.Array.Sort(distances, (a, b) => a.dist.CompareTo(b.dist));
        
        var result = new int[count];
        for (int i = 0; i < count; i++)
            result[i] = distances[i].idx;
        return result;
    }

    private SphericalHarmonicsL2 GetAmbientSH()
    {
        SphericalHarmonicsL2 sh = default;
        // 用 RenderSettings.ambientLight 填充 L0
        Color ambient = RenderSettings.ambientLight;
        sh[0, 0] = ambient.r * 0.886f;
        sh[1, 0] = ambient.g * 0.886f;
        sh[2, 0] = ambient.b * 0.886f;
        return sh;
    }
}
```

---

## 三、基于图像的光照（IBL）实现

### 3.1 IBL 管线概述

IBL 通过预计算 Cubemap 来模拟真实世界的环境光照：

- **漫反射 IBL**：Irradiance Map（辐照度贴图），通常投影为 SH 系数
- **镜面反射 IBL**：Pre-filtered Environment Map（预过滤环境贴图）+ BRDF LUT

```hlsl
// URP IBL Shader 实现
#ifndef IBL_INCLUDED
#define IBL_INCLUDED

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

// =====================================================
// 漫反射 IBL：SH 辐照度
// 使用 Unity 内置的 SH 系数（unity_SHAr/Ag/Ab/Br/Bg/Bb/C）
// =====================================================
half3 SampleSHIrradiance(half3 normalWS)
{
    // L0+L1 快速路径（顶点着色器）
    half4 SHCoefficients[7];
    SHCoefficients[0] = unity_SHAr;
    SHCoefficients[1] = unity_SHAg;
    SHCoefficients[2] = unity_SHAb;
    SHCoefficients[3] = unity_SHBr;
    SHCoefficients[4] = unity_SHBg;
    SHCoefficients[5] = unity_SHBb;
    SHCoefficients[6] = unity_SHC;
    return max(half3(0,0,0), SampleSH9(SHCoefficients, normalWS));
}

// =====================================================
// 镜面反射 IBL：Pre-filtered Env Map + BRDF LUT
// =====================================================
TEXTURECUBE(_IBL_EnvMap);
SAMPLER(sampler_IBL_EnvMap);
TEXTURE2D(_IBL_BrdfLUT);
SAMPLER(sampler_IBL_BrdfLUT);
float _IBL_EnvMapMipCount;

// 重要性采样（仅用于离线预过滤，此处为实时版本近似）
half3 SamplePreFilteredEnvMap(half3 reflectDirWS, half roughness)
{
    // roughness → mip level（指数映射更均匀）
    float mipLevel = roughness * roughness * _IBL_EnvMapMipCount;
    return SAMPLE_TEXTURECUBE_LOD(_IBL_EnvMap, sampler_IBL_EnvMap, reflectDirWS, mipLevel).rgb;
}

// BRDF LUT 采样：x=NdotV, y=roughness → (scale, bias)
half2 SampleBrdfLUT(half NdotV, half roughness)
{
    return SAMPLE_TEXTURE2D(_IBL_BrdfLUT, sampler_IBL_BrdfLUT, half2(NdotV, roughness)).rg;
}

// =====================================================
// 完整 IBL PBR 光照计算
// =====================================================
half3 ComputeIBL(
    half3 normalWS,
    half3 viewDirWS,
    half3 albedo,
    half metallic,
    half roughness,
    half occlusion)
{
    half NdotV = saturate(dot(normalWS, viewDirWS));
    half3 reflectDirWS = reflect(-viewDirWS, normalWS);

    // F0 菲涅尔基准反射率
    half3 F0 = lerp(half3(0.04, 0.04, 0.04), albedo, metallic);
    
    // 菲涅尔-Schlick 近似（带粗糙度修正）
    half3 F_env = F0 + (max(half3(1-roughness, 1-roughness, 1-roughness), F0) - F0) 
                  * pow(1.0 - NdotV, 5.0);

    // 漫反射 IBL（SH辐照度）
    half3 irradiance = SampleSHIrradiance(normalWS);
    half3 kD = (1.0 - F_env) * (1.0 - metallic);
    half3 diffuseIBL = kD * albedo * irradiance * occlusion;

    // 镜面反射 IBL
    half3 prefilteredColor = SamplePreFilteredEnvMap(reflectDirWS, roughness);
    half2 brdf = SampleBrdfLUT(NdotV, roughness);
    half3 specularIBL = prefilteredColor * (F_env * brdf.x + brdf.y) * occlusion;

    return diffuseIBL + specularIBL;
}

#endif // IBL_INCLUDED
```

### 3.2 BRDF LUT 离线预计算

```csharp
using UnityEngine;
using UnityEngine.Rendering;

/// <summary>
/// 离线生成 GGX BRDF LUT 纹理（128x128，存储 (scale, bias)）
/// 原理：对 GGX 分布进行重要性采样，预积分 F0 的 scale 和 bias 分量
/// </summary>
public class BrdfLutGenerator : MonoBehaviour
{
    [Header("LUT 配置")]
    public int resolution = 128;
    public int sampleCount = 1024;
    public string savePath = "Assets/Textures/IBL_BrdfLUT.png";

    [ContextMenu("生成 BRDF LUT")]
    public void GenerateBrdfLut()
    {
        var tex = new Texture2D(resolution, resolution, TextureFormat.RGBAHalf, false);
        tex.filterMode = FilterMode.Bilinear;
        tex.wrapMode = TextureWrapMode.Clamp;

        for (int y = 0; y < resolution; y++)
        {
            float roughness = (y + 0.5f) / resolution;
            float roughness2 = roughness * roughness;

            for (int x = 0; x < resolution; x++)
            {
                float NdotV = (x + 0.5f) / resolution;
                var (scale, bias) = IntegrateBRDF(NdotV, roughness2);
                tex.SetPixel(x, y, new Color(scale, bias, 0, 1));
            }
        }

        tex.Apply();

#if UNITY_EDITOR
        byte[] png = tex.EncodeToPNG();
        System.IO.File.WriteAllBytes(savePath, png);
        UnityEditor.AssetDatabase.Refresh();
        Debug.Log($"BRDF LUT 已保存到: {savePath}");
#endif
        DestroyImmediate(tex);
    }

    // GGX 重要性采样积分
    private (float scale, float bias) IntegrateBRDF(float NdotV, float roughness2)
    {
        Vector3 V = new Vector3(Mathf.Sqrt(1f - NdotV * NdotV), 0f, NdotV);
        float scale = 0f, bias = 0f;

        for (int i = 0; i < sampleCount; i++)
        {
            Vector2 Xi = Hammersley(i, sampleCount);
            Vector3 H = ImportanceSampleGGX(Xi, roughness2);
            Vector3 L = 2f * Vector3.Dot(V, H) * H - V;

            float NdotL = Mathf.Max(L.z, 0f);
            float NdotH = Mathf.Max(H.z, 0f);
            float VdotH = Mathf.Max(Vector3.Dot(V, H), 0f);

            if (NdotL > 0f)
            {
                float G = G_Smith(NdotV, NdotL, roughness2);
                float G_vis = G * VdotH / (NdotH * NdotV + 1e-5f);
                float Fc = Mathf.Pow(1f - VdotH, 5f);
                scale += (1f - Fc) * G_vis;
                bias += Fc * G_vis;
            }
        }

        return (scale / sampleCount, bias / sampleCount);
    }

    private Vector2 Hammersley(int i, int N)
    {
        return new Vector2((float)i / N, RadicalInverse_VdC((uint)i));
    }

    private float RadicalInverse_VdC(uint bits)
    {
        bits = (bits << 16) | (bits >> 16);
        bits = ((bits & 0x55555555u) << 1) | ((bits & 0xAAAAAAAAu) >> 1);
        bits = ((bits & 0x33333333u) << 2) | ((bits & 0xCCCCCCCCu) >> 2);
        bits = ((bits & 0x0F0F0F0Fu) << 4) | ((bits & 0xF0F0F0F0u) >> 4);
        bits = ((bits & 0x00FF00FFu) << 8) | ((bits & 0xFF00FF00u) >> 8);
        return bits * 2.3283064365386963e-10f;
    }

    private Vector3 ImportanceSampleGGX(Vector2 Xi, float roughness2)
    {
        float a = roughness2 * roughness2;
        float phi = 2f * Mathf.PI * Xi.x;
        float cosTheta = Mathf.Sqrt((1f - Xi.y) / (1f + (a * a - 1f) * Xi.y));
        float sinTheta = Mathf.Sqrt(1f - cosTheta * cosTheta);
        return new Vector3(Mathf.Cos(phi) * sinTheta, Mathf.Sin(phi) * sinTheta, cosTheta);
    }

    private float G_Smith(float NdotV, float NdotL, float roughness2)
    {
        float k = roughness2 * roughness2 / 2f;
        float GV = NdotV / (NdotV * (1f - k) + k);
        float GL = NdotL / (NdotL * (1f - k) + k);
        return GV * GL;
    }
}
```

---

## 四、Adaptive Probe Volume（APV）

### 4.1 APV 核心概念

Unity 6 引入的 APV 是对传统 Light Probe Group 的革命性升级：

| 特性 | Light Probe Group | APV |
|---|---|---|
| 探针布局 | 手动放置 | 自动体积填充 |
| 插值 | 四面体（稀疏） | 体积采样（3D纹理） |
| 动态调整 | 不支持 | 支持运行时细化 |
| 内存 | 低 | 较高（但可流式加载） |
| 漏光处理 | 差 | 有效（虚拟偏移+校正） |

### 4.2 APV 运行时控制

```csharp
using UnityEngine;
using UnityEngine.Rendering;

#if UNITY_6000_0_OR_NEWER
using UnityEngine.Rendering.UnifiedRayTracing;
#endif

/// <summary>
/// APV 运行时控制器：动态调整探针密度、处理漏光、流式加载
/// </summary>
public class APVRuntimeController : MonoBehaviour
{
    [Header("APV 设置")]
    public ProbeVolume probeVolume;
    public float minSubdivisionDistance = 0.5f;
    public float maxSubdivisionDistance = 4f;
    
    [Header("漏光修正")]
    public float virtualOffsetBias = 0.1f;
    public bool enableLeakReduction = true;

    private ProbeReferenceVolume _probeRefVolume;

    void Start()
    {
        _probeRefVolume = ProbeReferenceVolume.instance;
        ConfigureAPV();
    }

    private void ConfigureAPV()
    {
        if (_probeRefVolume == null) return;

        // 设置探针子空间细分参数
        _probeRefVolume.minBrickSize = minSubdivisionDistance;
        
        // 渲染设置中的探针系统回调
        RenderPipelineManager.beginCameraRendering += OnBeginCameraRendering;
    }

    private void OnBeginCameraRendering(ScriptableRenderContext ctx, Camera cam)
    {
        if (!enableLeakReduction) return;
        
        // 根据相机距离动态调整探针采样偏移，减少漏光
        float camDist = Vector3.Distance(cam.transform.position, transform.position);
        float normalizedDist = Mathf.Clamp01(camDist / maxSubdivisionDistance);
        
        // 通过 Shader 全局参数传递漏光修正偏移
        Shader.SetGlobalFloat("_APV_LeakBias", 
            Mathf.Lerp(virtualOffsetBias, virtualOffsetBias * 2f, normalizedDist));
    }

    /// <summary>
    /// 运行时查询指定位置的探针有效性
    /// </summary>
    public bool IsPositionInsideAPV(Vector3 worldPos)
    {
        if (_probeRefVolume == null) return false;
        return _probeRefVolume.GetCellIndexUpdateInfo(worldPos, out _);
    }

    /// <summary>
    /// APV 场景流式加载控制
    /// </summary>
    public void LoadProbeVolumeForScene(string sceneName)
    {
        ProbeReferenceVolume.instance.LoadCells(sceneName);
        Debug.Log($"[APV] 已加载场景探针数据: {sceneName}");
    }

    public void UnloadProbeVolumeForScene(string sceneName)
    {
        ProbeReferenceVolume.instance.UnloadCells(sceneName);
        Debug.Log($"[APV] 已卸载场景探针数据: {sceneName}");
    }

    void OnDestroy()
    {
        RenderPipelineManager.beginCameraRendering -= OnBeginCameraRendering;
    }
}
```

### 4.3 APV Shader 采样

```hlsl
// APV 采样（URP/HDRP 通用宏）
#ifdef USE_APV_PROBE_OCCLUSION
    // 启用探针遮挡时的采样
    float3 bakeDiffuseLighting = 0;
    float3 backBakeDiffuseLighting = 0;
    
    EvaluateAdaptiveProbeVolume(
        GetAbsolutePositionWS(positionInputs.positionWS),
        normalWS,
        -normalWS,
        GetWorldSpaceNormalizeViewDir(positionInputs.positionWS),
        positionInputs.positionSS,
        bakeDiffuseLighting,
        backBakeDiffuseLighting
    );
    
    indirectDiffuse = bakeDiffuseLighting * albedo;
#else
    // 回退到 Light Probe SH
    indirectDiffuse = SampleSHIrradiance(normalWS) * albedo;
#endif
```

---

## 五、性能优化策略

### 5.1 Light Probe 优化

```csharp
/// <summary>
/// Light Probe 批量更新优化器
/// 对大量动态物体按帧分批更新 SH，避免每帧全量计算
/// </summary>
public class LightProbeBatchUpdater : MonoBehaviour
{
    [Header("批量更新")]
    public int objectsPerFrame = 20;
    public float movementThreshold = 0.5f; // 移动超过此距离才重新采样

    private List<(Transform tr, Renderer rend, Vector3 lastPos, MaterialPropertyBlock mpb)> _objects;
    private int _currentIndex;

    public void RegisterObject(Transform tr, Renderer rend)
    {
        _objects.Add((tr, rend, tr.position, new MaterialPropertyBlock()));
    }

    void Update()
    {
        int processed = 0;
        int count = _objects.Count;
        
        while (processed < objectsPerFrame && count > 0)
        {
            int idx = _currentIndex % count;
            var (tr, rend, lastPos, mpb) = _objects[idx];

            // 只有物体移动超过阈值才重新采样
            if (Vector3.SqrMagnitude(tr.position - lastPos) > movementThreshold * movementThreshold)
            {
                LightProbes.GetInterpolatedProbe(tr.position, rend, out var sh);
                
                // 将 SH 写入 MaterialPropertyBlock
                ApplySHToMPB(sh, mpb);
                rend.SetPropertyBlock(mpb);
                
                _objects[idx] = (tr, rend, tr.position, mpb);
            }

            _currentIndex++;
            processed++;
        }
    }

    private void ApplySHToMPB(SphericalHarmonicsL2 sh, MaterialPropertyBlock mpb)
    {
        // 按照 Unity 内置格式填充 SH 参数
        var shA = new Vector4[3];
        var shB = new Vector4[3];
        
        for (int c = 0; c < 3; c++)
        {
            shA[c] = new Vector4(sh[c, 3], sh[c, 1], sh[c, 2], sh[c, 0] - sh[c, 6]);
        }
        shB[0] = new Vector4(sh[0, 4], sh[0, 5], sh[0, 6] * 3f, sh[0, 7]);
        shB[1] = new Vector4(sh[1, 4], sh[1, 5], sh[1, 6] * 3f, sh[1, 7]);
        shB[2] = new Vector4(sh[2, 4], sh[2, 5], sh[2, 6] * 3f, sh[2, 7]);
        
        mpb.SetVector("unity_SHAr", shA[0]);
        mpb.SetVector("unity_SHAg", shA[1]);
        mpb.SetVector("unity_SHAb", shA[2]);
        mpb.SetVector("unity_SHBr", shB[0]);
        mpb.SetVector("unity_SHBg", shB[1]);
        mpb.SetVector("unity_SHBb", shB[2]);
        mpb.SetVector("unity_SHC", new Vector4(sh[0, 8], sh[1, 8], sh[2, 8], 1f));
    }
}
```

---

## 六、最佳实践总结

### 6.1 Light Probe 布置原则

1. **密度分级**：光照变化剧烈区域（阴影边界、门洞、室内外交界）加密探针；开阔均匀区域稀疏放置
2. **避免穿透几何体**：探针不要放在墙内，使用 Probe Group 的 `Remove Rogue Probes` 功能
3. **高度层次**：角色不同高度（地面/跳跃高度）分层放置，避免地面探针被角色采样
4. **室内外分离**：门窗附近使用双层探针，分别代表室内外光照环境

### 6.2 IBL 性能权衡

| 方案 | CPU 开销 | GPU 开销 | 质量 |
|---|---|---|---|
| SH L0+L1（顶点）| 极低 | 极低 | 低 |
| SH L0+L1+L2（像素）| 低 | 低 | 中 |
| Pre-filtered Cubemap | 低（预计算）| 中（纹理采样）| 高 |
| 实时辐照度采样 | 无 | 高（卷积积分）| 最高 |

### 6.3 APV vs Light Probe Group 选型

- **APV 适用**：Unity 6+、URP/HDRP、开放世界、场景几何复杂
- **LPG 适用**：Unity 5/2022、兼容性优先、内存极度受限、项目规模小

### 6.4 常见问题排查

| 问题 | 原因 | 解决方案 |
|---|---|---|
| 角色漏光（暗角泛光） | 探针采样到几何体另一侧 | 启用 APV 虚拟偏移 / 手动调整 LPG |
| 室内探针变亮 | 室外探针影响 | 用 Light Probe Proxy Volume 隔离 |
| 探针插值跳变 | 探针密度不均匀 | 加密过渡区域 / 使用 APV |
| SH 系数 NaN | 烘焙时天空盒 HDR 值溢出 | 限制 HDR 亮度上限 / 检查光源 intensity |

---

## 结语

球谐函数以极低的存储和计算代价（9个向量），提供了足够质量的低频漫反射环境光照，是游戏实时渲染中最具性价比的技术之一。结合 Unity 的 Light Probe 系统和新一代 APV，配合 IBL PBR 管线，可以构建出媲美次世代品质的动态全局光照系统。随着 Unity 6 对 APV 的持续完善，APV 将逐渐取代传统 Light Probe Group，成为游戏间接光照的标准方案。
