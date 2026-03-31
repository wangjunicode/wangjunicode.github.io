---
title: Unity URP自定义渲染特性：ScriptableRenderPass实战
published: 2026-03-31
description: 深度解析Unity URP（Universal Render Pipeline）自定义渲染特性开发，涵盖ScriptableRendererFeature和ScriptableRenderPass的创建、RenderTexture采样与后处理、轮廓线描边效果实现、屏幕空间效果（扫描线/脉冲波）、自定义深度/法线预处理Pass，以及性能分析与优化要点。
tags: [Unity, URP, ScriptableRenderPass, 渲染管线, Shader]
category: 渲染管线
draft: false
---

## 一、URP 渲染特性架构

```
ScriptableRendererFeature（特性入口）
└── ScriptableRenderPass（渲染Pass执行）
    ├── Configure()         ← 配置RT和目标
    ├── Execute()           ← 执行渲染命令
    └── FrameCleanup()      ← 清理资源
```

---

## 二、轮廓线描边特性

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// URP 轮廓线描边渲染特性
/// 使用 Sobel 边缘检测（基于深度/法线）
/// </summary>
public class OutlineRendererFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class OutlineSettings
    {
        public RenderPassEvent Event = RenderPassEvent.BeforeRenderingPostProcessing;
        public Material OutlineMaterial;        // 轮廓线 Shader 材质
        public LayerMask OutlineLayer;          // 需要轮廓线的层级
        [Range(1, 4)] public float Width = 2f;
        public Color OutlineColor = Color.white;
    }

    [SerializeField] private OutlineSettings settings = new OutlineSettings();
    private OutlineRenderPass outlinePass;

    public override void Create()
    {
        outlinePass = new OutlineRenderPass(settings);
        outlinePass.renderPassEvent = settings.Event;
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (settings.OutlineMaterial == null) return;
        
        outlinePass.Setup(renderer.cameraColorTargetHandle);
        renderer.EnqueuePass(outlinePass);
    }

    protected override void Dispose(bool disposing)
    {
        outlinePass?.Dispose();
    }
}

/// <summary>
/// 轮廓线渲染 Pass
/// </summary>
public class OutlineRenderPass : ScriptableRenderPass, System.IDisposable
{
    private OutlineRendererFeature.OutlineSettings settings;
    private RTHandle source;
    private RTHandle tempRT;
    private RTHandle objectRT;         // 物体遮罩
    
    private static readonly int OutlineColorId = Shader.PropertyToID("_OutlineColor");
    private static readonly int OutlineWidthId = Shader.PropertyToID("_OutlineWidth");
    private static readonly int MaskTextureId  = Shader.PropertyToID("_MaskTexture");

    public OutlineRenderPass(OutlineRendererFeature.OutlineSettings settings)
    {
        this.settings = settings;
    }

    public void Setup(RTHandle sourceHandle)
    {
        source = sourceHandle;
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        
        // 分配临时 RT
        RenderingUtils.ReAllocateIfNeeded(ref tempRT, desc, name: "_TempRT");
        RenderingUtils.ReAllocateIfNeeded(ref objectRT, desc, name: "_ObjectMaskRT");
        
        // 配置 Shader 参数
        settings.OutlineMaterial.SetColor(OutlineColorId, settings.OutlineColor);
        settings.OutlineMaterial.SetFloat(OutlineWidthId, settings.Width);
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("Outline Pass");
        
        using (new ProfilingScope(cmd, new ProfilingSampler("Outline Effect")))
        {
            // 步骤1：渲染指定层到遮罩RT（白色）
            cmd.SetRenderTarget(objectRT);
            cmd.ClearRenderTarget(true, true, Color.clear);
            
            // 渲染outline层的物体（纯白）
            DrawingSettings drawingSettings = CreateDrawingSettings(
                new ShaderTagId("UniversalForward"), 
                ref renderingData, 
                SortingCriteria.CommonTransparent);
            
            FilteringSettings filteringSettings = new FilteringSettings(
                RenderQueueRange.all, settings.OutlineLayer);
            
            context.DrawRenderers(renderingData.cullResults, ref drawingSettings, 
                ref filteringSettings);
            
            // 步骤2：使用 Sobel 边缘检测生成轮廓线
            settings.OutlineMaterial.SetTexture(MaskTextureId, objectRT);
            
            // Blit：source → tempRT（应用轮廓线效果）
            Blitter.BlitCameraTexture(cmd, source, tempRT, settings.OutlineMaterial, 0);
            
            // 步骤3：将结果复制回 Camera Color
            Blitter.BlitCameraTexture(cmd, tempRT, source);
        }
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        // Pass 完成后的清理
    }

    public void Dispose()
    {
        tempRT?.Release();
        objectRT?.Release();
    }
}
```

---

## 三、屏幕空间扫描线特效

```csharp
/// <summary>
/// 扫描线/脉冲波 URP Renderer Feature
/// 适用场景：技能范围指示、雷达扫描、护盾激活
/// </summary>
public class ScanLineFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class ScanSettings
    {
        public RenderPassEvent Event = RenderPassEvent.BeforeRenderingPostProcessing;
        public Material ScanMaterial;
        [ColorUsage(true, true)] public Color ScanColor = Color.cyan;
        public float ScanWidth = 0.05f;
        public float ScanSpeed = 1f;
    }

    [SerializeField] private ScanSettings settings;
    private ScanRenderPass scanPass;

    public override void Create()
    {
        if (settings.ScanMaterial == null) return;
        scanPass = new ScanRenderPass(settings);
        scanPass.renderPassEvent = settings.Event;
    }

    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (scanPass == null) return;
        scanPass.Setup(renderer.cameraColorTargetHandle);
        renderer.EnqueuePass(scanPass);
    }
}

public class ScanRenderPass : ScriptableRenderPass
{
    private ScanLineFeature.ScanSettings settings;
    private RTHandle source;
    private RTHandle tempRT;
    
    private static readonly int ScanColorId = Shader.PropertyToID("_ScanColor");
    private static readonly int ScanWidthId = Shader.PropertyToID("_ScanWidth");
    private static readonly int ScanProgressId = Shader.PropertyToID("_ScanProgress");
    private static readonly int ScanOriginId = Shader.PropertyToID("_ScanOrigin");
    
    // 扫描状态
    private bool isScanning;
    private float scanProgress;
    private Vector3 scanOrigin;
    private float scanRadius;

    public ScanRenderPass(ScanLineFeature.ScanSettings settings)
    {
        this.settings = settings;
    }

    public void Setup(RTHandle sourceHandle) { source = sourceHandle; }

    public void TriggerScan(Vector3 worldOrigin, float maxRadius)
    {
        isScanning = true;
        scanProgress = 0f;
        scanOrigin = worldOrigin;
        scanRadius = maxRadius;
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        RenderingUtils.ReAllocateIfNeeded(ref tempRT, desc, name: "_ScanTempRT");
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        if (!isScanning) return;
        
        // 更新扫描进度
        scanProgress += Time.deltaTime * settings.ScanSpeed;
        if (scanProgress >= 1f)
        {
            isScanning = false;
            return;
        }
        
        var cmd = CommandBufferPool.Get("Scan Line");
        
        // 设置材质参数
        settings.ScanMaterial.SetColor(ScanColorId, settings.ScanColor);
        settings.ScanMaterial.SetFloat(ScanWidthId, settings.ScanWidth);
        settings.ScanMaterial.SetFloat(ScanProgressId, scanProgress);
        
        // 扫描原点（屏幕空间）
        Vector3 screenPos = renderingData.cameraData.camera.WorldToViewportPoint(scanOrigin);
        settings.ScanMaterial.SetVector(ScanOriginId, screenPos);
        
        Blitter.BlitCameraTexture(cmd, source, tempRT, settings.ScanMaterial, 0);
        Blitter.BlitCameraTexture(cmd, tempRT, source);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

---

## 四、对应的 Shader（HLSL）

```hlsl
// OutlineEffect.shader（轮廓线 Sobel 检测）
Shader "Hidden/OutlineEffect"
{
    Properties
    {
        _MainTex ("Source", 2D) = "white" {}
        _MaskTexture ("Mask", 2D) = "white" {}
        _OutlineColor ("Outline Color", Color) = (1,1,1,1)
        _OutlineWidth ("Width", Float) = 1.0
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex Vert
            #pragma fragment Frag
            
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            #include "Packages/com.unity.render-pipelines.core/Runtime/Utilities/Blit.hlsl"
            
            TEXTURE2D(_MaskTexture);
            SAMPLER(sampler_MaskTexture);
            
            float4 _OutlineColor;
            float _OutlineWidth;
            
            float SobelSample(float2 uv, float2 texelSize, float offset)
            {
                // Sobel X
                float gx = 
                    -1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(-offset, -offset) * texelSize).r +
                    -2 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(-offset,  0) * texelSize).r +
                    -1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(-offset,  offset) * texelSize).r +
                     1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2( offset, -offset) * texelSize).r +
                     2 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2( offset,  0) * texelSize).r +
                     1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2( offset,  offset) * texelSize).r;
                
                // Sobel Y
                float gy = 
                    -1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(-offset, -offset) * texelSize).r +
                    -2 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(0,        -offset) * texelSize).r +
                    -1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2( offset, -offset) * texelSize).r +
                     1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(-offset,  offset) * texelSize).r +
                     2 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2(0,         offset) * texelSize).r +
                     1 * SAMPLE_TEXTURE2D(_MaskTexture, sampler_MaskTexture, uv + float2( offset,  offset) * texelSize).r;
                
                return sqrt(gx * gx + gy * gy);
            }
            
            half4 Frag(Varyings input) : SV_Target
            {
                float2 uv = input.texcoord;
                half4 color = SAMPLE_TEXTURE2D(_BlitTexture, sampler_LinearClamp, uv);
                
                float2 texelSize = float2(
                    _OutlineWidth / _ScreenParams.x,
                    _OutlineWidth / _ScreenParams.y);
                
                float edge = SobelSample(uv, texelSize, 1.0);
                edge = saturate(edge * 2.0);
                
                return lerp(color, _OutlineColor, edge * _OutlineColor.a);
            }
            ENDHLSL
        }
    }
}
```

---

## 五、URP 渲染特性开发清单

| 步骤 | 内容 |
|------|------|
| 1 | 创建 ScriptableRendererFeature 子类 |
| 2 | 在 Create() 中初始化 RenderPass |
| 3 | 在 AddRenderPasses() 中注册 Pass |
| 4 | RenderPass.Execute() 执行 CommandBuffer |
| 5 | 使用 Blitter.BlitCameraTexture 代替 Blit |
| 6 | 使用 RenderingUtils.ReAllocateIfNeeded 管理 RT |
| 7 | 在 Dispose() 中释放所有 RTHandle |
| 8 | 使用 ProfilingScope 标记性能监测点 |

**注意：URP 12+ 改用 RTHandle 系统替代旧的 RenderTexture，Blit API 也改用 Blitter 类，注意版本差异。**
