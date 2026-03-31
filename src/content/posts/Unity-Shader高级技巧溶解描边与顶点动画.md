---
title: Unity Shader高级技巧：溶解、描边与顶点动画
published: 2026-03-31
description: 深度解析Unity Shader的高级特效技术，包含噪声纹理溶解特效（Dissolve）实现、法线外扩描边（支持透明物体）、顶点动画（摆动草/飘动旗帜/水波纹）、UV滚动与扭曲效果、自定义深度写入，以及URP/HDRP的Shader兼容性处理方案。
tags: [Unity, Shader, 特效, 顶点动画, 渲染]
category: 渲染
draft: false
---

## 一、溶解特效 Shader

```hlsl
Shader "Custom/Dissolve"
{
    Properties
    {
        _MainTex ("Albedo", 2D) = "white" {}
        _DissolveTex ("Dissolve Noise", 2D) = "white" {}
        _DissolveAmount ("Dissolve Amount", Range(0, 1)) = 0
        _EdgeWidth ("Edge Width", Range(0, 0.2)) = 0.05
        _EdgeColor ("Edge Color", Color) = (1, 0.5, 0, 1)
        _EdgeEmission ("Edge Emission", Float) = 3.0
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
                float2 dissolveUV : TEXCOORD1;
                float3 normalWS : TEXCOORD2;
            };

            TEXTURE2D(_MainTex);    SAMPLER(sampler_MainTex);
            TEXTURE2D(_DissolveTex); SAMPLER(sampler_DissolveTex);

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float4 _DissolveTex_ST;
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
                OUT.dissolveUV = TRANSFORM_TEX(IN.uv, _DissolveTex);
                OUT.normalWS = TransformObjectToWorldNormal(IN.normalOS);
                return OUT;
            }

            half4 frag(Varyings IN) : SV_Target
            {
                half4 albedo = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                half dissolveNoise = SAMPLE_TEXTURE2D(_DissolveTex, sampler_DissolveTex, IN.dissolveUV).r;

                // 核心：噪声值小于阈值则裁剪（溶解消失）
                float clipValue = dissolveNoise - _DissolveAmount;
                clip(clipValue);

                // 边缘发光效果
                half edgeFactor = step(clipValue, _EdgeWidth);
                half edgeIntensity = (1.0 - clipValue / _EdgeWidth) * edgeFactor;

                // 简单光照
                Light mainLight = GetMainLight();
                half NdotL = saturate(dot(normalize(IN.normalWS), mainLight.direction));
                half3 lighting = mainLight.color * NdotL + 0.2; // 0.2 环境光

                half3 color = albedo.rgb * lighting;

                // 叠加边缘颜色（自发光）
                color += _EdgeColor.rgb * edgeIntensity * _EdgeEmission;

                return half4(color, 1.0);
            }
            ENDHLSL
        }
    }
}
```

---

## 二、法线外扩描边 Shader

```hlsl
Shader "Custom/Outline"
{
    Properties
    {
        _MainTex ("Main Texture", 2D) = "white" {}
        _OutlineColor ("Outline Color", Color) = (0, 0, 0, 1)
        _OutlineWidth ("Outline Width", Range(0, 0.1)) = 0.02
    }

    SubShader
    {
        Tags { "RenderType"="Opaque" }

        // Pass 1：先渲染描边（背面法线外扩）
        Pass
        {
            Name "OUTLINE"
            Cull Front   // 只渲染背面
            
            HLSLPROGRAM
            #pragma vertex vert_outline
            #pragma fragment frag_outline
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attributes { float4 pos : POSITION; float3 normal : NORMAL; };
            struct Varyings { float4 pos : SV_POSITION; };

            CBUFFER_START(UnityPerMaterial)
                float4 _OutlineColor;
                float _OutlineWidth;
                float4 _MainTex_ST;
            CBUFFER_END

            Varyings vert_outline(Attributes IN)
            {
                Varyings OUT;
                // 法线方向外扩顶点（裁剪空间，保证描边宽度与距离无关）
                float4 posCS = TransformObjectToHClip(IN.pos.xyz);
                float3 normalCS = mul((float3x3)UNITY_MATRIX_MVP, IN.normal);
                
                // 在裁剪空间沿法线方向偏移
                float2 offset = normalize(normalCS.xy) * _OutlineWidth;
                // 修正宽高比
                offset.x /= _ScreenParams.x / _ScreenParams.y;
                
                posCS.xy += offset * posCS.w;
                OUT.pos = posCS;
                return OUT;
            }

            half4 frag_outline(Varyings IN) : SV_Target
            {
                return _OutlineColor;
            }
            ENDHLSL
        }

        // Pass 2：渲染正面（正常材质）
        Pass
        {
            Name "MAIN"
            Cull Back

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            struct Attributes { float4 pos : POSITION; float2 uv : TEXCOORD0; float3 normal : NORMAL; };
            struct Varyings { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; float3 normalWS : TEXCOORD1; };

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float4 _OutlineColor;
                float _OutlineWidth;
            CBUFFER_END

            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.pos = TransformObjectToHClip(IN.pos.xyz);
                OUT.uv = TRANSFORM_TEX(IN.uv, _MainTex);
                OUT.normalWS = TransformObjectToWorldNormal(IN.normal);
                return OUT;
            }

            half4 frag(Varyings IN) : SV_Target
            {
                half4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                Light light = GetMainLight();
                half NdotL = saturate(dot(normalize(IN.normalWS), light.direction));
                return half4(color.rgb * (NdotL * 0.8 + 0.2), color.a);
            }
            ENDHLSL
        }
    }
}
```

---

## 三、顶点动画（摆动草/树）

```hlsl
Shader "Custom/GrassWind"
{
    Properties
    {
        _MainTex ("Texture", 2D) = "white" {}
        _WindSpeed ("Wind Speed", Float) = 1.0
        _WindStrength ("Wind Strength", Float) = 0.3
        _WindDirection ("Wind Direction", Vector) = (1, 0, 0.5, 0)
        [Toggle] _TopOnly ("Only Top Sways", Float) = 1
    }

    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "Queue"="AlphaTest" }
        Cull Off  // 草不剔除背面

        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #pragma shader_feature _TOPONLY_ON
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attributes
            {
                float4 posOS : POSITION;
                float2 uv : TEXCOORD0;
                float4 color : COLOR;  // 顶点色 R 通道作为摆动权重（底部=0，顶部=1）
            };

            struct Varyings
            {
                float4 posCS : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                float _WindSpeed;
                float _WindStrength;
                float4 _WindDirection;
                float _TopOnly;
            CBUFFER_END

            Varyings vert(Attributes IN)
            {
                Varyings OUT;

                // 摆动权重（顶点色R通道，底部固定，顶部摇摆）
                float sway = IN.color.r;

                // 世界空间位置（用于采样风场，让不同位置的草摆动不同步）
                float3 worldPos = TransformObjectToWorld(IN.posOS.xyz);

                // 正弦波模拟风
                float windTime = _Time.y * _WindSpeed;
                float wind = sin(windTime + worldPos.x * 0.5 + worldPos.z * 0.3);
                wind += sin(windTime * 1.7 + worldPos.x * 0.8) * 0.5;  // 高次谐波

                // 计算偏移
                float3 windDir = normalize(_WindDirection.xyz);
                float3 offset = windDir * wind * _WindStrength * sway;

                float3 finalPos = IN.posOS.xyz + offset;
                OUT.posCS = TransformObjectToHClip(finalPos);
                OUT.uv = TRANSFORM_TEX(IN.uv, _MainTex);
                return OUT;
            }

            half4 frag(Varyings IN) : SV_Target
            {
                half4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                clip(color.a - 0.5); // Alpha Test
                return color;
            }
            ENDHLSL
        }
    }
}
```

---

## 四、UV滚动（流动效果）

```hlsl
// UV 滚动片元 Shader 核心代码
float2 scrollUV = IN.uv + float2(_ScrollSpeedX, _ScrollSpeedY) * _Time.y;

// 扭曲效果（采样法线图偏移UV）
float2 distortion = SAMPLE_TEXTURE2D(_NoiseTex, sampler_NoiseTex, IN.uv * 0.5 + _Time.y * 0.1).rg;
distortion = (distortion - 0.5) * _DistortionStrength;
float2 distortedUV = IN.uv + distortion;
half4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, distortedUV);
```

---

## 五、Shader 性能注意事项

| 操作 | 开销 | 建议 |
|------|------|------|
| discard/clip | 高（禁止Early-Z）| 仅在必要时使用 |
| 采样纹理 | 中高 | 减少采样次数，合并通道 |
| 复杂数学函数 | 中 | 预计算，放到顶点着色器 |
| 动态分支 | 高（GPU不擅长分支）| 用 lerp/step 代替 if |
| 顶点动画 | 低（顶点着色器快）| 优先考虑顶点动画而非骨骼动画 |

**调试工具：**
- Frame Debugger：查看每个Pass的渲染效果
- RenderDoc：深度捕获单帧分析
- Shader Graph Blackboard：可视化调试参数
