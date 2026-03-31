---
title: Unity Shader编写进阶：自定义光照模型实现
published: 2026-03-31
description: 深入解析Unity Shader中自定义光照模型的实现，包括PBR（基于物理的渲染）原理详解、Cook-Torrance BRDF推导与实现、各向异性高光（头发/拉丝金属）、次表面散射（SSS皮肤）、URP自定义光照Shader完整代码，以及在ShaderGraph中实现自定义光照节点。
tags: [Unity, Shader, 光照模型, PBR, 渲染技术]
category: 渲染与特效
draft: false
---

## 一、PBR 光照原理

```
PBR 渲染方程（简化版）：

L_out = ∫ [f_diffuse + f_specular] × L_in × cos(θ) dω

其中：
f_diffuse = albedo / π  （Lambert漫反射）
f_specular = D × F × G / (4 × NdotL × NdotV)  （Cook-Torrance）

D = 法线分布函数（GGX/Trowbridge-Reitz）—— 微表面分布
F = 菲涅尔方程（Schlick近似）—— 反射率
G = 几何遮蔽函数（Smith GGX）—— 自遮蔽
```

---

## 二、自定义 PBR Shader（URP）

```hlsl
Shader "Custom/PBR_Custom"
{
    Properties
    {
        _BaseColor    ("Base Color", Color) = (1, 1, 1, 1)
        _BaseMap      ("Base Map", 2D) = "white" {}
        _NormalMap    ("Normal Map", 2D) = "bump" {}
        _Metallic     ("Metallic", Range(0, 1)) = 0.0
        _Smoothness   ("Smoothness", Range(0, 1)) = 0.5
        _AoMap        ("AO Map", 2D) = "white" {}
        
        [Header(Emissive)]
        _EmissiveColor ("Emissive Color", Color) = (0, 0, 0, 1)
        _EmissiveStrength ("Emissive Strength", Float) = 1.0
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
            
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS
            #pragma multi_compile _ _SHADOWS_SOFT
            #pragma multi_compile_fog
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseColor;
                float4 _BaseMap_ST;
                float  _Metallic;
                float  _Smoothness;
                float4 _EmissiveColor;
                float  _EmissiveStrength;
            CBUFFER_END
            
            TEXTURE2D(_BaseMap);    SAMPLER(sampler_BaseMap);
            TEXTURE2D(_NormalMap);  SAMPLER(sampler_NormalMap);
            TEXTURE2D(_AoMap);      SAMPLER(sampler_AoMap);
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float4 tangentOS  : TANGENT;
                float2 uv         : TEXCOORD0;
            };
            
            struct Varyings
            {
                float4 positionHCS : SV_POSITION;
                float2 uv          : TEXCOORD0;
                float3 positionWS  : TEXCOORD1;
                float3 normalWS    : TEXCOORD2;
                float4 tangentWS   : TEXCOORD3;
                float4 shadowCoord : TEXCOORD4;
                float  fogFactor   : TEXCOORD5;
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                
                VertexPositionInputs posInputs = GetVertexPositionInputs(IN.positionOS.xyz);
                VertexNormalInputs normalInputs = GetVertexNormalInputs(IN.normalOS, IN.tangentOS);
                
                OUT.positionHCS = posInputs.positionCS;
                OUT.positionWS  = posInputs.positionWS;
                OUT.uv          = TRANSFORM_TEX(IN.uv, _BaseMap);
                OUT.normalWS    = normalInputs.normalWS;
                OUT.tangentWS   = float4(normalInputs.tangentWS, IN.tangentOS.w);
                OUT.shadowCoord = GetShadowCoord(posInputs);
                OUT.fogFactor   = ComputeFogFactor(posInputs.positionCS.z);
                
                return OUT;
            }
            
            // ============ 自定义 PBR 光照函数 ============
            
            float DistributionGGX(float3 N, float3 H, float roughness)
            {
                float a = roughness * roughness;
                float a2 = a * a;
                float NdotH = max(dot(N, H), 0.0);
                float NdotH2 = NdotH * NdotH;
                
                float num = a2;
                float denom = NdotH2 * (a2 - 1.0) + 1.0;
                denom = PI * denom * denom;
                
                return num / max(denom, 0.0001);
            }
            
            float GeometrySmith(float NdotV, float NdotL, float roughness)
            {
                float r = roughness + 1.0;
                float k = (r * r) / 8.0;
                
                float ggx1 = NdotV / (NdotV * (1.0 - k) + k);
                float ggx2 = NdotL / (NdotL * (1.0 - k) + k);
                
                return ggx1 * ggx2;
            }
            
            float3 FresnelSchlick(float cosTheta, float3 F0)
            {
                return F0 + (1.0 - F0) * pow(1.0 - cosTheta, 5.0);
            }
            
            float3 CookTorranceBRDF(float3 N, float3 V, float3 L, 
                float3 albedo, float metallic, float roughness)
            {
                float3 H = normalize(V + L);
                float NdotV = max(dot(N, V), 0.001);
                float NdotL = max(dot(N, L), 0.001);
                float HdotV = max(dot(H, V), 0.0);
                
                // 菲涅尔基础反射率（电介质0.04，金属使用albedo）
                float3 F0 = lerp(float3(0.04, 0.04, 0.04), albedo, metallic);
                
                // 法线分布
                float D = DistributionGGX(N, H, roughness);
                // 几何遮蔽
                float G = GeometrySmith(NdotV, NdotL, roughness);
                // 菲涅尔
                float3 F = FresnelSchlick(HdotV, F0);
                
                // 镜面反射
                float3 specular = D * G * F / (4.0 * NdotV * NdotL);
                
                // 漫反射（能量守恒：金属没有漫反射）
                float3 kD = (1.0 - F) * (1.0 - metallic);
                float3 diffuse = kD * albedo / PI;
                
                return (diffuse + specular) * NdotL;
            }
            
            float4 frag(Varyings IN) : SV_Target
            {
                // 采样贴图
                float4 baseColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, IN.uv) * _BaseColor;
                float3 normalTS = UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, IN.uv));
                float ao = SAMPLE_TEXTURE2D(_AoMap, sampler_AoMap, IN.uv).r;
                
                // 切线空间法线转世界空间
                float3 bitangent = IN.tangentWS.w * cross(IN.normalWS, IN.tangentWS.xyz);
                float3x3 TBN = float3x3(IN.tangentWS.xyz, bitangent, IN.normalWS);
                float3 N = normalize(mul(normalTS, TBN));
                
                float3 V = normalize(GetCameraPositionWS() - IN.positionWS);
                float roughness = 1.0 - _Smoothness;
                
                // 获取主光源
                Light mainLight = GetMainLight(IN.shadowCoord);
                float3 L = mainLight.direction;
                float shadowAtten = mainLight.shadowAttenuation;
                
                // PBR 光照计算
                float3 color = CookTorranceBRDF(N, V, L, baseColor.rgb, _Metallic, roughness);
                color *= mainLight.color * shadowAtten;
                
                // 环境光（AO）
                color += baseColor.rgb * unity_AmbientSky.rgb * 0.1 * ao;
                
                // 自发光
                color += _EmissiveColor.rgb * _EmissiveStrength;
                
                // 雾效
                color = MixFog(color, IN.fogFactor);
                
                return float4(color, baseColor.a);
            }
            ENDHLSL
        }
    }
}
```

---

## 三、各向异性高光（头发 Shader）

```hlsl
// Kajiya-Kay 头发光照模型（片段）

float3 KajiyaKaySpecular(float3 T, float3 V, float3 L, float shiftAmount, float specPower)
{
    // T: 切线方向（头发生长方向）
    // shiftAmount: 高光偏移（沿切线偏移模拟微结构）
    
    float3 shiftedT = normalize(T + shiftAmount * cross(T, float3(0, 1, 0)));
    
    float TdotH = dot(shiftedT, normalize(L + V));
    float sinTH = sqrt(1.0 - TdotH * TdotH);
    
    return pow(sinTH, specPower) * float3(1, 1, 1);
}
```

---

## 四、光照模型选型

| 模型 | 适用材质 | 复杂度 | 真实感 |
|------|----------|--------|--------|
| Lambert | 卡通/扁平化 | ★ | ★ |
| Phong/Blinn-Phong | 次时代移动端 | ★★ | ★★ |
| GGX PBR | 写实材质 | ★★★ | ★★★★ |
| Kajiya-Kay | 头发/毛发 | ★★★ | ★★★★ |
| SSS | 皮肤/蜡烛/玉石 | ★★★★ | ★★★★★ |
| Disney BRDF | 各类材质（电影级）| ★★★★★ | ★★★★★ |
