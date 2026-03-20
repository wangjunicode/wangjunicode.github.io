---
title: Unity 渲染管线深度解析：从 Built-in 到 URP
published: 2026-03-21
description: "深入剖析 Unity 渲染管线的工作原理，对比 Built-in、URP、HDRP 的差异，掌握自定义渲染特性的开发方法，以及移动端渲染优化的核心技术。"
tags: [Unity, 渲染管线, URP, Shader, 性能优化]
category: 图形渲染
draft: false
---

## 渲染管线是什么

渲染管线（Render Pipeline）是将三维场景数据最终输出为屏幕像素颜色的完整处理流程。理解它，是写出高性能 Shader、做好渲染优化的前提。

```
CPU 侧                          GPU 侧
┌──────────────────┐           ┌─────────────────────────────────────┐
│ 场景遍历          │           │ 顶点着色器                            │
│ 视锥剔除          │ DrawCall  │  → 图元装配                           │
│ 排序（透明/不透明）│ ────────→ │  → 光栅化                             │
│ 提交绘制命令      │           │  → 片元着色器                          │
│ 上传 uniform 数据 │           │  → 深度/模板测试                       │
└──────────────────┘           │  → 混合 → 帧缓冲                       │
                               └─────────────────────────────────────┘
```

---

## 一、Built-in 渲染管线

### 1.1 前向渲染（Forward Rendering）

前向渲染是 Built-in 管线的默认模式：

```
对每个物体：
  对每个影响它的光源：
    执行一次渲染 Pass

总 DrawCall 数 ≈ 物体数 × 平均受光源数
```

**优点**：实现简单，MSAA 支持好，适合移动端
**缺点**：多光源场景性能急剧下降

```glsl
// Built-in 前向渲染 Shader 结构
Shader "Game/Character"
{
    SubShader
    {
        // Pass 1：基础光照（主方向光）
        Pass
        {
            Tags { "LightMode" = "ForwardBase" }
            // 处理环境光 + 主光源
        }
        
        // Pass 2~N：额外光源（每个点光源一个 Pass）
        Pass
        {
            Tags { "LightMode" = "ForwardAdd" }
            Blend One One // 加法混合
            // 处理一个额外光源
        }
    }
}
```

### 1.2 延迟渲染（Deferred Rendering）

```
第一步（Geometry Pass）：所有物体渲染到 G-Buffer
  G-Buffer 0: Albedo (RGB) + Occlusion (A)
  G-Buffer 1: Specular (RGB) + Smoothness (A)  
  G-Buffer 2: World Normal (RGB)
  Depth Buffer: 深度值

第二步（Lighting Pass）：对每个光源做一次屏幕空间光照计算
  - 方向光：全屏 Quad
  - 点光/聚光：光源体积球/锥
```

**优点**：光源数量不影响场景物体的渲染开销
**缺点**：不支持 MSAA（G-Buffer 带宽大），透明物体需要回退前向渲染

---

## 二、URP 架构解析

### 2.1 URP 的核心设计理念

URP（Universal Render Pipeline）相比 Built-in 有几个根本性改变：

1. **统一的 Forward+ 渲染**：改善多光源性能
2. **可编程的渲染流程**：通过 Renderer Feature 插入自定义 Pass
3. **SRP Batcher**：大幅降低 CPU SetPass 开销
4. **更好的移动端优化**：Tile-Based 友好

### 2.2 SRP Batcher 原理

```
传统 DrawCall 流程：
  设置材质属性 → SetPass → DrawMesh → 设置材质属性 → SetPass → DrawMesh...

SRP Batcher 流程：
  将所有 Shader 的 per-object 属性上传到 GPU 内存（SSBO/CBUFFER）
  → 一次 SetPass（相同 Shader Variant 只需一次）
  → 多次 DrawMesh（从 GPU 内存读取各自的属性）
```

**关键**：SRP Batcher 要求所有 per-object 属性都在 `UnityPerMaterial` CBUFFER 中：

```glsl
// ✅ 兼容 SRP Batcher
CBUFFER_START(UnityPerMaterial)
    float4 _BaseColor;
    float4 _BaseMap_ST;
    float _Metallic;
    float _Smoothness;
CBUFFER_END

// ❌ 不兼容 SRP Batcher（属性在 CBUFFER 外）
float4 _BaseColor; // 这样写会导致 SRP Batcher 失效
```

### 2.3 Renderer Feature：自定义渲染 Pass

```csharp
// 自定义渲染特性示例：绘制外描边
public class OutlineRendererFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class Settings
    {
        public Material outlineMaterial;
        public float outlineWidth = 2f;
        public Color outlineColor = Color.white;
        public RenderPassEvent renderPassEvent = RenderPassEvent.AfterRenderingOpaques;
    }

    public Settings settings = new();
    private OutlinePass _outlinePass;

    public override void Create()
    {
        _outlinePass = new OutlinePass(settings);
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        // 只在非编辑器模式（或根据需要）添加
        renderer.EnqueuePass(_outlinePass);
    }
}

public class OutlinePass : ScriptableRenderPass
{
    private readonly OutlineRendererFeature.Settings _settings;
    private readonly List<ShaderTagId> _shaderTagIds;
    private FilteringSettings _filteringSettings;
    private RenderStateBlock _renderStateBlock;
    
    // 使用 RTHandle 管理临时 RT
    private RTHandle _tempColorTarget;

    public OutlinePass(OutlineRendererFeature.Settings settings)
    {
        _settings = settings;
        renderPassEvent = settings.renderPassEvent;
        
        _shaderTagIds = new List<ShaderTagId>
        {
            new ShaderTagId("UniversalForward"),
            new ShaderTagId("SRPDefaultUnlit"),
        };
        
        _filteringSettings = new FilteringSettings(RenderQueueRange.opaque);
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        // 申请临时 RT
        var descriptor = renderingData.cameraData.cameraTargetDescriptor;
        RenderingUtils.ReAllocateIfNeeded(ref _tempColorTarget, descriptor, name: "_TempOutlineRT");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get("Outline Pass");
        
        using (new ProfilingScope(cmd, new ProfilingSampler("Outline")))
        {
            context.ExecuteCommandBuffer(cmd);
            cmd.Clear();
            
            // 1. 渲染目标物体到临时 RT（法线外扩描边）
            var drawSettings = CreateDrawingSettings(_shaderTagIds, ref renderingData, 
                SortingCriteria.CommonOpaque);
            drawSettings.overrideMaterial = _settings.outlineMaterial;
            
            context.DrawRenderers(renderingData.cullResults, ref drawSettings, ref _filteringSettings);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // 释放临时 RT
        RTHandles.Release(_tempColorTarget);
    }
}
```

---

## 三、移动端 GPU 架构与渲染优化

### 3.1 TBDR（Tile-Based Deferred Rendering）

移动端 GPU（Mali、Adreno、PowerVR）与桌面端 GPU 架构根本不同：

```
桌面端 IMR（Immediate Mode Rendering）：
  每个三角形立即处理，直接写入帧缓冲（显存）
  优点：实现简单，适合大场景
  缺点：频繁读写帧缓冲，带宽消耗大，功耗高

移动端 TBDR（Tile-Based Deferred Rendering）：
  1. 将屏幕分成 16x16 或 32x32 的 Tile
  2. 第一步（Binning）：确定每个三角形影响哪些 Tile
  3. 第二步（Rendering）：逐 Tile 处理，使用片上缓存（On-Chip Cache）
  4. 所有 Tile 处理完后，一次性写回主存

好处：
  - 深度测试在片上进行，无需读写主存 → 节省带宽
  - HSR（Hidden Surface Removal）在片段着色之前剔除遮挡片段 → 节省 ALU
```

### 3.2 移动端的关键优化原则

**原则一：降低带宽消耗**

```
带宽消耗来源：
- RT Read/Write（每帧读写帧缓冲）
- 纹理采样（尤其是大尺寸纹理）
- 顶点缓冲读取

✅ 优化手段：
- 使用 ASTC 纹理压缩（相比 RGBA32 减少 75~90% 内存和带宽）
- 避免不必要的 RT 切换（每次切换 RT 都需要 Resolve）
- 合并 Post-processing Pass，减少 RT 读写次数
- 使用 Mipmap（GPU 自动采样合适层级）
```

**原则二：避免过度绘制（Overdraw）**

```
Overdraw = 同一像素被绘制多次
移动端 GPU 的像素着色能力有限，高 Overdraw 直接导致掉帧

测量方法：
  Unity Scene 视图 → Overdraw 模式
  越亮 = Overdraw 越严重（4x 以上开始有问题）

✅ 优化手段：
- 不透明物体：从前到后排序，Early-Z 剔除
- 透明物体：减少层叠，能用 Alpha Test 的不用 Alpha Blend
- UI：合并同层 Canvas，减少重叠
- 粒子：控制粒子尺寸，避免大面积半透明覆盖
```

**原则三：Shader 复杂度控制**

```glsl
// ❌ 移动端慎用的操作
discard; // 或 clip()：打断 HSR 早期剔除
textureLod(); // 显式 LOD 采样（部分设备性能差）
ddx() / ddy(); // 屏幕空间导数

// ❌ 复杂数学运算（改为查表或近似）
float spec = pow(dot(N, H), 128.0); // pow 很慢

// ✅ 使用近似或查表
float spec = exp2(log2(max(0.0, dot(N, H))) * 128.0); // 稍快
// 或者预烘焙高光 LUT 贴图
```

### 3.3 MSAA vs 后处理抗锯齿

```
移动端推荐：MSAA 4x
  - TBDR 架构下，MSAA 几乎是"免费"的（在片上完成）
  - 相比 FXAA/TAA，视觉质量更好，无运动模糊问题

桌面端：TAA（时间性抗锯齿）
  - 质量最高，但有一帧延迟，需要处理鬼影（Ghosting）

低端机：FXAA
  - 纯后处理，性能开销最小，但边缘质量一般
```

---

## 四、URP 自定义 Shader 编写规范

### 4.1 标准 URP Unlit Shader 模板

```glsl
Shader "Game/URP_Unlit_Template"
{
    Properties
    {
        _BaseMap ("Base Map", 2D) = "white" {}
        _BaseColor ("Base Color", Color) = (1,1,1,1)
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
            Name "URPUnlit"
            Tags { "LightMode" = "UniversalForward" }
            
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            
            // URP 必要的 include
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            // SRP Batcher 兼容的 CBUFFER
            CBUFFER_START(UnityPerMaterial)
                float4 _BaseMap_ST;
                float4 _BaseColor;
            CBUFFER_END
            
            TEXTURE2D(_BaseMap);
            SAMPLER(sampler_BaseMap);
            
            struct Attributes
            {
                float4 positionOS   : POSITION;
                float2 uv           : TEXCOORD0;
                UNITY_VERTEX_INPUT_INSTANCE_ID // GPU Instancing 支持
            };
            
            struct Varyings
            {
                float4 positionHCS  : SV_POSITION;
                float2 uv           : TEXCOORD0;
                UNITY_VERTEX_OUTPUT_STEREO // VR 支持
            };
            
            Varyings vert(Attributes input)
            {
                Varyings output;
                UNITY_SETUP_INSTANCE_ID(input);
                UNITY_INITIALIZE_VERTEX_OUTPUT_STEREO(output);
                
                // 使用 URP 提供的坐标变换函数（比 UnityObjectToClipPos 更高效）
                output.positionHCS = TransformObjectToHClip(input.positionOS.xyz);
                output.uv = TRANSFORM_TEX(input.uv, _BaseMap);
                return output;
            }
            
            half4 frag(Varyings input) : SV_Target
            {
                UNITY_SETUP_STEREO_EYE_INDEX_POST_VERTEX(input);
                
                half4 texColor = SAMPLE_TEXTURE2D(_BaseMap, sampler_BaseMap, input.uv);
                return texColor * _BaseColor;
            }
            ENDHLSL
        }
        
        // 阴影 Pass（接收/投射阴影）
        UsePass "Universal Render Pipeline/Lit/ShadowCaster"
    }
}
```

### 4.2 PBR Lit Shader 关键部分

```glsl
// URP PBR 光照计算
#include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Lighting.hlsl"

half4 frag(Varyings input) : SV_Target
{
    // 构建 InputData
    InputData inputData;
    InitializeInputData(input, normalWS, inputData);
    
    // 构建 SurfaceData
    SurfaceData surfaceData;
    surfaceData.albedo = albedo;
    surfaceData.metallic = metallic;
    surfaceData.smoothness = smoothness;
    surfaceData.normalTS = normalTS;
    surfaceData.occlusion = occlusion;
    surfaceData.alpha = alpha;
    // ...
    
    // URP 标准光照计算（自动处理实时光 + 烘焙光 + 阴影）
    return UniversalFragmentPBR(inputData, surfaceData);
}
```

---

## 五、渲染调试与性能分析

### 5.1 关键性能指标

```
CPU 侧：
  SetPass Calls：不同 Shader Variant 的切换次数（SRP Batcher 后可大幅降低）
  Draw Calls：实际绘制调用次数
  Total Batches：合批后的实际批次数

GPU 侧（通过 GPU Profiler 查看）：
  Vertex Processing：顶点着色器耗时
  Fragment Processing：片元着色器耗时
  Texture Memory：纹理占用
  Frame Time：总帧时间
```

### 5.2 Frame Debugger 使用技巧

```
1. 打开：Window → Analysis → Frame Debugger → Enable
2. 查看每个 DrawCall 的：
   - 使用的 Shader 和 Pass
   - 绑定的纹理
   - 输入的顶点数/三角形数
   - RT 状态

3. 关注点：
   - 同一帧内 RT 切换次数（过多说明后处理链设计有问题）
   - 透明物体绘制顺序（应从后到前）
   - Shadow Map 渲染（消耗多少 DrawCall）
```

### 5.3 Shader 热重载工作流

```csharp
// 编辑器下自动监听 Shader 文件变化并重新编译
#if UNITY_EDITOR
using UnityEditor;

[InitializeOnLoad]
public static class ShaderHotReload
{
    static ShaderHotReload()
    {
        // 监听资源导入事件
        AssetDatabase.importPackageCompleted += _ => RefreshShaders();
    }
    
    static void RefreshShaders()
    {
        // 强制重新编译所有 Shader
        ShaderUtil.ClearCurrentShaderErrors(null);
        // 实际项目中可以只重编特定 Shader
    }
}
#endif
```

---

## 总结

理解渲染管线，本质上是在建立一个**从数据到像素的完整心智模型**：

1. **CPU 端**：剔除、排序、合批 → 减少 DrawCall
2. **顶点阶段**：坐标变换、法线变换 → 正确的空间转换
3. **光栅化**：插值、Early-Z → 理解 HSR/MSAA
4. **片元阶段**：光照模型、纹理采样 → 性能热点
5. **输出合并**：深度测试、Alpha 混合 → 透明物体的处理

> **下一篇**：[移动端 GPU 架构深度解析：Tile-Based 渲染与带宽优化]
