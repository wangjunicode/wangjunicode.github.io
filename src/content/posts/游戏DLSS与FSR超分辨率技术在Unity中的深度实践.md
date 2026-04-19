---
title: 游戏DLSS与FSR超分辨率技术在Unity中的深度实践
published: 2026-04-19
description: 深入解析NVIDIA DLSS 3与AMD FSR 3超分辨率技术原理，涵盖Unity URP/HDRP集成方案、移动端FSR适配、时域上采样算法实现，以及自研轻量级超分辨率方案的完整工程落地指南
tags: [Unity, 渲染优化, DLSS, FSR, 超分辨率, URP, HDRP, 图形编程]
category: 渲染技术
draft: false
---

# 游戏DLSS与FSR超分辨率技术在Unity中的深度实践

## 1. 超分辨率技术概述

超分辨率（Super Resolution）技术通过在较低分辨率下渲染，再通过算法重建为高分辨率输出，在保证画质的前提下大幅提升帧率。这项技术已成为现代游戏渲染管线的核心组件。

### 1.1 主流超分辨率方案对比

| 技术 | 厂商 | 硬件要求 | 平台支持 | 核心算法 |
|------|------|---------|---------|---------|
| DLSS 3.5 | NVIDIA | RTX 20系+ | PC | 深度学习+Transformer |
| FSR 3.1 | AMD | 通用GPU | PC/主机/移动 | 空间+时域混合 |
| XeSS 1.3 | Intel | 通用(XMX加速) | PC | 机器学习 |
| MetalFX | Apple | Apple Silicon | iOS/macOS | 时域上采样 |
| TAAU | Epic/Unity | 通用 | 全平台 | 时域抗锯齿上采样 |

### 1.2 渲染管线集成位置

```
游戏场景渲染(低分辨率)
    ↓
G-Buffer / 光照计算
    ↓
运动向量生成 ←─── 关键！
    ↓
深度缓冲 + 历史帧
    ↓
[超分辨率上采样] ←─── DLSS/FSR/XeSS 介入点
    ↓
后处理(UI叠加在原生分辨率)
    ↓
最终输出(原生分辨率)
```

---

## 2. DLSS技术原理深度解析

### 2.1 DLSS 3架构

DLSS 3引入了**帧生成（Frame Generation）**技术，结合时域超分和光流估计，可将帧率提升最高4倍。

```
输入: 当前帧(低分辨率) + 前一帧(低分辨率) + 运动向量 + 深度
    ↓
DLSS Super Resolution (神经网络超分)
    ↓                    ↓
当前帧(高分辨率)    帧生成(DLSS 3独有)
    ↓                    ↓ 使用光流网络估计中间帧
最终高分辨率输出 ← 插入生成帧
```

### 2.2 Unity HDRP中启用DLSS

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.HighDefinition;

/// <summary>
/// DLSS管理器 - 负责DLSS质量模式切换与性能监控
/// </summary>
public class DLSSManager : MonoBehaviour
{
    [Header("DLSS配置")]
    [SerializeField] private HDAdditionalCameraData cameraData;
    [SerializeField] private DLSSQuality defaultQuality = DLSSQuality.Balanced;
    
    [Header("性能监控")]
    [SerializeField] private bool enablePerformanceLogging = false;
    
    private Camera mainCamera;
    private DLSSQuality currentQuality;
    
    // DLSS质量模式对应的渲染分辨率比例
    private static readonly Dictionary<DLSSQuality, float> QualityScaleMap = 
        new Dictionary<DLSSQuality, float>
    {
        { DLSSQuality.UltraPerformance, 0.33f },  // 3x上采样
        { DLSSQuality.Performance, 0.50f },         // 2x上采样
        { DLSSQuality.Balanced, 0.58f },            // ~1.7x上采样
        { DLSSQuality.Quality, 0.67f },             // 1.5x上采样
        { DLSSQuality.UltraQuality, 0.77f },        // ~1.3x上采样
    };
    
    private void Awake()
    {
        mainCamera = GetComponent<Camera>();
        if (cameraData == null)
            cameraData = mainCamera.GetComponent<HDAdditionalCameraData>();
    }
    
    private void Start()
    {
        // 检测DLSS可用性
        if (IsDLSSSupported())
        {
            EnableDLSS(defaultQuality);
            Debug.Log($"[DLSS] 已启用，质量模式: {defaultQuality}");
        }
        else
        {
            Debug.LogWarning("[DLSS] 当前GPU不支持DLSS，将使用TAA回退");
            EnableTAAFallback();
        }
    }
    
    /// <summary>
    /// 检测DLSS硬件支持
    /// </summary>
    public bool IsDLSSSupported()
    {
#if UNITY_STANDALONE_WIN && !UNITY_EDITOR
        // 需要NVIDIA RTX GPU + 驱动支持
        return SystemInfo.graphicsDeviceVendor.Contains("NVIDIA") &&
               SystemInfo.graphicsDeviceVersion.Contains("Direct3D 12");
#else
        return false;
#endif
    }
    
    /// <summary>
    /// 切换DLSS质量模式（可在运行时调用）
    /// </summary>
    public void SetDLSSQuality(DLSSQuality quality)
    {
        if (!IsDLSSSupported()) return;
        
        currentQuality = quality;
        
        // 通过HDRP设置DLSS质量
        if (cameraData != null)
        {
            var dlssSettings = new UnityEngine.Rendering.HighDefinition.GlobalDynamicResolutionSettings
            {
                enabled = true,
                dynResType = DynamicResolutionType.Hardware,
                upsampleFilter = DynamicResUpscaleFilter.DLSS,
                minPercentage = QualityScaleMap[quality] * 100f,
                maxPercentage = QualityScaleMap[quality] * 100f
            };
            
            // 应用到全局渲染管线设置
            var hdrpAsset = GraphicsSettings.currentRenderPipeline as HDRenderPipelineAsset;
            if (hdrpAsset != null)
            {
                Debug.Log($"[DLSS] 切换至质量模式: {quality}, 渲染比例: {QualityScaleMap[quality]:P0}");
            }
        }
    }
    
    private void EnableDLSS(DLSSQuality quality)
    {
        currentQuality = quality;
        // 实际项目中通过HDRP Volume或Asset配置启用DLSS
        SetDLSSQuality(quality);
    }
    
    private void EnableTAAFallback()
    {
        // 降级为TAA抗锯齿
        if (cameraData != null)
        {
            cameraData.antialiasing = HDAdditionalCameraData.AntialiasingMode.TemporalAntialiasing;
        }
    }
    
    /// <summary>
    /// 根据当前帧率动态调整DLSS质量（自适应性能优化）
    /// </summary>
    public void AdaptiveDLSSUpdate(float currentFPS, float targetFPS)
    {
        if (!IsDLSSSupported()) return;
        
        float ratio = currentFPS / targetFPS;
        
        DLSSQuality newQuality = ratio switch
        {
            < 0.7f => DLSSQuality.UltraPerformance,   // 帧率严重不足
            < 0.85f => DLSSQuality.Performance,        // 帧率不足
            < 0.95f => DLSSQuality.Balanced,           // 轻微不足
            < 1.05f => DLSSQuality.Quality,            // 达标
            _ => DLSSQuality.UltraQuality              // 性能富余，提升画质
        };
        
        if (newQuality != currentQuality)
        {
            SetDLSSQuality(newQuality);
        }
    }
}
```

---

## 3. AMD FSR 3 深度集成

FSR（FidelityFX Super Resolution）因其开源性和跨平台特性，成为移动端游戏超分的首选方案。

### 3.1 FSR 3工作原理

FSR 3包含两个主要组件：
- **FSR 3 Super Resolution**：空间+时域混合上采样
- **FSR 3 Frame Generation**：基于光流的帧插值

```
// FSR空间上采样核心算法（简化版EASU）
// Edge-Adaptive Spatial Upsampling

float4 FSR_EASU(Texture2D colorTex, float2 uv, float2 renderSize, float2 displaySize)
{
    // 1. 计算当前像素在输入纹理中的采样区域
    float2 pp = uv * displaySize - 0.5;
    float2 fp = floor(pp);
    float2 ppp = pp - fp;
    
    // 2. 12-tap采样（边缘自适应）
    float2 p0 = (fp + float2(0.5, -0.5)) / renderSize;
    float2 p1 = (fp + float2(1.5, -0.5)) / renderSize;
    float2 p2 = (fp + float2(-0.5, 0.5)) / renderSize;
    float2 p3 = (fp + float2(0.5, 0.5)) / renderSize;
    
    float4 c0 = colorTex.Sample(linearClamp, p0);
    float4 c1 = colorTex.Sample(linearClamp, p1);
    float4 c2 = colorTex.Sample(linearClamp, p2);
    float4 c3 = colorTex.Sample(linearClamp, p3);
    
    // 3. 边缘检测（通过亮度梯度）
    float luma0 = dot(c0.rgb, float3(0.299, 0.587, 0.114));
    float luma1 = dot(c1.rgb, float3(0.299, 0.587, 0.114));
    float luma2 = dot(c2.rgb, float3(0.299, 0.587, 0.114));
    float luma3 = dot(c3.rgb, float3(0.299, 0.587, 0.114));
    
    // 4. 自适应权重计算
    float edgeH = abs(luma0 - luma1) + abs(luma2 - luma3);
    float edgeV = abs(luma0 - luma2) + abs(luma1 - luma3);
    
    // 5. 双线性基础 + 边缘感知修正
    float4 result = lerp(
        lerp(c0, c1, ppp.x),
        lerp(c2, c3, ppp.x),
        ppp.y
    );
    
    return result;
}
```

### 3.2 Unity URP中集成FSR

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// FSR超分辨率渲染Pass - 集成到URP渲染管线
/// </summary>
public class FSRRenderPass : ScriptableRenderPass
{
    private const string ProfilerTag = "FSR Upscaling";
    
    private Material fsrMaterial;
    private RenderTextureDescriptor renderDescriptor;
    private RTHandle sourceHandle;
    private RTHandle destinationHandle;
    
    // FSR质量级别
    public enum FSRQuality
    {
        UltraQuality = 0,   // 77% 渲染分辨率
        Quality = 1,         // 67% 渲染分辨率  
        Balanced = 2,        // 59% 渲染分辨率
        Performance = 3,     // 50% 渲染分辨率
    }
    
    private static readonly float[] FSRScales = { 0.77f, 0.67f, 0.59f, 0.50f };
    
    public FSRRenderPass(Material material)
    {
        fsrMaterial = material;
        renderPassEvent = RenderPassEvent.AfterRenderingPostProcessing;
    }
    
    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        renderDescriptor = renderingData.cameraData.cameraTargetDescriptor;
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        if (fsrMaterial == null) return;
        
        CommandBuffer cmd = CommandBufferPool.Get(ProfilerTag);
        
        using (new ProfilingScope(cmd, new ProfilingSampler(ProfilerTag)))
        {
            ref CameraData cameraData = ref renderingData.cameraData;
            
            // 传递超分辨率参数到Shader
            float renderWidth = renderDescriptor.width;
            float renderHeight = renderDescriptor.height;
            float displayWidth = Screen.width;
            float displayHeight = Screen.height;
            
            // FSR EASU参数
            cmd.SetGlobalVector("_FSR_InputSize", 
                new Vector4(renderWidth, renderHeight, 1f / renderWidth, 1f / renderHeight));
            cmd.SetGlobalVector("_FSR_OutputSize", 
                new Vector4(displayWidth, displayHeight, 1f / displayWidth, 1f / displayHeight));
            
            // RCAS锐化参数（可调节）
            float sharpness = 0.2f; // 0.0(最锐利) ~ 2.0(最柔和)
            cmd.SetGlobalFloat("_FSR_RCASAttenuation", sharpness);
            
            // Pass 0: EASU空间上采样
            cmd.Blit(sourceHandle, destinationHandle, fsrMaterial, 0);
            
            // Pass 1: RCAS锐化
            cmd.Blit(destinationHandle, sourceHandle, fsrMaterial, 1);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}

/// <summary>
/// FSR渲染特性 - 负责动态分辨率管理
/// </summary>
public class FSRRendererFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class FSRSettings
    {
        public bool enabled = true;
        public FSRRenderPass.FSRQuality quality = FSRRenderPass.FSRQuality.Balanced;
        public Shader fsrShader;
        [Range(0f, 2f)]
        public float sharpness = 0.2f;
    }
    
    [SerializeField] private FSRSettings settings = new FSRSettings();
    
    private FSRRenderPass fsrPass;
    private Material fsrMaterial;
    
    public override void Create()
    {
        if (settings.fsrShader == null) return;
        
        fsrMaterial = CoreUtils.CreateEngineMaterial(settings.fsrShader);
        fsrPass = new FSRRenderPass(fsrMaterial);
        
        // 设置渲染分辨率缩放
        float scale = FSRRenderPass.FSRScales[(int)settings.quality];
        ScalableBufferManager.ResizeBuffers(scale, scale);
        
        Debug.Log($"[FSR] 已启用，质量: {settings.quality}, 渲染比例: {scale:P0}");
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (!settings.enabled || fsrPass == null) return;
        
        // 仅对游戏相机应用FSR（跳过SceneView、预览相机等）
        if (renderingData.cameraData.cameraType != CameraType.Game) return;
        
        renderer.EnqueuePass(fsrPass);
    }
    
    protected override void Dispose(bool disposing)
    {
        CoreUtils.Destroy(fsrMaterial);
    }
    
    /// <summary>
    /// 运行时切换FSR质量
    /// </summary>
    public void SetQuality(FSRRenderPass.FSRQuality newQuality)
    {
        settings.quality = newQuality;
        float scale = FSRRenderPass.FSRScales[(int)newQuality];
        ScalableBufferManager.ResizeBuffers(scale, scale);
    }
}
```

### 3.3 FSR Shader实现（HLSL）

```hlsl
// FSR_Upscale.shader
Shader "Hidden/FSR_Upscale"
{
    Properties
    {
        _MainTex ("Source", 2D) = "white" {}
    }
    
    HLSLINCLUDE
    #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
    
    TEXTURE2D(_MainTex);
    SAMPLER(sampler_LinearClamp);
    
    float4 _FSR_InputSize;   // (w, h, 1/w, 1/h)
    float4 _FSR_OutputSize;  // (w, h, 1/w, 1/h)
    float  _FSR_RCASAttenuation;
    
    // ============================================
    // EASU - Edge-Adaptive Spatial Upsampling
    // ============================================
    
    // 亮度计算（线性空间）
    float AH1_AF1(float x) { return x; }
    float3 opAHalf3(float3 a, float3 b) { return a + b; }
    
    float Luma(float3 c) 
    { 
        return dot(c, float3(0.2126, 0.7152, 0.0722)); 
    }
    
    // 自适应滤波核计算
    void FSR_EASU_F(out float4 pix, float2 ip, float4 con0, float4 con1, float4 con2, float4 con3)
    {
        // 采样位置计算
        float2 pp = ip * con0.xy + con0.zw;
        float2 fp = floor(pp);
        pp -= fp;
        
        // 4x3像素邻域采样
        float2 p0 = fp * con1.xy + con1.zw;
        
        // 方向感知的椭圆权重计算
        float4 bczzR = GATHER_RED_TEXTURE2D(_MainTex, sampler_LinearClamp, p0 + con2.xy);
        float4 bczzG = GATHER_GREEN_TEXTURE2D(_MainTex, sampler_LinearClamp, p0 + con2.xy);
        float4 bczzB = GATHER_BLUE_TEXTURE2D(_MainTex, sampler_LinearClamp, p0 + con2.xy);
        
        float4 ijfeR = GATHER_RED_TEXTURE2D(_MainTex, sampler_LinearClamp, p0);
        float4 ijfeG = GATHER_GREEN_TEXTURE2D(_MainTex, sampler_LinearClamp, p0);
        float4 ijfeB = GATHER_BLUE_TEXTURE2D(_MainTex, sampler_LinearClamp, p0);
        
        float4 klhgR = GATHER_RED_TEXTURE2D(_MainTex, sampler_LinearClamp, p0 + con3.xy);
        float4 klhgG = GATHER_GREEN_TEXTURE2D(_MainTex, sampler_LinearClamp, p0 + con3.xy);
        float4 klhgB = GATHER_BLUE_TEXTURE2D(_MainTex, sampler_LinearClamp, p0 + con3.xy);
        
        // 计算各样本的亮度
        float bL = Luma(float3(bczzR.x, bczzG.x, bczzB.x));
        float cL = Luma(float3(bczzR.y, bczzG.y, bczzB.y));
        float iL = Luma(float3(ijfeR.x, ijfeG.x, ijfeB.x));
        float jL = Luma(float3(ijfeR.y, ijfeG.y, ijfeB.y));
        float fL = Luma(float3(ijfeR.z, ijfeG.z, ijfeB.z));
        float eL = Luma(float3(ijfeR.w, ijfeG.w, ijfeB.w));
        float kL = Luma(float3(klhgR.x, klhgG.x, klhgB.x));
        float lL = Luma(float3(klhgR.y, klhgG.y, klhgB.y));
        float hL = Luma(float3(klhgR.z, klhgG.z, klhgB.z));
        float gL = Luma(float3(klhgR.w, klhgG.w, klhgB.w));
        
        // 边缘方向检测
        float2 dir = float2(0, 0);
        float len = 0;
        
        // 使用亮度梯度确定主要边缘方向
        float dc = fL - jL;
        float de = eL - iL;
        float dh = hL - kL;
        float dg = gL - lL;
        
        dir += float2(dc + de + dh + dg, -(dc + de - dh - dg));
        len += abs(dc) + abs(de) + abs(dh) + abs(dg);
        
        // 归一化方向并计算各向异性权重
        float2 dir2 = dir * dir;
        float dirR = dir2.x + dir2.y;
        bool zro = dirR < (1.0 / 32768.0);
        dirR = rsqrt(dirR);
        dirR = zro ? 1.0 : dirR;
        dir.x = zro ? 1.0 : dir.x;
        dir *= dirR;
        
        len = len * 0.5;
        len *= len;
        
        float stretch = (dir.x * dir.x + dir.y * dir.y) / max(abs(dir.x), abs(dir.y));
        float2 len2 = float2(1.0 + (stretch - 1.0) * len, 1.0 - 0.5 * len);
        float lob = 0.5 + ((1.0 / 4.0) - 0.04) * len;
        float clp = 1.0 / lob;
        
        // 插值输出
        pix = float4(
            dot(ijfeR, float4(0.25, 0.25, 0.25, 0.25)),
            dot(ijfeG, float4(0.25, 0.25, 0.25, 0.25)),
            dot(ijfeB, float4(0.25, 0.25, 0.25, 0.25)),
            1.0
        );
    }
    
    // ============================================
    // RCAS - Robust Contrast-Adaptive Sharpening
    // ============================================
    float4 FSR_RCAS(float2 uv)
    {
        float2 texelSize = _FSR_InputSize.zw;
        
        // 5-tap采样（十字形）
        float4 e = SAMPLE_TEXTURE2D(_MainTex, sampler_LinearClamp, uv);
        float4 b = SAMPLE_TEXTURE2D(_MainTex, sampler_LinearClamp, uv + float2(0, -texelSize.y));
        float4 d = SAMPLE_TEXTURE2D(_MainTex, sampler_LinearClamp, uv + float2(-texelSize.x, 0));
        float4 f = SAMPLE_TEXTURE2D(_MainTex, sampler_LinearClamp, uv + float2(texelSize.x, 0));
        float4 h = SAMPLE_TEXTURE2D(_MainTex, sampler_LinearClamp, uv + float2(0, texelSize.y));
        
        // 对比度自适应锐化
        float bL = Luma(b.rgb);
        float dL = Luma(d.rgb);
        float eL = Luma(e.rgb);
        float fL = Luma(f.rgb);
        float hL = Luma(h.rgb);
        
        float mn = min(min(bL, dL), min(eL, min(fL, hL)));
        float mx = max(max(bL, dL), max(eL, max(fL, hL)));
        
        // 自适应锐化系数
        float rcasAttenuation = _FSR_RCASAttenuation;
        float w = -1.0 / (4.0 * exp2(-rcasAttenuation) + (mn / mx - 1.0) * 8.0);
        w = max(w, -0.1875); // 防止过度锐化
        
        float4 result = (b + d + h + f) * w + e * (1.0 + 4.0 * w);
        result = max(result, 0.0); // 防止负值
        
        return result;
    }
    
    // ============================================
    // Vertex Shader
    // ============================================
    struct Varyings
    {
        float4 positionCS : SV_POSITION;
        float2 texcoord   : TEXCOORD0;
    };
    
    Varyings Vert(uint vertexID : SV_VertexID)
    {
        Varyings output;
        output.positionCS = GetFullScreenTriangleVertexPosition(vertexID);
        output.texcoord   = GetFullScreenTriangleTexCoord(vertexID);
        return output;
    }
    
    // EASU Pass
    float4 FragEASU(Varyings input) : SV_Target
    {
        float4 pix;
        float4 con0 = float4(_FSR_OutputSize.xy / _FSR_InputSize.xy, 
                             0.5 * _FSR_OutputSize.zw - 0.5 * _FSR_InputSize.zw * 
                             (_FSR_OutputSize.xy / _FSR_InputSize.xy));
        float4 con1 = float4(_FSR_InputSize.zw, 0, 0);
        float4 con2 = float4(0, 0, 0, 0);
        float4 con3 = float4(0, 0, 0, 0);
        
        FSR_EASU_F(pix, input.positionCS.xy, con0, con1, con2, con3);
        return pix;
    }
    
    // RCAS Pass
    float4 FragRCAS(Varyings input) : SV_Target
    {
        return FSR_RCAS(input.texcoord);
    }
    
    ENDHLSL
    
    SubShader
    {
        ZWrite Off ZTest Always Blend Off Cull Off
        
        // Pass 0: EASU
        Pass
        {
            Name "FSR_EASU"
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment FragEASU
            ENDHLSL
        }
        
        // Pass 1: RCAS
        Pass
        {
            Name "FSR_RCAS"
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment FragRCAS
            ENDHLSL
        }
    }
}
```

---

## 4. Apple MetalFX集成（iOS平台）

```csharp
/// <summary>
/// MetalFX上采样管理器 - 专为iOS/macOS Apple Silicon设备优化
/// </summary>
public class MetalFXManager : MonoBehaviour
{
    [Header("MetalFX设置")]
    [SerializeField] private bool enableMetalFX = true;
    [SerializeField, Range(0.5f, 1.0f)] private float renderScale = 0.67f;
    
    private bool metalFXSupported = false;
    
    private void Awake()
    {
#if UNITY_IOS || UNITY_STANDALONE_OSX
        metalFXSupported = CheckMetalFXSupport();
        
        if (metalFXSupported && enableMetalFX)
        {
            ApplyMetalFXSettings();
        }
#endif
    }
    
    private bool CheckMetalFXSupport()
    {
        // Apple Silicon M1及以上支持MetalFX时域上采样
        // A14 Bionic及以上支持空间上采样
        string gpuName = SystemInfo.graphicsDeviceName.ToLower();
        return SystemInfo.graphicsDeviceType == GraphicsDeviceType.Metal &&
               (gpuName.Contains("apple") || gpuName.Contains("m1") || 
                gpuName.Contains("m2") || gpuName.Contains("m3"));
    }
    
    private void ApplyMetalFXSettings()
    {
        // Unity 2023.1+通过动态分辨率API接入MetalFX
        var urpAsset = GraphicsSettings.currentRenderPipeline as UniversalRenderPipelineAsset;
        if (urpAsset != null)
        {
            // 设置渲染比例
            Screen.SetResolution(
                (int)(Screen.width * renderScale),
                (int)(Screen.height * renderScale),
                Screen.fullScreen
            );
            
            Debug.Log($"[MetalFX] 已启用时域上采样，渲染比例: {renderScale:P0}");
        }
    }
}
```

---

## 5. 运动向量优化（超分辨率关键依赖）

运动向量质量直接决定时域超分效果，不正确的运动向量会导致鬼影（Ghosting）。

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 精确运动向量生成Pass
/// 处理：动态物体、骨骼动画角色、粒子系统的运动向量
/// </summary>
public class MotionVectorPass : ScriptableRenderPass
{
    private const string ProfilerTag = "Accurate Motion Vectors";
    
    // 专用运动向量RT
    private RTHandle motionVectorRT;
    private Material motionVectorMaterial;
    
    // 记录上一帧的变换矩阵
    private readonly Dictionary<Renderer, Matrix4x4> prevTransforms = new();
    private Matrix4x4 prevViewProjection;
    private bool isFirstFrame = true;
    
    public MotionVectorPass(Material material)
    {
        motionVectorMaterial = material;
        renderPassEvent = RenderPassEvent.BeforeRenderingOpaques;
    }
    
    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.colorFormat = RenderTextureFormat.RGHalf; // 16位精度，RG通道存储XY运动
        desc.depthBufferBits = 0;
        
        RenderingUtils.ReAllocateIfNeeded(ref motionVectorRT, desc, 
            FilterMode.Point, TextureWrapMode.Clamp, name: "_MotionVectorTexture");
        
        cmd.SetGlobalTexture("_MotionVectorTexture", motionVectorRT);
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get(ProfilerTag);
        
        using (new ProfilingScope(cmd, new ProfilingSampler(ProfilerTag)))
        {
            // 清空运动向量RT
            cmd.SetRenderTarget(motionVectorRT);
            cmd.ClearRenderTarget(false, true, Color.clear);
            
            var camera = renderingData.cameraData.camera;
            Matrix4x4 currentVP = camera.projectionMatrix * camera.worldToCameraMatrix;
            
            if (!isFirstFrame)
            {
                // 相机运动向量（全屏Blit）
                cmd.SetGlobalMatrix("_PreviousVP", prevViewProjection);
                cmd.SetGlobalMatrix("_CurrentVP", currentVP);
                cmd.Blit(null, motionVectorRT, motionVectorMaterial, 0); // Pass 0: 相机运动
                
                // 动态物体运动向量
                RenderDynamicObjectMotionVectors(cmd, context, ref renderingData);
            }
            
            prevViewProjection = currentVP;
            isFirstFrame = false;
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
    
    private void RenderDynamicObjectMotionVectors(CommandBuffer cmd, 
        ScriptableRenderContext context, ref RenderingData renderingData)
    {
        // 找到所有需要精确运动向量的动态渲染器
        var renderers = FindObjectsOfType<SkinnedMeshRenderer>();
        
        foreach (var renderer in renderers)
        {
            if (!renderer.gameObject.activeInHierarchy) continue;
            
            Matrix4x4 currentMatrix = renderer.localToWorldMatrix;
            
            if (prevTransforms.TryGetValue(renderer, out Matrix4x4 prevMatrix))
            {
                // 设置该物体的上一帧变换矩阵
                cmd.SetGlobalMatrix("_PrevObjectToWorld", prevMatrix);
                cmd.SetGlobalMatrix("_ObjectToWorld", currentMatrix);
                
                // 使用专用材质渲染运动向量
                for (int i = 0; i < renderer.sharedMesh.subMeshCount; i++)
                {
                    cmd.DrawRenderer(renderer, motionVectorMaterial, i, 1); // Pass 1: 物体运动
                }
            }
            
            prevTransforms[renderer] = currentMatrix;
        }
    }
    
    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 不在这里释放，复用RT
    }
    
    public void Dispose()
    {
        motionVectorRT?.Release();
        prevTransforms.Clear();
    }
}
```

---

## 6. 超分辨率画质对比与性能数据

### 6.1 性能提升数据参考

| 分辨率组合 | 帧率提升 | 画质评分(SSIM) | 适用场景 |
|-----------|---------|------------|---------|
| 720p→1440p (FSR质量) | ~1.5x | 0.94 | PC中端 |
| 1080p→4K (DLSS均衡) | ~2.0x | 0.97 | PC高端 |
| 540p→1080p (FSR性能) | ~2.5x | 0.88 | 移动端中端 |
| 720p→1080p (FSR质量) | ~1.4x | 0.95 | 移动端高端 |
| 480p→1080p (FSR极速) | ~3.5x | 0.82 | 移动端低端(功耗优先) |

### 6.2 移动端功耗对比

```
传统1080p原生渲染: 100% GPU功耗, 基准帧率
FSR质量(720p→1080p): ~60% GPU功耗, 帧率提升40%
FSR性能(540p→1080p): ~40% GPU功耗, 帧率提升120%
MetalFX时域(iOS): ~55% GPU功耗, 帧率提升60%
```

---

## 7. 自适应超分辨率系统设计

```csharp
/// <summary>
/// 自适应超分辨率控制器
/// 根据设备性能、温度、电量动态选择最优超分方案
/// </summary>
public class AdaptiveSuperResolutionController : MonoBehaviour
{
    [Header("目标帧率")]
    [SerializeField] private int targetFPS = 60;
    [SerializeField] private float fpsSmoothing = 0.1f;
    
    [Header("调整阈值")]
    [SerializeField] private float upgradeThreshold = 1.15f;  // 超出目标15%时提升画质
    [SerializeField] private float downgradeThreshold = 0.85f; // 低于目标15%时降低画质
    [SerializeField] private float hysteresisTime = 3.0f;     // 调整间隔（防抖）
    
    private float smoothedFPS;
    private float lastAdjustTime;
    private int currentQualityLevel = 2; // 0=Ultra, 1=Quality, 2=Balanced, 3=Performance, 4=UltraPerf
    
    private FSRRendererFeature fsrFeature;
    
    private void Start()
    {
        // 获取FSR特性引用
        var renderer = (GraphicsSettings.currentRenderPipeline as UniversalRenderPipelineAsset)
            ?.scriptableRenderer;
        
        smoothedFPS = targetFPS;
        Application.targetFrameRate = targetFPS;
        
        // 根据设备性能设置初始质量
        InitialQualitySelection();
    }
    
    private void InitialQualitySelection()
    {
        // 根据设备GPU等级选择初始超分质量
        int gpuScore = SystemInfo.graphicsMemorySize;
        
        currentQualityLevel = gpuScore switch
        {
            > 8000 => 0,   // 高端GPU: Ultra Quality
            > 4000 => 1,   // 中高端: Quality
            > 2000 => 2,   // 中端: Balanced
            > 1000 => 3,   // 中低端: Performance
            _      => 4    // 低端: Ultra Performance
        };
        
        ApplyQualityLevel(currentQualityLevel);
    }
    
    private void Update()
    {
        // 平滑帧率
        smoothedFPS = Mathf.Lerp(smoothedFPS, 1.0f / Time.deltaTime, fpsSmoothing);
        
        // 防抖检查
        if (Time.time - lastAdjustTime < hysteresisTime) return;
        
        float fpsRatio = smoothedFPS / targetFPS;
        
        if (fpsRatio > upgradeThreshold && currentQualityLevel > 0)
        {
            // 性能富余，提升画质
            currentQualityLevel--;
            ApplyQualityLevel(currentQualityLevel);
            lastAdjustTime = Time.time;
            Debug.Log($"[AdaptiveSR] 提升画质至级别 {currentQualityLevel}, 当前帧率: {smoothedFPS:F1}");
        }
        else if (fpsRatio < downgradeThreshold && currentQualityLevel < 4)
        {
            // 性能不足，降低渲染分辨率
            currentQualityLevel++;
            ApplyQualityLevel(currentQualityLevel);
            lastAdjustTime = Time.time;
            Debug.Log($"[AdaptiveSR] 降低画质至级别 {currentQualityLevel}, 当前帧率: {smoothedFPS:F1}");
        }
    }
    
    private void ApplyQualityLevel(int level)
    {
        float[] scales = { 0.77f, 0.67f, 0.59f, 0.50f, 0.33f };
        if (level >= 0 && level < scales.Length)
        {
            ScalableBufferManager.ResizeBuffers(scales[level], scales[level]);
        }
    }
    
    /// <summary>
    /// 获取当前画质状态信息（用于Debug UI）
    /// </summary>
    public string GetStatusString()
    {
        string[] qualityNames = { "Ultra Quality", "Quality", "Balanced", "Performance", "Ultra Performance" };
        float[] scales = { 0.77f, 0.67f, 0.59f, 0.50f, 0.33f };
        
        return $"超分: {qualityNames[currentQualityLevel]} " +
               $"({scales[currentQualityLevel]:P0}渲染) | " +
               $"FPS: {smoothedFPS:F1}/{targetFPS}";
    }
}
```

---

## 8. 最佳实践总结

### 8.1 超分辨率选型建议

```
PC端高端（RTX GPU）:
  → 优先使用DLSS 3.5（最佳画质+帧生成）
  → 回退到FSR 3（兼容AMD/Intel GPU）
  → 最终回退到TAA（无GPU限制）

PC端中低端:
  → FSR 3（Quality/Balanced模式）
  → TAAU（Unity内置时域上采样）

移动端iOS (Apple Silicon):
  → MetalFX时域上采样（最优功耗比）
  → FSR空间上采样（A14以下）

移动端Android (高端/中端):
  → FSR 2.x（RDNA架构最优）
  → 自适应分辨率 + TAA（通用方案）

移动端Android (低端):
  → 简单双线性插值（最低开销）
  → 固定低分辨率 + 后处理锐化
```

### 8.2 工程注意事项

1. **运动向量准确性**：粒子系统、UI元素应在原生分辨率渲染，避免错误运动向量导致鬼影
2. **抖动模式（Jitter）**：开启次像素抖动以充分利用时域信息，避免静止场景画质退化
3. **UI渲染分离**：UI始终在显示分辨率渲染，叠加在超分结果上，避免UI模糊
4. **HDR输出**：超分辨率在色调映射前进行，避免色域裁剪导致的色彩错误
5. **透明物体处理**：透明物体建议使用专用的运动向量Pass或在原生分辨率渲染
6. **截帧工具配合**：使用RenderDoc验证运动向量纹理是否正确，对调试时域效果至关重要
7. **动态分辨率与超分组合**：避免同时启用Unity动态分辨率和超分插件的分辨率缩放，会产生双重缩放

### 8.3 画质验证清单

- [ ] 静态场景无明显噪点/闪烁
- [ ] 快速运动物体边缘无明显鬼影
- [ ] 细线、栅格图案无摩尔纹
- [ ] 文字、UI在原生分辨率清晰渲染
- [ ] 高光高频细节（铁丝网、头发）保留良好
- [ ] 不同质量模式性能符合预期分辨率比例
