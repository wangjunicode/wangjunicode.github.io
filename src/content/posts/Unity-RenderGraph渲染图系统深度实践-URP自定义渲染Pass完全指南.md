---
title: Unity RenderGraph渲染图系统深度实践：URP自定义渲染Pass完全指南
published: 2026-04-16
description: 深度解析Unity RenderGraph（渲染图）系统的设计原理与工程实践，涵盖ResourceHandle资源管理、RasterPass/ComputePass构建、自动资源生命周期、帧图优化、URP ScriptableRenderPass迁移与完整代码示例。
tags: [Unity, RenderGraph, URP, 渲染管线, 图形编程]
category: 渲染技术
draft: false
---

# Unity RenderGraph渲染图系统深度实践：URP自定义渲染Pass完全指南

## 一、RenderGraph 概述与设计动机

### 1.1 传统渲染管线的痛点

在 RenderGraph 出现之前，Unity 的自定义渲染通常依赖 `CommandBuffer` + `ScriptableRenderPass`，存在以下问题：

```
传统渲染痛点：
┌─────────────────────────────────────────┐
│ 1. 资源生命周期难以管理                    │
│    - RenderTexture 手动分配/释放           │
│    - 帧间资源复用逻辑复杂                  │
│                                           │
│ 2. 渲染依赖关系不透明                     │
│    - Pass 执行顺序由代码位置决定           │
│    - 读写冲突难以检测                     │
│                                           │
│ 3. 无法进行全局优化                       │
│    - 无用 Pass 无法自动剔除               │
│    - 内存带宽浪费                         │
│                                           │
│ 4. 多平台适配困难                         │
│    - 需手动处理 MSAA、Tile-based 差异     │
└─────────────────────────────────────────┘
```

### 1.2 RenderGraph 的核心思想

RenderGraph（帧图/渲染图）借鉴 **有向无环图（DAG）** 的思想，将整帧渲染描述为一张资源依赖图：

```
RenderGraph 帧图示意：
                    ┌──────────┐
                    │  GBuffer │
                    │   Pass   │
                    └────┬─────┘
                         │ ColorTex, NormalTex, DepthTex
                ┌────────▼────────┐
                │  Lighting Pass  │
                └────────┬────────┘
                         │ LightingTex
           ┌─────────────▼──────────────┐
           │      Post-Process Pass      │
           └─────────────┬──────────────┘
                         │ FinalTex
                    ┌────▼─────┐
                    │  Blit to │
                    │ Backbuf  │
                    └──────────┘

✓ 自动分析依赖关系
✓ 无引用资源自动跳过
✓ 瞬态资源自动复用内存
```

### 1.3 RenderGraph 的优势

| 特性 | 传统 CommandBuffer | RenderGraph |
|------|-------------------|-------------|
| 资源管理 | 手动 | 自动（生命周期追踪）|
| Pass 剔除 | ❌ | ✓ 无引用自动剔除 |
| 内存复用 | ❌ | ✓ 瞬态资源自动复用 |
| 依赖分析 | ❌ | ✓ 自动屏障/同步 |
| 调试支持 | 有限 | ✓ Frame Debugger 完整显示 |
| Tile GPU 优化 | ❌ | ✓ On-chip memory 利用 |

---

## 二、RenderGraph 核心 API 详解

### 2.1 项目配置

首先确保 Unity 版本（2023.1+ 或 6.x）与 URP 包版本匹配：

```csharp
// URP Asset 设置（Inspector）
// Universal Render Pipeline Asset:
//   Intermediate Texture: Auto（让 RenderGraph 决定）
//   Store Actions: SubpassInput（移动端优化）

// 在 URP Asset 中启用 RenderGraph:
// Edit > Project Settings > Graphics > URP Global Settings
// ✓ Enable Render Graph Compatibility Mode (Unity 6)
```

### 2.2 资源句柄（ResourceHandle）体系

RenderGraph 使用句柄而非实际资源引用：

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.RenderGraphModule;
using UnityEngine.Rendering.Universal;

/// <summary>
/// RenderGraph 资源句柄类型总览
/// </summary>
public static class RenderGraphResourceTypes
{
    // 纹理句柄 - 最常用
    // TextureHandle → 对应 RTHandle / RenderTexture
    
    // 计算缓冲区句柄
    // BufferHandle → 对应 GraphicsBuffer / ComputeBuffer
    
    // 加速结构句柄（光追）
    // RayTracingAccelerationStructureHandle
    
    // 外部资源导入（已有的 RTHandle）
    // ImportedTextureHandle → 不由 RenderGraph 管理生命周期
}

/// <summary>
/// 纹理描述符构建示例
/// </summary>
public class TextureDescriptorExamples
{
    public static TextureHandle CreateColorTexture(RenderGraph renderGraph, 
        RenderingData renderingData)
    {
        var cameraData = renderingData.cameraData;
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        
        // 构建纹理描述符
        var textureDesc = new TextureDesc(desc.width, desc.height)
        {
            colorFormat = GraphicsFormat.R16G16B16A16_SFloat,
            depthBufferBits = DepthBits.None,
            msaaSamples = MSAASamples.None,
            filterMode = FilterMode.Bilinear,
            wrapMode = TextureWrapMode.Clamp,
            enableRandomWrite = false,      // 非 UAV
            useMipMap = false,
            name = "MyCustomColorTexture"   // Frame Debugger 中显示的名称
        };
        
        // 创建瞬态纹理（帧内自动分配/释放）
        return renderGraph.CreateTexture(textureDesc);
    }
    
    public static TextureHandle CreateDepthTexture(RenderGraph renderGraph,
        RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        
        var depthDesc = new TextureDesc(desc.width, desc.height)
        {
            colorFormat = GraphicsFormat.None,
            depthBufferBits = DepthBits.Depth32,    // 或 Depth24Stencil8
            msaaSamples = MSAASamples.None,
            name = "MyCustomDepthTexture"
        };
        
        return renderGraph.CreateTexture(depthDesc);
    }
    
    public static TextureHandle CreateComputeTexture(RenderGraph renderGraph,
        int width, int height)
    {
        // UAV 纹理（Compute Shader 写入）
        var uavDesc = new TextureDesc(width, height)
        {
            colorFormat = GraphicsFormat.R32G32B32A32_SFloat,
            depthBufferBits = DepthBits.None,
            msaaSamples = MSAASamples.None,
            enableRandomWrite = true,       // 必须开启 UAV
            name = "ComputeOutputTexture"
        };
        
        return renderGraph.CreateTexture(uavDesc);
    }
}
```

### 2.3 RasterPass（光栅化 Pass）

```csharp
/// <summary>
/// 自定义 Raster Pass 完整实现
/// </summary>
public class CustomBlurRenderPass : ScriptableRenderPass
{
    private Material _blurMaterial;
    private int _blurIterations;
    
    // 传递给 PassData 的参数容器（避免装箱分配）
    private class PassData
    {
        public TextureHandle sourceTexture;
        public TextureHandle tempTexture;
        public Material blurMaterial;
        public int iterations;
        public Vector4 blurDirection;
    }
    
    public CustomBlurRenderPass(Material blurMaterial, int iterations)
    {
        _blurMaterial = blurMaterial;
        _blurIterations = iterations;
        
        // 设置 Pass 注入点
        renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
        
        // 标记 Pass 支持 RenderGraph
        requiresIntermediateTexture = false;
    }
    
    // Unity 6 / URP 17+ 使用此方法替代 Execute
    public override void RecordRenderGraph(RenderGraph renderGraph, 
        FrameResources frameResources, ref RenderingData renderingData)
    {
        // 获取相机颜色缓冲
        var cameraColorHandle = renderingData.cameraData.renderer.cameraColorTargetHandle;
        
        // 从 FrameResources 获取 TextureHandle
        // Unity 6: 使用 UniversalRenderer.GetCameraColorBackBuffer
        TextureHandle cameraColor = frameResources.GetTexture(UniversalResource.CameraColor);
        
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        
        // 创建临时纹理
        TextureHandle tempTex = renderGraph.CreateTexture(
            new TextureDesc(desc.width / 2, desc.height / 2)
            {
                colorFormat = GraphicsFormat.R8G8B8A8_UNorm,
                depthBufferBits = DepthBits.None,
                name = "BlurTempTexture"
            });
        
        // 水平模糊 Pass
        using (var builder = renderGraph.AddRasterRenderPass<PassData>(
            "Horizontal Blur Pass", out var passData))
        {
            // 声明资源使用
            passData.sourceTexture = builder.UseTexture(cameraColor);    // 读取
            passData.tempTexture = builder.SetRenderAttachment(tempTex, 0); // 写入（颜色目标）
            passData.blurMaterial = _blurMaterial;
            passData.blurDirection = new Vector4(1f / desc.width, 0, 0, 0);
            
            // 允许 Pass 被剔除的条件（false = 永远执行）
            builder.AllowPassCulling(false);
            
            // 设置渲染函数（静态方法，避免闭包分配）
            builder.SetRenderFunc(static (PassData data, RasterGraphContext ctx) =>
            {
                ExecuteBlurPass(ctx.cmd, data.sourceTexture, data.blurMaterial, data.blurDirection);
            });
        }
        
        // 垂直模糊 Pass（依赖水平 Pass 的输出）
        using (var builder = renderGraph.AddRasterRenderPass<PassData>(
            "Vertical Blur Pass", out var passData))
        {
            passData.sourceTexture = builder.UseTexture(tempTex);
            passData.tempTexture = builder.SetRenderAttachment(cameraColor, 0);
            passData.blurMaterial = _blurMaterial;
            passData.blurDirection = new Vector4(0, 1f / desc.height, 0, 0);
            
            builder.AllowPassCulling(false);
            
            builder.SetRenderFunc(static (PassData data, RasterGraphContext ctx) =>
            {
                ExecuteBlurPass(ctx.cmd, data.sourceTexture, data.blurMaterial, data.blurDirection);
            });
        }
    }
    
    private static void ExecuteBlurPass(RasterCommandBuffer cmd, TextureHandle source,
        Material material, Vector4 direction)
    {
        material.SetVector("_BlurDirection", direction);
        // 使用 Blitter 工具类（URP 推荐方式）
        Blitter.BlitTexture(cmd, source, new Vector4(1, 1, 0, 0), material, 0);
    }
    
    // 兼容旧版（非 RenderGraph）的 Execute 方法
    [System.Obsolete("Use RecordRenderGraph instead")]
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        // 留空或实现降级逻辑
    }
}
```

### 2.4 ComputePass（计算 Pass）

```csharp
/// <summary>
/// Compute Shader Pass 在 RenderGraph 中的实现
/// </summary>
public class ComputeSkinningPass : ScriptableRenderPass
{
    private ComputeShader _skinningCS;
    private int _kernelIndex;
    
    private class SkinningPassData
    {
        public TextureHandle outputTexture;
        public BufferHandle boneMatricesBuffer;
        public BufferHandle vertexBuffer;
        public ComputeShader computeShader;
        public int kernel;
        public int vertexCount;
    }
    
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        // 创建 Compute Buffer
        var boneBuffer = renderGraph.CreateBuffer(
            new BufferDesc(256 * 16, sizeof(float))    // 256 bones × 4x4 matrix
            {
                name = "BoneMatricesBuffer",
                target = GraphicsBuffer.Target.Structured
            });
        
        // 创建输出 UAV 纹理
        var outputTex = renderGraph.CreateTexture(
            new TextureDesc(1024, 1024)
            {
                colorFormat = GraphicsFormat.R32G32B32A32_SFloat,
                enableRandomWrite = true,
                name = "SkinningOutput"
            });
        
        // 添加 Compute Pass
        using (var builder = renderGraph.AddComputePass<SkinningPassData>(
            "GPU Skinning Compute", out var passData))
        {
            // 声明 Buffer 写入
            passData.boneMatricesBuffer = builder.UseBuffer(boneBuffer, AccessFlags.Write);
            // 声明纹理写入（UAV）
            passData.outputTexture = builder.UseTexture(outputTex, AccessFlags.Write);
            passData.computeShader = _skinningCS;
            passData.kernel = _kernelIndex;
            passData.vertexCount = 10000;
            
            builder.SetRenderFunc(static (SkinningPassData data, ComputeGraphContext ctx) =>
            {
                ctx.cmd.SetComputeBufferParam(data.computeShader, data.kernel,
                    "_BoneMatrices", data.boneMatricesBuffer);
                ctx.cmd.SetComputeTextureParam(data.computeShader, data.kernel,
                    "_Output", data.outputTexture);
                
                int threadGroupX = Mathf.CeilToInt(data.vertexCount / 64f);
                ctx.cmd.DispatchCompute(data.computeShader, data.kernel, threadGroupX, 1, 1);
            });
        }
    }
}
```

---

## 三、外部资源导入与跨帧持久化

### 3.1 导入已有 RTHandle

```csharp
/// <summary>
/// 将已存在的 RTHandle 导入到 RenderGraph（不由 RG 管理生命周期）
/// </summary>
public class PersistentTexturePass : ScriptableRenderPass
{
    private RTHandle _persistentRT;
    
    public void Setup(int width, int height)
    {
        // 手动管理的持久化 RTHandle
        _persistentRT = RTHandles.Alloc(
            width, height,
            colorFormat: GraphicsFormat.R16G16B16A16_SFloat,
            filterMode: FilterMode.Bilinear,
            name: "PersistentHistoryBuffer"
        );
    }
    
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        // 导入外部资源（importedResourceParams 控制初始状态）
        ImportResourceParams importParams = new ImportResourceParams()
        {
            clearOnFirstUse = false,    // 不自动清除
            discardOnLastUse = false    // 不自动丢弃（持久化）
        };
        
        TextureHandle persistentHandle = renderGraph.ImportTexture(
            _persistentRT, importParams);
        
        TextureHandle cameraColor = frameResources.GetTexture(UniversalResource.CameraColor);
        
        // 使用持久化纹理（TAA 历史帧混合示例）
        using (var builder = renderGraph.AddRasterRenderPass<TAAPassData>(
            "TAA History Blend", out var passData))
        {
            passData.historyTexture = builder.UseTexture(persistentHandle);  // 读取历史帧
            passData.currentTexture = builder.UseTexture(cameraColor);
            passData.outputTexture = builder.SetRenderAttachment(
                renderGraph.CreateTexture(GetColorDesc(renderingData)), 0);
            
            // 标记历史帧需要在 Pass 后更新
            passData.historyWriteHandle = builder.UseTexture(persistentHandle, AccessFlags.Write);
            
            builder.SetRenderFunc(static (TAAPassData data, RasterGraphContext ctx) =>
            {
                // TAA 混合逻辑
            });
        }
    }
    
    private class TAAPassData
    {
        public TextureHandle historyTexture;
        public TextureHandle currentTexture;
        public TextureHandle outputTexture;
        public TextureHandle historyWriteHandle;
    }
    
    private TextureDesc GetColorDesc(RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        return new TextureDesc(desc.width, desc.height)
        {
            colorFormat = GraphicsFormat.R16G16B16A16_SFloat,
            name = "TAAOutput"
        };
    }
    
    public void Dispose()
    {
        _persistentRT?.Release();
        _persistentRT = null;
    }
}
```

### 3.2 Backbuffer 导入（直接渲染到屏幕）

```csharp
public class BlitToBackbufferPass : ScriptableRenderPass
{
    private Material _finalBlitMaterial;
    
    private class BlitPassData
    {
        public TextureHandle source;
    }
    
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        TextureHandle cameraColor = frameResources.GetTexture(UniversalResource.CameraColor);
        
        // 获取最终 Backbuffer
        // Unity 6 中使用 renderingData.cameraData.renderer 获取
        TextureHandle backbuffer = renderingData.cameraData.renderer.GetCameraColorBackBuffer(renderGraph);
        
        using (var builder = renderGraph.AddRasterRenderPass<BlitPassData>(
            "Final Blit To Backbuffer", out var passData))
        {
            passData.source = builder.UseTexture(cameraColor);
            
            // 设置渲染目标为 Backbuffer
            builder.SetRenderAttachment(backbuffer, 0,
                loadAction: RenderBufferLoadAction.DontCare,
                storeAction: RenderBufferStoreAction.Store);
            
            builder.AllowPassCulling(false);
            
            builder.SetRenderFunc(static (BlitPassData data, RasterGraphContext ctx) =>
            {
                Blitter.BlitTexture(ctx.cmd, data.source, 
                    new Vector4(1, 1, 0, 0), 0, false);
            });
        }
    }
}
```

---

## 四、SubPass（子通道）与 Tile-Based 优化

移动端 GPU 采用 Tile-Based 架构，RenderGraph 可以将多个 Pass 合并为 SubPass，数据常驻 On-Chip Memory，大幅降低带宽消耗：

```csharp
/// <summary>
/// GBuffer + Lighting 使用 SubPass 合并（TBDR 优化）
/// </summary>
public class DeferredSubpassExample : ScriptableRenderPass
{
    private class GBufferData
    {
        public TextureHandle albedoGBuffer;
        public TextureHandle normalGBuffer;
        public TextureHandle depthBuffer;
        public TextureHandle lightingOutput;
    }
    
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        
        // 创建 GBuffer 纹理
        TextureHandle albedoGBuf = renderGraph.CreateTexture(
            new TextureDesc(desc.width, desc.height)
            {
                colorFormat = GraphicsFormat.R8G8B8A8_UNorm,
                name = "GBuffer_Albedo",
                memoryless = MemorylessMode.MSAA  // 移动端 memoryless（不回写主存）
            });
        
        TextureHandle normalGBuf = renderGraph.CreateTexture(
            new TextureDesc(desc.width, desc.height)
            {
                colorFormat = GraphicsFormat.R16G16_SFloat,
                name = "GBuffer_Normal",
                memoryless = MemorylessMode.MSAA
            });
        
        TextureHandle depthBuf = renderGraph.CreateTexture(
            new TextureDesc(desc.width, desc.height)
            {
                colorFormat = GraphicsFormat.None,
                depthBufferBits = DepthBits.Depth32,
                name = "GBuffer_Depth"
            });
        
        TextureHandle lightingOutput = frameResources.GetTexture(UniversalResource.CameraColor);
        
        // === Pass 1: GBuffer 填充 ===
        using (var builder = renderGraph.AddRasterRenderPass<GBufferData>(
            "GBuffer Fill", out var passData))
        {
            passData.albedoGBuffer = builder.SetRenderAttachment(albedoGBuf, 0,
                loadAction: RenderBufferLoadAction.Clear);
            passData.normalGBuffer = builder.SetRenderAttachment(normalGBuf, 1,
                loadAction: RenderBufferLoadAction.Clear);
            passData.depthBuffer = builder.SetRenderAttachmentDepth(depthBuf,
                loadAction: RenderBufferLoadAction.Clear);
            
            builder.SetRenderFunc(static (GBufferData data, RasterGraphContext ctx) =>
            {
                // 渲染不透明物体到 GBuffer
                // ctx.cmd.DrawRenderers(...)
            });
        }
        
        // === Pass 2: Deferred Lighting（SubPass 读取 GBuffer）===
        using (var builder = renderGraph.AddRasterRenderPass<GBufferData>(
            "Deferred Lighting", out var passData))
        {
            // 使用 SetInputAttachment 而非 UseTexture
            // SubPass Input 直接读取 On-Chip Memory（不产生带宽）
            passData.albedoGBuffer = builder.SetInputAttachment(albedoGBuf, 0);
            passData.normalGBuffer = builder.SetInputAttachment(normalGBuf, 1);
            passData.depthBuffer = builder.SetRenderAttachmentDepth(depthBuf,
                loadAction: RenderBufferLoadAction.Load);
            passData.lightingOutput = builder.SetRenderAttachment(lightingOutput, 0);
            
            builder.AllowPassCulling(false);
            
            builder.SetRenderFunc(static (GBufferData data, RasterGraphContext ctx) =>
            {
                // Deferred Lighting Shader 通过 LOAD_FRAMEBUFFER_INPUT 读取 GBuffer
                // ctx.cmd.DrawMesh(fullscreenMesh, Matrix4x4.identity, lightingMaterial);
            });
        }
    }
}
```

对应的 Shader 使用 SubPass Input：

```hlsl
// DeferredLighting.shader (HLSL 片段)
#if defined(SHADER_API_VULKAN) || defined(SHADER_API_METAL)
    // SubPass Input（移动端 On-chip 读取）
    FRAMEBUFFER_INPUT_HALF(0) _GBufferAlbedo;
    FRAMEBUFFER_INPUT_HALF(1) _GBufferNormal;
    
    half4 albedo = LOAD_FRAMEBUFFER_INPUT(0, input.positionCS);
    half4 normal = LOAD_FRAMEBUFFER_INPUT(1, input.positionCS);
#else
    // 桌面端降级为普通纹理采样
    TEXTURE2D(_GBufferAlbedo);
    TEXTURE2D(_GBufferNormal);
    
    half4 albedo = SAMPLE_TEXTURE2D(_GBufferAlbedo, sampler_GBufferAlbedo, input.uv);
    half4 normal = SAMPLE_TEXTURE2D(_GBufferNormal, sampler_GBufferNormal, input.uv);
#endif
```

---

## 五、RenderGraph 调试与可视化

### 5.1 Frame Debugger 集成

```csharp
/// <summary>
/// RenderGraph 调试辅助工具
/// </summary>
public static class RenderGraphDebugHelper
{
    /// <summary>
    /// 在 Pass 中添加调试标记（Frame Debugger 中显示）
    /// </summary>
    public static void AddDebugMarker(RasterCommandBuffer cmd, string markerName)
    {
#if UNITY_EDITOR || DEVELOPMENT_BUILD
        cmd.BeginSample(markerName);
        // ... 渲染命令 ...
        cmd.EndSample(markerName);
#endif
    }
}

// 启用 RenderGraph 可视化（Editor 运行时）
// Window > Analysis > Render Graph Viewer
// 可查看：
// - 每帧 Pass 列表及其资源依赖
// - 被剔除的 Pass（标记为灰色）
// - 资源生命周期（哪帧分配、哪帧释放）
// - 内存复用情况
```

### 5.2 Pass 剔除验证

```csharp
// 验证 Pass 剔除逻辑的测试代码
public class PassCullingTestPass : ScriptableRenderPass
{
    private class TestData
    {
        public TextureHandle output;
    }
    
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        TextureHandle unused = renderGraph.CreateTexture(
            new TextureDesc(16, 16) { name = "UnusedTexture" });
        
        // 此 Pass 的输出 'unused' 没有任何后续 Pass 使用
        // RenderGraph 会自动剔除此 Pass（AllowPassCulling 默认为 true）
        using (var builder = renderGraph.AddRasterRenderPass<TestData>(
            "Should Be Culled Pass", out var passData))
        {
            passData.output = builder.SetRenderAttachment(unused, 0);
            
            // builder.AllowPassCulling(true);  // 默认值，允许剔除
            
            builder.SetRenderFunc(static (TestData data, RasterGraphContext ctx) =>
            {
                // 这里的代码不会被执行（Pass 被剔除）
                Debug.Log("This should never print!");
            });
        }
    }
}
```

---

## 六、完整案例：屏幕空间边缘发光效果

```csharp
/// <summary>
/// 使用 RenderGraph 实现屏幕空间边缘检测发光（Rim Glow）
/// 完整实现：深度边缘检测 → 模糊 → 叠加到主缓冲
/// </summary>
public class ScreenSpaceRimGlowFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class Settings
    {
        public Material rimGlowMaterial;
        public float glowIntensity = 1.5f;
        public int blurRadius = 2;
        [ColorUsage(true, true)]
        public Color glowColor = Color.cyan;
    }
    
    public Settings settings;
    private RimGlowPass _rimGlowPass;
    
    public override void Create()
    {
        if (settings.rimGlowMaterial == null) return;
        _rimGlowPass = new RimGlowPass(settings);
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, 
        ref RenderingData renderingData)
    {
        if (_rimGlowPass == null) return;
        renderer.EnqueuePass(_rimGlowPass);
    }
    
    protected override void Dispose(bool disposing)
    {
        _rimGlowPass?.Dispose();
    }
    
    // ─── 内部 Pass ────────────────────────────────────────────────────────────
    private class RimGlowPass : ScriptableRenderPass, System.IDisposable
    {
        private readonly Settings _settings;
        private static readonly int s_GlowIntensityId = Shader.PropertyToID("_GlowIntensity");
        private static readonly int s_GlowColorId = Shader.PropertyToID("_GlowColor");
        
        private class GlowPassData
        {
            public TextureHandle depthSource;
            public TextureHandle glowMask;
            public TextureHandle glowBlurred;
            public TextureHandle cameraColor;
            public Material material;
            public float intensity;
            public Color color;
        }
        
        public RimGlowPass(Settings settings)
        {
            _settings = settings;
            renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
        }
        
        public override void RecordRenderGraph(RenderGraph renderGraph,
            FrameResources frameResources, ref RenderingData renderingData)
        {
            var desc = renderingData.cameraData.cameraTargetDescriptor;
            
            // 资源创建
            var maskDesc = new TextureDesc(desc.width, desc.height)
            {
                colorFormat = GraphicsFormat.R8_UNorm,
                depthBufferBits = DepthBits.None,
                name = "RimGlowMask"
            };
            var blurDesc = maskDesc;
            blurDesc.name = "RimGlowBlurred";
            
            TextureHandle glowMask = renderGraph.CreateTexture(maskDesc);
            TextureHandle glowBlurred = renderGraph.CreateTexture(blurDesc);
            
            TextureHandle depthTex = frameResources.GetTexture(UniversalResource.CameraDepth);
            TextureHandle cameraColor = frameResources.GetTexture(UniversalResource.CameraColor);
            
            // ── Pass 1: 边缘检测生成 Mask ──
            using (var builder = renderGraph.AddRasterRenderPass<GlowPassData>(
                "RimGlow EdgeDetect", out var passData))
            {
                passData.depthSource = builder.UseTexture(depthTex);
                passData.glowMask = builder.SetRenderAttachment(glowMask, 0);
                passData.material = _settings.rimGlowMaterial;
                
                builder.AllowPassCulling(false);
                builder.SetRenderFunc(static (GlowPassData data, RasterGraphContext ctx) =>
                {
                    ctx.cmd.SetGlobalTexture("_DepthSource", data.depthSource);
                    Blitter.BlitTexture(ctx.cmd, data.depthSource,
                        new Vector4(1, 1, 0, 0), data.material, 0); // Pass 0: 边缘检测
                });
            }
            
            // ── Pass 2: 模糊 Mask ──
            using (var builder = renderGraph.AddRasterRenderPass<GlowPassData>(
                "RimGlow Blur", out var passData))
            {
                passData.glowMask = builder.UseTexture(glowMask);
                passData.glowBlurred = builder.SetRenderAttachment(glowBlurred, 0);
                passData.material = _settings.rimGlowMaterial;
                
                builder.AllowPassCulling(false);
                builder.SetRenderFunc(static (GlowPassData data, RasterGraphContext ctx) =>
                {
                    Blitter.BlitTexture(ctx.cmd, data.glowMask,
                        new Vector4(1, 1, 0, 0), data.material, 1); // Pass 1: 模糊
                });
            }
            
            // ── Pass 3: 叠加到相机颜色 ──
            using (var builder = renderGraph.AddRasterRenderPass<GlowPassData>(
                "RimGlow Composite", out var passData))
            {
                passData.glowBlurred = builder.UseTexture(glowBlurred);
                passData.cameraColor = builder.SetRenderAttachment(cameraColor, 0,
                    loadAction: RenderBufferLoadAction.Load);
                passData.material = _settings.rimGlowMaterial;
                passData.intensity = _settings.glowIntensity;
                passData.color = _settings.glowColor;
                
                builder.AllowPassCulling(false);
                builder.SetRenderFunc(static (GlowPassData data, RasterGraphContext ctx) =>
                {
                    data.material.SetFloat(s_GlowIntensityId, data.intensity);
                    data.material.SetColor(s_GlowColorId, data.color);
                    ctx.cmd.SetGlobalTexture("_GlowBlurred", data.glowBlurred);
                    Blitter.BlitTexture(ctx.cmd, data.cameraColor,
                        new Vector4(1, 1, 0, 0), data.material, 2); // Pass 2: 叠加
                });
            }
        }
        
        // 兼容性静态字段引用
        private static readonly int s_GlowIntensityId = Shader.PropertyToID("_GlowIntensity");
        private static readonly int s_GlowColorId = Shader.PropertyToID("_GlowColor");
        
        public void Dispose() { }
    }
}
```

---

## 七、从 CommandBuffer 迁移到 RenderGraph

```csharp
// ─── 旧代码（CommandBuffer 风格）─────────────────────────────────────────────
public class OldStylePass : ScriptableRenderPass
{
    private RenderTargetHandle _tempRT;
    
    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        cmd.GetTemporaryRT(_tempRT.id, desc);
    }
    
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        CommandBuffer cmd = CommandBufferPool.Get("OldStylePass");
        // ... 手动管理资源 ...
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
    
    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        cmd.ReleaseTemporaryRT(_tempRT.id);
    }
}

// ─── 新代码（RenderGraph 风格）──────────────────────────────────────────────
public class NewStylePass : ScriptableRenderPass
{
    private class PassData { public TextureHandle output; }
    
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        
        // ✓ 无需手动 GetTemporaryRT / ReleaseTemporaryRT
        TextureHandle tempRT = renderGraph.CreateTexture(
            new TextureDesc(desc) { name = "TempRT" });
        
        using (var builder = renderGraph.AddRasterRenderPass<PassData>("NewPass", out var data))
        {
            data.output = builder.SetRenderAttachment(tempRT, 0);
            builder.AllowPassCulling(false);
            // ✓ 无需 CommandBufferPool.Get/Release
            builder.SetRenderFunc(static (PassData d, RasterGraphContext ctx) =>
            {
                // 直接使用 ctx.cmd（RasterCommandBuffer）
            });
        }
        // ✓ 无需 OnCameraCleanup，RenderGraph 自动释放 tempRT
    }
}
```

---

## 八、最佳实践总结

### 8.1 性能优化要点

| 实践 | 说明 |
|------|------|
| **使用静态 Lambda** | `SetRenderFunc` 传入 `static` 方法，避免闭包分配 |
| **PassData 复用** | 避免在 RecordRenderGraph 中每帧 new 对象，可用对象池 |
| **合理设置 AllowPassCulling** | 最终输出 Pass 必须设为 false，中间 Pass 让 RG 决定 |
| **memoryless 纹理** | 中间纹理（不需要回写主存）设置 MemorylessMode.MSAA |
| **SubPass Input** | 移动端 GBuffer 类 Pass 使用 SetInputAttachment 而非 UseTexture |
| **避免重复创建 TextureDesc** | 在 RecordRenderGraph 外缓存 TextureDesc 模板 |

### 8.2 兼容性策略

```csharp
// 同时支持 RenderGraph 和 非RenderGraph 模式
public class CompatiblePass : ScriptableRenderPass
{
    // 新版本（Unity 6+）
    public override void RecordRenderGraph(RenderGraph renderGraph,
        FrameResources frameResources, ref RenderingData renderingData)
    {
        // RenderGraph 实现
    }
    
    // 旧版本兼容（URP 14 及以下）
#pragma warning disable CS0672
    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        // CommandBuffer 实现（降级路径）
    }
#pragma warning restore CS0672
}
```

### 8.3 常见陷阱

```
❌ 错误用法：
   - 在 SetRenderFunc 的 Lambda 中捕获外部变量（产生闭包分配）
   - 对同一纹理同时调用 UseTexture 和 SetRenderAttachment
   - 在 RecordRenderGraph 阶段执行 GPU 命令（应在 SetRenderFunc 中）
   - 导入的外部资源忘记调用 Release（内存泄漏）

✓ 正确用法：
   - 所有参数通过 PassData 结构体传递
   - SetRenderFunc 使用 static 修饰的方法引用
   - 持久化纹理使用 ImportTexture + ImportResourceParams
   - 每帧仅 RecordRenderGraph 一次，执行由 RG 调度
```

---

## 九、总结

Unity RenderGraph 是现代 URP/HDRP 渲染管线的核心基础设施，其核心价值在于：

1. **自动资源管理**：瞬态纹理无需手动 GetTemporaryRT/Release，生命周期由帧图自动追踪
2. **Pass 剔除优化**：无引用输出的 Pass 自动跳过，节省 GPU 时间
3. **TBDR 友好**：SubPass Input / memoryless 纹理使移动端 On-chip Memory 得到充分利用
4. **调试可视化**：Render Graph Viewer 提供完整的帧图可视化，资源流向一目了然
5. **代码结构清晰**：渲染描述与执行分离，RecordRenderGraph 阶段只声明依赖，SetRenderFunc 阶段才执行命令

掌握 RenderGraph 是 Unity 图形开发者走向高级渲染工程的必经之路。
