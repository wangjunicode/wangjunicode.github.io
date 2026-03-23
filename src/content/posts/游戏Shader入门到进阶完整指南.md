---
title: 游戏Shader入门到进阶完整指南
description: 系统讲解游戏Shader开发从基础GLSL/HLSL语法到PBR材质、自定义渲染管线的完整学习路径，涵盖Unity URP与Shader Graph实战。
published: 2026-03-21
category: 图形渲染
tags: [Shader, HLSL, PBR, Unity, URP, 图形渲染]
---

# 游戏Shader入门到进阶完整指南

Shader 是游戏视觉效果的核心。掌握 Shader 开发，能让你从"功能实现者"晋升为"视觉创造者"。本指南系统覆盖从入门语法到 PBR 材质、自定义渲染管线的完整知识体系。

## 一、渲染管线基础

### 1.1 GPU 渲染流水线

```
顶点数据 → [顶点着色器] → 图元装配 → 光栅化 → [片元着色器] → 逐片元测试 → 帧缓冲
```

| 阶段 | 可编程 | 职责 |
|------|--------|------|
| 顶点着色器 | ✅ | 坐标变换、法线变换、UV传递 |
| 曲面细分 | ✅ | 动态增加多边形细节 |
| 几何着色器 | ✅ | 生成/销毁图元（粒子、草地） |
| 片元着色器 | ✅ | 光照计算、纹理采样、颜色输出 |
| 深度测试 | ❌ | Z-Buffer 比较，决定遮挡关系 |
| 混合 | 部分 | Alpha 混合、透明度处理 |

### 1.2 坐标空间变换

```hlsl
// 完整变换链：模型空间 → 世界空间 → 观察空间 → 裁剪空间
float4 ClipPos = mul(UNITY_MATRIX_MVP, float4(positionOS, 1.0));

// 分步理解：
float4 worldPos = mul(unity_ObjectToWorld, float4(positionOS, 1.0));  // M矩阵
float4 viewPos  = mul(UNITY_MATRIX_V, worldPos);                       // V矩阵
float4 clipPos  = mul(UNITY_MATRIX_P, viewPos);                        // P矩阵
```

## 二、HLSL 核心语法

### 2.1 数据类型

```hlsl
// 标量
float  f = 1.0;      // 32位浮点（高精度，移动端慎用）
half   h = 1.0;      // 16位浮点（移动端性能最优）
fixed  x = 0.5;      // 11位定点（-2~2范围，极少使用）
int    i = 1;        // 32位整数
bool   b = true;

// 向量（1~4分量）
float2 uv = float2(0.5, 0.5);
float3 normal = float3(0, 1, 0);
float4 color = float4(1, 0, 0, 1);   // RGBA

// 矩阵
float4x4 mvp;        // 4x4矩阵
float3x3 normalMat;  // 法线变换矩阵

// 访问分量（支持 xyzw 和 rgba 混用）
float3 v = float3(1, 2, 3);
float x = v.x;       // 1
float2 xy = v.xy;    // (1, 2)
float3 bgr = v.zyx;  // Swizzle: (3, 2, 1)
```

### 2.2 内置函数

```hlsl
// 数学函数
float a = abs(-1.5);          // 1.5
float b = saturate(1.5);      // clamp(x,0,1) = 1.0
float c = lerp(0.0, 1.0, 0.5); // 线性插值 = 0.5
float d = smoothstep(0, 1, 0.5); // 平滑阶梯
float e = pow(2.0, 10.0);    // 1024

// 几何函数
float3 n = normalize(float3(1, 1, 0)); // 归一化
float  d = dot(float3(1,0,0), float3(0,1,0)); // 点积 = 0
float3 r = reflect(lightDir, normal);  // 反射方向
float3 h = normalize(lightDir + viewDir); // 半程向量

// 纹理采样
float4 col = tex2D(_MainTex, uv);                    // 2D纹理
float4 col = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, uv); // URP写法
float4 col = texCUBE(_CubeTex, reflectDir);          // 立方体纹理
```

## 三、URP Shader 完整模板

### 3.1 最简单 Unlit Shader

```hlsl
Shader "Custom/SimpleUnlit"
{
    Properties
    {
        _BaseColor ("Base Color", Color) = (1,1,1,1)
        _BaseMap   ("Base Texture", 2D) = "white" {}
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
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _BaseMap_ST; // 纹理的Tiling和Offset
            CBUFFER_END
            
            TEXTURE2D(_BaseMap);
            SAMPLER(sampler_BaseMap);
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv         : TEXCOORD0;
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv         : TEXCOORD0;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = TRANSFORM_TEX(IN.uv, _BaseMap); // 应用 Tiling/Offset
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                half4 texColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, IN.uv);
                return texColor * _BaseColor;
            }
            ENDHLSL
        }
    }
}
```

### 3.2 PBR 光照 Shader

```hlsl
// 基于物理的渲染（PBR）核心公式
// Cook-Torrance BRDF: f = kd * f_lambert + ks * f_cook-torrance
//
// f_cook-torrance = D * G * F / (4 * dot(N,V) * dot(N,L))
// D = GGX 法线分布函数（微表面法线朝向）
// G = Smith 几何遮蔽函数（自遮挡）
// F = Fresnel-Schlick 近似（反射率随角度变化）

half3 PBRLighting(half3 albedo, half metallic, half roughness, 
                  half3 N, half3 V, half3 L, half3 lightColor)
{
    half3 H = normalize(V + L);
    float NdotL = max(dot(N, L), 0.0);
    float NdotV = max(dot(N, V), 0.001);
    float NdotH = max(dot(N, H), 0.0);
    float HdotV = max(dot(H, V), 0.0);

    // 基础反射率
    half3 F0 = lerp(half3(0.04, 0.04, 0.04), albedo, metallic);
    
    // Fresnel (Schlick近似)
    half3 F = F0 + (1.0 - F0) * pow(1.0 - HdotV, 5.0);
    
    // GGX 法线分布
    float alpha = roughness * roughness;
    float alpha2 = alpha * alpha;
    float denom = NdotH * NdotH * (alpha2 - 1.0) + 1.0;
    float D = alpha2 / (PI * denom * denom);
    
    // Smith 几何遮蔽
    float k = (roughness + 1.0) * (roughness + 1.0) / 8.0;
    float G1V = NdotV / (NdotV * (1.0 - k) + k);
    float G1L = NdotL / (NdotL * (1.0 - k) + k);
    float G = G1V * G1L;
    
    // 镜面项
    half3 specular = (D * G * F) / (4.0 * NdotV * NdotL + 0.001);
    
    // 漫反射项（金属无漫反射）
    half3 kD = (1.0 - F) * (1.0 - metallic);
    half3 diffuse = kD * albedo / PI;
    
    return (diffuse + specular) * lightColor * NdotL;
}
```

## 四、常见效果实现

### 4.1 溶解效果（Dissolve）

```hlsl
Properties
{
    _DissolveMap  ("Dissolve Noise", 2D) = "white" {}
    _DissolveAmount ("Dissolve Amount", Range(0,1)) = 0
    _EdgeColor    ("Edge Color", Color) = (1,0.5,0,1)
    _EdgeWidth    ("Edge Width", Range(0,0.1)) = 0.05
}

half4 frag(Varyings IN) : SV_Target
{
    half noise = SAMPLE_TEXTURE2D(_DissolveMap, sampler_DissolveMap, IN.uv).r;
    
    // 溶解裁剪
    float dissolve = noise - _DissolveAmount;
    clip(dissolve); // dissolve < 0 时丢弃该片元
    
    // 边缘发光
    half edgeMask = step(dissolve, _EdgeWidth);
    half3 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, IN.uv).rgb;
    half3 finalColor = lerp(baseColor, _EdgeColor.rgb, edgeMask);
    
    return half4(finalColor, 1);
}
```

### 4.2 顶点动画（水面波动）

```hlsl
Varyings vert(Attributes IN)
{
    Varyings OUT;
    
    // 获取世界空间 XZ 坐标用于波形计算
    float3 worldPos = mul(unity_ObjectToWorld, IN.positionOS).xyz;
    
    // 叠加多个正弦波模拟水面
    float wave1 = sin(worldPos.x * 2.0 + _Time.y * 1.5) * 0.1;
    float wave2 = sin(worldPos.z * 1.5 + _Time.y * 2.0) * 0.08;
    float wave3 = sin((worldPos.x + worldPos.z) * 1.2 + _Time.y * 1.2) * 0.06;
    
    IN.positionOS.y += wave1 + wave2 + wave3;
    
    // 重新计算法线（偏导数法）
    float dx = cos(worldPos.x * 2.0 + _Time.y * 1.5) * 0.2;
    float dz = cos(worldPos.z * 1.5 + _Time.y * 2.0) * 0.12;
    IN.normalOS = normalize(float3(-dx, 1.0, -dz));
    
    OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
    return OUT;
}
```

### 4.3 描边效果（Outline）

```hlsl
// Pass 1：正常渲染
// Pass 2：描边 Pass（背面法线扩张）
Pass
{
    Name "Outline"
    Cull Front // 渲染背面
    
    HLSLPROGRAM
    #pragma vertex OutlineVert
    #pragma fragment OutlineFrag
    
    float _OutlineWidth;
    float4 _OutlineColor;
    
    Varyings OutlineVert(Attributes IN)
    {
        Varyings OUT;
        // 沿法线方向扩张顶点（观察空间描边更稳定）
        float3 normalVS = mul((float3x3)UNITY_MATRIX_IT_MV, IN.normalOS);
        normalVS = normalize(normalVS);
        
        float4 posCS = TransformObjectToHClip(IN.positionOS.xyz);
        // 在裁剪空间偏移（保持描边宽度屏幕一致）
        float2 offset = normalize(normalVS.xy) * (_OutlineWidth * 0.01);
        posCS.xy += offset * posCS.w;
        OUT.positionCS = posCS;
        return OUT;
    }
    
    half4 OutlineFrag(Varyings IN) : SV_Target
    {
        return _OutlineColor;
    }
    ENDHLSL
}
```

## 五、Shader 性能优化

### 5.1 移动端优化清单

```hlsl
// ✅ 使用 half 替代 float（移动端 half 计算更快）
half3 albedo = SAMPLE_TEXTURE2D(...).rgb; // 非 float3

// ✅ 避免在片元着色器中做复杂计算
// 反面：片元着色器中归一化（每个像素都算）
float3 N = normalize(IN.normalWS); // 低精度法线要在片元归一化
// 优化：简单模型可以在顶点阶段归一化

// ✅ 分支预测优化：用 step/lerp 替代 if
// 反面：
if (mask > 0.5) color = colorA;
else color = colorB;
// 优化：
color = lerp(colorB, colorA, step(0.5, mask));

// ✅ 纹理采样数优化
// 将 Roughness/Metallic/AO 打包到一张纹理的 RGB 通道

// ✅ 避免 discard/clip（破坏 TBDR 优化，移动端 Early-Z 失效）
```

### 5.2 Shader 变体管理

```hlsl
// 使用 shader_feature 替代 multi_compile（减少变体数量）
#pragma shader_feature _USE_NORMAL_MAP     // 编辑器静态开关
#pragma multi_compile _ _SHADOWS_SOFT      // 运行时动态开关

// 变体数量计算：所有开关的笛卡尔积
// 2个二值开关 = 4个变体
// 控制变体数在 100 以内，否则打包时间和内存暴增
```

## 六、学习路线图

```
基础阶段（1-2月）
├── HLSL/GLSL 基础语法
├── 渲染管线理解
├── Unity ShaderLab 格式
└── Unlit Shader 实现

进阶阶段（2-4月）
├── 光照模型（Lambert → Blinn-Phong → PBR）
├── 法线贴图与切线空间
├── 透明与混合模式
└── 常见特效（描边/溶解/扭曲）

高级阶段（4-8月）
├── 自定义渲染管线（URP/HDRP）
├── ComputeShader（GPU 并行计算）
├── 屏幕空间效果（SSAO/SSR/景深）
└── 卡通渲染/NPR 风格化

专家阶段（8月+）
├── 自研渲染引擎 Shader 系统
├── 移动端 TBDR 架构优化
├── 光线追踪基础
└── 引擎 Shader 编译器原理
```

> 💡 **学习建议**：用 [ShaderToy](https://www.shadertoy.com) 练习纯片元 Shader，理解原理后再移植到游戏引擎。每天写一个小效果，一年后你的 Shader 能力会发生质变。
