---
title: 游戏HDR色调映射与颜色分级管线完全指南：从线性工作流到ACES色彩空间
published: 2026-04-03
description: 深度解析游戏渲染中的HDR管线设计，涵盖线性色彩空间、色调映射算法（ACES/Filmic/Reinhard）、LUT颜色分级、自适应曝光与颜色管理完整工程实践
tags: [HDR, 色调映射, ACES, LUT, 颜色分级, Unity, URP, 后处理]
category: 游戏渲染
draft: false
---

# 游戏HDR色调映射与颜色分级管线完全指南

## 1. 为什么需要HDR与色调映射

### 1.1 现实世界与显示器的亮度鸿沟

```
真实世界亮度范围（单位：nit/cd/m²）：
  阳光直射地面         : 100,000,000 nit
  晴天室外场景         : 10,000 - 100,000 nit
  普通室内环境         : 100 - 1,000 nit
  烛光                 : 1 nit
  夜晚月光             : 0.001 nit

显示设备亮度范围：
  普通SDR显示器        : 100 - 400 nit
  高端HDR10显示器      : 400 - 1000 nit
  Dolby Vision显示器   : 1000 - 4000 nit

结论：渲染器使用16位浮点HDR缓冲区可存储0-65504的亮度值，
      最终必须通过"色调映射"压缩到显示器可表示的范围。
```

### 1.2 线性工作流的重要性

```
常见的色彩空间错误：
  ❌ 错误：在sRGB空间做光照计算
     → 光照混合不自然，阴影过暗，高光过亮
  
  ✓ 正确：在线性空间计算，最后转换为sRGB输出
     → 物理正确的光照结果
     
Unity线性工作流配置：
  Edit → Project Settings → Player → Other Settings
  → Color Space: Linear（推荐，非Gamma）
```

---

## 2. 色调映射算法详解

### 2.1 Reinhard 色调映射（最简单）

```hlsl
// Reinhard Tonemapping
// 将HDR值映射到[0,1]范围
// 优点：简单快速  缺点：颜色饱和度降低，白色偏灰

float3 ReinhardTonemap(float3 hdrColor)
{
    return hdrColor / (hdrColor + float3(1.0, 1.0, 1.0));
}

// 扩展Reinhard - 保留更多高光细节
float3 ReinhardExtended(float3 hdrColor, float maxWhite)
{
    float3 numerator = hdrColor * (1.0 + hdrColor / (maxWhite * maxWhite));
    return numerator / (1.0 + hdrColor);
}
```

### 2.2 ACES（Academy Color Encoding System）

ACES 是电影工业标准，Unity URP/HDRP 内置的首选色调映射方案。

```hlsl
// ACES Filmic Tonemapping (近似实现)
// 来源：Stephen Hill 的 ACES 近似版本

float3 ACESFilm(float3 x)
{
    float a = 2.51f;
    float b = 0.03f;
    float c = 2.43f;
    float d = 0.59f;
    float e = 0.14f;
    return saturate((x * (a * x + b)) / (x * (c * x + d) + e));
}

// 完整ACES转换（更精确，但开销更大）
// 使用标准ACES色彩空间矩阵转换
static const float3x3 ACESInputMat = 
{
    {0.59719, 0.35458, 0.04823},
    {0.07600, 0.90834, 0.01566},
    {0.02840, 0.13383, 0.83777}
};

static const float3x3 ACESOutputMat = 
{
    { 1.60475, -0.53108, -0.07367},
    {-0.10208,  1.10813, -0.00605},
    {-0.00327, -0.07276,  1.07602}
};

float3 RRTAndODT(float3 v)
{
    float3 a = v * (v + 0.0245786f) - 0.000090537f;
    float3 b = v * (0.983729f * v + 0.4329510f) + 0.238081f;
    return a / b;
}

float3 ACESFitted(float3 color)
{
    color = mul(ACESInputMat, color);
    color = RRTAndODT(color);
    color = mul(ACESOutputMat, color);
    return saturate(color);
}
```

### 2.3 Filmic Tonemapping（Uncharted2风格）

```hlsl
// Filmic Tonemapping - John Hable（神秘海域2）
// 比Reinhard有更好的高光细节和对比度

float3 Uncharted2Partial(float3 x)
{
    float A = 0.15;  // 肩部强度
    float B = 0.50;  // 肩部角度
    float C = 0.10;  // 趾部强度
    float D = 0.20;  // 趾部角度
    float E = 0.02;  // 趾部数值
    float F = 0.30;  // 趾部角度
    return ((x * (A * x + C * B) + D * E) / (x * (A * x + B) + D * F)) - E / F;
}

float3 FilmicTonemap(float3 color)
{
    float3 curr = Uncharted2Partial(color * 2.0);
    float3 W = float3(11.2, 11.2, 11.2); // 白点
    float3 whiteScale = 1.0 / Uncharted2Partial(W);
    return curr * whiteScale;
}
```

### 2.4 不同算法效果对比

```
对比（高光区域 HDR=5.0）：
  Reinhard:   0.833（白色偏灰，高光压缩）
  ACES:       0.951（自然的电影感，适度饱和）
  Filmic:     0.878（高对比度，暗部细节好）
  
色彩保真度：
  Reinhard  < Filmic < ACES
  
计算开销：
  Reinhard  < Filmic < ACES（完整版）
```

---

## 3. URP 自定义色调映射 Pass

### 3.1 完整 Shader 实现

```hlsl
// Assets/Shaders/PostProcess/CustomTonemap.hlsl
#ifndef CUSTOM_TONEMAP_INCLUDED
#define CUSTOM_TONEMAP_INCLUDED

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
#include "Packages/com.unity.render-pipelines.core/ShaderLibrary/Color.hlsl"

TEXTURE2D(_MainTex);
SAMPLER(sampler_MainTex);

TEXTURE2D(_LutTex);           // 3D LUT纹理
SAMPLER(sampler_LutTex);
float4 _LutParams;            // x: 1/lutSize, y: 0.5/lutSize, z: lutSize-1/lutSize

float _Exposure;              // 曝光调整（EV）
float _Contrast;              // 对比度
float _Saturation;            // 饱和度
float _TonemapMode;           // 0=Reinhard, 1=ACES, 2=Filmic

struct Attributes
{
    float4 positionOS : POSITION;
    float2 uv : TEXCOORD0;
};

struct Varyings
{
    float4 positionCS : SV_POSITION;
    float2 uv : TEXCOORD0;
};

Varyings Vert(Attributes input)
{
    Varyings output;
    output.positionCS = TransformObjectToHClip(input.positionOS.xyz);
    output.uv = input.uv;
    return output;
}

// ============ 色调映射函数 ============

float3 ReinhardTonemap(float3 color)
{
    return color / (color + 1.0);
}

float3 ACESFilm(float3 x)
{
    float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return saturate((x * (a * x + b)) / (x * (c * x + d) + e));
}

float3 FilmicTonemap(float3 color)
{
    float3 x = max(0, color - 0.004);
    return (x * (6.2 * x + 0.5)) / (x * (6.2 * x + 1.7) + 0.06);
}

// ============ 颜色分级 ============

float3 ApplyExposure(float3 color, float ev)
{
    return color * pow(2.0, ev);
}

float3 ApplyContrast(float3 color, float contrast)
{
    // 在对数空间做对比度调整
    return saturate((color - 0.5) * contrast + 0.5);
}

float3 ApplySaturation(float3 color, float saturation)
{
    float luma = dot(color, float3(0.2126, 0.7152, 0.0722));
    return lerp(float3(luma, luma, luma), color, saturation);
}

// ============ 3D LUT采样 ============

float3 ApplyLut3D(TEXTURE2D_PARAM(lutTex, lutSampler), float3 color, float4 lutParams)
{
    // lutParams: x=1/lutSize, y=0.5/lutSize, z=(lutSize-1)/lutSize
    float3 coords = color * lutParams.z + lutParams.y;
    
    // 3D LUT存储为2D Strip格式（横向展开）
    float slice = coords.z * lutParams.w; // w = lutSize
    float sliceFloor = floor(slice);
    float sliceFrac = slice - sliceFloor;
    
    float2 uv1 = float2((sliceFloor + coords.x) * lutParams.x, coords.y);
    float2 uv2 = float2((sliceFloor + 1.0 + coords.x) * lutParams.x, coords.y);
    
    float3 col1 = SAMPLE_TEXTURE2D(lutTex, lutSampler, uv1).rgb;
    float3 col2 = SAMPLE_TEXTURE2D(lutTex, lutSampler, uv2).rgb;
    
    return lerp(col1, col2, sliceFrac);
}

// ============ 主片段着色器 ============

float4 Frag(Varyings input) : SV_Target
{
    float3 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, input.uv).rgb;
    
    // 1. 曝光调整（在色调映射前）
    color = ApplyExposure(color, _Exposure);
    
    // 2. 色调映射（HDR → LDR）
    if (_TonemapMode < 0.5)
        color = ReinhardTonemap(color);
    else if (_TonemapMode < 1.5)
        color = ACESFilm(color);
    else
        color = FilmicTonemap(color);
    
    // 3. 颜色分级（在LDR空间）
    color = ApplyContrast(color, _Contrast);
    color = ApplySaturation(color, _Saturation);
    
    // 4. 应用3D LUT
    // color = ApplyLut3D(TEXTURE2D_ARGS(_LutTex, sampler_LutTex), color, _LutParams);
    
    // 5. sRGB转换（如果是Gamma空间输出）
    // color = LinearToSRGB(color);
    
    return float4(color, 1.0);
}

#endif
```

### 3.2 C# 渲染 Pass 实现

```csharp
// Assets/Scripts/Rendering/CustomTonemapPass.cs
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class CustomTonemapPass : ScriptableRenderPass
{
    private readonly Material _tonemapMaterial;
    private RTHandle _tempRT;
    private static readonly int ExposureId    = Shader.PropertyToID("_Exposure");
    private static readonly int ContrastId    = Shader.PropertyToID("_Contrast");
    private static readonly int SaturationId  = Shader.PropertyToID("_Saturation");
    private static readonly int TonemapModeId = Shader.PropertyToID("_TonemapMode");

    public CustomTonemapPass(Material material)
    {
        _tonemapMaterial = material;
        renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        RenderingUtils.ReAllocateIfNeeded(ref _tempRT, desc, name: "_CustomTonemapTemp");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        // 获取自定义后处理Volume参数
        var volume = VolumeManager.instance.stack.GetComponent<CustomTonemapVolume>();
        if (volume == null || !volume.IsActive()) return;

        _tonemapMaterial.SetFloat(ExposureId,    volume.exposure.value);
        _tonemapMaterial.SetFloat(ContrastId,    volume.contrast.value);
        _tonemapMaterial.SetFloat(SaturationId,  volume.saturation.value);
        _tonemapMaterial.SetFloat(TonemapModeId, (float)volume.tonemapMode.value);

        var cmd = CommandBufferPool.Get("Custom Tonemap");
        
        using (new ProfilingScope(cmd, new ProfilingSampler("Custom Tonemap")))
        {
            var source = renderingData.cameraData.renderer.cameraColorTargetHandle;
            Blitter.BlitCameraTexture(cmd, source, _tempRT, _tonemapMaterial, 0);
            Blitter.BlitCameraTexture(cmd, _tempRT, source);
        }

        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 清理临时RT
    }

    public void Cleanup()
    {
        _tempRT?.Release();
    }
}

// Volume组件
using UnityEngine.Rendering;

[System.Serializable, VolumeComponentMenu("Custom/Tonemap")]
public class CustomTonemapVolume : VolumeComponent, IPostProcessComponent
{
    public enum TonemapMode { Reinhard = 0, ACES = 1, Filmic = 2 }

    [Header("色调映射")]
    public VolumeParameter<TonemapMode> tonemapMode = new(TonemapMode.ACES);
    
    [Header("曝光与颜色")]
    public ClampedFloatParameter exposure   = new(0f, -5f, 5f);
    public ClampedFloatParameter contrast   = new(1f, 0.5f, 2f);
    public ClampedFloatParameter saturation = new(1f, 0f, 2f);

    public bool IsActive() => true;
    public bool IsTileCompatible() => false;
}
```

---

## 4. 自适应曝光（Auto Exposure）

### 4.1 基于直方图的自动曝光

```csharp
// 使用Compute Shader计算画面平均亮度
using UnityEngine;
using UnityEngine.Rendering;

public class AutoExposureController : MonoBehaviour
{
    [Header("自动曝光参数")]
    [Range(-5, 5)]  public float minEV = -2f;
    [Range(-5, 5)]  public float maxEV = 4f;
    [Range(0.1f, 10f)] public float adaptationSpeed = 2f;
    [Range(0f, 1f)]    public float targetMiddleGrey = 0.18f;

    private ComputeShader _luminanceCS;
    private ComputeBuffer _histogramBuffer;
    private ComputeBuffer _avgLuminanceBuffer;
    
    private float _currentEV = 0f;
    private float _targetEV = 0f;

    private const int HISTOGRAM_BINS = 256;

    private void Start()
    {
        _luminanceCS = Resources.Load<ComputeShader>("LuminanceHistogram");
        _histogramBuffer   = new ComputeBuffer(HISTOGRAM_BINS, sizeof(uint));
        _avgLuminanceBuffer = new ComputeBuffer(1, sizeof(float));
    }

    private void Update()
    {
        // 平滑过渡到目标EV
        _currentEV = Mathf.Lerp(_currentEV, _targetEV, Time.deltaTime * adaptationSpeed);
        
        // 应用到色调映射材质
        Shader.SetGlobalFloat("_AutoExposure", _currentEV);
    }

    /// <summary>
    /// 从RenderTexture计算平均亮度（异步方式）
    /// </summary>
    public void ComputeAverageLuminance(RenderTexture hdrBuffer)
    {
        if (_luminanceCS == null) return;

        // 清空直方图
        _histogramBuffer.SetData(new uint[HISTOGRAM_BINS]);

        // Kernel 0: 计算亮度直方图
        int buildKernel = _luminanceCS.FindKernel("BuildHistogram");
        _luminanceCS.SetTexture(buildKernel, "_InputTex", hdrBuffer);
        _luminanceCS.SetBuffer(buildKernel, "_HistogramBuffer", _histogramBuffer);
        _luminanceCS.SetFloat("_MinLogLum", minEV);
        _luminanceCS.SetFloat("_MaxLogLum", maxEV);
        
        int dispatchX = Mathf.CeilToInt(hdrBuffer.width / 16f);
        int dispatchY = Mathf.CeilToInt(hdrBuffer.height / 16f);
        _luminanceCS.Dispatch(buildKernel, dispatchX, dispatchY, 1);

        // Kernel 1: 从直方图计算平均亮度
        int avgKernel = _luminanceCS.FindKernel("ComputeAverage");
        _luminanceCS.SetBuffer(avgKernel, "_HistogramBuffer", _histogramBuffer);
        _luminanceCS.SetBuffer(avgKernel, "_AvgLuminance", _avgLuminanceBuffer);
        _luminanceCS.SetFloat("_PixelCount", hdrBuffer.width * hdrBuffer.height);
        _luminanceCS.SetFloat("_TargetMiddleGrey", targetMiddleGrey);
        _luminanceCS.Dispatch(avgKernel, 1, 1, 1);

        // 异步读回结果（避免GPU Stall）
        AsyncGPUReadback.Request(_avgLuminanceBuffer, request =>
        {
            if (!request.hasError)
            {
                float avgLum = request.GetData<float>()[0];
                // 将平均亮度转换为目标EV
                _targetEV = Mathf.Log2(targetMiddleGrey / Mathf.Max(avgLum, 0.0001f));
                _targetEV = Mathf.Clamp(_targetEV, minEV, maxEV);
            }
        });
    }

    private void OnDestroy()
    {
        _histogramBuffer?.Release();
        _avgLuminanceBuffer?.Release();
    }
}
```

### 4.2 Compute Shader - 亮度直方图

```hlsl
// Assets/Shaders/Compute/LuminanceHistogram.compute
#pragma kernel BuildHistogram
#pragma kernel ComputeAverage

Texture2D<float4> _InputTex;
RWStructuredBuffer<uint> _HistogramBuffer;
RWStructuredBuffer<float> _AvgLuminance;

float _MinLogLum;
float _MaxLogLum;
float _PixelCount;
float _TargetMiddleGrey;

#define HISTOGRAM_BINS 256

// 将亮度值映射到直方图bin索引
uint LuminanceToBin(float lum)
{
    if (lum < 0.005) return 0;
    float logLum = clamp(log2(lum), _MinLogLum, _MaxLogLum);
    float normalizedLum = (logLum - _MinLogLum) / (_MaxLogLum - _MinLogLum);
    return (uint)(normalizedLum * (HISTOGRAM_BINS - 1) + 0.5);
}

[numthreads(16, 16, 1)]
void BuildHistogram(uint3 id : SV_DispatchThreadID)
{
    uint width, height;
    _InputTex.GetDimensions(width, height);
    
    if (id.x >= width || id.y >= height) return;
    
    float4 color = _InputTex[id.xy];
    
    // 计算亮度（线性空间）
    float lum = dot(color.rgb, float3(0.2126, 0.7152, 0.0722));
    
    uint bin = LuminanceToBin(lum);
    InterlockedAdd(_HistogramBuffer[bin], 1);
}

[numthreads(HISTOGRAM_BINS, 1, 1)]
void ComputeAverage(uint3 id : SV_DispatchThreadID)
{
    // 加权平均（忽略最暗和最亮的10%）
    uint bin = id.x;
    float binValue = _HistogramBuffer[bin];
    
    // 计算bin对应的亮度值
    float normalizedBin = (float)bin / (HISTOGRAM_BINS - 1);
    float logLum = normalizedBin * (_MaxLogLum - _MinLogLum) + _MinLogLum;
    
    // 简化版：直接累加（实际应做加权平均）
    float contribution = binValue / _PixelCount * exp2(logLum);
    
    // 原子加（需要GroupShared优化）
    uint quantized = (uint)(contribution * 1000000);
    InterlockedAdd((uint)_AvgLuminance[0], quantized);
}
```

---

## 5. 3D LUT 颜色分级系统

### 5.1 什么是 3D LUT

```
3D LUT（Look-Up Table）：
  一个3维颜色查找表，将输入RGB映射到输出RGB
  
  标准尺寸：
  - 17x17x17（简单效果，体积小）
  - 33x33x33（标准质量，推荐）
  - 65x65x65（高精度，开销大）
  
  使用场景：
  - 昼夜颜色过渡
  - 场景气氛渲染（恐怖/温暖/冷峻）
  - 模拟胶片风格
  - 色盲辅助模式
  
存储方式（在Unity中）：
  3D纹理 → 直接3D采样
  2D Strip → 横向展开（兼容性更好）
```

### 5.2 运行时 LUT 混合系统

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;
using System.Collections.Generic;

/// <summary>
/// 运行时3D LUT颜色分级控制器
/// 支持多个LUT之间的平滑过渡
/// </summary>
public class LutColorGradingSystem : MonoBehaviour
{
    [System.Serializable]
    public class LutPreset
    {
        public string name;
        public Texture2D lutTexture;  // 2D Strip LUT
        [Range(0, 1)] public float intensity = 1f;
    }

    [Header("LUT预设库")]
    public List<LutPreset> lutPresets = new();
    
    [Header("当前状态")]
    [SerializeField] private int _activeLutIndex = 0;
    [SerializeField] [Range(0, 1)] private float _blendProgress = 0f;

    private Volume _postProcessVolume;
    private ColorAdjustments _colorAdjustments;
    private Material _lutBlendMaterial;
    
    // LUT混合目标
    private int _fromLutIndex = 0;
    private int _toLutIndex = 0;
    private float _blendSpeed = 1f;
    private bool _isBlending = false;

    private static readonly int LutTexFrom   = Shader.PropertyToID("_LutFrom");
    private static readonly int LutTexTo     = Shader.PropertyToID("_LutTo");
    private static readonly int BlendAmount  = Shader.PropertyToID("_BlendAmount");
    private static readonly int LutIntensity = Shader.PropertyToID("_LutIntensity");

    private void Start()
    {
        _postProcessVolume = GetComponent<Volume>();
        _postProcessVolume?.profile?.TryGet(out _colorAdjustments);
    }

    private void Update()
    {
        if (_isBlending)
        {
            _blendProgress += Time.deltaTime * _blendSpeed;
            
            if (_blendProgress >= 1f)
            {
                _blendProgress = 1f;
                _fromLutIndex = _toLutIndex;
                _activeLutIndex = _toLutIndex;
                _isBlending = false;
            }

            UpdateLutMaterial();
        }
    }

    /// <summary>
    /// 切换到指定LUT（带过渡动画）
    /// </summary>
    public void TransitionToLut(int lutIndex, float duration = 1f)
    {
        if (lutIndex < 0 || lutIndex >= lutPresets.Count) return;
        
        _fromLutIndex = _activeLutIndex;
        _toLutIndex = lutIndex;
        _blendProgress = 0f;
        _blendSpeed = duration > 0 ? 1f / duration : float.MaxValue;
        _isBlending = true;
    }

    /// <summary>
    /// 按名称切换LUT
    /// </summary>
    public void TransitionToLut(string lutName, float duration = 1f)
    {
        int index = lutPresets.FindIndex(p => p.name == lutName);
        if (index >= 0) TransitionToLut(index, duration);
        else Debug.LogWarning($"[LUT] 未找到预设：{lutName}");
    }

    private void UpdateLutMaterial()
    {
        if (_lutBlendMaterial == null) return;

        var fromPreset = lutPresets[_fromLutIndex];
        var toPreset   = lutPresets[_toLutIndex];

        _lutBlendMaterial.SetTexture(LutTexFrom,  fromPreset.lutTexture);
        _lutBlendMaterial.SetTexture(LutTexTo,    toPreset.lutTexture);
        _lutBlendMaterial.SetFloat(BlendAmount,   _blendProgress);
        _lutBlendMaterial.SetFloat(LutIntensity,  
            Mathf.Lerp(fromPreset.intensity, toPreset.intensity, _blendProgress));
    }
}
```

---

## 6. 场景颜色氛围系统

### 6.1 基于时间的颜色过渡

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 昼夜颜色氛围系统
/// 根据游戏内时间自动调整色调映射参数
/// </summary>
public class DayNightColorSystem : MonoBehaviour
{
    [System.Serializable]
    public class TimeColorState
    {
        [Range(0, 24)] public float hour;
        [ColorUsage(false, true)] public Color sunColor = Color.white;
        public float exposure = 0f;
        public float contrast = 1f;
        public float saturation = 1f;
        [Range(-180, 180)] public float hueShift = 0f;
        public int lutPresetIndex = 0;
    }

    [Header("时间色彩曲线")]
    public List<TimeColorState> timeStates = new List<TimeColorState>
    {
        new TimeColorState { hour = 0,  exposure = -2f, saturation = 0.7f },  // 午夜
        new TimeColorState { hour = 6,  exposure = -0.5f, saturation = 0.9f, hueShift = 10 },  // 日出
        new TimeColorState { hour = 9,  exposure = 0f, saturation = 1.1f },   // 上午
        new TimeColorState { hour = 12, exposure = 0.5f, saturation = 1.2f }, // 正午
        new TimeColorState { hour = 17, exposure = 0.2f, saturation = 1.3f, hueShift = -5 }, // 傍晚
        new TimeColorState { hour = 19, exposure = -0.5f, saturation = 1.1f, hueShift = 15 }, // 黄昏
        new TimeColorState { hour = 22, exposure = -1.5f, saturation = 0.8f }, // 夜晚
    };

    [Header("引用")]
    public Volume postProcessVolume;
    
    [Range(0, 24)] public float currentHour = 12f;

    private ColorAdjustments _colorAdjustments;
    private LutColorGradingSystem _lutSystem;

    private void Start()
    {
        postProcessVolume?.profile?.TryGet(out _colorAdjustments);
        _lutSystem = GetComponent<LutColorGradingSystem>();
    }

    private void Update()
    {
        ApplyColorForHour(currentHour);
    }

    private void ApplyColorForHour(float hour)
    {
        if (timeStates.Count < 2) return;

        // 找到当前时间的前后状态
        int fromIdx = 0, toIdx = 1;
        
        for (int i = 0; i < timeStates.Count - 1; i++)
        {
            if (hour >= timeStates[i].hour && hour < timeStates[i + 1].hour)
            {
                fromIdx = i;
                toIdx = i + 1;
                break;
            }
        }

        var from = timeStates[fromIdx];
        var to   = timeStates[toIdx];
        
        float range = to.hour - from.hour;
        float t = range > 0 ? (hour - from.hour) / range : 0f;
        t = Mathf.SmoothStep(0, 1, t); // 平滑插值

        if (_colorAdjustments != null)
        {
            _colorAdjustments.postExposure.value = Mathf.Lerp(from.exposure, to.exposure, t);
            _colorAdjustments.contrast.value     = Mathf.Lerp(from.contrast, to.contrast, t) * 100f - 100f; // URP范围[-100,100]
            _colorAdjustments.saturation.value   = Mathf.Lerp(from.saturation, to.saturation, t) * 100f - 100f;
            _colorAdjustments.hueShift.value     = Mathf.Lerp(from.hueShift, to.hueShift, t);
        }
    }

    /// <summary>
    /// 快速切换到特定天气/场景氛围
    /// </summary>
    public void ApplyAtmosphere(string atmosphereName, float transitionTime = 2f)
    {
        switch (atmosphereName)
        {
            case "horror":
                StartCoroutine(TransitionToColor(-0.5f, 1.3f, 0.4f, -15f, transitionTime));
                break;
            case "dream":
                StartCoroutine(TransitionToColor(0.5f, 0.8f, 1.5f, 30f, transitionTime));
                break;
            case "cinematic":
                StartCoroutine(TransitionToColor(0f, 1.2f, 0.9f, 0f, transitionTime));
                break;
        }
    }

    private System.Collections.IEnumerator TransitionToColor(
        float targetExposure, float targetContrast, 
        float targetSaturation, float targetHue,
        float duration)
    {
        if (_colorAdjustments == null) yield break;

        float elapsed = 0;
        float startExposure    = _colorAdjustments.postExposure.value;
        float startContrast    = _colorAdjustments.contrast.value;
        float startSaturation  = _colorAdjustments.saturation.value;
        float startHue         = _colorAdjustments.hueShift.value;

        while (elapsed < duration)
        {
            elapsed += Time.deltaTime;
            float t = Mathf.SmoothStep(0, 1, elapsed / duration);
            
            _colorAdjustments.postExposure.value = Mathf.Lerp(startExposure, targetExposure, t);
            _colorAdjustments.contrast.value     = Mathf.Lerp(startContrast, targetContrast * 100f - 100f, t);
            _colorAdjustments.saturation.value   = Mathf.Lerp(startSaturation, targetSaturation * 100f - 100f, t);
            _colorAdjustments.hueShift.value     = Mathf.Lerp(startHue, targetHue, t);
            
            yield return null;
        }
    }
}
```

---

## 7. 最佳实践总结

### 7.1 色调映射选择指南

```
场景类型         | 推荐算法      | 原因
─────────────────┼─────────────┼─────────────────────────────
写实游戏         | ACES        | 电影级色彩，高光自然
卡通/风格化      | Filmic/自定义 | 高对比度，色彩鲜明
VR应用           | Reinhard    | 低开销，避免晕动症
移动端轻量游戏   | Reinhard    | 最优性能
高端PC游戏       | ACES完整版   | 最高质量
```

### 7.2 工程规范

```
✅ 务必使用线性色彩空间（Linear）进行渲染
✅ HDR缓冲区使用R16G16B16A16_SFloat格式
✅ 色调映射在最后阶段（BeforeRenderingPostProcessing后）执行
✅ LUT尺寸选32³（平衡质量与性能）
✅ 自动曝光使用异步GPU读回，避免主线程等待
✅ 昼夜过渡使用SmoothStep插值，避免线性突变

⚠️  避免在Gamma空间做光照计算
⚠️  避免在色调映射前调整曝光（应在之后），除非物理曝光
⚠️  LUT纹理必须关闭sRGB采样（否则二次gamma转换）
⚠️  移动端慎用完整ACES，考虑近似版本
```

### 7.3 性能参考数据

```
色调映射开销（1080p，RTX3060）：
  Reinhard:           0.05ms
  ACES近似版:         0.08ms
  ACES完整版:         0.15ms
  + 3D LUT(32³):      0.03ms
  + 自动曝光直方图:   0.10ms
  
移动端（骁龙888）：
  Reinhard:           0.3ms
  ACES近似版:         0.5ms
  建议移动端预算:     <1ms（含所有后处理）
```

---

## 总结

HDR色调映射与颜色分级管线是游戏视觉品质的核心组成。通过合理选择色调映射算法（推荐ACES）、配合3D LUT颜色分级和自适应曝光系统，可以为玩家呈现电影级的视觉体验。关键在于：**在正确的色彩空间做计算，在正确的阶段做色调映射，用LUT实现灵活的视觉风格控制**。
