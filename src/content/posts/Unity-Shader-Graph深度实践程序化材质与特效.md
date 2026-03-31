---
title: Unity Shader Graph深度实践：程序化材质与特效制作
published: 2026-03-31
description: 深入掌握 Unity Shader Graph 的核心节点与高级用法，涵盖 PBR 材质制作、溶解/扫光/描边效果、顶点动画、交互水波纹、UV流动特效，以及 Shader Graph 与手写 HLSL 的性能对比与混合使用方案。
tags: [Unity, Shader Graph, 特效, 材质, URP]
category: 渲染技术
draft: false
---

## 一、Shader Graph 核心节点速查

### 1.1 常用数学节点

| 节点 | 功能 | 常见用法 |
|------|------|----------|
| Lerp | 线性插值 | 颜色混合、过渡效果 |
| Smoothstep | 平滑阶梯 | 软边遮罩、软阴影边缘 |
| Remap | 重映射数值范围 | 将 [-1,1] 转换到 [0,1] |
| Step | 阶梯函数 | 硬边遮罩、描边 |
| Fresnel Effect | 菲涅尔 | 边缘发光、玻璃效果 |
| Noise (Gradient/Simple) | 噪声 | 火焰、云朵、溶解 |
| Voronoi | 泰森多边形噪声 | 泡泡、破碎效果 |

### 1.2 UV 操作节点

```hlsl
// Shader Graph 等效手写代码

// Tiling & Offset（等效节点）
float2 TiledUV(float2 uv, float2 tiling, float2 offset)
{
    return uv * tiling + offset;
}

// UV流动（随时间滚动）
float2 FlowUV(float2 uv, float2 flowDir, float speed)
{
    return uv + flowDir * _Time.y * speed;
}

// UV扭曲（用噪声扭曲UV）
float2 DistortUV(float2 uv, sampler2D noiseTex, float strength)
{
    float2 noise = tex2D(noiseTex, uv).rg * 2.0 - 1.0;
    return uv + noise * strength;
}
```

---

## 二、溶解（Dissolve）效果

```hlsl
// 溶解 Shader（Shader Graph 等效 HLSL）
Shader "Custom/Dissolve"
{
    Properties
    {
        _MainTex ("Main Texture", 2D) = "white" {}
        _NoiseTex ("Noise Texture", 2D) = "white" {}
        _DissolveAmount ("Dissolve Amount", Range(0,1)) = 0
        _EdgeWidth ("Edge Width", Range(0, 0.1)) = 0.05
        _EdgeColor ("Edge Color", Color) = (1, 0.5, 0, 1)
        _EdgeEmission ("Edge Emission", Range(0, 5)) = 2
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
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                float3 normalOS : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionHCS : SV_POSITION;
                float2 uv : TEXCOORD0;
                float3 worldNormal : TEXCOORD1;
            };
            
            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            TEXTURE2D(_NoiseTex); SAMPLER(sampler_NoiseTex);
            float _DissolveAmount;
            float _EdgeWidth;
            float4 _EdgeColor;
            float _EdgeEmission;
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionHCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = IN.uv;
                OUT.worldNormal = TransformObjectToWorldNormal(IN.normalOS);
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                // 采样噪声纹理
                float noise = SAMPLE_TEXTURE2D(_NoiseTex, sampler_NoiseTex, IN.uv).r;
                
                // 溶解裁剪（噪声值 < 溶解量时丢弃）
                float dissolveValue = noise - _DissolveAmount;
                clip(dissolveValue);
                
                // 边缘发光效果
                float edge = step(dissolveValue, _EdgeWidth);
                float edgeIntensity = (1.0 - dissolveValue / _EdgeWidth) * edge;
                
                // 采样主纹理
                half4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                
                // 叠加边缘颜色
                color.rgb += _EdgeColor.rgb * edgeIntensity * _EdgeEmission;
                
                return color;
            }
            ENDHLSL
        }
    }
}
```

---

## 三、扫光（Scanline）效果

```hlsl
Shader "Custom/ScanlineEffect"
{
    Properties
    {
        _MainTex ("Main Texture", 2D) = "white" {}
        _ScanlineColor ("Scanline Color", Color) = (0, 1, 1, 1)
        _ScanlineSpeed ("Scanline Speed", Float) = 1
        _ScanlineWidth ("Scanline Width", Range(0, 0.5)) = 0.1
        _ScanlineSharpness ("Scanline Sharpness", Range(1, 50)) = 10
    }
    
    SubShader
    {
        Tags { "RenderType"="Transparent" "Queue"="Transparent" }
        Blend SrcAlpha OneMinusSrcAlpha
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            struct Attributes { float4 pos : POSITION; float2 uv : TEXCOORD0; };
            struct Varyings { float4 pos : SV_POSITION; float2 uv : TEXCOORD0; };
            
            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            float4 _ScanlineColor;
            float _ScanlineSpeed, _ScanlineWidth, _ScanlineSharpness;
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.pos = TransformObjectToHClip(IN.pos.xyz);
                OUT.uv = IN.uv;
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                half4 mainColor = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                
                // 扫描线位置（随时间向上移动）
                float scanPos = frac(_Time.y * _ScanlineSpeed);
                
                // 计算当前像素到扫描线的距离
                float dist = abs(IN.uv.y - scanPos);
                
                // 使用 smoothstep 产生软边扫描线
                float scanMask = 1.0 - smoothstep(0, _ScanlineWidth, dist);
                scanMask = pow(scanMask, _ScanlineSharpness);
                
                // 混合扫描线颜色
                half4 result = mainColor;
                result.rgb = lerp(result.rgb, _ScanlineColor.rgb, scanMask * _ScanlineColor.a);
                result.rgb += _ScanlineColor.rgb * scanMask * 0.5; // 额外发光
                
                return result;
            }
            ENDHLSL
        }
    }
}
```

---

## 四、顶点动画（旗帜飘动）

```hlsl
Shader "Custom/FlagWave"
{
    Properties
    {
        _MainTex ("Flag Texture", 2D) = "white" {}
        _WaveAmplitude ("Wave Amplitude", Float) = 0.1
        _WaveFrequency ("Wave Frequency", Float) = 2
        _WaveSpeed ("Wave Speed", Float) = 1
        _WindDirection ("Wind Direction", Vector) = (1, 0, 0, 0)
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
            
            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
                float3 normalOS : NORMAL;
            };
            
            struct Varyings
            {
                float4 positionHCS : SV_POSITION;
                float2 uv : TEXCOORD0;
            };
            
            TEXTURE2D(_MainTex); SAMPLER(sampler_MainTex);
            float _WaveAmplitude, _WaveFrequency, _WaveSpeed;
            float4 _WindDirection;
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                
                // UV.x = 0 是固定端（挂旗处），UV.x = 1 是飘动端
                float influence = IN.uv.x;
                
                // 正弦波动
                float wave = sin(IN.uv.x * _WaveFrequency + _Time.y * _WaveSpeed) 
                    * _WaveAmplitude * influence;
                
                float3 windDir = normalize(_WindDirection.xyz);
                float3 offset = windDir * wave;
                offset.y += wave * 0.5; // Y方向也有轻微起伏
                
                float3 newPos = IN.positionOS.xyz + offset;
                OUT.positionHCS = TransformObjectToHClip(newPos);
                OUT.uv = IN.uv;
                return OUT;
            }
            
            half4 frag(Varyings IN) : SV_Target
            {
                return SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
            }
            ENDHLSL
        }
    }
}
```

---

## 五、交互水波纹（触摸水面）

```csharp
// 水波纹 CPU 控制部分
public class WaterRippleController : MonoBehaviour
{
    [SerializeField] private Material waterMaterial;
    [SerializeField] private int maxRipples = 10;
    [SerializeField] private float rippleLifetime = 2f;
    
    private Vector4[] ripplePositions;
    private float[] rippleTimes;
    private int rippleIndex;
    
    private static readonly int RipplePositionsId = Shader.PropertyToID("_RipplePositions");
    private static readonly int RippleTimesId = Shader.PropertyToID("_RippleTimes");
    private static readonly int RippleCountId = Shader.PropertyToID("_RippleCount");

    void Awake()
    {
        ripplePositions = new Vector4[maxRipples];
        rippleTimes = new float[maxRipples];
        
        for (int i = 0; i < maxRipples; i++)
            rippleTimes[i] = -rippleLifetime; // 初始化为已过期
    }

    void Update()
    {
        // 更新 Shader 参数
        for (int i = 0; i < maxRipples; i++)
            ripplePositions[i].w = (Time.time - rippleTimes[i]) / rippleLifetime;
        
        waterMaterial.SetVectorArray(RipplePositionsId, ripplePositions);
        
        // 调试：点击添加水波纹
        if (Input.GetMouseButtonDown(0))
        {
            Ray ray = Camera.main.ScreenPointToRay(Input.mousePosition);
            if (Physics.Raycast(ray, out RaycastHit hit) && hit.collider.gameObject == gameObject)
            {
                AddRipple(hit.point);
            }
        }
    }

    public void AddRipple(Vector3 worldPos)
    {
        ripplePositions[rippleIndex] = new Vector4(worldPos.x, worldPos.z, 0, 0);
        rippleTimes[rippleIndex] = Time.time;
        rippleIndex = (rippleIndex + 1) % maxRipples;
    }
}
```

---

## 六、Shader Graph vs 手写 HLSL

| 维度 | Shader Graph | 手写 HLSL |
|------|-------------|-----------|
| 开发效率 | ✅ 可视化，快速迭代 | ❌ 需要编写代码 |
| 性能优化空间 | ❌ 编译结果较冗余 | ✅ 精确控制每个指令 |
| 复杂逻辑 | ❌ 节点图复杂难维护 | ✅ 代码更清晰 |
| 跨平台 | ✅ 自动处理平台差异 | ⚠️ 需要手动处理 |
| 版本控制 | ❌ JSON文件，合并困难 | ✅ 文本友好 |
| 团队协作 | ⚠️ 美术可编辑 | ❌ 需要程序员 |

**推荐混合策略：**
- 常规材质（金属、皮肤、布料）→ Shader Graph
- 复杂特效（性能敏感）→ 手写 HLSL
- 可以在 Shader Graph 中嵌入自定义 HLSL 节点（Custom Function Node）
