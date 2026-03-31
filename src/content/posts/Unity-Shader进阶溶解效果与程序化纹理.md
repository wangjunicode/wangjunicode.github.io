---
title: Unity Shader进阶：溶解效果与程序化纹理
published: 2026-03-31
description: 深度解析Unity Shader的进阶技法，包含溶解效果（Dissolve）的完整实现（噪声纹理+Clip+发光边缘）、角色受击白化效果、隐形渐变（Dithering透明）、程序化纹理生成（Voronoi/FBM噪声）、Shader中的UV动画（流动/旋转/扰动），以及URP中的自定义Lit Shader扩展方案。
tags: [Unity, Shader, 溶解效果, 程序化纹理, 图形学]
category: 渲染技术
draft: false
---

## 一、溶解效果 Shader

```hlsl
Shader "Custom/Dissolve"
{
    Properties
    {
        _MainTex ("主纹理", 2D) = "white" {}
        _NoiseTex ("噪声纹理", 2D) = "white" {}
        _DissolveAmount ("溶解进度", Range(0, 1)) = 0
        _EdgeWidth ("边缘宽度", Range(0, 0.1)) = 0.05
        _EdgeColor ("边缘颜色", Color) = (1, 0.5, 0, 1)
        _EdgeEmission ("边缘发光强度", Range(1, 10)) = 3
    }
    
    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "Queue"="AlphaTest" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                float3 normalOS : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 normalWS : TEXCOORD1;
            };
            
            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            TEXTURE2D(_NoiseTex); SAMPLER(sampler_NoiseTex);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float _DissolveAmount;
                float _EdgeWidth;
                float4 _EdgeColor;
                float _EdgeEmission;
            CBUFFER_END
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = TRANSFORM_TEX(IN.uv, _MainTex);
                OUT.normalWS = TransformObjectToWorldNormal(IN.normalOS);
                return OUT;
            }
            
            float4 frag(Varyings IN) : SV_Target
            {
                // 采样噪声纹理
                float noise = SAMPLE_TEXTURE2D(_NoiseTex, sampler_NoiseTex, IN.uv).r;
                
                // 溶解裁切
                float dissolveEdge = noise - _DissolveAmount;
                clip(dissolveEdge); // < 0 则丢弃片段
                
                // 边缘发光
                float edgeFactor = saturate(dissolveEdge / _EdgeWidth);
                
                // 主色
                float4 mainColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                
                // 简单漫反射光照
                Light light = GetMainLight();
                float NdotL = saturate(dot(IN.normalWS, light.direction));
                mainColor.rgb *= light.color * (NdotL * 0.7 + 0.3);
                
                // 边缘颜色叠加
                float3 edgeGlow = _EdgeColor.rgb * _EdgeEmission * (1.0 - edgeFactor);
                mainColor.rgb += edgeGlow;
                
                return mainColor;
            }
            ENDHLSL
        }
    }
}
```

---

## 二、受击白化 Shader

```hlsl
Shader "Custom/HitFlash"
{
    Properties
    {
        _MainTex ("主纹理", 2D) = "white" {}
        _FlashAmount ("白化程度", Range(0, 1)) = 0
        _FlashColor ("闪光颜色", Color) = (1, 1, 1, 1)
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            
            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float _FlashAmount;
                float4 _FlashColor;
            CBUFFER_END
            
            struct Attributes { float4 positionOS : POSITION; float2 uv : TEXCOORD0; };
            struct Varyings { float4 positionCS : SV_POSITION; float2 uv : TEXCOORD0; };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = TRANSFORM_TEX(IN.uv, _MainTex);
                return OUT;
            }
            
            float4 frag(Varyings IN) : SV_Target
            {
                float4 mainColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                // 向白色/指定颜色插值
                mainColor.rgb = lerp(mainColor.rgb, _FlashColor.rgb, _FlashAmount);
                return mainColor;
            }
            ENDHLSL
        }
    }
}
```

---

## 三、程序化溶解控制器

```csharp
using System.Collections;
using UnityEngine;

/// <summary>
/// 溶解效果控制器（运行时控制Shader参数）
/// </summary>
public class DissolveController : MonoBehaviour
{
    [SerializeField] private Renderer targetRenderer;
    [SerializeField] private float dissolveDuration = 1.5f;
    
    private MaterialPropertyBlock propertyBlock;
    private static readonly int DissolveAmountId = Shader.PropertyToID("_DissolveAmount");

    void Awake()
    {
        propertyBlock = new MaterialPropertyBlock();
    }

    /// <summary>
    /// 开始溶解效果
    /// </summary>
    public Coroutine StartDissolve(bool dissolveIn = false, 
        System.Action onComplete = null)
    {
        return StartCoroutine(DissolveCoroutine(dissolveIn, onComplete));
    }

    IEnumerator DissolveCoroutine(bool dissolveIn, System.Action onComplete)
    {
        float start = dissolveIn ? 1f : 0f;
        float end = dissolveIn ? 0f : 1f;
        float t = 0;
        
        while (t < dissolveDuration)
        {
            t += Time.deltaTime;
            float progress = t / dissolveDuration;
            
            // 使用EaseInOut曲线
            float easedProgress = progress < 0.5f 
                ? 2f * progress * progress 
                : 1f - Mathf.Pow(-2f * progress + 2f, 2f) / 2f;
            
            float dissolveAmount = Mathf.Lerp(start, end, easedProgress);
            
            // 使用 MaterialPropertyBlock 避免生成新材质实例
            targetRenderer.GetPropertyBlock(propertyBlock);
            propertyBlock.SetFloat(DissolveAmountId, dissolveAmount);
            targetRenderer.SetPropertyBlock(propertyBlock);
            
            yield return null;
        }
        
        // 确保最终值
        targetRenderer.GetPropertyBlock(propertyBlock);
        propertyBlock.SetFloat(DissolveAmountId, end);
        targetRenderer.SetPropertyBlock(propertyBlock);
        
        onComplete?.Invoke();
    }
}

/// <summary>
/// 受击白化控制器
/// </summary>
public class HitFlashController : MonoBehaviour
{
    [SerializeField] private Renderer targetRenderer;
    [SerializeField] private float flashDuration = 0.15f;
    
    private MaterialPropertyBlock propertyBlock;
    private static readonly int FlashAmountId = Shader.PropertyToID("_FlashAmount");
    private Coroutine flashCoroutine;

    void Awake() { propertyBlock = new MaterialPropertyBlock(); }

    public void TriggerFlash()
    {
        if (flashCoroutine != null)
            StopCoroutine(flashCoroutine);
        flashCoroutine = StartCoroutine(FlashCoroutine());
    }

    IEnumerator FlashCoroutine()
    {
        float t = 0;
        while (t < flashDuration)
        {
            t += Time.deltaTime;
            float flash = 1f - (t / flashDuration); // 从1到0
            
            targetRenderer.GetPropertyBlock(propertyBlock);
            propertyBlock.SetFloat(FlashAmountId, flash);
            targetRenderer.SetPropertyBlock(propertyBlock);
            
            yield return null;
        }
        
        targetRenderer.GetPropertyBlock(propertyBlock);
        propertyBlock.SetFloat(FlashAmountId, 0f);
        targetRenderer.SetPropertyBlock(propertyBlock);
    }
}
```

---

## 四、UV动画 Shader

```hlsl
// UV流动效果（用于流水/熔岩等）
float4 frag_flow(Varyings IN) : SV_Target
{
    // 基础UV流动
    float2 flowUV = IN.uv + float2(_Time.y * 0.1, _Time.y * 0.05);
    
    // 噪声扰动UV（让流动不那么规则）
    float2 noise = SAMPLE_TEXTURE2D(_NoiseTex, sampler_NoiseTex, IN.uv * 0.5).rg;
    noise = noise * 2.0 - 1.0; // 重映射到 -1~1
    flowUV += noise * 0.05;
    
    return SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, flowUV);
}
```

---

## 五、Shader效果最佳实践

| 技巧 | 说明 |
|------|------|
| MaterialPropertyBlock | 修改Shader参数时不破坏合批 |
| clip() vs Alpha Blend | 溶解用clip性能更好（Early-Z生效）|
| 噪声贴图 | 预生成灰度噪声贴图，运行时采样 |
| CBUFFER | 所有材质参数放进CBUFFER（SRP Batcher要求）|
| 避免tex2D | URP中用SAMPLE_TEXTURE2D宏 |
