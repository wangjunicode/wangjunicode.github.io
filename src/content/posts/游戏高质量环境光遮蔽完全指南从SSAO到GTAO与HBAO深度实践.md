---
title: 游戏高质量环境光遮蔽完全指南：从SSAO到GTAO与HBAO深度实践
published: 2026-04-13
description: 深度解析游戏中环境光遮蔽（AO）技术的完整进化路径，从经典SSAO到地平线基础HBAO+，再到物理精确的GTAO（Ground Truth AO），结合Unity URP完整Shader实现与移动端优化策略，覆盖时域降噪（TAAO）与多层AO合成。
tags: [环境光遮蔽, SSAO, HBAO, GTAO, 后处理, URP, 渲染, 性能优化]
category: 渲染技术
draft: false
---

# 游戏高质量环境光遮蔽完全指南：从SSAO到GTAO与HBAO深度实践

## 前言

环境光遮蔽（Ambient Occlusion, AO）是游戏画面中"地基质感"的关键——角落阴影、物体接触面的深度感、场景的立体感，都与 AO 密切相关。从早期的 SSAO 到 HBAO、再到物理精确的 GTAO，AO 技术走过了超过 15 年的演进。

本文将系统讲解每种 AO 技术的数学原理、GPU 实现、时域降噪（TAAO），以及如何在 Unity URP 中构建完整的 AO 后处理管线。

---

## 一、AO 技术全景对比

### 1.1 各技术核心特性

| 技术 | 物理精度 | GPU 开销 | 适用平台 | 自遮挡 | 间接阴影 |
|---|---|---|---|---|---|
| SSAO | 低 | 低 | 全平台 | 是 | 否 |
| HBAO | 中 | 中 | PC/主机 | 是 | 部分 |
| HBAO+ | 中高 | 中高 | PC/主机 | 是 | 是 |
| GTAO | 高 | 高 | PC | 是 | 是 |
| RTAO（光线追踪）| 最高 | 极高 | PC 高端 | 是 | 是 |
| MSAO（多重采样）| 中 | 中 | 全平台 | 是 | 否 |

### 1.2 积分方程

所有屏幕空间 AO 技术都是对以下可见性积分的近似：

$$A(\mathbf{p}) = \frac{1}{\pi} \int_{\Omega^+} V(\mathbf{p}, \omega) \cos\theta \, d\omega$$

其中 $V(\mathbf{p}, \omega)$ 为方向 $\omega$ 上的可见性函数（0=遮挡，1=可见），$\cos\theta$ 为朗伯余弦权重。

---

## 二、SSAO 经典实现

### 2.1 SSAO 原理与限制

SSAO（Crytek 2007）通过在法线半球上随机采样深度缓冲来估算遮蔽：

```hlsl
// =====================================================
// SSAO Shader（URP ScriptableRenderPass 版本）
// 输入：深度缓冲、法线缓冲、随机旋转噪声纹理
// 输出：AO 值（单通道，[0,1]）
// =====================================================

#ifndef SSAO_INCLUDED
#define SSAO_INCLUDED

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareDepthTexture.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/DeclareNormalsTexture.hlsl"

TEXTURE2D(_SSAO_NoiseTexture); SAMPLER(sampler_SSAO_NoiseTexture);
float4 _SSAO_Params;        // x=radius, y=bias, z=intensity, w=sampleCount
float4 _ScreenSize;
float4x4 _InvProjectionMatrix;
float4x4 _ProjectionMatrix;

// 预生成的 Poisson 盘采样核（16个样本，cos权重分布）
static const int SSAO_SAMPLE_COUNT = 16;
static const float3 SSAO_KERNEL[16] = {
    float3( 0.5381, 0.1856,-0.4319), float3( 0.1379, 0.2486, 0.4430),
    float3( 0.3371, 0.5679,-0.0057), float3(-0.6999,-0.0451,-0.0019),
    float3( 0.0689,-0.1598,-0.8547), float3( 0.0560, 0.0069,-0.1843),
    float3(-0.0146, 0.1402, 0.0762), float3( 0.0100,-0.1924,-0.0344),
    float3(-0.3577,-0.5301,-0.4358), float3(-0.3169, 0.1063, 0.0158),
    float3( 0.0103,-0.5869, 0.0046), float3(-0.0897,-0.4940, 0.3287),
    float3( 0.7119,-0.0154,-0.0918), float3(-0.0533, 0.0596,-0.5411),
    float3( 0.0352,-0.0631, 0.5460), float3(-0.4776, 0.2847,-0.0271)
};

// 从深度缓冲重建世界空间位置
float3 ReconstructPositionVS(float2 uv)
{
    float depth = SampleSceneDepth(uv);
    float4 ndc = float4(uv * 2.0 - 1.0, depth, 1.0);
    #if UNITY_REVERSED_Z
    ndc.z = 1.0 - ndc.z;
    #endif
    float4 viewPos = mul(_InvProjectionMatrix, ndc);
    return viewPos.xyz / viewPos.w;
}

// TBN 矩阵（随机旋转，减少采样规律性）
float3x3 GetRandomTBN(float2 uv, float3 normalVS)
{
    float2 noiseUV = uv * _ScreenSize.xy / 4.0; // 4x4 噪声纹理平铺
    float3 randomVec = normalize(SAMPLE_TEXTURE2D(_SSAO_NoiseTexture, sampler_SSAO_NoiseTexture, noiseUV).xyz * 2.0 - 1.0);
    
    float3 tangent = normalize(randomVec - normalVS * dot(randomVec, normalVS));
    float3 bitangent = cross(normalVS, tangent);
    return float3x3(tangent, bitangent, normalVS);
}

float4 SSAOFragment(Varyings input) : SV_Target
{
    float2 uv = input.texcoord;
    float radius   = _SSAO_Params.x;
    float bias     = _SSAO_Params.y;
    float intensity = _SSAO_Params.z;
    int   sampleCount = (int)_SSAO_Params.w;
    
    float3 posVS    = ReconstructPositionVS(uv);
    float3 normalVS = normalize(SampleSceneNormals(uv) * 2.0 - 1.0);
    normalVS = mul((float3x3)UNITY_MATRIX_V, normalVS); // 转到视空间
    
    float3x3 TBN = GetRandomTBN(uv, normalVS);
    
    float occlusion = 0.0;
    
    [unroll]
    for (int i = 0; i < SSAO_SAMPLE_COUNT; ++i)
    {
        if (i >= sampleCount) break;
        
        // 将核心样本转到视空间
        float3 sampleVS = mul(SSAO_KERNEL[i], TBN);
        // 保证样本在半球正面
        sampleVS = sampleVS * sign(dot(sampleVS, normalVS));
        
        float3 samplePos = posVS + sampleVS * radius;
        
        // 投影到屏幕空间
        float4 offset = mul(_ProjectionMatrix, float4(samplePos, 1.0));
        offset.xy = offset.xy / offset.w * 0.5 + 0.5;
        
        // 采样该位置的实际深度
        float3 samplePosActual = ReconstructPositionVS(offset.xy);
        float actualDepth = samplePosActual.z;
        
        // 范围检测（超出 radius 的遮挡权重为 0）
        float rangeCheck = smoothstep(0.0, 1.0, radius / abs(posVS.z - actualDepth));
        
        // 深度比较（带 bias 避免自遮挡）
        occlusion += (actualDepth >= samplePos.z + bias ? 1.0 : 0.0) * rangeCheck;
    }
    
    occlusion = 1.0 - (occlusion / sampleCount);
    occlusion = pow(occlusion, intensity);
    
    return float4(occlusion, 0, 0, 1);
}
#endif
```

---

## 三、HBAO+ 实现（地平线基础AO）

### 3.1 HBAO 核心算法

HBAO 相比 SSAO 的关键改进是将积分转换为2D角度积分：

$$A(\mathbf{p}) = 1 - \frac{1}{2\pi}\int_0^{2\pi} \sin^2(h(\phi, \mathbf{p})) \, d\phi$$

其中 $h(\phi, \mathbf{p})$ 是方向 $\phi$ 上的地平线角（horizon angle）。

```hlsl
// =====================================================
// HBAO+ 核心实现
// 在每个像素沿多个方向搜索地平线角
// =====================================================

TEXTURE2D(_DepthBuffer);
SAMPLER(sampler_DepthBuffer);

float4 _HBAO_Params;    // x=radius, y=bias, z=maxRadiusPixels, w=numSteps
float4 _HBAO_Params2;   // x=numDirections, y=attenuation, z=angleBias

#define NUM_DIRECTIONS 8
#define NUM_STEPS      4

// 从屏幕空间步进，搜索地平线角
float SearchHorizonAngle(float2 startUV, float2 stepDir, float3 originVS, int steps, float stepSize)
{
    float maxSinAngle = sin(radians(_HBAO_Params2.z)); // 初始角度偏差
    
    for (int i = 1; i <= steps; i++)
    {
        float2 sampleUV = startUV + stepDir * (i * stepSize);
        
        if (sampleUV.x < 0 || sampleUV.x > 1 || sampleUV.y < 0 || sampleUV.y > 1)
            break;
        
        float3 samplePosVS = ReconstructPositionVS(sampleUV);
        float3 horizonVec = samplePosVS - originVS;
        
        float dist = length(horizonVec);
        float attenuation = 1.0 - saturate(dist / _HBAO_Params.x); // 距离衰减
        attenuation *= attenuation; // 平方衰减，更物理
        
        float sinAngle = horizonVec.z / dist; // 高度/距离 = sin(angle)
        maxSinAngle = max(maxSinAngle, sinAngle * attenuation);
    }
    return maxSinAngle;
}

float4 HBAOFragment(Varyings input) : SV_Target
{
    float2 uv = input.texcoord;
    float3 posVS = ReconstructPositionVS(uv);
    float3 normalVS = normalize(SampleSceneNormals(uv) * 2.0 - 1.0);
    normalVS = mul((float3x3)UNITY_MATRIX_V, normalVS);
    
    // 随机旋转方向（时域稳定性）
    float randomAngle = SAMPLE_TEXTURE2D(_SSAO_NoiseTexture, sampler_SSAO_NoiseTexture, 
                                          uv * _ScreenSize.xy / 4.0).r * TWO_PI;
    
    float radiusPixels = _HBAO_Params.z / abs(posVS.z); // 透视校正半径
    radiusPixels = min(radiusPixels, _HBAO_Params.z);
    float stepSizePixels = radiusPixels / (NUM_STEPS + 1);
    float stepSizeUV = stepSizePixels / _ScreenSize.x;
    
    float occlusion = 0.0;
    
    [unroll]
    for (int d = 0; d < NUM_DIRECTIONS; d++)
    {
        float angle = randomAngle + d * (TWO_PI / NUM_DIRECTIONS);
        float2 dir = float2(cos(angle), sin(angle));
        
        // 双向地平线搜索（+/- 方向）
        float sinH1 = SearchHorizonAngle(uv,  dir, posVS, NUM_STEPS, stepSizeUV);
        float sinH2 = SearchHorizonAngle(uv, -dir, posVS, NUM_STEPS, stepSizeUV);
        
        // 投影法线到当前方向的切平面
        float3 dirVS = float3(dir, 0);
        float3 planeNormal = cross(dirVS, float3(0,0,1));
        float3 projNormal = normalVS - planeNormal * dot(normalVS, planeNormal);
        float normLen = length(projNormal);
        
        if (normLen > 1e-3)
        {
            projNormal /= normLen;
            float cosN = dot(projNormal, dirVS);
            float n = acos(clamp(cosN, -1, 1)); // 法线在当前切面的角度
            
            // 半球遮蔽积分（近似计算）
            float h1 = -asin(sinH1), h2 = asin(sinH2);
            h1 = n + max(h1 - n, -HALF_PI);
            h2 = n + min(h2 - n,  HALF_PI);
            
            // cos²积分的闭合解
            float ao = normLen * 0.25 * (
                -cos(2*h1 - n) + cos(n) + 2*h1*sin(n)
                -cos(2*h2 - n) + cos(n) + 2*h2*sin(n));
            occlusion += ao;
        }
    }
    
    occlusion /= NUM_DIRECTIONS;
    occlusion = 1.0 - saturate(occlusion * _HBAO_Params2.y); // 强度调整
    
    return float4(occlusion, 0, 0, 1);
}
```

---

## 四、GTAO：物理精确的 AO

### 4.1 GTAO 原理

GTAO（Ground Truth Ambient Occlusion，Intel 2016）将 HBAO 的积分改为精确的余弦加权积分，同时引入了**多重遮挡**（Multi-bounce AO）校正，使暗部不会过度变黑。

```hlsl
// =====================================================
// GTAO 核心实现（简化版）
// 关键改进：使用精确的 cos 加权积分替代 HBAO 的近似
// =====================================================

// GTAO 地平线积分（cos 加权）
float IntegrateArcCosWeight(float sinH1, float sinH2, float cosN, float sinN)
{
    // 对 cos(theta) * dtheta 在 [h1, h2] 上积分的精确闭合解
    float h1 = asin(clamp(sinH1, -1, 1));
    float h2 = asin(clamp(sinH2, -1, 1));
    float n  = asin(clamp(cosN, -1, 1));  // 这里其实是 atan2 更稳定
    
    // W(h1, h2) = 0.5*(cos(2*h1) + 2*h1*sin(n) - cos(2*h2) - 2*h2*sin(n))
    return 0.5 * (
        -cos(2*h1 - n) + cos(n) + 2*h1*sinN
        -cos(2*h2 - n) + cos(n) + 2*h2*sinN
    );
}

// 多重弹射近似（Jimenez 2016）：减少过暗问题
float MultibounceApproximation(float ao, float albedo)
{
    // 基于 albedo 的多弹射修正，白色物体接触阴影更柔和
    float a =  2.0404 * albedo - 0.3324;
    float b = -4.7951 * albedo + 0.6417;
    float c =  2.7552 * albedo + 0.6903;
    float x = ao;
    return max(x, x * (x * (a * x + b) + c));
}

float4 GTAOFragment(Varyings input) : SV_Target
{
    float2 uv = input.texcoord;
    float3 posVS = ReconstructPositionVS(uv);
    float3 normalVS = normalize(SampleSceneNormals(uv) * 2.0 - 1.0);
    normalVS = mul((float3x3)UNITY_MATRIX_V, normalVS);
    
    float3 viewDirVS = normalize(-posVS); // 视方向（指向相机）
    float randomAngle = GetBlueNoiseSample(uv, _FrameIndex) * TWO_PI; // 时域稳定蓝噪声
    
    float visibilitySum = 0.0;
    float weightSum = 0.0;
    
    [unroll]
    for (int d = 0; d < GTAO_NUM_DIRECTIONS; d++)
    {
        float angle = randomAngle + d * (TWO_PI / GTAO_NUM_DIRECTIONS);
        float2 dir = float2(cos(angle), sin(angle));
        float2 stepUV = dir / _ScreenSize.xy * (_HBAO_Params.x / abs(posVS.z));
        
        // 双向地平线搜索
        float sinH_pos = -1.0, sinH_neg = -1.0;
        float sinN_bias = sin(radians(GTAO_ANGLE_BIAS));
        
        for (int s = 1; s <= GTAO_NUM_STEPS; s++)
        {
            // 正方向
            float3 sp = ReconstructPositionVS(uv + stepUV * s);
            float3 hv = sp - posVS;
            float dist = length(hv);
            float atten = 1.0 - saturate(dist * dist / (_HBAO_Params.x * _HBAO_Params.x));
            sinH_pos = max(sinH_pos, hv.z / (dist + 1e-5) * atten);
            
            // 负方向
            float3 sn = ReconstructPositionVS(uv - stepUV * s);
            hv = sn - posVS;
            dist = length(hv);
            atten = 1.0 - saturate(dist * dist / (_HBAO_Params.x * _HBAO_Params.x));
            sinH_neg = max(sinH_neg, hv.z / (dist + 1e-5) * atten);
        }
        
        sinH_pos = max(sinH_pos, sinN_bias);
        sinH_neg = max(sinH_neg, sinN_bias);
        
        // 法线投影
        float3 dirVS3 = float3(dir, 0);
        float cosN_proj = dot(normalVS, dirVS3);
        float sinN_proj = sqrt(max(0, 1.0 - cosN_proj * cosN_proj));
        
        float w = sinN_proj; // 法线在当前方向的权重
        visibilitySum += w * IntegrateArcCosWeight(sinH_neg, sinH_pos, cosN_proj, sinN_proj);
        weightSum += w;
    }
    
    float ao = weightSum > 0 ? visibilitySum / weightSum : 1.0;
    ao = saturate(1.0 - ao * _HBAO_Params2.y);
    
    // 多重弹射修正
    float albedo = dot(SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv).rgb, float3(0.333,0.333,0.333));
    ao = MultibounceApproximation(ao, albedo);
    
    return float4(ao, 0, 0, 1);
}
```

---

## 五、时域降噪（TAAO）

### 5.1 时域积累原理

```hlsl
// =====================================================
// TAAO：时域 AO 积累，用历史帧减少噪点
// 结合运动向量重投影，自适应混合权重
// =====================================================

TEXTURE2D(_HistoryAOTex);   SAMPLER(sampler_HistoryAOTex);
TEXTURE2D(_MotionVectors);  SAMPLER(sampler_MotionVectors);
TEXTURE2D(_CurrentAOTex);   SAMPLER(sampler_CurrentAOTex);

float4 _TAAO_Params; // x=blendFactor, y=velocityScale, z=disocclusionThreshold

float4 TAAOFragment(Varyings input) : SV_Target
{
    float2 uv = input.texcoord;
    
    // 读取运动向量（前一帧坐标偏移）
    float2 motion = SAMPLE_TEXTURE2D(_MotionVectors, sampler_MotionVectors, uv).rg;
    float2 prevUV = uv - motion * _TAAO_Params.y;
    
    float currentAO = SAMPLE_TEXTURE2D(_CurrentAOTex, sampler_CurrentAOTex, uv).r;
    
    // 检查重投影有效性（超出屏幕边界）
    bool validReprojection = all(prevUV >= 0) && all(prevUV <= 1);
    
    if (!validReprojection)
        return float4(currentAO, 0, 0, 1);
    
    float historyAO = SAMPLE_TEXTURE2D(_HistoryAOTex, sampler_HistoryAOTex, prevUV).r;
    
    // 当前帧邻域 Clamp（防止 ghosting）
    // 3x3 邻域的 min/max 约束历史值
    float minAO = 1.0, maxAO = 0.0;
    [unroll]
    for (int x = -1; x <= 1; x++)
    for (int y = -1; y <= 1; y++)
    {
        float2 neighborUV = uv + float2(x, y) / _ScreenSize.xy;
        float neighborAO = SAMPLE_TEXTURE2D(_CurrentAOTex, sampler_CurrentAOTex, neighborUV).r;
        minAO = min(minAO, neighborAO);
        maxAO = max(maxAO, neighborAO);
    }
    historyAO = clamp(historyAO, minAO, maxAO);
    
    // 自适应混合（快速变化区域使用更多当前帧）
    float aoChange = abs(currentAO - historyAO);
    float blendFactor = lerp(_TAAO_Params.x, 1.0, smoothstep(0.0, 0.3, aoChange));
    
    // 深度不连续检测（遮挡/解遮挡边界更新更快）
    float currentDepth = SampleSceneDepth(uv);
    float historyDepth = SampleSceneDepth(prevUV);
    float depthDiff = abs(currentDepth - historyDepth) / (currentDepth + 1e-4);
    blendFactor = lerp(blendFactor, 1.0, step(_TAAO_Params.z, depthDiff));
    
    float finalAO = lerp(historyAO, currentAO, blendFactor);
    return float4(finalAO, 0, 0, 1);
}
```

---

## 六、Unity URP AO 后处理集成

### 6.1 完整 ScriptableRenderPass 框架

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 完整的 AO 后处理渲染 Pass（SSAO/HBAO/GTAO 统一框架）
/// </summary>
public class AmbientOcclusionPass : ScriptableRenderPass
{
    public enum AOMethod { SSAO, HBAO, GTAO }
    
    private AOMethod _method;
    private Material _aoMaterial;
    private Material _blurMaterial;
    private Material _taaoMaterial;
    private Material _compositeMaterial;
    
    private RTHandle _aoBuffer;
    private RTHandle _blurBuffer;
    private RTHandle _historyBuffer;
    private RTHandle _prevHistoryBuffer;
    
    private static readonly int k_AOTexID  = Shader.PropertyToID("_AOTexture");
    private static readonly int k_ParamsID = Shader.PropertyToID("_SSAO_Params");
    
    private AmbientOcclusionSettings _settings;
    private int _frameIndex;

    public AmbientOcclusionPass(AOMethod method, AmbientOcclusionSettings settings)
    {
        _method = method;
        _settings = settings;
        renderPassEvent = RenderPassEvent.BeforeRenderingTransparents;
        
        // 加载对应 Shader
        string shaderName = method switch
        {
            AOMethod.SSAO => "Custom/SSAO",
            AOMethod.HBAO => "Custom/HBAO",
            AOMethod.GTAO => "Custom/GTAO",
            _ => "Custom/SSAO"
        };
        _aoMaterial = CoreUtils.CreateEngineMaterial(shaderName);
        _blurMaterial = CoreUtils.CreateEngineMaterial("Hidden/AOBilateralBlur");
        _taaoMaterial = CoreUtils.CreateEngineMaterial("Hidden/TAAO");
        _compositeMaterial = CoreUtils.CreateEngineMaterial("Hidden/AOComposite");
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.colorFormat = RenderTextureFormat.R8;
        desc.depthBufferBits = 0;
        desc.msaaSamples = 1;
        
        RenderingUtils.ReAllocateIfNeeded(ref _aoBuffer, desc, FilterMode.Bilinear, 
            TextureWrapMode.Clamp, name: "_AOBuffer");
        RenderingUtils.ReAllocateIfNeeded(ref _blurBuffer, desc, FilterMode.Bilinear, 
            TextureWrapMode.Clamp, name: "_AOBlurBuffer");
        
        // 历史缓冲需要全精度（TAAO）
        desc.colorFormat = RenderTextureFormat.RHalf;
        RenderingUtils.ReAllocateIfNeeded(ref _historyBuffer, desc, FilterMode.Bilinear, 
            TextureWrapMode.Clamp, name: "_AOHistoryBuffer");
        RenderingUtils.ReAllocateIfNeeded(ref _prevHistoryBuffer, desc, FilterMode.Bilinear, 
            TextureWrapMode.Clamp, name: "_AOPrevHistoryBuffer");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("AmbientOcclusion");
        
        using (new ProfilingScope(cmd, new ProfilingSampler("AO Pass")))
        {
            // 1. 设置 AO 参数
            _aoMaterial.SetVector(k_ParamsID, new Vector4(
                _settings.radius, _settings.bias, _settings.intensity, _settings.sampleCount));
            
            var cam = renderingData.cameraData.camera;
            _aoMaterial.SetMatrix("_InvProjectionMatrix", cam.projectionMatrix.inverse);
            _aoMaterial.SetMatrix("_ProjectionMatrix", cam.projectionMatrix);
            
            // 2. 计算 AO
            Blitter.BlitCameraTexture(cmd, _aoBuffer, _aoBuffer, _aoMaterial, 0);
            
            // 3. 双边模糊（保留边缘）
            cmd.SetGlobalTexture("_BlurSourceTex", _aoBuffer);
            Blitter.BlitCameraTexture(cmd, _aoBuffer, _blurBuffer, _blurMaterial, 0); // H Blur
            Blitter.BlitCameraTexture(cmd, _blurBuffer, _aoBuffer, _blurMaterial, 1); // V Blur
            
            // 4. TAAO 时域积累
            cmd.SetGlobalInt("_FrameIndex", _frameIndex++ % 8);
            cmd.SetGlobalTexture("_CurrentAOTex", _aoBuffer);
            cmd.SetGlobalTexture("_HistoryAOTex", _prevHistoryBuffer);
            Blitter.BlitCameraTexture(cmd, _aoBuffer, _historyBuffer, _taaoMaterial, 0);
            
            // 5. 合成到光照缓冲
            cmd.SetGlobalTexture(k_AOTexID, _historyBuffer);
            
            // 交换历史缓冲
            (_historyBuffer, _prevHistoryBuffer) = (_prevHistoryBuffer, _historyBuffer);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd) { }

    public void Dispose()
    {
        _aoBuffer?.Release();
        _blurBuffer?.Release();
        _historyBuffer?.Release();
        _prevHistoryBuffer?.Release();
        CoreUtils.Destroy(_aoMaterial);
        CoreUtils.Destroy(_blurMaterial);
        CoreUtils.Destroy(_taaoMaterial);
        CoreUtils.Destroy(_compositeMaterial);
    }
}

[System.Serializable]
public class AmbientOcclusionSettings
{
    [Range(0.01f, 2f)] public float radius = 0.3f;
    [Range(0f, 0.1f)]  public float bias = 0.025f;
    [Range(1f, 4f)]    public float intensity = 2f;
    [Range(4, 32)]     public int   sampleCount = 16;
    [Range(0f, 1f)]    public float temporalBlend = 0.1f;
    public bool enableTemporal = true;
}
```

### 6.2 双边模糊（保边滤波）

```hlsl
// 双边高斯模糊：根据深度/法线差异调整权重，保留几何边缘
TEXTURE2D(_BlurSourceTex); SAMPLER(sampler_BlurSourceTex);

float4 BilateralBlurH(Varyings input) : SV_Target
{
    float2 uv = input.texcoord;
    float centerDepth = SampleSceneDepth(uv);
    float centerNormal = SampleSceneNormals(uv).x;
    
    float result = 0.0;
    float totalWeight = 0.0;
    
    // 7-tap 高斯核（sigma=2）
    const float weights[4] = { 0.2270, 0.1945, 0.1216, 0.0540 };
    const int radius = 3;
    
    for (int i = -radius; i <= radius; i++)
    {
        float2 sampleUV = uv + float2(i, 0) / _ScreenSize.xy;
        float sampleDepth = SampleSceneDepth(sampleUV);
        float sampleNormal = SampleSceneNormals(sampleUV).x;
        
        // 深度权重（深度差异大时权重降低）
        float depthDiff = abs(centerDepth - sampleDepth);
        float depthWeight = exp(-depthDiff * depthDiff * 10.0);
        
        // 法线权重
        float normalDiff = abs(centerNormal - sampleNormal);
        float normalWeight = exp(-normalDiff * normalDiff * 4.0);
        
        float gaussWeight = weights[abs(i)];
        float w = gaussWeight * depthWeight * normalWeight;
        
        result += SAMPLE_TEXTURE2D(_BlurSourceTex, sampler_BlurSourceTex, sampleUV).r * w;
        totalWeight += w;
    }
    
    return float4(result / max(totalWeight, 1e-5), 0, 0, 1);
}
```

---

## 七、移动端优化策略

### 7.1 低开销 AO 方案

```csharp
/// <summary>
/// 移动端 AO 自适应质量管理器
/// 根据 GPU 帧时间动态调整 AO 质量
/// </summary>
public class MobileAOQualityManager : MonoBehaviour
{
    [Header("质量阈值（毫秒）")]
    public float targetFrameMs = 16.67f;  // 60fps
    public float ultraFrameMs  = 11.11f;  // 90fps（VR）
    
    private AmbientOcclusionPass _aoPass;
    private float _gpuFrameTime;

    public enum AOQualityLevel { Off, VeryLow, Low, Medium, High, Ultra }

    void Update()
    {
        // 采样 GPU 帧时间（Unity 2022.2+）
        _gpuFrameTime = Time.deltaTime * 1000f; // 简化估算

        AOQualityLevel quality = DetermineQuality(_gpuFrameTime);
        ApplyQuality(quality);
    }

    private AOQualityLevel DetermineQuality(float frameMs)
    {
        if (frameMs > targetFrameMs * 1.3f) return AOQualityLevel.Off;
        if (frameMs > targetFrameMs * 1.1f) return AOQualityLevel.VeryLow;
        if (frameMs > targetFrameMs)        return AOQualityLevel.Low;
        if (frameMs > ultraFrameMs * 1.5f)  return AOQualityLevel.Medium;
        if (frameMs > ultraFrameMs)         return AOQualityLevel.High;
        return AOQualityLevel.Ultra;
    }

    private void ApplyQuality(AOQualityLevel quality)
    {
        // 不同质量级别的配置
        var (samples, radius, resolution) = quality switch
        {
            AOQualityLevel.Off      => (0,     0f,   0),
            AOQualityLevel.VeryLow  => (4,     0.2f, 1),  // 半分辨率
            AOQualityLevel.Low      => (8,     0.25f, 1),
            AOQualityLevel.Medium   => (12,    0.3f,  0),
            AOQualityLevel.High     => (16,    0.35f, 0),
            AOQualityLevel.Ultra    => (24,    0.4f,  0),
            _ => (0, 0f, 0)
        };
        
        if (_aoPass != null)
        {
            // 应用到 AO Pass 设置...
        }
    }
}
```

---

## 八、最佳实践总结

### 8.1 AO 方案选型

| 平台 | 帧预算 < 2ms | 帧预算 2-4ms | 帧预算 > 4ms |
|---|---|---|---|
| 移动端 | 顶点 AO / Baked | 半分辨率 SSAO (4~8 samples) | SSAO + 双边模糊 |
| 主机 | SSAO (8~16 samples) | HBAO (8方向×4步) | GTAO + TAAO |
| PC | HBAO | GTAO | GTAO + RTAO 混合 |

### 8.2 质量提升技巧

1. **蓝噪声采样**：用 64x64 蓝噪声纹理代替白噪声，时域收敛更快
2. **重要性采样**：高频法线区域增加采样数，平坦区域减少
3. **Checkerboard Rendering**：棋盘格渲染 AO（半分辨率），时域重建
4. **Bent Normal**：GTAO 同时输出弯曲法线，用于更精确的环境光采样方向
5. **厚度感知**：对薄物体（叶片、布料）降低 AO 强度，避免过暗

### 8.3 常见失真与修复

| 现象 | 原因 | 解决方案 |
|---|---|---|
| 光晕/光环（halo artifact） | 采样深度边界跳变 | 增大 bias / 启用法线方向采样 |
| 噪点（noisy）| 采样数不足 | 增加 sample count 或启用 TAAO |
| 鬼影（ghosting） | TAAO 混合权重过低 | 降低 blend factor / 加强 clamp |
| 过暗（too dark）| intensity 过高 | 启用多重弹射修正 / 降低强度 |
| 边缘锯齿 | 双边模糊 sigma 不足 | 加大高斯核半径 |

---

## 结语

环境光遮蔽是"便宜却高回报"的视觉增强技术。SSAO 凭借实现简单、性能良好继续在移动端广泛使用；HBAO+ 在主机平台提供了物理更准确的地平线积分；GTAO 配合 TAAO 时域降噪，已成为 PC 端高画质游戏的标配。理解每种 AO 技术的数学本质，才能在不同性能预算下做出正确的取舍，让有限的 GPU 帧预算发挥最大的视觉价值。
