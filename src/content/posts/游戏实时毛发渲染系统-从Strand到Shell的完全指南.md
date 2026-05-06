---
title: 游戏实时毛发渲染系统——从Strand到Shell的完全指南
published: 2026-05-06
description: 深度解析游戏引擎中实时毛发渲染的核心技术体系，涵盖Shell/Fin几何方案、Strand-Based头发渲染、Kajiya-Kay与Marschner光照模型、Alpha排序透明渲染、SDF碰撞模拟，以及Unity URP下的工程落地实践。
tags: [渲染, Shader, 毛发渲染, Hair Rendering, Unity, URP, 图形学]
category: 渲染技术
draft: false
---

# 游戏实时毛发渲染系统——从Strand到Shell的完全指南

毛发渲染是游戏图形中公认最具挑战性的领域之一。无论是角色头发、动物皮毛，还是写实草地，其核心难题都高度相似：**海量细长几何体 × 各向异性光照 × 半透明排序 × 物理模拟**，四大难点叠加，对渲染管线提出了极高要求。

本文将系统性地拆解实时毛发渲染的完整技术栈，从几何表示方案到光照模型，从透明渲染策略到物理模拟集成，最终给出可直接落地到 Unity URP 的工程方案。

---

## 1. 毛发几何表示方案全景

实时渲染无法承受真实毛发的几何量级（一个人头约有 10 万根发丝），因此必须选择合适的近似方案。

### 1.1 Shell/Fin 方案（皮毛/短毛首选）

Shell 方案将毛发表示为**多层偏移的网格壳体**，每层沿法线方向向外挤出，层内用噪声纹理做随机遮罩，层间透明度渐变，产生毛茸茸的视觉深度感。

```
表面层 (Shell 0) ──► Shell 1 ──► Shell 2 ──► ... ──► Shell N
                   ↑挤出距离        每层遮罩密度递减
```

**核心 Shader（Shell Layer）：**

```hlsl
// Shell Hair Shader - URP
Shader "Custom/ShellHair"
{
    Properties
    {
        _ShellCount ("Shell Count", Range(1, 64)) = 16
        _ShellLength ("Shell Length", Range(0, 1)) = 0.15
        _ShellIndex ("Shell Index", Float) = 0       // 由 C# 按层传入
        _NoiseTex ("Noise Texture", 2D) = "white" {}
        _HairDensity ("Hair Density", Range(0, 1)) = 0.7
        _HairThickness ("Hair Thickness", Range(0, 1)) = 0.3
        _RootColor ("Root Color", Color) = (0.1, 0.05, 0.02, 1)
        _TipColor ("Tip Color", Color) = (0.4, 0.25, 0.1, 1)
        _AO ("Ambient Occlusion Strength", Range(0, 1)) = 0.8
        _WindDir ("Wind Direction", Vector) = (1, 0, 0, 0)
        _WindStrength ("Wind Strength", Range(0, 1)) = 0.1
        _WindSpeed ("Wind Speed", Range(0, 10)) = 2.0
    }

    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "Queue"="AlphaTest" }
        Cull Off  // 双面渲染

        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

            TEXTURE2D(_NoiseTex); SAMPLER(sampler_NoiseTex);

            CBUFFER_START(UnityPerMaterial)
                float _ShellCount;
                float _ShellLength;
                float _ShellIndex;
                float _HairDensity;
                float _HairThickness;
                float4 _RootColor;
                float4 _TipColor;
                float _AO;
                float4 _WindDir;
                float _WindStrength;
                float _WindSpeed;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float2 uv         : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv         : TEXCOORD0;
                float  shellHeight : TEXCOORD1;  // 归一化层高 [0,1]
                float3 normalWS   : TEXCOORD2;
                float3 positionWS : TEXCOORD3;
            };

            Varyings vert(Attributes IN)
            {
                Varyings OUT;

                // 归一化层高
                float h = _ShellIndex / (_ShellCount - 1.0);

                // 风力偏移（层越高偏移越大）
                float windTime = _Time.y * _WindSpeed;
                float3 windOffset = _WindDir.xyz
                    * _WindStrength
                    * h * h                     // 抛物线形态：根部固定，尖端摇摆
                    * sin(windTime + IN.positionOS.x * 3.14);

                // 沿法线挤出 + 风力偏移
                float3 offset = IN.normalOS * h * _ShellLength + windOffset;
                float4 posOS = float4(IN.positionOS.xyz + offset, 1.0);

                OUT.positionCS  = TransformObjectToHClip(posOS);
                OUT.positionWS  = TransformObjectToWorld(posOS);
                OUT.normalWS    = TransformObjectToWorldNormal(IN.normalOS);
                OUT.uv          = IN.uv;
                OUT.shellHeight = h;
                return OUT;
            }

            half4 frag(Varyings IN) : SV_Target
            {
                // 采样噪声纹理决定该像素是否有毛发
                float noise = SAMPLE_TEXTURE2D(_NoiseTex, sampler_NoiseTex, IN.uv * 20.0).r;

                // 动态发丝阈值：越靠近尖端越稀疏
                float threshold = (1.0 - _HairDensity) + IN.shellHeight * (1.0 - _HairThickness);
                clip(noise - threshold);   // Alpha 测试

                // 根部→尖端颜色插值
                half4 hairColor = lerp(_RootColor, _TipColor, IN.shellHeight);

                // 环境光遮蔽：根部更暗
                float ao = lerp(1.0 - _AO, 1.0, IN.shellHeight);

                // 简单 Lambert 漫反射
                Light mainLight = GetMainLight();
                float NdotL = saturate(dot(IN.normalWS, mainLight.direction));
                half3 diffuse = hairColor.rgb * mainLight.color * NdotL;
                half3 ambient = hairColor.rgb * unity_AmbientSky.rgb;

                return half4((diffuse + ambient) * ao, 1.0);
            }
            ENDHLSL
        }
    }
}
```

**C# Shell 层管理器：**

```csharp
using UnityEngine;

[RequireComponent(typeof(MeshFilter), typeof(MeshRenderer))]
public class ShellHairRenderer : MonoBehaviour
{
    [Header("Shell Settings")]
    [Range(4, 64)]
    public int shellCount = 24;
    public float shellLength = 0.15f;
    public Material shellMaterial;

    private GameObject[] _shells;
    private static readonly int ShellIndex  = Shader.PropertyToID("_ShellIndex");
    private static readonly int ShellCount  = Shader.PropertyToID("_ShellCount");
    private static readonly int ShellLength = Shader.PropertyToID("_ShellLength");

    void Start() => BuildShells();

    void BuildShells()
    {
        DestroyShells();
        _shells = new GameObject[shellCount];
        MeshFilter mf = GetComponent<MeshFilter>();

        for (int i = 0; i < shellCount; i++)
        {
            var go = new GameObject($"Shell_{i:D2}");
            go.transform.SetParent(transform, false);

            go.AddComponent<MeshFilter>().sharedMesh = mf.sharedMesh;
            var mr = go.AddComponent<MeshRenderer>();

            // 每层使用独立 Material 实例（避免相互干扰）
            var mat = new Material(shellMaterial);
            mat.SetFloat(ShellIndex,  i);
            mat.SetFloat(ShellCount,  shellCount);
            mat.SetFloat(ShellLength, shellLength);
            mr.material = mat;

            _shells[i] = go;
        }
    }

    void DestroyShells()
    {
        if (_shells == null) return;
        foreach (var s in _shells)
            if (s != null) Destroy(s);
        _shells = null;
    }

    void OnDestroy() => DestroyShells();

#if UNITY_EDITOR
    void OnValidate()
    {
        if (Application.isPlaying) BuildShells();
    }
#endif
}
```

### 1.2 Card-Based 方案（游戏角色头发主流方案）

Card 方案将头发建模为**一组面片（Cards）**，每个 Card 贴上头发纹理（含 Alpha 通道），按发型分组，美术手动摆放，是 AAA 游戏角色头发的主流选择。

优点：
- 面数可控（500~2000 面片），渲染开销低
- 美术可精确控制发型
- 易于支持物理模拟

缺点：
- 制作成本高（需专门发型制作工具）
- 近距离看边缘感明显

### 1.3 Strand-Based 方案（高端写实方案）

每根发丝由多段线段组成，使用 Geometry Shader 或 Mesh Shader 将线段扩展为带状面片（Billboard Strip），真实度极高但开销大，多用于主机/PC 旗舰作品。

---

## 2. 各向异性光照模型

毛发的高光形态与普通 PBR 完全不同——发丝的微观柱状结构产生**各向异性高光**，呈现出沿发丝方向的条带状光晕。

### 2.1 Kajiya-Kay 模型（经典近似）

1989 年提出的经典模型，至今仍在大量实时渲染中使用。

核心公式：
$$
L_{diffuse} = \sin(\vec{T}, \vec{L})
$$
$$
L_{specular} = \cos^n(\vec{T} \times \vec{V}, \vec{T} \times \vec{L})
$$

```hlsl
// Kajiya-Kay 各向异性光照
half3 KajiyaKayHair(
    float3 tangent,   // 发丝切线方向（沿发丝）
    float3 lightDir,
    float3 viewDir,
    half3 hairColor,
    half3 specColor,
    float specPow,
    float specShift    // 高光沿发丝偏移量（模拟鳞片结构）
)
{
    // 偏移切线（模拟发丝表面微鳞片）
    float3 T = normalize(tangent + specShift * float3(0, 1, 0));

    // 漫反射：基于切线与光线夹角的 sin
    float TdotL = dot(T, lightDir);
    float sinTL = sqrt(max(0, 1.0 - TdotL * TdotL));
    half3 diffuse = hairColor * sinTL;

    // 高光：基于切线-光线和切线-视线的夹角
    float TdotV = dot(T, viewDir);
    float sinTV = sqrt(max(0, 1.0 - TdotV * TdotV));
    float cosPhi = TdotL * TdotV + sinTL * sinTV;  // cos(theta_h)
    half3 specular = specColor * pow(saturate(cosPhi), specPow);

    return diffuse + specular;
}
```

### 2.2 双层高光（Scheuermann 方案）

Tomb Raider 等游戏使用的双层高光方案，通过两个偏移不同的 Kajiya-Kay 层叠加，模拟头发的**一次反射（R）** 和 **二次透射-反射（TRT）** 两种光路：

```hlsl
// 双层各向异性高光（Scheuermann-style）
half3 DoubleLayerSpecular(
    float3 tangent,
    float3 lightDir,
    float3 viewDir,
    half3 specColor1,
    half3 specColor2,
    float  pow1,
    float  pow2,
    float  shift1,   // 第一层高光偏移（主高光，较强）
    float  shift2,   // 第二层高光偏移（次高光，较弱，颜色偏暖）
    TEXTURE2D(shiftMap), SAMPLER(sampler_shiftMap),
    float2 uv
)
{
    // 从切线偏移贴图读取高光偏移扰动（沿发丝分布不均匀）
    float shift = SAMPLE_TEXTURE2D(shiftMap, sampler_shiftMap, uv).r - 0.5;

    float3 T1 = normalize(tangent + (shift1 + shift) * cross(tangent, float3(0,1,0)));
    float3 T2 = normalize(tangent + (shift2 + shift) * cross(tangent, float3(0,1,0)));

    half3 spec1 = KajiyaKaySpecular(T1, lightDir, viewDir, pow1) * specColor1;
    half3 spec2 = KajiyaKaySpecular(T2, lightDir, viewDir, pow2) * specColor2;

    return spec1 + spec2;
}

half KajiyaKaySpecular(float3 T, float3 L, float3 V, float pow)
{
    float TdotL = dot(T, L);
    float TdotV = dot(T, V);
    float sinTL = sqrt(max(0, 1 - TdotL * TdotL));
    float sinTV = sqrt(max(0, 1 - TdotV * TdotV));
    float cosPhi = TdotL * TdotV + sinTL * sinTV;
    return pow(saturate(cosPhi), pow);
}
```

---

## 3. 透明渲染与排序策略

毛发最棘手的问题之一是**透明排序**。Alpha Blend 需要从后到前排序，但发丝数量巨大无法每帧排序。

### 3.1 Alpha Test（最简单但有锯齿）

```hlsl
// 简单 Alpha Test，无排序问题
clip(hairAlpha - 0.5);
```

- 无排序问题，性能最好
- 边缘有明显锯齿
- 通常配合 MSAA/TAA 使用

### 3.2 Alpha to Coverage（A2C）

利用 MSAA 将 Alpha 值映射到多采样覆盖位，实现亚像素级半透明效果，是移动端毛发的常用方案：

```hlsl
// 需要开启 MSAA，Shader 中设置
Tags { "RenderType" = "TransparentCutout" }
AlphaToMask On

// 输出 Alpha 即可，驱动程序自动处理 A2C
return half4(color.rgb, hairAlpha);
```

### 3.3 Per-Object Depth Peeling（高质量但昂贵）

多 Pass 渲染，每次 Pass 剥去最前一层透明层，适合离线渲染，实时使用有限。

### 3.4 OIT（顺序无关透明）实践方案

```csharp
// Unity URP OIT 基础框架
public class HairOITFeature : ScriptableRendererFeature
{
    // 使用链表 OIT 或 Weighted Blended OIT
    // 这里以 WBOIT (Weighted Blended OIT) 为例

    private HairAccumulatePass _accPass;
    private HairCompositePass  _compPass;

    public override void Create()
    {
        _accPass  = new HairAccumulatePass();
        _compPass = new HairCompositePass();
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        renderer.EnqueuePass(_accPass);
        renderer.EnqueuePass(_compPass);
    }
}
```

---

## 4. 毛发物理模拟

### 4.1 基于弹簧链的位置模拟（Verlet Integration）

每根发丝近似为一条**质点-弹簧链**，使用 Verlet 积分模拟运动：

```csharp
public class StrandSimulator : MonoBehaviour
{
    [System.Serializable]
    public struct Particle
    {
        public Vector3 position;
        public Vector3 prevPosition;
        public bool    isRoot;       // 根部粒子固定
    }

    public int   particleCount = 8;
    public float stiffness     = 0.8f;
    public float damping       = 0.98f;
    public float gravity       = -9.8f;
    public float segmentLength = 0.05f;

    private Particle[] _particles;

    void Start()
    {
        _particles = new Particle[particleCount];
        Vector3 start = transform.position;
        for (int i = 0; i < particleCount; i++)
        {
            _particles[i] = new Particle
            {
                position     = start + Vector3.down * i * segmentLength,
                prevPosition = start + Vector3.down * i * segmentLength,
                isRoot       = i == 0
            };
        }
    }

    void FixedUpdate()
    {
        float dt = Time.fixedDeltaTime;

        // Step 1: Verlet 积分
        for (int i = 1; i < particleCount; i++)
        {
            ref Particle p = ref _particles[i];
            Vector3 vel = (p.position - p.prevPosition) * damping;
            p.prevPosition = p.position;
            p.position    += vel + Vector3.up * gravity * dt * dt;
        }

        // Step 2: 约束修正（保持各段长度恒定）
        const int iterations = 4;
        for (int iter = 0; iter < iterations; iter++)
        {
            // 根部固定
            _particles[0].position = transform.position;

            for (int i = 1; i < particleCount; i++)
            {
                ref Particle a = ref _particles[i - 1];
                ref Particle b = ref _particles[i];

                Vector3 dir  = b.position - a.position;
                float   dist = dir.magnitude;
                if (dist < 0.0001f) continue;

                float  error  = (dist - segmentLength) / dist;
                Vector3 corr  = dir * error * 0.5f;

                if (!a.isRoot) a.position += corr;
                if (!b.isRoot) b.position -= corr;
            }

            // 刚度约束：向初始位置拉回
            for (int i = 1; i < particleCount; i++)
            {
                ref Particle p = ref _particles[i];
                Vector3 restPos = transform.position + Vector3.down * i * segmentLength;
                p.position = Vector3.Lerp(p.position, restPos, stiffness * Time.fixedDeltaTime);
            }
        }
    }

    void OnDrawGizmos()
    {
        if (_particles == null) return;
        Gizmos.color = Color.yellow;
        for (int i = 1; i < _particles.Length; i++)
            Gizmos.DrawLine(_particles[i-1].position, _particles[i].position);
    }
}
```

### 4.2 SDF 碰撞检测

将头部/身体近似为一组球体 SDF，避免穿插：

```hlsl
// Compute Shader：SDF 球体碰撞
float3 SDFSphereCollide(float3 pos, float3 center, float radius, float hairRadius)
{
    float3 dir  = pos - center;
    float  dist = length(dir);
    float  minDist = radius + hairRadius;

    if (dist < minDist)
    {
        // 推出碰撞体外
        pos = center + normalize(dir) * minDist;
    }
    return pos;
}
```

---

## 5. 完整工程方案：Unity URP 角色头发

### 5.1 材质分层架构

```
角色头发材质体系
├── 底部发丝层（Opaque，Alpha Test）
│   ├── 主发型 Card 网格
│   └── Kajiya-Kay 双层高光
├── 飘散发丝层（Alpha Blend，Sorted）
│   ├── 少量关键飘散发片
│   └── 手动深度排序
└── 柔化边缘层（A2C，MSAA）
    └── 外轮廓细碎发丝
```

### 5.2 完整头发着色器（Production-Grade）

```hlsl
Shader "Custom/CharacterHair_URP"
{
    Properties
    {
        _BaseMap        ("Hair Albedo (RGBA)", 2D) = "white" {}
        _NormalMap      ("Normal Map", 2D) = "bump" {}
        _FlowMap        ("Hair Flow Map (RG=tangent)", 2D) = "gray" {}
        _ShiftMap       ("Specular Shift Map", 2D) = "gray" {}
        _SpecColor1     ("Specular Color 1", Color) = (1,1,1,1)
        _SpecColor2     ("Specular Color 2", Color) = (0.8,0.6,0.3,1)
        _SpecPow1       ("Specular Power 1", Range(1,200)) = 80
        _SpecPow2       ("Specular Power 2", Range(1,200)) = 20
        _SpecShift1     ("Spec Shift 1", Range(-1,1)) = -0.1
        _SpecShift2     ("Spec Shift 2", Range(-1,1)) = 0.1
        _AlphaClip      ("Alpha Clip Threshold", Range(0,1)) = 0.3
        _SSSColor       ("Sub-Surface Scatter Color", Color) = (0.5,0.3,0.2,1)
        _SSSStrength    ("SSS Strength", Range(0,1)) = 0.3
    }

    SubShader
    {
        Tags { "RenderType"="TransparentCutout" "Queue"="AlphaTest+1" }
        AlphaToMask On
        Cull Off

        Pass
        {
            Name "ForwardLit"
            Tags { "LightMode" = "UniversalForward" }

            HLSLPROGRAM
            #pragma vertex   vert
            #pragma fragment frag
            #pragma multi_compile _ _MAIN_LIGHT_SHADOWS _MAIN_LIGHT_SHADOWS_CASCADE
            #pragma multi_compile _ _SHADOWS_SOFT
            #pragma multi_compile_fog

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Shadows.hlsl"

            TEXTURE2D(_BaseMap);  SAMPLER(sampler_BaseMap);
            TEXTURE2D(_NormalMap);SAMPLER(sampler_NormalMap);
            TEXTURE2D(_FlowMap);  SAMPLER(sampler_FlowMap);
            TEXTURE2D(_ShiftMap); SAMPLER(sampler_ShiftMap);

            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                half4  _SpecColor1, _SpecColor2;
                float  _SpecPow1, _SpecPow2;
                float  _SpecShift1, _SpecShift2;
                float  _AlphaClip;
                half4  _SSSColor;
                float  _SSSStrength;
            CBUFFER_END

            struct Attributes
            {
                float4 positionOS : POSITION;
                float3 normalOS   : NORMAL;
                float4 tangentOS  : TANGENT;
                float2 uv         : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS  : SV_POSITION;
                float2 uv          : TEXCOORD0;
                float3 positionWS  : TEXCOORD1;
                float3 normalWS    : TEXCOORD2;
                float3 tangentWS   : TEXCOORD3;
                float3 bitangentWS : TEXCOORD4;
                float4 shadowCoord : TEXCOORD5;
                UNITY_FOG_COORDS(6)
            };

            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                VertexPositionInputs posInputs = GetVertexPositionInputs(IN.positionOS.xyz);
                VertexNormalInputs   nrmInputs = GetVertexNormalInputs(IN.normalOS, IN.tangentOS);

                OUT.positionCS  = posInputs.positionCS;
                OUT.positionWS  = posInputs.positionWS;
                OUT.normalWS    = nrmInputs.normalWS;
                OUT.tangentWS   = nrmInputs.tangentWS;
                OUT.bitangentWS = nrmInputs.bitangentWS;
                OUT.uv          = TRANSFORM_TEX(IN.uv, _BaseMap);
                OUT.shadowCoord = GetShadowCoord(posInputs);
                UNITY_TRANSFER_FOG(OUT, OUT.positionCS);
                return OUT;
            }

            // ---- 各向异性高光核心函数 ----
            half AnisotropicSpec(float3 T, float3 L, float3 V, float power)
            {
                float TdotL = dot(T, L);
                float TdotV = dot(T, V);
                float sinTL = sqrt(saturate(1 - TdotL * TdotL));
                float sinTV = sqrt(saturate(1 - TdotV * TdotV));
                return pow(saturate(TdotL * TdotV + sinTL * sinTV), power);
            }

            half4 frag(Varyings IN) : SV_Target
            {
                float2 uv = IN.uv;

                // 采样基础贴图
                half4 base    = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv);
                clip(base.a - _AlphaClip);

                // 法线（切线空间 → 世界空间）
                half3 normalTS = UnpackNormal(SAMPLE_TEXTURE2D(_NormalMap, sampler_NormalMap, uv));
                float3x3 TBN   = float3x3(IN.tangentWS, IN.bitangentWS, IN.normalWS);
                float3 N       = normalize(mul(normalTS, TBN));

                // 从 FlowMap 构建切线方向（发丝走向）
                half2 flow = SAMPLE_TEXTURE2D(_FlowMap, sampler_FlowMap, uv).rg * 2 - 1;
                float3 T   = normalize(IN.tangentWS * flow.x + IN.bitangentWS * flow.y);

                // 光照向量
                Light  light = GetMainLight(IN.shadowCoord);
                float3 L     = normalize(light.direction);
                float3 V     = normalize(GetCameraPositionWS() - IN.positionWS);

                // 高光偏移扰动
                float shift = SAMPLE_TEXTURE2D(_ShiftMap, sampler_ShiftMap, uv).r - 0.5;
                float3 T1 = normalize(T + (_SpecShift1 + shift * 0.2) * N);
                float3 T2 = normalize(T + (_SpecShift2 + shift * 0.2) * N);

                // 双层 Kajiya-Kay 高光
                half spec1 = AnisotropicSpec(T1, L, V, _SpecPow1);
                half spec2 = AnisotropicSpec(T2, L, V, _SpecPow2);
                half3 specular = spec1 * _SpecColor1.rgb + spec2 * _SpecColor2.rgb;

                // 漫反射（Lambert + Wrap for SSS近似）
                float wrapDiff  = saturate((dot(N, L) + 0.3) / 1.3);
                half3 diffuse   = base.rgb * wrapDiff * light.color;

                // 次表面散射近似（逆光透射）
                float sss       = saturate(dot(-L, V)) * _SSSStrength;
                half3 sssColor  = _SSSColor.rgb * sss * light.color;

                // 环境光
                half3 ambient   = base.rgb * unity_AmbientSky.rgb * 0.5;

                half3 finalColor = (diffuse + specular + sssColor + ambient) * light.shadowAttenuation;
                UNITY_APPLY_FOG(IN.fogCoord, finalColor);

                return half4(finalColor, base.a);
            }
            ENDHLSL
        }

        // Shadow Caster Pass（发丝投影）
        Pass
        {
            Name "ShadowCaster"
            Tags { "LightMode" = "ShadowCaster" }
            ZWrite On
            Cull Off

            HLSLPROGRAM
            #pragma vertex   ShadowVert
            #pragma fragment ShadowFrag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/SurfaceInput.hlsl"
            #include "Packages/com.unity.render-pipelines.universal/Shaders/ShadowCasterPass.hlsl"

            TEXTURE2D(_BaseMap); SAMPLER(sampler_BaseMap);
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                float  _AlphaClip;
            CBUFFER_END

            // 覆盖 Fragment 做 Alpha Test
            half4 ShadowFrag(Varyings IN) : SV_Target
            {
                float2 uv    = TRANSFORM_TEX(IN.uv, _BaseMap);
                half   alpha = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv).a;
                clip(alpha - _AlphaClip);
                return 0;
            }
            ENDHLSL
        }
    }
}
```

---

## 6. 性能优化策略

### 6.1 LOD 分级方案

```
LOD 0（近距 < 3m）  : 完整 Strand Card + 双层高光 + 物理模拟
LOD 1（中距 3~8m）  : 简化 Card + 单层高光 + 骨骼动画
LOD 2（远距 > 8m）  : 合并 Mesh + 简单 Lambert
LOD 3（极远 > 20m） : Impostor（公告板替代）
```

### 6.2 Early-Out Clip 优化

```hlsl
// 在高光计算前提前 Alpha Test，避免无效计算
half alpha = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, uv).a;
clip(alpha - _AlphaClip);   // 早期剔除无发丝区域
// ... 后续复杂光照计算
```

### 6.3 移动端降级方案

```hlsl
// 移动端：禁用双层高光，使用单次采样
#if defined(SHADER_API_MOBILE)
    half3 specular = spec1 * _SpecColor1.rgb;  // 只保留主高光
#else
    half3 specular = spec1 * _SpecColor1.rgb + spec2 * _SpecColor2.rgb;
#endif
```

---

## 7. 最佳实践总结

| 场景 | 推荐方案 | 原因 |
|------|----------|------|
| 移动端角色头发 | Card + Alpha Test + A2C | 性能可控，视觉效果够用 |
| PC/主机写实角色 | Card + WBOIT + 双层高光 | 视觉质量优先 |
| 动物皮毛（写实） | Shell（16~32层） + Kajiya-Kay | 皮毛感强，制作简单 |
| 动物皮毛（手游） | Shell（8层以内） + Simple Lambert | 性能优先 |
| 高端 PC 旗舰 | Strand-Based + Marschner | 最高真实度 |

**关键工程经验：**

1. **Alpha Test 优先于 Alpha Blend** —— 发丝渲染优先用 Alpha Test + A2C，而非 Alpha Blend，避免排序问题。
2. **切线方向贴图（FlowMap）必不可少** —— 各向异性高光的质量完全依赖正确的发丝走向信息。
3. **SSS 提升逆光效果** —— 用简单的 Wrap Lighting + 逆光透射模拟，大幅提升头发的光影立体感。
4. **Shell 层数按距离动态调整** —— Shell 方案的性能代价线性增长，务必配合 LOD 动态调节层数。
5. **物理模拟与渲染解耦** —— 物理运行在固定帧率（20~30fps），渲染插值，避免物理成为渲染瓶颈。
