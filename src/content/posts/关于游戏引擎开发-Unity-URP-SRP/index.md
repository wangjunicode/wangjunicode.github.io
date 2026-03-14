---
title: Unity URP/SRP 深度解析：可编程渲染管线实战指南
published: 2021-09-03
description: "系统讲解 Unity 渲染管线体系：内置管线 vs URP vs HDRP 的对比选型，SRP 核心架构（RenderPipelineAsset/ScriptableRendererFeature），URP 完整渲染流程，以及如何通过 ScriptableRenderPass 自定义渲染效果，并总结移动端 URP 性能优化要点。"
tags: [Unity, 渲染, URP, 图形渲染]
category: 图形渲染
draft: false
---

我最早接触 URP 是在 Unity 2019 版本，那时候它还叫 LWRP（轻量级渲染管线）。刚开始觉得它只是手游的轻量化方案，后来随着功能越来越完善，加上 Unity 宣布内置管线不再更新新特性，团队逐渐把新项目全面迁移到 URP。这篇文章把我对 URP/SRP 体系的理解系统整理一下。

---

## 为什么要有 SRP（可编程渲染管线）

### 内置渲染管线的痛点

Unity 内置渲染管线（Built-in Render Pipeline）有两个根本性的缺陷：

**1. 定制性差**

渲染管线的代码全在引擎 C++ 层，开发者拿不到、改不了。如果要实现一个自定义渲染效果（比如卡通描边、自定义阴影），只能通过各种 hack 方式绕路实现，代码丑且不稳定。

**2. 平台无法最优化**

内置管线需要同时支持 PC 高端显卡和 5 年前的低端手机，所有平台共用一套管线代码。结果是：PC 上功能太少，手机上开销太大，谁都不满意。

### SRP 的设计思路

Unity 的解法是：**在 C++ 层保留最小的渲染内核，把管线逻辑暴露成 C# API**。

这样开发者可以：
- 自己写渲染管线（或者用 Unity 提供的 URP/HDRP）
- 针对目标平台做最优化
- 在 C# 层扩展任意渲染特效

```
Unity 渲染体系结构：
┌─────────────────────────────────────────┐
│            你的游戏代码                  │
├─────────────────────────────────────────┤
│     SRP C# API（ScriptableRenderer等）   │  ← 你可以在这里扩展
├─────────────────────────────────────────┤
│     URP / HDRP（Unity 提供的实现）       │  ← 或者直接使用
├─────────────────────────────────────────┤
│        Unity C++ 渲染内核               │
└─────────────────────────────────────────┘
```

---

## 三条管线对比

| 维度 | 内置管线（Built-in）| URP | HDRP |
|------|-------------------|-----|------|
| **定位** | 通用，旧项目 | 移动端/中端 | PC/主机高品质 |
| **性能开销** | 中 | 低 | 高 |
| **画质上限** | 中 | 中高（持续提升） | 极高 |
| **光照** | 多光源较贵 | 优化的多光源 | 物理基础光照 |
| **Shader 语言** | CG/HLSL | HLSL（URP ShaderLib）| HLSL（HDRP ShaderLib）|
| **后处理** | Post Processing Stack v2 | 内置 Volume 系统 | 内置 Volume 系统 |
| **自定义扩展** | 困难 | ScriptableRendererFeature | CustomPass |
| **推荐新项目** | ❌ 不再更新 | ✅ 手游/独立游戏 | ✅ 3A 品质项目 |

**选型建议**：
- 手游项目 → **URP**，性能好，功能够用
- PC/主机高品质 → **HDRP**，PBR 管线，效果拔群
- 维护老项目 → 继续用**内置管线**，迁移成本高

---

## SRP 核心架构

### RenderPipelineAsset

这是你的渲染管线的"配置文件+工厂"，继承自 `RenderPipelineAsset<T>`，负责创建具体的渲染管线实例，并在 Inspector 中暴露配置项。

URP 里对应的就是 `UniversalRenderPipelineAsset`（在 Project Settings → Graphics 里指定）。

### RenderPipeline（管线实例）

管线的核心逻辑在这里，每帧的渲染入口是 `Render(ScriptableRenderContext context, Camera[] cameras)`。URP 对应 `UniversalRenderPipeline`。

### ScriptableRendererFeature

这是**给开发者的扩展接口**，也是平时用得最多的。在这里你可以向渲染队列插入自定义的 `ScriptableRenderPass`，实现各种后处理效果。

```
URP 扩展点示意：
ForwardRenderer
  ├─ RendererFeature A （你自己加的）
  │    └─ ScriptableRenderPass（在某个渲染阶段执行你的代码）
  ├─ RendererFeature B
  └─ ... Unity 内置的 Feature
```

---

## URP 渲染流程

URP 的渲染顺序（Forward Rendering 模式）：

```
1. Setup（初始化，创建 RT）
2. Shadow Pass（阴影贴图渲染）
3. Depth Pre-Pass（深度预通道，可选）
4. Opaque（不透明物体）
5. Skybox（天空盒）
6. Transparent（透明物体，从后往前）
7. Post-Processing（后处理：Bloom/Color Grading等）
8. UI（UGUI 等，最后渲染）
```

在代码层面，这对应 `RenderPassEvent` 枚举：

```csharp
public enum RenderPassEvent
{
    BeforeRendering = 0,
    BeforeRenderingShadows = 50,
    AfterRenderingShadows = 100,
    BeforeRenderingPrePasses = 150,
    AfterRenderingPrePasses = 200,
    BeforeRenderingGbuffer = 210,        // Deferred 模式
    AfterRenderingGbuffer = 220,
    BeforeRenderingDeferredLights = 230,
    AfterRenderingDeferredLights = 240,
    BeforeRenderingOpaques = 250,
    AfterRenderingOpaques = 300,
    BeforeRenderingSkybox = 350,
    AfterRenderingSkybox = 400,
    BeforeRenderingTransparents = 450,
    AfterRenderingTransparents = 500,
    BeforeRenderingPostProcessing = 550,
    AfterRenderingPostProcessing = 600,
    AfterRendering = 1000,
}
```

---

## 实战：自定义渲染特效（描边 + 颜色叠加）

下面是原有代码的完整版本，我加入了更多注释和说明。

### ScriptableRenderPass 实现

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 自定义渲染 Pass：对不透明物体渲染后的帧缓冲做颜色叠加处理
/// </summary>
public class ColorTintRenderPass : ScriptableRenderPass
{
    private readonly Material _material;
    private RenderTargetIdentifier _source;
    private RenderTargetHandle _tempRT;
    private readonly ProfilingSampler _profilingSampler;

    public ColorTintRenderPass(Material material)
    {
        _material = material;
        // 设置这个 Pass 插入的渲染阶段：不透明物体渲染完毕后
        renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
        _tempRT.Init("_ColorTintTemp");
        _profilingSampler = new ProfilingSampler("ColorTintPass");
    }

    /// <summary>
    /// 每帧渲染前调用，设置当前帧的颜色 RT 来源
    /// </summary>
    public void Setup(RenderTargetIdentifier source)
    {
        _source = source;
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get();

        using (new ProfilingScope(cmd, _profilingSampler))
        {
            // 1. 获取当前帧的 RT 描述（分辨率、格式等）
            RenderTextureDescriptor desc = renderingData.cameraData.cameraTargetDescriptor;
            desc.depthBufferBits = 0; // 临时 RT 不需要深度

            // 2. 申请一张临时 RT
            cmd.GetTemporaryRT(_tempRT.id, desc, FilterMode.Bilinear);

            // 3. 用我们的 Shader 处理源 RT，输出到临时 RT
            Blit(cmd, _source, _tempRT.Identifier(), _material);

            // 4. 将处理后的临时 RT 写回到摄像机 RT
            Blit(cmd, _tempRT.Identifier(), _source);
        }

        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void FrameCleanup(CommandBuffer cmd)
    {
        // 释放临时 RT，避免显存泄漏
        cmd.ReleaseTemporaryRT(_tempRT.id);
    }
}
```

### ScriptableRendererFeature 实现

```csharp
using UnityEngine;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 颜色叠加 RendererFeature
/// 在 URP Renderer Asset 的 Inspector 中 Add Renderer Feature 即可使用
/// </summary>
public class ColorTintFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class Settings
    {
        public Color TintColor = Color.red;
        [Range(0f, 1f)]
        public float Intensity = 0.2f;
    }

    public Settings settings = new Settings();

    private ColorTintRenderPass _pass;
    private Material _material;

    /// <summary>
    /// Feature 被创建或设置修改时调用
    /// </summary>
    public override void Create()
    {
        _material = new Material(Shader.Find("Hidden/ColorTint"));
        _pass = new ColorTintRenderPass(_material);
    }

    /// <summary>
    /// 每帧为每个摄像机调用一次，将 Pass 加入渲染队列
    /// </summary>
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        // 可以在这里做条件判断，比如只在游戏摄像机上生效
        if (renderingData.cameraData.cameraType == CameraType.Preview)
            return;

        _material.SetColor("_TintColor", settings.TintColor);
        _material.SetFloat("_Intensity", settings.Intensity);

        _pass.Setup(renderer.cameraColorTarget);
        renderer.EnqueuePass(_pass);
    }

    protected override void Dispose(bool disposing)
    {
        if (_material != null)
            CoreUtils.Destroy(_material);
    }
}
```

### 配套 Shader

```hlsl
Shader "Hidden/ColorTint"
{
    Properties
    {
        _MainTex ("Screen Texture", 2D) = "white" {}
        _TintColor ("Tint Color", Color) = (1, 0, 0, 1)
        _Intensity ("Intensity", Range(0, 1)) = 0.2
    }

    SubShader
    {
        Tags { "RenderType" = "Opaque" "RenderPipeline" = "UniversalPipeline" }

        Pass
        {
            ZTest Always
            ZWrite Off
            Cull Off

            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag

            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"

            struct Attributes
            {
                float4 positionOS : POSITION;
                float2 uv : TEXCOORD0;
            };

            struct Varyings
            {
                float4 positionCS : SV_POSITION;
                float2 uv : TEXCOORD0;
            };

            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);

            CBUFFER_START(UnityPerMaterial)
                float4 _MainTex_ST;
                half4 _TintColor;
                half _Intensity;
            CBUFFER_END

            Varyings vert(Attributes v)
            {
                Varyings o;
                VertexPositionInputs posInputs = GetVertexPositionInputs(v.positionOS.xyz);
                o.positionCS = posInputs.positionCS;
                o.uv = TRANSFORM_TEX(v.uv, _MainTex);
                return o;
            }

            half4 frag(Varyings i) : SV_Target
            {
                half4 col = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, i.uv);
                return lerp(col, _TintColor, _Intensity);
            }
            ENDHLSL
        }
    }
}
```

---

## 移动端 URP 优化建议

从我们项目的移动端经验总结：

### 1. 关闭不需要的特性

在 `UniversalRenderPipelineAsset` 里，逐项检查：
- 阴影：移动端尽量用 1 个 Shadow Cascade，分辨率 1024 或 2048
- MSAA：移动端选 2x，不要 4x 或 8x
- HDR：中低端手机关闭（减少带宽）
- Depth Texture / Opaque Texture：只在需要的时候开启（折射、软粒子等用到）

### 2. Shader 复杂度控制

```hlsl
// ✅ 移动端用简化光照
#pragma multi_compile _ _MAIN_LIGHT_SHADOWS  // 按需开启阴影采样
#pragma multi_compile _ _ADDITIONAL_LIGHTS   // 多光源支持，移动端尽量关

// 移动端 frag 中避免 discard（会禁用 HSR/Early-Z 优化）
// 尽量减少 tex2D 采样次数（带宽瓶颈）
```

### 3. Render Pass 数量控制

每多一个 `ScriptableRenderPass`，就多一次（或多次）RT 操作。移动端带宽有限，全屏后处理叠太多会严重影响性能。Bloom + ColorGrading 合并成一个 Pass 比两个独立 Pass 快很多。

### 4. 善用 Batcher

URP 内置了 SRP Batcher，它可以大幅减少 CPU 侧的 SetPass 调用。确保你的 Shader 里的 `CBUFFER_START(UnityPerMaterial)` 是正确包含所有材质属性的，否则 SRP Batcher 会失效。

```hlsl
// ✅ 正确：所有材质属性都在 UnityPerMaterial CBuffer 里
CBUFFER_START(UnityPerMaterial)
    float4 _BaseColor;
    float _Smoothness;
    float _Metallic;
CBUFFER_END

// ❌ 错误：材质属性散落在 CBuffer 外面，破坏 SRP Batcher
float4 _BaseColor;  // 不在 CBuffer 里！
```

---

## 总结

URP 体系是 Unity 图形的未来，无论是手游还是独立游戏，这套管线都是主流选择。掌握 `ScriptableRendererFeature` + `ScriptableRenderPass` 之后，你几乎可以实现任何想要的渲染效果——描边、轮廓高亮、自定义后处理、特殊深度效果……都在这套框架里实现。

入门建议：先从改一个现有的 Feature 开始（比如 Unity 内置的 `BlitRendererFeature`），在上面加入自己的 Shader 逻辑，比从头写要快很多。

参考：[CSDN URP 入门教程](https://blog.csdn.net/qq_33700123/article/details/114092028)
