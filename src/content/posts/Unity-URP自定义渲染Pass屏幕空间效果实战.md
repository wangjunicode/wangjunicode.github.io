---
title: Unity URP自定义渲染Pass：屏幕空间效果实战
published: 2026-03-31
description: 深度解析Unity URP渲染管线的扩展方案，包含ScriptableRenderPass的完整开发流程、ScriptableRendererFeature注册方式、自定义后处理效果实现（描边/扫描线/热成像/X光透视）、Render Pass顺序与插入时机、URP Volume与自定义效果的整合，以及性能注意事项。
tags: [Unity, URP, 自定义渲染, Shader, 后处理]
category: 渲染技术
draft: false
---

## 一、ScriptableRendererFeature 架构

```csharp
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

/// <summary>
/// 自定义渲染特性（注册到 URP Renderer）
/// </summary>
public class OutlineRendererFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class OutlineSettings
    {
        public Material OutlineMaterial;
        public RenderPassEvent RenderEvent = RenderPassEvent.BeforeRenderingPostProcessing;
        [Range(1, 5)] public int OutlineWidth = 2;
        public Color OutlineColor = Color.white;
        public LayerMask OutlineLayer;
    }

    [SerializeField] private OutlineSettings settings = new OutlineSettings();
    
    private OutlineRenderPass outlinePass;

    /// <summary>
    /// 初始化（ScriptableRendererFeature生命周期方法）
    /// </summary>
    public override void Create()
    {
        outlinePass = new OutlineRenderPass(settings);
        outlinePass.renderPassEvent = settings.RenderEvent;
    }

    /// <summary>
    /// 每帧将 Pass 加入渲染队列
    /// </summary>
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (settings.OutlineMaterial == null) return;
        
        outlinePass.Setup(renderer.cameraColorTarget);
        renderer.EnqueuePass(outlinePass);
    }
}

/// <summary>
/// 描边渲染 Pass
/// </summary>
public class OutlineRenderPass : ScriptableRenderPass
{
    private OutlineRendererFeature.OutlineSettings settings;
    private RenderTargetIdentifier cameraColorTarget;
    private RenderTargetHandle tempTexture;
    
    // 绘制轮廓的物体（通过 LayerMask 过滤）
    private static readonly ShaderTagId shaderTagId = new ShaderTagId("UniversalForward");
    private FilteringSettings filteringSettings;

    public OutlineRenderPass(OutlineRendererFeature.OutlineSettings settings)
    {
        this.settings = settings;
        tempTexture.Init("_TempOutlineTexture");
        filteringSettings = new FilteringSettings(
            RenderQueueRange.all, settings.OutlineLayer);
    }

    public void Setup(RenderTargetIdentifier colorTarget)
    {
        cameraColorTarget = colorTarget;
    }

    public override void OnCameraSetup(CommandBuffer cmd, ref RenderingData renderingData)
    {
        // 获取相机的描述符（分辨率/格式等）
        RenderTextureDescriptor desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        
        // 申请临时 RenderTexture
        cmd.GetTemporaryRT(tempTexture.id, desc, FilterMode.Bilinear);
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        if (settings.OutlineMaterial == null) return;
        
        CommandBuffer cmd = CommandBufferPool.Get("OutlinePass");
        
        // 第一步：将目标物体渲染到临时 RT（白色轮廓物体，黑色背景）
        cmd.SetRenderTarget(tempTexture.Identifier());
        cmd.ClearRenderTarget(true, true, Color.black);
        
        context.ExecuteCommandBuffer(cmd);
        cmd.Clear();
        
        // 渲染指定Layer的物体
        DrawingSettings drawingSettings = CreateDrawingSettings(
            shaderTagId, ref renderingData, SortingCriteria.CommonOpaque);
        
        // 使用纯白材质渲染形状
        drawingSettings.overrideMaterial = settings.OutlineMaterial;
        
        context.DrawRenderers(renderingData.cullResults, 
            ref drawingSettings, ref filteringSettings);
        
        // 第二步：后处理（Edge Detection Shader）
        settings.OutlineMaterial.SetFloat("_OutlineWidth", settings.OutlineWidth);
        settings.OutlineMaterial.SetColor("_OutlineColor", settings.OutlineColor);
        
        cmd.Blit(tempTexture.Identifier(), cameraColorTarget, 
            settings.OutlineMaterial, 1); // Pass 1 = 边缘检测+合成
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }

    public override void OnCameraCleanup(CommandBuffer cmd)
    {
        cmd.ReleaseTemporaryRT(tempTexture.id);
    }
}
```

---

## 二、热成像效果

```csharp
/// <summary>
/// 热成像后处理效果
/// </summary>
public class ThermalVisionFeature : ScriptableRendererFeature
{
    [System.Serializable]
    public class Settings
    {
        public Shader ThermalShader;
        public Gradient ThermalGradient;    // 冷→热颜色映射
        public bool Enabled = false;
    }
    
    [SerializeField] private Settings settings;
    private ThermalVisionPass pass;
    
    public override void Create()
    {
        if (settings.ThermalShader == null) return;
        pass = new ThermalVisionPass(settings);
        pass.renderPassEvent = RenderPassEvent.BeforeRenderingPostProcessing;
    }
    
    public override void AddRenderPasses(ScriptableRenderer renderer, ref RenderingData renderingData)
    {
        if (!settings.Enabled || pass == null) return;
        
        pass.Setup(renderer.cameraColorTarget, renderer.cameraDepthTarget);
        renderer.EnqueuePass(pass);
    }
}

public class ThermalVisionPass : ScriptableRenderPass
{
    private ThermalVisionFeature.Settings settings;
    private Material thermalMaterial;
    private RenderTargetIdentifier colorTarget, depthTarget;
    private RenderTargetHandle tempHandle;

    public ThermalVisionPass(ThermalVisionFeature.Settings settings)
    {
        this.settings = settings;
        thermalMaterial = new Material(settings.ThermalShader);
        tempHandle.Init("_ThermalTemp");
    }

    public void Setup(RenderTargetIdentifier color, RenderTargetIdentifier depth)
    {
        colorTarget = color;
        depthTarget = depth;
    }

    public override void Execute(ScriptableRenderContext context, ref RenderingData renderingData)
    {
        var cmd = CommandBufferPool.Get("ThermalVision");
        
        var desc = renderingData.cameraData.cameraTargetDescriptor;
        desc.depthBufferBits = 0;
        cmd.GetTemporaryRT(tempHandle.id, desc);
        
        // 应用热成像效果
        cmd.Blit(colorTarget, tempHandle.Identifier(), thermalMaterial);
        cmd.Blit(tempHandle.Identifier(), colorTarget);
        cmd.ReleaseTemporaryRT(tempHandle.id);
        
        context.ExecuteCommandBuffer(cmd);
        CommandBufferPool.Release(cmd);
    }
}
```

---

## 三、对应的热成像 Shader

```hlsl
// ThermalVision.shader
Shader "Custom/ThermalVision"
{
    Properties
    {
        _MainTex ("Source", 2D) = "white" {}
        _ThermalGradient ("Thermal Gradient", 2D) = "white" {}
        _NoiseIntensity ("Noise", Range(0, 0.05)) = 0.01
    }
    
    SubShader
    {
        Tags { "RenderType"="Opaque" "RenderPipeline"="UniversalPipeline" }
        
        Pass
        {
            HLSLPROGRAM
            #pragma vertex vert
            #pragma fragment frag
            #include "Packages/com.unity.render-pipelines.universal/ShaderLibrary/Core.hlsl"
            
            TEXTURE2D(_MainTex);
            SAMPLER(sampler_MainTex);
            TEXTURE2D(_ThermalGradient);
            SAMPLER(sampler_ThermalGradient);
            float _NoiseIntensity;
            
            struct Attributes { float4 positionOS : POSITION; float2 uv : TEXCOORD0; };
            struct Varyings { float4 positionCS : SV_POSITION; float2 uv : TEXCOORD0; };
            
            Varyings vert(Attributes IN)
            {
                Varyings OUT;
                OUT.positionCS = TransformObjectToHClip(IN.positionOS.xyz);
                OUT.uv = IN.uv;
                return OUT;
            }
            
            float4 frag(Varyings IN) : SV_Target
            {
                float4 color = SAMPLE_TEXTURE2D(_MainTex, sampler_MainTex, IN.uv);
                
                // 计算亮度作为热量指标
                float luminance = dot(color.rgb, float3(0.299, 0.587, 0.114));
                
                // 添加噪声（模拟热成像颗粒感）
                float noise = frac(sin(dot(IN.uv + _Time.xx, float2(12.9898, 78.233))) * 43758.5453);
                luminance = saturate(luminance + (noise - 0.5) * _NoiseIntensity);
                
                // 从渐变贴图采样热成像颜色
                float4 thermalColor = SAMPLE_TEXTURE2D(_ThermalGradient, 
                    sampler_ThermalGradient, float2(luminance, 0.5));
                
                return thermalColor;
            }
            ENDHLSL
        }
    }
}
```

---

## 四、自定义 Pass 最佳实践

| 注意事项 | 说明 |
|----------|------|
| 使用 CommandBufferPool | 不要每帧 new CommandBuffer，会 GC |
| 释放临时 RT | OnCameraCleanup 中 ReleaseTemporaryRT |
| 避免 GrabPass | 性能很差，改用 Blit 到临时 RT |
| RenderPassEvent 选对 | 插入顺序不对会导致效果层序错误 |
| 多 Camera 场景 | 注意 Feature 是否对所有Camera生效 |
| 条件开关 | 低端设备禁用复杂特效 |
