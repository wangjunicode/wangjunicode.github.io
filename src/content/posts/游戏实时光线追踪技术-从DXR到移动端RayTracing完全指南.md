---
title: 游戏实时光线追踪技术：从DXR到移动端RayTracing完全指南
published: 2026-04-11
description: 深度解析实时光线追踪技术原理、DXR/Vulkan RayTracing API、Unity HDRP中的光追实现、软阴影/反射/全局光照优化，以及移动端光线追踪落地策略与性能权衡方案。
tags: [光线追踪, RayTracing, DXR, Unity HDRP, 图形渲染, 性能优化]
category: 图形渲染
draft: false
---

# 游戏实时光线追踪技术：从DXR到移动端RayTracing完全指南

## 一、光线追踪技术概览

### 1.1 什么是光线追踪

光线追踪（Ray Tracing）是一种模拟光线物理传播过程的渲染技术。与传统的光栅化渲染不同，光线追踪从摄像机出发，向场景投射光线，通过递归追踪反射、折射和散射来计算每个像素的最终颜色。

```
传统光栅化渲染流程：
顶点变换 → 三角形裁剪 → 光栅化 → 片元着色 → 深度测试 → 输出

光线追踪渲染流程：
生成主光线 → BVH加速结构遍历 → 求交测试 → 着色计算 → 递归追踪（反射/折射/阴影）→ 输出
```

### 1.2 实时光追 vs 离线光追

| 对比维度 | 离线光追（电影级） | 实时光追（游戏级） |
|---------|-------------------|-------------------|
| 采样数量 | 数千SPP | 1-4 SPP |
| 帧时间预算 | 数小时/帧 | 16-33ms/帧 |
| 降噪方式 | 蒙特卡洛积分收敛 | AI降噪/时域累积(TAA) |
| 硬件要求 | 无GPU限制 | RTX/RDNA2以上 |
| 精度 | 接近物理真实 | 视觉近似 |

### 1.3 硬件加速单元

NVIDIA Turing/Ampere 架构引入了专用 **RT Core**：
- **RT Core**：硬件BVH遍历加速单元
- **Tensor Core**：AI降噪加速（DLSS）
- **CUDA Core**：通用计算与着色

AMD RDNA2/3 的等效单元：**Ray Accelerator**，每个CU含1个Ray Accelerator。

---

## 二、光线追踪核心 API 解析

### 2.1 DXR（DirectX Raytracing）

DXR 是 DirectX 12 的扩展，于2018年引入。核心概念：

```
DXR 流水线阶段：
┌─────────────────────────────────────────┐
│ Ray Generation Shader  (光线生成)         │
│ Intersection Shader   (自定义求交)        │
│ Any Hit Shader        (任意命中)          │
│ Closest Hit Shader    (最近命中)          │
│ Miss Shader           (光线未命中)        │
└─────────────────────────────────────────┘
```

**加速结构（Acceleration Structure）：**
- **BLAS（Bottom-Level AS）**：存储单个网格的几何数据
- **TLAS（Top-Level AS）**：实例化场景中所有BLAS，支持变换矩阵

### 2.2 Vulkan Ray Tracing Extension

```glsl
// Vulkan光线追踪着色器示例 - 光线生成
#version 460
#extension GL_EXT_ray_tracing : require

layout(binding = 0, set = 0) uniform accelerationStructureEXT topLevelAS;
layout(binding = 1, set = 0, rgba8) uniform image2D image;
layout(binding = 2, set = 0) uniform CameraProperties {
    mat4 viewInverse;
    mat4 projInverse;
} cam;

layout(location = 0) rayPayloadEXT vec3 hitValue;

void main() {
    const vec2 pixelCenter = vec2(gl_LaunchIDEXT.xy) + vec2(0.5);
    const vec2 inUV = pixelCenter / vec2(gl_LaunchSizeEXT.xy);
    vec2 d = inUV * 2.0 - 1.0;

    vec4 origin    = cam.viewInverse * vec4(0, 0, 0, 1);
    vec4 target    = cam.projInverse * vec4(d.x, d.y, 1, 1);
    vec4 direction = cam.viewInverse * vec4(normalize(target.xyz), 0);

    float tmin = 0.001;
    float tmax = 10000.0;

    traceRayEXT(
        topLevelAS,            // 加速结构
        gl_RayFlagsOpaqueEXT,  // 光线标志
        0xFF,                  // 剔除掩码
        0, 1, 0,               // sbtOffset, sbtStride, missIndex
        origin.xyz,            // 光线起点
        tmin,                  // 最小距离
        direction.xyz,         // 光线方向
        tmax,                  // 最大距离
        0                      // payloadLocation
    );

    imageStore(image, ivec2(gl_LaunchIDEXT.xy), vec4(hitValue, 0.0));
}
```

---

## 三、Unity HDRP 光线追踪实践

### 3.1 环境配置

Unity HDRP 从 2019.3 开始支持 DXR，配置步骤：

```csharp
// 1. 检查硬件支持
using UnityEngine;
using UnityEngine.Rendering;

public class RayTracingCapabilityChecker : MonoBehaviour
{
    void Start()
    {
        // 检查是否支持光追
        bool isSupported = SystemInfo.supportsRayTracing;
        Debug.Log($"Ray Tracing Supported: {isSupported}");
        
        // 检查光追加速结构
        bool accelSupported = SystemInfo.supportsRayTracingShaders;
        Debug.Log($"RT Shaders Supported: {accelSupported}");
        
        // 当前图形API
        Debug.Log($"Graphics API: {SystemInfo.graphicsDeviceType}");
        // 需要 Direct3D12 或 Vulkan
    }
}
```

```csharp
// 2. HDRP 配置文件设置
// HDRenderPipelineAsset 中启用光追功能
// Edit → Project Settings → Graphics → HDRP Settings
// 启用 "Realtime Ray Tracing"
```

### 3.2 光线追踪反射（RT Reflections）

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

/// <summary>
/// 动态控制光追反射质量的系统
/// </summary>
public class RTReflectionController : MonoBehaviour
{
    [Header("光追反射配置")]
    [SerializeField] private Volume postProcessVolume;
    [SerializeField] private float highQualityDistance = 50f;
    [SerializeField] private float lowQualityDistance = 100f;

    private RayTracedReflections rtReflections;
    private Camera mainCamera;

    void Start()
    {
        mainCamera = Camera.main;
        
        if (postProcessVolume.profile.TryGet<RayTracedReflections>(out rtReflections))
        {
            InitializeReflections();
        }
    }

    void InitializeReflections()
    {
        // 启用光追反射
        rtReflections.active = true;
        
        // 设置光追模式
        rtReflections.mode.value = RayTracingMode.Performance;
        
        // 每帧光线数量（性能/质量权衡）
        rtReflections.sampleCount.value = 1;
        
        // 反射层级（次级反射）
        rtReflections.bounceCount.value = 1;
        
        // 降噪设置
        rtReflections.denoise.value = true;
        rtReflections.denoiserRadius.value = 16;
    }

    void Update()
    {
        // 根据摄像机与反射物的距离动态调整质量
        AdjustQualityByDistance();
    }

    void AdjustQualityByDistance()
    {
        // 在性能紧张时降低反射质量
        if (rtReflections == null) return;
        
        bool isHighPerf = IsPerformancePressure();
        
        if (isHighPerf)
        {
            // 降级：使用SSR替代光追反射
            rtReflections.mode.value = RayTracingMode.Performance;
            rtReflections.sampleCount.value = 1;
        }
        else
        {
            // 升级：使用完整光追反射
            rtReflections.mode.value = RayTracingMode.Quality;
            rtReflections.sampleCount.value = 2;
        }
    }

    bool IsPerformancePressure()
    {
        // 简单示例：基于帧率判断
        return 1.0f / Time.smoothDeltaTime < 30f;
    }
}
```

### 3.3 光线追踪阴影（RT Shadows）

```csharp
/// <summary>
/// 光追软阴影配置控制器
/// </summary>
public class RTShadowController : MonoBehaviour
{
    [Header("区域光软阴影")]
    [SerializeField] private Light areaLight;
    [SerializeField] private int shadowSampleCount = 4;

    void Start()
    {
        ConfigureRTShadow();
    }

    void ConfigureRTShadow()
    {
        var additionalLightData = areaLight.GetComponent<HDAdditionalLightData>();
        if (additionalLightData == null) return;

        // 启用光追阴影
        additionalLightData.useRayTracedShadows = true;
        
        // 软阴影采样数（影响性能与质量）
        additionalLightData.numRayTracingSamples = shadowSampleCount;
        
        // 软阴影降噪
        additionalLightData.filterTracedShadow = true;
        additionalLightData.filterSizeTraced = 16;
        
        Debug.Log($"RT Shadow configured: {shadowSampleCount} samples");
    }
}
```

### 3.4 光线追踪全局光照（RTGI）

```csharp
using UnityEngine.Rendering.HighDefinition;

/// <summary>
/// RTGI 动态全局光照系统
/// </summary>
public class RTGlobalIlluminationSystem : MonoBehaviour
{
    [Header("RTGI配置")]
    [SerializeField] private Volume volume;
    [SerializeField] private bool enableRTGI = true;
    [SerializeField] [Range(1, 4)] private int bouncesCount = 1;
    
    private GlobalIllumination gi;
    private ScreenSpaceAmbientOcclusion ssao;

    void Start()
    {
        if (volume.profile.TryGet<GlobalIllumination>(out gi))
        {
            SetupRTGI();
        }
        
        if (volume.profile.TryGet<ScreenSpaceAmbientOcclusion>(out ssao))
        {
            SetupRTAO();
        }
    }

    void SetupRTGI()
    {
        gi.active = enableRTGI;
        gi.tracing.value = RayCastingMode.RayTracing;
        
        // 光线反弹次数（直接光=0，1次间接光=1，多次间接=2+）
        gi.bounceCount.value = bouncesCount;
        
        // 每像素光线采样数
        gi.sampleCount.value = 1;
        
        // 时域降噪（重用历史帧数据）
        gi.denoise.value = true;
        gi.halfResolution.value = true; // 半分辨率提升性能
        
        Debug.Log($"RTGI enabled: {bouncesCount} bounces");
    }

    void SetupRTAO()
    {
        // 光追环境光遮蔽（比SSAO精度更高）
        ssao.rayTracing.value = true;
    }
    
    /// <summary>
    /// 运行时切换GI质量档位
    /// </summary>
    public void SetGIQuality(GIQuality quality)
    {
        if (gi == null) return;
        
        switch (quality)
        {
            case GIQuality.Ultra:
                gi.tracing.value = RayCastingMode.RayTracing;
                gi.bounceCount.value = 2;
                gi.sampleCount.value = 2;
                gi.halfResolution.value = false;
                break;
                
            case GIQuality.High:
                gi.tracing.value = RayCastingMode.RayTracing;
                gi.bounceCount.value = 1;
                gi.sampleCount.value = 1;
                gi.halfResolution.value = true;
                break;
                
            case GIQuality.Medium:
                // 降级至屏幕空间GI
                gi.tracing.value = RayCastingMode.Mixed;
                gi.halfResolution.value = true;
                break;
                
            case GIQuality.Low:
                // 纯烘焙GI
                gi.active = false;
                break;
        }
    }
}

public enum GIQuality { Ultra, High, Medium, Low }
```

---

## 四、自适应光线追踪系统

### 4.1 屏幕空间混合策略

在性能有限的情况下，混合光追与屏幕空间技术可以达到最优的视觉/性能平衡：

```csharp
/// <summary>
/// 自适应光追系统：根据GPU负载动态切换光追/屏幕空间技术
/// </summary>
public class AdaptiveRayTracingSystem : MonoBehaviour
{
    [Header("性能目标")]
    [SerializeField] private float targetFrameRate = 60f;
    [SerializeField] private float frameTimeBudgetMs = 16.67f;
    
    [Header("组件引用")]
    [SerializeField] private Volume mainVolume;

    private RayTracedReflections rtReflections;
    private ScreenSpaceReflection ssReflections;
    private GlobalIllumination rtGI;
    
    // 性能历史记录
    private Queue<float> frameTimeHistory = new Queue<float>();
    private const int HISTORY_FRAMES = 30;
    private float avgFrameTime;

    void Start()
    {
        mainVolume.profile.TryGet(out rtReflections);
        mainVolume.profile.TryGet(out ssReflections);
        mainVolume.profile.TryGet(out rtGI);
        
        // 每2秒检查一次性能
        InvokeRepeating(nameof(EvaluatePerformance), 2f, 2f);
    }

    void Update()
    {
        // 记录帧时间历史
        frameTimeHistory.Enqueue(Time.unscaledDeltaTime * 1000f);
        if (frameTimeHistory.Count > HISTORY_FRAMES)
            frameTimeHistory.Dequeue();
    }

    void EvaluatePerformance()
    {
        if (frameTimeHistory.Count == 0) return;
        
        avgFrameTime = frameTimeHistory.Average();
        float overhead = avgFrameTime - frameTimeBudgetMs;
        
        if (overhead > 5f)
        {
            // 严重超出预算，降级
            DegradeQuality();
        }
        else if (overhead > 2f)
        {
            // 略微超出，小幅降级
            MinorDegradeQuality();
        }
        else if (overhead < -3f)
        {
            // 帧时间有余量，尝试升级
            UpgradeQuality();
        }
        
        Debug.Log($"[AdaptiveRT] AvgFrameTime: {avgFrameTime:F2}ms, Budget: {frameTimeBudgetMs}ms");
    }

    void DegradeQuality()
    {
        // 优先关闭开销最大的RTGI
        if (rtGI != null && rtGI.active)
        {
            rtGI.active = false;
            Debug.Log("[AdaptiveRT] Disabled RT GI");
            return;
        }
        
        // 其次降低反射质量
        if (rtReflections != null && rtReflections.sampleCount.value > 1)
        {
            rtReflections.sampleCount.value--;
            Debug.Log($"[AdaptiveRT] RT Reflections samples: {rtReflections.sampleCount.value}");
            return;
        }
        
        // 最后切换到屏幕空间反射
        if (rtReflections != null && rtReflections.active)
        {
            rtReflections.active = false;
            if (ssReflections != null) ssReflections.active = true;
            Debug.Log("[AdaptiveRT] Fallback to SSR");
        }
    }

    void MinorDegradeQuality()
    {
        if (rtReflections != null && rtReflections.active)
        {
            rtReflections.mode.value = RayTracingMode.Performance;
        }
    }

    void UpgradeQuality()
    {
        // 逐步升级：先升反射，再开RTGI
        if (rtReflections != null && !rtReflections.active)
        {
            rtReflections.active = true;
            if (ssReflections != null) ssReflections.active = false;
            Debug.Log("[AdaptiveRT] Enabled RT Reflections");
            return;
        }
        
        if (rtGI != null && !rtGI.active)
        {
            rtGI.active = true;
            Debug.Log("[AdaptiveRT] Enabled RT GI");
        }
    }
}

// 扩展方法：Queue<float>的平均值
public static class QueueExtensions
{
    public static float Average(this Queue<float> queue)
    {
        float sum = 0;
        foreach (var v in queue) sum += v;
        return sum / queue.Count;
    }
}
```

---

## 五、移动端光线追踪策略

### 5.1 移动端硬件现状

目前支持光追的移动端GPU（截至2024年）：
- **Apple A17 Pro（iPhone 15 Pro）**：Metal 3 硬件光追
- **ARM Immortalis-G715/G720**：基于Vulkan的硬件光追
- **高通 Adreno 740+（骁龙8 Gen 2）**：支持Vulkan光追扩展

### 5.2 移动端光追替代方案

对于不支持硬件光追的中低端设备，可用以下技术模拟：

```hlsl
// 移动端软件光追 - 体素化场景光追（精度低但兼容性好）
// 基于SDF（有符号距离场）的光线步进
Shader "Game/SDF_SoftShadow"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _ShadowHardness ("Shadow Hardness", Range(2, 64)) = 8
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float2 uv         : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 positionWS : TEXCOORD0;
                float3 normalWS   : TEXCOORD1;
                float2 uv         : TEXCOORD2;
            };

            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);
            float _ShadowHardness;

            // SDF球体
            float sdSphere(float3 p, float3 center, float r)
            {
                return length(p - center) - r;
            }

            // 场景SDF（简化示例，实际应使用预计算SDF纹理）
            float sceneSDF(float3 p)
            {
                float d = sdSphere(p, float3(0, 0.5, 0), 0.5);
                d = min(d, p.y); // 地面
                return d;
            }

            // 软阴影光线步进
            float softShadow(float3 ro, float3 rd, float mint, float maxt, float k)
            {
                float res = 1.0;
                float t = mint;
                
                for (int i = 0; i < 32; i++)
                {
                    float h = sceneSDF(ro + rd * t);
                    if (h < 0.001) return 0.0;
                    res = min(res, k * h / t);
                    t += clamp(h, 0.02, 0.2);
                    if (t > maxt) break;
                }
                return saturate(res);
            }

            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionWS = TransformObjectToWorld(IN.positionOS.xyz);
                OUT.positionCS = TransformWorldToHClip(OUT.positionWS);
                OUT.normalWS   = TransformObjectToWorldNormal(IN.normalOS);
                OUT.uv         = IN.uv;
                return OUT;
            }

            half4 frag(Varyings IN) : SV_Target
            {
                float3 albedo = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv).rgb;
                float3 normal = normalize(IN.normalWS);
                
                // 获取主光源方向
                Light mainLight = GetMainLight();
                float3 lightDir = normalize(mainLight.direction);
                
                // SDF软阴影（替代硬件光追阴影）
                float shadow = softShadow(
                    IN.positionWS + normal * 0.01, // 偏移避免自遮挡
                    lightDir,
                    0.02,  // mint
                    5.0,   // maxt
                    _ShadowHardness
                );
                
                // Lambert漫反射
                float NdotL = max(0, dot(normal, lightDir));
                float3 color = albedo * NdotL * shadow * mainLight.color.rgb;
                
                return half4(color, 1);
            }
            ENDHLSL
        }
    }
}
```

### 5.3 Metal 3 光追（Apple 平台）

```csharp
// Unity Metal光追检测与配置
public class MetalRayTracingSetup : MonoBehaviour
{
    void Start()
    {
#if UNITY_IOS || UNITY_TVOS
        bool metalRTSupported = SystemInfo.supportsRayTracing;
        
        if (metalRTSupported)
        {
            Debug.Log("Metal Ray Tracing supported (A17 Pro or newer)");
            EnableMobileRayTracing();
        }
        else
        {
            Debug.Log("Falling back to software ray tracing approximations");
            EnableFallbackMode();
        }
#endif
    }

    void EnableMobileRayTracing()
    {
        // 移动端只使用最轻量的光追特性
        // 例如：只用光追阴影，关闭RTGI和光追反射
        var volume = FindObjectOfType<Volume>();
        if (volume == null) return;
        
        // 仅启用光追阴影（开销最小）
        if (volume.profile.TryGet<ScreenSpaceShadows>(out var shadows))
        {
            // 使用1个采样的超轻量RT阴影
        }
    }

    void EnableFallbackMode()
    {
        // 降级到屏幕空间技术
    }
}
```

---

## 六、降噪技术详解

### 6.1 时域降噪（TAA-Based Denoising）

低采样数的光追结果充满噪声，时域降噪利用历史帧数据进行累积：

```hlsl
// 时域累积降噪核心逻辑（简化版）
float4 TemporalAccumulateRT(
    Texture2D<float4> currentFrame,   // 当前帧（噪声）
    Texture2D<float4> historyBuffer,  // 历史帧（降噪后）
    Texture2D<float2> motionVectors,  // 运动向量
    float2 uv,
    float blendFactor               // 新旧帧混合因子（0.05-0.1）
)
{
    float2 motion = motionVectors.Sample(samplerLinear, uv);
    float2 historyUV = uv - motion;
    
    float4 current = currentFrame.Sample(samplerLinear, uv);
    float4 history = historyBuffer.Sample(samplerLinear, historyUV);
    
    // 邻域夹取：防止历史帧幽灵
    float4 neighborMin = current;
    float4 neighborMax = current;
    
    // 3x3邻域最小/最大值
    for (int x = -1; x <= 1; x++)
    {
        for (int y = -1; y <= 1; y++)
        {
            float4 sample = currentFrame.Sample(samplerLinear, 
                uv + float2(x, y) * _TexelSize.xy);
            neighborMin = min(neighborMin, sample);
            neighborMax = max(neighborMax, sample);
        }
    }
    
    // 将历史帧夹取到当前帧的邻域范围内
    history = clamp(history, neighborMin, neighborMax);
    
    // 指数移动平均混合
    return lerp(history, current, blendFactor);
}
```

### 6.2 DLSS/FSR 与光追联合使用

```
DLSS 3.5 Ray Reconstruction 流程：
低分辨率光追 → DLSS超分 → DLSS光追重建（专用神经网络降噪）→ 最终图像

优势：
- 光追在 1/4 分辨率下计算 → 性能提升 4x
- AI重建恢复高频细节（反射边缘、高光）
- 比传统TAA降噪效果更好
```

---

## 七、性能优化最佳实践

### 7.1 光追性能开销分布

```
典型场景光追开销（RTX 3080, 1440p）：
├── RT Reflections (1 SPP)    ≈ 2.5ms
├── RT Shadows (1 SPP)        ≈ 1.8ms  
├── RTGI (1 SPP, 半分辨率)    ≈ 3.2ms
├── RT AO (1 SPP)             ≈ 1.2ms
├── 降噪（时域 + 空间）        ≈ 2.0ms
└── TLAS重建（动态物体）       ≈ 0.5ms
Total                         ≈ 11.2ms
```

### 7.2 加速结构优化策略

```csharp
/// <summary>
/// TLAS管理器：精细控制加速结构更新策略
/// </summary>
public class TLASUpdateManager : MonoBehaviour
{
    [Header("更新策略")]
    [SerializeField] private bool separateStaticDynamic = true;
    [SerializeField] private int dynamicObjectsPerFrame = 10;
    
    private List<Renderer> staticRenderers  = new List<Renderer>();
    private List<Renderer> dynamicRenderers = new List<Renderer>();
    private int dynamicUpdateIndex = 0;

    void Start()
    {
        ClassifyRenderers();
    }

    void ClassifyRenderers()
    {
        foreach (var r in FindObjectsOfType<Renderer>())
        {
            if (r.gameObject.isStatic)
                staticRenderers.Add(r);
            else
                dynamicRenderers.Add(r);
        }
        
        Debug.Log($"Static: {staticRenderers.Count}, Dynamic: {dynamicRenderers.Count}");
    }

    void Update()
    {
        // 静态物体：只在场景加载时构建一次BLAS
        // 动态物体：分帧更新，每帧只更新部分动态物体
        UpdateDynamicSubset();
    }

    void UpdateDynamicSubset()
    {
        int endIndex = Mathf.Min(
            dynamicUpdateIndex + dynamicObjectsPerFrame, 
            dynamicRenderers.Count
        );
        
        for (int i = dynamicUpdateIndex; i < endIndex; i++)
        {
            // 标记需要更新BLAS的渲染器
            // Unity HDRP会自动处理，但可以通过设置控制精细度
            var renderer = dynamicRenderers[i];
            // renderer.rayTracingMode = RayTracingMode.DynamicTransform;
        }
        
        dynamicUpdateIndex = endIndex % dynamicRenderers.Count;
    }
}
```

### 7.3 光追物体层级剔除

```csharp
/// <summary>
/// 光追视距剔除：远处物体不参与光追计算
/// </summary>
public class RayTracingCullingSystem : MonoBehaviour
{
    [Header("剔除设置")]
    [SerializeField] private float rtMaxDistance = 80f;
    [SerializeField] private LayerMask rtLayer;
    
    private Camera mainCamera;
    private List<Renderer> rtRenderers = new List<Renderer>();

    void Start()
    {
        mainCamera = Camera.main;
        rtRenderers.AddRange(FindObjectsOfType<Renderer>());
        InvokeRepeating(nameof(UpdateRTCulling), 0f, 0.2f); // 每200ms更新一次
    }

    void UpdateRTCulling()
    {
        Vector3 camPos = mainCamera.transform.position;
        
        foreach (var renderer in rtRenderers)
        {
            if (renderer == null) continue;
            
            float distance = Vector3.Distance(camPos, renderer.bounds.center);
            bool shouldRT = distance < rtMaxDistance;
            
            // 控制物体是否参与光追
            renderer.rayTracingMode = shouldRT 
                ? UnityEngine.Experimental.Rendering.RayTracingMode.DynamicTransform
                : UnityEngine.Experimental.Rendering.RayTracingMode.Off;
        }
    }
}
```

---

## 八、调试与分析工具

### 8.1 HDRP 光追调试视图

Unity HDRP 提供内置调试视图：
```
Window → Rendering → Render Pipeline Debugger
→ Lighting → Ray Tracing Debug
  ├── RT Reflections Buffer（查看反射缓冲区）
  ├── RT Shadow Map（查看光追阴影）
  └── GI Buffer（查看间接光照）
```

### 8.2 RenderDoc 抓帧分析

```
光追帧分析步骤：
1. 启动 RenderDoc，附加到 Unity 进程
2. 抓取包含光追的帧
3. 查看 Pipeline State → Ray Tracing Pipeline
4. 检查 BLAS/TLAS 数量与内存占用
5. 分析各个 RT Shader 的执行时间

关键指标：
- BLAS 构建时间
- TLAS 实例数量（过多影响遍历效率）
- 每个光追阶段的 GPU 时间
```

---

## 九、最佳实践总结

### 9.1 设计原则

| 原则 | 建议 |
|------|------|
| **渐进式降级** | 从RTGI→RT反射→RT阴影依次降级，而非全关 |
| **半分辨率计算** | RTGI和RT AO在半分辨率计算，降噪后升采样 |
| **静动分离** | 静态BLAS只构建一次，动态BLAS分帧更新 |
| **距离剔除** | 超出阈值距离的物体关闭RT参与 |
| **时域积累** | 充分利用TAA降噪，单帧1SPP即可 |
| **平台适配** | 移动端只用最轻量的RT阴影或完全降级 |

### 9.2 质量档位参考

```
PC端质量档位建议：

Ultra（RTX 3080以上）：
  - RT Reflections: 2SPP, 2 Bounce
  - RT Shadows: 4SPP  
  - RTGI: 1SPP, 1 Bounce, 全分辨率
  - RT AO: 2SPP

High（RTX 2070以上）：
  - RT Reflections: 1SPP, 1 Bounce
  - RT Shadows: 1SPP
  - RTGI: 1SPP, 半分辨率
  - SSAO（非RT）

Medium（非RT显卡）：
  - SSR（屏幕空间反射）
  - ShadowMap阴影
  - 烘焙GI + 动态探针
  - SSAO

Low：
  - 完全关闭光追
  - 所有降级为传统技术
```

### 9.3 工程落地 Checklist

- [ ] 检测硬件支持，实现优雅降级
- [ ] 配置质量档位系统
- [ ] 实现自适应性能调节器
- [ ] TLAS 按静态/动态分离管理
- [ ] 设置光追距离剔除
- [ ] 针对不同平台测试帧率
- [ ] Profile各RT特性的开销
- [ ] 实现运行时质量切换API
- [ ] 移动端单独测试（Apple/ARM光追）
- [ ] 集成降噪（TAA/DLSS/FSR）

---

## 总结

实时光线追踪是游戏渲染的革命性突破，通过硬件加速、智能降噪和自适应质量控制，现代游戏已能在60fps下实现高质量的反射、软阴影和全局光照。关键在于：**不追求完美的物理精度，而是在视觉效果与性能开销之间寻找最优的工程平衡点**。随着移动端硬件光追逐渐普及，光线追踪技术栈将成为游戏客户端开发的必备技能之一。
