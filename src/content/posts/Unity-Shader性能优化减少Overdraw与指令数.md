---
title: Unity Shader性能优化：减少Overdraw与指令数
published: 2026-03-31
description: 深度解析Unity Shader性能优化的核心技术，包含ALU指令优化（精度降级half/fixed）、纹理采样优化（减少采样次数/合并贴图）、分支优化（避免动态分支）、Early-Z优化（Alpha Test顺序）、Shader变体控制（减少编译组合爆炸），以及移动端Shader最佳实践清单。
tags: [Unity, Shader, GPU优化, 性能优化, 游戏开发]
category: 渲染技术
draft: false
---

## 一、Shader精度优化

```hlsl
// 移动端精度层级：
// float  = 32位（高精度，用于坐标/矩阵变换）
// half   = 16位（中精度，用于颜色/法线/UV）
// fixed  = 10位（低精度，用于0-1颜色值）

// ❌ 低效：所有计算都用float
half4 frag_bad(Varyings IN) : SV_Target
{
    float4 albedo = tex2D(_MainTex, IN.uv);  // UV可以用half
    float3 normal = normalize(IN.normal);     // 法线用half足够
    float lighting = dot(normal, _LightDir);
    return albedo * lighting;
}

// ✅ 优化：根据需要选择精度
half4 frag_good(Varyings IN) : SV_Target
{
    half4 albedo = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv); // half UV
    half3 normal = normalize(IN.normalWS);   // half法线
    half lighting = dot(normal, (half3)_LightDir);
    return albedo * lighting;
}
```

---

## 二、纹理采样优化

```hlsl
// ❌ 低效：多次分开采样
half4 frag_bad(Varyings IN) : SV_Target
{
    half4 albedo = SAMPLE_TEXTURE2D(_AlbedoTex, sampler_AlbedoTex, IN.uv);
    half spec = SAMPLE_TEXTURE2D(_SpecTex, sampler_SpecTex, IN.uv).r;
    half rough = SAMPLE_TEXTURE2D(_RoughTex, sampler_RoughTex, IN.uv).r;
    half ao = SAMPLE_TEXTURE2D(_AOTex, sampler_AOTex, IN.uv).r;
    // 4次纹理采样
    return albedo * ao;
}

// ✅ 优化：合并贴图（1张RGBA = 4张R通道）
// R=Metallic, G=Roughness, B=AO, A=Emissive Mask
Texture2D _PackedTex; // 打包贴图
half4 frag_good(Varyings IN) : SV_Target
{
    half4 albedo = SAMPLE_TEXTURE2D(_AlbedoTex, sampler_AlbedoTex, IN.uv);
    half4 packed = SAMPLE_TEXTURE2D(_PackedTex, sampler_PackedTex, IN.uv);
    
    half metallic = packed.r;
    half roughness = packed.g;
    half ao = packed.b;
    // 只需2次纹理采样
    return albedo * ao;
}
```

---

## 三、分支优化

```hlsl
// ❌ 动态分支（GPU并行执行时效率低）
half4 frag_bad(Varyings IN) : SV_Target
{
    if (_EnableRainEffect > 0.5)  // 动态分支
    {
        return ApplyRain(IN);
    }
    return ApplyNormal(IN);
}

// ✅ 静态分支（编译期决定，使用Keyword）
#pragma multi_compile _ RAIN_EFFECT_ON
half4 frag_good(Varyings IN) : SV_Target
{
    #ifdef RAIN_EFFECT_ON
    return ApplyRain(IN);
    #else
    return ApplyNormal(IN);
    #endif
}

// ✅ 数学替代分支（lerp消除if）
half4 frag_lerp(Varyings IN, float wetness) : SV_Target
{
    half4 dry = SampleDryColor(IN.uv);
    half4 wet = SampleWetColor(IN.uv);
    return lerp(dry, wet, wetness); // 无分支，GPU友好
}
```

---

## 四、移动端Shader最佳实践

```hlsl
// 移动端完整优化示例
Shader "Custom/MobileOptimized"
{
    Properties { _MainTex("Albedo", 2D) = "white" {} }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            // ✅ 移动端：明确声明精度以减少编译歧义
            #pragma target 2.0
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                half4 _Color;
            CBUFFER_END
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                half2 uv : TEXCOORD0;  // ✅ UV用half
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                half2 uv : TEXCOORD0;  // ✅ 插值用half
            };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                // ✅ 坐标变换用float（精度要求高）
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = TRANSFORM_TEX(IN.uv, _MainTex); // ✅ macro自动处理
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                // ✅ 颜色计算用half
                half4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                return color * _Color;
            }
            ENDHLSL
        }
    }
}
```

---

## 五、Shader优化检查清单

| 检查项 | 方案 |
|--------|------|
| UV插值精度 | 改用 half2 |
| 颜色计算精度 | 改用 half/fixed |
| 纹理数量 | 合并到打包贴图 |
| if分支 | 改用 lerp 或 #ifdef |
| pow/exp/log | 预计算或查表 |
| normalize | 仅必要时调用 |
| discard | 尽量避免（破坏Early-Z）|
