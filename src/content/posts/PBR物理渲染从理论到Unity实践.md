---
title: "PBR物理渲染从理论到Unity实践"
description: "深入解析PBR（基于物理的渲染）核心理论，包括微表面模型、能量守恒、菲涅尔效应，以及在Unity URP中的完整实践指南"
published: 2025-03-21
tags: ["PBR", "渲染", "图形学", "Shader", "URP", "Unity"]
---

# PBR物理渲染从理论到Unity实践

> 《原神》《崩坏：星穹铁道》《明日方舟：终末地》——这些流水破百亿的游戏都基于Unity，都使用了深度定制的PBR渲染。掌握PBR是进入顶级游戏渲染领域的入场券。

---

## 一、为什么需要PBR？

### 1.1 传统Phong着色的问题

传统光照模型（Phong/Blinn-Phong）存在根本性缺陷：

```
Phong光照模型：
最终颜色 = 环境光 + 漫反射 * max(N·L, 0) + 镜面反射 * pow(max(N·H, 0), shininess)

问题一：参数没有物理意义
- "shininess" 是什么？ 100是光滑还是粗糙？
- 美术调参靠感觉，换光照环境就崩

问题二：能量不守恒
- 一个表面反射的光能可以大于接收的光能！
- 导致在强光下物体看起来"发光"

问题三：无法统一表现不同材质
- 金属和非金属的高光完全不同
- Phong模型很难正确表现金属感
```

### 1.2 PBR解决了什么

PBR（Physically Based Rendering）基于真实物理规律建立光照模型：

- **能量守恒**：反射光 ≤ 入射光
- **参数有物理意义**：Metallic（金属度）、Roughness（粗糙度）有明确含义
- **一致性**：相同材质在不同光照环境下表现一致

---

## 二、PBR核心理论

### 2.1 微表面（Microfacet）理论

从宏观看光滑的表面，在微观尺度上实际上是由无数微小镜面（microfacets）组成的。

```
粗糙度（Roughness）决定微表面的凹凸分布：

粗糙度 = 0.0（完全光滑）
▄▄▄▄▄▄▄▄▄▄▄  所有微表面朝向一致 → 锐利高光

粗糙度 = 0.5（半光滑）
▄▃▅▄▂▄▅▃▄▄  微表面方向有些分散 → 柔和高光

粗糙度 = 1.0（完全粗糙）
▅▁▄▆▂▅▁▃▆▄  微表面方向随机 → 漫反射为主
```

**渲染方程（The Rendering Equation）：**

$$L_o(p, \omega_o) = \int_{\Omega} (k_d \frac{c}{\pi} + k_s \frac{DFG}{4(\omega_o \cdot n)(\omega_i \cdot n)}) L_i(p, \omega_i) n \cdot \omega_i d\omega_i$$

这个积分表示：从某点 p 向观察方向 ωo 出射的光 = 来自半球各方向的入射光 × BRDF × 余弦项的积分

### 2.2 BRDF（双向反射分布函数）

BRDF = 漫反射项（Diffuse）+ 镜面反射项（Specular）

**漫反射部分（Lambertian）：**
```glsl
// 最简单的漫反射：光从各方向均匀散射
float3 diffuse = albedo / PI;
// 除以π是为了能量守恒
```

**镜面反射部分（Cook-Torrance BRDF）：**

由三个函数组成：
- **D**：法线分布函数（Normal Distribution Function）
- **F**：菲涅尔方程（Fresnel Equation）  
- **G**：几何遮蔽函数（Geometry Function）

### 2.3 法线分布函数 D（GGX/Trowbridge-Reitz）

```glsl
// GGX法线分布函数（最常用，有长尾高光，更真实）
float DistributionGGX(float NdotH, float roughness)
{
    float a = roughness * roughness; // 注意：使用粗糙度的平方
    float a2 = a * a;
    float NdotH2 = NdotH * NdotH;
    
    float num = a2;
    float denom = (NdotH2 * (a2 - 1.0) + 1.0);
    denom = PI * denom * denom;
    
    return num / denom;
}

// 物理含义：roughness=0时，D极大（几乎所有微表面对齐）
//           roughness=1时，D平坦（微表面随机分布）
```

### 2.4 菲涅尔效应 F

**关键洞察：** 你观察水面，直视时（视线垂直水面）能看到水下；斜视时（视线接近平行水面）水面变成镜子。

这就是菲涅尔效应——反射率随入射角变化。

```glsl
// Schlick近似公式（实时渲染常用近似）
float3 FresnelSchlick(float cosTheta, float3 F0)
{
    return F0 + (1.0 - F0) * pow(clamp(1.0 - cosTheta, 0.0, 1.0), 5.0);
}

// F0 = 0度入射角时的基础反射率
// 非金属（Dielectric）：F0 ≈ 0.04（约4%）
// 金属（Metallic）：F0由albedo决定（50-100%，各不相同）
float3 F0 = mix(float3(0.04), albedo, metallic);
```

### 2.5 几何遮蔽函数 G

微表面之间会相互遮挡（Shadow）和自遮挡（Masking），导致实际参与反射的微表面减少。

```glsl
float GeometrySchlickGGX(float NdotV, float roughness)
{
    float r = (roughness + 1.0);
    float k = (r * r) / 8.0; // 直接光照时的k值
    
    float num = NdotV;
    float denom = NdotV * (1.0 - k) + k;
    
    return num / denom;
}

// Smith方法：分别计算光照方向和视线方向的遮蔽，然后相乘
float GeometrySmith(float NdotV, float NdotL, float roughness)
{
    float ggx2 = GeometrySchlickGGX(NdotV, roughness);
    float ggx1 = GeometrySchlickGGX(NdotL, roughness);
    return ggx1 * ggx2;
}
```

---

## 三、PBR材质参数详解

### 3.1 标准PBR工作流

**金属/粗糙度工作流（Metal/Roughness Workflow）——Unity标准：**

| 贴图 | 通道 | 含义 |
|------|------|------|
| Albedo | RGB | 基础颜色（金属时是F0，非金属时是漫反射颜色） |
| Metallic | R | 金属度（0=非金属，1=金属） |
| Roughness | G | 粗糙度（0=光滑，1=粗糙） |
| Normal | RGB | 法线贴图 |
| AO | R | 环境光遮蔽 |
| Emission | RGB | 自发光颜色 |

**高光/光泽度工作流（Specular/Glossiness Workflow）——Substance Painter原生：**

```
Albedo → 漫反射颜色
Specular → 镜面反射颜色（直接控制F0）
Glossiness = 1 - Roughness
```

### 3.2 金属与非金属的根本区别

```
非金属（塑料、木头、皮肤等）：
- 漫反射：强（albedo决定颜色）
- 镜面高光：弱，白色（约4%反射率）
- F0 = 约0.04

金属（铁、金、铜等）：
- 漫反射：几乎为零（金属吸收折射光）
- 镜面高光：强，有颜色！
- F0 = albedo（金：[1.0, 0.86, 0.57]）
```

**为什么金属高光有颜色？** 金属表面自由电子的振动频率会有选择地吸收不同波长，导致反射光有颜色（金反射橙黄色）。

---

## 四、Unity中的PBR Shader实现

### 4.1 URP中的完整PBR Shader

```hlsl
Shader "Custom/PBRLit"
{
    Properties
    {
        _Albedo ("Albedo", 2D) = "white" {}
        _AlbedoColor ("Albedo Color", Color) = (1,1,1,1)
        _MetallicMap ("Metallic (R) Roughness (G)", 2D) = "white" {}
        _Metallic ("Metallic", Range(0,1)) = 0.0
        _Roughness ("Roughness", Range(0,1)) = 0.5
        _NormalMap ("Normal Map", 2D) = "bump" {}
        _NormalStrength ("Normal Strength", Float) = 1.0
        _AOMap ("Ambient Occlusion", 2D) = "white" {}
        _EmissionMap ("Emission", 2D) = "black" {}
        _EmissionColor ("Emission Color", Color) = (0,0,0,0)
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }
        
        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode"="UniversalForward" }
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            // URP关键字
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile _ _ADDITIONAL_LIGHTS_VERTEX _ADDITIONAL_LIGHTS
            #pragma multi_compile_fog
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            TEXTURE2D(_Albedo); SAMPLER(sampler_Albedo);
            TEXTURE2D(_MetallicMap); SAMPLER(sampler_MetallicMap);
            TEXTURE2D(_NormalMap); SAMPLER(sampler_NormalMap);
            TEXTURE2D(_AOMap); SAMPLER(sampler_AOMap);
            TEXTURE2D(_EmissionMap); SAMPLER(sampler_EmissionMap);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _Albedo_ST;
                float4 _AlbedoColor;
                float _Metallic;
                float _Roughness;
                float _NormalStrength;
                float4 _EmissionColor;
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
            
            Varyings vert(Attributes input)
            {
                Varyings output;
                
                VertexPositionInputs positionInputs = GetVertexPositionInputs(input.positionOS.xyz);
                VertexNormalInputs normalInputs = GetVertexNormalInputs(input.normalOS, input.tangentOS);
                
                output.positionCS = positionInputs.positionCS;
                output.positionWS = positionInputs.positionWS;
                output.uv = TRANSFORM_TEX(input.uv, _Albedo);
                output.normalWS = normalInputs.normalWS;
                output.tangentWS = normalInputs.tangentWS;
                output.bitangentWS = normalInputs.bitangentWS;
                
                return output;
            }
            
            // ===== PBR核心函数 =====
            
            float DistributionGGX(float NdotH, float roughness)
            {
                float a = roughness * roughness;
                float a2 = a * a;
                float NdotH2 = NdotH * NdotH;
                float denom = NdotH2 * (a2 - 1.0) + 1.0;
                return a2 / (PI * denom * denom);
            }
            
            float GeometrySchlickGGX(float NdotV, float roughness)
            {
                float r = roughness + 1.0;
                float k = (r * r) / 8.0;
                return NdotV / (NdotV * (1.0 - k) + k);
            }
            
            float GeometrySmith(float NdotV, float NdotL, float roughness)
            {
                return GeometrySchlickGGX(NdotV, roughness) * 
                       GeometrySchlickGGX(NdotL, roughness);
            }
            
            float3 FresnelSchlick(float cosTheta, float3 F0)
            {
                return F0 + (1.0 - F0) * pow(max(1.0 - cosTheta, 0.0), 5.0);
            }
            
            float3 CookTorranceBRDF(float3 N, float3 V, float3 L, 
                                    float3 albedo, float metallic, float roughness)
            {
                float3 H = normalize(V + L);
                
                float NdotV = max(dot(N, V), 0.0001);
                float NdotL = max(dot(N, L), 0.0001);
                float NdotH = max(dot(N, H), 0.0);
                float HdotV = max(dot(H, V), 0.0);
                
                // F0：基础反射率
                float3 F0 = lerp(float3(0.04, 0.04, 0.04), albedo, metallic);
                
                // Cook-Torrance镜面反射
                float D = DistributionGGX(NdotH, roughness);
                float3 F = FresnelSchlick(HdotV, F0);
                float G = GeometrySmith(NdotV, NdotL, roughness);
                
                float3 numerator = D * F * G;
                float denominator = 4.0 * NdotV * NdotL;
                float3 specular = numerator / max(denominator, 0.0001);
                
                // 能量守恒：kS = F（镜面反射分量）
                float3 kS = F;
                // kD = 1 - kS，且金属没有漫反射
                float3 kD = (1.0 - kS) * (1.0 - metallic);
                
                float3 diffuse = kD * albedo / PI;
                
                return (diffuse + specular) * NdotL;
            }
            
            float4 frag(Varyings input) : SV_Target
            {
                float2 uv = input.uv;
                
                // 采样贴图
                float3 albedo = SAMPLE_TEXTURE2D(_Albedo, sampler_Albedo, uv).rgb 
                                * _AlbedoColor.rgb;
                float2 mrSample = SAMPLE_TEXTURE2D(_MetallicMap, sampler_MetallicMap, uv).rg;
                float metallic = mrSample.r * _Metallic;
                float roughness = mrSample.g * _Roughness;
                float ao = SAMPLE_TEXTURE2D(_AOMap, sampler_AOMap, uv).r;
                
                // 法线贴图
                float3 normalTS = UnpackNormalScale(
                    SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, uv), _NormalStrength);
                float3x3 TBN = float3x3(
                    normalize(input.tangentWS),
                    normalize(input.bitangentWS),
                    normalize(input.normalWS)
                );
                float3 N = normalize(mul(normalTS, TBN));
                float3 V = normalize(GetCameraPositionWS() - input.positionWS);
                
                // 主光源
                Light mainLight = GetMainLight(TransformWorldToShadowCoord(input.positionWS));
                float3 L = normalize(mainLight.direction);
                float3 lightColor = mainLight.color * mainLight.shadowAttenuation;
                
                // PBR计算
                float3 color = CookTorranceBRDF(N, V, L, albedo, metallic, roughness) 
                               * lightColor;
                
                // 环境光（简化处理）
                float3 ambient = 0.03 * albedo * ao;
                color += ambient;
                
                // 自发光
                float3 emission = SAMPLE_TEXTURE2D(_EmissionMap, sampler_EmissionMap, uv).rgb 
                                  * _EmissionColor.rgb;
                color += emission;
                
                return float4(color, 1.0);
            }
            
            ENDHLSL
        }
    }
}
```

---

## 五、风格化PBR（卡通渲染与PBR融合）

### 5.1 《原神》风格化渲染分析

《原神》是PBR + NPR（非真实感渲染）融合的典范：

```
原神渲染策略：
- 基础：PBR材质体系（保证物理一致性）
- 卡通化：离散化光照（把连续光照分成几个色阶）
- 边缘光：轮廓线增强角色立体感
- 面部特殊处理：SDF（有向距离场）面部阴影
```

**离散化光照（Cel Shading）实现：**

```hlsl
// 传统PBR的漫反射是连续渐变的
// 卡通渲染需要分段阶梯化
float3 CelShading(float NdotL, float3 albedo, float3 shadowColor)
{
    // 使用阶梯函数离散化
    // step(0.5, NdotL) → 0或1，两色阶
    // smoothstep(0.45, 0.55, NdotL) → 带边缘柔化的两色阶
    float toonFactor = smoothstep(0.45, 0.55, NdotL);
    
    return lerp(shadowColor * albedo, albedo, toonFactor);
}

// 更精细的多色阶
float3 MultiStepCelShading(float NdotL, float3 albedo)
{
    // 使用渐变图（1D纹理）来控制色阶
    float toonValue = SAMPLE_TEXTURE2D(_RampTex, sampler_RampTex, float2(NdotL * 0.5 + 0.5, 0)).r;
    return albedo * toonValue;
}
```

**SDF面部阴影（防止面部阴影破碎）：**

```hlsl
// 普通法线计算在面部会产生丑陋的阴影
// SDF方案：预计算从各角度看的阴影形状，存入贴图

float GetFaceShadow(float2 uv, float3 lightDir, float3 faceForward, float3 faceRight)
{
    float lightAngle = atan2(dot(lightDir, faceRight), dot(lightDir, faceForward));
    lightAngle = lightAngle * (1.0 / (2.0 * PI)) + 0.5; // 映射到[0,1]
    
    float sdfValue = SAMPLE_TEXTURE2D(_FaceShadowSDF, sampler_FaceShadowSDF, uv).r;
    
    // SDF值大于当前角度→亮，否则→暗
    return step(lightAngle, sdfValue);
}
```

---

## 六、IBL（基于图像的照明）

### 6.1 为什么需要IBL

直接光照（方向光、点光源）只能模拟一部分光照。真实场景中，物体受到来自四面八方的环境光照射。

IBL通过将环境全景图（Cubemap/HDRI）解码为光照信息，实现真实的环境光照。

### 6.2 IBL分为两部分

**漫反射IBL（irradiance map）：**
```hlsl
// 预计算：对半球面积分，存储为低分辨率irradiance贴图
// 使用：采样与法线方向对应的irradiance
float3 irradiance = SAMPLE_TEXTURECUBE(_IrradianceMap, sampler_IrradianceMap, N).rgb;
float3 diffuseIBL = irradiance * albedo;
```

**镜面IBL（prefiltered map + BRDF LUT）：**
```hlsl
// 使用Split Sum近似（Brian Karis, Epic Games）
// 预计算：不同粗糙度下的环境map（prefiltered map）
// 预计算：BRDF积分（LUT贴图）

// 运行时采样
float3 R = reflect(-V, N);
float3 prefilteredColor = SAMPLE_TEXTURECUBE_LOD(
    _PrefilteredMap, sampler_PrefilteredMap, R, roughness * MAX_REFLECTION_LOD).rgb;

float2 brdfLUT = SAMPLE_TEXTURE2D(_BRDFLut, sampler_BRDFLut, 
                                   float2(max(dot(N, V), 0.0), roughness)).rg;

float3 specularIBL = prefilteredColor * (F0 * brdfLUT.x + brdfLUT.y);
```

---

## 七、移动端PBR优化策略

### 7.1 性能vs质量平衡

移动端GPU算力有限，PBR需要做合理简化：

```hlsl
// PC端完整PBR：
// - 精确的多光源计算
// - 完整IBL（irradiance + prefiltered）
// - SSR（屏幕空间反射）
// - SSAO（屏幕空间环境光遮蔽）

// 移动端优化PBR（保留80%视觉效果）：
// 1. 使用MobileBlinnPhong代替完整GGX（低端设备）
// 2. 减少实时光源数量（主光源+1-2个附加光源）
// 3. 使用低分辨率IBL（32x32 irradiance, 128x128 prefiltered）
// 4. AO使用烘焙贴图代替SSAO
// 5. 反射使用Reflection Probe代替SSR
```

**适配不同性能层级：**

```csharp
// 根据设备等级动态切换着色器变体
public enum GraphicsQuality { Low, Medium, High, Ultra }

void ApplyQualitySettings(GraphicsQuality quality)
{
    switch (quality)
    {
        case GraphicsQuality.Low:
            Shader.EnableKeyword("PBR_QUALITY_LOW");
            // 使用简化Blinn-Phong
            break;
        case GraphicsQuality.Medium:
            Shader.EnableKeyword("PBR_QUALITY_MEDIUM");
            // 使用GGX但无IBL
            break;
        case GraphicsQuality.High:
            Shader.EnableKeyword("PBR_QUALITY_HIGH");
            // 完整PBR + IBL
            break;
        case GraphicsQuality.Ultra:
            Shader.EnableKeyword("PBR_QUALITY_ULTRA");
            // 完整PBR + IBL + SSR + SSAO
            break;
    }
}
```

---

## 八、面试必考问题

### Q1：PBR和Phong有什么根本区别？

**答：** 
1. **物理基础**：PBR基于真实物理（微表面理论、能量守恒），Phong是经验公式
2. **能量守恒**：PBR严格保证，Phong不保证
3. **参数意义**：PBR参数（Metallic/Roughness）有明确物理含义，Phong的shininess是魔法数字
4. **一致性**：PBR在不同光照环境下表现一致，Phong需要针对每个场景重新调整

### Q2：菲涅尔效应在游戏中的应用？

**答：**
1. 边缘光效果（Rim Light）：模拟菲涅尔让角色轮廓发光
2. 水面渲染：斜看水面变镜面，垂直看透明
3. 玻璃/冰面材质
4. 卡通渲染的边缘光增强

### Q3：什么情况下用HDR渲染？

**答：** HDR（高动态范围）渲染允许颜色值超过1.0，与Tone Mapping配合：
- 允许物理正确的高亮度光源
- Bloom等后处理效果在HDR下更真实
- 代价：需要F16/F32帧缓冲，内存和带宽翻倍

---

## 总结

PBR是现代游戏渲染的基础：
1. **理解原理**：微表面、能量守恒、菲涅尔——这些不是公式，是物理直觉
2. **实践能力**：能写出完整PBR Shader，能在URP中集成
3. **工程判断**：知道在什么设备上做什么程度的简化
4. **视觉敏感度**：能判断材质是否物理正确

作为技术负责人，你还需要：建立项目的材质规范，培训美术同学理解PBR参数的物理含义，确保全项目材质的一致性。
