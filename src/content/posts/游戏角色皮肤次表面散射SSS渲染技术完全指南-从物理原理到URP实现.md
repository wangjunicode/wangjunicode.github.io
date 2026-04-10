---
title: 游戏角色皮肤次表面散射（SSS）渲染技术完全指南：从物理原理到URP实现
published: 2026-04-10
description: 深度解析游戏中皮肤次表面散射的物理原理与实时渲染实现，涵盖Pre-Integrated SSS、Screen-Space SSS（SSSSS）、Burley归一化扩散模型、URP自定义ShaderGraph与手写HLSL实现，并提供移动端降级方案与性能优化策略。
tags: [渲染技术, Shader, 次表面散射, URP, 角色渲染, PBR, HLSL]
category: 渲染技术
draft: false
---

# 游戏角色皮肤次表面散射（SSS）渲染技术完全指南

## 一、次表面散射的物理基础

### 1.1 为什么皮肤需要SSS

在标准PBR模型中，光线打到表面后仅在接触点发生反射（漫反射+镜面反射）。但皮肤是一种**半透明多层介质**，光线进入表皮后会在真皮层发生多次散射，从不同位置射出，这就是**次表面散射（Subsurface Scattering，SSS）**。

没有SSS的皮肤渲染看起来像是塑料或橡胶，而真实的皮肤在强光下会呈现出温暖的半透光感（如耳朵、手指被灯光照射时的血色透光感）。

```
标准Lambertian漫反射：
光线 → 表面 → 单点反射出射

次表面散射：
光线 → 进入皮肤表面 → 在真皮层散射 → 从周围多点出射
输出点 ≠ 输入点（光的传播距离可达数毫米）
```

### 1.2 皮肤的分层结构

```
空气
─────────────────────────── 表层（角质层 ~20μm，高反射率）
─────────────────────────── 表皮层（50~100μm，黑色素决定肤色）
─────────────────────────── 真皮层（1~4mm，血红蛋白散射，红色调）
─────────────────────────── 皮下脂肪（散射最强，亮黄色调）
肌肉/骨骼
```

不同层次具有不同的**散射系数（σs）**和**吸收系数（σa）**，这决定了光在各层的颜色贡献。

### 1.3 BSSRDF理论

次表面散射由**双向次表面散射反射分布函数（BSSRDF）**描述：

```
L(xo, ωo) = ∫∫ S(xi, ωi, xo, ωo) · L(xi, ωi) · (n·ωi) dxi dωi
```

其中 `S` 是BSSRDF，表示从点 `xi` 入射到点 `xo` 出射的光传输量。

在实时渲染中，完整求解BSSRDF计算量过大，因此需要各种近似方案。

---

## 二、实时SSS近似方案概览

| 方案 | 质量 | 性能开销 | 适用场景 |
|------|------|----------|----------|
| Pre-Integrated SSS | 中高 | 低 | 移动端/主机 |
| Screen-Space SSS (SSSS) | 高 | 中高 | PC/主机 |
| Burley Normalized Diffusion | 高 | 中 | PC端 |
| Texture-Space Diffusion | 最高 | 高 | 离线/次世代主机 |
| 简化双层模型 | 低中 | 极低 | 移动端降级 |

---

## 三、Pre-Integrated SSS（预积分皮肤）

### 3.1 核心原理

Pre-Integrated SSS 由 **Penner 2011** 提出，核心思路是将光照积分预烘焙到一张2D查找表（LUT）中：

- **X轴（U）**：`NdotL`（法线与光线夹角）
- **Y轴（V）**：`1/r`（表面曲率，r是曲率半径）

查表时只需一次纹理采样，即可获得考虑了散射宽度的漫反射颜色。

### 3.2 生成预积分查找表

```csharp
// Editor工具：生成Pre-Integrated SSS LUT
using UnityEngine;
using UnityEditor;

public class SSSLUTGenerator : EditorWindow
{
    [MenuItem("Tools/Rendering/Generate SSS LUT")]
    public static void ShowWindow()
    {
        GetWindow<SSSLUTGenerator>("SSS LUT Generator");
    }

    private int lutSize = 256;
    private float scatterWidth = 0.1f;

    void OnGUI()
    {
        lutSize = EditorGUILayout.IntField("LUT Size", lutSize);
        scatterWidth = EditorGUILayout.Slider("Scatter Width", scatterWidth, 0.01f, 0.5f);

        if (GUILayout.Button("Generate LUT"))
        {
            GenerateSSSLUT();
        }
    }

    void GenerateSSSLUT()
    {
        Texture2D lut = new Texture2D(lutSize, lutSize, TextureFormat.RGBA32, false, true);
        Color[] pixels = new Color[lutSize * lutSize];

        for (int y = 0; y < lutSize; y++)
        {
            float curvature = y / (float)(lutSize - 1); // 0~1 对应曲率

            for (int x = 0; x < lutSize; x++)
            {
                float NdotL = x / (float)(lutSize - 1) * 2f - 1f; // -1~1

                // 数值积分：在球面上对散射后的漫反射积分
                Color diffuse = IntegrateDiffuseScattering(NdotL, curvature);
                pixels[y * lutSize + x] = diffuse;
            }
        }

        lut.SetPixels(pixels);
        lut.Apply();

        // 保存LUT
        byte[] pngData = lut.EncodeToPNG();
        string path = "Assets/Textures/SSS_LUT.png";
        System.IO.File.WriteAllBytes(path, pngData);
        AssetDatabase.ImportAsset(path);

        TextureImporter importer = AssetImporter.GetAtPath(path) as TextureImporter;
        if (importer != null)
        {
            importer.sRGBTexture = false;
            importer.SaveAndReimport();
        }

        Debug.Log($"SSS LUT 已生成: {path}");
    }

    Color IntegrateDiffuseScattering(float NdotL, float curvature)
    {
        // 皮肤散射颜色权重（RGB通道分别对应不同散射深度）
        // R: 深散射（血红蛋白，红色调）
        // G: 中等散射（表皮）
        // B: 浅散射（几乎无散射）
        float[] scatterWeights = { 0.233f, 0.455f, 0.649f, 0.344f, 0.163f, 0.21f };
        Color[] scatterColors = {
            new Color(0.233f, 0.1f, 0.1f),   // 深红色
            new Color(0.1f, 0.366f, 0.344f),   // 绿色调
            new Color(0.118f, 0.198f, 0.0f),   // 黄绿
            new Color(0.113f, 0.007f, 0.007f), // 深红
            new Color(0.358f, 0.004f, 0.0f),   // 暗红
            new Color(0.078f, 0.0f, 0.0f),     // 极深红
        };

        Color result = Color.black;
        float totalWeight = 0f;

        // 在法线方向偏移角度范围内积分
        int samples = 128;
        for (int i = 0; i < samples; i++)
        {
            float theta = (i / (float)(samples - 1)) * Mathf.PI * 2f;
            float sampleNdotL = Mathf.Clamp01(
                NdotL * Mathf.Cos(theta * curvature * scatterWidth)
            );

            // Gaussian散射核
            float gaussianWeight = GaussianScatter(theta, curvature);

            for (int j = 0; j < scatterColors.Length; j++)
            {
                result += scatterColors[j] * gaussianWeight * sampleNdotL;
            }
            totalWeight += gaussianWeight;
        }

        if (totalWeight > 0)
            result /= totalWeight;

        result.a = 1f;
        return result;
    }

    float GaussianScatter(float x, float v)
    {
        return (1f / Mathf.Sqrt(2f * Mathf.PI * v)) * Mathf.Exp(-(x * x) / (2f * v));
    }
}
```

### 3.3 Shader中使用Pre-Integrated SSS

```hlsl
// SkinSSS_PreIntegrated.hlsl
#ifndef SKIN_SSS_PREINTEGRATED_INCLUDED
#define SKIN_SSS_PREINTEGRATED_INCLUDED

TEXTURE2D(_SSSLut);
SAMPLER(sampler_SSSLut);

TEXTURE2D(_SSSMask);       // R通道：SSS强度遮罩
SAMPLER(sampler_SSSMask);

float _SSSCurvatureScale;  // 曲率缩放系数（通常0.1~0.3）
float _SSSColorBleed;      // 色彩渗透强度

// 从几何信息估算曲率
float EstimateCurvature(float3 normal, float3 worldPos)
{
    // 通过法线贴图的ddx/ddy估算局部曲率
    float3 dNdx = ddx(normal);
    float3 dNdy = ddy(normal);
    float3 dPdx = ddx(worldPos);
    float3 dPdy = ddy(worldPos);

    float curvature = (cross(dNdx, dPdx).y + cross(dNdy, dPdy).y) * 40.0;
    return saturate(abs(curvature) * _SSSCurvatureScale);
}

// Pre-Integrated SSS主函数
float3 PreIntegratedSSS(
    float3 albedo,
    float3 normalWS,
    float3 lightDirWS,
    float2 uv,
    float3 worldPos)
{
    float NdotL = dot(normalWS, lightDirWS);

    // 采样SSS遮罩（控制哪些区域有SSS）
    float sssMask = SAMPLE_TEXTURE2D(_SSSMask, sampler_SSSMask, uv).r;

    // 估算曲率
    float curvature = EstimateCurvature(normalWS, worldPos);

    // 查找LUT
    // U = NdotL 映射到 [0,1]：(NdotL * 0.5 + 0.5)
    // V = curvature
    float2 lutUV = float2(NdotL * 0.5 + 0.5, curvature);
    float3 sssColor = SAMPLE_TEXTURE2D(_SSSLut, sampler_SSSLut, lutUV).rgb;

    // 标准漫反射
    float3 standardDiffuse = albedo * max(0, NdotL);

    // 混合SSS与标准漫反射
    float3 finalDiffuse = lerp(standardDiffuse, albedo * sssColor, sssMask);

    return finalDiffuse;
}

#endif
```

---

## 四、Screen-Space SSS（屏幕空间次表面散射）

### 4.1 算法原理

**SSSS** 在屏幕空间对已渲染的diffuse pass做多次高斯模糊，模拟光在皮肤表面扩散。关键是使用**分离可变高斯核**，分别对RGB通道使用不同宽度的模糊。

```
皮肤散射核（6高斯加权和）：
σR = [0.0064, 0.0484, 0.187, 0.567, 1.99, 7.41]  宽度从窄到宽
权重W = [0.233, 0.100, 0.118, 0.113, 0.358, 0.078]  × 红色通道
绿通道使用更小的σ，蓝通道几乎不散射
```

### 4.2 URP自定义RenderPass实现

```csharp
// ScreenSpaceSSSPass.cs
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

public class ScreenSpaceSSSPass : ScriptableRenderPass
{
    private Material sssMaterial;
    private RTHandle sssBuffer;
    private RTHandle tempBuffer;

    private static readonly int s_SSSStrength = Shader.PropertyToID("_SSSStrength");
    private static readonly int s_SSSWidth = Shader.PropertyToID("_SSSWidth");
    private static readonly int s_SSSStencilMask = Shader.PropertyToID("_SSSStencilMask");

    // 皮肤高斯核参数（基于Jimenez et al. 2015）
    private static readonly Vector4[] s_SSSKernel = new Vector4[]
    {
        new Vector4(0.530605f, 0.613514f, 0.739601f, 0f),
        new Vector4(0.000229f, 0.000059f, 0.000015f, -3f),
        new Vector4(0.005310f, 0.001368f, 0.000349f, -2.5f),
        new Vector4(0.038356f, 0.009869f, 0.002518f, -2f),
        new Vector4(0.111515f, 0.028697f, 0.007320f, -1.5f),
        new Vector4(0.184988f, 0.047614f, 0.012151f, -1f),
        new Vector4(0.222504f, 0.057268f, 0.014602f, -0.5f),
        new Vector4(0.222504f, 0.057268f, 0.014602f,  0.5f),
        new Vector4(0.184988f, 0.047614f, 0.012151f,  1f),
        new Vector4(0.111515f, 0.028697f, 0.007320f,  1.5f),
        new Vector4(0.038356f, 0.009869f, 0.002518f,  2f),
        new Vector4(0.005310f, 0.001368f, 0.000349f,  2.5f),
        new Vector4(0.000229f, 0.000059f, 0.000015f,  3f),
    };

    public ScreenSpaceSSSPass(Material material)
    {
        sssMaterial = material;
        renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        RenderTextureDescriptor desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        RenderingUtils.ReAllocateIfNeeded(ref sssBuffer, desc, name: "_SSSBuffer");
        RenderingUtils.ReAllocateIfNeeded(ref tempBuffer, desc, name: "_SSSTempBuffer");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get("ScreenSpaceSSS");

        // 获取当前相机颜色缓冲
        RTHandle cameraColorTarget = renderingData.cameraData.renderer.cameraColorTargetHandle;

        // 传递核参数
        sssMaterial.SetVectorArray("_SSSKernel", System.Array.ConvertAll(s_SSSKernel, v => (Vector4)v));

        // 水平方向模糊 Pass 0
        sssMaterial.SetVector("_SSSBlurDir", new Vector2(1f, 0f));
        Blit(cmd, cameraColorTarget, tempBuffer, sssMaterial, 0);

        // 垂直方向模糊 Pass 1
        sssMaterial.SetVector("_SSSBlurDir", new Vector2(0f, 1f));
        Blit(cmd, tempBuffer, sssBuffer, sssMaterial, 1);

        // 合成回主缓冲（仅对Stencil标记的皮肤区域）
        Blit(cmd, sssBuffer, cameraColorTarget, sssMaterial, 2);

        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 清理在每帧Setup阶段分配的临时资源
    }
}
```

```hlsl
// ScreenSpaceSSS.shader - 核心模糊Pass
Shader "Hidden/ScreenSpaceSSS"
{
    Properties
    {
        _MainTex ("Source", 2D) = "white" {}
        _SSSWidth ("SSS Width", Float) = 0.012
        _SSSStrength ("SSS Strength", Float) = 1.0
    }

    HLSLINCLUDE
    #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
    #include "Packages/com.unity.render-pipelines.core/Runtime/Utilities/Blit.hlsl"

    TEXTURE2D(_MainTex);
    SAMPLER(sampler_MainTex);
    TEXTURE2D(_CameraDepthTexture);
    SAMPLER(sampler_CameraDepthTexture);

    float4 _MainTex_TexelSize;
    float2 _SSSBlurDir;
    float _SSSWidth;
    float _SSSStrength;

    // 皮肤散射核（分离加权）
    static const int KERNEL_SIZE = 13;
    float4 _SSSKernel[KERNEL_SIZE]; // xyz = 颜色权重, w = 偏移

    float4 BlurSSS(Varyings input) : SV_Target
    {
        float2 uv = input.texcoord;

        // 从深度缓冲获取线性深度（用于缩放散射宽度）
        float depth = SAMPLE_TEXTURE2D(_CameraDepthTexture, sampler_CameraDepthTexture, uv).r;
        float linearDepth = LinearEyeDepth(depth, _ZBufferParams);

        // 根据深度缩放SSS宽度（远处物体散射应该更小以保持一致的世界空间宽度）
        float scatterWidth = _SSSWidth / linearDepth;
        float2 blurStep = _SSSBlurDir * _MainTex_TexelSize.xy * scatterWidth * 300.0;

        float4 color = 0;
        float3 totalWeight = 0;

        for (int i = 0; i < KERNEL_SIZE; i++)
        {
            float2 sampleUV = uv + _SSSKernel[i].w * blurStep;
            sampleUV = clamp(sampleUV, 0, 1);

            float4 sampleColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, sampleUV);

            // 分通道权重（R通道散射最广，B几乎不散射）
            float3 weights = _SSSKernel[i].xyz;

            color.r += sampleColor.r * weights.r;
            color.g += sampleColor.g * weights.g;
            color.b += sampleColor.b * weights.b;
            totalWeight += weights;
        }

        color.rgb /= max(totalWeight, 0.0001);
        color.a = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv).a;

        return lerp(SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv), color, _SSSStrength);
    }
    ENDHLSL

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }
        Cull Off ZWrite Off ZTest Always

        Pass // Pass 0: 水平模糊
        {
            Stencil { Ref 10  Comp Equal } // 只处理皮肤Stencil标记区域
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment BlurSSS
            ENDHLSL
        }

        Pass // Pass 1: 垂直模糊
        {
            Stencil { Ref 10 Comp Equal }
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment BlurSSS
            ENDHLSL
        }
    }
}
```

---

## 五、Burley归一化扩散模型（Unity HDRP方案）

### 5.1 理论背景

Burley (2015) 提出了一种与蒙特卡洛路径追踪结果高度吻合的归一化扩散模型：

```
R(r) = s/8π × [e^(-sr) + e^(-sr/3)] / r
```

其中 `r` 是散射距离，`s` 是基于平均自由程的散射系数，该模型具有能量守恒性质。

### 5.2 实现Burley SSS参数化

```csharp
// BurleySSS.cs - 参数管理器
using UnityEngine;

[CreateAssetMenu(fileName = "SkinSSSProfile", menuName = "Rendering/Skin SSS Profile")]
public class SkinSSSProfile : ScriptableObject
{
    [Header("散射颜色（定义各通道扩散宽度）")]
    public Color scatterColor = new Color(0.7f, 0.35f, 0.2f);

    [Header("散射半径（米）")]
    [Range(0.001f, 0.05f)]
    public float scatterRadius = 0.012f; // 皮肤约1.2cm

    [Header("表面反照率")]
    public Color surfaceAlbedo = new Color(0.7f, 0.55f, 0.4f);

    [HideInInspector]
    public Vector3 shapeParam;  // s = 1/d（扩散形状参数）
    [HideInInspector]
    public Vector3 transParam;  // 透射参数

    // 计算Burley散射参数
    void OnValidate()
    {
        ComputeParams();
    }

    public void ComputeParams()
    {
        // 从艺术参数推导物理参数
        Vector3 albedo = new Vector3(surfaceAlbedo.r, surfaceAlbedo.g, surfaceAlbedo.b);
        Vector3 radius = Vector3.one * scatterRadius;
        radius.x *= scatterColor.r;
        radius.y *= scatterColor.g;
        radius.z *= scatterColor.b;

        // Burley s参数：s = 1.85 - A + 7|A - 0.8|^3，A是反照率
        shapeParam.x = ComputeShapeParam(albedo.x) / radius.x;
        shapeParam.y = ComputeShapeParam(albedo.y) / radius.y;
        shapeParam.z = ComputeShapeParam(albedo.z) / radius.z;

        transParam = new Vector3(
            Mathf.Exp(-shapeParam.x * radius.x * 3.5f),
            Mathf.Exp(-shapeParam.y * radius.y * 3.5f),
            Mathf.Exp(-shapeParam.z * radius.z * 3.5f)
        );
    }

    float ComputeShapeParam(float A)
    {
        // Burley归一化扩散形状参数近似
        return 1.85f - A + 7f * Mathf.Pow(Mathf.Abs(A - 0.8f), 3f);
    }
}
```

---

## 六、完整的皮肤PBR + SSS Shader

```hlsl
// SkinPBR_SSS.hlsl - 完整皮肤着色器
Shader "Custom/SkinPBR_SSS"
{
    Properties
    {
        // 基础PBR
        _BaseMap ("Albedo", 2D) = "white" {}
        _NormalMap ("Normal Map", 2D) = "bump" {}
        _NormalScale ("Normal Scale", Range(0,2)) = 1.0
        _MetallicMap ("Metallic/Roughness", 2D) = "white" {}
        _Roughness ("Roughness", Range(0,1)) = 0.4
        _Metallic ("Metallic", Range(0,1)) = 0.0

        // SSS参数
        _SSSMap ("SSS Mask + Curvature", 2D) = "white" {}
        _SSSLut ("Pre-Integrated SSS LUT", 2D) = "white" {}
        _SSSColor ("SSS Scatter Color", Color) = (1, 0.4, 0.25, 1)
        _SSSStrength ("SSS Strength", Range(0, 2)) = 1.0
        _SSSCurvatureScale ("Curvature Scale", Range(0.01, 1)) = 0.1

        // 透射（背光透射效果）
        _TransmissionColor ("Transmission Color", Color) = (0.8, 0.2, 0.1, 1)
        _TransmissionPower ("Transmission Power", Range(1, 16)) = 4
        _TransmissionScale ("Transmission Scale", Range(0, 2)) = 1.0
        _TransmissionDistortion ("Transmission Distortion", Range(0, 1)) = 0.1

        // 镜面
        _SpecularMap ("Specular Map", 2D) = "white" {}
        _SpecularIntensity ("Specular Intensity", Range(0, 2)) = 1.0
    }

    SubShader
    {
        Tags
        {
            "RenderType" = "Opaque"
            "RenderPipeline" = "UniversalPipeline"
            "Queue" = "Geometry"
        }

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            // 写入Stencil供SSSS Pass识别
            Stencil
            {
                Ref 10
                Comp Always
                Pass Replace
            }

            HLSLPROGRAM
            #pragma vertex SkinVert
            #pragma fragment SkinFrag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS
            #pragma multi_compile _ _ADDITIONAL_LIGHTS

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            TEXTURE2D(_BaseMap);        SAMPLER(sampler_BaseMap);
            TEXTURE2D(_NormalMap);      SAMPLER(sampler_NormalMap);
            TEXTURE2D(_MetallicMap);    SAMPLER(sampler_MetallicMap);
            TEXTURE2D(_SSSMap);         SAMPLER(sampler_SSSMap);
            TEXTURE2D(_SSSLut);         SAMPLER(sampler_SSSLut);
            TEXTURE2D(_SpecularMap);    SAMPLER(sampler_SpecularMap);

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                float _Roughness, _Metallic, _NormalScale;
                float4 _SSSColor;
                float _SSSStrength, _SSSCurvatureScale;
                float4 _TransmissionColor;
                float _TransmissionPower, _TransmissionScale, _TransmissionDistortion;
                float _SpecularIntensity;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS : NORMAL;
                float4 tangentOS : TANGENT;
                float2 uv : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 positionWS : TEXCOORD1;
                float3 normalWS : TEXCOORD2;
                float3 tangentWS : TEXCOORD3;
                float3 bitangentWS : TEXCOORD4;
            };

            Varyings SkinVert(Attributes input)
            {
                Varyings output;
                VertexPositionInputs posInputs = GetVertexPositionInputs(input.positionOS.xyz);
                VertexNormalInputs normInputs = GetVertexNormalInputs(input.normalOS, input.tangentOS);

                output.positionCS = posInputs.positionCS;
                output.positionWS = posInputs.positionWS;
                output.uv = TRANSFORM_TEX(input.uv, _BaseMap);
                output.normalWS = normInputs.normalWS;
                output.tangentWS = normInputs.tangentWS;
                output.bitangentWS = normInputs.bitangentWS;
                return output;
            }

            // SSS漫反射：使用Pre-Integrated LUT
            float3 SSSLighting(float3 albedo, float3 normalWS, float3 lightDir, float2 uv, float3 posWS)
            {
                float NdotL = dot(normalWS, lightDir);

                // 估算曲率
                float3 dNdx = ddx(normalWS);
                float3 dNdy = ddy(normalWS);
                float3 dPdx = ddx(posWS);
                float3 dPdy = ddy(posWS);
                float curvature = length(float2(length(dNdx), length(dNdy))) /
                                  length(float2(length(dPdx), length(dPdy)));
                curvature = saturate(curvature * _SSSCurvatureScale);

                // 采样SSS遮罩
                float4 sssData = SAMPLE_TEXTURE2D(_SSSMap, sampler_SSSMap, uv);
                float sssMask = sssData.r;

                // 查Pre-Integrated LUT
                float2 lutUV = float2(NdotL * 0.5 + 0.5, curvature);
                float3 sssLut = SAMPLE_TEXTURE2D(_SSSLut, sampler_SSSLut, lutUV).rgb;

                // 标准diffuse
                float3 standardDiff = albedo * max(0, NdotL);
                // SSS diffuse（LUT颜色已包含albedo tint）
                float3 sssDiff = albedo * sssLut * _SSSColor.rgb;

                return lerp(standardDiff, sssDiff, sssMask * _SSSStrength);
            }

            // 透射效果（背光穿透皮肤）
            float3 Transmission(float3 albedo, float3 normalWS, float3 viewDir, float3 lightDir, float thickness)
            {
                // 扭曲后的透射光方向
                float3 transLightDir = lightDir + normalWS * _TransmissionDistortion;
                float transVdotL = pow(saturate(dot(viewDir, -transLightDir)), _TransmissionPower);
                float3 transmission = (transVdotL + 0.0) * _TransmissionColor.rgb;
                return transmission * thickness * albedo * _TransmissionScale;
            }

            float4 SkinFrag(Varyings input) : SV_Target
            {
                float2 uv = input.uv;

                // 法线贴图
                float3 normalTS = UnpackNormalScale(
                    SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, uv), _NormalScale);
                float3x3 TBN = float3x3(input.tangentWS, input.bitangentWS, input.normalWS);
                float3 normalWS = normalize(mul(normalTS, TBN));

                // 基础颜色
                float4 albedoSample = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv);
                float3 albedo = albedoSample.rgb;

                // Metallic / Roughness
                float4 mrSample = SAMPLE_TEXTURE2D(_MetallicMap, sampler_MetallicMap, uv);
                float metallic = mrSample.r * _Metallic;
                float roughness = mrSample.g * _Roughness;

                // SSS厚度（存在B通道）
                float thickness = SAMPLE_TEXTURE2D(_SSSMap, sampler_SSSMap, uv).b;

                float3 viewDirWS = normalize(GetCameraPositionWS() - input.positionWS);

                // 主光源
                Light mainLight = GetMainLight();
                float3 lightDir = mainLight.direction;
                float3 lightColor = mainLight.color * mainLight.distanceAttenuation;

                // SSS漫反射
                float3 diffuse = SSSLighting(albedo, normalWS, lightDir, uv, input.positionWS);
                diffuse *= lightColor;

                // 透射
                float3 trans = Transmission(albedo, normalWS, viewDirWS, lightDir, thickness);
                trans *= lightColor;

                // 镜面反射（Cook-Torrance）
                float3 halfDir = normalize(lightDir + viewDirWS);
                float NdotH = max(0, dot(normalWS, halfDir));
                float NdotV = max(0, dot(normalWS, viewDirWS));
                float NdotL = max(0, dot(normalWS, lightDir));

                float specSample = SAMPLE_TEXTURE2D(_SpecularMap, sampler_SpecularMap, uv).r;
                float alpha = roughness * roughness;
                float D = alpha * alpha / max(0.0001, pow(NdotH * NdotH * (alpha * alpha - 1) + 1, 2));
                float3 specular = D * _SpecularIntensity * specSample * lightColor * NdotL;

                // 环境光（使用球谐）
                float3 ambient = SampleSH(normalWS) * albedo;

                float3 finalColor = ambient + diffuse + specular + trans;

                return float4(finalColor, 1.0);
            }
            ENDHLSL
        }
    }
}
```

---

## 七、移动端降级方案

### 7.1 轻量级双层漫反射

```hlsl
// 移动端简化SSS（无LUT，纯数学近似）
float3 MobileSSS(float3 albedo, float NdotL, float sssMask)
{
    // 将wrap lighting与颜色偏移组合模拟SSS
    // Wrap lighting：让暗部不那么暗，模拟散射
    float wrapFactor = 0.4; // 0=标准，1=完全wrap
    float wrappedNdotL = (NdotL + wrapFactor) / (1 + wrapFactor);
    float3 wrappedDiffuse = albedo * max(0, wrappedNdotL);

    // 暗部添加红色调（模拟皮下血红蛋白）
    float3 darkRegionColor = albedo * float3(1.0, 0.3, 0.2) * 0.5;
    float darkBlend = 1.0 - saturate(NdotL * 2); // 越暗越明显
    float3 bloodTint = lerp(wrappedDiffuse, darkRegionColor, darkBlend * sssMask);

    return bloodTint;
}
```

### 7.2 性能对比与方案选择

| 方案 | 额外Draw Call | 额外纹理采样 | 显存占用 | 移动端建议 |
|------|-------------|------------|---------|---------|
| Pre-Integrated SSS | 0 | +1（LUT） | +256KB | ✅ 推荐 |
| Screen-Space SSS | +2 Pass | +26采样/像素 | +2*RT | ❌ 高端才可 |
| Burley扩散 | +2 Pass | +16采样/像素 | +1*RT | ⚠️ 有条件 |
| 移动端近似 | 0 | 0 | 0 | ✅ 优先 |

---

## 八、最佳实践总结

### 8.1 美术工作流建议

1. **SSS遮罩贴图**：R通道=SSS强度（脸颊、耳朵最强），G通道=粗糙度修正，B通道=透射厚度
2. **曲率烘焙**：在建模软件（Substance/Marmoset）烘焙曲率图存入专用通道，避免实时计算开销
3. **LUT调色**：Pre-Integrated LUT由TA统一生成，美术不直接修改，通过 `_SSSColor` 参数调整色调

### 8.2 Shader优化技巧

```hlsl
// 优化1：避免在Fragment Shader中计算ddx/ddy求曲率（移动端昂贵）
// 改为在Vertex Shader中传入预计算的曲率
// 优化2：对LUT使用Point采样（性能）或Bilinear（质量）根据平台选择
// 优化3：SSSS的Stencil剔除确保只处理皮肤像素，不全屏模糊

// 优化4：LOD降级
#if defined(SHADER_API_MOBILE)
    // 移动端：仅使用Wrap Lighting
    float3 diffuse = MobileSSS(albedo, NdotL, sssMask);
#else
    // PC/主机：使用Pre-Integrated LUT
    float3 diffuse = SSSLighting(albedo, normalWS, lightDir, uv, positionWS);
#endif
```

### 8.3 集成检查清单

- [ ] 皮肤材质Stencil Ref设为10，供SSSS Pass识别
- [ ] SSS LUT贴图sRGB关闭（线性空间）
- [ ] SSS Mask贴图压缩格式：使用BC4（单通道）或BC5节省带宽
- [ ] 在URP Asset中注册自定义RenderFeature
- [ ] 验证各分辨率下SSSS宽度正确缩放（基于深度）
- [ ] 移动端：关闭SSSS，开启Pre-Integrated方案
- [ ] 测试耳朵/鼻尖/手指背光透射效果

### 8.4 常见问题排查

| 问题 | 原因 | 解决方案 |
|------|------|---------|
| 皮肤过红 | SSS Color饱和度过高 | 降低_SSSColor饱和度 |
| 阴影边缘出现彩色 | LUT UV偏移 | 检查NdotL映射范围 |
| SSSS模糊溢出轮廓 | 没有Stencil剔除 | 确认皮肤Stencil = 10 |
| 移动端性能骤降 | 误开了SSSS Pass | 检查平台宏 |
| 背光区域过亮 | 透射强度过大 | 降低_TransmissionScale |

---

## 参考资料

- Penner, E. (2011). *Pre-Integrated Skin Shading*. GPU Pro 2.
- Jimenez, J. et al. (2015). *Separable Subsurface Scattering*. Eurographics.
- Burley, B. (2015). *Physically Based Shading at Disney (Extended)*. SIGGRAPH.
- d'Eon, E. (2011). *A Quantized-Diffusion Model for Rendering Translucent Materials*. SIGGRAPH.
- Unity HDRP Subsurface Scattering 文档（2022+）
