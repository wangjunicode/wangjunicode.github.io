---
title: 游戏GPU曲面细分与贝塞尔曲线技术完全指南：Tessellation与样条插值深度实践
published: 2026-04-13
description: 深入解析GPU曲面细分（Tessellation）管线、贝塞尔曲线/Catmull-Rom样条的数学原理与游戏工程实践，涵盖PN三角形、位移贴图、LOD自适应细分、样条路径系统，结合Unity URP完整Shader与C#代码实现。
tags: [曲面细分, Tessellation, 贝塞尔, Catmull-Rom, 样条, GPU, 渲染, 几何]
category: 渲染技术
draft: false
---

# 游戏GPU曲面细分与贝塞尔曲线技术完全指南：Tessellation与样条插值深度实践

## 前言

GPU 曲面细分（Tessellation）是现代图形管线中最强大却最易被忽视的特性之一。它允许在 GPU 上将低多边形网格动态细分为更高精度的几何体，配合位移贴图（Displacement Map）实现真正的几何细节。而贝塞尔曲线与 Catmull-Rom 样条，则是游戏中路径系统、相机轨道、程序化地形、角色动画曲线的数学基石。

本文将系统讲解 Tessellation 管线的三个着色器阶段、PN 三角形技术、自适应 LOD 细分，以及贝塞尔/样条的工程实现，最终构建一个完整的程序化地形系统。

---

## 一、GPU 曲面细分管线

### 1.1 Tessellation 三阶段架构

DirectX 11 / OpenGL 4.0 引入的曲面细分包含三个可编程阶段：

```
顶点着色器 (VS)
    ↓
Hull Shader（外壳着色器）← 控制细分因子
    ↓
固定功能细分器（Tessellator）← GPU 硬件执行
    ↓
Domain Shader（域着色器）← 计算新顶点位置
    ↓
几何着色器（可选）
    ↓
片段/像素着色器 (PS/FS)
```

**Unity 中对应的着色器阶段**：

| DX11 名称 | Unity HLSL | 功能 |
|---|---|---|
| Hull Shader | `[HULL_SHADER]` / `hull` 函数 | 输出细分因子 |
| Tessellator | 固定硬件 | 生成细分坐标 |
| Domain Shader | `[DOMAIN_SHADER]` / `domain` 函数 | 计算最终顶点位置 |

### 1.2 Unity URP Tessellation Shader 完整实现

```hlsl
// =====================================================
// 文件：TessellationDisplacement.shader
// 功能：基于视距的自适应曲面细分 + 位移贴图
// 支持：URP 14+（Unity 2022.3+）
// =====================================================

Shader "Custom/TessellationDisplacement"
{
    Properties
    {
        _BaseColor("Base Color", Color) = (1,1,1,1)
        _BaseMap("Albedo Map", 2D) = "white" {}
        _NormalMap("Normal Map", 2D) = "bump" {}
        _HeightMap("Height Map (R)", 2D) = "black" {}
        _HeightScale("Height Scale", Range(0, 0.5)) = 0.05
        _TessellationMin("Min Tessellation Factor", Range(1, 4)) = 1
        _TessellationMax("Max Tessellation Factor", Range(4, 64)) = 16
        _TessDistanceMin("Min Distance (Full Tess)", Range(1, 50)) = 5
        _TessDistanceMax("Max Distance (No Tess)", Range(5, 200)) = 50
        _EdgeLength("Edge Length Threshold", Range(5, 100)) = 20
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" "Queue"="Geometry" }

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode"="UniversalForward" }

            HLSLPROGRAM
            #pragma target 4.6  // 必须 4.6+ 才支持 Tessellation
            #pragma require tessellation tessHW

            #pragma vertex TessVert
            #pragma hull HullShader
            #pragma domain DomainShader
            #pragma fragment FragmentShader

            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS
            #pragma multi_compile_fog

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            // ==================== 属性声明 ====================
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _BaseMap_ST;
                float  _HeightScale;
                float  _TessellationMin;
                float  _TessellationMax;
                float  _TessDistanceMin;
                float  _TessDistanceMax;
                float  _EdgeLength;
            CBUFFER_END

            TEXTURE2D(_BaseMap);    SAMPLER(sampler_BaseMap);
            TEXTURE2D(_NormalMap);  SAMPLER(sampler_NormalMap);
            TEXTURE2D(_HeightMap);  SAMPLER(sampler_HeightMap);

            // ==================== 数据结构 ====================
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float4 tangentOS  : TANGENT;
                float2 uv         : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            // Hull Shader 输入（来自 VS 的控制点）
            struct TessControlPoint
            {
                float4 positionWS : INTERNALTESSPOS;
                float3 normalWS   : NORMAL;
                float4 tangentWS  : TANGENT;
                float2 uv         : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID
            };

            // Hull Shader 常量输出（Patch 级别）
            struct TessFactors
            {
                float edge[3]   : SV_TessFactor;
                float inside    : SV_InsideTessFactor;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float3 normalWS   : TEXCOORD0;
                float3 tangentWS  : TEXCOORD1;
                float3 bitangentWS: TEXCOORD2;
                float2 uv         : TEXCOORD3;
                float3 positionWS : TEXCOORD4;
                float  fogCoord   : TEXCOORD5;
            };

            // ==================== 顶点着色器 ====================
            TessControlPoint TessVert(Attributes input)
            {
                UNITY_SETUP_INSTANCE_ID(input);
                TessControlPoint output;
                UNITY_TRANSFER_INSTANCE_ID(input, output);

                VertexPositionInputs posInputs = GetVertexPositionInputs(input.positionOS.xyz);
                VertexNormalInputs normInputs = GetVertexNormalInputs(input.normalOS, input.tangentOS);

                output.positionWS = posInputs.positionWS;
                output.normalWS = normInputs.normalWS;
                output.tangentWS = float4(normInputs.tangentWS, input.tangentOS.w);
                output.uv = TRANSFORM_TEX(input.uv, _BaseMap);
                return output;
            }

            // ==================== 细分因子计算 ====================

            // 方案1：基于视距的均匀细分
            float CalcTessFactorByDistance(float3 posWS)
            {
                float3 camPos = GetCameraPositionWS();
                float dist = distance(posWS, camPos);
                float t = saturate((dist - _TessDistanceMin) / (_TessDistanceMax - _TessDistanceMin));
                return lerp(_TessellationMax, _TessellationMin, t);
            }

            // 方案2：基于屏幕空间边长的自适应细分（更均匀的屏幕空间分布）
            float CalcTessFactorByEdgeLength(float3 p0WS, float3 p1WS)
            {
                float4 p0CS = TransformWorldToHClip(p0WS);
                float4 p1CS = TransformWorldToHClip(p1WS);
                
                // 透视除法到 NDC
                float2 p0NDC = p0CS.xy / p0CS.w;
                float2 p1NDC = p1CS.xy / p1CS.w;
                
                // 转为像素坐标
                float2 p0Screen = p0NDC * _ScreenParams.xy * 0.5;
                float2 p1Screen = p1NDC * _ScreenParams.xy * 0.5;
                
                float edgeLenPixels = length(p1Screen - p0Screen);
                return clamp(edgeLenPixels / _EdgeLength, _TessellationMin, _TessellationMax);
            }

            // ==================== Hull Shader ====================
            // [maxtessfactor(64)] 告知编译器最大细分因子
            [maxtessfactor(64.0)]
            [domain("tri")]
            [partitioning("fractional_odd")]  // 平滑过渡，避免突变
            [outputtopology("triangle_cw")]
            [outputcontrolpoints(3)]
            [patchconstantfunc("PatchConstant")]
            TessControlPoint HullShader(
                InputPatch<TessControlPoint, 3> patch,
                uint id : SV_OutputControlPointID)
            {
                return patch[id];
            }

            TessFactors PatchConstant(InputPatch<TessControlPoint, 3> patch)
            {
                TessFactors factors;
                
                // 每条边的细分因子（使用边中点视距计算）
                float3 edge0Mid = (patch[1].positionWS + patch[2].positionWS) * 0.5;
                float3 edge1Mid = (patch[0].positionWS + patch[2].positionWS) * 0.5;
                float3 edge2Mid = (patch[0].positionWS + patch[1].positionWS) * 0.5;

                // 屏幕空间自适应细分
                factors.edge[0] = CalcTessFactorByEdgeLength(patch[1].positionWS, patch[2].positionWS);
                factors.edge[1] = CalcTessFactorByEdgeLength(patch[0].positionWS, patch[2].positionWS);
                factors.edge[2] = CalcTessFactorByEdgeLength(patch[0].positionWS, patch[1].positionWS);
                
                // 内部因子取边长的最大值
                factors.inside = max(max(factors.edge[0], factors.edge[1]), factors.edge[2]);
                
                return factors;
            }

            // ==================== Domain Shader ====================
            [domain("tri")]
            Varyings DomainShader(
                TessFactors factors,
                OutputPatch<TessControlPoint, 3> patch,
                float3 bary : SV_DomainLocation)  // 重心坐标
            {
                Varyings output;

                // 重心坐标插值基础属性
                float3 posWS = patch[0].positionWS * bary.x 
                             + patch[1].positionWS * bary.y 
                             + patch[2].positionWS * bary.z;
                float3 normalWS = normalize(
                    patch[0].normalWS * bary.x + 
                    patch[1].normalWS * bary.y + 
                    patch[2].normalWS * bary.z);
                float2 uv = patch[0].uv * bary.x + patch[1].uv * bary.y + patch[2].uv * bary.z;

                // 位移贴图：沿法线方向移动
                float height = SAMPLE_TEXTURE2D_LOD(_HeightMap, sampler_HeightMap, uv, 0).r;
                posWS += normalWS * (height * _HeightScale);

                // 切线空间重建
                float4 tangentWS = patch[0].tangentWS * bary.x 
                                 + patch[1].tangentWS * bary.y 
                                 + patch[2].tangentWS * bary.z;
                float3 bitangentWS = cross(normalWS, tangentWS.xyz) * tangentWS.w;

                output.positionCS = TransformWorldToHClip(posWS);
                output.positionWS = posWS;
                output.normalWS = normalWS;
                output.tangentWS = tangentWS.xyz;
                output.bitangentWS = bitangentWS;
                output.uv = uv;
                output.fogCoord = ComputeFogFactor(output.positionCS.z);
                return output;
            }

            // ==================== 片段着色器 ====================
            half4 FragmentShader(Varyings input) : SV_Target
            {
                half4 albedo = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv) * _BaseColor;
                
                half3 normalTS = UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, input.uv));
                float3x3 TBN = float3x3(input.tangentWS, input.bitangentWS, input.normalWS);
                float3 normalWS = normalize(mul(normalTS, TBN));

                // PBR 光照
                InputData lightingInput = (InputData)0;
                lightingInput.positionWS = input.positionWS;
                lightingInput.normalWS = normalWS;
                lightingInput.viewDirectionWS = GetWorldSpaceNormalizeViewDir(input.positionWS);
                lightingInput.fogCoord = input.fogCoord;
                lightingInput.bakedGI = SampleSH(normalWS);

                SurfaceData surfaceData = (SurfaceData)0;
                surfaceData.albedo = albedo.rgb;
                surfaceData.alpha = albedo.a;
                surfaceData.smoothness = 0.5;
                surfaceData.metallic = 0;
                surfaceData.normalTS = normalTS;
                surfaceData.occlusion = 1;

                half4 color = UniversalFragmentPBR(lightingInput, surfaceData);
                color.rgb = MixFog(color.rgb, input.fogCoord);
                return color;
            }

            ENDHLSL
        }
    }
}
```

---

## 二、PN 三角形技术

### 2.1 PN 三角形原理

PN（Point-Normal）三角形通过各顶点的位置和法线，将平面三角形拟合成光滑曲面，无需额外的控制网格。

```hlsl
// PN 三角形 Hull Shader 扩展
// 每条边用两端点和法线构造贝塞尔控制点

struct PNTessFactors
{
    float edge[3]  : SV_TessFactor;
    float inside   : SV_InsideTessFactor;
    
    // PN 三角形贝塞尔控制点（10个）
    float3 b300 : BEZIERPOS0;
    float3 b030 : BEZIERPOS1;
    float3 b003 : BEZIERPOS2;
    float3 b210 : BEZIERPOS3;
    float3 b120 : BEZIERPOS4;
    float3 b021 : BEZIERPOS5;
    float3 b012 : BEZIERPOS6;
    float3 b102 : BEZIERPOS7;
    float3 b201 : BEZIERPOS8;
    float3 b111 : BEZIERPOS9;
    
    // 法线二次贝塞尔控制点（6个）
    float3 n200 : BEZIERNORM0;
    float3 n020 : BEZIERNORM1;
    float3 n002 : BEZIERNORM2;
    float3 n110 : BEZIERNORM3;
    float3 n011 : BEZIERNORM4;
    float3 n101 : BEZIERNORM5;
};

// 计算 PN 控制点
PNTessFactors PNPatchConstant(InputPatch<TessControlPoint, 3> patch)
{
    PNTessFactors factors;
    
    // 角控制点（即原顶点位置）
    float3 p0 = patch[0].positionWS;
    float3 p1 = patch[1].positionWS;
    float3 p2 = patch[2].positionWS;
    float3 n0 = patch[0].normalWS;
    float3 n1 = patch[1].normalWS;
    float3 n2 = patch[2].normalWS;
    
    factors.b300 = p0; factors.b030 = p1; factors.b003 = p2;
    
    // 边中间控制点（投影到切平面）
    // b_ij0 = (2*pi + pj - dot(pj-pi, ni)*ni) / 3
    factors.b210 = (2*p0 + p1 - dot(p1-p0, n0)*n0) / 3.0;
    factors.b120 = (2*p1 + p0 - dot(p0-p1, n1)*n1) / 3.0;
    factors.b021 = (2*p1 + p2 - dot(p2-p1, n1)*n1) / 3.0;
    factors.b012 = (2*p2 + p1 - dot(p1-p2, n2)*n2) / 3.0;
    factors.b102 = (2*p2 + p0 - dot(p0-p2, n2)*n2) / 3.0;
    factors.b201 = (2*p0 + p2 - dot(p2-p0, n0)*n0) / 3.0;
    
    // 中心控制点（保持曲面连续性）
    float3 avg = (factors.b210 + factors.b120 + factors.b021 + 
                  factors.b012 + factors.b102 + factors.b201) / 6.0;
    factors.b111 = avg + (avg - (p0+p1+p2)/3.0) / 2.0;
    
    // 法线控制点（二次贝塞尔）
    factors.n200 = n0; factors.n020 = n1; factors.n002 = n2;
    float v01 = 2.0 * dot(p1-p0, n0+n1) / dot(p1-p0, p1-p0);
    float v12 = 2.0 * dot(p2-p1, n1+n2) / dot(p2-p1, p2-p1);
    float v20 = 2.0 * dot(p0-p2, n2+n0) / dot(p0-p2, p0-p2);
    factors.n110 = normalize(n0 + n1 - v01*(p1-p0));
    factors.n011 = normalize(n1 + n2 - v12*(p2-p1));
    factors.n101 = normalize(n2 + n0 - v20*(p0-p2));
    
    // 细分因子
    factors.edge[0] = CalcTessFactorByEdgeLength(p1, p2);
    factors.edge[1] = CalcTessFactorByEdgeLength(p0, p2);
    factors.edge[2] = CalcTessFactorByEdgeLength(p0, p1);
    factors.inside  = (factors.edge[0] + factors.edge[1] + factors.edge[2]) / 3.0;
    
    return factors;
}

// PN Domain Shader：用 10 控制点三次贝塞尔计算平滑位置
[domain("tri")]
Varyings PNDomainShader(
    PNTessFactors factors,
    OutputPatch<TessControlPoint, 3> patch,
    float3 bary : SV_DomainLocation)
{
    float u = bary.x, v = bary.y, w = bary.z;
    float u2=u*u, v2=v*v, w2=w*w;
    float u3=u2*u, v3=v2*v, w3=w2*w;
    
    // 三次贝塞尔位置插值
    float3 posWS = 
        factors.b300*u3 + factors.b030*v3 + factors.b003*w3 +
        factors.b210*3*u2*v + factors.b120*3*u*v2 + 
        factors.b201*3*u2*w + factors.b102*3*u*w2 +
        factors.b021*3*v2*w + factors.b012*3*v*w2 +
        factors.b111*6*u*v*w;
    
    // 二次贝塞尔法线插值
    float3 normalWS = normalize(
        factors.n200*u2 + factors.n020*v2 + factors.n002*w2 +
        factors.n110*u*v + factors.n011*v*w + factors.n101*u*w);
    
    // ... 其余同普通 Domain Shader
    Varyings output;
    output.positionCS = TransformWorldToHClip(posWS);
    output.positionWS = posWS;
    output.normalWS = normalWS;
    output.uv = patch[0].uv*u + patch[1].uv*v + patch[2].uv*w;
    output.fogCoord = ComputeFogFactor(output.positionCS.z);
    return output;
}
```

---

## 三、贝塞尔曲线与 Catmull-Rom 样条

### 3.1 贝塞尔曲线实现

```csharp
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// 完整的贝塞尔曲线库：支持二次/三次贝塞尔、复合曲线、弧长参数化
/// </summary>
public static class BezierMath
{
    // =====================================================
    // 三次贝塞尔曲线（最常用）
    // B(t) = (1-t)³P0 + 3(1-t)²tP1 + 3(1-t)t²P2 + t³P3
    // =====================================================
    
    public static Vector3 Evaluate(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
    {
        float u = 1f - t;
        float u2 = u * u; float u3 = u2 * u;
        float t2 = t * t; float t3 = t2 * t;
        return u3*p0 + 3*u2*t*p1 + 3*u*t2*p2 + t3*p3;
    }

    /// <summary>
    /// 切线向量（一阶导数）
    /// B'(t) = 3[(1-t)²(P1-P0) + 2(1-t)t(P2-P1) + t²(P3-P2)]
    /// </summary>
    public static Vector3 EvaluateTangent(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
    {
        float u = 1f - t;
        return 3f * (u*u*(p1-p0) + 2*u*t*(p2-p1) + t*t*(p3-p2));
    }

    /// <summary>
    /// 曲率（二阶导数）：用于相机避障、路径平滑评估
    /// B''(t) = 6[(1-t)(P2-2P1+P0) + t(P3-2P2+P1)]
    /// </summary>
    public static Vector3 EvaluateCurvature(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t)
    {
        return 6f * ((1-t)*(p2 - 2*p1 + p0) + t*(p3 - 2*p2 + p1));
    }

    /// <summary>
    /// 弧长参数化查找表（LUT）
    /// 将均匀 t 值转换为均匀弧长 s 值，实现匀速移动
    /// </summary>
    public static float[] BuildArcLengthLUT(
        Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, int resolution = 100)
    {
        var lut = new float[resolution + 1];
        lut[0] = 0f;
        Vector3 prev = p0;
        
        for (int i = 1; i <= resolution; i++)
        {
            float t = i / (float)resolution;
            Vector3 curr = Evaluate(p0, p1, p2, p3, t);
            lut[i] = lut[i-1] + Vector3.Distance(prev, curr);
            prev = curr;
        }
        
        // 归一化到 [0,1]
        float totalLength = lut[resolution];
        if (totalLength > 0f)
            for (int i = 0; i <= resolution; i++)
                lut[i] /= totalLength;
        
        return lut;
    }

    /// <summary>
    /// 通过弧长 LUT 将均匀 s [0,1] 转换为 t 参数
    /// </summary>
    public static float ArcLengthToT(float[] lut, float s)
    {
        s = Mathf.Clamp01(s);
        int resolution = lut.Length - 1;
        
        // 二分查找
        int lo = 0, hi = resolution;
        while (lo < hi - 1)
        {
            int mid = (lo + hi) / 2;
            if (lut[mid] < s) lo = mid;
            else hi = mid;
        }
        
        // 线性插值
        float segS = lut[hi] - lut[lo];
        if (segS < 1e-6f) return lo / (float)resolution;
        float blend = (s - lut[lo]) / segS;
        return (lo + blend) / resolution;
    }
}

/// <summary>
/// Catmull-Rom 样条：过所有控制点，C1 连续，游戏中常用于相机路径
/// </summary>
public static class CatmullRomSpline
{
    /// <summary>
    /// 标准 Catmull-Rom 插值（α=0.5 为向心参数化，最平滑）
    /// </summary>
    public static Vector3 Evaluate(Vector3 p0, Vector3 p1, Vector3 p2, Vector3 p3, float t, float alpha = 0.5f)
    {
        // 向心 Catmull-Rom（避免过弯和自交）
        float t01 = Mathf.Pow(Vector3.Distance(p0, p1), alpha);
        float t12 = Mathf.Pow(Vector3.Distance(p1, p2), alpha);
        float t23 = Mathf.Pow(Vector3.Distance(p2, p3), alpha);

        Vector3 m1 = (p2 - p1 + t12 * ((p1 - p0) / t01 - (p2 - p0) / (t01 + t12)));
        Vector3 m2 = (p2 - p1 + t12 * ((p3 - p2) / t23 - (p3 - p1) / (t12 + t23)));

        float t2 = t * t, t3 = t2 * t;
        Vector3 a = 2*p1 - 2*p2 + m1 + m2;
        Vector3 b = -3*p1 + 3*p2 - 2*m1 - m2;
        return a*t3 + b*t2 + m1*t + p1;
    }

    /// <summary>
    /// 在控制点序列中均匀采样指定数量的点（用于路径预览/导航点生成）
    /// </summary>
    public static Vector3[] SamplePath(Vector3[] controlPoints, int sampleCount, bool loop = false)
    {
        if (controlPoints.Length < 2) return controlPoints;
        
        var result = new Vector3[sampleCount];
        int segCount = loop ? controlPoints.Length : controlPoints.Length - 1;
        
        for (int i = 0; i < sampleCount; i++)
        {
            float t = i / (float)(sampleCount - 1) * segCount;
            int seg = Mathf.FloorToInt(t);
            float localT = t - seg;
            
            int p0i = Mathf.Clamp(seg - 1, 0, controlPoints.Length - 1);
            int p1i = Mathf.Clamp(seg,     0, controlPoints.Length - 1);
            int p2i = Mathf.Clamp(seg + 1, 0, controlPoints.Length - 1);
            int p3i = Mathf.Clamp(seg + 2, 0, controlPoints.Length - 1);
            
            if (loop)
            {
                p0i = ((seg - 1) % controlPoints.Length + controlPoints.Length) % controlPoints.Length;
                p1i = seg % controlPoints.Length;
                p2i = (seg + 1) % controlPoints.Length;
                p3i = (seg + 2) % controlPoints.Length;
            }
            
            result[i] = Evaluate(
                controlPoints[p0i], controlPoints[p1i], 
                controlPoints[p2i], controlPoints[p3i], localT);
        }
        return result;
    }
}
```

### 3.2 样条路径组件

```csharp
using UnityEngine;
using System.Collections.Generic;

/// <summary>
/// 游戏样条路径系统：支持沿路径移动、朝向对齐、等距采样
/// 应用场景：相机轨道、NPC 巡逻路径、投射物轨迹、过场动画
/// </summary>
[ExecuteInEditMode]
public class SplinePath : MonoBehaviour
{
    [Header("控制点")]
    public List<Transform> controlPoints = new List<Transform>();
    
    [Header("样条设置")]
    public bool loop = false;
    public float alpha = 0.5f;          // 向心参数化 alpha（0=标准, 0.5=向心, 1=弦长）
    public int previewResolution = 50;  // 编辑器预览分辨率
    
    [Header("弧长参数化")]
    public int arcLengthResolution = 200;
    private float[] _segmentLengths;
    private float _totalLength;

    /// <summary>
    /// 按弧长 [0,1] 获取路径上的位置（匀速移动）
    /// </summary>
    public Vector3 GetPositionAtDistance(float normalizedDist)
    {
        EnsureArcLengthCache();
        
        float targetDist = normalizedDist * _totalLength;
        float accumulated = 0f;
        
        int segCount = loop ? controlPoints.Count : controlPoints.Count - 1;
        for (int seg = 0; seg < segCount; seg++)
        {
            float segLen = _segmentLengths[seg];
            if (accumulated + segLen >= targetDist || seg == segCount - 1)
            {
                float localT = (targetDist - accumulated) / Mathf.Max(segLen, 1e-6f);
                return SampleSegment(seg, Mathf.Clamp01(localT));
            }
            accumulated += segLen;
        }
        return controlPoints[controlPoints.Count - 1].position;
    }

    /// <summary>
    /// 获取切线朝向（用于对齐物体方向）
    /// </summary>
    public Quaternion GetOrientationAtDistance(float normalizedDist, Vector3 up)
    {
        float delta = 0.001f;
        Vector3 p0 = GetPositionAtDistance(Mathf.Max(0, normalizedDist - delta));
        Vector3 p1 = GetPositionAtDistance(Mathf.Min(1, normalizedDist + delta));
        
        Vector3 tangent = (p1 - p0).normalized;
        if (tangent.sqrMagnitude < 1e-6f) return Quaternion.identity;
        return Quaternion.LookRotation(tangent, up);
    }

    private Vector3 SampleSegment(int seg, float t)
    {
        int n = controlPoints.Count;
        int p0i = loop ? ((seg - 1 + n) % n) : Mathf.Max(0, seg - 1);
        int p1i = seg % n;
        int p2i = (seg + 1) % n;
        int p3i = loop ? ((seg + 2) % n) : Mathf.Min(n - 1, seg + 2);
        
        return CatmullRomSpline.Evaluate(
            controlPoints[p0i].position,
            controlPoints[p1i].position,
            controlPoints[p2i].position,
            controlPoints[p3i].position, t, alpha);
    }

    private void EnsureArcLengthCache()
    {
        int segCount = loop ? controlPoints.Count : controlPoints.Count - 1;
        if (_segmentLengths != null && _segmentLengths.Length == segCount) return;
        
        _segmentLengths = new float[segCount];
        _totalLength = 0f;
        
        for (int seg = 0; seg < segCount; seg++)
        {
            float len = 0f;
            Vector3 prev = SampleSegment(seg, 0f);
            for (int i = 1; i <= arcLengthResolution; i++)
            {
                float t = i / (float)arcLengthResolution;
                Vector3 curr = SampleSegment(seg, t);
                len += Vector3.Distance(prev, curr);
                prev = curr;
            }
            _segmentLengths[seg] = len;
            _totalLength += len;
        }
    }

    void OnDrawGizmos()
    {
        if (controlPoints == null || controlPoints.Count < 2) return;
        
        Gizmos.color = Color.green;
        int segCount = loop ? controlPoints.Count : controlPoints.Count - 1;
        int steps = segCount * previewResolution;
        
        Vector3 prev = GetPositionAtDistance(0);
        for (int i = 1; i <= steps; i++)
        {
            float t = (float)i / steps;
            Vector3 curr = GetPositionAtDistance(t);
            Gizmos.DrawLine(prev, curr);
            prev = curr;
        }
        
        // 绘制控制点
        Gizmos.color = Color.cyan;
        foreach (var cp in controlPoints)
            if (cp != null) Gizmos.DrawWireSphere(cp.position, 0.2f);
    }
}
```

---

## 四、程序化地形应用

### 4.1 基于 Tessellation 的地形系统

```csharp
using UnityEngine;

/// <summary>
/// 程序化地形管理器：结合 Tessellation Shader + 高度图 + 草地生成
/// </summary>
public class TessellationTerrainManager : MonoBehaviour
{
    [Header("地形配置")]
    public MeshRenderer terrainRenderer;
    public Texture2D heightMap;
    public float terrainSize = 100f;
    public float maxHeight = 20f;
    
    [Header("Tessellation 参数")]
    [Range(1, 64)] public float maxTessFactor = 32f;
    [Range(1, 64)] public float minTessFactor = 1f;
    public float tessDistanceMin = 5f;
    public float tessDistanceMax = 80f;
    
    [Header("LOD")]
    public Camera mainCamera;
    public float cullingDistance = 200f;

    private Material _terrainMat;

    void Start()
    {
        _terrainMat = terrainRenderer.material;
        ApplyTerrainSettings();
    }

    void Update()
    {
        // 根据相机高度动态调整最大细分（高空视角不需要高细分）
        float camHeight = mainCamera.transform.position.y;
        float heightFactor = Mathf.Clamp01(1f - camHeight / (maxHeight * 3f));
        float dynamicMaxTess = Mathf.Lerp(minTessFactor, maxTessFactor, heightFactor);
        
        _terrainMat.SetFloat("_TessellationMax", dynamicMaxTess);
        _terrainMat.SetFloat("_TessDistanceMin", tessDistanceMin);
        _terrainMat.SetFloat("_TessDistanceMax", tessDistanceMax);
    }

    private void ApplyTerrainSettings()
    {
        _terrainMat.SetTexture("_HeightMap", heightMap);
        _terrainMat.SetFloat("_HeightScale", maxHeight);
        _terrainMat.SetFloat("_TessellationMin", minTessFactor);
        _terrainMat.SetFloat("_TessellationMax", maxTessFactor);
    }

    /// <summary>
    /// 在 CPU 端采样高度图，用于碰撞检测和 AI 导航
    /// </summary>
    public float SampleHeight(Vector3 worldPos)
    {
        if (heightMap == null) return 0f;
        
        Vector2 uv = new Vector2(
            (worldPos.x / terrainSize) + 0.5f,
            (worldPos.z / terrainSize) + 0.5f);
        
        int x = Mathf.Clamp(Mathf.RoundToInt(uv.x * (heightMap.width - 1)), 0, heightMap.width - 1);
        int y = Mathf.Clamp(Mathf.RoundToInt(uv.y * (heightMap.height - 1)), 0, heightMap.height - 1);
        
        return heightMap.GetPixel(x, y).r * maxHeight;
    }
}
```

---

## 五、最佳实践总结

### 5.1 Tessellation 使用原则

1. **最小细分因子**：移动端慎用 Tessellation，iOS/Android 对 GPU Tessellation 支持有限，建议桌面端才开启
2. **裁剪优化**：在 Hull Shader 中添加视锥体裁剪，细分因子为 0 时 GPU 跳过整个三角形
3. **细分因子上限**：实际工程中建议不超过 16-32，过高的细分因子收益递减且 GPU 占用剧增
4. **位移与法线一致**：位移方向必须用低频法线（顶点法线），否则出现接缝
5. **阴影 Pass 单独控制**：阴影 Pass 的细分因子可以更低（降低 2-4 倍），不影响视觉效果

### 5.2 样条选型指南

| 场景 | 推荐方案 | 原因 |
|---|---|---|
| 相机过场动画 | Catmull-Rom (α=0.5) | 过控制点，向心参数化避免环路 |
| 敌人巡逻路径 | Catmull-Rom (α=0.5) | 弧长参数化实现匀速移动 |
| UI 动画缓动 | 三次贝塞尔 | 直觉化控制手柄，与 CSS ease 兼容 |
| 程序化道路 | B-Spline | C2 连续，适合大段平滑曲线 |
| 粒子轨迹 | 二次贝塞尔 | 计算简单，实时大量评估 |

### 5.3 常见问题

| 问题 | 原因 | 解决方案 |
|---|---|---|
| 曲面接缝/裂缝 | 相邻三角形细分因子不同 | 共享边使用相同细分因子计算 |
| Tessellation 无效果 | `#pragma target` 低于 4.6 | 确保使用 SM4.6+ |
| Catmull-Rom 出现环路 | 标准参数化（α=0）遇极近控制点 | 改用向心参数化（α=0.5） |
| 弧长移动速度不均 | 未使用弧长 LUT | 构建 ArcLength LUT 并二分查找 |
| 位移贴图接缝 | UV 边界不连续 | 在边界处使用 LOD 0 采样 |

---

## 结语

GPU Tessellation 赋予了渲染管线在不增加原始网格复杂度的前提下，动态提升几何精度的能力。结合 PN 三角形的法线驱动曲面拟合，以及自适应 LOD 细分，可以实现兼顾性能与质量的地形、角色皮肤等高精度渲染。Catmull-Rom 样条凭借"过控制点"和 C1 连续性，是游戏路径系统的首选数学工具，其向心参数化变体有效解决了传统样条的自交问题。掌握这两套技术，将极大拓展游戏视觉表现的深度。
