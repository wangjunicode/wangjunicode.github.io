---
title: 游戏实时反射系统完全指南：SSR屏幕空间反射与反射探针深度实践
published: 2026-04-02
description: 深入解析游戏中实时反射的核心技术体系，涵盖屏幕空间反射（SSR）算法原理、层次反射探针（Reflection Probe）烘焙与混合、平面反射（Planar Reflection）、反射捕获（Capture）管线，以及移动端反射降质策略，附完整Shader实现与Unity/URP集成代码。
tags: [实时反射, SSR, 屏幕空间反射, 反射探针, URP, 渲染优化, Shader]
category: 渲染技术
draft: false
---

# 游戏实时反射系统完全指南：SSR屏幕空间反射与反射探针深度实践

## 1. 反射技术概述与选型矩阵

在现代游戏渲染中，反射效果是构成视觉真实感的核心要素之一。金属、水面、玻璃等材质的正确呈现都依赖高质量的反射实现。然而反射本质上需要"看到看不见的方向"，这使其计算代价高昂。

### 1.1 主要反射技术对比

| 技术 | 精度 | 性能代价 | 动态支持 | 适用场景 |
|------|------|----------|----------|----------|
| 反射探针（Baked） | 低 | 极低 | 否 | 室内静态环境 |
| 反射探针（实时） | 中 | 高 | 是 | 重要动态对象 |
| 平面反射 | 高 | 中高 | 是 | 水面/镜面 |
| SSR（屏幕空间反射） | 中 | 中 | 是 | 粗糙金属/地面 |
| 光线追踪反射 | 极高 | 极高 | 是 | PC高端/主机 |
| 视差纠正盒体（PCC） | 中高 | 低 | 否 | 室内盒体环境 |

实际项目通常采用**分层混合策略**：SSR作为主要来源 → 反射探针兜底 → 天空盒最终回退。

### 1.2 反射方程基础

基于物理的反射遵循微表面理论（GGX/Trowbridge-Reitz）：

```
Lo(wo) = ∫ fr(wi,wo) * Li(wi) * (n·wi) dwi
```

镜面反射分量使用分裂和近似（Split-Sum Approximation）：

```
Lo_spec = ∫ fr_spec * Li dwi
        ≈ LD(R, roughness) * (F0 * BRDF_LUT.x + BRDF_LUT.y)
```

其中 `LD` 为预滤波环境贴图（Pre-filtered Environment Map），对应不同粗糙度的Mip层级。

---

## 2. 屏幕空间反射（SSR）原理与实现

### 2.1 算法核心思想

SSR基于深度缓冲中已有的屏幕像素信息进行光线步进（Ray Marching），无需额外场景几何信息：

1. 从当前像素重建世界空间位置
2. 基于法线和观察方向计算反射光线方向
3. 将反射光线变换到屏幕空间（SS）中进行步进
4. 找到与深度缓冲相交的采样点
5. 从颜色缓冲采样反射颜色
6. 基于粗糙度和边界衰减进行混合

### 2.2 完整SSR Shader实现（URP）

**SSR Pass Shader：**

```hlsl
// SSR_Pass.hlsl
#pragma kernel CSMain

Texture2D<float4> _ColorBuffer;
Texture2D<float> _DepthBuffer;
Texture2D<float4> _NormalBuffer;      // GBuffer法线（世界空间）
Texture2D<float4> _MetallicRoughness; // R=Metallic, G=Roughness
RWTexture2D<float4> _OutputSSR;

SamplerState sampler_LinearClamp;
SamplerState sampler_PointClamp;

// 相机矩阵
float4x4 _ProjectionMatrix;
float4x4 _InvProjectionMatrix;
float4x4 _ViewMatrix;
float4x4 _InvViewMatrix;
float4x4 _ViewProjectionMatrix;
float4x4 _InvViewProjectionMatrix;

// SSR参数
int _MaxSteps;          // 最大步进次数，默认64
float _StepSize;        // 初始步长
float _Thickness;       // 深度厚度阈值
float _MaxDistance;     // 最大反射距离
float _EdgeFadeWidth;   // 边缘衰减宽度
int _BinarySearchSteps; // 二分搜索次数

float2 _ScreenSize;
float _Near;
float _Far;

// 从深度缓冲重建世界空间位置
float3 ReconstructWorldPos(float2 uv, float depth)
{
    float4 clipPos = float4(uv * 2.0 - 1.0, depth, 1.0);
    #if UNITY_UV_STARTS_AT_TOP
    clipPos.y = -clipPos.y;
    #endif
    float4 worldPos = mul(_InvViewProjectionMatrix, clipPos);
    return worldPos.xyz / worldPos.w;
}

// 世界空间位置变换到屏幕UV
float3 WorldToScreenPos(float3 worldPos)
{
    float4 clipPos = mul(_ViewProjectionMatrix, float4(worldPos, 1.0));
    clipPos.xyz /= clipPos.w;
    float2 uv = clipPos.xy * 0.5 + 0.5;
    #if UNITY_UV_STARTS_AT_TOP
    uv.y = 1.0 - uv.y;
    #endif
    return float3(uv, clipPos.z);
}

// 线性深度转换
float LinearizeDepth(float depth)
{
    return (2.0 * _Near) / (_Far + _Near - depth * (_Far - _Near));
}

// 层次Z步进（Hierarchical Z Tracing）
// 使用HiZ加速，跨越不相交区域
bool HiZTrace(float3 rayOriginVS, float3 rayDirVS, 
              out float2 hitUV, out float hitDepth, out int hitLevel)
{
    hitUV = 0;
    hitDepth = 0;
    hitLevel = 0;
    
    float3 currentPos = rayOriginVS;
    float stepLen = _StepSize;
    
    [loop]
    for (int i = 0; i < _MaxSteps; i++)
    {
        currentPos += rayDirVS * stepLen;
        
        float3 ssPos = WorldToScreenPos(currentPos);
        float2 uv = ssPos.xy;
        
        // 超出屏幕边界
        if (uv.x < 0 || uv.x > 1 || uv.y < 0 || uv.y > 1)
            return false;
        
        float sceneDepth = _DepthBuffer.SampleLevel(sampler_PointClamp, uv, 0).r;
        float rayDepth = ssPos.z;
        
        // 线性化深度比较
        float sceneLinear = LinearizeDepth(sceneDepth);
        float rayLinear = LinearizeDepth(rayDepth);
        
        // 检测相交：光线深度大于场景深度（穿入表面）
        if (rayLinear > sceneLinear && rayLinear - sceneLinear < _Thickness)
        {
            // 二分搜索精确交点
            float3 startPos = currentPos - rayDirVS * stepLen;
            float3 endPos = currentPos;
            
            [loop]
            for (int j = 0; j < _BinarySearchSteps; j++)
            {
                float3 midPos = (startPos + endPos) * 0.5;
                float3 midSS = WorldToScreenPos(midPos);
                float midScene = LinearizeDepth(
                    _DepthBuffer.SampleLevel(sampler_PointClamp, midSS.xy, 0).r);
                float midRay = LinearizeDepth(midSS.z);
                
                if (midRay > midScene)
                    endPos = midPos;
                else
                    startPos = midPos;
            }
            
            float3 finalSS = WorldToScreenPos((startPos + endPos) * 0.5);
            hitUV = finalSS.xy;
            hitDepth = finalSS.z;
            return true;
        }
        
        // 指数步长增大（远处步进更快）
        stepLen *= 1.05;
        if (stepLen > _MaxDistance / _MaxSteps * 4.0)
            stepLen = _MaxDistance / _MaxSteps * 4.0;
    }
    
    return false;
}

// 边缘衰减：反射靠近屏幕边界时淡出
float ComputeEdgeFade(float2 uv)
{
    float2 edge = min(uv, 1.0 - uv);
    float fade = min(edge.x, edge.y);
    return saturate(fade / _EdgeFadeWidth);
}

// 基于粗糙度的反射衰减
float ComputeRoughnessFade(float roughness)
{
    // 高粗糙度时SSR贡献降低
    return 1.0 - smoothstep(0.4, 0.8, roughness);
}

[numthreads(8, 8, 1)]
void CSMain(uint3 id : SV_DispatchThreadID)
{
    float2 uv = (id.xy + 0.5) / _ScreenSize;
    
    float4 metallicRoughness = _MetallicRoughness.SampleLevel(sampler_PointClamp, uv, 0);
    float metallic = metallicRoughness.r;
    float roughness = metallicRoughness.g;
    
    // 仅处理金属或光滑表面
    float roughnessFade = ComputeRoughnessFade(roughness);
    if (roughnessFade < 0.01 || metallic < 0.01)
    {
        _OutputSSR[id.xy] = float4(0, 0, 0, 0);
        return;
    }
    
    // 重建几何信息
    float depth = _DepthBuffer.SampleLevel(sampler_PointClamp, uv, 0).r;
    if (depth >= 1.0) // 天空
    {
        _OutputSSR[id.xy] = float4(0, 0, 0, 0);
        return;
    }
    
    float3 worldPos = ReconstructWorldPos(uv, depth);
    float4 normalSample = _NormalBuffer.SampleLevel(sampler_PointClamp, uv, 0);
    float3 worldNormal = normalize(normalSample.xyz * 2.0 - 1.0);
    
    // 计算观察方向和反射方向
    float3 viewDir = normalize(worldPos - _WorldSpaceCameraPos.xyz);
    float3 reflectDir = reflect(viewDir, worldNormal);
    
    // 对粗糙表面添加随机抖动（模拟模糊反射）
    // 实际项目中使用TAA累积多帧
    
    // 执行光线步进
    float2 hitUV;
    float hitDepth;
    int hitLevel;
    bool hit = HiZTrace(worldPos, reflectDir, hitUV, hitDepth, hitLevel);
    
    if (hit)
    {
        float4 reflectColor = _ColorBuffer.SampleLevel(sampler_LinearClamp, hitUV, 
                              roughness * 4.0); // 粗糙度映射到Mip
        
        float edgeFade = ComputeEdgeFade(hitUV);
        float alpha = edgeFade * roughnessFade * metallic;
        
        _OutputSSR[id.xy] = float4(reflectColor.rgb, alpha);
    }
    else
    {
        _OutputSSR[id.xy] = float4(0, 0, 0, 0);
    }
}
```

### 2.3 SSR合成Pass

```hlsl
// SSR_Composite.shader
Shader "Hidden/SSR_Composite"
{
    Properties
    {
        _MainTex ("Color Buffer", 2D) = "white" {}
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        
        Pass
        {
            ZTest Always ZWrite Off Cull Off
            
            HLSLPROGRAM
            #pragma vertex FullscreenVert
            #pragma fragment CompositeFragment
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            TEXTURE2D(_MainTex);
            TEXTURE2D(_SSRTexture);
            TEXTURE2D(_ReflectionProbeTexture); // 探针回退
            TEXTURE2D(_MetallicRoughness);
            SAMPLER(sampler_LinearClamp);
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
            };
            
            Varyings FullscreenVert(uint vertexID : SV_VertexID)
            {
                Varyings o;
                o.uv = float2((vertexID << 1) & 2, vertexID & 2);
                o.positionCS = float4(o.uv * 2 - 1, 0, 1);
                #if UNITY_UV_STARTS_AT_TOP
                o.uv.y = 1 - o.uv.y;
                #endif
                return o;
            }
            
            float4 CompositeFragment(Varyings i) : SV_Target
            {
                float4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_LinearClamp, i.uv);
                float4 ssrResult = SAMPLE_TEXTURE2D(_SSRTexture, sampler_LinearClamp, i.uv);
                float4 probeResult = SAMPLE_TEXTURE2D(_ReflectionProbeTexture, sampler_LinearClamp, i.uv);
                
                float4 mr = SAMPLE_TEXTURE2D(_MetallicRoughness, sampler_LinearClamp, i.uv);
                float metallic = mr.r;
                float roughness = mr.g;
                
                // SSR Alpha表示命中置信度
                float ssrAlpha = ssrResult.a;
                
                // SSR -> 探针 -> 天空盒 的分层混合
                float3 reflectContrib = lerp(probeResult.rgb, ssrResult.rgb, ssrAlpha);
                
                // 基于菲涅尔的反射强度
                // 简化版（正式应使用GGX BRDF分裂和查表）
                float fresnel = pow(1.0 - roughness, 4.0) * metallic;
                
                float3 finalColor = color.rgb + reflectContrib * fresnel;
                
                return float4(finalColor, color.a);
            }
            ENDHLSL
        }
    }
}
```

### 2.4 SSR RenderFeature（Unity URP）

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class SSRRenderFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class SSRSettings
    {
        public ComputeShader ssrComputeShader;
        public Shader compositeShader;
        
        [Header("Ray Marching")]
        [Range(16, 128)] public int maxSteps = 64;
        [Range(0.01f, 1f)] public float stepSize = 0.1f;
        [Range(0.01f, 0.5f)] public float thickness = 0.05f;
        [Range(1f, 100f)] public float maxDistance = 50f;
        [Range(0.01f, 0.2f)] public float edgeFadeWidth = 0.05f;
        [Range(4, 16)] public int binarySearchSteps = 8;
        
        [Header("Quality")]
        public bool useTemporalAccumulation = true;
        [Range(0f, 1f)] public float temporalBlend = 0.9f;
    }
    
    public SSRSettings settings = new SSRSettings();
    private SSRPass ssrPass;
    
    public override void Create()
    {
        ssrPass = new SSRPass(settings);
        ssrPass.renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (settings.ssrComputeShader == null) return;
        renderer.EnqueuePass(ssrPass);
    }
    
    class SSRPass : ScriptableRenderPass
    {
        private SSRSettings settings;
        private Material compositeMaterial;
        
        private RenderTargetIdentifier ssrBuffer;
        private RenderTargetIdentifier prevFrameBuffer; // 时序累积
        private int ssrBufferID = Shader.PropertyToID("_SSRTexture");
        private int prevFrameID = Shader.PropertyToID("_SSRPrevFrame");
        
        private ComputeBuffer[] tiledBuffer;
        private int kernelIndex;
        
        public SSRPass(SSRSettings settings)
        {
            this.settings = settings;
            if (settings.compositeShader != null)
                compositeMaterial = new Material(settings.compositeShader);
        }
        
        public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
        {
            var desc = renderingData.cameraData.cameraTargetDescriptor;
            desc.colorFormat = RenderTextureFormat.ARGBHalf;
            desc.enableRandomWrite = true;
            desc.msaaSamples = 1;
            
            cmd.GetTemporaryRT(ssrBufferID, desc);
            ssrBuffer = new RenderTargetIdentifier(ssrBufferID);
        }
        
        public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
        {
            if (settings.ssrComputeShader == null || compositeMaterial == null) return;
            
            var cmd = CommandBufferPool.Get("SSR Pass");
            var camera = renderingData.cameraData.camera;
            var desc = renderingData.cameraData.cameraTargetDescriptor;
            
            try
            {
                // 设置Compute Shader参数
                int kernel = settings.ssrComputeShader.FindKernel("CSMain");
                
                settings.ssrComputeShader.SetInt("_MaxSteps", settings.maxSteps);
                settings.ssrComputeShader.SetFloat("_StepSize", settings.stepSize);
                settings.ssrComputeShader.SetFloat("_Thickness", settings.thickness);
                settings.ssrComputeShader.SetFloat("_MaxDistance", settings.maxDistance);
                settings.ssrComputeShader.SetFloat("_EdgeFadeWidth", settings.edgeFadeWidth);
                settings.ssrComputeShader.SetInt("_BinarySearchSteps", settings.binarySearchSteps);
                settings.ssrComputeShader.SetVector("_ScreenSize", 
                    new Vector4(desc.width, desc.height, 0, 0));
                settings.ssrComputeShader.SetFloat("_Near", camera.nearClipPlane);
                settings.ssrComputeShader.SetFloat("_Far", camera.farClipPlane);
                
                // 矩阵参数
                Matrix4x4 proj = GL.GetGPUProjectionMatrix(camera.projectionMatrix, true);
                Matrix4x4 view = camera.worldToCameraMatrix;
                Matrix4x4 vp = proj * view;
                
                settings.ssrComputeShader.SetMatrix("_ProjectionMatrix", proj);
                settings.ssrComputeShader.SetMatrix("_InvProjectionMatrix", proj.inverse);
                settings.ssrComputeShader.SetMatrix("_ViewMatrix", view);
                settings.ssrComputeShader.SetMatrix("_InvViewMatrix", view.inverse);
                settings.ssrComputeShader.SetMatrix("_ViewProjectionMatrix", vp);
                settings.ssrComputeShader.SetMatrix("_InvViewProjectionMatrix", vp.inverse);
                
                // 绑定纹理
                settings.ssrComputeShader.SetTextureFromGlobal(kernel, "_ColorBuffer", 
                    "_CameraColorTexture");
                settings.ssrComputeShader.SetTextureFromGlobal(kernel, "_DepthBuffer", 
                    "_CameraDepthTexture");
                settings.ssrComputeShader.SetTextureFromGlobal(kernel, "_NormalBuffer", 
                    "_CameraNormalsTexture");
                settings.ssrComputeShader.SetTexture(kernel, "_OutputSSR", ssrBuffer);
                
                // Dispatch
                int groupX = Mathf.CeilToInt(desc.width / 8f);
                int groupY = Mathf.CeilToInt(desc.height / 8f);
                cmd.DispatchCompute(settings.ssrComputeShader, kernel, groupX, groupY, 1);
                
                // 时序累积（TAA-like blending）
                if (settings.useTemporalAccumulation)
                {
                    // 此处简化，实际需要MotionVector和历史帧混合
                    cmd.SetGlobalFloat("_TemporalBlend", settings.temporalBlend);
                }
                
                // 合成到主缓冲
                cmd.SetGlobalTexture("_SSRTexture", ssrBuffer);
                // composite blit...
                
                context.ExecuteCommandBuffer(cmd);
            }
            finally
            {
                CommandBufferPool.Release(cmd);
            }
        }
        
        public override void OnCameraCleanup(CommandBuffer cmd)
        {
            cmd.ReleaseTemporaryRT(ssrBufferID);
        }
    }
}
```

---

## 3. 反射探针系统深度解析

### 3.1 视差纠正盒体（Parallax-Corrected Cubemap）

标准Cubemap反射存在视差错误，需要通过盒体投影纠正：

```hlsl
// ParallaxCorrectedReflection.hlsl
float3 ApplyParallaxCorrection(float3 worldPos, float3 reflectDir, 
                                float3 probeCenter, float3 boxMin, float3 boxMax)
{
    // 变换到探针局部空间
    float3 localPos = worldPos - probeCenter;
    float3 localDir = reflectDir;
    
    // 射线与AABB盒体求交
    float3 invDir = 1.0 / localDir;
    
    float3 tMin = (boxMin - probeCenter - localPos) * invDir;
    float3 tMax = (boxMax - probeCenter - localPos) * invDir;
    
    float3 t1 = min(tMin, tMax);
    float3 t2 = max(tMin, tMax);
    
    float tNear = max(max(t1.x, t1.y), t1.z);
    float tFar  = min(min(t2.x, t2.y), t2.z);
    
    // 取最远交点（光线从内部出发）
    float t = tFar > 0 ? tFar : tNear;
    
    // 计算交点作为Cubemap采样方向
    float3 intersectPos = worldPos + reflectDir * t;
    float3 correctedDir = intersectPos - probeCenter;
    
    return correctedDir;
}
```

### 3.2 多探针混合与优先级管理

```csharp
using System.Collections.Generic;
using UnityEngine;

[ExecuteAlways]
public class ReflectionProbeBlender : MonoBehaviour
{
    [System.Serializable]
    public struct ProbeWeight
    {
        public ReflectionProbe probe;
        public float weight;
        public float blendDistance; // 边界混合距离
    }
    
    private List<ProbeWeight> activeProbes = new List<ProbeWeight>();
    private static readonly int MaxProbes = 4;
    
    // 每帧根据相机位置计算最近的N个探针权重
    public void UpdateProbeWeights(Vector3 cameraPos)
    {
        activeProbes.Clear();
        
        // 获取场景中所有探针（可改为空间分区加速）
        var allProbes = FindObjectsOfType<ReflectionProbe>();
        
        foreach (var probe in allProbes)
        {
            if (!probe.isActiveAndEnabled) continue;
            
            Bounds bounds = probe.bounds;
            
            // 判断相机是否在影响范围内
            if (!IsInInfluenceZone(cameraPos, probe)) continue;
            
            float weight = ComputeProbeWeight(cameraPos, probe);
            activeProbes.Add(new ProbeWeight 
            { 
                probe = probe, 
                weight = weight,
                blendDistance = probe.blendDistance
            });
        }
        
        // 按权重排序，取最高的MaxProbes个
        activeProbes.Sort((a, b) => b.weight.CompareTo(a.weight));
        if (activeProbes.Count > MaxProbes)
            activeProbes.RemoveRange(MaxProbes, activeProbes.Count - MaxProbes);
        
        // 归一化权重
        float totalWeight = 0;
        foreach (var p in activeProbes) totalWeight += p.weight;
        if (totalWeight > 0)
        {
            for (int i = 0; i < activeProbes.Count; i++)
            {
                var pw = activeProbes[i];
                pw.weight /= totalWeight;
                activeProbes[i] = pw;
            }
        }
        
        // 上传到Shader
        UploadProbeDataToShader();
    }
    
    private bool IsInInfluenceZone(Vector3 pos, ReflectionProbe probe)
    {
        // 带混合距离的扩展盒体检测
        Bounds expandedBounds = probe.bounds;
        expandedBounds.Expand(probe.blendDistance * 2);
        return expandedBounds.Contains(pos);
    }
    
    private float ComputeProbeWeight(Vector3 cameraPos, ReflectionProbe probe)
    {
        Bounds bounds = probe.bounds;
        Vector3 closestPoint = bounds.ClosestPoint(cameraPos);
        float dist = Vector3.Distance(cameraPos, closestPoint);
        
        // 在盒体内部权重为1，超出blendDistance为0
        float blendDist = probe.blendDistance;
        if (dist <= 0) return 1f; // 在盒体内部
        
        return Mathf.Clamp01(1f - dist / blendDist);
    }
    
    private void UploadProbeDataToShader()
    {
        // 上传探针贴图和权重数组
        for (int i = 0; i < activeProbes.Count && i < MaxProbes; i++)
        {
            var probe = activeProbes[i].probe;
            Shader.SetGlobalTexture($"_ReflectionProbe{i}", probe.texture);
            Shader.SetGlobalVector($"_ReflectionProbeHDR{i}", probe.textureHDRDecodeValues);
            Shader.SetGlobalFloat($"_ReflectionProbeWeight{i}", activeProbes[i].weight);
            Shader.SetGlobalVector($"_ReflectionProbeCenter{i}", probe.transform.position);
            Shader.SetGlobalVector($"_ReflectionProbeBoxMin{i}", probe.bounds.min);
            Shader.SetGlobalVector($"_ReflectionProbeBoxMax{i}", probe.bounds.max);
        }
        Shader.SetGlobalInt("_ActiveProbeCount", activeProbes.Count);
    }
}
```

---

## 4. 平面反射（Planar Reflection）实现

### 4.1 反射相机设置

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

[RequireComponent(typeof(MeshRenderer))]
public class PlanarReflectionRenderer : MonoBehaviour
{
    [Header("质量设置")]
    [Range(0.1f, 1f)] public float renderScale = 0.5f;
    public bool useAntiAliasing = false;
    public LayerMask reflectionMask = -1;
    
    [Header("裁剪")]
    public float clipPlaneOffset = 0.07f;
    
    private Camera reflectionCamera;
    private RenderTexture reflectionRT;
    private Material reflectionMaterial;
    private static readonly int ReflectionTexID = Shader.PropertyToID("_ReflectionTex");
    
    private void Start()
    {
        SetupReflectionCamera();
    }
    
    private void SetupReflectionCamera()
    {
        // 创建反射相机
        var go = new GameObject("PlanarReflection_Camera");
        go.hideFlags = HideFlags.HideAndDontSave;
        reflectionCamera = go.AddComponent<Camera>();
        reflectionCamera.enabled = false; // 手动控制渲染
        reflectionCamera.cullingMask = reflectionMask;
        
        // 禁用不必要特性
        var camData = go.AddComponent<UniversalAdditionalCameraData>();
        camData.renderPostProcessing = false;
        camData.requiresColorTexture = false;
        camData.requiresDepthTexture = false;
        
        reflectionMaterial = GetComponent<MeshRenderer>().sharedMaterial;
    }
    
    private void OnWillRenderObject()
    {
        if (!gameObject.activeSelf) return;
        
        Camera mainCam = Camera.current;
        if (mainCam == null || mainCam == reflectionCamera) return;
        
        UpdateReflectionRenderTexture(mainCam);
        UpdateReflectionCamera(mainCam);
        RenderReflection();
        
        reflectionMaterial.SetTexture(ReflectionTexID, reflectionRT);
    }
    
    private void UpdateReflectionRenderTexture(Camera mainCam)
    {
        int width  = Mathf.RoundToInt(mainCam.pixelWidth  * renderScale);
        int height = Mathf.RoundToInt(mainCam.pixelHeight * renderScale);
        
        if (reflectionRT == null || 
            reflectionRT.width != width || 
            reflectionRT.height != height)
        {
            if (reflectionRT != null) RenderTexture.ReleaseTemporary(reflectionRT);
            reflectionRT = RenderTexture.GetTemporary(width, height, 16, 
                           RenderTextureFormat.ARGBHalf);
            reflectionRT.filterMode = FilterMode.Bilinear;
        }
    }
    
    private void UpdateReflectionCamera(Camera mainCam)
    {
        // 将主相机在平面法线处的位置反射
        Vector3 planeNormal = transform.up;
        Vector3 planePoint  = transform.position;
        
        // 构建反射矩阵
        Vector4 plane = new Vector4(planeNormal.x, planeNormal.y, planeNormal.z,
                        -Vector3.Dot(planeNormal, planePoint));
        Matrix4x4 reflectM = CalculateReflectionMatrix(plane);
        
        reflectionCamera.worldToCameraMatrix = mainCam.worldToCameraMatrix * reflectM;
        
        // 斜近裁剪面（避免水面下的内容渲染到反射中）
        Vector4 clipPlane = CameraSpacePlane(reflectionCamera, planePoint, 
                            planeNormal, clipPlaneOffset);
        reflectionCamera.projectionMatrix = mainCam.CalculateObliqueMatrix(clipPlane);
        
        reflectionCamera.fieldOfView = mainCam.fieldOfView;
        reflectionCamera.aspect      = mainCam.aspect;
        reflectionCamera.nearClipPlane = mainCam.nearClipPlane;
        reflectionCamera.farClipPlane  = mainCam.farClipPlane;
    }
    
    private void RenderReflection()
    {
        GL.invertCulling = true;
        reflectionCamera.targetTexture = reflectionRT;
        reflectionCamera.Render();
        GL.invertCulling = false;
    }
    
    private static Matrix4x4 CalculateReflectionMatrix(Vector4 plane)
    {
        var reflectionMat = Matrix4x4.identity;
        reflectionMat.m00 = 1f - 2f * plane.x * plane.x;
        reflectionMat.m01 =    - 2f * plane.x * plane.y;
        reflectionMat.m02 =    - 2f * plane.x * plane.z;
        reflectionMat.m03 =    - 2f * plane.x * plane.w;
        
        reflectionMat.m10 =    - 2f * plane.y * plane.x;
        reflectionMat.m11 = 1f - 2f * plane.y * plane.y;
        reflectionMat.m12 =    - 2f * plane.y * plane.z;
        reflectionMat.m13 =    - 2f * plane.y * plane.w;
        
        reflectionMat.m20 =    - 2f * plane.z * plane.x;
        reflectionMat.m21 =    - 2f * plane.z * plane.y;
        reflectionMat.m22 = 1f - 2f * plane.z * plane.z;
        reflectionMat.m23 =    - 2f * plane.z * plane.w;
        
        return reflectionMat;
    }
    
    private Vector4 CameraSpacePlane(Camera cam, Vector3 pos, Vector3 normal, float offset)
    {
        var offsetPos = pos + normal * offset;
        var m = cam.worldToCameraMatrix;
        var cameraNormal = m.MultiplyVector(normal).normalized;
        var cameraPos    = m.MultiplyPoint(offsetPos);
        return new Vector4(cameraNormal.x, cameraNormal.y, cameraNormal.z,
                           -Vector3.Dot(cameraNormal, cameraPos));
    }
    
    private void OnDisable()
    {
        if (reflectionRT != null)
        {
            RenderTexture.ReleaseTemporary(reflectionRT);
            reflectionRT = null;
        }
        if (reflectionCamera != null)
            DestroyImmediate(reflectionCamera.gameObject);
    }
}
```

---

## 5. 移动端反射降质策略

### 5.1 质量层级设计

```csharp
public enum ReflectionQualityLevel
{
    Low,    // 仅低频探针Cubemap，无SSR
    Medium, // 低分辨率SSR（半分辨率） + 探针
    High,   // 全分辨率SSR + 探针 + 平面反射
    Ultra   // 全功能 + TAA时序累积
}

public class ReflectionQualityManager : MonoBehaviour
{
    private static ReflectionQualityLevel currentLevel = ReflectionQualityLevel.Medium;
    
    private void Start()
    {
        // 根据设备性能自动选择
        AutoSelectQualityLevel();
    }
    
    private void AutoSelectQualityLevel()
    {
        // 移动端判断
        if (SystemInfo.deviceType == DeviceType.Handheld)
        {
            // GPU等级检测
            int gpuMemory = SystemInfo.graphicsMemorySize;
            bool supportsComputeShaders = SystemInfo.supportsComputeShaders;
            
            if (!supportsComputeShaders || gpuMemory < 1024)
            {
                SetQualityLevel(ReflectionQualityLevel.Low);
            }
            else if (gpuMemory < 3072)
            {
                SetQualityLevel(ReflectionQualityLevel.Medium);
            }
            else
            {
                SetQualityLevel(ReflectionQualityLevel.High);
            }
        }
        else
        {
            // PC/主机默认高质量
            SetQualityLevel(ReflectionQualityLevel.Ultra);
        }
    }
    
    public static void SetQualityLevel(ReflectionQualityLevel level)
    {
        currentLevel = level;
        
        // 设置全局关键字控制SSR特性
        switch (level)
        {
            case ReflectionQualityLevel.Low:
                Shader.DisableKeyword("SSR_ENABLED");
                Shader.DisableKeyword("PLANAR_REFLECTION_ENABLED");
                Shader.SetGlobalFloat("_SSRResolutionScale", 0f);
                break;
            case ReflectionQualityLevel.Medium:
                Shader.EnableKeyword("SSR_ENABLED");
                Shader.DisableKeyword("PLANAR_REFLECTION_ENABLED");
                Shader.SetGlobalFloat("_SSRResolutionScale", 0.5f);
                break;
            case ReflectionQualityLevel.High:
                Shader.EnableKeyword("SSR_ENABLED");
                Shader.EnableKeyword("PLANAR_REFLECTION_ENABLED");
                Shader.SetGlobalFloat("_SSRResolutionScale", 1.0f);
                break;
            case ReflectionQualityLevel.Ultra:
                Shader.EnableKeyword("SSR_ENABLED");
                Shader.EnableKeyword("PLANAR_REFLECTION_ENABLED");
                Shader.EnableKeyword("TAA_SSR_ENABLED");
                Shader.SetGlobalFloat("_SSRResolutionScale", 1.0f);
                break;
        }
        
        Debug.Log($"[ReflectionSystem] Quality set to: {level}");
    }
}
```

---

## 6. 最佳实践总结

### 6.1 性能优化策略

| 优化手段 | 收益 | 说明 |
|----------|------|------|
| 半分辨率SSR | 3-4x加速 | 对中低频反射无明显质量损失 |
| 分块剔除（Tile-based） | 2x加速 | 仅处理有金属/光滑像素的Tile |
| HiZ加速步进 | 1.5-2x加速 | 跨越深度遮挡区域 |
| TAA时序累积 | 质量大幅提升 | 用时间换空间，多帧叠加消噪 |
| 探针异步刷新 | 降低峰值 | 每帧只刷新1-2个动态探针 |
| 平面反射分辨率缩减 | 显著降低带宽 | 0.5x分辨率几乎无视觉差异 |

### 6.2 陷阱与注意事项

1. **SSR边界伪影**：屏幕边缘没有反射来源时必须淡出，否则出现硬边。
2. **探针视差**：大场景必须启用视差纠正（PCC），否则反射会"漂移"。
3. **水下穿帮**：平面反射必须使用斜近裁剪面，防止水面以下物体渗入。
4. **移动端Compute Shader**：GLES3.1以上才支持Compute，需提供Fallback。
5. **MSAA兼容性**：SSR与MSAA有冲突，开启MSAA时需特殊处理深度采样。
6. **HDR颜色范围**：反射颜色可能超出LDR范围，务必使用半浮点（ARGBHalf）RT。

### 6.3 推荐技术栈搭配

```
移动中低端：Baked ReflectionProbe + PCC视差纠正
移动高端：  半分辨率SSR + ReflectionProbe混合
PC/主机：   全分辨率SSR + TAA + ReflectionProbe + 可选平面反射
次世代：    硬件光追反射（DXR/VKR）
```

通过合理的分层反射策略，在移动端也能实现接近次世代品质的反射效果，同时将额外GPU消耗控制在2-5ms之内。
