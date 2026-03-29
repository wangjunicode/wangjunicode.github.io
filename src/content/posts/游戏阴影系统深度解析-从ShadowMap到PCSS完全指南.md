---
title: 游戏阴影系统深度解析：从ShadowMap到PCSS完全指南
published: 2026-03-29
description: 深入剖析游戏阴影渲染的完整技术体系，从基础ShadowMap原理到PCF、PCSS、VSM、级联阴影CSM的实现细节，涵盖移动端阴影优化策略与Unity URP实践，助你掌握高质量实时阴影的工程落地方案。
tags: [Unity, 阴影, ShadowMap, PCSS, 渲染优化, 图形学]
category: 渲染技术
draft: false
---

# 游戏阴影系统深度解析：从ShadowMap到PCSS完全指南

阴影是游戏视觉真实感的基石之一。一个缺少阴影的场景会让玩家感到物体"漂浮"在地面上，破坏沉浸感。然而，高质量的实时阴影计算代价昂贵——在移动端尤为突出。本文将系统性地拆解阴影技术栈，从最基础的 Shadow Map 原理出发，逐步讲解 PCF、PCSS、VSM、CSM 等主流方案，并给出 Unity URP 下的工程实践。

---

## 一、阴影渲染的基础原理

### 1.1 Shadow Map 核心思路

Shadow Map（阴影贴图）是当前游戏引擎中最主流的实时阴影方案，由 Lance Williams 于 1978 年提出。其核心思路极为简洁：

**"从光源视角渲染场景，记录每个像素到光源的最近距离（深度），再从摄像机视角渲染时比较当前像素深度与光源深度图中的值，若当前深度更大则该点处于阴影中。"**

```
阴影判断：
  shadow_depth = ShadowMap.sample(light_space_uv)
  current_depth = dot(light_dir, world_pos) / light_range

  if current_depth > shadow_depth + bias:
      in_shadow = true
```

**两步渲染流程：**

```
Pass 1（阴影Pass）:
  - 从光源位置构造 View/Projection 矩阵
  - 渲染场景几何，只输出深度到 ShadowMap RT

Pass 2（正常渲染Pass）:
  - 将世界坐标变换到光源空间（LightSpacePos）
  - 采样 ShadowMap，比较深度
  - 根据比较结果调节光照贡献
```

### 1.2 Shadow Acne 与 Peter Panning

Shadow Map 最经典的两个伪影：

**Shadow Acne（阴影痘痘）**：由于深度精度有限，表面自身产生错误阴影条纹。

解决方案：添加 **Depth Bias**（偏移量），在采样比较时给 shadow_depth 加一个小偏移：

```hlsl
// 固定偏移
float bias = 0.005;

// 更精确：根据法线与光源夹角动态调整
float cosTheta = clamp(dot(normalWS, lightDir), 0.0, 1.0);
float bias = max(0.01 * (1.0 - cosTheta), 0.001);

float shadow = currentDepth - bias > closestDepth ? 1.0 : 0.0;
```

**Peter Panning（彼得·潘效果）**：Bias 过大导致物体阴影与物体分离，看起来像在飞。

工程上的平衡策略：
- 使用 Normal Bias（沿法线方向偏移采样点）而非 Depth Bias
- 在背面渲染 Shadow Pass（Cull Front），消除正面的自遮挡问题

```hlsl
// Normal Offset Shadow Map
float3 shadowPositionWS = positionWS + normalWS * normalBias;
float4 shadowCoord = TransformWorldToShadowCoord(shadowPositionWS);
```

### 1.3 Shadow Map 分辨率与精度问题

Shadow Map 分辨率直接影响阴影锯齿（aliasing）。常见分辨率：

| 质量档位 | 分辨率 | 适用平台 |
|---------|--------|---------|
| 低 | 512×512 | 低端移动端 |
| 中 | 1024×1024 | 主流移动端 |
| 高 | 2048×2048 | 高端移动/主机 |
| 超高 | 4096×4096 | PC/主机 |

---

## 二、PCF：软阴影的入门方案

### 2.1 PCF 原理

**Percentage Closer Filtering（PCF）** 不是对深度值做滤波，而是对比较结果做均值滤波：

```hlsl
float PCF_Shadow(sampler2D shadowMap, float4 shadowCoord, float bias)
{
    float shadow = 0.0;
    float2 texelSize = 1.0 / textureSize(shadowMap, 0);
    
    // 3x3 核采样
    for(int x = -1; x <= 1; ++x)
    {
        for(int y = -1; y <= 1; ++y)
        {
            float pcfDepth = texture(shadowMap, shadowCoord.xy + vec2(x, y) * texelSize).r;
            shadow += shadowCoord.z - bias > pcfDepth ? 1.0 : 0.0;
        }
    }
    shadow /= 9.0;
    return shadow;
}
```

PCF 的本质是：对周围多个采样点分别判断是否在阴影中，然后求平均值，得到 0~1 之间的连续遮挡值，从而实现软边缘过渡。

### 2.2 PCF 核大小与性能权衡

| 核大小 | 采样次数 | 质量 | 性能开销 |
|--------|---------|------|---------|
| 3×3 | 9次 | 较低 | 低 |
| 5×5 | 25次 | 中等 | 中 |
| 7×7 | 49次 | 较高 | 高 |
| Poisson Disk | 可变 | 高 | 可控 |

**泊松圆盘采样（Poisson Disk Sampling）** 可以用更少的采样次数获得更均匀的覆盖：

```hlsl
// 预定义泊松圆盘采样点（16点）
static const float2 poissonDisk[16] = {
    float2(-0.94201624, -0.39906216),
    float2( 0.94558609, -0.76890725),
    float2(-0.09400376,  0.92938870),
    float2( 0.34495938,  0.29387760),
    float2(-0.91588581,  0.45771432),
    float2(-0.81544232, -0.87912464),
    float2(-0.38277543,  0.27676845),
    float2( 0.97484398,  0.75648379),
    float2( 0.44323325, -0.97511554),
    float2( 0.53742981, -0.47373420),
    float2(-0.26496911, -0.41893023),
    float2( 0.79197514,  0.19090188),
    float2(-0.24188840,  0.99706507),
    float2(-0.81409955,  0.91437590),
    float2( 0.19984126,  0.78641367),
    float2( 0.14383161, -0.14100790)
};

float PCF_Poisson(sampler2D shadowMap, float4 shadowCoord, float bias, float spread)
{
    float shadow = 0.0;
    float2 texelSize = 1.0 / textureSize(shadowMap, 0);
    
    for(int i = 0; i < 16; i++)
    {
        float2 offset = poissonDisk[i] * texelSize * spread;
        float pcfDepth = texture(shadowMap, shadowCoord.xy + offset).r;
        shadow += shadowCoord.z - bias > pcfDepth ? 1.0 : 0.0;
    }
    return shadow / 16.0;
}
```

---

## 三、PCSS：基于物理的软阴影

### 3.1 PCSS 核心思路

**Percentage Closer Soft Shadows（PCSS）** 由 Randima Fernando 在 2005 年 GDC 提出，能模拟真实光源面积产生的软阴影：离投射物近的地方阴影硬，离得远的地方阴影软。

PCSS 分三步：

```
Step 1：Blocker Search（遮挡物搜索）
  - 在光源空间，搜索当前点周围区域，找到平均遮挡深度 d_blocker

Step 2：Penumbra Size 估算（半影宽度估算）
  - w_penumbra = (d_receiver - d_blocker) / d_blocker * w_light
  - 距离遮挡物越远，半影越宽

Step 3：PCF 滤波
  - 用 w_penumbra 决定 PCF 核的大小，做自适应 PCF
```

### 3.2 PCSS HLSL 实现

```hlsl
// =============================================
// PCSS 完整实现
// =============================================

#define BLOCKER_SEARCH_SAMPLES 16
#define PCF_SAMPLES 32
#define LIGHT_SIZE 0.05  // 光源大小（越大半影越宽）
#define SHADOW_MAP_SIZE 2048.0

// Blocker Search：找到平均遮挡深度
float FindBlockerDistance(sampler2D shadowMap, float2 uv, float currentDepth, float searchRadius)
{
    float blockerSum = 0.0;
    int numBlockers = 0;
    
    for(int i = 0; i < BLOCKER_SEARCH_SAMPLES; i++)
    {
        float2 offset = poissonDisk[i] * searchRadius;
        float shadowMapDepth = texture(shadowMap, uv + offset).r;
        
        if(shadowMapDepth < currentDepth)
        {
            blockerSum += shadowMapDepth;
            numBlockers++;
        }
    }
    
    if(numBlockers == 0) return -1.0; // 没有遮挡物，完全在光照中
    return blockerSum / float(numBlockers);
}

// PCSS 主函数
float PCSS(sampler2D shadowMap, float4 shadowCoord)
{
    float2 uv = shadowCoord.xy;
    float currentDepth = shadowCoord.z;
    
    // Step 1: Blocker Search
    float searchRadius = LIGHT_SIZE * (currentDepth - 0.1) / currentDepth;
    searchRadius /= SHADOW_MAP_SIZE;
    
    float avgBlockerDepth = FindBlockerDistance(shadowMap, uv, currentDepth, searchRadius);
    
    // 完全在光照中
    if(avgBlockerDepth < 0.0) return 0.0;
    
    // Step 2: 计算半影宽度
    float penumbraWidth = (currentDepth - avgBlockerDepth) / avgBlockerDepth;
    penumbraWidth *= LIGHT_SIZE;
    float pcfRadius = penumbraWidth / SHADOW_MAP_SIZE;
    pcfRadius = clamp(pcfRadius, 0.0001, 0.01); // 限制范围
    
    // Step 3: 自适应 PCF
    float shadow = 0.0;
    for(int i = 0; i < PCF_SAMPLES; i++)
    {
        float2 offset = poissonDisk[i % 16] * pcfRadius;
        float shadowDepth = texture(shadowMap, uv + offset).r;
        shadow += currentDepth - 0.001 > shadowDepth ? 1.0 : 0.0;
    }
    
    return shadow / float(PCF_SAMPLES);
}
```

---

## 四、VSM：方差阴影贴图

### 4.1 VSM 原理

**Variance Shadow Map（VSM）** 利用切比雪夫不等式来估算一个点处于阴影中的概率，最大优势是可以对深度值直接做模糊（硬件滤波/Mipmap），实现高效软阴影。

VSM 存储两个值：
- `μ = E[x]`：深度均值
- `σ² = E[x²] - E[x]²`：深度方差

```hlsl
// VSM Shadow Map 生成（Pass 1）
// RT 格式：RG32F，存储 depth 和 depth²
fragOutput.rg = float2(depth, depth * depth);
```

采样时使用切比雪夫不等式估算概率：

```hlsl
float ChebyshevUpperBound(float2 moments, float t)
{
    // 完全在光照中
    if(t <= moments.x) return 1.0;
    
    // 计算方差
    float variance = moments.y - (moments.x * moments.x);
    variance = max(variance, 0.00002); // 最小方差防除零
    
    // 切比雪夫不等式
    float d = t - moments.x;
    float p_max = variance / (variance + d * d);
    
    return p_max;
}

float VSM_Shadow(sampler2D shadowMap, float4 shadowCoord)
{
    float2 moments = texture(shadowMap, shadowCoord.xy).rg;
    return 1.0 - ChebyshevUpperBound(moments, shadowCoord.z);
}
```

### 4.2 Light Bleeding 问题与解决

VSM 的主要缺陷是 **Light Bleeding（漏光）**：当多个遮挡物叠加时，切比雪夫不等式过于乐观，导致不应被照亮的区域显示光照。

解决方案：**Light Bleeding Reduction**

```hlsl
float ReduceLightBleeding(float pMax, float amount)
{
    // 将 [0, amount] 映射到 0，[amount, 1] 重新映射到 [0, 1]
    return smoothstep(amount, 1.0, pMax);
}

float VSM_Shadow_NoBleed(sampler2D shadowMap, float4 shadowCoord, float bleedReduction)
{
    float2 moments = texture(shadowMap, shadowCoord.xy).rg;
    float pMax = ChebyshevUpperBound(moments, shadowCoord.z);
    pMax = ReduceLightBleeding(pMax, bleedReduction); // bleedReduction 典型值 0.3~0.6
    return 1.0 - pMax;
}
```

---

## 五、CSM：级联阴影贴图

### 5.1 为什么需要级联

平行光的 Shadow Map 面临"近处精度浪费，远处精度不足"的问题：

```
摄像机近处：Shadow Map 覆盖区域小，单个像素对应游戏世界中面积很小 → 精度浪费
摄像机远处：Shadow Map 覆盖区域大，单个像素对应大面积 → 锯齿严重
```

**Cascaded Shadow Maps（CSM）** 解决方案：将视锥体按距离分割为多个子区域（级联），为每个级联单独生成一张 Shadow Map：

```
Cascade 0：[near, split0]   → 高精度，覆盖近处
Cascade 1：[split0, split1] → 中等精度
Cascade 2：[split1, split2] → 低精度，覆盖远处
Cascade 3：[split2, far]    → 最低精度，覆盖最远处
```

### 5.2 级联分割策略

**对数分割（实用性最强）**：

```csharp
// C# - 计算 CSM 分割平面
public static float[] ComputeCascadeSplits(float nearPlane, float farPlane, 
    int numCascades, float lambda = 0.7f)
{
    float range = farPlane - nearPlane;
    float ratio = farPlane / nearPlane;
    float[] splits = new float[numCascades];
    
    for(int i = 0; i < numCascades; i++)
    {
        float p = (i + 1) / (float)numCascades;
        float log = nearPlane * Mathf.Pow(ratio, p);
        float uniform = nearPlane + range * p;
        float d = lambda * (log - uniform) + uniform;
        splits[i] = d;
    }
    return splits;
}
```

### 5.3 Unity URP CSM 实践

```csharp
// Unity URP 中配置 CSM
// 通过 UniversalRenderPipelineAsset 设置

[System.Serializable]
public class ShadowSettings
{
    [Range(1, 4)]
    public int cascadeCount = 4;
    
    // 各级联的分割比例（百分比）
    public float cascade2Split = 0.25f;
    public Vector2 cascade3Split = new Vector2(0.167f, 0.4f);
    public Vector3 cascade4Split = new Vector3(0.067f, 0.2f, 0.467f);
    
    public float maxShadowDistance = 150f;
    public int shadowResolution = 2048;
}

// Shader 中访问 CSM
// URP 已内置 CSM 支持，通过 TransformWorldToShadowCoord 自动选择级联

float4 shadowCoord = TransformWorldToShadowCoord(positionWS);
// shadowCoord.w 包含级联索引信息

half shadow = MainLightRealtimeShadow(shadowCoord);
```

### 5.4 级联间的过渡混合

级联边界处容易出现可见的"接缝"，需要做混合过渡：

```hlsl
// URP 源码风格 - 级联过渡混合
float GetShadowFade(float3 positionWS)
{
    float3 camToPixel = positionWS - _WorldSpaceCameraPos;
    float distanceCamToPixel2 = dot(camToPixel, camToPixel);
    
    // _LightShadowData.z = maxShadowDistance, .w = fade start
    float fade = saturate(distanceCamToPixel2 * _LightShadowData.z + _LightShadowData.w);
    return fade * fade;
}

// 在 CSM 采样中使用 dither 过渡
float SampleShadowmapWithDither(float4 shadowCoord, half cascadeIndex)
{
    // Bayer 矩阵抖动，用于平滑级联过渡
    float dither = InterleavedGradientNoise(positionSS, 0);
    // ... 混合相邻级联的阴影值
}
```

---

## 六、移动端阴影优化策略

### 6.1 移动端阴影的性能瓶颈

```
瓶颈1：带宽
  - Shadow Map 的读写带宽消耗巨大
  - TBDR 架构下，阴影 Pass 打破 Tile 缓存优势

瓶颈2：ALU
  - PCF 多次采样的计算量
  - PCSS 的 Blocker Search 代价极高

瓶颈3：精度
  - 移动端通常使用 16-bit 深度，精度有限
  - 需要仔细调整 Bias 参数
```

### 6.2 移动端阴影优化方案清单

**方案一：简化阴影质量分档**

```csharp
// 根据设备性能等级选择阴影质量
public enum ShadowQuality { Off, Hard, Soft2x2, Soft4x4 }

public void ApplyShadowQuality(ShadowQuality quality)
{
    var asset = (UniversalRenderPipelineAsset)GraphicsSettings.renderPipelineAsset;
    
    switch(quality)
    {
        case ShadowQuality.Off:
            asset.shadowDistance = 0;
            break;
            
        case ShadowQuality.Hard:
            asset.shadowDistance = 50f;
            asset.mainLightShadowmapResolution = ShadowResolution._512;
            // 禁用 PCF，使用硬阴影
            break;
            
        case ShadowQuality.Soft2x2:
            asset.shadowDistance = 80f;
            asset.mainLightShadowmapResolution = ShadowResolution._1024;
            break;
            
        case ShadowQuality.Soft4x4:
            asset.shadowDistance = 120f;
            asset.mainLightShadowmapResolution = ShadowResolution._2048;
            break;
    }
}
```

**方案二：动态阴影距离裁剪**

```csharp
// 根据摄像机移动动态调整阴影投射范围
public class DynamicShadowCuller : MonoBehaviour
{
    [SerializeField] private float shadowDistance = 80f;
    [SerializeField] private float shadowFadeStart = 60f;
    
    private List<Renderer> shadowCasters = new List<Renderer>();
    
    void Update()
    {
        var camPos = Camera.main.transform.position;
        
        foreach(var renderer in shadowCasters)
        {
            float dist = Vector3.Distance(renderer.transform.position, camPos);
            // 超过距离的物体不投射阴影
            renderer.shadowCastingMode = dist < shadowDistance
                ? UnityEngine.Rendering.ShadowCastingMode.On
                : UnityEngine.Rendering.ShadowCastingMode.Off;
        }
    }
}
```

**方案三：屏幕空间阴影（Screen Space Shadow）**

在 URP 中启用 Screen Space Shadow，可以将阴影计算转移到屏幕空间，降低采样次数：

```csharp
// URP Renderer Feature：ScreenSpaceShadows
// 原理：
// 1. 在单独 Pass 中，对每个屏幕像素计算阴影，存储到 ScreenSpaceShadow RT
// 2. 光照 Pass 直接采样 ScreenSpaceShadow RT（屏幕空间单次采样）
// 3. 避免了 PCF 在每个 Fragment 的多次 ShadowMap 采样

// 启用方法（代码方式）
public class ScreenSpaceShadowSetup : ScriptableRendererFeature
{
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        // URP 内置 ScreenSpaceShadows Feature 添加
        renderer.EnqueuePass(new ScreenSpaceShadowResolvePass());
    }
}
```

**方案四：Baked Shadow + 动态角色混合**

```csharp
// 静态场景使用烘焙阴影，只对角色等动态物体计算实时阴影
// 减少 Shadow Map 中的投射物数量

// 将静态物体从实时阴影中排除
public class StaticShadowOptimizer : MonoBehaviour
{
    void Start()
    {
        var renderers = GetComponentsInChildren<MeshRenderer>();
        foreach(var r in renderers)
        {
            if(r.gameObject.isStatic)
            {
                // 接受阴影但不投射（利用光照贴图中的烘焙阴影）
                r.shadowCastingMode = ShadowCastingMode.Off;
                r.receiveShadows = true;
            }
        }
    }
}
```

---

## 七、Unity URP 阴影系统完整配置实践

### 7.1 URP Shadow 完整 Shader 实现

```hlsl
// MyLit_Shadow.hlsl
// URP 自定义 Lit Shader 中的阴影接收

#pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE _MAIN_LIGHT_SHADOWS_SCREEN
#pragma multi_compile _ _SHADOWS_SOFT
#pragma multi_compile _ _ADDITIONAL_LIGHT_SHADOWS

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"

struct Varyings
{
    float4 positionHCS  : SV_POSITION;
    float3 positionWS   : TEXCOORD0;
    float3 normalWS     : TEXCOORD1;
    float2 uv           : TEXCOORD2;
    // 屏幕空间阴影坐标（当使用 Screen Space Shadow 时）
    float4 shadowCoord  : TEXCOORD3;
};

Varyings LitPassVertex(Attributes input)
{
    Varyings output;
    
    VertexPositionInputs posInputs = GetVertexPositionInputs(input.positionOS.xyz);
    VertexNormalInputs normInputs = GetVertexNormalInputs(input.normalOS);
    
    output.positionHCS = posInputs.positionCS;
    output.positionWS  = posInputs.positionWS;
    output.normalWS    = normInputs.normalWS;
    output.uv          = TRANSFORM_TEX(input.uv, _BaseMap);
    
    // 计算阴影坐标（支持 CSM 级联选择）
    output.shadowCoord = GetShadowCoord(posInputs);
    
    return output;
}

half4 LitPassFragment(Varyings input) : SV_Target
{
    // 采样主光源阴影（自动处理 CSM 级联选择）
    float4 shadowCoord = TransformWorldToShadowCoord(input.positionWS);
    
#if defined(_MAIN_LIGHT_SHADOWS_SCREEN)
    // 屏幕空间阴影模式
    shadowCoord = input.shadowCoord;
#endif
    
    Light mainLight = GetMainLight(shadowCoord);
    // mainLight.shadowAttenuation 就是阴影遮蔽值（0=全阴影，1=全光照）
    
    // 标准 PBR 光照计算
    InputData inputData;
    inputData.positionWS = input.positionWS;
    inputData.normalWS   = normalize(input.normalWS);
    inputData.viewDirectionWS = GetWorldSpaceViewDir(input.positionWS);
    inputData.shadowCoord = shadowCoord;
    inputData.fogCoord    = 0;
    inputData.vertexLighting = half3(0, 0, 0);
    inputData.bakedGI     = SampleSH(inputData.normalWS);
    
    SurfaceData surfaceData;
    surfaceData.albedo = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv).rgb * _BaseColor.rgb;
    surfaceData.metallic   = _Metallic;
    surfaceData.smoothness = _Smoothness;
    surfaceData.occlusion  = 1.0;
    surfaceData.emission   = half3(0, 0, 0);
    surfaceData.alpha      = 1.0;
    surfaceData.specular   = half3(0, 0, 0);
    surfaceData.normalTS   = half3(0, 0, 1);
    surfaceData.clearCoatMask = 0;
    surfaceData.clearCoatSmoothness = 0;
    
    return UniversalFragmentPBR(inputData, surfaceData);
}
```

### 7.2 阴影质量调试工具

```csharp
// 运行时阴影质量调试面板
#if UNITY_EDITOR || DEVELOPMENT_BUILD
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class ShadowDebugPanel : MonoBehaviour
{
    private UniversalRenderPipelineAsset urpAsset;
    
    void Start()
    {
        urpAsset = (UniversalRenderPipelineAsset)GraphicsSettings.currentRenderPipeline;
    }
    
    void OnGUI()
    {
        GUILayout.BeginArea(new Rect(10, 10, 300, 300));
        GUILayout.Label($"Shadow Distance: {urpAsset.shadowDistance:F1}m");
        GUILayout.Label($"Cascade Count: {urpAsset.shadowCascadeCount}");
        GUILayout.Label($"Shadow Resolution: {urpAsset.mainLightShadowmapResolution}");
        
        // 可视化当前级联
        if(GUILayout.Button("Toggle Shadow Cascade Visualization"))
        {
            // 通过 Frame Debugger 或 RenderDoc 查看各级联覆盖
        }
        
        GUILayout.Label("FPS: " + (1f / Time.deltaTime).ToString("F0"));
        GUILayout.EndArea();
    }
}
#endif
```

---

## 八、高级技巧：Self-Shadow 与 Subsurface Scattering

### 8.1 角色皮肤的次表面散射阴影

皮肤等半透明材质在强光下应显示出"透光"效果，纯 Shadow Map 无法表达：

```hlsl
// 简化版 SSS 阴影处理
// 皮肤材质：即使在阴影中，也有少量背光透射

half SkinShadow(half shadowAtten, half3 normalWS, half3 lightDir, half subsurface)
{
    // 背光方向的透射分量
    half backlight = saturate(dot(-normalWS, lightDir));
    half transmission = pow(backlight, 3.0) * subsurface;
    
    // 混合：阴影部分仍有 transmission 比例的透射光
    return max(shadowAtten, transmission);
}
```

### 8.2 Ray Traced Shadows（光线追踪阴影）简介

Unity 2021+ 在 HDRP 中支持光线追踪软阴影：

```csharp
// HDRP 启用 Ray Traced Shadows
// 在 Light 组件上设置
var additionalData = light.GetComponent<HDAdditionalLightData>();
additionalData.useRayTracedShadows = true;
additionalData.numRayTracingSamples = 4;  // 采样数，越高质量越好但越慢
```

光线追踪阴影可以自然地处理：
- 曲面光源的柔和半影
- 自遮挡（无需 bias 调整）
- 透明物体的彩色阴影

但移动端暂不适用，是 PC/主机端未来方向。

---

## 九、性能对比与方案选型

| 阴影技术 | 软阴影 | 物理准确 | 移动端可用 | 实现复杂度 | 典型开销 |
|---------|--------|---------|-----------|-----------|---------|
| Hard Shadow Map | ❌ | ❌ | ✅ | 低 | 极低 |
| PCF 3×3 | 近似 | ❌ | ✅ | 低 | 低 |
| PCF 5×5 | 中等 | ❌ | 中端 | 低 | 中 |
| PCSS | ✅ | ✅ | ❌ | 高 | 高 |
| VSM | ✅ | 近似 | 中端 | 中 | 中低 |
| CSM + PCF | 中等 | ❌ | ✅ | 中 | 中 |
| Ray Traced | ✅ | ✅ | ❌ | 高 | 极高 |

**选型建议：**

```
移动端低配：Hard Shadow Map + CSM(2级联) + 短距离裁剪
移动端中配：PCF 3×3 + CSM(3级联) + Screen Space Shadow
移动端高配：PCF 5×5 + CSM(4级联) + VSM 远景
PC/主机中配：PCSS + CSM(4级联)
PC/主机高配：Ray Traced Shadows
```

---

## 十、最佳实践总结

1. **始终使用 Normal Bias 代替 Depth Bias**：法线偏移在大多数情况下效果更好，且不易出现 Peter Panning。

2. **CSM 分割不要均匀**：使用对数分割或 PSSM（Practical Split Scheme），把更多精度留给近处。

3. **Shadow Distance 是第一优化手段**：减少 Shadow Distance 对性能提升最为显著，根据场景合理设置（大多数游戏 50~100m 已足够）。

4. **利用 Screen Space Shadow 降低带宽**：URP 的 Screen Space Shadow Feature 将 Shadow Map 采样集中在一个全屏 Pass，后续 Light Pass 直接读取缓存结果。

5. **静态物体使用 Lightmap 阴影**：只让动态物体（角色、可移动道具）参与实时阴影计算，静态场景使用烘焙结果。

6. **阴影 Culling 不要忽视**：Unity 的 Shadow Culling 系统会剔除不在光源视锥和摄像机视锥交集内的投射物，自定义 ShadowCasterGroup 可以进一步减少不必要的 Draw Call。

7. **移动端慎用 PCSS**：PCSS 的 Blocker Search 步骤对移动端 GPU 压力极大，建议在中高端机型才考虑，或使用 VSM 作为替代。

8. **阴影 Fade 要做好过渡**：远处阴影逐渐淡出时，使用 Dither 或 Smooth Fade 避免突变，并结合 Ambient Occlusion 弥补远处阴影缺失的接触感。

---

> **作者注**：阴影系统是渲染工程中"改动小、影响大"的领域。一个精心调校的 Shadow Map 配置，在不增加 PCSS 开销的前提下，完全可以达到视觉上令人满意的效果。理解每种技术背后的数学原理，才能在遇到 Artifact 时快速定位原因并找到最优解。
