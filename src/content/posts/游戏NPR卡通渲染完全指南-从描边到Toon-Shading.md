---
title: 游戏NPR卡通渲染完全指南：从描边算法到Toon Shading工程实践
published: 2026-03-30
description: 深度解析非真实感渲染（NPR）在游戏中的工程实现，涵盖轮廓描边算法（Back-Face扩展/后处理描边/几何着色器）、多级色块渲染、卡通高光、Rim Light、日式赛璐珞风格完整Shader实现，以及URP管线下的NPR工程化最佳实践。
tags: [Shader, NPR, 卡通渲染, Unity, URP, 游戏开发]
category: 图形渲染
draft: false
---

# 游戏NPR卡通渲染完全指南：从描边算法到Toon Shading工程实践

## 前言

非真实感渲染（Non-Photorealistic Rendering, NPR）是游戏美术风格化的核心技术之一。从《原神》的赛璐珞风格到《塞尔达：旷野之息》的水彩风，NPR渲染让游戏在画面表现上形成鲜明的辨识度。

本文将系统讲解NPR卡通渲染的完整技术体系：

- 描边（Outline）算法的多种实现方案对比
- 多级色块（Toon Shading）光照模型
- 卡通高光（Specular）与边缘光（Rim Light）
- 完整的赛璐珞风格Shader实现
- URP管线下的NPR工程化方案

---

## 一、描边算法详解

描边是卡通渲染中最具辨识度的特征，不同算法各有优劣：

### 1.1 背面扩展法（Back-Face Expansion）

这是最经典的实时描边方法，通过两个Pass实现：

```hlsl
// ===== 描边Pass（Back Face Expansion）=====
// 在URP中作为第一个Pass，专门渲染描边

Shader "NPR/ToonOutline"
{
    Properties
    {
        _OutlineColor ("描边颜色", Color) = (0, 0, 0, 1)
        _OutlineWidth ("描边宽度", Range(0, 0.1)) = 0.005
        // 使用顶点色R通道控制描边宽度（精细调整）
        _OutlineWidthByVertexColor ("顶点色控制描边宽度", Float) = 1.0
        // 描边随距离缩放（防止近处描边过粗）
        _OutlineDistanceScale ("距离缩放", Range(0, 1)) = 0.5
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }

        // Pass 1：描边Pass
        Pass
        {
            Name "Outline"
            // 只渲染背面
            Cull Front

            HLSLPROGRAM
            #pragma vertex OutlineVert
            #pragma fragment OutlineFrag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float4 color      : COLOR;  // R通道存描边宽度系数
                float4 tangentOS  : TANGENT; // 可选：存平滑法线
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
            };

            CBUFFER_START(UnityPerMaterial)
                half4 _OutlineColor;
                float _OutlineWidth;
                float _OutlineWidthByVertexColor;
                float _OutlineDistanceScale;
            CBUFFER_END

            Varyings OutlineVert(Attributes input)
            {
                Varyings output;

                // 使用顶点色控制描边宽度（美术可在DCC工具中精细调整）
                float widthFactor = lerp(1.0, input.color.r, _OutlineWidthByVertexColor);
                float outlineWidth = _OutlineWidth * widthFactor;

                // 在观察空间中扩展顶点（保证描边粗细不受模型缩放影响）
                float3 positionVS = TransformWorldToView(
                    TransformObjectToWorld(input.positionOS.xyz));
                float3 normalVS = TransformWorldToViewDir(
                    TransformObjectToWorldNormal(input.normalOS));

                // 基于距离缩放描边宽度（模拟真实感，近处描边细）
                float distanceScale = lerp(1.0,
                    1.0 / max(1.0, abs(positionVS.z)), _OutlineDistanceScale);

                // 只在XY方向扩展（避免深度方向伸缩）
                positionVS.xy += normalize(normalVS.xy) * outlineWidth * distanceScale;

                output.positionCS = TransformWViewToHClip(positionVS);
                return output;
            }

            half4 OutlineFrag(Varyings input) : SV_Target
            {
                return _OutlineColor;
            }
            ENDHLSL
        }
    }
}
```

**存在问题：** 法线不连续的硬边模型（如立方体）描边会断开。

### 1.2 平滑法线烘焙技术

解决硬边描边断裂问题的关键技术：

```csharp
using UnityEngine;
using UnityEditor;

/// <summary>
/// 平滑法线烘焙工具 - 将平滑法线写入顶点切线（TANGENT.xyz）
/// 专门解决硬边模型描边断裂问题
/// </summary>
public class SmoothNormalBaker : EditorWindow
{
    [MenuItem("Tools/NPR/烘焙平滑法线到切线")]
    static void ShowWindow() => GetWindow<SmoothNormalBaker>("平滑法线烘焙");

    void OnGUI()
    {
        if (GUILayout.Button("烘焙选中网格的平滑法线"))
            BakeSelectedMeshes();
    }

    static void BakeSelectedMeshes()
    {
        foreach (var go in Selection.gameObjects)
        {
            var mf = go.GetComponent<MeshFilter>();
            if (mf == null || mf.sharedMesh == null) continue;

            BakeSmoothNormals(mf.sharedMesh);
            EditorUtility.SetDirty(mf.sharedMesh);
        }
        AssetDatabase.SaveAssets();
        Debug.Log("平滑法线烘焙完成！");
    }

    /// <summary>
    /// 核心算法：
    /// 1. 收集所有共享同一位置的顶点
    /// 2. 对这些顶点的法线求平均（加权平均）
    /// 3. 将平滑法线转换到切线空间
    /// 4. 写入 TANGENT.xyz（保留 TANGENT.w 用于其他用途）
    /// </summary>
    static void BakeSmoothNormals(Mesh mesh)
    {
        Vector3[] vertices = mesh.vertices;
        Vector3[] normals = mesh.normals;
        Vector4[] tangents = mesh.tangents;

        // 按位置分组（使用字典合并重叠顶点）
        var positionToNormals = new Dictionary<Vector3, List<int>>();
        for (int i = 0; i < vertices.Length; i++)
        {
            // 对位置进行量化，避免浮点误差导致分组失败
            Vector3 roundedPos = new Vector3(
                Mathf.Round(vertices[i].x * 1000f) / 1000f,
                Mathf.Round(vertices[i].y * 1000f) / 1000f,
                Mathf.Round(vertices[i].z * 1000f) / 1000f);

            if (!positionToNormals.ContainsKey(roundedPos))
                positionToNormals[roundedPos] = new List<int>();
            positionToNormals[roundedPos].Add(i);
        }

        Vector3[] smoothNormals = new Vector3[vertices.Length];

        // 计算平均法线
        foreach (var group in positionToNormals.Values)
        {
            Vector3 avgNormal = Vector3.zero;
            foreach (int idx in group)
                avgNormal += normals[idx];
            avgNormal.Normalize();

            foreach (int idx in group)
                smoothNormals[idx] = avgNormal;
        }

        // 将平滑法线转换到切线空间，写入TANGENT
        if (tangents.Length != vertices.Length)
            tangents = new Vector4[vertices.Length];

        for (int i = 0; i < vertices.Length; i++)
        {
            Vector3 n = normals[i];
            Vector3 t = tangents[i];
            Vector3 b = Vector3.Cross(n, t) * tangents[i].w;

            // TBN矩阵逆变换（物体空间 → 切线空间）
            Matrix4x4 tbn = new Matrix4x4(
                new Vector4(t.x, t.y, t.z, 0),
                new Vector4(b.x, b.y, b.z, 0),
                new Vector4(n.x, n.y, n.z, 0),
                new Vector4(0, 0, 0, 1));

            Vector3 smoothNormalTS = tbn.MultiplyVector(smoothNormals[i]);

            // 写入切线的XYZ（保留W分量）
            tangents[i] = new Vector4(smoothNormalTS.x, smoothNormalTS.y,
                smoothNormalTS.z, tangents[i].w);
        }

        mesh.tangents = tangents;
    }
}
```

### 1.3 后处理描边（屏幕空间）

基于法线/深度梯度的后处理描边，效果更统一：

```hlsl
// ===== 屏幕空间描边 - URP RendererFeature =====
Shader "Hidden/NPR/ScreenSpaceOutline"
{
    Properties
    {
        _OutlineColor ("描边颜色", Color) = (0,0,0,1)
        _OutlineThickness ("描边厚度", Range(1, 5)) = 1
        _DepthThreshold ("深度阈值", Range(0.0001, 0.01)) = 0.001
        _NormalThreshold ("法线阈值", Range(0, 1)) = 0.5
    }

    SubShader
    {
        Pass
        {
            ZTest Always Cull Off ZWrite Off

            HLSLPROGRAM
            #pragma vertex FullscreenVert
            #pragma fragment OutlineDetectFrag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/Runtime/Utilities/Blit.hlsl"

            TEXTURE2D_X(_CameraDepthTexture);
            TEXTURE2D_X(_CameraNormalsTexture);
            SAMPLER(sampler_CameraDepthTexture);
            SAMPLER(sampler_CameraNormalsTexture);

            CBUFFER_START(UnityPerMaterial)
                half4 _OutlineColor;
                float _OutlineThickness;
                float _DepthThreshold;
                float _NormalThreshold;
            CBUFFER_END

            // Roberts Cross 边缘检测算子（比 Sobel 更适合实时）
            float RobertsCrossDepth(float d0, float d1, float d2, float d3)
            {
                float gx = d1 - d3;  // 对角差
                float gy = d0 - d2;
                return sqrt(gx * gx + gy * gy);
            }

            float RobertsCrossNormal(float3 n0, float3 n1, float3 n2, float3 n3)
            {
                float3 gx = n1 - n3;
                float3 gy = n0 - n2;
                return sqrt(dot(gx,gx) + dot(gy,gy));
            }

            half4 OutlineDetectFrag(Varyings input) : SV_Target
            {
                float2 uv = input.texcoord;
                float2 texelSize = _BlitTexture_TexelSize.xy;
                float thickness = _OutlineThickness;

                // 采样4个对角邻居（Roberts Cross核）
                float2 uvs[4];
                uvs[0] = uv + float2(-1, 1) * texelSize * thickness;
                uvs[1] = uv + float2( 1, 1) * texelSize * thickness;
                uvs[2] = uv + float2(-1,-1) * texelSize * thickness;
                uvs[3] = uv + float2( 1,-1) * texelSize * thickness;

                // 深度差异检测
                float depths[4];
                for (int i = 0; i < 4; i++)
                    depths[i] = SAMPLE_TEXTURE2D_X(
                        _CameraDepthTexture, sampler_CameraDepthTexture, uvs[i]).r;

                float depthEdge = RobertsCrossDepth(depths[0], depths[1],
                    depths[2], depths[3]);

                // 法线差异检测
                float3 normals[4];
                for (int j = 0; j < 4; j++)
                    normals[j] = SAMPLE_TEXTURE2D_X(
                        _CameraNormalsTexture, sampler_CameraNormalsTexture, uvs[j]).rgb;

                float normalEdge = RobertsCrossNormal(normals[0], normals[1],
                    normals[2], normals[3]);

                // 合并边缘
                float edge = step(_DepthThreshold, depthEdge)
                           + step(_NormalThreshold, normalEdge);
                edge = saturate(edge);

                // 混合原始颜色与描边颜色
                half4 originalColor = SAMPLE_TEXTURE2D_X(
                    _BlitTexture, sampler_LinearClamp, uv);
                return lerp(originalColor, _OutlineColor, edge);
            }
            ENDHLSL
        }
    }
}
```

---

## 二、Toon Shading 光照模型

### 2.1 多级色块光照实现

```hlsl
// ===== 完整的卡通着色器 - 多级色块 + 描边 =====
Shader "NPR/ToonLit"
{
    Properties
    {
        [Header(Base)]
        _BaseColor ("基础颜色", Color) = (1, 1, 1, 1)
        _BaseMap ("基础贴图", 2D) = "white" {}

        [Header(Toon Shading)]
        _ShadowColor ("阴影颜色", Color) = (0.6, 0.6, 0.8, 1)  // 偏蓝的阴影
        _ShadowThreshold ("明暗分界线", Range(-1, 1)) = 0
        _ShadowSmoothness ("分界线柔和度", Range(0, 0.5)) = 0.05
        _ShadowRamp ("阴影渐变图", 2D) = "white" {}
        _UseShadowRamp ("使用渐变图", Float) = 0

        [Header(Specular)]
        _SpecularColor ("高光颜色", Color) = (1, 1, 1, 1)
        _SpecularSize ("高光大小", Range(0, 1)) = 0.5
        _SpecularSmoothness ("高光柔和度", Range(0, 0.5)) = 0.01

        [Header(Rim Light)]
        _RimColor ("边缘光颜色", Color) = (1, 1, 1, 1)
        _RimPower ("边缘光强度", Range(0.1, 8)) = 3

        [Header(Outline)]
        _OutlineColor ("描边颜色", Color) = (0, 0, 0, 1)
        _OutlineWidth ("描边宽度", Range(0, 0.05)) = 0.002

        [Header(Emission)]
        _EmissionColor ("自发光颜色", Color) = (0, 0, 0, 0)
        _EmissionMap ("自发光贴图", 2D) = "black" {}
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }

        // ===== Pass 1：描边Pass =====
        Pass
        {
            Name "Outline"
            Cull Front

            HLSLPROGRAM
            #pragma vertex OutlineVert
            #pragma fragment OutlineFrag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attribs { float4 posOS : POSITION; float3 normalOS : NORMAL; float4 tangentOS : TANGENT; };
            struct Varyings { float4 posCS : SV_POSITION; };

            CBUFFER_START(UnityPerMaterial)
                half4 _OutlineColor;
                float _OutlineWidth;
            CBUFFER_END

            Varyings OutlineVert(Attribs v)
            {
                Varyings o;
                // 从切线中读取烘焙的平滑法线
                float3 smoothNormalTS = v.tangentOS.xyz;
                float3 normalOS = v.normalOS;
                float3 tangentOS = v.tangentOS.xyz;
                float3 bitangentOS = cross(normalOS, tangentOS) * v.tangentOS.w;
                // TBN矩阵转换到物体空间
                float3 smoothNormalOS = tangentOS * smoothNormalTS.x
                    + bitangentOS * smoothNormalTS.y
                    + normalOS * smoothNormalTS.z;

                float3 smoothNormalWS = TransformObjectToWorldNormal(smoothNormalOS);
                float3 smoothNormalCS = TransformWorldToHClipDir(smoothNormalWS);

                float4 posCS = TransformObjectToHClip(v.posOS.xyz);
                // 在裁剪空间沿法线方向扩展
                float2 ndcNormal = normalize(smoothNormalCS.xy);
                posCS.xy += ndcNormal * _OutlineWidth * posCS.w;

                o.posCS = posCS;
                return o;
            }

            half4 OutlineFrag(Varyings i) : SV_Target { return _OutlineColor; }
            ENDHLSL
        }

        // ===== Pass 2：主光照Pass =====
        Pass
        {
            Name "ToonLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex ToonVert
            #pragma fragment ToonFrag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile _ _SHADOWS_SOFT

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
                float4 positionCS  : SV_POSITION;
                float2 uv          : TEXCOORD0;
                float3 positionWS  : TEXCOORD1;
                float3 normalWS    : TEXCOORD2;
            };

            TEXTURE2D(_BaseMap);        SAMPLER(sampler_BaseMap);
            TEXTURE2D(_ShadowRamp);     SAMPLER(sampler_ShadowRamp);
            TEXTURE2D(_EmissionMap);    SAMPLER(sampler_EmissionMap);

            CBUFFER_START(UnityPerMaterial)
                half4 _BaseColor;
                float4 _BaseMap_ST;
                half4 _ShadowColor;
                float _ShadowThreshold;
                float _ShadowSmoothness;
                float _UseShadowRamp;
                half4 _SpecularColor;
                float _SpecularSize;
                float _SpecularSmoothness;
                half4 _RimColor;
                float _RimPower;
                half4 _EmissionColor;
            CBUFFER_END

            Varyings ToonVert(Attributes v)
            {
                Varyings o;
                VertexPositionInputs posInputs = GetVertexPositionInputs(v.positionOS.xyz);
                o.positionCS = posInputs.positionCS;
                o.positionWS = posInputs.positionWS;
                o.normalWS = TransformObjectToWorldNormal(v.normalOS);
                o.uv = TRANSFORM_TEX(v.uv, _BaseMap);
                return o;
            }

            half4 ToonFrag(Varyings i) : SV_Target
            {
                // 基础纹理采样
                half4 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, i.uv) * _BaseColor;
                float3 normalWS = normalize(i.normalWS);
                float3 viewDirWS = GetWorldSpaceNormalizeViewDir(i.positionWS);

                // 获取主光源
                Light mainLight = GetMainLight(TransformWorldToShadowCoord(i.positionWS));
                float3 lightDir = normalize(mainLight.direction);
                float3 halfDir = normalize(lightDir + viewDirWS);

                // ===== 1. 卡通漫反射（多级色块）=====
                float NdotL = dot(normalWS, lightDir);
                // 加入阴影衰减
                float lightAttenuation = mainLight.shadowAttenuation * mainLight.distanceAttenuation;
                float halfLambert = NdotL * 0.5 + 0.5; // Half Lambert 更柔和

                half3 diffuse;
                if (_UseShadowRamp > 0.5)
                {
                    // 使用 Ramp 贴图驱动色调（美术可精确控制每个色阶）
                    float rampU = saturate(halfLambert * lightAttenuation);
                    diffuse = SAMPLE_TEXTURE2D(_ShadowRamp, sampler_ShadowRamp,
                        float2(rampU, 0.5)).rgb * baseColor.rgb;
                }
                else
                {
                    // 数学公式版：smoothstep 实现色块过渡
                    float toonMask = smoothstep(
                        _ShadowThreshold - _ShadowSmoothness,
                        _ShadowThreshold + _ShadowSmoothness,
                        halfLambert * lightAttenuation);

                    diffuse = lerp(_ShadowColor.rgb, half3(1,1,1), toonMask) * baseColor.rgb;
                }

                // ===== 2. 卡通高光（Blinn-Phong 色块化）=====
                float NdotH = dot(normalWS, halfDir);
                // 将连续高光量化为色块
                float specularMask = smoothstep(
                    _SpecularSize - _SpecularSmoothness,
                    _SpecularSize + _SpecularSmoothness,
                    NdotH);
                half3 specular = specularMask * _SpecularColor.rgb * lightAttenuation;

                // ===== 3. 边缘光（Rim Light）=====
                float NdotV = dot(normalWS, viewDirWS);
                float rim = pow(1.0 - saturate(NdotV), _RimPower);
                // 只在受光面显示边缘光（背光面本就有阴影，无需 Rim）
                rim *= saturate(NdotL + 0.3);
                half3 rimLight = rim * _RimColor.rgb;

                // ===== 4. 自发光 =====
                half3 emission = SAMPLE_TEXTURE2D(
                    _EmissionMap, sampler_EmissionMap, i.uv).rgb * _EmissionColor.rgb;

                // ===== 最终合成 =====
                half3 finalColor = diffuse
                    + specular
                    + rimLight
                    + emission;

                // 叠加环境光（避免背光面全黑）
                finalColor += SampleSH(normalWS) * baseColor.rgb * 0.3;

                return half4(finalColor, baseColor.a);
            }
            ENDHLSL
        }
    }
}
```

---

## 三、高级NPR技术

### 3.1 面部阴影修正（SDF阴影贴图）

日系角色渲染中，面部阴影通常使用 SDF（Signed Distance Field）贴图精确控制，避免法线差异导致的异常阴影：

```hlsl
// 面部SDF阴影技术
// SDF贴图：存储了不同光照角度下面部的阴影形状信息

half3 ComputeFaceShadow(float2 uv, float3 lightDirWS, float3 faceForward, float3 faceRight)
{
    // 计算光照在面部平面上的投影角度
    float3 lightFlat = normalize(float3(lightDirWS.x, 0, lightDirWS.z));
    float dotFwd = dot(lightFlat, faceForward);
    float dotRight = dot(lightFlat, faceRight);

    // 根据光照方向，镜像UV（左右脸对称）
    float2 sdfUV = uv;
    if (dotRight < 0) sdfUV.x = 1 - sdfUV.x;

    // 采样SDF贴图（存的是光照角度的阈值）
    float sdfValue = SAMPLE_TEXTURE2D(_FaceShadowSDF, sampler_FaceShadowSDF, sdfUV).r;

    // 将当前光照角度映射到 [0,1]
    float lightAngle = (1 - dotFwd) * 0.5;  // 正前方=0, 侧面=0.5, 背面=1

    // SDF值大于当前角度时处于亮面
    float shadowMask = step(lightAngle, sdfValue);

    return lerp(_ShadowColor.rgb, half3(1,1,1), shadowMask);
}
```

### 3.2 描边粗细动态控制

```hlsl
// 根据不同部位动态调整描边粗细
// 通过顶点色的不同通道传递不同部位的描边权重

// R通道：描边宽度系数（0=无描边，1=完整描边）
// G通道：描边颜色偏移（可实现颜色变化的描边）
// B通道：描边形变系数（控制是否参与宽度×距离计算）

Varyings OutlineVert_Advanced(AttributesAdvanced v)
{
    float outlineWidthR = v.color.r;   // 美术控制的宽度
    float outlineType   = v.color.b;   // 0=世界空间描边，1=屏幕空间描边

    // 世界空间描边：粗细随距离变化
    float3 posWS = TransformObjectToWorld(v.positionOS.xyz);
    float3 cameraPosWS = GetCameraPositionWS();
    float dist = length(posWS - cameraPosWS);
    float distFactor = 1.0 / max(1.0, dist * 0.1); // 距离衰减

    float finalWidth = _OutlineWidth * outlineWidthR
        * lerp(distFactor, 1.0, outlineType);  // 混合两种模式

    // ...后续扩展逻辑
}
```

### 3.3 NPR URP RendererFeature 实现

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// NPR Screen Space Outline - URP Renderer Feature
/// 负责在渲染管线中注入后处理描边Pass
/// </summary>
public class NPROutlineFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class Settings
    {
        public RenderPassEvent renderPassEvent = RenderPassEvent.AfterRenderingTransparents;
        public Material outlineMaterial;
        public float outlineThickness = 1f;
        [ColorUsage(true, true)]
        public Color outlineColor = Color.black;
        public float depthThreshold = 0.001f;
        public float normalThreshold = 0.5f;
    }

    public Settings settings = new();
    private NPROutlinePass _pass;

    public override void Create()
    {
        _pass = new NPROutlinePass(settings);
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (settings.outlineMaterial == null) return;
        renderer.EnqueuePass(_pass);
    }
}

public class NPROutlinePass : ScriptableRenderPass
{
    private readonly NPROutlineFeature.Settings _settings;
    private RTHandle _tempRT;
    private static readonly int OutlineColorID = Shader.PropertyToID("_OutlineColor");
    private static readonly int OutlineThicknessID = Shader.PropertyToID("_OutlineThickness");
    private static readonly int DepthThresholdID = Shader.PropertyToID("_DepthThreshold");
    private static readonly int NormalThresholdID = Shader.PropertyToID("_NormalThreshold");

    public NPROutlinePass(NPROutlineFeature.Settings settings)
    {
        _settings = settings;
        renderPassEvent = settings.renderPassEvent;
        // 需要法线贴图
        ConfigureInput(ScriptableRenderPassInput.Normal | ScriptableRenderPassInput.Depth);
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        RenderingUtils.ReAllocateIfNeeded(ref _tempRT, desc, name: "_NPROutlineTemp");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("NPR Outline");

        // 设置Shader参数
        _settings.outlineMaterial.SetColor(OutlineColorID, _settings.outlineColor);
        _settings.outlineMaterial.SetFloat(OutlineThicknessID, _settings.outlineThickness);
        _settings.outlineMaterial.SetFloat(DepthThresholdID, _settings.depthThreshold);
        _settings.outlineMaterial.SetFloat(NormalThresholdID, _settings.normalThreshold);

        var renderer = renderingData.cameraData.renderer;
        // Blit 全屏后处理
        Blitter.BlitCameraTexture(cmd, renderer.cameraColorTargetHandle,
            _tempRT, _settings.outlineMaterial, 0);
        Blitter.BlitCameraTexture(cmd, _tempRT, renderer.cameraColorTargetHandle);

        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        _tempRT?.Release();
    }
}
```

---

## 四、材质属性动画（实现水墨/赛璐珞动态效果）

```csharp
/// <summary>
/// NPR材质动画控制器 - 实现动态色调、受击高亮等效果
/// </summary>
public class NPRMaterialAnimator : MonoBehaviour
{
    [Header("受击高亮效果")]
    public float hitFlashDuration = 0.15f;
    public Color hitFlashColor = Color.white;

    [Header("溶解效果")]
    public float dissolveSpeed = 1f;

    private Renderer _renderer;
    private MaterialPropertyBlock _mpb;
    private Coroutine _flashCoroutine;

    // Shader property IDs（避免字符串查找性能开销）
    private static readonly int HitColorID = Shader.PropertyToID("_HitFlashColor");
    private static readonly int HitIntensityID = Shader.PropertyToID("_HitFlashIntensity");
    private static readonly int DissolveID = Shader.PropertyToID("_DissolveAmount");

    void Awake()
    {
        _renderer = GetComponent<Renderer>();
        _mpb = new MaterialPropertyBlock();
    }

    /// <summary>触发受击高亮（不分配新材质，使用MaterialPropertyBlock）</summary>
    public void TriggerHitFlash()
    {
        if (_flashCoroutine != null) StopCoroutine(_flashCoroutine);
        _flashCoroutine = StartCoroutine(HitFlashRoutine());
    }

    private System.Collections.IEnumerator HitFlashRoutine()
    {
        float elapsed = 0f;
        while (elapsed < hitFlashDuration)
        {
            elapsed += Time.deltaTime;
            float intensity = Mathf.Sin(elapsed / hitFlashDuration * Mathf.PI);

            _renderer.GetPropertyBlock(_mpb);
            _mpb.SetColor(HitColorID, hitFlashColor);
            _mpb.SetFloat(HitIntensityID, intensity);
            _renderer.SetPropertyBlock(_mpb);

            yield return null;
        }

        // 恢复
        _renderer.GetPropertyBlock(_mpb);
        _mpb.SetFloat(HitIntensityID, 0f);
        _renderer.SetPropertyBlock(_mpb);
    }

    /// <summary>角色消失溶解动画</summary>
    public void PlayDissolve(System.Action onComplete = null)
    {
        StartCoroutine(DissolveRoutine(onComplete));
    }

    private System.Collections.IEnumerator DissolveRoutine(System.Action onComplete)
    {
        float amount = 0f;
        while (amount < 1f)
        {
            amount += Time.deltaTime * dissolveSpeed;
            _renderer.GetPropertyBlock(_mpb);
            _mpb.SetFloat(DissolveID, amount);
            _renderer.SetPropertyBlock(_mpb);
            yield return null;
        }
        onComplete?.Invoke();
    }
}
```

---

## 五、性能优化与移动端适配

### 5.1 移动端NPR优化策略

```hlsl
// 移动端卡通着色器优化版本
// 目标：在中低端手机保持60fps

Shader "NPR/ToonLit_Mobile"
{
    // 针对移动端的主要优化点：
    // 1. 去除屏幕空间描边（改用背面扩展法）
    // 2. 简化阴影计算（使用单级色块而非渐变图）
    // 3. 去除实时阴影支持，改用预烘焙的AO贴图
    // 4. 使用half精度而非float（ARM Mali优化）

    Properties
    {
        _BaseMap ("基础贴图", 2D) = "white" {}
        _BaseColor ("颜色", Color) = (1,1,1,1)
        _ShadowColor ("阴影颜色", Color) = (0.6,0.6,0.8,1)
        _ShadowThreshold ("明暗阈值", Range(-1,1)) = 0
        _AOMap ("AO贴图", 2D) = "white" {}
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }
        LOD 100

        Pass
        {
            Name "ToonLit_Mobile"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            // 移动端：禁用不需要的变体
            #pragma vertex ToonVertMobile
            #pragma fragment ToonFragMobile
            // 不使用阴影变体
            // #pragma multi_compile _ _MAIN_LIGHT_SHADOWS

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            struct Attributes
            {
                float4 positionOS : POSITION;
                half3 normalOS    : NORMAL;   // half精度法线
                float2 uv         : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv         : TEXCOORD0;
                half3 normalWS    : TEXCOORD1;  // half精度
                half3 viewDirWS   : TEXCOORD2;
            };

            TEXTURE2D(_BaseMap);  SAMPLER(sampler_BaseMap);
            TEXTURE2D(_AOMap);    SAMPLER(sampler_AOMap);

            CBUFFER_START(UnityPerMaterial)
                half4 _BaseColor;
                float4 _BaseMap_ST;
                half4 _ShadowColor;
                half _ShadowThreshold;
            CBUFFER_END

            Varyings ToonVertMobile(Attributes v)
            {
                Varyings o;
                o.positionCS = TransformObjectToHClip(v.positionOS.xyz);
                o.uv = TRANSFORM_TEX(v.uv, _BaseMap);
                o.normalWS = (half3)TransformObjectToWorldNormal(v.normalOS);
                o.viewDirWS = (half3)GetWorldSpaceNormalizeViewDir(
                    TransformObjectToWorld(v.positionOS.xyz));
                return o;
            }

            half4 ToonFragMobile(Varyings i) : SV_Target
            {
                half4 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, i.uv)
                    * _BaseColor;
                half ao = SAMPLE_TEXTURE2D(_AOMap, sampler_AOMap, i.uv).r;

                half3 normalWS = normalize(i.normalWS);

                // 获取主光源方向（不含阴影计算）
                Light mainLight = GetMainLight();
                half NdotL = dot(normalWS, (half3)mainLight.direction);
                half halfLambert = NdotL * 0.5h + 0.5h;

                // 单级色块（移动端最省的实现）
                half toonMask = step(_ShadowThreshold, halfLambert * ao);
                half3 diffuse = lerp(_ShadowColor.rgb, (half3)1, toonMask)
                    * baseColor.rgb;

                // 简化的边缘光
                half rim = pow(1.0h - saturate(dot(normalWS, i.viewDirWS)), 3.0h);
                diffuse += rim * 0.3h;

                return half4(diffuse, baseColor.a);
            }
            ENDHLSL
        }
    }

    // 低配版回退
    FallBack "Universal Render Pipeline/Lit"
}
```

---

## 六、最佳实践总结

### 6.1 NPR 描边方案选型

| 方案 | 优点 | 缺点 | 适用场景 |
|------|------|------|---------|
| 背面扩展 | 性能极佳 | 硬边断裂，需烘焙平滑法线 | 角色、主要物体 |
| 屏幕空间 | 描边统一，包含所有物体 | 性能开销大，动态感强 | PC/主机平台 |
| 几何着色器 | 精确控制每条边 | 移动端不支持，性能差 | 不推荐生产使用 |
| SDF描边 | 细节可控，效果最好 | 需要额外贴图，制作成本高 | 主角面部、重要角色 |

### 6.2 工程化建议

1. **分级质量设置**：
   - 高画质：屏幕空间描边 + 面部SDF阴影 + 多级Ramp光照
   - 中画质：背面扩展描边 + 数学计算Toon Shading
   - 低画质：简化单级色块，无描边

2. **平滑法线工作流**：
   - 在 DCC 工具（Maya/Blender）中导出时保留平滑法线
   - 或使用工具在 Unity 中烘焙到切线/顶点色

3. **材质参数数据化**：
   - 将阴影阈值、描边宽度等参数存入 ScriptableObject
   - 允许策划/美术在运行时调整预览

4. **性能测试基准**：
   - 移动端目标：单角色 Toon Shader < 0.3ms（GPU时间）
   - 开启 Frame Debugger 检查 Pass 数量，避免描边 Pass 叠加

### 6.3 常见问题

```
问题：描边在角色弯曲处断裂
解决：使用平滑法线烘焙工具，将平滑法线存入切线通道

问题：面部阴影出现奇怪的三角形块状阴影
解决：
  1. 检查面部法线是否平滑
  2. 使用SDF阴影贴图替代实时光照阴影
  3. 将面部网格单独拆分，使用独立光照方向

问题：边缘光（Rim Light）在背光时太强
解决：乘以 saturate(NdotL + offset) 衰减背光面的边缘光

问题：移动端Toon Shader发热明显
解决：
  1. 检查是否有overdraw（使用帧调试器的Overdraw模式）
  2. 降低贴图采样次数
  3. 将阴影计算改为顶点着色（Vertex Shader）
```

---

## 总结

NPR卡通渲染是艺术与工程的结合。从描边算法的精心选择，到Toon Shading的光照建模，每一个细节都在服务游戏的美术风格。

核心要点：
- **描边**是卡通渲染的灵魂，背面扩展 + 平滑法线是生产首选
- **色块光照**通过 smoothstep 或 Ramp 贴图实现，后者美术可控性更强
- **Rim Light** 为角色增添立体感，但要避免背光面过曝
- **移动端** 必须简化，half 精度 + 减少 Pass + 预烘焙 AO 是关键
- **工程化** 才是落地之道：分级渲染、数据驱动、MaterialPropertyBlock 避免材质拷贝

掌握 NPR 技术，让你的游戏在茫茫竞品中拥有独特的视觉辨识度。
