---
title: 游戏延迟渲染管线深度实践：G-Buffer设计、MRT多渲染目标与光照重建完全指南
published: 2026-04-16
description: 系统讲解延迟渲染管线（Deferred Rendering）的核心原理与工程实践，涵盖G-Buffer布局设计、MRT多渲染目标输出、法线编码方案、PBR光照重建、光源剔除算法、移动端TBDR优化及Unity URP延迟渲染集成完整代码。
tags: [Unity, 延迟渲染, G-Buffer, MRT, PBR, 光照系统]
category: 渲染技术
draft: false
---

# 游戏延迟渲染管线深度实践：G-Buffer 设计、MRT 多渲染目标与光照重建完全指南

## 一、延迟渲染概述

### 1.1 前向渲染 vs 延迟渲染

在前向渲染中，每个物体的光照计算在顶点/片元 Shader 中完成，光源数量直接影响渲染复杂度：

```
前向渲染复杂度：O(Objects × Lights)
延迟渲染复杂度：O(Objects + Lights × Pixels)
```

当场景中存在大量动态光源时，延迟渲染的优势显著：

```
场景：1000 个物体，100 盏动态点光源

前向渲染：1000 × 100 = 100,000 次光照计算（每物体每光源）
延迟渲染：1000（GBuffer填充） + 100 × ScreenPixels（光照Pass）
         → 光照仅对屏幕空间实际可见像素计算一次
```

### 1.2 延迟渲染管线总览

```
延迟渲染管线：

┌─────────────────────────────────────────────────────┐
│ Geometry Pass（几何阶段）                             │
│   渲染所有不透明物体 → 填充 G-Buffer (MRT)           │
│   输出：Albedo | Normal | Material | Depth           │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ Lighting Pass（光照阶段）                             │
│   读取 G-Buffer → 重建世界坐标 → PBR 光照计算        │
│   对每个光源（或光源 Tile）执行一次全屏/形状绘制     │
│   输出：HDR Lighting Buffer                          │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ Transparency Pass（透明阶段）                         │
│   透明物体回退到前向渲染（叠加到 Lighting Buffer）   │
└────────────────────┬────────────────────────────────┘
                     │
┌────────────────────▼────────────────────────────────┐
│ Post-Process Pass（后处理阶段）                       │
│   Bloom、DoF、TAA、Color Grading 等                  │
└─────────────────────────────────────────────────────┘
```

---

## 二、G-Buffer 布局设计

### 2.1 典型 G-Buffer 方案对比

G-Buffer 的布局设计是延迟渲染的核心工程决策，需要在精度、带宽、功能之间权衡：

| 方案 | 布局 | 带宽（1080p） | 特点 |
|------|------|--------------|------|
| **URP 默认** | RT0:RGBA8 + RT1:RGBA8 + RT2:RGBA8 + Depth | ~12 MB/帧 | 兼容性好 |
| **高精度方案** | RT0:RGBA8 + RT1:RGB10A2 + RT2:RG16 + Depth | ~14 MB/帧 | 法线精度高 |
| **移动端精简** | RT0:RGBA8 + RT1:RGBA8 + Depth | ~8 MB/帧 | SubPass 优化 |
| **HDRP 方案** | 5 个 RT（Albedo+Normal+Roughness+Emissive+Depth） | ~20 MB/帧 | 完整 PBR |

### 2.2 URP 内置 G-Buffer 布局

```
URP Deferred G-Buffer 布局（Unity 2021.3+）：

RT0  RGBA8_sRGB    [Albedo.rgb | Occlusion]
RT1  RGBA8         [SpecularColor.rgb | Smoothness]
RT2  RGB10A2       [Normal.xy（八面体编码）| Flags | Shadow mask]
RT3  RGBA16F       [BakedGI.rgb | 0]         （可选）
Depth  D32/D24S8   Depth + Stencil

注意：
- Normal 使用八面体编码（Octahedron Encoding）压缩到 RG10，精度优于球面编码
- Stencil 区分延迟光照区域（避免天空盒执行光照 Shader）
```

### 2.3 自定义 G-Buffer Shader 实现

```hlsl
// GBuffer.hlsl - G-Buffer 填充 Shader

#ifndef CUSTOM_GBUFFER_INCLUDED
#define CUSTOM_GBUFFER_INCLUDED

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/GBufferInput.hlsl"

// ─── G-Buffer 输出结构 ──────────────────────────────────────────────────────

struct GBufferOutput
{
    half4 GBuffer0 : SV_Target0;  // Albedo.rgb | Occlusion.a
    half4 GBuffer1 : SV_Target1;  // SpecColor.rgb | Smoothness.a
    half4 GBuffer2 : SV_Target2;  // Normal（八面体编码）| Material Flags
    // 注意：Depth 不在 MRT 中，使用 SV_Depth 或 Depth Attachment
};

// ─── 法线编码：八面体映射（Octahedron Encoding）────────────────────────────

/// 将单位向量编码为 [0,1]² 的 RG 值（比球面坐标精度更均匀）
float2 EncodeNormalOctahedron(float3 normal)
{
    // 八面体投影
    float3 n = normal / (abs(normal.x) + abs(normal.y) + abs(normal.z));
    
    // 折叠下半球
    if (n.z < 0.0)
    {
        float2 wrapped = (1.0 - abs(n.yx)) * sign(n.xy);
        n.xy = wrapped;
    }
    
    // 映射到 [0, 1]
    return n.xy * 0.5 + 0.5;
}

/// 从八面体编码解码法线
float3 DecodeNormalOctahedron(float2 encoded)
{
    float2 f = encoded * 2.0 - 1.0;
    
    // 从八面体坐标恢复
    float3 n = float3(f.xy, 1.0 - abs(f.x) - abs(f.y));
    
    float t = saturate(-n.z);
    n.xy += (n.xy >= 0.0) ? -t : t;
    
    return normalize(n);
}

// ─── 材质标志位（Stencil / GBuffer2.ba 的 Flag 位）──────────────────────────

#define GBUFFER_FLAG_RECEIVE_SHADOWS      (1 << 0)
#define GBUFFER_FLAG_SPECULAR_HIGHLIGHTS  (1 << 1)
#define GBUFFER_FLAG_ENVIRONMENT_REFLECT  (1 << 2)
#define GBUFFER_FLAG_IS_SUBSURFACE        (1 << 3)

// ─── Geometry Pass Fragment Shader ──────────────────────────────────────────

struct FragInput
{
    float4 positionCS   : SV_POSITION;
    float3 positionWS   : TEXCOORD0;
    float3 normalWS     : TEXCOORD1;
    float4 tangentWS    : TEXCOORD2;
    float2 uv           : TEXCOORD3;
    UNITY_VERTEX_INPUT_INSTANCE_ID
};

TEXTURE2D(_BaseMap);       SAMPLER(sampler_BaseMap);
TEXTURE2D(_NormalMap);     SAMPLER(sampler_NormalMap);
TEXTURE2D(_MetallicMap);   SAMPLER(sampler_MetallicMap);
TEXTURE2D(_OcclusionMap);  SAMPLER(sampler_OcclusionMap);

CBUFFER_START(UnityPerMaterial)
    half4 _BaseColor;
    half  _Metallic;
    half  _Smoothness;
    half  _OcclusionStrength;
    half  _NormalScale;
    uint  _MaterialFlags;
CBUFFER_END

GBufferOutput FragmentGBuffer(FragInput input)
{
    UNITY_SETUP_INSTANCE_ID(input);
    
    // ── 采样贴图 ──
    half4 albedoAlpha = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv) * _BaseColor;
    
    // Alpha 测试（裁剪透明部分）
    clip(albedoAlpha.a - 0.5);
    
    // 采样法线贴图并转换到世界空间
    half4 normalMapSample = SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, input.uv);
    float3 normalTS = UnpackNormalScale(normalMapSample, _NormalScale);
    
    float3 bitangentWS = cross(input.normalWS, input.tangentWS.xyz) * input.tangentWS.w;
    float3x3 TBN = float3x3(input.tangentWS.xyz, bitangentWS, input.normalWS);
    float3 normalWS = normalize(mul(normalTS, TBN));
    
    // 采样金属度/光滑度
    half4 metallicSample = SAMPLE_TEXTURE2D(_MetallicMap, sampler_MetallicMap, input.uv);
    half metallic   = metallicSample.r * _Metallic;
    half smoothness = metallicSample.a * _Smoothness;
    half occlusion  = LerpWhiteTo(
        SAMPLE_TEXTURE2D(_OcclusionMap, sampler_OcclusionMap, input.uv).g,
        _OcclusionStrength);
    
    // ── 计算高光颜色（金属工作流）──
    // 非金属 F0 ≈ 0.04，金属 F0 = albedo
    half3 specularColor = lerp(half3(0.04, 0.04, 0.04), albedoAlpha.rgb, metallic);
    half3 diffuseColor  = albedoAlpha.rgb * (1.0 - metallic);
    
    // ── 编码到 G-Buffer ──
    GBufferOutput output;
    
    // RT0: Diffuse Albedo + Occlusion
    output.GBuffer0 = half4(diffuseColor, occlusion);
    
    // RT1: Specular Color + Smoothness
    output.GBuffer1 = half4(specularColor, smoothness);
    
    // RT2: 法线（八面体编码） + Material Flags
    float2 encodedNormal = EncodeNormalOctahedron(normalWS);
    uint flags = _MaterialFlags;
    output.GBuffer2 = half4(encodedNormal.x, encodedNormal.y,
                            PackFloatInt8bit((half)0, flags, 8),  // 自定义打包
                            1.0);
    
    return output;
}

#endif // CUSTOM_GBUFFER_INCLUDED
```

---

## 三、从深度缓冲重建世界坐标

Lighting Pass 需要重建每个像素的世界坐标来进行光照计算：

```hlsl
// ReconstructPosition.hlsl

/// 从深度缓冲重建世界空间位置
/// @param uv         屏幕 UV [0,1]
/// @param deviceDepth 原始深度值（非线性）
float3 ReconstructWorldPosition(float2 uv, float deviceDepth,
    float4x4 invViewProj)
{
    // NDC 空间坐标（OpenGL 风格 Z ∈ [-1,1]，DirectX 风格 Z ∈ [0,1]）
    float3 ndcPos;
    ndcPos.xy = uv * 2.0 - 1.0;
    
#if UNITY_REVERSED_Z
    ndcPos.z = deviceDepth;  // DX: 深度已翻转，0=远，1=近
#else
    ndcPos.z = deviceDepth * 2.0 - 1.0;  // OpenGL: -1=近，1=远
#endif
    
    // 反投影到世界空间
    float4 worldPos = mul(invViewProj, float4(ndcPos, 1.0));
    worldPos.xyz /= worldPos.w;
    
    return worldPos.xyz;
}

/// 更高效的重建方法：使用相机射线插值
/// 适合 Fullscreen Quad 的顶点着色器
struct LightingVaryings
{
    float4 positionCS   : SV_POSITION;
    float2 uv           : TEXCOORD0;
    float3 cameraRay    : TEXCOORD1;  // 从相机到远裁面的方向
};

// 顶点着色器中计算射线（减少片元着色器中的矩阵乘法）
LightingVaryings LightingVertex(uint vertexID : SV_VertexID)
{
    LightingVaryings output;
    
    // 全屏三角形技巧（无需 VBO）
    output.uv = float2((vertexID << 1) & 2, vertexID & 2);
    output.positionCS = float4(output.uv * 2.0 - 1.0, 0.0, 1.0);
    
    // 计算该顶点对应的世界空间射线方向
    float4 clipPos = float4(output.positionCS.xy, 1.0, 1.0);
    float4 viewPos = mul(unity_CameraInvProjection, clipPos);
    viewPos /= viewPos.w;
    output.cameraRay = mul(unity_CameraToWorld, float4(viewPos.xyz, 0.0)).xyz;
    
    return output;
}

// 片元着色器中插值重建（无矩阵乘法）
float3 ReconstructPositionFromRay(float3 cameraRay, float deviceDepth)
{
    float linearDepth = LinearEyeDepth(deviceDepth, _ZBufferParams);
    
    // cameraRay 已包含方向信息，按深度缩放
    float3 worldPos = _WorldSpaceCameraPos + 
                      normalize(cameraRay) * linearDepth;
    return worldPos;
}
```

---

## 四、PBR 光照重建（Lighting Pass）

### 4.1 完整 PBR 光照 Shader

```hlsl
// DeferredLighting.hlsl - 延迟光照重建

#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

// G-Buffer 采样贴图
TEXTURE2D_X(_GBuffer0);  SAMPLER(sampler_GBuffer0);
TEXTURE2D_X(_GBuffer1);  SAMPLER(sampler_GBuffer1);
TEXTURE2D_X(_GBuffer2);  SAMPLER(sampler_GBuffer2);
TEXTURE2D_X(_CameraDepthTexture); SAMPLER(sampler_CameraDepthTexture);

// 光源参数（延迟光源 Uniform）
float4 _LightPosition;      // xyz: 位置, w: 1/Range^2
float4 _LightColor;         // rgb: 颜色*强度, a: 无用
float4 _LightDirection;     // xyz: 方向（点光源为0）, w: spotAngle
float4 _LightAttenuation;   // x: distAttenuation, y: angleAttenuation

/// Cook-Torrance BRDF（GGX NDF + Smith G + Fresnel Schlick）
half3 EvaluatePBR(half3 albedo, half3 specColor, half roughness,
                  float3 normalWS, float3 viewDirWS, float3 lightDirWS,
                  half3 lightColor)
{
    float3 halfVec = normalize(viewDirWS + lightDirWS);
    
    float NdotL = saturate(dot(normalWS, lightDirWS));
    float NdotV = saturate(dot(normalWS, viewDirWS)) + 1e-5;
    float NdotH = saturate(dot(normalWS, halfVec));
    float LdotH = saturate(dot(lightDirWS, halfVec));
    
    float alpha = roughness * roughness;
    float alpha2 = alpha * alpha;
    
    // ── GGX 法线分布函数（NDF）──
    // D(h) = α² / (π × ((NdotH² × (α²-1) + 1)²))
    float denom = NdotH * NdotH * (alpha2 - 1.0) + 1.0;
    float D = alpha2 / (UNITY_PI * denom * denom + 1e-7);
    
    // ── Smith G2（联合遮蔽-阴影函数）──
    // 使用 Schlick-GGX 近似
    float k = alpha * 0.5;
    float G_V = NdotV / (NdotV * (1.0 - k) + k);
    float G_L = NdotL / (NdotL * (1.0 - k) + k);
    float G = G_V * G_L;
    
    // ── Fresnel Schlick ──
    half3 F0 = specColor;
    half3 F = F0 + (1.0 - F0) * pow(1.0 - LdotH, 5.0);
    
    // ── 镜面 BRDF ──
    half3 specularBRDF = (D * G * F) / max(4.0 * NdotV * NdotL, 1e-7);
    
    // ── Lambert 漫反射（能量守恒：乘以 (1 - F) × (1 - metallic)，这里 albedo 已处理）──
    half3 diffuseBRDF = albedo / UNITY_PI;
    
    return (diffuseBRDF + specularBRDF) * lightColor * NdotL;
}

/// 计算点光源衰减
half PointLightAttenuation(float3 lightPos, float3 worldPos, float invRangeSq)
{
    float3 toLight = lightPos - worldPos;
    float distSq = dot(toLight, toLight);
    
    // 平方反比衰减（URP 使用的公式）
    float attenuation = 1.0 / (distSq * invRangeSq + 1.0);
    
    // 边界平滑淡出（避免突然截止）
    float normalizedDist = distSq * invRangeSq;
    float smoothOut = saturate(1.0 - normalizedDist * normalizedDist);
    
    return attenuation * smoothOut * smoothOut;
}

/// 计算聚光灯衰减
half SpotLightAttenuation(float3 lightPos, float3 lightDir, float3 worldPos,
    float2 spotAttenParams)  // x: cosInner, y: cosOuter
{
    float3 toLight = normalize(lightPos - worldPos);
    float cosAngle = dot(-lightDir, toLight);
    
    // 聚光灯角度衰减
    float angleAtten = saturate((cosAngle - spotAttenParams.y) /
                                (spotAttenParams.x - spotAttenParams.y));
    return angleAtten * angleAtten;
}

// ─── 主 Lighting Pass Fragment ───────────────────────────────────────────────

half4 DeferredLightingFragment(LightingVaryings input) : SV_Target
{
    float2 uv = input.uv;
    
    // ── 采样 G-Buffer ──
    half4 gbuffer0 = SAMPLE_TEXTURE2D_X(_GBuffer0, sampler_GBuffer0, uv);
    half4 gbuffer1 = SAMPLE_TEXTURE2D_X(_GBuffer1, sampler_GBuffer1, uv);
    half4 gbuffer2 = SAMPLE_TEXTURE2D_X(_GBuffer2, sampler_GBuffer2, uv);
    float deviceDepth = SAMPLE_TEXTURE2D_X(_CameraDepthTexture,
                            sampler_CameraDepthTexture, uv).r;
    
    // ── 解码 G-Buffer ──
    half3 albedo     = gbuffer0.rgb;
    half  occlusion  = gbuffer0.a;
    half3 specColor  = gbuffer1.rgb;
    half  smoothness = gbuffer1.a;
    half  roughness  = 1.0 - smoothness;
    
    // 解码法线（八面体编码）
    float3 normalWS = DecodeNormalOctahedron(gbuffer2.rg);
    
    // ── 重建世界坐标 ──
    float3 worldPos = ReconstructPositionFromRay(input.cameraRay, deviceDepth);
    float3 viewDir  = normalize(_WorldSpaceCameraPos - worldPos);
    
    // ── 计算光照 ──
    float3 lightVec = _LightPosition.xyz - worldPos;
    float3 lightDir = normalize(lightVec);
    
    // 点光源衰减
    half atten = PointLightAttenuation(_LightPosition.xyz, worldPos,
                                        _LightPosition.w);
    
    // PBR 光照
    half3 lighting = EvaluatePBR(albedo, specColor, roughness,
                                  normalWS, viewDir, lightDir,
                                  _LightColor.rgb * atten);
    
    // 应用 AO
    lighting *= occlusion;
    
    return half4(lighting, 0.0);  // 使用加法混合累积多光源
}
```

---

## 五、光源剔除与 Tile-Based 延迟渲染

### 5.1 Clustered Deferred 光源分块算法（C# 端）

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using Unity.Collections;
using Unity.Mathematics;

/// <summary>
/// Tile-Based 延迟光源分配系统
/// 将屏幕划分为 TileSize × TileSize 的块，预计算每块影响的光源列表
/// </summary>
public class TiledLightCuller
{
    private const int TileSize = 16;    // 每块像素尺寸（16×16 = 256 像素/块）
    private const int MaxLightsPerTile = 64;
    
    private GraphicsBuffer _lightListBuffer;    // 每 Tile 的光源索引列表
    private GraphicsBuffer _tileHeaderBuffer;   // 每 Tile 的光源数量与起始偏移
    private ComputeShader _lightCullCS;
    private int _kernel;
    
    public void Initialize(ComputeShader lightCullCS)
    {
        _lightCullCS = lightCullCS;
        _kernel = lightCullCS.FindKernel("TileLightCull");
    }
    
    public void Execute(CommandBuffer cmd, Camera camera,
        NativeArray<LightData> lights, int screenWidth, int screenHeight)
    {
        int tileCountX = Mathf.CeilToInt(screenWidth  / (float)TileSize);
        int tileCountY = Mathf.CeilToInt(screenHeight / (float)TileSize);
        int tileCount  = tileCountX * tileCountY;
        
        // 分配缓冲区（首次或分辨率变化时）
        if (_lightListBuffer == null || _lightListBuffer.count < tileCount * MaxLightsPerTile)
        {
            _lightListBuffer?.Dispose();
            _tileHeaderBuffer?.Dispose();
            
            _lightListBuffer = new GraphicsBuffer(
                GraphicsBuffer.Target.Structured,
                tileCount * MaxLightsPerTile, sizeof(uint));
            
            _tileHeaderBuffer = new GraphicsBuffer(
                GraphicsBuffer.Target.Structured,
                tileCount, sizeof(uint) * 2);  // [lightCount, startOffset]
        }
        
        // 上传光源数据
        using var lightBuffer = new GraphicsBuffer(
            GraphicsBuffer.Target.Structured,
            lights.Length, System.Runtime.InteropServices.Marshal.SizeOf<LightData>());
        lightBuffer.SetData(lights);
        
        // 设置 Compute Shader 参数
        cmd.SetComputeIntParam(_lightCullCS, "_TileCountX", tileCountX);
        cmd.SetComputeIntParam(_lightCullCS, "_TileCountY", tileCountY);
        cmd.SetComputeIntParam(_lightCullCS, "_LightCount", lights.Length);
        cmd.SetComputeIntParam(_lightCullCS, "_ScreenWidth", screenWidth);
        cmd.SetComputeIntParam(_lightCullCS, "_ScreenHeight", screenHeight);
        
        cmd.SetComputeMatrixParam(_lightCullCS, "_ViewMatrix", camera.worldToCameraMatrix);
        cmd.SetComputeMatrixParam(_lightCullCS, "_ProjMatrix", camera.projectionMatrix);
        
        cmd.SetComputeBufferParam(_lightCullCS, _kernel, "_Lights", lightBuffer);
        cmd.SetComputeBufferParam(_lightCullCS, _kernel, "_LightList", _lightListBuffer);
        cmd.SetComputeBufferParam(_lightCullCS, _kernel, "_TileHeader", _tileHeaderBuffer);
        
        cmd.DispatchCompute(_lightCullCS, _kernel, tileCountX, tileCountY, 1);
        
        // 将结果传递给 Lighting Shader
        cmd.SetGlobalBuffer("_TileLightList", _lightListBuffer);
        cmd.SetGlobalBuffer("_TileLightHeader", _tileHeaderBuffer);
        cmd.SetGlobalInt("_TileCountX", tileCountX);
    }
    
    public void Dispose()
    {
        _lightListBuffer?.Dispose();
        _tileHeaderBuffer?.Dispose();
    }
    
    [System.Runtime.InteropServices.StructLayout(
        System.Runtime.InteropServices.LayoutKind.Sequential)]
    public struct LightData
    {
        public float3 position;
        public float  range;
        public float3 color;
        public float  intensity;
        public float3 direction;   // 聚光灯方向
        public int    type;        // 0=点光 1=聚光 2=方向光
    }
}
```

### 5.2 Tile Light Cull Compute Shader

```hlsl
// TileLightCull.compute
#pragma kernel TileLightCull

#define TILE_SIZE 16
#define MAX_LIGHTS_PER_TILE 64

struct LightData
{
    float3 position;
    float  range;
    float3 color;
    float  intensity;
    float3 direction;
    int    type;
};

StructuredBuffer<LightData> _Lights;
RWStructuredBuffer<uint>    _LightList;
RWStructuredBuffer<uint2>   _TileHeader;  // [lightCount, startOffset]

int _TileCountX, _TileCountY, _LightCount, _ScreenWidth, _ScreenHeight;
float4x4 _ViewMatrix, _ProjMatrix;

groupshared uint gs_LightCount;
groupshared uint gs_LightIndices[MAX_LIGHTS_PER_TILE];
groupshared float4 gs_FrustumPlanes[4];  // Left, Right, Top, Bottom

[numthreads(TILE_SIZE, TILE_SIZE, 1)]
void TileLightCull(
    uint3 groupId       : SV_GroupID,
    uint3 groupThreadId : SV_GroupThreadID,
    uint  groupIndex    : SV_GroupIndex)
{
    uint tileX = groupId.x;
    uint tileY = groupId.y;
    uint tileIndex = tileY * _TileCountX + tileX;
    
    // 初始化共享内存
    if (groupIndex == 0)
    {
        gs_LightCount = 0;
        
        // 计算 Tile 视锥面
        float2 tileMin = float2(tileX, tileY) * TILE_SIZE;
        float2 tileMax = tileMin + TILE_SIZE;
        
        // 转换到 NDC
        float2 ndcMin = tileMin / float2(_ScreenWidth, _ScreenHeight) * 2.0 - 1.0;
        float2 ndcMax = tileMax / float2(_ScreenWidth, _ScreenHeight) * 2.0 - 1.0;
        
        // 从投影矩阵提取平截头体平面（简化版）
        float4x4 invProj = transpose(_ProjMatrix);  // 近似
        gs_FrustumPlanes[0] = float4(1, 0, 0, -ndcMin.x);  // Left
        gs_FrustumPlanes[1] = float4(-1, 0, 0, ndcMax.x);  // Right
        gs_FrustumPlanes[2] = float4(0, 1, 0, -ndcMin.y);  // Bottom
        gs_FrustumPlanes[3] = float4(0, -1, 0, ndcMax.y);  // Top
    }
    
    GroupMemoryBarrierWithGroupSync();
    
    // 每线程分担部分光源检测
    for (uint i = groupIndex; i < (uint)_LightCount; i += TILE_SIZE * TILE_SIZE)
    {
        LightData light = _Lights[i];
        
        // 光源包围球到视图空间
        float4 lightViewPos = mul(_ViewMatrix, float4(light.position, 1.0));
        float radius = light.range;
        
        // 与 Tile 视锥体进行球-平面检测
        bool inFrustum = true;
        [unroll]
        for (int p = 0; p < 4; p++)
        {
            float dist = dot(gs_FrustumPlanes[p].xyz, lightViewPos.xyz) + gs_FrustumPlanes[p].w;
            if (dist < -radius)
            {
                inFrustum = false;
                break;
            }
        }
        
        if (inFrustum)
        {
            uint slot;
            InterlockedAdd(gs_LightCount, 1, slot);
            if (slot < MAX_LIGHTS_PER_TILE)
            {
                gs_LightIndices[slot] = i;
            }
        }
    }
    
    GroupMemoryBarrierWithGroupSync();
    
    // 仅一个线程将结果写入全局缓冲
    if (groupIndex == 0)
    {
        uint count = min(gs_LightCount, MAX_LIGHTS_PER_TILE);
        uint startOffset = tileIndex * MAX_LIGHTS_PER_TILE;
        
        _TileHeader[tileIndex] = uint2(count, startOffset);
        
        for (uint k = 0; k < count; k++)
        {
            _LightList[startOffset + k] = gs_LightIndices[k];
        }
    }
}
```

---

## 六、移动端 TBDR 延迟渲染优化

### 6.1 Memoryless G-Buffer

在移动端 GPU（PowerVR, Adreno, Mali 等 Tile-Based 架构）上，G-Buffer 可设置为 Memoryless，使其常驻 On-Chip Memory，完全避免写回主内存：

```csharp
// Unity URP 移动端延迟渲染配置
// Inspector 中：
// Universal Render Pipeline Asset:
//   ✓ Use Rendering Layers
//   Deferred Rendering:
//     Store Actions: SubpassInput  ← 关键：使 GBuffer 不写回主存

// 代码验证是否支持 Native Render Pass
bool supportsNativeRenderPass = SystemInfo.graphicsDeviceType == GraphicsDeviceType.Metal
                             || SystemInfo.graphicsDeviceType == GraphicsDeviceType.Vulkan;

if (supportsNativeRenderPass)
{
    // G-Buffer 将作为 Tile Memory 使用，Lighting Pass 作为 SubPass
    // 整个 GBuffer Fill → Lighting 流程带宽消耗 ≈ 0
    Debug.Log("Native Render Pass (SubPass) enabled: GBuffer is memoryless");
}
```

### 6.2 Stencil 掩码优化

```hlsl
// 利用 Stencil 避免在天空盒像素上执行延迟光照
// Geometry Pass 写入 Stencil
Stencil
{
    Ref 128
    Comp Always
    Pass Replace  // 所有几何体像素写入 Stencil = 128
}

// Lighting Pass 只处理 Stencil = 128 的像素（跳过天空盒）
Stencil
{
    Ref 128
    Comp Equal    // 只处理有几何体的像素
    Pass Keep
}
```

---

## 七、透明物体处理策略

延迟渲染的核心局限是无法原生支持透明物体（G-Buffer 只能存储单层信息）：

```csharp
/// <summary>
/// 延迟渲染中透明物体的处理策略枚举
/// </summary>
public enum TransparencyStrategy
{
    /// <summary>
    /// 策略1：前向渲染回退（URP 默认）
    /// 透明物体在延迟光照后用前向 Pass 单独渲染
    /// 优点：完整支持透明效果
    /// 缺点：透明物体仍受光源数量限制
    /// </summary>
    ForwardFallback,
    
    /// <summary>
    /// 策略2：OIT 顺序无关透明（Order-Independent Transparency）
    /// 使用 PerPixel Linked List 或 WBOIT 权重混合
    /// 优点：正确的透明排序
    /// 缺点：内存和带宽开销大
    /// </summary>
    OrderIndependentTransparency,
    
    /// <summary>
    /// 策略3：Depth Peeling
    /// 多次 Pass 逐层剥离透明层
    /// 优点：精确排序
    /// 缺点：Pass 数量多，性能低
    /// </summary>
    DepthPeeling,
}

// URP 中的透明物体前向渲染配置
// 透明物体的 RenderQueue > 2500 会自动使用前向路径
// Material Inspector: Rendering Mode = Transparent → 自动分配到前向 Pass
```

---

## 八、延迟渲染完整 C# 集成

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 自定义延迟渲染 Renderer Feature（URP 集成示例）
/// </summary>
public class CustomDeferredRenderFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class DeferredSettings
    {
        public bool enableTiledLighting = true;
        public int maxLightsPerTile = 64;
        public Material gbufferMaterial;
        public Material lightingMaterial;
        public ComputeShader lightCullCS;
    }
    
    public DeferredSettings settings;
    
    private CustomGBufferPass _gbufferPass;
    private CustomDeferredLightingPass _lightingPass;
    private TiledLightCuller _lightCuller;
    
    public override void Create()
    {
        _lightCuller = new TiledLightCuller();
        if (settings.lightCullCS != null)
            _lightCuller.Initialize(settings.lightCullCS);
        
        _gbufferPass = new CustomGBufferPass(settings.gbufferMaterial)
        {
            renderPassEvent = RenderPassEvent.AfterRenderingOpaques
        };
        
        _lightingPass = new CustomDeferredLightingPass(
            settings.lightingMaterial, _lightCuller)
        {
            renderPassEvent = RenderPassEvent.AfterRenderingOpaques + 1
        };
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer,
        ref RenderingData renderingData)
    {
        // 只在延迟渲染模式下启用（检查 URP Asset 设置）
        var urpData = renderingData.cameraData.renderer as UniversalRenderer;
        if (urpData == null) return;
        
        renderer.EnqueuePass(_gbufferPass);
        renderer.EnqueuePass(_lightingPass);
    }
    
    protected override void Dispose(bool disposing)
    {
        _lightCuller?.Dispose();
    }
}
```

---

## 九、最佳实践总结

### 9.1 G-Buffer 设计原则

| 原则 | 说明 |
|------|------|
| **最小化 RT 数量** | 每增加一个 RT 带来额外的带宽与内存开销 |
| **选择合适的精度** | 法线用 R10G10B10A2，Albedo 用 R8G8B8A8，避免过度精度 |
| **八面体编码法线** | 精度均匀，优于 Lambert 球面编码或 Spheremap 编码 |
| **金属工作流预计算** | Geometry Pass 中拆分 Diffuse/Specular，减少 Lighting Pass 复杂度 |
| **利用 Stencil** | 用 Stencil 标记不同材质类型（标准PBR/SSS/自发光），实现多套光照路径 |

### 9.2 性能关键点

```
性能优化清单：
✓ 移动端使用 SubPass Input（G-Buffer 常驻 Tile Memory）
✓ 使用 Stencil 掩码跳过天空盒/无效像素的光照计算
✓ Tiled/Clustered Deferred 替代逐光源全屏 Pass
✓ 光源形状绘制（球体/圆锥）代替全屏 Pass（减少 Shading 像素数）
✓ 大光源 Back Face Culling（相机在球内时正常；相机在球外时 Front Face Culling）
✓ 透明物体优先使用前向渲染，避免 OIT 的额外开销
```

### 9.3 何时使用延迟渲染

```
✓ 适合延迟渲染的场景：
  - 大量动态点光源（>8个）
  - 需要屏幕空间效果（SSAO, SSR, 屏幕空间阴影）
  - 桌面端/主机端高画质渲染

✗ 不适合延迟渲染的场景：
  - 移动端带宽受限（G-Buffer 带宽消耗大，除非有 TBDR 优化）
  - 大量透明物体的场景（UI 密集、VFX 密集）
  - MSAA 需求高的场景（延迟渲染与 MSAA 兼容性差）
  - 目标硬件不支持 MRT（极少见）
```

---

## 十、总结

延迟渲染管线是现代游戏引擎处理复杂光照场景的核心技术，其核心价值在于将光照计算复杂度从 `O(Objects × Lights)` 降低到 `O(Objects + Lights × Pixels)`。通过合理的 G-Buffer 布局设计、高效的法线编码方案（八面体编码）、Tile-Based 光源剔除算法以及移动端 SubPass 优化，可以在保证视觉效果的前提下最大化渲染性能。理解延迟渲染的原理与工程细节，是游戏图形工程师迈向高级渲染开发的重要基石。
